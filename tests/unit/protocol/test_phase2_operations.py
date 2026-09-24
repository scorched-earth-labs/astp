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
Phase 2 — Operations Unit Tests

Exercises create_fork, resolve_fork, execute_merge, verify_merge_integrity
against the in-memory reference store (``astp.adapters.memory.InMemoryStore``). Verifies:
  - all three writes happen per spec (structural node + delta + audit)
  - AUTO strategy returns ConflictManifest, does not write merge records
  - resolutions allow merge to commit with RESOLVED type
  - three Merkle roots are captured and integrity verifier agrees
  - MERGED terminus carries branch_point_hash integrity link
  - fork siblings share fork_id; resolve promotes one, discards others
"""

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

import pytest

from astp.adapters.memory import InMemoryStore
from astp.core import branch_operations
from astp.core.branching import (
    ASTPGovernanceError,
    ConflictManifest,
    MergeResult,
    MergeType,
)


# ── Fixtures ───────────────────────────────────────────────────────────────


def _make_store_with_episodes(eids: List[str]) -> InMemoryStore:
    s = InMemoryStore()
    for eid in eids:
        s.episodes[eid] = {"episode_id": eid, "episode_status": "ACTIVE", "spine_hash": f"spine-{eid[:8]}"}
        # One spine leaf per Episode: merge roots are live spine roots (2.2.0),
        # computed from Segments, not read from a stored spine hash.
        sid = str(uuid4())
        s.segments[sid] = {"segment_id": sid, "episode_id": eid, "sequence_index": 0,
                           "content_hash": hashlib.sha3_256(eid.encode()).hexdigest(), "retention_tier": "PERSISTENT"}
    return s


def _make_branch(store: InMemoryStore, parent_episode_id: str,
                 branch_id: str = None, segment_id: str = "seg-parent") -> Dict:
    """Simulate an existing BranchPoint in the store."""
    bp_id = str(uuid4())
    bid = branch_id or str(uuid4())
    bp = {
        "branch_point_id": bp_id,
        "branch_id": bid,
        "episode_id": parent_episode_id,
        "parent_episode_id": parent_episode_id,
        "source_segment_id": segment_id,
        "branch_type": "exploratory",
        "branch_depth": 1,
        "declaration_type": "explicit",
        "trigger_context": "human_explicit",
        "initiated_by": "test-agent",
        "spine_merkle_snapshot": f"spine-{parent_episode_id[:8]}",
        "content_hash": f"bp-content-{bp_id[:8]}",
        "parent_hash": "",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    store.branch_points[bp_id] = bp
    return bp


# ── Tests: create_fork ─────────────────────────────────────────────────────


class TestCreateFork:
    def test_writes_n_fork_points_sharing_fork_id(self):
        eid = str(uuid4())
        store = _make_store_with_episodes([eid])

        result = branch_operations.create_fork(
            store,
            origin_episode_id=eid,
            origin_segment_id="seg-1",
            fork_objective="Explore two paths",
            fork_intent="objectives diverge",
            alternatives=[
                {"participants": ["agent-a"]},
                {"participants": ["agent-b"]},
                {"participants": ["agent-c"]},
            ],
            initiator="test",
        )

        assert result is not None
        assert len(result.fork_point_ids) == 3
        # All siblings share fork_id
        fork_ids = {store.fork_points[fp]["fork_id"] for fp in result.fork_point_ids}
        assert fork_ids == {result.fork_id}
        # Each has a distinct sibling_index
        indices = sorted(
            store.fork_points[fp]["sibling_index"] for fp in result.fork_point_ids
        )
        assert indices == [0, 1, 2]

    def test_writes_fork_created_audit_record(self):
        eid = str(uuid4())
        store = _make_store_with_episodes([eid])

        branch_operations.create_fork(
            store,
            origin_episode_id=eid,
            origin_segment_id="seg-1",
            fork_objective="obj",
            fork_intent="int",
            alternatives=[{}, {}],
        )

        fork_audits = [
            a for a in store.audit_records
            if a.get("delta_type") == "FORK_CREATED"
        ]
        assert len(fork_audits) == 1
        assert fork_audits[0]["episode_id"] == eid
        assert fork_audits[0]["delta_sequence"] == 1
        # Chain hash present
        assert fork_audits[0]["record_hash"]
        assert fork_audits[0]["prior_audit_hash"] == "GENESIS"

    def test_rejects_single_alternative(self):
        eid = str(uuid4())
        store = _make_store_with_episodes([eid])

        with pytest.raises(ASTPGovernanceError):
            branch_operations.create_fork(
                store,
                origin_episode_id=eid,
                origin_segment_id="s",
                fork_objective="obj",
                fork_intent="int",
                alternatives=[{}],  # Only 1 — must be at least 2
            )

    def test_rejects_empty_fork_objective(self):
        eid = str(uuid4())
        store = _make_store_with_episodes([eid])

        with pytest.raises(ASTPGovernanceError):
            branch_operations.create_fork(
                store,
                origin_episode_id=eid,
                origin_segment_id="s",
                fork_objective="",
                fork_intent="int",
                alternatives=[{}, {}],
            )


# ── Tests: resolve_fork ────────────────────────────────────────────────────


class TestResolveFork:
    def test_promotes_selected_discards_others(self):
        eid = str(uuid4())
        store = _make_store_with_episodes([eid])

        fork_result = branch_operations.create_fork(
            store,
            origin_episode_id=eid,
            origin_segment_id="s",
            fork_objective="obj",
            fork_intent="int",
            alternatives=[{}, {}, {}],
        )
        selected = fork_result.fork_point_ids[1]

        result = branch_operations.resolve_fork(
            store,
            fork_id=fork_result.fork_id,
            selected_fork_point_id=selected,
            resolution_rationale="option B showed best coherence",
        )

        assert result is not None
        assert result.selected_fork_point_id == selected
        assert len(result.discarded_fork_point_ids) == 2

        # Statuses updated in store
        assert store.fork_points[selected]["fork_status"] == "PROMOTED"
        for fpid in result.discarded_fork_point_ids:
            assert store.fork_points[fpid]["fork_status"] == "DISCARDED"

        # FORK_RESOLVED audit written
        resolved_audits = [
            a for a in store.audit_records
            if a.get("delta_type") == "FORK_RESOLVED"
        ]
        assert len(resolved_audits) == 1

    def test_rejects_empty_rationale(self):
        eid = str(uuid4())
        store = _make_store_with_episodes([eid])
        fork_result = branch_operations.create_fork(
            store, origin_episode_id=eid, origin_segment_id="s",
            fork_objective="obj", fork_intent="int",
            alternatives=[{}, {}],
        )

        with pytest.raises(ASTPGovernanceError):
            branch_operations.resolve_fork(
                store,
                fork_id=fork_result.fork_id,
                selected_fork_point_id=fork_result.fork_point_ids[0],
                resolution_rationale="",
            )


# ── Tests: execute_merge ───────────────────────────────────────────────────


class TestExecuteMergeClean:
    def test_clean_merge_writes_all_three_records(self):
        eid = str(uuid4())
        store = _make_store_with_episodes([eid])

        bp = _make_branch(store, eid)

        result = branch_operations.execute_merge(
            store,
            source_branch_id=bp["branch_id"],
            target_episode_id=eid,
            merge_summary="clean synthesis of branch work",
            initiator="test",
            merge_strategy="MANUAL_REVIEW",
        )

        assert isinstance(result, MergeResult)
        assert result.merge_type == MergeType.CLEAN
        # All three Merkle roots populated
        assert result.source_merkle_root
        assert result.target_merkle_root_pre
        assert result.target_merkle_root_post
        # Target pre != post (post is derived)
        assert result.target_merkle_root_pre != result.target_merkle_root_post

        # MergePoint written
        assert len(store.merge_points) == 1
        mp = list(store.merge_points.values())[0]
        assert mp["source_merkle_root"] == result.source_merkle_root
        assert mp["target_merkle_root_pre"] == result.target_merkle_root_pre
        assert mp["target_merkle_root_post"] == result.target_merkle_root_post

        # BranchTerminus written with MERGED type + integrity link
        merged_termini = [
            t for t in store.branch_termini.values()
            if t.get("terminus_type") == "merged"
        ]
        assert len(merged_termini) == 1
        assert merged_termini[0]["branch_point_hash"] == bp["content_hash"]

        # MERGE_EXECUTED audit
        merge_audits = [
            a for a in store.audit_records
            if a.get("delta_type") == "MERGE_EXECUTED"
        ]
        assert len(merge_audits) == 1


class TestExecuteMergeConflictSurface:
    def test_auto_returns_manifest_on_conflicts_even_with_resolutions(self):
        eid = str(uuid4())
        store = _make_store_with_episodes([eid])
        bp = _make_branch(store, eid)

        conflicts = [{
            "segment_id": "seg-x",
            "ancestor_content_hash": "a",
            "source_content_hash": "b",
            "target_content_hash": "c",
        }]
        resolutions = [{
            "segment_id": "seg-x",
            "resolution_type": "TAKE_SOURCE",
            "resolved_content_hash": "b",
            "resolver": "agent",
        }]

        result = branch_operations.execute_merge(
            store,
            source_branch_id=bp["branch_id"],
            target_episode_id=eid,
            merge_summary="attempted auto",
            merge_strategy="AUTO",  # AUTO never resolves silently
            conflict_segments=conflicts,
            conflict_resolutions=resolutions,
        )

        assert isinstance(result, ConflictManifest)
        # No MergePoint written
        assert len(store.merge_points) == 0
        # No MERGE_EXECUTED audit
        assert not any(
            a.get("delta_type") == "MERGE_EXECUTED"
            for a in store.audit_records
        )

    def test_conflicts_without_resolutions_returns_manifest(self):
        eid = str(uuid4())
        store = _make_store_with_episodes([eid])
        bp = _make_branch(store, eid)

        conflicts = [{
            "segment_id": "seg-x",
            "ancestor_content_hash": "a",
            "source_content_hash": "b",
            "target_content_hash": "c",
        }]

        result = branch_operations.execute_merge(
            store,
            source_branch_id=bp["branch_id"],
            target_episode_id=eid,
            merge_summary="no resolutions supplied",
            merge_strategy="MANUAL_REVIEW",
            conflict_segments=conflicts,
            conflict_resolutions=[],  # Unresolved
        )

        assert isinstance(result, ConflictManifest)
        assert len(result.conflicts) == 1
        assert len(store.merge_points) == 0

    def test_manual_review_with_resolutions_commits_as_resolved(self):
        eid = str(uuid4())
        store = _make_store_with_episodes([eid])
        bp = _make_branch(store, eid)

        conflicts = [{
            "segment_id": "seg-x",
            "ancestor_content_hash": "a",
            "source_content_hash": "b",
            "target_content_hash": "c",
        }]
        resolutions = [{
            "segment_id": "seg-x",
            "resolution_type": "CUSTOM",
            "resolved_content_hash": "d-synthesis",
            "resolver": "human",
            "rationale": "merged both perspectives",
        }]

        result = branch_operations.execute_merge(
            store,
            source_branch_id=bp["branch_id"],
            target_episode_id=eid,
            merge_summary="resolved conflicts by hand",
            merge_strategy="MANUAL_REVIEW",
            conflict_segments=conflicts,
            conflict_resolutions=resolutions,
        )

        assert isinstance(result, MergeResult)
        assert result.merge_type == MergeType.RESOLVED


# ── Tests: verify_merge_integrity ──────────────────────────────────────────


class TestMergeIntegrity:
    def test_integrity_holds_for_clean_merge(self):
        eid = str(uuid4())
        store = _make_store_with_episodes([eid])
        bp = _make_branch(store, eid)

        merge_result = branch_operations.execute_merge(
            store,
            source_branch_id=bp["branch_id"],
            target_episode_id=eid,
            merge_summary="clean",
            merge_strategy="MANUAL_REVIEW",
        )

        integrity = branch_operations.verify_merge_integrity(
            store, merge_result.merge_id
        )
        assert integrity is not None
        assert integrity.source_valid is True
        assert integrity.target_pre_valid is True
        assert integrity.target_post_valid is True
        assert integrity.integrity_holds is True


# ── Tests: audit chain continuity ──────────────────────────────────────────


class TestAuditChainContinuity:
    def test_fork_then_resolve_chains_correctly(self):
        eid = str(uuid4())
        store = _make_store_with_episodes([eid])

        fork_result = branch_operations.create_fork(
            store, origin_episode_id=eid, origin_segment_id="s",
            fork_objective="obj", fork_intent="int",
            alternatives=[{}, {}],
        )
        branch_operations.resolve_fork(
            store,
            fork_id=fork_result.fork_id,
            selected_fork_point_id=fork_result.fork_point_ids[0],
            resolution_rationale="winner",
        )

        audits = sorted(
            store.audit_records, key=lambda a: a.get("delta_sequence", 0)
        )
        assert len(audits) == 2
        assert audits[0]["delta_type"] == "FORK_CREATED"
        assert audits[0]["delta_sequence"] == 1
        assert audits[1]["delta_type"] == "FORK_RESOLVED"
        assert audits[1]["delta_sequence"] == 2
        # Chain link: second record's prior_audit_hash == first's record_hash
        assert audits[1]["prior_audit_hash"] == audits[0]["record_hash"]


class TestCreateDepartureFork:
    """Phase D — the single directional departure fork (origin continues)."""

    def test_creates_episode_point_and_audit(self):
        oid = str(uuid4())
        store = _make_store_with_episodes([oid])

        result = branch_operations.create_departure_fork(
            store,
            origin_episode_id=oid,
            origin_segment_id="seg-1",
            fork_objective="Explore the DAG tangent",
            fork_creation_trigger="TOPIC_SHIFT",
            initiator="agent-a",
            fork_title="DAG tangent",
        )

        assert result is not None
        assert result.fork_id and result.fork_point_id and result.fork_episode_id
        # single departure point written (no siblings)
        assert len(store.departure_fork_points) == 1
        dp = store.departure_fork_points[result.fork_point_id]
        assert dp["fork_creation_trigger"] == "TOPIC_SHIFT"
        # the fork episode was created ACTIVE with provenance
        fe = store.episodes[result.fork_episode_id]
        assert fe["fork_status"] == "ACTIVE"
        assert fe["fork_origin_episode_id"] == oid
        # DEPARTURE_FORK_CREATED audit written
        dep_audits = [a for a in store.audit_records
                      if a.get("delta_type") == "DEPARTURE_FORK_CREATED"]
        assert len(dep_audits) == 1
        assert dep_audits[0]["record_hash"]

    def test_backdating_integrity_invariant(self):
        """spine_tip_hash_at_departure (point) == fork_origin_spine_tip_hash (episode)."""
        oid = str(uuid4())
        store = _make_store_with_episodes([oid])
        result = branch_operations.create_departure_fork(
            store, origin_episode_id=oid, origin_segment_id="seg-1",
            fork_objective="obj", fork_creation_trigger="PARALLEL_THREAD", initiator="x",
        )
        dp = store.departure_fork_points[result.fork_point_id]
        fe = store.episodes[result.fork_episode_id]
        assert dp["spine_tip_hash_at_departure"] == fe["fork_origin_spine_tip_hash"]
        assert result.spine_tip_hash_at_departure == dp["spine_tip_hash_at_departure"]

    def test_origin_episode_continues_untouched(self):
        """A departure does NOT resolve or alter the origin — it continues."""
        oid = str(uuid4())
        store = _make_store_with_episodes([oid])
        branch_operations.create_departure_fork(
            store, origin_episode_id=oid, origin_segment_id="seg-1",
            fork_objective="obj", fork_creation_trigger="EXPLICIT_FORK", initiator="x",
        )
        assert store.episodes[oid]["episode_status"] == "ACTIVE"  # origin unchanged

    def test_agent_escalation_requires_trigger_segment(self):
        oid = str(uuid4())
        store = _make_store_with_episodes([oid])
        # missing fork_trigger_segment_id → governance error
        with pytest.raises(ASTPGovernanceError):
            branch_operations.create_departure_fork(
                store, origin_episode_id=oid, origin_segment_id="seg-1",
                fork_objective="obj", fork_creation_trigger="AGENT_ESCALATION", initiator="agent-a",
            )
        # with the trigger segment → succeeds
        result = branch_operations.create_departure_fork(
            store, origin_episode_id=oid, origin_segment_id="seg-1",
            fork_objective="obj", fork_creation_trigger="AGENT_ESCALATION",
            initiator="agent-a", fork_trigger_segment_id="seg-trigger",
        )
        assert result is not None

    def test_idempotent_on_repeat(self):
        oid = str(uuid4())
        store = _make_store_with_episodes([oid])
        kw = dict(origin_episode_id=oid, origin_segment_id="seg-1",
                  fork_objective="same obj", fork_creation_trigger="TOPIC_SHIFT", initiator="x")
        r1 = branch_operations.create_departure_fork(store, **kw)
        r2 = branch_operations.create_departure_fork(store, **kw)
        assert r1 is not None and r2 is not None
        # second call short-circuits on the COMPLETE intent — no second departure point
        assert len(store.departure_fork_points) == 1

    def test_fork_anchor_index_patched_to_origin_segment_index(self):
        """STEP 6: fork_anchor_index (null at episode-create) is patched to the ORIGIN
        segment's sequence_index once the DepartureForkPointNode is written."""
        oid = str(uuid4())
        store = _make_store_with_episodes([oid])
        store.segments["seg-1"] = {"sequence_index": 7}
        result = branch_operations.create_departure_fork(
            store, origin_episode_id=oid, origin_segment_id="seg-1",
            fork_objective="obj", fork_creation_trigger="TOPIC_SHIFT", initiator="x",
        )
        assert store.episodes[result.fork_episode_id]["fork_anchor_index"] == 7

    def test_fork_anchor_index_null_when_origin_segment_unresolved(self):
        """No resolvable origin-segment index → anchor left null (point written, anchor
        unresolved) rather than a wrong value. The point is still written."""
        oid = str(uuid4())
        store = _make_store_with_episodes([oid])  # no segment seeded
        result = branch_operations.create_departure_fork(
            store, origin_episode_id=oid, origin_segment_id="seg-missing",
            fork_objective="obj", fork_creation_trigger="TOPIC_SHIFT", initiator="x",
        )
        assert store.episodes[result.fork_episode_id].get("fork_anchor_index") is None
        assert len(store.departure_fork_points) == 1

    def test_supplied_fork_id_is_used(self):
        """A caller may pin fork_id (retry/recovery); it flows through to the result + point."""
        oid = str(uuid4())
        store = _make_store_with_episodes([oid])
        pinned = str(uuid4())
        result = branch_operations.create_departure_fork(
            store, origin_episode_id=oid, origin_segment_id="seg-1",
            fork_objective="obj", fork_creation_trigger="TOPIC_SHIFT", initiator="x",
            fork_id=pinned,
        )
        assert result.fork_id == pinned
        assert str(store.departure_fork_points[result.fork_point_id]["fork_id"]) == pinned

    def test_supplied_fork_id_idempotent_no_duplicate(self):
        """Re-drive with a pinned fork_id whose point already exists short-circuits (STEP 2b)
        — no second departure point, even though the intent guard would not fire (fresh key)."""
        oid = str(uuid4())
        store = _make_store_with_episodes([oid])
        pinned = str(uuid4())
        pid = str(uuid4())
        store.departure_fork_points[pid] = {  # a prior attempt's already-written point
            "fork_point_id": pid, "fork_id": pinned,
            "fork_episode_id": "fork-ep-x", "spine_tip_hash_at_departure": "tip-x",
        }
        result = branch_operations.create_departure_fork(
            store, origin_episode_id=oid, origin_segment_id="seg-1",
            fork_objective="a different objective", fork_creation_trigger="TOPIC_SHIFT",
            initiator="x", fork_id=pinned,
        )
        assert result.fork_id == pinned
        assert result.fork_point_id == pid            # returned the existing point
        assert result.fork_episode_id == "fork-ep-x"
        assert len(store.departure_fork_points) == 1        # no duplicate created

    def test_idempotent_replay_returns_full_result(self):
        """The intent-COMPLETE replay reconstructs the FULL original result (point + episode
        + tip), not a degraded empty shell."""
        oid = str(uuid4())
        store = _make_store_with_episodes([oid])
        kw = dict(origin_episode_id=oid, origin_segment_id="seg-1",
                  fork_objective="same obj", fork_creation_trigger="TOPIC_SHIFT", initiator="x")
        r1 = branch_operations.create_departure_fork(store, **kw)
        r2 = branch_operations.create_departure_fork(store, **kw)
        assert r2.fork_id == r1.fork_id
        assert r2.fork_point_id == r1.fork_point_id and r2.fork_point_id
        assert r2.fork_episode_id == r1.fork_episode_id and r2.fork_episode_id
        assert r2.spine_tip_hash_at_departure == r1.spine_tip_hash_at_departure


