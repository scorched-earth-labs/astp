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

    python vectors/5.0.0/generate.py            # rewrite the file
    python vectors/5.0.0/generate.py --check    # exit 1 if the file is stale

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
from astp.core import content_hash_v2 as C
from astp.protocol.anchor_v2 import compute_anchor_commitment_v2
from astp.protocol.witness_v2 import sign_witness_record_v2
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from astp.protocol.audit_v2 import make_audit_record
from astp.protocol.canonical_json import canonical_json
from astp.protocol import encoding as E
from astp.protocol.leaf_hash import compute_leaf_hash, compute_leaf_hash_v2
from astp.protocol.merkle import generate_inclusion_proof_v2

OUT = Path(__file__).with_name("seal-constructions.json")


def H(b: bytes) -> str:
    return hashlib.sha3_256(b).hexdigest()


def nid(i: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{i:012x}")


def canonical_json_vectors() -> dict:
    """RFC 8785 + NFC. `rfc8785_appendix_example` is the RFC's own example
    document; the expected output is the RFC's, byte for byte."""
    euro, dollar, si, nl, bs, q = chr(0x20AC), "$", chr(0x0F), chr(0x0A), chr(0x5C), chr(0x22)
    rfc_doc = {
        "numbers": [333333333.33333329, 1e30, 4.50, 2e-3, 0.000000000000000000000000001],
        "string": euro + dollar + si + nl + "A'B" + q + bs + bs + "/",
        "literals": [None, True, False],
    }
    cases = {
        "rfc8785_appendix_example": rfc_doc,
        "nested_keys_sorted_by_utf16_code_units": {"\U0001F600": 1, "\uFFFF": 2, "a": 3, "B": 4, "": 5},
        "nfc_decomposed_key_and_value": {"e" + chr(0x301): "e" + chr(0x301)},
        "numbers": {"int": 1, "neg": -7, "float_one": 1.0, "tiny": 1e-7, "big": 1e21, "neg_zero": -0.0,
                    "large_int": 123456789012345678901234567890},
        "empty_containers": {"o": {}, "a": []},
    }
    return {k: {"input_repr": repr(v), "canonical": canonical_json(v).decode("utf-8"),
                "sha3_256": H(canonical_json(v))} for k, v in cases.items()}


def audit_vectors(ep: UUID, t: datetime) -> dict:
    """A three-record chain plus a genesis-with-everything-absent record."""
    key = str(ep)
    common = dict(chain_key=key, agent_id="agent-α", session_id="session-1")
    r1 = make_audit_record(**common, delta_sequence=1, delta_type="BRANCH_CREATED",
                           trigger_context="human_explicit", human_actor="devin",
                           forward_delta={"branch_id": str(nid(20)), "label": "e" + chr(0x301) + "tude", "depth": 2.5},
                           reverse_delta={"branch_id": str(nid(20)), "deleted": True},
                           affected_nodes=[str(nid(20)), str(nid(3))], explicit_reason="try the other reading",
                           caught_by="HUMAN", detection_window_open=True, wall_clock_time=t, episode_time=7,
                           prior_audit_hash=None, audit_id=nid(30))
    r2 = make_audit_record(**common, delta_sequence=2, delta_type="BRANCH_ABANDONED",
                           trigger_context="agent_detected", forward_delta={"branch_id": str(nid(20))},
                           reverse_delta={}, affected_nodes=[str(nid(20))], wall_clock_time=t + timedelta(seconds=1, microseconds=999_999),
                           episode_time=8, prior_audit_hash=r1.record_hash, audit_id=nid(31))
    r3 = make_audit_record(**common, delta_sequence=3, delta_type="LINK_ASSERTED",
                           trigger_context="human_explicit", forward_delta={"z": [1, {"y": None}], "a": ""},
                           reverse_delta={}, affected_nodes=[], wall_clock_time=t + timedelta(seconds=2),
                           episode_time=8, prior_audit_hash=r2.record_hash, audit_id=nid(32))
    genesis_minimal = make_audit_record(chain_key="declaration:system-x:group-y", delta_sequence=1,
                                        delta_type="GROUP_DECLARED", agent_id="", session_id="",
                                        trigger_context="system_automatic", forward_delta={}, reverse_delta={},
                                        wall_clock_time=datetime(1970, 1, 1, tzinfo=timezone.utc),
                                        prior_audit_hash=None, audit_id=nid(33))
    def dump(r):
        d = json.loads(r.model_dump_json())
        return d
    return {
        "preimage_field_order": ["audit_id UUID", "chain_key STRING", "delta_sequence UINT", "delta_type STRING",
                                 "agent_id STRING", "session_id STRING", "human_actor STRING|NULL",
                                 "wall_clock_time TIMESTAMP", "episode_time UINT", "forward_delta BYTES",
                                 "reverse_delta BYTES", "affected_nodes LIST(STRING)", "trigger_context STRING",
                                 "explicit_reason STRING|NULL", "caught_by STRING", "detection_window_open BOOL",
                                 "prior_audit_hash HASH|NULL"],
        "prefix": "AUDIT_RECORD:v2:",
        "chain": [dump(r1), dump(r2), dump(r3)],
        "genesis_minimal": dump(genesis_minimal),
        "note": "wall_clock_time is stored at millisecond precision; record 2 was built from an instant with 999999 microseconds and is stored truncated, so the stored value is what was hashed.",
    }


def content_hash_vectors(ep: UUID, t: datetime, segs: list) -> dict:
    """Aside, soliloquy and Episode-link content hashes (draft §13)."""
    c = [s["content_hash"] for s in segs]
    aside = C.compute_aside_hash_v2(nid(40), ep, nid(2), c[2], "devin", "agent-α", t)
    aside_t = C.compute_aside_terminus_hash_v2(nid(41), nid(40), ep, aside, [c[3], c[4]], "done",
                                               False, [nid(5)], "CLOSED", t + timedelta(minutes=5))
    sol = C.compute_soliloquy_hash_v2(nid(42), ep, nid(2), c[2], "agent-α", t)
    chain = C.compute_deliberation_chain_hash_v2(nid(42), [c[3], c[4], c[5]])
    chain_empty = C.compute_deliberation_chain_hash_v2(nid(42), [])
    concl = C.compute_soliloquy_conclusion_hash_v2(nid(43), nid(42), ep, chain, "take the second reading",
                                                   nid(6), "ABSORBED", t + timedelta(minutes=5))
    sig1 = C.compute_link_signal_hash_v2("SEMANTIC_SIMILARITY", 0.6, 0.91, t)
    sig2 = C.compute_link_signal_hash_v2("PARTICIPANT_OVERLAP", 0.4, 0.5, t)
    src_root = H(b"episode-root-of-source")
    ep2 = UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
    link_inferred = C.compute_episode_link_hash_v2(nid(44), ep, ep2, src_root, None, t, "RELATES_TO", 0.736, True,
                                                   [sig1, sig2], 0.7, True, "1.0.0", None)
    link_asserted = C.compute_episode_link_hash_v2(nid(45), ep, ep2, None, None, t, "CONTINUES_FROM", 1.0, False,
                                                   [], None, False, None, None)
    return {
        "inputs": "see tests/conformance/test_content_hashes_v2_vectors.py for the exact field values",
        "aside_v2": aside, "aside_terminus_v2": aside_t,
        "soliloquy_v2": sol, "deliberation_chain_v2": chain, "deliberation_chain_v2_empty": chain_empty,
        "soliloquy_conclusion_v2": concl,
        "link_signal_v2": [sig1, sig2],
        "episode_link_v2_inferred_source_sealed": link_inferred,
        "episode_link_v2_asserted_neither_sealed": link_asserted,
        "source_episode_root_used": src_root, "target_episode_id": str(ep2),
    }


def witness_anchor_vectors(ep: UUID, t: datetime) -> dict:
    """Witness records signed with the RFC 8032 §7.1 test keys (Ed25519 is
    deterministic, so the signatures are reproducible), and an anchor commitment."""
    root = H(b"episode-root-of-source")
    sk1 = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"))
    sk2 = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb"))
    common = dict(node_id=ep, node_type="episode", root=root, root_version=2, sequence_index=7, logical_clock=9,
                  witnessed_at=t + timedelta(minutes=1))
    w1 = sign_witness_record_v2(sk1, witness_id="witness-1", role="SEAL_WITNESS", **common)
    w2 = sign_witness_record_v2(sk2, witness_id="witness-2", role="CUSTOM", role_detail="notary", **common)
    def dump(w):
        d = json.loads(w.model_dump_json(exclude={"signature", "public_key"}))
        d["signature"] = w.signature.hex(); d["public_key"] = w.public_key.hex()
        return d
    anchor = compute_anchor_commitment_v2(node_id=ep, node_type="episode", workspace_id="ws-1", root=root, root_version=2,
                                          crystallization_sequence=7, logical_clock=9, anchored_at=t + timedelta(minutes=2))
    return {
        "signing_keys": "RFC 8032 section 7.1 TEST 1 and TEST 2 secret keys; signatures are over bytes.fromhex(commitment_hash)",
        "witness_records": [dump(w1), dump(w2)],
        "anchor_commitment_v2": anchor,
        "anchor_inputs": {"node_id": str(ep), "node_type": "episode", "workspace_id": "ws-1", "root": root, "root_version": 2,
                          "crystallization_sequence": 7, "logical_clock": 9, "anchored_at": (t + timedelta(minutes=2)).isoformat()},
    }


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
            "LIST_of_STRING_a_b": E.encode_field((E.LIST, E.STRING), ["a", "b"]).hex(),
            "LIST_empty": E.encode_field((E.LIST, E.STRING), []).hex(),
            "BOOL_true": E.encode_field(E.BOOL, True).hex(),
            "BOOL_false": E.encode_field(E.BOOL, False).hex(),
            "FLOAT_0.75": E.encode_field(E.FLOAT, 0.75).hex(),
            "FLOAT_negative_zero_is_positive_zero": [E.encode_field(E.FLOAT, -0.0).hex(), E.encode_field(E.FLOAT, 0.0).hex()],
            "LIST_of_HASH_two": E.encode_field((E.LIST, E.HASH), [segs[0]["content_hash"], segs[1]["content_hash"]]).hex(),
        },
        "content_hashes_v2": content_hash_vectors(ep, t, segs),
        "witness_and_anchor_v2": witness_anchor_vectors(ep, t),
        "canonical_json": canonical_json_vectors(),
        "audit_records_v2": audit_vectors(ep, t),
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
