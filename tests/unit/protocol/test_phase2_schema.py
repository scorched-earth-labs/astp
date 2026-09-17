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
Phase 2 — Schema Unit Tests

Verify Phase 2 schema types (ForkPoint, MergePoint, BranchReturnEdge,
ConflictManifest) instantiate cleanly, hashes are deterministic with
domain separation, and governance rules reject invalid inputs.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from astp.core.branching import (
    AriadneGovernanceError,
    BranchReturnEdge,
    ConflictManifest,
    ConflictResolution,
    ConflictSegment,
    ForkCreatedDelta,
    ForkPointNode,
    ForkResolvedDelta,
    MergeExecutedDelta,
    MergePointNode,
    MergeStrategy,
    MergeType,
    compute_conflict_manifest_hash,
    compute_fork_point_hash,
    compute_merge_point_hash,
    enforce_fork_objective_required,
    enforce_fork_sibling_count,
    enforce_merge_summary_required,
)


class TestForkPointNode:
    def test_instantiates_with_required_fields(self):
        fp = ForkPointNode(
            fork_id=uuid4(),
            episode_id=uuid4(),
            origin_episode_id=uuid4(),
            origin_segment_id="seg-123",
            fork_objective="Explore option B",
            fork_intent="Objective diverges from parent",
            initiator="agent-clotho",
            sibling_count=2,
            sibling_index=0,
        )
        assert fp.sibling_count == 2
        assert fp.sibling_index == 0
        assert fp.content_hash == ""  # Filled in by hash step

    def test_siblings_share_fork_id(self):
        shared = uuid4()
        fp0 = ForkPointNode(
            fork_id=shared,
            episode_id=uuid4(),
            origin_episode_id=uuid4(),
            origin_segment_id="s",
            fork_objective="obj",
            fork_intent="int",
            initiator="a",
            sibling_count=2,
            sibling_index=0,
        )
        fp1 = ForkPointNode(
            fork_id=shared,
            episode_id=uuid4(),
            origin_episode_id=uuid4(),
            origin_segment_id="s",
            fork_objective="obj",
            fork_intent="int",
            initiator="a",
            sibling_count=2,
            sibling_index=1,
        )
        assert fp0.fork_id == fp1.fork_id
        assert fp0.fork_point_id != fp1.fork_point_id


class TestMergePointNode:
    def test_all_three_merkle_roots_required(self):
        mp = MergePointNode(
            source_episode_id="s-ep",
            source_branch_id="s-br",
            target_episode_id="t-ep",
            merge_type=MergeType.CLEAN,
            source_merkle_root="src-root",
            target_merkle_root_pre="pre-root",
            target_merkle_root_post="post-root",
            common_ancestor_id="anc-seg",
            initiator="agent",
        )
        assert mp.source_merkle_root == "src-root"
        assert mp.target_merkle_root_pre == "pre-root"
        assert mp.target_merkle_root_post == "post-root"


class TestHashDomainSeparation:
    def test_fork_point_hash_deterministic(self):
        ts = datetime(2026, 4, 21, tzinfo=timezone.utc).isoformat()
        h1 = compute_fork_point_hash(
            "fp", "fork", "ep", "orig", "seg",
            "obj", "init", 0, ts, "parent",
        )
        h2 = compute_fork_point_hash(
            "fp", "fork", "ep", "orig", "seg",
            "obj", "init", 0, ts, "parent",
        )
        assert h1 == h2
        assert len(h1) == 64  # SHA3-256 hex

    def test_merge_point_hash_binds_all_three_roots(self):
        ts = datetime.now(timezone.utc).isoformat()
        h_base = compute_merge_point_hash(
            "mp", "m", "s", "t", "src", "pre", "post", "anc", ts, "p"
        )
        # Changing ANY Merkle root changes the hash
        h_src = compute_merge_point_hash(
            "mp", "m", "s", "t", "SRC", "pre", "post", "anc", ts, "p"
        )
        h_pre = compute_merge_point_hash(
            "mp", "m", "s", "t", "src", "PRE", "post", "anc", ts, "p"
        )
        h_post = compute_merge_point_hash(
            "mp", "m", "s", "t", "src", "pre", "POST", "anc", ts, "p"
        )
        assert h_base != h_src
        assert h_base != h_pre
        assert h_base != h_post

    def test_fork_point_and_merge_point_use_different_domains(self):
        ts = datetime.now(timezone.utc).isoformat()
        # Identical preimages (structurally) produce different hashes
        # because of the domain prefix.
        fp_hash = compute_fork_point_hash(
            "x", "x", "x", "x", "x", "x", "x", 0, ts, "x"
        )
        mp_hash = compute_merge_point_hash(
            "x", "x", "x", "x", "x", "x", "x", "x", ts, "x"
        )
        assert fp_hash != mp_hash

    def test_conflict_manifest_hash_order_independent(self):
        h1 = compute_conflict_manifest_hash("m", "s", "t", ["seg-b", "seg-a"])
        h2 = compute_conflict_manifest_hash("m", "s", "t", ["seg-a", "seg-b"])
        assert h1 == h2


