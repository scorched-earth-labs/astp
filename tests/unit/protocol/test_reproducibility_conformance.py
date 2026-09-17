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
Reproducibility Conformance Test Vectors (CONFORMANCE-REPRODUCIBILITY.md, RP-*)

SPEC 4.3.0 §5.6–§5.8 and §9.3. A sealed root MUST be reconstructible from
stored nodes alone, with no out-of-band state; the signal manifest MUST be
order-independent; version tags MUST select the reproduction function; and
an Episode whose record is fixed MUST refuse new content.
"""
import random
from datetime import datetime, timezone

import pytest

from astp.core.schema import (
    EpisodeStatus,
    G1_FROZEN_STATES,
    ORDERING_VERSION_CURRENT,
    ORDERING_VERSION_LEGACY,
    SPINE_ALGORITHM_VERSION_CURRENT,
    AriadneGovernanceError,
    compute_episode_root_hash,
    compute_exclusion_hash,
    compute_signal_manifest_hash,
    compute_spine_hash,
    compute_spine_root_v2,
    enforce_G1_write_guard,
    sha3_256,
)
from astp.core.crystallization import (
    CrystallizationScope,
    EpisodeVersionVector,
    build_crystallization_delta,
    compute_crystallization_content_hash,
)
from astp.protocol.node import CognitiveNode


def _h(i: int) -> str:
    return sha3_256(f"leaf-{i}".encode())


SEGMENTS = [_h(i) for i in range(7)]
SIGNALS = [_h(100 + i) for i in range(5)]
EPISODE = "550e8400-e29b-41d4-a716-446655440000"


class TestRP001SpineRootFromStoredNodesOnly:
    """RP-001 — the v2 spine root depends on segment hashes in sequence_index
    order and nothing else. Two verifiers holding the same stored nodes agree."""

    def test_deterministic_across_calls(self):
        a = compute_spine_root_v2(SEGMENTS, episode_id=EPISODE)
        b = compute_spine_root_v2(list(SEGMENTS), episode_id=EPISODE)
        assert a == b and len(a) == 64

    def test_signals_do_not_enter_the_spine(self):
        """The v1 form folded signals into the leaf set; v2 must not."""
        v2 = compute_spine_root_v2(SEGMENTS, episode_id=EPISODE)
        v1_with_signals = compute_spine_hash(SEGMENTS, SIGNALS)
        assert v2 != v1_with_signals
        # v2 equals the adaptive tree over segments alone
        from astp.core.merkle import compute_adaptive_spine_hash
        assert v2 == compute_adaptive_spine_hash(SEGMENTS, [], episode_id=EPISODE)[0]

    def test_sequence_order_is_binding(self):
        shuffled = SEGMENTS[:]
        random.Random(7).shuffle(shuffled)
        assert compute_spine_root_v2(shuffled, episode_id=EPISODE) != compute_spine_root_v2(SEGMENTS, episode_id=EPISODE)

    def test_empty_leaf_set_refused(self):
        with pytest.raises(ValueError):
            compute_spine_root_v2([], episode_id=EPISODE)


class TestRP002SignalManifestIsASet:
    """RP-002 — arrival order, timestamps and ties play no part in the manifest."""

    def test_order_independent(self):
        a = compute_signal_manifest_hash(SIGNALS)
        for seed in range(5):
            s = SIGNALS[:]
            random.Random(seed).shuffle(s)
            assert compute_signal_manifest_hash(s) == a

    def test_duplicates_collapse_and_membership_binds(self):
        assert compute_signal_manifest_hash(SIGNALS + [SIGNALS[0]]) == compute_signal_manifest_hash(SIGNALS)
        assert compute_signal_manifest_hash(SIGNALS[:-1]) != compute_signal_manifest_hash(SIGNALS)

    def test_empty_manifest_is_well_defined_and_distinct_from_empty_exclusion(self):
        assert compute_signal_manifest_hash([]) != compute_exclusion_hash([])
        assert len(compute_signal_manifest_hash([])) == 64

    def test_episode_root_composes_three_components(self):
        spine = compute_spine_root_v2(SEGMENTS, episode_id=EPISODE)
        root = compute_episode_root_hash(spine, compute_signal_manifest_hash(SIGNALS), compute_exclusion_hash([]))
        # changing any component changes the root
        assert root != compute_episode_root_hash(spine, compute_signal_manifest_hash(SIGNALS[:-1]), compute_exclusion_hash([]))
        assert root != compute_episode_root_hash(spine, compute_signal_manifest_hash(SIGNALS), compute_exclusion_hash([_h(9)]))


class TestRP003VersionTagsSelectTheFunction:
    """RP-003 — a seal record carries which algorithm/ordering produced its root;
    the tags live outside the content-hash preimage so they cannot make a bad
    root verify, and a record without tags is read as legacy."""

    def _delta(self, **kw):
        from uuid import UUID
        return build_crystallization_delta(
            episode_id=UUID(EPISODE),
            predecessor_hash=sha3_256(b"GENESIS"),
            sealed_chain_root=compute_spine_root_v2(SEGMENTS, episode_id=EPISODE),
            verification_authority="verifier",
            chain_position=1,
            version_vector=EpisodeVersionVector(content_version=len(SEGMENTS) + len(SIGNALS), lifecycle_version=0, chain_version=0),
            schema_version="2.0.0",
            crystallization_scope=CrystallizationScope.EPISODE,
            **kw,
        )

    def test_tags_are_recorded_and_default_to_none(self):
        tagged = self._delta(spine_algorithm_version=SPINE_ALGORITHM_VERSION_CURRENT, ordering_version=ORDERING_VERSION_CURRENT)
        legacy = self._delta()
        assert tagged.content.spine_algorithm_version == 1 and tagged.content.ordering_version == 2
        assert legacy.content.spine_algorithm_version is None and legacy.content.ordering_version is None
        assert ORDERING_VERSION_LEGACY == 1

    def test_tags_are_outside_the_content_hash_preimage(self):
        legacy = self._delta().content
        tagged = legacy.model_copy(update={"spine_algorithm_version": 1, "ordering_version": 2})
        assert (tagged.spine_algorithm_version, tagged.ordering_version) == (1, 2)
        assert compute_crystallization_content_hash(tagged) == compute_crystallization_content_hash(legacy)

    def test_cognitive_node_carries_hash_version_outside_leaf_preimage(self):
        from astp.protocol.leaf_hash import compute_leaf_hash_from_node
        base = dict(node_type="segment", sequence_index=3, content_hash=_h(1), authored_by="a",
                    created_at=datetime(2026, 9, 13, tzinfo=timezone.utc), payload={})
        n1 = CognitiveNode(**base)
        n2 = CognitiveNode(**base, hash_version=7)
        n2.node_id = n1.node_id
        assert n1.hash_version == 1
        assert compute_leaf_hash_from_node(n1) == compute_leaf_hash_from_node(n2)


# RP-004's fixed and open states, as CONFORMANCE-REPRODUCIBILITY.md lists them.
# Deliberately spelled out here rather than derived from G1_FROZEN_STATES, so
# the vector checks the guard against the document and not against itself.
RP004_FIXED_STATES = [
    EpisodeStatus.CLOSING_PENDING_SEAL,
    EpisodeStatus.CLOSED,
    EpisodeStatus.CRYSTALLIZATION_PENDING,
    EpisodeStatus.SEALING,
    EpisodeStatus.SEALED,
    EpisodeStatus.ARCHIVED,
]
RP004_OPEN_STATES = [
    EpisodeStatus.CREATED,
    EpisodeStatus.ACTIVE,
    EpisodeStatus.PENDING_HITL,
    EpisodeStatus.CLOSING,
    EpisodeStatus.CRYSTALLIZED,
]


class TestRP004FixedRecordRefusesContent:
    """RP-004 — G-1 refuses appends to an Episode whose record is fixed:
    CLOSING_PENDING_SEAL onward, CLOSED included."""

    @pytest.mark.parametrize("state", RP004_FIXED_STATES)
    def test_frozen_states_refuse(self, state):
        with pytest.raises(AriadneGovernanceError):
            enforce_G1_write_guard(state)

    @pytest.mark.parametrize("state", RP004_OPEN_STATES)
    def test_open_states_admit(self, state):
        enforce_G1_write_guard(state)

    def test_fixed_and_open_partition_the_lifecycle(self):
        fixed, open_ = set(RP004_FIXED_STATES), set(RP004_OPEN_STATES)
        assert fixed | open_ == set(EpisodeStatus)
        assert fixed & open_ == set()

    def test_guard_constant_matches_the_vector(self):
        assert set(G1_FROZEN_STATES) == set(RP004_FIXED_STATES)

    def test_closed_is_frozen(self):
        assert EpisodeStatus.CLOSED in G1_FROZEN_STATES
