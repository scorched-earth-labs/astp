"""
Phase 2 — Operations Unit Tests (driver-mocked)

Exercises create_fork, resolve_fork, execute_merge, verify_merge_integrity
against an in-memory fake Neo4j driver. Verifies:
  - all three writes happen per spec (structural node + delta + audit)
  - AUTO strategy returns ConflictManifest, does not write merge records
  - resolutions allow merge to commit with RESOLVED type
  - three Merkle roots are captured and integrity verifier agrees
  - MERGED terminus carries branch_point_hash integrity link
  - fork siblings share fork_id; resolve promotes one, discards others
"""

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4


os.environ["ARIADNE_ENABLED"] = "true"

# Must be set BEFORE importing writer.py — it reads the env at import time.
import importlib

from ariadne.adapters.neo4j import writer as ariadne_writer  # noqa: E402
importlib.reload(ariadne_writer)
# Force guard to True for this test module even if import order differed
ariadne_writer.ARIADNE_ENABLED = True

from ariadne.core import branch_operations  # noqa: E402
from ariadne.core.branching import (  # noqa: E402
    BranchDeclarationType,
    BranchType,
    ConflictManifest,
    MergeResult,
    MergeStrategy,
    MergeType,
    TriggerType,
)


# ── Fake Neo4j driver ───────────────────────────────────────────────────────


class FakeResult:
    def __init__(self, rows: List[Dict[str, Any]]):
        self._rows = rows

    def single(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class FakeSession:
    def __init__(self, store: "FakeStore"):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query: str, params: Dict[str, Any] = None):
        params = params or {}
        return self.store.run(query, params)


class FakeDriver:
    def __init__(self, store: "FakeStore"):
        self._store = store

    def session(self):
        return FakeSession(self._store)


