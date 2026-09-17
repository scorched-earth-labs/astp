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
Phase 4 — Write Intercept + Registry Integration Tests (driver-mocked)

Verifies:
  - intercept_segment_write persists fingerprint with computed state
  - successive intercepts advance NOMINAL → WATCHING → CANDIDATE →
    MATERIALIZED when drift persists
  - MATERIALIZED transition returns a recommendation anchored at last
    NOMINAL segment
  - objective-hash change forces CANDIDATE on first drift
  - registry.recent returns newest-first
"""

from typing import Any, Dict, List

from astp.core.branching import (
    DetectionState,
    IntentClass,
)
from astp.core.coherence import (
    CoherenceFingerprintRegistry,
    detect_branch_candidate,
    intercept_segment_write,
)


# ── Fake driver ─────────────────────────────────────────────────────────────


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def single(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class FakeSession:
    def __init__(self, store):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, params=None):
        return self.store.run(query, params or {})


class FakeDriver:
    def __init__(self, store):
        self._store = store

    def session(self):
        return FakeSession(self._store)


class FakeStore:
    def __init__(self):
        self.calls = []
        self.fingerprints: List[Dict[str, Any]] = []
        self.episodes: Dict[str, Dict[str, Any]] = {}

    def run(self, query, params):
        self.calls.append({"query": query, "params": params})
        q = " ".join(query.split())

        # Fingerprint create
        if "MERGE (fp:AriadneCoherenceFingerprint {fingerprint_id: $fingerprint_id})" in q:
            self.fingerprints.append(dict(params))
            return FakeResult([])

        # Recent fingerprints
        if "MATCH (fp:AriadneCoherenceFingerprint {episode_id: $episode_id}) RETURN fp" in q:
            eid = params.get("episode_id")
            limit = int(params.get("limit", 10))
            relevant = [
                f for f in self.fingerprints if f.get("episode_id") == eid
            ]
            relevant.sort(key=lambda f: f.get("sequence_index", 0), reverse=True)
            return FakeResult([{"fingerprint": f} for f in relevant[:limit]])

        # Last nominal segment
        if ("MATCH (fp:AriadneCoherenceFingerprint {episode_id: $episode_id})" in q
                and "fp.detection_state = 'NOMINAL'" in q):
            eid = params.get("episode_id")
            relevant = [
                f for f in self.fingerprints
                if f.get("episode_id") == eid
                and f.get("detection_state") == "NOMINAL"
            ]
            relevant.sort(key=lambda f: f.get("sequence_index", 0), reverse=True)
            if relevant:
                return FakeResult([{"segment_id": relevant[0]["segment_id"]}])
            return FakeResult([])

        # Edge create — noop
        return FakeResult([])


# ── Tests ───────────────────────────────────────────────────────────────────


class TestRegistry:
    def test_recent_returns_newest_first(self):
        store = FakeStore()
        driver = FakeDriver(store)
        reg = CoherenceFingerprintRegistry(driver)
        # Simulate 3 fingerprints
        for i in range(3):
            intercept_segment_write(
                driver, episode_id="e1", segment_id=f"seg-{i}",
                sequence_index=i, current_objective="obj-A",
                drift_from_spine=0.0,
            )
        recent = reg.recent("e1", limit=5)
        # Newest first
        assert [r["segment_id"] for r in recent] == ["seg-2", "seg-1", "seg-0"]


class TestInterceptProgression:
    def test_first_nominal_write_stays_nominal(self):
        store = FakeStore()
        driver = FakeDriver(store)
        result = intercept_segment_write(
            driver, episode_id="e", segment_id="s0",
            sequence_index=0, current_objective="obj",
            drift_from_spine=0.0,
        )
        assert result.new_state == DetectionState.NOMINAL
        assert len(store.fingerprints) == 1

    def test_persistent_drift_advances_through_states(self):
        """With drift=0.35 (above watching, below materialized), state
        should walk: NOMINAL → WATCHING (turn 1) → WATCHING (turn 2) →
        CANDIDATE (turn 3) → CANDIDATE (turn 4+). Never reaches MATERIALIZED
        because drift < 0.5."""
        store = FakeStore()
        driver = FakeDriver(store)

        states = []
        for i in range(5):
            r = intercept_segment_write(
                driver, episode_id="e", segment_id=f"s{i}",
                sequence_index=i, current_objective="obj",
                drift_from_spine=0.35,
            )
            states.append(r.new_state)

        assert states[0] == DetectionState.WATCHING
        assert states[1] == DetectionState.WATCHING
        assert states[2] == DetectionState.CANDIDATE
        assert states[3] == DetectionState.CANDIDATE
        assert states[4] == DetectionState.CANDIDATE
        # No materialization at drift=0.35
        assert all(s != DetectionState.MATERIALIZED for s in states)

    def test_high_drift_materializes_at_turn_five(self):
        store = FakeStore()
        driver = FakeDriver(store)

        # First write a NOMINAL segment so we have a last_nominal anchor
        intercept_segment_write(
            driver, episode_id="e", segment_id="anchor-nominal",
            sequence_index=0, current_objective="obj",
            drift_from_spine=0.0,
        )

        states = []
        rec_at_turn = None
        for i in range(1, 7):
            r = intercept_segment_write(
                driver, episode_id="e", segment_id=f"s{i}",
                sequence_index=i, current_objective="obj",
                drift_from_spine=0.6,
            )
            states.append(r.new_state)
            if r.new_state == DetectionState.MATERIALIZED and rec_at_turn is None:
                rec_at_turn = (i, r.materialized_recommendation)

        # Expected progression at drift=0.6 (>= materialized_drift=0.5):
        # turn 1: count=1 → WATCHING
        # turn 2: count=2 → WATCHING
        # turn 3: count=3 → CANDIDATE
        # turn 4: count=4 → CANDIDATE
        # turn 5: count=5 → MATERIALIZED
        assert states[0] == DetectionState.WATCHING
        assert states[4] == DetectionState.MATERIALIZED
        assert rec_at_turn is not None
        assert rec_at_turn[0] == 5  # turn number where MATERIALIZED first fired
        rec = rec_at_turn[1]
        assert rec["recommended_action"] == "CREATE_BRANCH_RETROACTIVE"
        # Anchor is the last NOMINAL segment
        assert rec["source_segment_id"] == "anchor-nominal"

    def test_drift_resolution_resets_state(self):
        store = FakeStore()
        driver = FakeDriver(store)

        # Drift for a few turns
        for i in range(3):
            intercept_segment_write(
                driver, episode_id="e", segment_id=f"s{i}",
                sequence_index=i, current_objective="obj",
                drift_from_spine=0.4,
            )

        # Then drift resolves
        r = intercept_segment_write(
            driver, episode_id="e", segment_id="s-back",
            sequence_index=3, current_objective="obj",
            drift_from_spine=0.05,
        )
        assert r.new_state == DetectionState.NOMINAL
        assert r.consecutive_drift_count == 0

    def test_objective_change_forces_candidate(self):
        store = FakeStore()
        driver = FakeDriver(store)

        intercept_segment_write(
            driver, episode_id="e", segment_id="s0",
            sequence_index=0, current_objective="original objective",
            drift_from_spine=0.0,
        )
        # Change the objective — should force CANDIDATE regardless of drift
        r = intercept_segment_write(
            driver, episode_id="e", segment_id="s1",
            sequence_index=1, current_objective="completely different objective",
            drift_from_spine=0.05,  # low drift
        )
        assert r.new_state == DetectionState.CANDIDATE

    def test_introduce_intent_forces_candidate(self):
        store = FakeStore()
        driver = FakeDriver(store)
        r = intercept_segment_write(
            driver, episode_id="e", segment_id="s0",
            sequence_index=0, current_objective="obj",
            drift_from_spine=0.0,
            intent_class=IntentClass.INTRODUCE,
        )
        assert r.new_state == DetectionState.CANDIDATE


class TestDetectBranchCandidateIsReadOnly:
    """detect_branch_candidate should NOT write a fingerprint — intercept does."""

    def test_detect_does_not_write_fingerprint(self):
        store = FakeStore()
        driver = FakeDriver(store)
        result = detect_branch_candidate(
            driver, episode_id="e", segment_id="s",
            sequence_index=0, drift_from_spine=0.35,
        )
        assert result.new_state == DetectionState.WATCHING
        # No fingerprint persisted
        assert len(store.fingerprints) == 0
