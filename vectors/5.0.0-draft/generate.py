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
"""Regenerate seal-constructions.json from the draft reference constructions.

    python vectors/5.0.0-draft/generate.py            # rewrite the file
    python vectors/5.0.0-draft/generate.py --check    # exit 1 if the file is stale

The JSON is the artifact: a second implementation needs it and the draft text,
not this script. The script exists so the file is never edited by hand.
"""
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from astp.core import seal_v2 as S
from astp.protocol import encoding as E
from astp.protocol.leaf_hash import compute_leaf_hash, compute_leaf_hash_v2
from astp.protocol.merkle import generate_inclusion_proof_v2

OUT = Path(__file__).with_name("seal-constructions.json")


def H(b: bytes) -> str:
    return hashlib.sha3_256(b).hexdigest()


def nid(i: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{i:012x}")


def build() -> dict:
    ep = UUID("550e8400-e29b-41d4-a716-446655440000")
    t = datetime(2026, 1, 1, 0, 0, 0, 123000, tzinfo=timezone.utc)

    segs = []
    for i in range(7):
        s = dict(node_id=str(nid(i)), node_type="segment", schema_version="1.0.0", sequence_index=i,
                 content_hash=H(f"leaf-{i}".encode()), parent_node_id=str(ep))
        s["leaf_hash_v2"] = compute_leaf_hash_v2(nid(i), "segment", "1.0.0", i, s["content_hash"], ep)
        segs.append(s)
    leaves = [s["leaf_hash_v2"] for s in segs]
    signals = [H(f"leaf-{i}".encode()) for i in range(100, 105)]
    root3, root7 = S.compute_spine_root_sav2(leaves[:3]), S.compute_spine_root_sav2(leaves)

    bp = S.compute_branch_point_hash_v2(nid(0x100), ep, nid(0x101), nid(3), root3, "EXPLORATORY", "EXPLICIT", t, None)
    bt = S.compute_branch_terminus_hash_v2(nid(0x102), nid(0x101), "ABANDONED", bp, None, t)
    fp = S.compute_fork_point_hash_v2(nid(0x110), nid(0x111), nid(0x112), ep, nid(5), "evaluate the alternative", 0, t, bp)
    dfp = S.compute_departure_fork_point_hash_v2(nid(0x120), nid(0x121), nid(0x122), ep, nid(5), "follow the tangent",
                                                 "DRIFT_CONFIRMED", leaves[5], t, None)
    fr = S.compute_fork_return_hash_v2(nid(0x123), nid(0x121), nid(0x122), ep, "COMPLETED", leaves[6], t, dfp)
    mp = S.compute_merge_point_hash_v2(nid(0x130), nid(0x131), nid(0x112), ep, leaves[0], leaves[1], leaves[2], None, "CLEAN", t, fp)
    ctx = S.compute_hitl_context_hash_v2("req-1", ep, "APPROVAL_REQUIRED", "agent-a", t, '{"action":"deploy"}')
    res = S.compute_hitl_resolution_hash_v2(nid(0x140), "approved", "human-1", t, None)
    hn = S.compute_hitl_node_hash_v2(ctx, res)
    members = [bp, bt, fp, dfp, fr, mp, hn]

    sm, ex = S.compute_signal_manifest_hash_v2(signals), S.compute_exclusion_hash_v2([])
    st, st_empty = S.compute_structural_manifest_hash(members), S.compute_structural_manifest_hash([])

    old = segs[2]
    v1_leaf = compute_leaf_hash(nid(2), "segment", "1.0.0", 2, old["content_hash"], None, ep)

    return {
        "status": "DRAFT for SPEC 5.0.0 — not ratified. Values change if any construction changes before ratification.",
        "hash": "SHA3-256 (FIPS 202). Hash values are lowercase hex here; they enter every construction as 32 raw bytes.",
        "note_on_identifiers": "node_id values here are fixed so the vectors are reproducible. Real node_id values MUST be random.",
        "field_encoding": {
            "NULL": E.encode_field(E.STRING, None).hex(),
            "BYTES_0x0102": E.encode_field(E.BYTES, b"\x01\x02").hex(),
            "STRING_segment": E.encode_field(E.STRING, "segment").hex(),
            "STRING_nfc_e_acute_composed_equals_decomposed": [E.encode_field(E.STRING, "é").hex(),
                                                              E.encode_field(E.STRING, "é").hex()],
            "UINT_6": E.encode_field(E.UINT, 6).hex(),
            "UUID_episode": E.encode_field(E.UUID_, ep).hex(),
            "TIMESTAMP_2026-01-01T00:00:00.123Z": E.encode_field(E.TIMESTAMP, t).hex(),
            "TIMESTAMP_same_instant_at_-08:00": E.encode_field(E.TIMESTAMP, t.astimezone(timezone(timedelta(hours=-8)))).hex(),
            "HASH_of_leaf-0": E.encode_field(E.HASH, segs[0]["content_hash"]).hex(),
        },
        "episode_id": str(ep),
        "segments": segs,
        "spine_root_sav2": {str(n): S.compute_spine_root_sav2(leaves[:n]) for n in (1, 2, 3, 7)},
        "mixed_vintage_segment": {
            "rule": "A Segment created before 5.0.0 is sealed under 5.0.0 by computing the hash_version 2 leaf hash from its "
                    "stored fields. Never by re-hashing its stored version 1 leaf hash.",
            "fields": {k: old[k] for k in ("node_id", "node_type", "schema_version", "sequence_index", "content_hash", "parent_node_id")},
            "stored_leaf_hash_v1": v1_leaf,
            "leaf_hash_v2_from_fields": old["leaf_hash_v2"],
        },
        "inclusion_proofs_v2": {
            "rule": "leaf_index and leaf_count fix the path shape; the verifier derives at which levels a sibling exists "
                    "and on which side. A proof binds the leaf and its position, not the tree's size.",
            "tree": "the seven leaf_hash_v2 values above, in order",
            "leaf_3_of_7": generate_inclusion_proof_v2(leaves, 3).model_dump(),
            "leaf_6_of_7_unpaired_path": generate_inclusion_proof_v2(leaves, 6).model_dump(),
            "leaf_0_of_1": generate_inclusion_proof_v2(leaves[:1], 0).model_dump(),
            "expected_sibling_counts_for_7_leaves": [__import__("astp.protocol.merkle", fromlist=["x"]).expected_sibling_count_v2(i, 7) for i in range(7)],
        },
        "signals": signals,
        "signal_manifest_v2": {"five_members_any_order": sm, "empty": S.compute_signal_manifest_hash_v2([])},
        "exclusion_v2": {"empty": ex},
        "structural_members": {
            "timestamp": t.isoformat(),
            "branch_point_v2": bp, "branch_terminus_v2": bt, "fork_point_v2": fp, "departure_fork_point_v2": dfp,
            "fork_return_v2": fr, "merge_point_v2": mp,
            "hitl_context_v2": ctx, "hitl_resolution_v2": res, "hitl_node_v2": hn,
            "inputs": "see tests/conformance/test_seal_constructions_v2_vectors.py::test_structural_members for the exact field values",
        },
        "structural_manifest_v1": {
            "seven_members_any_order": st, "empty": st_empty,
            "with_branch_terminus_removed": S.compute_structural_manifest_hash([m for m in members if m != bt]),
        },
        "episode_root_v2": {
            "inputs": ["episode_id", "spine_root_sav2[7]", "signal_manifest_v2.five_members_any_order",
                       "structural_manifest_v1.seven_members_any_order", "exclusion_v2.empty"],
            "hash": S.compute_episode_root_hash_v2(ep, root7, sm, st, ex),
            "with_empty_structural_manifest": S.compute_episode_root_hash_v2(ep, root7, sm, st_empty, ex),
        },
    }


if __name__ == "__main__":
    text = json.dumps(build(), indent=2, ensure_ascii=False) + "\n"
    if "--check" in sys.argv:
        sys.exit(0 if OUT.read_text(encoding="utf-8") == text else 1)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT}")
