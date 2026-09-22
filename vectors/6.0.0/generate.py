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
"""Regenerate context-commitment.json from the 6.0.0 reference constructions.

    python vectors/6.0.0/generate.py            # rewrite the file
    python vectors/6.0.0/generate.py --check    # exit 1 if the file is stale

The JSON is the artifact: a second implementation needs it and the draft text,
not this script. The script exists so the file is never edited by hand.
The values were generated while 6.0.0 was a draft and are unchanged by ratification.

The Episode is the one the ratified 5.0.0 vectors seal (same identifier,
Segments, Signals and structural members), so the version 2 roots here are
the ratified values byte for byte and CM-10 — a version 2 seal of an Episode
holding context entries still reproduces under version 2 — is shown against
them, not against a value this script invents.
"""
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from astp.core import context_v1 as X
from astp.core import seal_v2 as S
from astp.core.seal_v2 import SegmentSealInput, compute_episode_seal_v2

OUT = Path(__file__).with_name("context-commitment.json")
BASE = Path(__file__).resolve().parents[1] / "5.0.0" / "seal-constructions.json"


def H(b: bytes) -> str:
    return hashlib.sha3_256(b).hexdigest()


def nid(i: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{i:012x}")


def dump_entry(e: X.ContextEntryNode, entry_hash: str) -> dict:
    d = json.loads(e.model_dump_json())
    d["entry_hash"] = entry_hash
    return d


def build() -> dict:
    base = json.loads(BASE.read_text(encoding="utf-8"))
    ep = UUID(base["episode_id"])
    t = datetime(2026, 1, 1, 0, 0, 0, 123000, tzinfo=timezone.utc)
    m = lambda k: t + timedelta(minutes=k)

    # the ratified 5.0.0 Episode, sealed again under version 2 from the same stored fields
    segments = [SegmentSealInput(node_id=UUID(s["node_id"]), node_type=s["node_type"], schema_version=s["schema_version"],
                                 sequence_index=s["sequence_index"], content_hash=s["content_hash"], parent_node_id=UUID(s["parent_node_id"]))
                for s in base["segments"]]
    signals = base["signals"]
    member_keys = ("branch_point_v2", "branch_terminus_v2", "fork_point_v2", "departure_fork_point_v2",
                   "fork_return_v2", "merge_point_v2", "hitl_node_v2")
    members = [base["structural_members"][k] for k in member_keys]
    v2 = compute_episode_seal_v2(ep, segments, signal_content_hashes=signals, excluded_content_hashes=[],
                                 structural_member_hashes=members)
    assert v2.episode_root_hash == base["episode_root_v2"]["hash"], "the 5.0.0 Episode did not reproduce"

    # content commitments (draft §5.3)
    pdf = b"%PDF-1.7\n1 0 obj << /Type /Catalog >> endobj\n%%EOF\n"
    dob = b"1979-03-14"
    salt = bytes(range(32))                      # FIXED here for reproducibility; a real salt is 32 CSPRNG bytes
    rate_sheet = b"<html><body>30-year fixed 6.125% (2026-01-01)</body></html>"
    apr = b'{"apr": 6.125, "points": 0.5}'
    recovered = b"Guidance bulletin, September 1: verify income with two pay stubs."
    h_pdf, h_dob_plain = X.compute_context_content_hash_v1(pdf), X.compute_context_content_hash_v1(dob)
    h_dob_salted = X.compute_context_content_hash_v1(dob, salt)
    h_rates, h_apr, h_recovered = (X.compute_context_content_hash_v1(x) for x in (rate_sheet, apr, recovered))
    h_guidance_snapshot = H(b"guidance-index-snapshot-2026-01-01")

    # the seven entries (draft §4.8, §5.1)
    E = X.ContextEntryNode
    e1 = E(entry_id=nid(0x200), episode_id=ep, entry_type="attachment", provided_to="agent-α", provided_at=m(1),
           provided_before_sequence_index=3, content_hash=h_pdf, verifiability_at_seal="verifiable",
           media_type="application/pdf", source_ref=str(nid(0x300)), content_ref="blob://ctx/e1")
    e2 = E(entry_id=nid(0x201), episode_id=ep, entry_type="retrieval", provided_to="agent-α", provided_at=m(2),
           provided_before_sequence_index=4, content_hash=H(b"CONTEXT_CONTENT:v1:" + b"\x01" + (0).to_bytes(4, "big")),
           verifiability_at_seal="attested", media_type="text/markdown", source_version_hash=h_guidance_snapshot,
           source_ref=f"kn:{nid(0x301)}")
    e2 = e2.model_copy(update={"content_hash": X.compute_context_content_hash_v1(b"Guidance bulletin, September 1.")})
    e3 = E(entry_id=nid(0x202), episode_id=ep, entry_type="retrieval", provided_to="agent-β", provided_at=m(3),
           provided_before_sequence_index=4, content_hash=h_dob_salted, salted=True, verifiability_at_seal="verifiable",
           media_type="text/plain", source_version_hash=H(b"borrower-record-v7"), source_ref="doc:borrower-4471#dob",
           content_ref="blob://ctx/e3", salt_ref="salt://ctx/e3", pii_classification=X.PII_LOW_ENTROPY)
    e4 = E(entry_id=nid(0x203), episode_id=ep, entry_type="external", provided_to="agent-α", provided_at=m(4),
           provided_before_sequence_index=5, content_hash=h_rates, verifiability_at_seal="verifiable", media_type="text/html",
           source_ref='https://rates.example/sheet?date=2026-01-01 status=200 etag="7f3a"', content_ref="blob://ctx/e4")
    e5 = E(entry_id=nid(0x204), episode_id=ep, entry_type="tool_output", provided_to="agent-α", provided_at=m(5),
           provided_before_sequence_index=6, content_hash=h_apr, verifiability_at_seal="verifiable",
           media_type="application/json", source_version_hash=H(b"skill-invocation-content"), source_ref=str(nid(0x310)),
           content_ref="blob://ctx/e5")
    e6 = E(entry_id=nid(0x205), episode_id=ep, entry_type="retrieval", provided_to="agent-β", provided_at=m(6),
           capture_state="declared_incomplete", source_ref="index:query=income verification guidance;results=1")
    e7 = E(entry_id=nid(0x206), episode_id=ep, entry_type="retrieval", provided_to="agent-β", provided_at=m(7),
           content_hash=h_recovered, verifiability_at_seal="verifiable", media_type="text/plain",
           source_version_hash=H(b"guidance-v2"), resolves=nid(0x205), source_ref="index:doc=guidance-2026-09-01",
           content_ref="blob://ctx/e7")
    entries = [e1, e2, e3, e4, e5, e6, e7]
    hashes = X.context_entry_hashes(entries)
    by_id = dict(zip([e.entry_id for e in entries], hashes))
    h6, h7 = by_id[e6.entry_id], by_id[e7.entry_id]
    assert h7 == X.context_entry_hash(e7, h6)

    # manifest, root, seal (draft §6.2, §6.3, §7)
    posture = "declared_only"
    tree_root = X.compute_context_tree_root_v1(hashes)
    cm = X.compute_context_manifest_hash_v1(posture, hashes)
    seal = X.compute_episode_seal_v3(ep, segments, capture_posture=posture, context_entries=entries,
                                     signal_content_hashes=signals, structural_member_hashes=members)
    assert seal.context_manifest_hash == cm and seal.spine_root == v2.spine_root
    cm_empty = X.compute_context_manifest_hash_v1("none", [])
    seal_empty = X.compute_episode_seal_v3(ep, segments, capture_posture="none", signal_content_hashes=signals,
                                           structural_member_hashes=members)

    # inclusion proof for the salted entry (CM-04)
    proof = X.generate_context_inclusion_proof_v1(hashes, by_id[e3.entry_id])
    assert X.verify_context_inclusion_proof_v1(proof, posture, len(hashes), cm)

    # erasure of the salted entry (CM-06)
    tomb = X.ErasureTombstone(tombstone_id=nid(0x400), episode_id=ep, entry_id=e3.entry_id, entry_hash=by_id[e3.entry_id],
                              erased_at=m(60), erasure_authority="GDPR-Art17", erasure_request_id="dsr-2026-0142", erased_by="privacy-officer")
    e3_erased = X.apply_erasure(e3, tomb)
    entries_after = [e3_erased if e.entry_id == e3.entry_id else e for e in entries]
    seal_after = X.compute_episode_seal_v3(ep, segments, capture_posture=posture, context_entries=entries_after,
                                           signal_content_hashes=signals, structural_member_hashes=members)
    assert seal_after.episode_root_hash == seal.episode_root_hash

    # an external entry's provenance is outside the preimage (CM-08)
    e4_moved = e4.model_copy(update={"source_ref": "https://rates.example/sheet?date=2026-01-02 status=404"})

    sorted_order = X.sort_entry_hashes(hashes)
    return {
        "status": "Ratified with SPEC 6.0.0 (Episode of Record 80e5a2dd-3d9f-45d0-abfb-6489c8caf1b8). Every value is fixed: a construction never changes in place, so a different value is a new versioned construction.",
        "hash": "SHA3-256 (FIPS 202). Hash values are lowercase hex here; they enter every construction as 32 raw bytes.",
        "note_on_identifiers": "entry_id, tombstone_id and the base Episode's node_id values are fixed so the vectors are reproducible. Real identifiers MUST be random.",
        "note_on_salts": "The salt below is fixed so the salted commitment is reproducible. A real salt MUST be 32 bytes from a CSPRNG, stored in a namespace separate from the content, and destroyed with it (draft §5.3, §8.2).",
        "base_episode": {
            "source": "vectors/5.0.0/seal-constructions.json — the same Episode, Segments, Signals and structural members",
            "episode_id": str(ep), "spine_root": v2.spine_root, "signal_manifest_hash": v2.signal_manifest_hash,
            "structural_manifest_hash": v2.structural_manifest_hash, "exclusion_hash": v2.exclusion_hash,
            "episode_root_v2": v2.episode_root_hash,
        },
        "content_hashes_v1": {
            "rule": "CONTEXT_CONTENT:v1: ‖ BYTES(content), or CONTEXT_CONTENT_SALTED:v1: ‖ BYTES(salt) ‖ BYTES(content); BYTES is the §5.1.1 length-prefixed field encoding",
            "plain_pdf": {"content_hex": pdf.hex(), "hash": h_pdf},
            "plain_low_entropy_dob": {"content_utf8": dob.decode(), "hash": h_dob_plain,
                                      "note": "a plain commitment to a date of birth confirms a guess at it forever — G-42 forbids it"},
            "salted_low_entropy_dob": {"content_utf8": dob.decode(), "salt_hex": salt.hex(), "hash": h_dob_salted},
            "plain_rate_sheet": {"content_hex": rate_sheet.hex(), "hash": h_rates},
            "plain_tool_output": {"content_hex": apr.hex(), "hash": h_apr},
            "plain_recovered_guidance": {"content_hex": recovered.hex(), "hash": h_recovered},
            "plain_guidance_bulletin": {"content_utf8": "Guidance bulletin, September 1.", "hash": e2.content_hash},
        },
        "entry_hash_v1": {
            "preimage_field_order": ["entry_id UUID", "episode_id UUID", "entry_type STRING", "provided_to STRING",
                                     "provided_at TIMESTAMP", "provided_before_sequence_index UINT|NULL", "capture_state STRING",
                                     "content_hash HASH|NULL", "salted BOOL", "verifiability_at_seal STRING|NULL",
                                     "media_type STRING|NULL", "source_version_hash HASH|NULL", "resolves_entry_hash HASH|NULL"],
            "side_channel_not_bound": ["source_ref", "content_ref", "salt_ref", "erasure_state", "pii_classification", "resolves (bound as the resolved entry's hash, not as an identifier)"],
            "prefix": "CONTEXT_ENTRY:v1:",
        },
        "entries": [dump_entry(e, by_id[e.entry_id]) for e in entries],
        "context_tree_v1": {
            "rule": "the §5.4 version 2 tree (TREE_LEAF:v2:, TREE_NODE:v2:, raw bytes) over entry hashes sorted ascending bytewise; undefined for zero entries",
            "sorted_leaf_order_entry_ids": [str(next(e.entry_id for e in entries if by_id[e.entry_id] == h)) for h in sorted_order],
            "root_seven_entries": tree_root,
        },
        "context_manifest_v1": {
            "rule": "CONTEXT_MANIFEST:v1: ‖ STRING(capture_posture) ‖ UINT(n) ‖ HASH|NULL(context_tree_root)",
            "declared_only_seven": cm,
            "declared_only_seven_entries_in_reverse_insertion_order": X.compute_context_manifest_hash_v1(posture, list(reversed(hashes))),
            "all_external_seven": X.compute_context_manifest_hash_v1("all_external", hashes),
            "declared_only_without_the_attested_retrieval": X.compute_context_manifest_hash_v1(posture, [h for h in hashes if h != by_id[e2.entry_id]]),
            "empty_none": cm_empty,
            "empty_declared_only": X.compute_context_manifest_hash_v1("declared_only", []),
        },
        "episode_root_v3": {
            "inputs": ["base_episode.episode_id", "base_episode.spine_root", "base_episode.signal_manifest_hash",
                       "base_episode.structural_manifest_hash", "base_episode.exclusion_hash", "context_manifest_v1.declared_only_seven"],
            "seven_entries_declared_only": seal.episode_root_hash,
            "empty_manifest_posture_none": seal_empty.episode_root_hash,
            "seal_record": json.loads(seal.model_dump_json()),
        },
        "cm10_version_2_seal_is_unchanged_by_context_entries": {
            "episode_root_v2_of_the_same_episode": v2.episode_root_hash,
            "equals_5.0.0_vector": v2.episode_root_hash == base["episode_root_v2"]["hash"],
            "rule": "context entries are not members of a version 2 root; a version 2 seal of this Episode reproduces to the ratified value whether or not entries exist",
        },
        "inclusion_proof_v1": {
            "rule": "leaf_index is the entry's position in the sorted leaf list; the proof reproduces context_tree_root, then the manifest hash from posture and count, then the Episode root",
            "entry_id": str(e3.entry_id), "proof": proof.model_dump(), "capture_posture": posture, "entry_count": len(hashes),
            "context_manifest_hash": cm, "episode_root_v3": seal.episode_root_hash,
        },
        "resolves": {
            "declared_incomplete_entry_id": str(e6.entry_id), "declared_incomplete_entry_hash": h6,
            "resolving_entry_id": str(e7.entry_id), "resolving_entry_hash": h7,
            "rule": "the resolving entry's preimage binds the resolved entry's hash; the resolved entry is never mutated",
        },
        "erasure_v1": {
            "entry_id": str(e3.entry_id),
            "before": {"content_ref": e3.content_ref, "salt_ref": e3.salt_ref, "erasure_state": e3.erasure_state},
            "after": {"content_ref": e3_erased.content_ref, "salt_ref": e3_erased.salt_ref, "erasure_state": e3_erased.erasure_state},
            "entry_hash_unchanged": by_id[e3.entry_id],
            "tombstone": {**json.loads(tomb.model_dump_json()), "tombstone_hash": X.tombstone_hash(tomb)},
            "tombstone_preimage_field_order": ["tombstone_id UUID", "episode_id UUID", "entry_id UUID", "entry_hash HASH",
                                               "erased_at TIMESTAMP", "erasure_authority STRING", "erasure_request_id STRING", "erased_by STRING"],
            "context_manifest_hash_unchanged": seal_after.context_manifest_hash,
            "episode_root_v3_unchanged": seal_after.episode_root_hash,
        },
        "external_entry_provenance_is_outside_the_preimage": {
            "entry_id": str(e4.entry_id), "entry_hash": by_id[e4.entry_id],
            "source_ref_changed_to": e4_moved.source_ref, "entry_hash_after": X.context_entry_hash(e4_moved),
        },
    }


if __name__ == "__main__":
    text = json.dumps(build(), indent=2, ensure_ascii=False) + "\n"
    if "--check" in sys.argv:
        sys.exit(0 if OUT.exists() and OUT.read_text(encoding="utf-8") == text else 1)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT}")