class FakeStore:
    """Tracks Cypher calls and emulates the minimum queries the ops hit."""

    def __init__(self):
        self.calls: List[Dict[str, Any]] = []
        self.episodes: Dict[str, Dict[str, Any]] = {}
        self.branch_points: Dict[str, Dict[str, Any]] = {}
        self.branch_terminuses: List[Dict[str, Any]] = []
        self.fork_points: Dict[str, Dict[str, Any]] = {}
        self.departure_points: Dict[str, Dict[str, Any]] = {}  # Phase D
        self.fork_returns: Dict[str, Dict[str, Any]] = {}       # Phase D
        self.merge_points: Dict[str, Dict[str, Any]] = {}
        self.audit_records: List[Dict[str, Any]] = []
        self.intents: Dict[str, Dict[str, Any]] = {}  # by idempotency_key
        self.max_delta_sequence: Dict[str, int] = {}

    def _record_call(self, query: str, params: Dict[str, Any]):
        self.calls.append({"query": query, "params": params})

    def run(self, query: str, params: Dict[str, Any]):
        self._record_call(query, params)
        q = " ".join(query.split())

        # Episode status check
        if "MATCH (e:AriadneEpisode" in q and "RETURN e.episode_status" in q:
            eid = params.get("eid")
            ep = self.episodes.get(eid)
            if not ep:
                return FakeResult([])
            return FakeResult([{
                "status": ep.get("status", "ACTIVE"),
                "spine_hash": ep.get("spine_hash", ""),
            }])

        # Episode spine_hash only
        if "MATCH (e:AriadneEpisode" in q and "RETURN e.spine_hash" in q and "episode_status" not in q:
            eid = params.get("eid")
            ep = self.episodes.get(eid)
            if not ep:
                return FakeResult([])
            return FakeResult([{"spine_hash": ep.get("spine_hash", "")}])

        # BranchPoint load
        if "MATCH (bp:AriadneBranchPoint {branch_id: $bid})" in q:
            bid = params.get("bid")
            bp = self.branch_points.get(bid)
            has_terminus = any(
                t["branch_id"] == bid for t in self.branch_terminuses
            )
            if not bp:
                return FakeResult([])
            return FakeResult([{
                "branch_point": bp,
                "has_terminus": has_terminus,
            }])

        # BranchPoint for common ancestor lookup
        if ("MATCH (bp:AriadneBranchPoint {branch_id: $branch_id})" in q
                and "MATCH (e:AriadneEpisode {episode_id: $target_episode_id})" in q):
            bid = params.get("branch_id")
            tgt = params.get("target_episode_id")
            bp = self.branch_points.get(bid)
            if not bp or bp.get("parent_episode_id") != tgt:
                return FakeResult([])
            return FakeResult([{
                "ancestor_segment_id": bp.get("source_segment_id"),
                "branch_point_id": bp.get("branch_point_id"),
                "parent_episode_id": bp.get("parent_episode_id"),
                "anchor_merkle": bp.get("spine_merkle_snapshot"),
            }])

        # Load all fork points by fork_id
        if "MATCH (fp:AriadneForkPoint {fork_id: $fork_id})" in q and "RETURN fp.fork_point_id" in q:
            fork_id = params.get("fork_id")
            rows = [
                {
                    "fpid": fp["fork_point_id"],
                    "eid": fp["episode_id"],
                    "status": fp.get("fork_status", "ACTIVE"),
                    "origin_id": fp.get("origin_episode_id"),
                }
                for fp in self.fork_points.values()
                if fp["fork_id"] == fork_id
            ]
            return FakeResult(rows)

        # Create/Merge BranchPoint node
        if "MERGE (bp:AriadneBranchPoint" in q and "branch_point_id" in q:
            bpid = params.get("branch_point_id")
            if bpid and bpid not in self.branch_points:
                self.branch_points[params.get("branch_id")] = dict(params)
                self.branch_points[params.get("branch_id")]["branch_point_id"] = bpid
            return FakeResult([])

        # Create BranchTerminus
        if "MERGE (bt:AriadneBranchTerminus" in q:
            self.branch_terminuses.append(dict(params))
            return FakeResult([])

        # Create ForkPoint
        if "MERGE (fp:AriadneForkPoint" in q and "fork_point_id: $fork_point_id" in q:
            self.fork_points[params.get("fork_point_id")] = dict(params)
            self.fork_points[params.get("fork_point_id")]["fork_status"] = "ACTIVE"
            return FakeResult([])

        # Update ForkPoint status
        if "MATCH (fp:AriadneForkPoint {fork_point_id: $fork_point_id}) SET fp.fork_status" in q:
            fpid = params.get("fork_point_id")
            if fpid in self.fork_points:
                self.fork_points[fpid]["fork_status"] = params.get("status")
            return FakeResult([])

        # Create MergePoint
        if "MERGE (mp:AriadneMergePoint" in q and "merge_point_id: $merge_point_id" in q:
            self.merge_points[params.get("merge_point_id")] = dict(params)
            return FakeResult([])

        # Create AuditRecord
        if "MERGE (ar:AriadneAuditRecord" in q:
            self.audit_records.append(dict(params))
            return FakeResult([])

        # Get max delta_sequence
        if "RETURN max(ar.delta_sequence)" in q:
            eid = params.get("eid")
            relevant = [
                a["delta_sequence"]
                for a in self.audit_records
                if a.get("episode_id") == eid
            ]
            max_seq = max(relevant) if relevant else None
            return FakeResult([{"max_seq": max_seq}])

        # Get prior audit hash
        if "RETURN ar.record_hash AS hash" in q:
            eid = params.get("eid")
            relevant = sorted(
                (a for a in self.audit_records if a.get("episode_id") == eid),
                key=lambda x: x.get("delta_sequence", 0),
                reverse=True,
            )
            if relevant:
                return FakeResult([{"hash": relevant[0].get("record_hash", "GENESIS")}])
            return FakeResult([{"hash": None}])

        # Intent record lookup
        if "MATCH (ir:AriadneIntentRecord {idempotency_key: $key})" in q and "RETURN ir" in q:
            key = params.get("key")
            intent = self.intents.get(key)
            if intent:
                return FakeResult([{"intent": intent}])
            return FakeResult([])

        # Create intent
        if "MERGE (ir:AriadneIntentRecord {idempotency_key: $key})" in q:
            key = params.get("key")
            if key not in self.intents:
                self.intents[key] = {
                    "intent_id": params.get("intent_id"),
                    "intent_type": params.get("intent_type"),
                    "initiator_id": params.get("initiator_id"),
                    "status": "PENDING",
                    "idempotency_key": key,
                }
            return FakeResult([])

        # Complete intent
        if "MATCH (ir:AriadneIntentRecord {idempotency_key: $key}) WHERE ir.status = 'PENDING'" in q:
            key = params.get("key")
            if key in self.intents:
                self.intents[key]["status"] = "COMPLETE"
                self.intents[key]["result_node_id"] = params.get("result_node_id")
            return FakeResult([])

        # Retrieve MergePoint for integrity
        if "MATCH (mp:AriadneMergePoint {merge_id: $mid})" in q and "RETURN mp" in q:
            mid = params.get("mid")
            for mp in self.merge_points.values():
                if mp.get("merge_id") == mid:
                    return FakeResult([{"merge_point": mp}])
            return FakeResult([])

        # Retrieve MERGE_EXECUTED audit
        if "MATCH (ar:AriadneAuditRecord {delta_type: 'MERGE_EXECUTED'})" in q:
            mid = params.get("mid")
            for a in self.audit_records:
                if a.get("delta_type") == "MERGE_EXECUTED":
                    fd = a.get("forward_delta", "")
                    if mid in str(fd):
                        return FakeResult([{"fd": fd}])
            return FakeResult([])

        # Create DepartureForkPoint (Phase D)
        if "MERGE (fp:AriadneDepartureForkPoint" in q and "fork_point_id: $fork_point_id" in q:
            self.departure_points[params.get("fork_point_id")] = dict(params)
            return FakeResult([])

        # Create departure-fork Episode node (Phase D — MERGE with ON CREATE SET)
        if "MERGE (e:AriadneEpisode {episode_id: $episode_id}" in q and "fork_status" in q:
            self.episodes[params.get("episode_id")] = dict(params)
            return FakeResult([])

        # Read departure fork status by episode_id
        if "MATCH (e:AriadneEpisode {episode_id: $eid})" in q and "RETURN e.episode_id AS eid, e.fork_status AS st" in q:
            ep = self.episodes.get(params.get("eid"))
            if not ep:
                return FakeResult([])
            return FakeResult([{"eid": params.get("eid"), "st": ep.get("fork_status")}])

        # Read departure fork status by fork_id
        if "MATCH (e:AriadneEpisode {fork_id: $fid})" in q and "RETURN e.episode_id AS eid, e.fork_status AS st" in q:
            fid = params.get("fid")
            for eid, ep in self.episodes.items():
                if str(ep.get("fork_id")) == str(fid):
                    return FakeResult([{"eid": eid, "st": ep.get("fork_status")}])
            return FakeResult([])

        # Update departure fork status
        if "MATCH (e:AriadneEpisode {episode_id: $episode_id})" in q and "SET e.fork_status" in q:
            ep = self.episodes.get(params.get("episode_id"))
            if ep is not None:
                ep["fork_status"] = params.get("status")
            return FakeResult([])

        # Set fork_return_type on the fork episode
        if "MATCH (e:AriadneEpisode {episode_id: $eid})" in q and "SET e.fork_return_type" in q:
            ep = self.episodes.get(params.get("eid"))
            if ep is not None:
                ep["fork_return_type"] = params.get("rt")
            return FakeResult([])

        # Create ForkReturnNode (Phase D)
        if "MERGE (fr:AriadneForkReturn {fork_return_id: $fork_return_id})" in q:
            self.fork_returns[params.get("fork_return_id")] = dict(params)
            return FakeResult([])

        # Prior ForkReturn check by fork_id
        if "MATCH (fr:AriadneForkReturn {fork_id: $fid})" in q and "RETURN fr.fork_return_id" in q:
            fid = params.get("fid")
            for fr in self.fork_returns.values():
                if str(fr.get("fork_id")) == str(fid):
                    return FakeResult([{"id": fr.get("fork_return_id")}])
            return FakeResult([])

        # Catch-all: edges / WIL / other merges — silently succeed
        return FakeResult([])


