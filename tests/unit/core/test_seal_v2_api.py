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
"""compute_episode_seal_v2 / reproduce_episode_root — the runtime-facing seal API
(SPEC §5.7, §5.8, §9.3), checked against the ratified vectors."""

import json
from pathlib import Path
from uuid import UUID

import pytest

from astp.core.schema import reproduce_spine_root
from astp.core.seal_v2 import SegmentSealInput, compute_episode_seal_v2, reproduce_episode_root

V = json.loads((Path(__file__).parents[3] / "vectors" / "5.0.0" / "seal-constructions.json").read_text("utf-8"))
EP = UUID(V["episode_id"])
MEMBERS = [V["structural_members"][k] for k in ("branch_point_v2", "branch_terminus_v2", "fork_point_v2",
                                                 "departure_fork_point_v2", "fork_return_v2", "merge_point_v2", "hitl_node_v2")]
SIGNALS = V["signals"] if isinstance(V["signals"], list) else list(V["signals"].values())


def _segs():
    return [SegmentSealInput(node_id=UUID(s["node_id"]), node_type=s["node_type"], schema_version=s["schema_version"],
                             sequence_index=s["sequence_index"], content_hash=s["content_hash"], parent_node_id=EP)
            for s in V["segments"]]


def test_seal_from_stored_fields_matches_the_vectors_and_carries_its_identifiers():
    seal = compute_episode_seal_v2(EP, reversed(_segs()), signal_content_hashes=SIGNALS, structural_member_hashes=MEMBERS)
    assert seal.spine_root == V["spine_root_sav2"]["7"]
    assert seal.episode_root_hash == V["episode_root_v2"]["hash"]
    assert (seal.spine_algorithm_version, seal.ordering_version, seal.hash_version, seal.leaf_count) == (2, 2, 2, 7)


def test_seal_refuses_no_leaves_and_duplicate_positions():
    with pytest.raises(ValueError, match="no spine root"):
        compute_episode_seal_v2(EP, [])
    s = _segs()
    s[1] = s[1].model_copy(update={"sequence_index": s[0].sequence_index})
    with pytest.raises(ValueError, match="duplicate sequence_index"):
        compute_episode_seal_v2(EP, s)


def test_reproduce_episode_root_selects_by_version():
    seal = compute_episode_seal_v2(EP, _segs(), signal_content_hashes=SIGNALS, structural_member_hashes=MEMBERS)
    assert reproduce_episode_root(spine_algorithm_version=2, episode_id=str(EP), spine_root=seal.spine_root,
                                  signal_content_hashes=SIGNALS, excluded_content_hashes=[], structural_member_hashes=MEMBERS) == seal.episode_root_hash
    # a version-1 seal of the same Episode: content-hash leaves, Episode-id leaf, three-component root — a different root
    content = [s.content_hash for s in _segs()]
    root1 = reproduce_spine_root(content, [], spine_algorithm_version=1, ordering_version=2, episode_id=str(EP))
    r1 = reproduce_episode_root(spine_algorithm_version=1, episode_id=str(EP), spine_root=root1,
                                signal_content_hashes=SIGNALS, excluded_content_hashes=[])
    assert r1 != seal.episode_root_hash and len(r1) == 64
    # structural members do not enter a version-1 root
    assert reproduce_episode_root(spine_algorithm_version=1, episode_id=str(EP), spine_root=root1,
                                  signal_content_hashes=SIGNALS, excluded_content_hashes=[], structural_member_hashes=MEMBERS) == r1
    with pytest.raises(ValueError, match="unknown spine_algorithm_version"):
        reproduce_episode_root(spine_algorithm_version=7, episode_id=str(EP), spine_root=root1, signal_content_hashes=[], excluded_content_hashes=[])
