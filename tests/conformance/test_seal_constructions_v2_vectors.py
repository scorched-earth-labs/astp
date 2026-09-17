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
Draft SPEC 5.0.0 seal constructions, checked against ``vectors/5.0.0-draft/``.

Two checks per value. The library must produce it — and so must the few lines of
``hashlib`` below, written from the draft text alone, which import nothing from
``astp``. The vector file is language-neutral; a second implementation needs the
JSON and the draft, not this package.
"""

import hashlib
import json
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from astp.core import seal_v2
from astp.protocol import encoding
from astp.protocol.leaf_hash import compute_leaf_hash_v2
from astp.protocol.merkle import compute_merkle_root_v2

VECTORS = json.loads(
    (Path(__file__).resolve().parents[2] / "vectors" / "5.0.0-draft" / "seal-constructions.json").read_text(encoding="utf-8")
)
EPISODE = UUID(VECTORS["episode_id"])
SEGMENTS = VECTORS["segments"]
LEAVES = [s["leaf_hash_v2"] for s in SEGMENTS]


# ── an independent implementation, from the draft text ─────────────────────────

def _sha3(b: bytes) -> bytes:
    return hashlib.sha3_256(b).digest()


def _u32(n): return n.to_bytes(4, "big")
def _null(): return b"\x00"
def _string(s): d = unicodedata.normalize("NFC", s).encode("utf-8"); return b"\x02" + _u32(len(d)) + d
def _uint(n): return b"\x03" + n.to_bytes(8, "big")
def _uuid(u): return b"\x04" + UUID(u).bytes
def _hash(h): return b"\x06" + bytes.fromhex(h)


def ref_leaf_hash(s) -> str:
    return _sha3(b"LEAF_HASH:v2:" + _uuid(s["node_id"]) + _string(s["node_type"]) + _string(s["schema_version"])
                 + _uint(s["sequence_index"]) + _hash(s["content_hash"]) + _uuid(s["parent_node_id"])).hex()


def ref_tree(leaf_hex) -> str:
    level = [_sha3(b"TREE_LEAF:v2:" + bytes.fromhex(x)) for x in leaf_hex]
    while len(level) > 1:
        level = [_sha3(b"TREE_NODE:v2:" + level[i] + level[i + 1]) if i + 1 < len(level) else level[i]
                 for i in range(0, len(level), 2)]
    return level[0].hex()


def ref_set(prefix: bytes, members) -> str:
    ms = sorted({bytes.fromhex(m) for m in members})
    return _sha3(prefix + _u32(len(ms)) + b"".join(ms)).hex()


# ── field encoding ─────────────────────────────────────────────────────────────

def test_field_encoding_bytes():
    fe = VECTORS["field_encoding"]
    assert encoding.encode_field(encoding.STRING, None).hex() == fe["NULL"] == "00"
    assert encoding.encode_field(encoding.BYTES, b"\x01\x02").hex() == fe["BYTES_0x0102"]
    assert encoding.encode_field(encoding.STRING, "segment").hex() == fe["STRING_segment"] == _string("segment").hex()
    assert encoding.encode_field(encoding.UINT, 6).hex() == fe["UINT_6"] == _uint(6).hex()
    assert encoding.encode_field(encoding.UUID_, EPISODE).hex() == fe["UUID_episode"]
    assert encoding.encode_field(encoding.HASH, SEGMENTS[0]["content_hash"]).hex() == fe["HASH_of_leaf-0"]


def test_strings_are_nfc_normalized():
    composed, decomposed = VECTORS["field_encoding"]["STRING_nfc_e_acute_composed_equals_decomposed"]
    assert composed == decomposed == encoding.encode_field(encoding.STRING, "é").hex()


def test_timestamps_are_utc_milliseconds_and_naive_is_refused():
    t = datetime(2026, 1, 1, 0, 0, 0, 123000, tzinfo=timezone.utc)
    fe = VECTORS["field_encoding"]
    assert encoding.encode_field(encoding.TIMESTAMP, t).hex() == fe["TIMESTAMP_2026-01-01T00:00:00.123Z"]
    assert encoding.encode_field(encoding.TIMESTAMP, t.astimezone(timezone(timedelta(hours=-8)))).hex() \
        == fe["TIMESTAMP_same_instant_at_-08:00"] == fe["TIMESTAMP_2026-01-01T00:00:00.123Z"]
    with pytest.raises(ValueError, match="naive"):
        encoding.encode_field(encoding.TIMESTAMP, datetime(2026, 1, 1))


def test_a_number_and_its_text_do_not_collide():
    assert encoding.encode_field(encoding.UINT, 75) != encoding.encode_field(encoding.STRING, "75")


def test_field_boundaries_cannot_be_moved():
    # the 4.x colon-joined preimages hash ("obj:alice","bob") and ("obj","alice:bob") identically
    a = encoding.hash_fields(b"X:", [(encoding.STRING, "obj:alice"), (encoding.STRING, "bob")])
    b = encoding.hash_fields(b"X:", [(encoding.STRING, "obj"), (encoding.STRING, "alice:bob")])
    assert a != b


def test_absent_parent_is_not_the_nil_uuid():
    s = SEGMENTS[0]
    args = (UUID(s["node_id"]), s["node_type"], s["schema_version"], s["sequence_index"], s["content_hash"])
    assert compute_leaf_hash_v2(*args, None) != compute_leaf_hash_v2(*args, UUID(int=0))


# ── leaf hash, tree, spine ─────────────────────────────────────────────────────

@pytest.mark.parametrize("s", SEGMENTS, ids=lambda s: f"seq{s['sequence_index']}")
def test_leaf_hash_v2(s):
    got = compute_leaf_hash_v2(UUID(s["node_id"]), s["node_type"], s["schema_version"], s["sequence_index"],
                               s["content_hash"], UUID(s["parent_node_id"]))
    assert got == s["leaf_hash_v2"] == ref_leaf_hash(s)


def test_leaf_hash_binds_identity_position_and_parent():
    s = SEGMENTS[3]
    base = dict(node_id=UUID(s["node_id"]), node_type=s["node_type"], schema_version=s["schema_version"],
                sequence_index=s["sequence_index"], content_hash=s["content_hash"], parent_node_id=EPISODE)
    for field, other in [("node_id", UUID(int=9)), ("node_type", "signal"), ("schema_version", "9.9.9"),
                         ("sequence_index", 4), ("content_hash", SEGMENTS[4]["content_hash"]), ("parent_node_id", UUID(int=7))]:
        assert compute_leaf_hash_v2(**{**base, field: other}) != s["leaf_hash_v2"], field


@pytest.mark.parametrize("n", [1, 2, 3, 7])
def test_spine_root_sav2(n):
    expected = VECTORS["spine_root_sav2"][str(n)]
    assert seal_v2.compute_spine_root_sav2(LEAVES[:n]) == expected == ref_tree(LEAVES[:n]) == compute_merkle_root_v2(LEAVES[:n])


@pytest.mark.parametrize("n", range(1, 40))
def test_tree_matches_the_independent_implementation_across_sizes(n):
    leaves = [hashlib.sha3_256(f"x{i}".encode()).hexdigest() for i in range(n)]
    assert compute_merkle_root_v2(leaves) == ref_tree(leaves)


def test_empty_leaf_list_has_no_root():
    with pytest.raises(ValueError):
        compute_merkle_root_v2([])


def test_same_content_in_two_episodes_gives_different_spine_roots():
    # the property the Episode-identifier leaf used to supply: each leaf binds its parent
    other = [compute_leaf_hash_v2(UUID(s["node_id"]), s["node_type"], s["schema_version"], s["sequence_index"],
                                  s["content_hash"], UUID(int=42)) for s in SEGMENTS]
    assert seal_v2.compute_spine_root_sav2(other) != VECTORS["spine_root_sav2"]["7"]


# ── sets and the Episode root ──────────────────────────────────────────────────

def test_signal_manifest_and_exclusion():
    sig = VECTORS["signals"]
    want = VECTORS["signal_manifest_v2"]
    assert seal_v2.compute_signal_manifest_hash_v2(sig) == want["five_members_any_order"] == ref_set(b"SIGNAL_MANIFEST:v2:", sig)
    assert seal_v2.compute_signal_manifest_hash_v2(list(reversed(sig)) + sig[:2]) == want["five_members_any_order"]
    assert seal_v2.compute_signal_manifest_hash_v2([]) == want["empty"] == ref_set(b"SIGNAL_MANIFEST:v2:", [])
    assert seal_v2.compute_exclusion_hash_v2([]) == VECTORS["exclusion_v2"]["empty"] != want["empty"]


def _members():
    t = datetime.fromisoformat(VECTORS["structural_members"]["timestamp"])
    u = lambda i: UUID(f"00000000-0000-4000-8000-{i:012x}")
    root3 = VECTORS["spine_root_sav2"]["3"]
    bp = seal_v2.compute_branch_point_hash_v2(u(0x100), EPISODE, u(0x101), u(3), root3, "EXPLORATORY", "EXPLICIT", t, None)
    bt = seal_v2.compute_branch_terminus_hash_v2(u(0x102), u(0x101), "ABANDONED", bp, None, t)
    fp = seal_v2.compute_fork_point_hash_v2(u(0x110), u(0x111), u(0x112), EPISODE, u(5), "evaluate the alternative", 0, t, bp)
    dfp = seal_v2.compute_departure_fork_point_hash_v2(u(0x120), u(0x121), u(0x122), EPISODE, u(5), "follow the tangent",
                                                       "DRIFT_CONFIRMED", LEAVES[5], t, None)
    fr = seal_v2.compute_fork_return_hash_v2(u(0x123), u(0x121), u(0x122), EPISODE, "COMPLETED", LEAVES[6], t, dfp)
    mp = seal_v2.compute_merge_point_hash_v2(u(0x130), u(0x131), u(0x112), EPISODE, LEAVES[0], LEAVES[1], LEAVES[2], None, "CLEAN", t, fp)
    ctx = seal_v2.compute_hitl_context_hash_v2("req-1", EPISODE, "APPROVAL_REQUIRED", "agent-a", t, '{"action":"deploy"}')
    res = seal_v2.compute_hitl_resolution_hash_v2(u(0x140), "approved", "human-1", t, None)
    hn = seal_v2.compute_hitl_node_hash_v2(ctx, res)
    return dict(branch_point_v2=bp, branch_terminus_v2=bt, fork_point_v2=fp, departure_fork_point_v2=dfp,
                fork_return_v2=fr, merge_point_v2=mp, hitl_context_v2=ctx, hitl_resolution_v2=res, hitl_node_v2=hn)


MANIFEST_MEMBERS = ("branch_point_v2", "branch_terminus_v2", "fork_point_v2", "departure_fork_point_v2",
                    "fork_return_v2", "merge_point_v2", "hitl_node_v2")


def test_structural_members():
    got = _members()
    assert got == {k: VECTORS["structural_members"][k] for k in got}
    assert len(set(got.values())) == len(got)


def test_structural_fields_are_bound_and_commentary_is_not_a_field():
    # spine_merkle_snapshot and merge_type make structural claims, so they are in the preimage
    t = datetime.fromisoformat(VECTORS["structural_members"]["timestamp"])
    u = lambda i: UUID(f"00000000-0000-4000-8000-{i:012x}")
    base = _members()
    other_snapshot = seal_v2.compute_branch_point_hash_v2(u(0x100), EPISODE, u(0x101), u(3), VECTORS["spine_root_sav2"]["2"],
                                                          "EXPLORATORY", "EXPLICIT", t, None)
    assert other_snapshot != base["branch_point_v2"]
    other_merge = seal_v2.compute_merge_point_hash_v2(u(0x130), u(0x131), u(0x112), EPISODE, LEAVES[0], LEAVES[1], LEAVES[2],
                                                      None, "PARTIAL", t, base["fork_point_v2"])
    assert other_merge != base["merge_point_v2"]
    import inspect
    bound = {name: set(inspect.signature(fn).parameters) for name, fn in vars(seal_v2).items()
             if name.startswith("compute_") and name.endswith("_hash_v2")}
    commentary_or_provenance = {"branch_label", "merge_summary", "synthesis_summary",
                                "initiated_by", "initiator", "returned_by"}
    for name in ("compute_branch_point_hash_v2", "compute_branch_terminus_hash_v2", "compute_fork_point_hash_v2",
                 "compute_departure_fork_point_hash_v2", "compute_fork_return_hash_v2", "compute_merge_point_hash_v2"):
        assert not (bound[name] & commentary_or_provenance), (name, bound[name] & commentary_or_provenance)


def test_hitl_terminal_states():
    assert seal_v2.HITL_TERMINAL_STATES == {"resolved", "timed_out", "escalated"}


def test_structural_manifest_detects_removal():
    m = _members()
    members = [m[k] for k in MANIFEST_MEMBERS]
    want = VECTORS["structural_manifest_v1"]
    assert seal_v2.compute_structural_manifest_hash(members) == want["seven_members_any_order"] == ref_set(b"STRUCTURAL_MANIFEST:v1:", members)
    assert seal_v2.compute_structural_manifest_hash(list(reversed(members))) == want["seven_members_any_order"]
    # a closed branch made to look open: drop its terminus, and the manifest changes
    without_terminus = [h for h in members if h != m["branch_terminus_v2"]]
    assert seal_v2.compute_structural_manifest_hash(without_terminus) == want["with_branch_terminus_removed"] != want["seven_members_any_order"]
    assert seal_v2.compute_structural_manifest_hash([]) == want["empty"]


def test_old_segment_is_sealed_from_its_fields_never_from_its_old_leaf_hash():
    from astp.protocol.leaf_hash import compute_leaf_hash

    mv = VECTORS["mixed_vintage_segment"]
    f = mv["fields"]
    v1 = compute_leaf_hash(UUID(f["node_id"]), f["node_type"], f["schema_version"], f["sequence_index"],
                           f["content_hash"], None, UUID(f["parent_node_id"]))
    v2 = compute_leaf_hash_v2(UUID(f["node_id"]), f["node_type"], f["schema_version"], f["sequence_index"],
                              f["content_hash"], UUID(f["parent_node_id"]))
    assert v1 == mv["stored_leaf_hash_v1"] and v2 == mv["leaf_hash_v2_from_fields"] == ref_leaf_hash(f)
    # the tempting mistake: "upgrade" the stored v1 leaf by hashing it again
    rewrapped = hashlib.sha3_256(b"LEAF_HASH:v2:" + bytes.fromhex(v1)).hexdigest()
    assert rewrapped != v2


def test_vector_file_is_current():
    import subprocess, sys

    gen = Path(__file__).resolve().parents[2] / "vectors" / "5.0.0-draft" / "generate.py"
    assert subprocess.run([sys.executable, str(gen), "--check"]).returncode == 0, "run vectors/5.0.0-draft/generate.py"


def test_episode_root_v2():
    want = VECTORS["episode_root_v2"]
    spine = VECTORS["spine_root_sav2"]["7"]
    sig = VECTORS["signal_manifest_v2"]["five_members_any_order"]
    st = VECTORS["structural_manifest_v1"]["seven_members_any_order"]
    ex = VECTORS["exclusion_v2"]["empty"]
    ref = _sha3(b"EPISODE_ROOT:v2:" + _uuid(VECTORS["episode_id"]) + _hash(spine) + _hash(sig) + _hash(st) + _hash(ex)).hex()
    assert seal_v2.compute_episode_root_hash_v2(EPISODE, spine, sig, st, ex) == want["hash"] == ref
    # removing every structural node changes the Episode root — the guarantee 4.x never had
    assert seal_v2.compute_episode_root_hash_v2(EPISODE, spine, sig, VECTORS["structural_manifest_v1"]["empty"], ex) \
        == want["with_empty_structural_manifest"] != want["hash"]
    assert seal_v2.compute_episode_root_hash_v2(UUID(int=42), spine, sig, st, ex) != want["hash"]


def test_every_prefix_in_the_registry_is_distinct_and_none_is_a_4x_prefix():
    prefixes = [v for k, v in vars(seal_v2).items() if k.isupper() and isinstance(v, bytes)]
    prefixes += [b"LEAF_HASH:v2:", b"TREE_LEAF:v2:", b"TREE_NODE:v2:"]
    assert len(prefixes) == len(set(prefixes)) == 16
    assert not any(p in (b"LEAF:", b"NODE:") or p.startswith((b"LEAF:", b"NODE:")) for p in prefixes)
    assert not any(a != b and a.startswith(b) for a in prefixes for b in prefixes)      # no prefix is a prefix of another
