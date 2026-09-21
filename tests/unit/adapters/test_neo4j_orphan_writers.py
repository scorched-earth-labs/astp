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
Phase D orphan-recovery write primitives of the Neo4j reference adapter
(SPEC §19.3.7), against a fake driver that records the Cypher it is given.

These exercise the adapter's writer functions directly, not the operations
layer, and belong with the adapter.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from astp.adapters.neo4j import writer as neo4j_writer


# ── Fake Neo4j driver (orphan-recovery queries only) ───────────────────────────────────────────────────────


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
        self.segments: Dict[str, Dict[str, Any]] = {}           # by segment_id
        self.orphan_markers: Dict[str, Dict[str, Any]] = {}     # by fork_id (dedup)
        self.merge_points: Dict[str, Dict[str, Any]] = {}
        self.audit_records: List[Dict[str, Any]] = []
        self.intents: Dict[str, Dict[str, Any]] = {}  # by idempotency_key
        self.max_delta_sequence: Dict[str, int] = {}

    def _record_call(self, query: str, params: Dict[str, Any]):
        self.calls.append({"query": query, "params": params})

    def run(self, query: str, params: Dict[str, Any]):
        self._record_call(query, params)
        q = " ".join(query.split())

        # Create DepartureForkPoint (Phase D)
        if "MERGE (fp:AriadneDepartureForkPoint" in q and "fork_point_id: $fork_point_id" in q:
            self.departure_points[params.get("fork_point_id")] = dict(params)
            return FakeResult([])

        # Phase D orphan: write ForkOrphanMarker (dedup on fork_id)
        if "MERGE (m:AriadneForkOrphanMarker {fork_id: $fork_id})" in q:
            fid = params.get("fork_id")
            if fid not in self.orphan_markers:
                self.orphan_markers[fid] = dict(params)
            return FakeResult([])

        # Phase D orphan: flag departure fork point orphaned (Class A)
        if "MATCH (fp:AriadneDepartureForkPoint {fork_point_id: $fork_point_id})" in q and "SET fp.orphaned" in q:
            dp = self.departure_points.get(params.get("fork_point_id"))
            if dp is not None:
                dp["orphaned"] = True
            return FakeResult([])

        # Phase D orphan: mark fork episode UNANCHORED (Class B, origin unreachable)
        if "MATCH (e:AriadneEpisode {episode_id: $episode_id})" in q and "SET e.fork_orphaned" in q:
            ep = self.episodes.get(params.get("episode_id"))
            if ep is not None:
                ep["fork_orphaned"] = True
                ep["fork_orphan_class"] = "UNANCHORED"
            return FakeResult([])

        # Phase D orphan: correct fork status by recovery (Class C) — MUST precede generic fork_status
        if "MATCH (e:AriadneEpisode {episode_id: $episode_id})" in q and "status_corrected_by_orphan_recovery" in q:
            ep = self.episodes.get(params.get("episode_id"))
            if ep is not None:
                ep["fork_status"] = "COMPLETED"
                ep["status_corrected_by_orphan_recovery"] = True
                ep["status_corrected_at"] = params.get("ts")
            return FakeResult([])
        # Catch-all: edges / other merges — silently succeed
        return FakeResult([])


