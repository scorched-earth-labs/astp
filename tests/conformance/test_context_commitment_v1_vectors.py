# Copyright 2026 Scorched Earth Labs, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
SPEC 6.0.0 draft context-commitment constructions, checked against
``vectors/6.0.0-draft/``. **Draft: not ratified.**

Two checks per value. The library must produce it — and so must the few lines
of ``hashlib`` below, written from the draft text alone, which import nothing
from ``astp``. Each CM-nn of the draft's §13 conformance sketch is one test.
"""

import hashlib
import json
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from astp.core import context_v1 as X
from astp.core import seal_v2
from astp.core.seal_v2 import SegmentSealInput, reproduce_episode_root

ROOT = Path(__file__).resolve().parents[2]
VECTORS = json.loads((ROOT / "vectors" / "6.0.0-draft" / "context-commitment.json").read_text(encoding="utf-8"))
BASE50 = json.loads((ROOT / "vectors" / "5.0.0" / "seal-constructions.json").read_text(encoding="utf-8"))
B = VECTORS["base_episode"]
EPISODE = UUID(B["episode_id"])
ENTRIES = VECTORS["entries"]
HASHES = [e["entry_hash"] for e in ENTRIES]
POSTURE = "declared_only"


# ── an independent implementation, from the draft text ────────────────────────

def _sha3(b: bytes) -> bytes:
    return hashlib.sha3_256(b).digest()


def _u32(n): return n.to_bytes(4, "big")
def _null(): return b"\x00"
def _bytes(b): return b"\x01" + _u32(len(b)) + b
def _string(s): d = unicodedata.normalize("NFC", s).encode("utf-8"); return b"\x02" + _u32(len(d)) + d
def _uint(n): return b"\x03" + n.to_bytes(8, "big")
def _uuid(u): return b"\x04" + UUID(u).bytes
def _ts(iso):
    t = datetime.fromisoformat(iso)
    ms = int((t - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds() * 1000)
    return b"\x05" + ms.to_bytes(8, "big")
def _hash(h): return b"\x06" + bytes.fromhex(h)
def _bool(v): return b"\x08" + (b"\x01" if v else b"\x00")
def _opt(enc, v): return _null() if v is None else enc(v)


def ref_content_hash(content: bytes, salt: bytes = None) -> str:
    if salt is None:
        return _sha3(b"CONTEXT_CONTENT:v1:" + _bytes(content)).hex()
    return _sha3(b"CONTEXT_CONTENT_SALTED:v1:" + _bytes(salt) + _bytes(content)).hex()


def ref_entry_hash(e: dict, resolves_entry_hash: str = None) -> str:
    return _sha3(b"CONTEXT_ENTRY:v1:" + _uuid(e["entry_id"]) + _uuid(e["episode_id"]) + _string(e["entry_type"])
                 + _string(e["provided_to"]) + _ts(e["provided_at"]) + _opt(_uint, e["provided_before_sequence_index"])
                 + _string(e["capture_state"]) + _opt(_hash, e["content_hash"]) + _bool(e["salted"])
                 + _opt(_string, e["verifiability_at_seal"]) + _opt(_string, e["media_type"])
                 + _opt(_hash, e["source_version_hash"]) + _opt(_hash, resolves_entry_hash)).hex()


def ref_entry_hashes(entries) -> dict:
    by_id = {e["entry_id"]: e for e in entries}
    out = {}
    for e in entries:
        target = by_id[e["resolves"]] if e["resolves"] else None
        out[e["entry_id"]] = ref_entry_hash(e, ref_entry_hash(target) if target else None)
    return out


def ref_tree(leaf_hex) -> str:
    level = [_sha3(b"TREE_LEAF:v2:" + bytes.fromhex(x)) for x in leaf_hex]
    while len(level) > 1:
        level = [_sha3(b"TREE_NODE:v2:" + level[i] + level[i + 1]) if i + 1 < len(level) else level[i]
                 for i in range(0, len(level), 2)]
    return level[0].hex()


def ref_manifest(posture: str, entry_hashes) -> str:
    leaves = [h.hex() for h in sorted(bytes.fromhex(x) for x in entry_hashes)]
    root = ref_tree(leaves) if leaves else None
    return _sha3(b"CONTEXT_MANIFEST:v1:" + _string(posture) + _uint(len(leaves)) + _opt(_hash, root)).hex()


def ref_root_v3(ep, spine, sig, st, ex, cm) -> str:
    return _sha3(b"EPISODE_ROOT:v3:" + _uuid(ep) + _hash(spine) + _hash(sig) + _hash(st) + _hash(ex) + _hash(cm)).hex()


def ref_tombstone(t: dict) -> str:
    return _sha3(b"ERASURE_TOMBSTONE:v1:" + _uuid(t["tombstone_id"]) + _uuid(t["episode_id"]) + _uuid(t["entry_id"])
                 + _hash(t["entry_hash"]) + _ts(t["erased_at"]) + _string(t["erasure_authority"])
                 + _string(t["erasure_request_id"]) + _string(t["erased_by"])).hex()


def ref_verify_proof(p: dict) -> bool:
    n, pos, k = p["leaf_count"], p["leaf_index"], 0
    if not 0 <= pos < n:
        return False
    cur = _sha3(b"TREE_LEAF:v2:" + bytes.fromhex(p["entry_hash"]))
    sib = [bytes.fromhex(h) for h in p["siblings"]]
    while n > 1:
        if not (pos % 2 == 0 and pos == n - 1):
            if k >= len(sib):
                return False
            cur = _sha3(b"TREE_NODE:v2:" + (cur + sib[k] if pos % 2 == 0 else sib[k] + cur)); k += 1
        pos, n = pos // 2, (n + 1) // 2
    return k == len(sib) and cur.hex() == p["context_tree_root"]


def _node(e: dict) -> X.ContextEntryNode:
    return X.ContextEntryNode(**{k: v for k, v in e.items() if k != "entry_hash"})


def _segments():
    return [SegmentSealInput(node_id=UUID(s["node_id"]), node_type=s["node_type"], schema_version=s["schema_version"],
                             sequence_index=s["sequence_index"], content_hash=s["content_hash"], parent_node_id=UUID(s["parent_node_id"]))
            for s in BASE50["segments"]]


def _members():
    return [BASE50["structural_members"][k] for k in ("branch_point_v2", "branch_terminus_v2", "fork_point_v2",
                                                       "departure_fork_point_v2", "fork_return_v2", "merge_point_v2", "hitl_node_v2")]


def _seal(entries, posture=POSTURE):
    return X.compute_episode_seal_v3(EPISODE, _segments(), capture_posture=posture, context_entries=entries,
                                     signal_content_hashes=BASE50["signals"], structural_member_hashes=_members())


# ── registry ───────────────────────────────────────────────────────────────────

def test_new_prefixes_are_distinct_and_none_is_a_prefix_of_an_existing_one():
    new = [v for k, v in vars(X).items() if k.isupper() and isinstance(v, bytes)]
    assert set(new) == {b"CONTEXT_ENTRY:v1:", b"CONTEXT_CONTENT:v1:", b"CONTEXT_CONTENT_SALTED:v1:",
                        b"CONTEXT_MANIFEST:v1:", b"EPISODE_ROOT:v3:", b"ERASURE_TOMBSTONE:v1:"}
    existing = [v for k, v in vars(seal_v2).items() if k.isupper() and isinstance(v, bytes)]
    existing += [b"LEAF_HASH:v2:", b"TREE_LEAF:v2:", b"TREE_NODE:v2:"]
    every = new + existing
    assert len(every) == len(set(every))
    assert not any(a != b and a.startswith(b) for a in every for b in every)


# ── content commitment (§5.3) ──────────────────────────────────────────────────

def test_content_hashes_plain_and_salted():
    c = VECTORS["content_hashes_v1"]
    pdf = bytes.fromhex(c["plain_pdf"]["content_hex"])
    assert X.compute_context_content_hash_v1(pdf) == c["plain_pdf"]["hash"] == ref_content_hash(pdf)
    dob = c["plain_low_entropy_dob"]["content_utf8"].encode()
    salt = bytes.fromhex(c["salted_low_entropy_dob"]["salt_hex"])
    assert X.compute_context_content_hash_v1(dob) == c["plain_low_entropy_dob"]["hash"] == ref_content_hash(dob)
    assert X.compute_context_content_hash_v1(dob, salt) == c["salted_low_entropy_dob"]["hash"] == ref_content_hash(dob, salt)
    assert len(salt) == 32
    with pytest.raises(ValueError):
        X.compute_context_content_hash_v1(dob, b"short")


def test_salt_and_content_boundaries_cannot_be_moved():
    a = X.compute_context_content_hash_v1(b"bc", b"a" * 32)
    b = X.compute_context_content_hash_v1(b"c", b"a" * 31 + b"b")
    assert a != b


# ── entry hash (§6.1) ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("e", ENTRIES, ids=lambda e: e["entry_type"] + ":" + e["capture_state"] + (":resolves" if e["resolves"] else ""))
def test_entry_hash_v1(e):
    ref = ref_entry_hashes(ENTRIES)
    got = dict(zip([x["entry_id"] for x in ENTRIES], X.context_entry_hashes([_node(x) for x in ENTRIES])))
    assert got[e["entry_id"]] == e["entry_hash"] == ref[e["entry_id"]]


def test_cm02_preimage_fields_bind_and_side_channel_fields_do_not():
    e = next(x for x in ENTRIES if x["entry_type"] == "attachment")
    base = _node(e)
    for field, other in [("entry_id", UUID(int=9)), ("episode_id", UUID(int=8)), ("entry_type", "external"),
                         ("provided_to", "agent-ω"), ("provided_at", base.provided_at.replace(second=59)),
                         ("provided_before_sequence_index", None), ("provided_before_sequence_index", 4),
                         ("content_hash", HASHES[1]), ("salted", True), ("verifiability_at_seal", "attested"),
                         ("media_type", None), ("media_type", "image/png"), ("source_version_hash", HASHES[2])]:
        assert X.context_entry_hash(base.model_copy(update={field: other})) != e["entry_hash"], field
    for field, other in [("source_ref", "elsewhere"), ("content_ref", None), ("salt_ref", "salt://x"),
                         ("erasure_state", "tombstoned"), ("pii_classification", X.PII_LOW_ENTROPY)]:
        assert X.context_entry_hash(base.model_copy(update={field: other})) == e["entry_hash"], field
    assert VECTORS["entry_hash_v1"]["preimage_field_order"][0] == "entry_id UUID"


def test_declared_incomplete_entry_carries_nulls_and_nothing_else():
    e = next(x for x in ENTRIES if x["capture_state"] == "declared_incomplete")
    assert e["content_hash"] is None and e["salted"] is False and e["verifiability_at_seal"] is None
    with pytest.raises(ValueError):
        X.context_entry_hash(_node(e).model_copy(update={"content_hash": HASHES[0]}))
    with pytest.raises(ValueError):
        X.context_entry_hash(_node(ENTRIES[0]).model_copy(update={"verifiability_at_seal": None}))


# ── manifest (§6.2, §6.3) ─────────────────────────────────────────────────────

def test_context_tree_root_is_over_sorted_leaves():
    t = VECTORS["context_tree_v1"]
    leaves = X.sort_entry_hashes(HASHES)
    assert leaves == [h.hex() for h in sorted(bytes.fromhex(x) for x in HASHES)]
    assert X.compute_context_tree_root_v1(HASHES) == t["root_seven_entries"] == ref_tree(leaves)
    by_hash = {e["entry_hash"]: e["entry_id"] for e in ENTRIES}
    assert [by_hash[h] for h in leaves] == t["sorted_leaf_order_entry_ids"]
    with pytest.raises(ValueError):
        X.compute_context_tree_root_v1([])


def test_cm03_manifest_is_order_independent_and_removal_and_posture_change_it():
    m = VECTORS["context_manifest_v1"]
    assert X.compute_context_manifest_hash_v1(POSTURE, HASHES) == m["declared_only_seven"] == ref_manifest(POSTURE, HASHES)
    assert X.compute_context_manifest_hash_v1(POSTURE, list(reversed(HASHES))) == m["declared_only_seven_entries_in_reverse_insertion_order"] == m["declared_only_seven"]
    attested = next(e["entry_hash"] for e in ENTRIES if e["verifiability_at_seal"] == "attested")
    without = [h for h in HASHES if h != attested]
    assert X.compute_context_manifest_hash_v1(POSTURE, without) == m["declared_only_without_the_attested_retrieval"] == ref_manifest(POSTURE, without) != m["declared_only_seven"]
    assert X.compute_context_manifest_hash_v1("all_external", HASHES) == m["all_external_seven"] == ref_manifest("all_external", HASHES) != m["declared_only_seven"]
    with pytest.raises(X.G41Violation):
        X.compute_context_manifest_hash_v1("everything", HASHES)


def test_cm01_empty_manifest_is_defined_and_seals_under_version_3():
    m = VECTORS["context_manifest_v1"]
    assert X.compute_context_manifest_hash_v1("none", []) == m["empty_none"] == ref_manifest("none", [])
    assert X.compute_context_manifest_hash_v1("declared_only", []) == m["empty_declared_only"] == ref_manifest("declared_only", []) != m["empty_none"]
    seal = _seal([], posture="none")
    assert seal.context_entry_count == 0 and seal.context_manifest_hash == m["empty_none"]
    assert seal.episode_root_hash == VECTORS["episode_root_v3"]["empty_manifest_posture_none"] \
        == ref_root_v3(B["episode_id"], B["spine_root"], B["signal_manifest_hash"], B["structural_manifest_hash"], B["exclusion_hash"], m["empty_none"])
    assert reproduce_episode_root(spine_algorithm_version=3, episode_id=EPISODE, spine_root=B["spine_root"],
                                  signal_content_hashes=BASE50["signals"], excluded_content_hashes=[],
                                  structural_member_hashes=_members(), capture_posture="none", context_entry_hashes=[]) == seal.episode_root_hash


# ── Episode root version 3 (§7) ────────────────────────────────────────────────

def test_episode_root_v3_is_the_version_2_root_plus_a_sixth_field():
    r = VECTORS["episode_root_v3"]
    cm = VECTORS["context_manifest_v1"]["declared_only_seven"]
    want = r["seven_entries_declared_only"]
    assert X.compute_episode_root_hash_v3(EPISODE, B["spine_root"], B["signal_manifest_hash"], B["structural_manifest_hash"], B["exclusion_hash"], cm) \
        == want == ref_root_v3(B["episode_id"], B["spine_root"], B["signal_manifest_hash"], B["structural_manifest_hash"], B["exclusion_hash"], cm)
    seal = _seal([_node(e) for e in ENTRIES])
    assert seal.episode_root_hash == want and seal.spine_algorithm_version == 3
    assert (seal.spine_root, seal.signal_manifest_hash, seal.structural_manifest_hash, seal.exclusion_hash) \
        == (B["spine_root"], B["signal_manifest_hash"], B["structural_manifest_hash"], B["exclusion_hash"])
    assert json.loads(seal.model_dump_json()) == r["seal_record"]
    assert reproduce_episode_root(spine_algorithm_version=3, episode_id=str(EPISODE), spine_root=B["spine_root"],
                                  signal_content_hashes=BASE50["signals"], excluded_content_hashes=[], structural_member_hashes=_members(),
                                  capture_posture=POSTURE, context_entry_hashes=HASHES) == want
    with pytest.raises(ValueError, match="capture_posture"):
        reproduce_episode_root(spine_algorithm_version=3, episode_id=EPISODE, spine_root=B["spine_root"],
                               signal_content_hashes=[], excluded_content_hashes=[])


def test_cm10_a_version_2_seal_is_unchanged_by_context_entries():
    c = VECTORS["cm10_version_2_seal_is_unchanged_by_context_entries"]
    v2 = seal_v2.compute_episode_seal_v2(EPISODE, _segments(), signal_content_hashes=BASE50["signals"], structural_member_hashes=_members())
    assert v2.episode_root_hash == c["episode_root_v2_of_the_same_episode"] == BASE50["episode_root_v2"]["hash"] == B["episode_root_v2"]
    assert c["equals_5.0.0_vector"] is True
    assert v2.episode_root_hash != VECTORS["episode_root_v3"]["seven_entries_declared_only"]
    assert reproduce_episode_root(spine_algorithm_version=2, episode_id=EPISODE, spine_root=B["spine_root"],
                                  signal_content_hashes=BASE50["signals"], excluded_content_hashes=[],
                                  structural_member_hashes=_members()) == v2.episode_root_hash


# ── inclusion proofs (§10; CM-04) ─────────────────────────────────────────────

def test_cm04_one_entry_is_proven_without_the_others():
    p = VECTORS["inclusion_proof_v1"]
    entry_hash = next(e["entry_hash"] for e in ENTRIES if e["entry_id"] == p["entry_id"])
    proof = X.generate_context_inclusion_proof_v1(HASHES, entry_hash)
    assert proof.model_dump() == p["proof"]
    assert X.verify_context_inclusion_proof_v1(proof, p["capture_posture"], p["entry_count"], p["context_manifest_hash"])
    assert ref_verify_proof(p["proof"])
    assert ref_manifest(p["capture_posture"], HASHES) == p["context_manifest_hash"]
    assert ref_root_v3(B["episode_id"], B["spine_root"], B["signal_manifest_hash"], B["structural_manifest_hash"], B["exclusion_hash"], p["context_manifest_hash"]) == p["episode_root_v3"]
    for j in range(p["entry_count"]):
        if j != proof.leaf_index:
            assert not X.verify_context_inclusion_proof_v1(proof.model_copy(update={"leaf_index": j}), POSTURE, 7, p["context_manifest_hash"])
    assert not X.verify_context_inclusion_proof_v1(proof, "all_external", 7, p["context_manifest_hash"])
    assert not X.verify_context_inclusion_proof_v1(proof, POSTURE, 6, p["context_manifest_hash"])
    with pytest.raises(ValueError):
        X.generate_context_inclusion_proof_v1(HASHES, hashlib.sha3_256(b"absent").hexdigest())


# ── resolves (§5.5; CM-05) ────────────────────────────────────────────────────

def test_cm05_a_resolving_entry_binds_the_resolved_entry_and_the_resolved_entry_is_unchanged():
    r = VECTORS["resolves"]
    inc = next(e for e in ENTRIES if e["entry_id"] == r["declared_incomplete_entry_id"])
    res = next(e for e in ENTRIES if e["entry_id"] == r["resolving_entry_id"])
    assert res["resolves"] == inc["entry_id"]
    assert X.context_entry_hash(_node(inc)) == r["declared_incomplete_entry_hash"] == ref_entry_hash(inc)
    assert X.context_entry_hash(_node(res), r["declared_incomplete_entry_hash"]) == r["resolving_entry_hash"] == ref_entry_hash(res, r["declared_incomplete_entry_hash"])
    assert X.context_entry_hash(_node(res), HASHES[0]) != r["resolving_entry_hash"]
    with pytest.raises(ValueError):
        X.context_entry_hash(_node(res))
    with pytest.raises(ValueError):
        X.context_entry_hashes([_node(res)])                               # resolves an entry not in the set
    with pytest.raises(ValueError):
        X.context_entry_hashes([_node(res), _node(inc).model_copy(update={"capture_state": "captured", "content_hash": HASHES[0], "verifiability_at_seal": "attested"})])


# ── erasure (§8; CM-06, CM-07) ────────────────────────────────────────────────

def test_cm06_erasure_leaves_every_sealed_value_unchanged_and_is_witnessed():
    er = VECTORS["erasure_v1"]
    e = _node(next(x for x in ENTRIES if x["entry_id"] == er["entry_id"]))
    t = X.ErasureTombstone(**{k: v for k, v in er["tombstone"].items() if k != "tombstone_hash"})
    assert X.tombstone_hash(t) == er["tombstone"]["tombstone_hash"] == ref_tombstone(er["tombstone"])
    assert t.entry_hash == er["entry_hash_unchanged"] == X.context_entry_hash(e)
    erased = X.apply_erasure(e, t)
    assert (erased.content_ref, erased.salt_ref, erased.erasure_state) == (None, None, "tombstoned") == tuple(er["after"].values())
    assert (e.content_ref, e.salt_ref, e.erasure_state) == tuple(er["before"].values())
    assert X.context_entry_hash(erased) == er["entry_hash_unchanged"]
    assert (erased.content_hash, erased.salted, erased.verifiability_at_seal) == (e.content_hash, True, "verifiable")
    after = [erased if x["entry_id"] == er["entry_id"] else _node(x) for x in ENTRIES]
    seal = _seal(after)
    assert seal.context_manifest_hash == er["context_manifest_hash_unchanged"] == VECTORS["context_manifest_v1"]["declared_only_seven"]
    assert seal.episode_root_hash == er["episode_root_v3_unchanged"] == VECTORS["episode_root_v3"]["seven_entries_declared_only"]
    with pytest.raises(X.G43Violation):
        X.apply_erasure(erased, t)                                          # already tombstoned
    with pytest.raises(X.G43Violation):
        X.apply_erasure(_node(ENTRIES[0]), t)                               # tombstone names another entry


def test_cm07_a_salted_commitment_does_not_confirm_a_guess_once_the_salt_is_gone():
    c = VECTORS["content_hashes_v1"]
    guess = c["plain_low_entropy_dob"]["content_utf8"].encode()
    assert X.compute_context_content_hash_v1(guess) == c["plain_low_entropy_dob"]["hash"]           # plain: the guess is confirmed
    salted = c["salted_low_entropy_dob"]["hash"]
    assert X.compute_context_content_hash_v1(guess) != salted                                        # without the salt: nothing
    assert X.compute_context_content_hash_v1(guess, b"\x00" * 32) != salted                          # a wrong salt: nothing
    assert X.compute_context_content_hash_v1(guess, bytes.fromhex(c["salted_low_entropy_dob"]["salt_hex"])) == salted   # verification needs the salt
    # brute force over the whole low-entropy space with the salt destroyed confirms nothing
    space = [f"1979-03-{d:02d}".encode() for d in range(1, 32)]
    assert not any(X.compute_context_content_hash_v1(g) == salted for g in space)


# ── external entries (§5.4; CM-08) ────────────────────────────────────────────

def test_cm08_an_external_entry_verifies_without_a_fetch():
    x = VECTORS["external_entry_provenance_is_outside_the_preimage"]
    e = _node(next(y for y in ENTRIES if y["entry_id"] == x["entry_id"]))
    assert e.entry_type == "external" and e.source_version_hash is None
    assert X.context_entry_hash(e) == x["entry_hash"] == x["entry_hash_after"]
    assert X.context_entry_hash(e.model_copy(update={"source_ref": x["source_ref_changed_to"]})) == x["entry_hash"]


# ── governance at the seal (G-41, G-42; CM-09) ────────────────────────────────

def test_cm09_safe_only_together_g42_is_enforced_at_the_seal():
    dob = next(x for x in ENTRIES if x["salted"])
    plain_dob = _node(dob).model_copy(update={"salted": False, "content_hash": VECTORS["content_hashes_v1"]["plain_low_entropy_dob"]["hash"],
                                              "salt_ref": None})
    assert plain_dob.pii_classification == X.PII_LOW_ENTROPY
    with pytest.raises(X.G42Violation):
        _seal([plain_dob])
    _seal([plain_dob.model_copy(update={"pii_classification": None})])     # the classifier's call; the protocol cannot see entropy


def test_g41_posture_is_required_and_an_undeclared_gap_blocks_the_seal():
    with pytest.raises(X.G41Violation):
        X.compute_episode_seal_v3(EPISODE, _segments(), capture_posture=None, signal_content_hashes=BASE50["signals"], structural_member_hashes=_members())   # type: ignore[arg-type]
    pending = _node(ENTRIES[0]).model_copy(update={"capture_state": "pending"})
    with pytest.raises(X.G41Violation):
        _seal([pending])


# ── the file ──────────────────────────────────────────────────────────────────

def test_vector_file_is_current():
    import subprocess, sys

    gen = ROOT / "vectors" / "6.0.0-draft" / "generate.py"
    assert subprocess.run([sys.executable, str(gen), "--check"]).returncode == 0, "run vectors/6.0.0-draft/generate.py"


def test_status_says_draft():
    assert VECTORS["status"].startswith("DRAFT")