class TestDepartureForkFSM:
    """Phase D FSM ops: complete / abandon / declare_fork_return."""

    def _make_active_fork(self, store):
        oid = str(uuid4())
        store.episodes[oid] = {"episode_id": oid, "episode_status": "ACTIVE", "spine_hash": f"spine-{oid[:8]}"}
        res = branch_operations.create_departure_fork(
            store, origin_episode_id=oid, origin_segment_id="seg-1",
            fork_objective="tangent", fork_creation_trigger="TOPIC_SHIFT", initiator="a",
        )
        return oid, res, store

    def test_complete_transitions_active_to_completed(self):
        store = InMemoryStore()
        _oid, res, store = self._make_active_fork(store)
        ok = branch_operations.complete_departure_fork(store, res.fork_episode_id, actor="fork-agent")
        assert ok is True
        assert store.episodes[res.fork_episode_id]["fork_status"] == "COMPLETED"
        assert any(a.get("delta_type") == "DEPARTURE_FORK_COMPLETED" for a in store.audit_records)

    def test_abandon_transitions_active_to_abandoned(self):
        store = InMemoryStore()
        _oid, res, store = self._make_active_fork(store)
        ok = branch_operations.abandon_departure_fork(store, res.fork_episode_id, actor="origin-agent")
        assert ok is True
        assert store.episodes[res.fork_episode_id]["fork_status"] == "ABANDONED"
        assert any(a.get("delta_type") == "DEPARTURE_FORK_ABANDONED" for a in store.audit_records)

    def test_cannot_abandon_a_completed_fork(self):
        store = InMemoryStore()
        _oid, res, store = self._make_active_fork(store)
        branch_operations.complete_departure_fork(store, res.fork_episode_id)
        ok = branch_operations.abandon_departure_fork(store, res.fork_episode_id)
        assert ok is False  # COMPLETED forks return, they are not abandoned
        assert store.episodes[res.fork_episode_id]["fork_status"] == "COMPLETED"

    def test_declare_return_requires_completed(self):
        store = InMemoryStore()
        oid, res, store = self._make_active_fork(store)
        # fork is ACTIVE — return must be blocked
        with pytest.raises(ASTPGovernanceError):
            branch_operations.declare_fork_return(
                store, fork_id=res.fork_id, origin_episode_id=oid,
                return_type="INCORPORATED", returned_by="origin-agent",
            )

    def test_declare_return_writes_return_node_and_audit(self):
        store = InMemoryStore()
        oid, res, store = self._make_active_fork(store)
        branch_operations.complete_departure_fork(store, res.fork_episode_id)
        result = branch_operations.declare_fork_return(
            store, fork_id=res.fork_id, origin_episode_id=oid,
            return_type="INCORPORATED", returned_by="origin-agent",
            synthesis_summary="took the DAG insight",
        )
        assert result is not None
        assert result.return_type == "INCORPORATED"
        assert len(store.fork_returns) == 1
        assert any(a.get("delta_type") == "DEPARTURE_FORK_RETURNED" for a in store.audit_records)
        # return_type recorded on the fork episode
        assert store.episodes[res.fork_episode_id].get("fork_return_type") == "INCORPORATED"

    def test_no_double_return(self):
        store = InMemoryStore()
        oid, res, store = self._make_active_fork(store)
        branch_operations.complete_departure_fork(store, res.fork_episode_id)
        branch_operations.declare_fork_return(
            store, fork_id=res.fork_id, origin_episode_id=oid,
            return_type="ACKNOWLEDGED", returned_by="origin-agent",
        )
        with pytest.raises(ASTPGovernanceError):
            branch_operations.declare_fork_return(
                store, fork_id=res.fork_id, origin_episode_id=oid,
                return_type="INCORPORATED", returned_by="origin-agent",
            )
