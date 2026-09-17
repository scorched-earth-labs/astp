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
Phase 4 — Schema + State Machine + Confirmation Cache Unit Tests

Pure unit tests (no driver). Verifies:
  - CoherenceFingerprint / DetectionThresholds schema round-trips
  - advance_detection_state transitions through NOMINAL → WATCHING →
    CANDIDATE → MATERIALIZED per spec thresholds
  - drift reset returns to NOMINAL and resets consecutive count
  - objective_change forces IMMEDIATE CANDIDATE regardless of drift
  - INTRODUCE intent class forces IMMEDIATE CANDIDATE
  - materialized_recommendation payload shape
  - ConfirmationCache hit / miss / expiry after valid_for_turns
  - enforce_write_time_fingerprint rejects None
  - hash domain separation for FINGERPRINT: and OBJECTIVE:
"""

import pytest

from astp.core.branching import (
    AriadneGovernanceError,
    CoherenceFingerprint,
    ConfirmationCache,
    ConfirmedAction,
    DEFAULT_DETECTION_THRESHOLDS,
    DetectionState,
    IntentClass,
    advance_detection_state,
    compute_fingerprint_hash,
    compute_materialized_recommendation,
    compute_objective_hash,
    enforce_write_time_fingerprint,
)


class TestFingerprintSchema:
    def test_defaults(self):
        fp = CoherenceFingerprint(episode_id="e", segment_id="s")
        assert fp.detection_state == DetectionState.NOMINAL
        assert fp.consecutive_drift_count == 0
        assert fp.intent_class == IntentClass.CONTINUE
        assert fp.topic_vector == []

    def test_hash_is_deterministic_and_domain_separated(self):
        h_fp = compute_fingerprint_hash("x", "x", "x", "x", "x", "t")
        h_fp2 = compute_fingerprint_hash("x", "x", "x", "x", "x", "t")
        assert h_fp == h_fp2
        # Different domain from OBJECTIVE:
        h_obj = compute_objective_hash("x")
        assert h_fp != h_obj

    def test_objective_hash_canonicalization(self):
        # Leading/trailing whitespace does not change the hash
        assert compute_objective_hash("goal") == compute_objective_hash("  goal  ")


class TestThresholds:
    def test_defaults_match_spec(self):
        t = DEFAULT_DETECTION_THRESHOLDS
        assert t.watching_drift == 0.3
        assert t.watching_consecutive_turns == 1
        assert t.candidate_drift == 0.3
        assert t.candidate_consecutive_turns == 3
        assert t.materialized_drift == 0.5
        assert t.materialized_consecutive_turns == 5
        assert t.objective_change_forces_candidate is True


class TestStateMachine:
    """advance_detection_state progression per spec §7.2."""

    def _apply(self, prior_state, prior_count, drift, obj_changed=False,
               intent=IntentClass.CONTINUE, thresholds=None):
        return advance_detection_state(
            prior_state=prior_state,
            prior_consecutive_count=prior_count,
            drift_from_spine=drift,
            objective_changed=obj_changed,
            intent_class=intent,
            thresholds=thresholds or DEFAULT_DETECTION_THRESHOLDS,
        )

    def test_nominal_to_watching_after_one_turn_at_watching_drift(self):
        state, count = self._apply(DetectionState.NOMINAL, 0, drift=0.35)
        assert state == DetectionState.WATCHING
        assert count == 1

    def test_watching_to_candidate_after_three_consecutive_turns(self):
        # Turn 2: still below candidate count
        state, count = self._apply(DetectionState.WATCHING, 1, drift=0.35)
        assert state == DetectionState.WATCHING
        assert count == 2
        # Turn 3: reaches CANDIDATE
        state, count = self._apply(DetectionState.WATCHING, 2, drift=0.35)
        assert state == DetectionState.CANDIDATE
        assert count == 3

    def test_candidate_to_materialized_at_higher_drift_and_count(self):
        # Need drift >= 0.5 AND count >= 5
        state, count = self._apply(DetectionState.CANDIDATE, 4, drift=0.6)
        assert state == DetectionState.MATERIALIZED
        assert count == 5

    def test_drift_resolution_resets_to_nominal(self):
        """If drift drops below watching threshold, state returns to NOMINAL
        and consecutive_drift_count resets to 0."""
        state, count = self._apply(DetectionState.CANDIDATE, 3, drift=0.1)
        assert state == DetectionState.NOMINAL
        assert count == 0

    def test_objective_change_forces_candidate_regardless_of_drift(self):
        state, count = self._apply(
            DetectionState.NOMINAL, 0, drift=0.0, obj_changed=True,
        )
        assert state == DetectionState.CANDIDATE

    def test_introduce_intent_forces_candidate(self):
        state, _ = self._apply(
            DetectionState.NOMINAL, 0, drift=0.0,
            intent=IntentClass.INTRODUCE,
        )
        assert state == DetectionState.CANDIDATE

    def test_watching_level_drift_below_candidate_count_stays_watching(self):
        state, count = self._apply(DetectionState.WATCHING, 1, drift=0.4)
        assert state == DetectionState.WATCHING
        assert count == 2

    def test_high_drift_but_insufficient_count_stays_candidate_not_materialized(self):
        state, count = self._apply(DetectionState.CANDIDATE, 2, drift=0.7)
        assert state == DetectionState.CANDIDATE
        assert count == 3


class TestMaterializedRecommendation:
    def test_payload_shape(self):
        rec = compute_materialized_recommendation(
            episode_id="ep-1",
            segment_id="seg-current",
            last_nominal_segment_id="seg-prior-nominal",
            drift_from_spine=0.7,
        )
        assert rec["recommended_action"] == "CREATE_BRANCH_RETROACTIVE"
        assert rec["source_segment_id"] == "seg-prior-nominal"
        assert rec["drift_from_spine"] == 0.7

    def test_falls_back_to_current_segment_when_no_nominal(self):
        rec = compute_materialized_recommendation(
            episode_id="e", segment_id="s-current",
            last_nominal_segment_id=None, drift_from_spine=0.6,
        )
        assert rec["source_segment_id"] == "s-current"


class TestConfirmationCache:
    def test_unknown_action_not_confirmed(self):
        cache = ConfirmationCache()
        assert cache.is_confirmed("delete everything", current_turn=5) is False

    def test_recorded_action_confirmed_within_window(self):
        cache = ConfirmationCache()
        cache.record("deploy", confirmed_by="human-1", current_turn=10,
                     valid_for_turns=5)
        assert cache.is_confirmed("deploy", current_turn=11) is True
        assert cache.is_confirmed("deploy", current_turn=15) is True  # 10 + 5 = within window

    def test_confirmation_expires_after_valid_for_turns(self):
        cache = ConfirmationCache()
        cache.record("deploy", confirmed_by="human-1", current_turn=10,
                     valid_for_turns=5)
        # 10 + 5 = 15 still within; 16 is beyond
        assert cache.is_confirmed("deploy", current_turn=16) is False
        # Expired entry is discarded
        assert cache.get("deploy") is None

    def test_case_and_whitespace_insensitive(self):
        cache = ConfirmationCache()
        cache.record("Deploy Now", confirmed_by="human-1", current_turn=1)
        assert cache.is_confirmed("  deploy now  ", current_turn=2) is True

    def test_invalidate_removes_entry(self):
        cache = ConfirmationCache()
        cache.record("op", confirmed_by="a", current_turn=1)
        cache.invalidate("op")
        assert cache.is_confirmed("op", current_turn=1) is False

    def test_record_returns_confirmation(self):
        cache = ConfirmationCache()
        conf = cache.record("x", confirmed_by="u", current_turn=1)
        assert isinstance(conf, ConfirmedAction)
        assert conf.confirmed_by == "u"
        assert conf.confirmed_at_turn == 1


class TestWriteTimeGuard:
    def test_rejects_none_fingerprint(self):
        with pytest.raises(AriadneGovernanceError):
            enforce_write_time_fingerprint(None)

    def test_accepts_fingerprint(self):
        fp = CoherenceFingerprint(episode_id="e", segment_id="s")
        enforce_write_time_fingerprint(fp)  # no raise