# ── Fixtures ───────────────────────────────────────────────────────────────


def _make_store_with_episodes(eids: List[str]) -> FakeStore:
    s = FakeStore()
    for eid in eids:
        s.episodes[eid] = {"status": "ACTIVE", "spine_hash": f"spine-{eid[:8]}"}
    return s


def _make_branch(store: FakeStore, parent_episode_id: str,
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
    store.branch_points[bid] = bp
    return bp


# ── Tests: create_fork ─────────────────────────────────────────────────────


class TestCreateFork:
    def test_writes_n_fork_points_sharing_fork_id(self):
        eid = str(uuid4())
        store = _make_store_with_episodes([eid])
        driver = FakeDriver(store)

        result = branch_operations.create_fork(
            driver,
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
        driver = FakeDriver(store)

        branch_operations.create_fork(
            driver,
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
        driver = FakeDriver(store)

        import pytest
        from ariadne.core.branching import AriadneGovernanceError
        with pytest.raises(AriadneGovernanceError):
            branch_operations.create_fork(
                driver,
                origin_episode_id=eid,
                origin_segment_id="s",
                fork_objective="obj",
                fork_intent="int",
                alternatives=[{}],  # Only 1 — must be at least 2
            )

    def test_rejects_empty_fork_objective(self):
        eid = str(uuid4())
        store = _make_store_with_episodes([eid])
        driver = FakeDriver(store)

        import pytest
        from ariadne.core.branching import AriadneGovernanceError
        with pytest.raises(AriadneGovernanceError):
            branch_operations.create_fork(
                driver,
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
        driver = FakeDriver(store)

        fork_result = branch_operations.create_fork(
            driver,
            origin_episode_id=eid,
            origin_segment_id="s",
            fork_objective="obj",
            fork_intent="int",
            alternatives=[{}, {}, {}],
        )
        selected = fork_result.fork_point_ids[1]

        result = branch_operations.resolve_fork(
            driver,
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
        driver = FakeDriver(store)
        fork_result = branch_operations.create_fork(
            driver, origin_episode_id=eid, origin_segment_id="s",
            fork_objective="obj", fork_intent="int",
            alternatives=[{}, {}],
        )

        import pytest
        from ariadne.core.branching import AriadneGovernanceError
        with pytest.raises(AriadneGovernanceError):
            branch_operations.resolve_fork(
                driver,
                fork_id=fork_result.fork_id,
                selected_fork_point_id=fork_result.fork_point_ids[0],
                resolution_rationale="",
            )


# ── Tests: execute_merge ───────────────────────────────────────────────────


class TestExecuteMergeClean:
    def test_clean_merge_writes_all_three_records(self):
        eid = str(uuid4())
        store = _make_store_with_episodes([eid])
        driver = FakeDriver(store)

        bp = _make_branch(store, eid)

        result = branch_operations.execute_merge(
            driver,
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
            t for t in store.branch_terminuses
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
        driver = FakeDriver(store)
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
            driver,
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
        driver = FakeDriver(store)
        bp = _make_branch(store, eid)

        conflicts = [{
            "segment_id": "seg-x",
            "ancestor_content_hash": "a",
            "source_content_hash": "b",
            "target_content_hash": "c",
        }]

        result = branch_operations.execute_merge(
            driver,
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
        driver = FakeDriver(store)
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
            driver,
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
        driver = FakeDriver(store)
        bp = _make_branch(store, eid)

        merge_result = branch_operations.execute_merge(
            driver,
            source_branch_id=bp["branch_id"],
            target_episode_id=eid,
            merge_summary="clean",
            merge_strategy="MANUAL_REVIEW",
        )

        integrity = branch_operations.verify_merge_integrity(
            driver, merge_result.merge_id
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
        driver = FakeDriver(store)

        fork_result = branch_operations.create_fork(
            driver, origin_episode_id=eid, origin_segment_id="s",
            fork_objective="obj", fork_intent="int",
            alternatives=[{}, {}],
        )
        branch_operations.resolve_fork(
            driver,
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
        driver = FakeDriver(store)

        result = branch_operations.create_departure_fork(
            driver,
            origin_episode_id=oid,
            origin_segment_id="seg-1",
            fork_objective="Explore the DAG tangent",
            fork_creation_trigger="TOPIC_SHIFT",
            initiator="clotho",
            fork_title="DAG tangent",
        )

        assert result is not None
        assert result.fork_id and result.fork_point_id and result.fork_episode_id
        # single departure point written (no siblings)
        assert len(store.departure_points) == 1
        dp = store.departure_points[result.fork_point_id]
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
        driver = FakeDriver(store)
        result = branch_operations.create_departure_fork(
            driver, origin_episode_id=oid, origin_segment_id="seg-1",
            fork_objective="obj", fork_creation_trigger="PARALLEL_THREAD", initiator="x",
        )
        dp = store.departure_points[result.fork_point_id]
        fe = store.episodes[result.fork_episode_id]
        assert dp["spine_tip_hash_at_departure"] == fe["fork_origin_spine_tip_hash"]
        assert result.spine_tip_hash_at_departure == dp["spine_tip_hash_at_departure"]

    def test_origin_episode_continues_untouched(self):
        """A departure does NOT resolve or alter the origin — it continues."""
        oid = str(uuid4())
        store = _make_store_with_episodes([oid])
        driver = FakeDriver(store)
        branch_operations.create_departure_fork(
            driver, origin_episode_id=oid, origin_segment_id="seg-1",
            fork_objective="obj", fork_creation_trigger="EXPLICIT_FORK", initiator="x",
        )
        assert store.episodes[oid]["status"] == "ACTIVE"  # origin unchanged

    def test_agent_escalation_requires_trigger_segment(self):
        from ariadne.core.schema import AriadneGovernanceError
        oid = str(uuid4())
        store = _make_store_with_episodes([oid])
        driver = FakeDriver(store)
        # missing fork_trigger_segment_id → governance error
        try:
            branch_operations.create_departure_fork(
                driver, origin_episode_id=oid, origin_segment_id="seg-1",
                fork_objective="obj", fork_creation_trigger="AGENT_ESCALATION", initiator="aci",
            )
            assert False, "expected AriadneGovernanceError"
        except AriadneGovernanceError:
            pass
        # with the trigger segment → succeeds
        result = branch_operations.create_departure_fork(
            driver, origin_episode_id=oid, origin_segment_id="seg-1",
            fork_objective="obj", fork_creation_trigger="AGENT_ESCALATION",
            initiator="aci", fork_trigger_segment_id="seg-trigger",
        )
        assert result is not None

    def test_idempotent_on_repeat(self):
        oid = str(uuid4())
        store = _make_store_with_episodes([oid])
        driver = FakeDriver(store)
        kw = dict(origin_episode_id=oid, origin_segment_id="seg-1",
                  fork_objective="same obj", fork_creation_trigger="TOPIC_SHIFT", initiator="x")
        r1 = branch_operations.create_departure_fork(driver, **kw)
        r2 = branch_operations.create_departure_fork(driver, **kw)
        assert r1 is not None and r2 is not None
        # second call short-circuits on the COMPLETE intent — no second departure point
        assert len(store.departure_points) == 1


class TestDepartureForkFSM:
    """Phase D FSM ops: complete / abandon / declare_fork_return."""

    def _make_active_fork(self, store):
        oid = str(uuid4())
        store.episodes[oid] = {"status": "ACTIVE", "spine_hash": f"spine-{oid[:8]}"}
        driver = FakeDriver(store)
        res = branch_operations.create_departure_fork(
            driver, origin_episode_id=oid, origin_segment_id="seg-1",
            fork_objective="tangent", fork_creation_trigger="TOPIC_SHIFT", initiator="a",
        )
        return oid, res, driver

    def test_complete_transitions_active_to_completed(self):
        store = FakeStore()
        _oid, res, driver = self._make_active_fork(store)
        ok = branch_operations.complete_departure_fork(driver, res.fork_episode_id, actor="fork-agent")
        assert ok is True
        assert store.episodes[res.fork_episode_id]["fork_status"] == "COMPLETED"
        assert any(a.get("delta_type") == "DEPARTURE_FORK_COMPLETED" for a in store.audit_records)

    def test_abandon_transitions_active_to_abandoned(self):
        store = FakeStore()
        _oid, res, driver = self._make_active_fork(store)
        ok = branch_operations.abandon_departure_fork(driver, res.fork_episode_id, actor="origin-agent")
        assert ok is True
        assert store.episodes[res.fork_episode_id]["fork_status"] == "ABANDONED"
        assert any(a.get("delta_type") == "DEPARTURE_FORK_ABANDONED" for a in store.audit_records)

    def test_cannot_abandon_a_completed_fork(self):
        store = FakeStore()
        _oid, res, driver = self._make_active_fork(store)
        branch_operations.complete_departure_fork(driver, res.fork_episode_id)
        ok = branch_operations.abandon_departure_fork(driver, res.fork_episode_id)
        assert ok is False  # COMPLETED forks return, they are not abandoned
        assert store.episodes[res.fork_episode_id]["fork_status"] == "COMPLETED"

    def test_declare_return_requires_completed(self):
        from ariadne.core.schema import AriadneGovernanceError
        store = FakeStore()
        oid, res, driver = self._make_active_fork(store)
        # fork is ACTIVE — return must be blocked
        try:
            branch_operations.declare_fork_return(
                driver, fork_id=res.fork_id, origin_episode_id=oid,
                return_type="INCORPORATED", returned_by="origin-agent",
            )
            assert False, "expected AriadneGovernanceError"
        except AriadneGovernanceError:
            pass

    def test_declare_return_writes_return_node_and_audit(self):
        store = FakeStore()
        oid, res, driver = self._make_active_fork(store)
        branch_operations.complete_departure_fork(driver, res.fork_episode_id)
        result = branch_operations.declare_fork_return(
            driver, fork_id=res.fork_id, origin_episode_id=oid,
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
        from ariadne.core.schema import AriadneGovernanceError
        store = FakeStore()
        oid, res, driver = self._make_active_fork(store)
        branch_operations.complete_departure_fork(driver, res.fork_episode_id)
        branch_operations.declare_fork_return(
            driver, fork_id=res.fork_id, origin_episode_id=oid,
            return_type="ACKNOWLEDGED", returned_by="origin-agent",
        )
        try:
            branch_operations.declare_fork_return(
                driver, fork_id=res.fork_id, origin_episode_id=oid,
                return_type="INCORPORATED", returned_by="origin-agent",
            )
            assert False, "expected AriadneGovernanceError (double return)"
        except AriadneGovernanceError:
            pass
