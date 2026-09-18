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
"""G-40: an Episode created under an earlier version with a non-UUID identifier
is sealed under spine_algorithm_version 1, and never under version 2."""

from uuid import UUID, uuid4

import pytest

from astp.core.crystallization import (
    CrystallizationDeltaNode, CrystallizationScope, EpisodeVersionVector, build_crystallization_delta,
    compute_crystallization_content_hash, compute_crystallization_node_hash, episode_ref,
)


def _delta(episode_id, sav):
    return build_crystallization_delta(
        episode_id=episode_id, predecessor_hash="GENESIS", sealed_chain_root="ab" * 32,
        verification_authority="test", chain_position=1,
        version_vector=EpisodeVersionVector(content_version=3, lifecycle_version=0, chain_version=0),
        crystallization_scope=CrystallizationScope.EPISODE, spine_algorithm_version=sav, ordering_version=2,
    )


def test_episode_ref_is_a_uuid_when_it_can_be_and_the_legacy_string_otherwise():
    u = uuid4()
    assert episode_ref(u) == u
    assert episode_ref(str(u)) == u
    assert episode_ref(str(u).upper()) == u
    assert episode_ref("phase-a-doc-campaign") == "phase-a-doc-campaign"
    for bad in ("", None, 7):
        with pytest.raises(ValueError):
            episode_ref(bad)


def test_legacy_identifier_seals_under_version_1_and_is_not_in_any_hash():
    d = _delta("phase-a-doc-campaign", sav=1)
    assert d.episode_id == "phase-a-doc-campaign"
    # episode_id is in no delta preimage: the same content under a UUID Episode has the same hashes
    u = CrystallizationDeltaNode(episode_id=uuid4(), chain_position=1, content=d.content,
                                 content_hash=compute_crystallization_content_hash(d.content),
                                 node_hash=compute_crystallization_node_hash(d.content_hash, "GENESIS"),
                                 version_vector=d.version_vector)
    assert isinstance(u.episode_id, UUID)
    assert d.content_hash == u.content_hash and d.node_hash == u.node_hash


def test_legacy_identifier_is_refused_under_version_2():
    with pytest.raises(ValueError, match="version 2 seal binds a UUID"):
        _delta("phase-a-doc-campaign", sav=2)
    assert isinstance(_delta(str(uuid4()), sav=2).episode_id, UUID)   # a UUID-shaped string is a UUID
