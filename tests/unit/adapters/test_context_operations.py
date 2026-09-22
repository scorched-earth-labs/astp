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
Context-commitment operations (SPEC 6.0.0 §4.8, §4.9, §5.7.3) end to end
through ``InMemoryStore``, landing on the ratified ``vectors/6.0.0`` values:
the seven entries committed through the store, sealed under version 3,
reproduce the vector file's manifest and Episode root; an erasure through
the store leaves both unchanged; and the proof of record exported from the
store verifies with the package alone.
"""
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from astp.adapters.memory import InMemoryStore
from astp.core import context_operations as ops
from astp.core.context_v1 import (G41Violation, G42Violation, G43Violation, PII_LOW_ENTROPY, ContextEntryNode,
                                  compute_episode_seal_v3, context_entry_hashes, tombstone_hash)
from astp.core.proof_of_record import build_proof_of_record, verify_proof_of_record
from astp.core.seal_v2 import SegmentSealInput
from astp.core.wil import WILOperation

ROOT = Path(__file__).resolve().parents[3]
V = json.loads((ROOT / "vectors" / "6.0.0" / "context-commitment.json").read_text(encoding="utf-8"))
V5 = json.loads((ROOT / "vectors" / "5.0.0" / "seal-constructions.json").read_text(encoding="utf-8"))
EP = V["base_episode"]["episode_id"]
ENTRIES = [ContextEntryNode(**{k: v for k, v in e.items() if k != "entry_hash"}) for e in V["entries"]]
MEMBERS = [V5["structural_members"][k] for k in ("branch_point_v2", "branch_terminus_v2", "fork_point_v2",
                                                   "departure_fork_point_v2", "fork_return_v2", "merge_point_v2", "hitl_node_v2")]
SEGMENTS = [SegmentSealInput(node_id=UUID(s["node_id"]), node_type=s["node_type"], schema_version=s["schema_version"],
                             sequence_index=s["sequence_index"], content_hash=s["content_hash"], parent_node_id=UUID(s["parent_node_id"]))
            for s in V5["segments"]]


def _store(status="ACTIVE"):
    store = InMemoryStore()
    store.episodes[EP] = {"episode_id": EP, "episode_status": status, "spine_hash": V["base_episode"]["spine_root"]}
    return store


def _commit_all(store):
    # the resolving entry (#7) names #6, so #6 must be in the store first — insertion order does it
    return [ops.commit_context_entry(store, e) for e in ENTRIES]


def _seal(store):
    posture, entries = ops.context_seal_inputs(store, EP)
    return compute_episode_seal_v3(UUID(EP), SEGMENTS, capture_posture=posture, context_entries=entries,
                                   signal_content_hashes=V5["signals"], structural_member_hashes=MEMBERS)


# ── commit ────────────────────────────────────────────────────────────────────

def test_commit_writes_entries_and_ledgers_context_commit():
    store = _store()
    results = _commit_all(store)
    assert [r.entry_hash for r in results] == [e["entry_hash"] for e in V["entries"]]
    assert len(store.context_entries_of(EP)) == 7
    ops_ledgered = [w for w in store.wil_entries.values() if w["operation"] == WILOperation.CONTEXT_COMMIT.value]
    assert len(ops_ledgered) == 7 and all(w["status"] == "COMPLETE" for w in ops_ledgered)


def test_commit_refuses_duplicates_closed_episodes_and_absent_episodes():
    store = _store()
    ops.commit_context_entry(store, ENTRIES[0])
    with pytest.raises(ops.ContextOperationError, match="append-only"):
        ops.commit_context_entry(store, ENTRIES[0])
    for status in ("CLOSED", "SEALED", "ARCHIVED", "CRYSTALLIZED"):
        with pytest.raises(ops.ContextOperationError, match=status):
            ops.commit_context_entry(_store(status), ENTRIES[1])
    with pytest.raises(ops.ContextOperationError, match="does not exist"):
        ops.commit_context_entry(InMemoryStore(), ENTRIES[1])


def test_commit_enforces_g42_where_the_write_happens():
    store = _store()
    dob = next(e for e in ENTRIES if e.salted)
    plain = dob.model_copy(update={"salted": False, "content_hash": V["content_hashes_v1"]["plain_low_entropy_dob"]["hash"], "salt_ref": None})
    assert plain.pii_classification == PII_LOW_ENTROPY
    with pytest.raises(G42Violation):
        ops.commit_context_entry(store, plain)
    assert store.context_entries_of(EP) == [] and store.wil_entries == {}          # nothing written, nothing ledgered


def test_commit_validates_resolves_against_the_store():
    store = _store()
    resolving = next(e for e in ENTRIES if e.resolves)
    with pytest.raises(ops.ContextOperationError, match="resolves"):
        ops.commit_context_entry(store, resolving)                                  # target not yet in the store
    incomplete = next(e for e in ENTRIES if e.capture_state == "declared_incomplete")
    ops.commit_context_entry(store, incomplete)
    r = ops.commit_context_entry(store, resolving)
    assert r.entry_hash == V["resolves"]["resolving_entry_hash"]
    with pytest.raises(ops.ContextOperationError):
        ops.commit_context_entry(store, ENTRIES[0].model_copy(update={"entry_id": uuid4(), "resolves": resolving.entry_id}))   # resolving a resolver


def test_commit_refuses_an_entry_that_arrives_tombstoned():
    with pytest.raises(ops.ContextOperationError, match="present"):
        ops.commit_context_entry(_store(), ENTRIES[0].model_copy(update={"erasure_state": "tombstoned"}))


# ── posture and seal (G-41) ───────────────────────────────────────────────────

def test_seal_requires_a_posture_and_the_posture_is_validated():
    store = _store()
    _commit_all(store)
    with pytest.raises(G41Violation, match="capture_posture"):
        ops.context_seal_inputs(store, EP)
    with pytest.raises(G41Violation):
        ops.set_capture_posture(store, EP, "everything")
    with pytest.raises(ops.ContextOperationError):
        ops.set_capture_posture(store, str(uuid4()), "none")
    ops.set_capture_posture(store, EP, "declared_only")
    assert store.capture_posture(EP) == "declared_only"
    with pytest.raises(G41Violation, match="sealed"):
        ops.set_capture_posture(_store("SEALED"), EP, "none")


def test_entries_committed_through_the_store_seal_to_the_ratified_vectors():
    store = _store()
    _commit_all(store)
    ops.set_capture_posture(store, EP, "declared_only")
    assert ops.episode_context_manifest_hash(store, EP) == V["context_manifest_v1"]["declared_only_seven"]
    seal = _seal(store)
    assert seal.episode_root_hash == V["episode_root_v3"]["seven_entries_declared_only"]
    assert seal.spine_root == V["base_episode"]["spine_root"] and seal.context_entry_count == 7


def test_an_empty_episode_seals_with_posture_none():
    store = _store()
    ops.set_capture_posture(store, EP, "none")
    assert _seal(store).episode_root_hash == V["episode_root_v3"]["empty_manifest_posture_none"]


# ── erasure (G-43) ────────────────────────────────────────────────────────────

def test_erasure_through_the_store_leaves_every_sealed_value_unchanged():
    store = _store()
    _commit_all(store)
    ops.set_capture_posture(store, EP, "declared_only")
    before = _seal(store)
    er = V["erasure_v1"]; t = er["tombstone"]
    from datetime import datetime
    r = ops.erase_context_entry(store, er["entry_id"], erasure_authority=t["erasure_authority"], erasure_request_id=t["erasure_request_id"],
                                erased_by=t["erased_by"], content_and_salt_destroyed=True,
                                erased_at=datetime.fromisoformat(t["erased_at"]), tombstone_id=UUID(t["tombstone_id"]))
    assert r.entry_hash == er["entry_hash_unchanged"] and r.tombstone_hash == t["tombstone_hash"]
    stored = store.context_entry(er["entry_id"])
    assert (stored["content_ref"], stored["salt_ref"], stored["erasure_state"]) == (None, None, "tombstoned")
    assert stored["salted"] is True and stored["content_hash"] == V["content_hashes_v1"]["salted_low_entropy_dob"]["hash"]   # the sealed bit and commitment are untouched
    codicil = store.codicils[str(r.codicil_id)]
    assert json.loads(codicil["content"])["tombstone_hash"] == t["tombstone_hash"] and codicil["author"] == t["erased_by"]
    assert [w for w in store.wil_entries.values() if w["operation"] == WILOperation.CODICIL_APPEND.value]
    after = _seal(store)
    assert after.context_manifest_hash == before.context_manifest_hash and after.episode_root_hash == before.episode_root_hash == er["episode_root_v3_unchanged"]


def test_erasure_refusals():
    store = _store()
    _commit_all(store)
    eid = V["erasure_v1"]["entry_id"]
    common = dict(erasure_authority="GDPR-Art17", erasure_request_id="dsr-1", erased_by="privacy-officer")
    with pytest.raises(G43Violation, match="destroyed"):
        ops.erase_context_entry(store, eid, content_and_salt_destroyed=False, **common)
    with pytest.raises(ops.ContextOperationError):
        ops.erase_context_entry(store, str(uuid4()), content_and_salt_destroyed=True, **common)
    ops.erase_context_entry(store, eid, content_and_salt_destroyed=True, **common)
    with pytest.raises(G43Violation, match="already"):
        ops.erase_context_entry(store, eid, content_and_salt_destroyed=True, **common)


# ── proof of record, version 3 ────────────────────────────────────────────────

def _proof(store, profile="full", **override):
    posture, entries = ops.context_seal_inputs(store, EP)
    seal = _seal(store)
    kw = dict(episode_id=EP, profile=profile, spine_algorithm_version=3, ordering_version=2, sealed_at="2026-09-22T23:00:00+00:00",
              closed_at="2026-09-22T23:00:00+00:00", spine_root=seal.spine_root, signal_manifest_hash=seal.signal_manifest_hash,
              exclusion_hash=seal.exclusion_hash, structural_manifest_hash=seal.structural_manifest_hash,
              context_manifest_hash=seal.context_manifest_hash, capture_posture=posture, context_entry_count=len(entries),
              episode_root_hash=seal.episode_root_hash, leaf_count=seal.leaf_count,
              segments=[json.loads(s.model_dump_json()) for s in SEGMENTS], signal_content_hashes=V5["signals"],
              excluded_content_hashes=[], structural_member_hashes=MEMBERS, context_entries=store.context_entries_of(EP))
    kw.update(override)
    return build_proof_of_record(**kw)


def test_version_3_proof_of_record_reproduces_the_sixth_field():
    store = _store(); _commit_all(store); ops.set_capture_posture(store, EP, "declared_only")
    doc = _proof(store)
    assert doc["seal"]["hash_version"] == 2 and doc["seal"]["context_manifest_hash"] == V["context_manifest_v1"]["declared_only_seven"]
    r = verify_proof_of_record(json.loads(json.dumps(doc)))
    assert r.ok and "context_manifest_hash reproduced" in r.checks and "episode_root_hash reproduced" in r.checks, r


def test_version_3_proof_still_verifies_after_erasure_and_fails_on_tampering():
    store = _store(); _commit_all(store); ops.set_capture_posture(store, EP, "declared_only")
    ops.erase_context_entry(store, V["erasure_v1"]["entry_id"], erasure_authority="GDPR-Art17", erasure_request_id="dsr-1",
                            erased_by="privacy-officer", content_and_salt_destroyed=True)
    doc = _proof(store)
    assert verify_proof_of_record(doc).ok
    bad = json.loads(json.dumps(doc)); bad["stored"]["context_entries"].pop()
    r = verify_proof_of_record(bad)
    assert not r.ok and any("context_manifest_hash differs" in f for f in r.failures) and any("context_entry_count" in f for f in r.failures)
    bad = json.loads(json.dumps(doc)); bad["stored"]["context_entries"][0]["provided_to"] = "someone-else"
    assert not verify_proof_of_record(bad).ok
    bad = json.loads(json.dumps(doc)); bad["seal"]["capture_posture"] = "all_external"
    assert not verify_proof_of_record(bad).ok
    bad = json.loads(json.dumps(doc)); bad["seal"]["capture_posture"] = None
    assert any("G-41" in f for f in verify_proof_of_record(bad).failures)


def test_attested_profile_withholds_the_entry_list():
    store = _store(); _commit_all(store); ops.set_capture_posture(store, EP, "declared_only")
    r = verify_proof_of_record(_proof(store, profile="attested"))
    assert r.ok and any("context_manifest_hash membership" in n for n in r.not_checked)