class TestForkOrphanRecovery:
    """Phase D §19.3.7 — orphan-detection write primitives (protocol exposes writes;
    the host application orchestrates detection). All append-only or set-once; no deletes."""

    def _dfp(self, tip="backdated-tip", initiator="recovery"):
        from astp.core.branching import (
            DepartureForkPointNode, compute_departure_fork_point_hash, ForkCreationTrigger,
        )
        now = datetime(2026, 7, 5, tzinfo=timezone.utc)
        dfp = DepartureForkPointNode(
            fork_id=uuid4(), fork_episode_id=uuid4(), origin_episode_id=uuid4(),
            origin_segment_id="seg-1", fork_objective="obj",
            fork_creation_trigger=ForkCreationTrigger.TOPIC_SHIFT, fork_title_snapshot="t",
            spine_tip_hash_at_departure=tip, initiator=initiator, timestamp_utc=now,
        )
        dfp.content_hash = compute_departure_fork_point_hash(
            str(dfp.fork_point_id), str(dfp.fork_id), str(dfp.fork_episode_id),
            str(dfp.origin_episode_id), dfp.origin_segment_id, dfp.fork_objective,
            dfp.fork_creation_trigger.value, dfp.spine_tip_hash_at_departure,
            dfp.initiator, dfp.timestamp_utc.isoformat(), dfp.parent_hash,
        )
        return dfp, now

    def test_orphan_marker_hash_deterministic_and_self_hashed(self):
        from astp.core.branching import (
            compute_fork_orphan_marker_hash, ForkOrphanMarker, OrphanClass,
        )
        args = ("mid", "fid", "oid", "CLASS_A", 5, "drid", "did stuff", True, "2026-07-05T00:00:00+00:00")
        h1 = compute_fork_orphan_marker_hash(*args)
        h2 = compute_fork_orphan_marker_hash(*args)
        h3 = compute_fork_orphan_marker_hash("mid", "fid", "oid", "CLASS_B", 5, "drid", "did stuff", True, "2026-07-05T00:00:00+00:00")
        assert h1 == h2 and h1 != h3
        # satellite: self-hashed (content_hash) but NOT chained (no parent_hash field)
        m = ForkOrphanMarker(
            fork_id=uuid4(), origin_episode_id=uuid4(), orphan_class=OrphanClass.CLASS_A,
            sequence_index=1, detection_run_id=uuid4(), recovery_action="x",
            requires_operator_review=True,
        )
        assert hasattr(m, "content_hash") and not hasattr(m, "parent_hash")

    def test_write_orphan_marker_dedup_on_fork_id(self):
        from astp.core.branching import ForkOrphanMarker, OrphanClass
        store = FakeStore()
        driver = FakeDriver(store)
        fid = uuid4()
        for action in ("first", "second"):
            neo4j_writer.write_fork_orphan_marker_sync(driver, ForkOrphanMarker(
                fork_id=fid, origin_episode_id=uuid4(), orphan_class=OrphanClass.CLASS_A,
                sequence_index=1, detection_run_id=uuid4(), recovery_action=action,
                requires_operator_review=True,
            ))
        assert len(store.orphan_markers) == 1            # one marker per orphaned fork
        assert str(fid) in store.orphan_markers
        assert store.orphan_markers[str(fid)]["recovery_action"] == "first"  # ON CREATE only

    def test_class_a_flags_point_orphaned_append_only(self):
        store = FakeStore()
        driver = FakeDriver(store)
        pid = str(uuid4())
        store.departure_points[pid] = {"fork_point_id": pid, "fork_id": str(uuid4())}
        neo4j_writer.mark_departure_fork_point_orphaned_sync(driver, pid)
        assert store.departure_points[pid]["orphaned"] is True
        assert pid in store.departure_points                 # never deleted (append-only)

    def test_class_b_retroactive_write_appends_backdated_and_byte_identical(self):
        from astp.core.branching import compute_departure_fork_point_hash
        store = FakeStore()
        driver = FakeDriver(store)
        dfp, now = self._dfp(tip="backdated-tip")
        neo4j_writer.write_retroactive_departure_fork_point_sync(driver, dfp, now)
        stored = store.departure_points[str(dfp.fork_point_id)]
        assert stored["retroactive"] is True
        assert stored["orphan_recovery_timestamp"] == now.isoformat()
        # backdated anchor preserved (cross-verifiable invariant holds by construction)
        assert stored["spine_tip_hash_at_departure"] == "backdated-tip"
        # byte-identical to an on-time write — the retroactive flag is outside the hash preimage
        recomputed = compute_departure_fork_point_hash(
            str(dfp.fork_point_id), str(dfp.fork_id), str(dfp.fork_episode_id),
            str(dfp.origin_episode_id), dfp.origin_segment_id, dfp.fork_objective,
            dfp.fork_creation_trigger.value, dfp.spine_tip_hash_at_departure,
            dfp.initiator, dfp.timestamp_utc.isoformat(), dfp.parent_hash,
        )
        assert stored["content_hash"] == recomputed

    def test_class_b_unanchored_marks_episode(self):
        store = FakeStore()
        driver = FakeDriver(store)
        eid = str(uuid4())
        store.episodes[eid] = {"status": "ACTIVE", "fork_status": "ACTIVE"}
        neo4j_writer.mark_fork_episode_unanchored_sync(driver, eid)
        assert store.episodes[eid]["fork_orphaned"] is True
        assert store.episodes[eid]["fork_orphan_class"] == "UNANCHORED"

    def test_class_c_corrects_status(self):
        store = FakeStore()
        driver = FakeDriver(store)
        eid = str(uuid4())
        store.episodes[eid] = {"status": "ACTIVE", "fork_status": "ACTIVE"}
        neo4j_writer.correct_fork_status_by_orphan_recovery_sync(driver, eid)
        assert store.episodes[eid]["fork_status"] == "COMPLETED"
        assert store.episodes[eid]["status_corrected_by_orphan_recovery"] is True
        assert store.episodes[eid]["status_corrected_at"] is not None