class TestGovernanceRules:
    def test_fork_objective_required(self):
        with pytest.raises(AriadneGovernanceError):
            enforce_fork_objective_required(None)
        with pytest.raises(AriadneGovernanceError):
            enforce_fork_objective_required("")
        with pytest.raises(AriadneGovernanceError):
            enforce_fork_objective_required("   ")
        enforce_fork_objective_required("valid")  # no raise

    def test_fork_sibling_count_minimum_two(self):
        with pytest.raises(AriadneGovernanceError):
            enforce_fork_sibling_count(0)
        with pytest.raises(AriadneGovernanceError):
            enforce_fork_sibling_count(1)
        enforce_fork_sibling_count(2)  # no raise
        enforce_fork_sibling_count(5)  # no raise

    def test_merge_summary_required(self):
        with pytest.raises(AriadneGovernanceError):
            enforce_merge_summary_required(None)
        with pytest.raises(AriadneGovernanceError):
            enforce_merge_summary_required("")
        enforce_merge_summary_required("synthesis")  # no raise


class TestConflictManifest:
    def test_manifest_carries_all_merkle_context(self):
        m = ConflictManifest(
            source_episode_id="s",
            target_episode_id="t",
            common_ancestor_id="anc",
            conflicts=[
                ConflictSegment(
                    segment_id="seg-1",
                    ancestor_content_hash="a",
                    source_content_hash="b",
                    target_content_hash="c",
                )
            ],
            source_merkle_root="src-root",
            target_merkle_root_pre="pre-root",
        )
        assert len(m.conflicts) == 1
        assert m.source_merkle_root == "src-root"
        # target_merkle_root_post is deliberately absent — merge did not proceed


class TestDeltaPayloads:
    def test_fork_created_delta_has_forward_and_reverse(self):
        d = ForkCreatedDelta(
            origin_episode_id="ep",
            origin_segment_id="seg",
            fork_id="fork",
            fork_objective="obj",
            fork_intent="int",
            fork_point_ids=["fp1", "fp2"],
            reverse_delete_fork_id="fork",
            reverse_delete_fork_point_ids=["fp1", "fp2"],
        )
        assert d.fork_point_ids == ["fp1", "fp2"]
        assert d.reverse_delete_fork_id == "fork"

    def test_merge_executed_delta_records_all_three_roots(self):
        d = MergeExecutedDelta(
            source_episode_id="s",
            target_episode_id="t",
            merge_id="m",
            merge_type=MergeType.CLEAN,
            source_merkle_root="src",
            target_merkle_root_pre="pre",
            target_merkle_root_post="post",
            reverse_split_to_source_branches=["br"],
            reverse_clear_merge_record="m",
        )
        assert d.source_merkle_root == "src"
        assert d.target_merkle_root_pre == "pre"
        assert d.target_merkle_root_post == "post"


class TestMergeTypeEnum:
    def test_all_merge_types_exist(self):
        assert MergeType.CLEAN.value == "CLEAN"
        assert MergeType.RESOLVED.value == "RESOLVED"
        assert MergeType.PARTIAL.value == "PARTIAL"

    def test_all_merge_strategies_exist(self):
        assert MergeStrategy.AUTO.value == "AUTO"
        assert MergeStrategy.MANUAL_REVIEW.value == "MANUAL_REVIEW"
        assert MergeStrategy.AGENT_RESOLVED.value == "AGENT_RESOLVED"
        assert MergeStrategy.CONCLUSION_ONLY.value == "CONCLUSION_ONLY"


class TestBranchReturnEdge:
    def test_links_terminus_to_merge_point(self):
        e = BranchReturnEdge(
            branch_id="br",
            terminus_id="term",
            merge_point_id="mp",
            target_episode_id="t",
            synthesis_summary="merged cleanly",
            nodes_integrated=3,
        )
        assert e.branch_id == "br"
        assert e.nodes_integrated == 3
