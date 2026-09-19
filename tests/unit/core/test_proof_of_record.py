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
"""Proof of record: export and third-party verification (SPEC §9.3)."""

import copy
import hashlib
import json
from pathlib import Path
from uuid import UUID

import pytest

from astp.core.proof_of_record import FORMAT, build_proof_of_record, dumps, main, verify_proof_of_record
from astp.core.schema import compute_exclusion_hash, compute_signal_manifest_hash, reproduce_spine_root
from astp.core.seal_v2 import SegmentSealInput, compute_episode_seal_v2, reproduce_episode_root

V = json.loads((Path(__file__).parents[3] / "vectors" / "5.0.0" / "seal-constructions.json").read_text("utf-8"))
EP = V["episode_id"]
SIGNALS = V["signals"] if isinstance(V["signals"], list) else list(V["signals"].values())
MEMBERS = [V["structural_members"][k] for k in ("branch_point_v2", "branch_terminus_v2", "fork_point_v2",
                                                 "departure_fork_point_v2", "fork_return_v2", "merge_point_v2", "hitl_node_v2")]
SEGS = [dict(node_id=s["node_id"], node_type=s["node_type"], schema_version=s["schema_version"], sequence_index=s["sequence_index"],
             content_hash=s["content_hash"], parent_node_id=EP) for s in V["segments"]]


def _v2_doc(profile="full", **over):
    seal = compute_episode_seal_v2(UUID(EP), [SegmentSealInput(**{**s, "node_id": UUID(s["node_id"]), "parent_node_id": UUID(EP)}) for s in SEGS],
                                   signal_content_hashes=SIGNALS, structural_member_hashes=MEMBERS)
    kw = dict(episode_id=EP, profile=profile, spine_algorithm_version=2, ordering_version=2,
              sealed_at="2026-09-19T20:46:18+00:00", closed_at="2026-09-19T20:46:18+00:00",
              spine_root=seal.spine_root, signal_manifest_hash=seal.signal_manifest_hash, exclusion_hash=seal.exclusion_hash,
              structural_manifest_hash=seal.structural_manifest_hash, episode_root_hash=seal.episode_root_hash, leaf_count=7,
              segments=SEGS, signal_content_hashes=SIGNALS, excluded_content_hashes=[], structural_member_hashes=MEMBERS)
    kw.update(over)
    return copy.deepcopy(build_proof_of_record(**kw))   # tests mutate documents; the fixture lists must stay pristine


def test_full_profile_version_2_reproduces_every_root():
    r = verify_proof_of_record(_v2_doc())
    assert r.ok and r.failures == []
    assert {"spine_root reproduced", "episode_root_hash reproduced", "structural_manifest_hash reproduced"} <= set(r.checks)


def test_full_profile_detects_a_tampered_segment_and_a_removed_member():
    doc = _v2_doc(); doc["stored"]["segments"][3]["content_hash"] = hashlib.sha3_256(b"x").hexdigest()
    r = verify_proof_of_record(doc); assert not r.ok and any("spine_root differs" in f for f in r.failures)
    doc = _v2_doc(); doc["stored"]["structural_member_hashes"].pop()
    r = verify_proof_of_record(doc); assert not r.ok and any("structural_manifest_hash differs" in f for f in r.failures)


def test_attested_profile_never_claims_what_it_cannot_rebuild():
    r = verify_proof_of_record(_v2_doc(profile="attested"))
    assert r.ok and "stored" not in _v2_doc(profile="attested")
    assert any("withheld" in n for n in r.not_checked) and not any("reproduced" in c for c in r.checks)


def test_full_profile_version_1_seal():
    content = [s["content_hash"] for s in SEGS]
    root = reproduce_spine_root(content, [], spine_algorithm_version=1, ordering_version=2, episode_id=EP)
    ep_root = reproduce_episode_root(spine_algorithm_version=1, episode_id=EP, spine_root=root, signal_content_hashes=SIGNALS, excluded_content_hashes=[])
    doc = build_proof_of_record(episode_id=EP, profile="full", spine_algorithm_version=1, ordering_version=2,
                                sealed_at="2026-09-18T17:25:35+00:00", closed_at="2026-09-18T17:25:35+00:00",
                                spine_root=root, signal_manifest_hash=compute_signal_manifest_hash(SIGNALS),
                                exclusion_hash=compute_exclusion_hash([]), episode_root_hash=ep_root,
                                segments=[{"sequence_index": s["sequence_index"], "content_hash": s["content_hash"]} for s in SEGS],
                                signal_content_hashes=SIGNALS, excluded_content_hashes=[])
    r = verify_proof_of_record(doc)
    assert r.ok, r.failures


def test_malformed_documents_fail_rather_than_crash(tmp_path):
    assert not verify_proof_of_record({"format": "nope"}).ok
    doc = _v2_doc(); doc["seal"]["ordering_version"] = 1
    assert "requires ordering_version 2" in verify_proof_of_record(doc).failures[0]
    doc = _v2_doc(); doc["seal"]["sealed_at"] = "2020-01-01T00:00:00+00:00"
    assert any("G-40" in f for f in verify_proof_of_record(doc).failures)
    doc = _v2_doc(); doc["stored"]["segments"][0]["node_id"] = "not-a-uuid"
    r = verify_proof_of_record(doc); assert not r.ok and "could not reproduce" in r.failures[0]
    p = tmp_path / "p.json"; p.write_text(dumps(_v2_doc()))
    assert main(["verify", str(p)]) == 0
    p.write_text(dumps(doc)); assert main(["verify", str(p)]) == 1


def test_pre_4_3_0_seal_carries_only_a_spine_root_and_says_so():
    content = [s["content_hash"] for s in SEGS]
    root = reproduce_spine_root(content, SIGNALS, spine_algorithm_version=1, ordering_version=1, episode_id=EP)
    doc = build_proof_of_record(episode_id=EP, profile="full", spine_algorithm_version=1, ordering_version=1,
                                sealed_at="2026-08-22T00:00:00+00:00", closed_at=None, spine_root=root,
                                signal_manifest_hash=None, exclusion_hash=None, episode_root_hash=None,
                                segments=[{"leaf_index": i, "content_hash": h} for i, h in enumerate(content)],
                                signal_content_hashes=SIGNALS, resolved_signal_order=SIGNALS)
    r = verify_proof_of_record(doc)
    assert r.ok and "spine_root reproduced" in r.checks
    assert any("predates" in n for n in r.not_checked) and not any("episode_root_hash reproduced" in c for c in r.checks)
    # a version 2 seal, by contrast, must carry all four
    d2 = _v2_doc(); d2["seal"]["structural_manifest_hash"] = None
    assert "version 2 seal without structural_manifest_hash" in verify_proof_of_record(d2).failures
