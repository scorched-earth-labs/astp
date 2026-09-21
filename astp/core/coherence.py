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
ASTP Phase 4 — Prescriptive Enforcement (SPEC §19.5)

This module turns drift detection from descriptive into prescriptive.
Phase 4 makes detection active:

  - detect_branch_candidate(): read recent fingerprints, advance state,
    fire MATERIALIZED recommendations
  - intercept_segment_write(): Write Intercept Protocol — compute
    fingerprint at write time, persist it, advance the detection state
  - CoherenceFingerprintRegistry: convenience wrapper around the structural store
    fingerprint queries
"""

import logging
from typing import Any, Dict, List, Optional

from astp.adapters.base import as_structural_store
from astp.core.branching import (
    CoherenceFingerprint,
    DetectionResult,
    DetectionState,
    DetectionThresholds,
    DEFAULT_DETECTION_THRESHOLDS,
    IntentClass,
    advance_detection_state,
    compute_materialized_recommendation,
    compute_objective_hash,
    enforce_write_time_fingerprint,
)
from astp.core.drift_fsm import (
    DriftDetectionState,
    advance_drift_fsm,
)

logger = logging.getLogger("astp.coherence")


_FSM_TO_DETECTION = {
    "CANDIDATE": DetectionState.CANDIDATE,
    "MATERIALIZED": DetectionState.MATERIALIZED,
    "NOMINAL": DetectionState.NOMINAL,
    "COOLDOWN": DetectionState.NOMINAL,   # post-detection monitoring
}


def _detect_via_fsm(
    store,
    episode_id: str,
    segment_id: str,
    sequence_index: int,
    drift_from_spine: float,
    fsm_state: DriftDetectionState,
    drift_vs_anchor: Optional[float] = None,
) -> DetectionResult:
    """Derivative+hysteresis FSM path for detect_branch_candidate.

    Pure transition (no fingerprint read) except the materialized-recommendation
    lookup, which mirrors the legacy path. The new FSM state is returned on
    `new_fsm_state` for the caller to persist in its ephemeral coordinator.

    `drift_vs_anchor` (caller-supplied, the pre-pivot centroid snapshot) is the
    sustain-gate input; None falls back to live drift.
    """
    store = as_structural_store(store)
    res = advance_drift_fsm(
        fsm_state, drift_from_spine, sequence_index, drift_vs_anchor=drift_vs_anchor
    )

    if res.materialized:
        new_state = DetectionState.MATERIALIZED
    else:
        new_state = _FSM_TO_DETECTION.get(res.fsm_state, DetectionState.NOMINAL)

    recommendation = None
    if res.materialized:
        registry = CoherenceFingerprintRegistry(store)
        last_nominal = registry.last_nominal_segment(episode_id)
        recommendation = compute_materialized_recommendation(
            episode_id=episode_id,
            segment_id=segment_id,
            last_nominal_segment_id=last_nominal,
            drift_from_spine=drift_from_spine,
        )
        logger.warning(
            f"Drift FSM MATERIALIZED for episode {episode_id[:8]}... "
            f"segment {segment_id[:8]}... drift={drift_from_spine:.3f} "
            f"Δ={res.delta_drift:.3f} → recommending RETROACTIVE branch from "
            f"segment {(last_nominal or segment_id)[:8]}..."
        )

    return DetectionResult(
        episode_id=episode_id,
        segment_id=segment_id,
        prior_state=_FSM_TO_DETECTION.get(fsm_state.fsm_state, DetectionState.NOMINAL),
        new_state=new_state,
        consecutive_drift_count=res.new_state.sustained_count,
        drift_from_spine=drift_from_spine,
        materialized_recommendation=recommendation,
        new_fsm_state=res.new_state,
        delta_drift=res.delta_drift,
        triggered_on_derivative=res.triggered_on_derivative,
    )


# ============================================================================
# Fingerprint Registry — convenience wrapper around writer queries
# ============================================================================


class CoherenceFingerprintRegistry:
    """Read/write facade over the stored coherence fingerprints.

    Backed by a ``StructuralStore``. Use this instead of store calls from application code.
    """

    def __init__(self, store):
        self.store = as_structural_store(store)

    def write(self, fingerprint: CoherenceFingerprint) -> None:
        enforce_write_time_fingerprint(fingerprint)
        self.store.write_coherence_fingerprint(fingerprint)

    def recent(self, episode_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        return self.store.recent_fingerprints(episode_id, limit)

    def last(self, episode_id: str) -> Optional[Dict[str, Any]]:
        return self.store.last_fingerprint(episode_id)

    def last_nominal_segment(self, episode_id: str) -> Optional[str]:
        return self.store.last_nominal_segment(episode_id)


# ============================================================================
# Detection — read current state + advance
# ============================================================================


def detect_branch_candidate(
    store,
    episode_id: str,
    segment_id: str,
    sequence_index: int,
    drift_from_spine: float,
    intent_class: IntentClass = IntentClass.CONTINUE,
    objective_hash: str = "",
    thresholds: DetectionThresholds = DEFAULT_DETECTION_THRESHOLDS,
    fsm_state: Optional["DriftDetectionState"] = None,
    drift_vs_anchor: Optional[float] = None,
) -> DetectionResult:
    """Active detection: compute new state from prior fingerprint + observation.

    Does NOT write a fingerprint — that is the intercept's job. This is
    the pure detection function: read last fingerprint, decide new state.

    When new_state advances to MATERIALIZED, a retroactive-branch
    recommendation is attached to the result.

    Detection model:
      - `fsm_state is None` (default): the legacy streak-based
        `advance_detection_state` — unchanged, fully backward-compatible.
      - `fsm_state` provided: the derivative+hysteresis FSM. The caller owns
        the persisted DriftDetectionState and passes it in; the new state comes back on `result.new_fsm_state`.
    """
    store = as_structural_store(store)
    if fsm_state is not None:
        return _detect_via_fsm(
            store, episode_id, segment_id, sequence_index,
            drift_from_spine, fsm_state, drift_vs_anchor=drift_vs_anchor,
        )

    registry = CoherenceFingerprintRegistry(store)
    last = registry.last(episode_id)

    prior_state = DetectionState.NOMINAL
    prior_count = 0
    prior_objective_hash = objective_hash
    if last:
        try:
            prior_state = DetectionState(last.get("detection_state", "NOMINAL"))
        except ValueError:
            prior_state = DetectionState.NOMINAL
        prior_count = int(last.get("consecutive_drift_count", 0) or 0)
        prior_objective_hash = last.get("objective_hash", "") or ""

    objective_changed = (
        bool(objective_hash)
        and bool(prior_objective_hash)
        and objective_hash != prior_objective_hash
    )

    new_state, new_count = advance_detection_state(
        prior_state=prior_state,
        prior_consecutive_count=prior_count,
        drift_from_spine=drift_from_spine,
        objective_changed=objective_changed,
        intent_class=intent_class,
        thresholds=thresholds,
    )

    recommendation = None
    if new_state == DetectionState.MATERIALIZED and prior_state != DetectionState.MATERIALIZED:
        last_nominal = registry.last_nominal_segment(episode_id)
        recommendation = compute_materialized_recommendation(
            episode_id=episode_id,
            segment_id=segment_id,
            last_nominal_segment_id=last_nominal,
            drift_from_spine=drift_from_spine,
        )
        logger.warning(
            f"Detection MATERIALIZED for episode {episode_id[:8]}... "
            f"segment {segment_id[:8]}... drift={drift_from_spine:.3f} "
            f"→ recommending RETROACTIVE branch from segment "
            f"{(last_nominal or segment_id)[:8]}..."
        )

    return DetectionResult(
        episode_id=episode_id,
        segment_id=segment_id,
        prior_state=prior_state,
        new_state=new_state,
        consecutive_drift_count=new_count,
        drift_from_spine=drift_from_spine,
        materialized_recommendation=recommendation,
    )


# ============================================================================
# Write Intercept Protocol
# ============================================================================


def intercept_segment_write(
    store,
    episode_id: str,
    segment_id: str,
    sequence_index: int,
    current_objective: str,
    topic_vector: Optional[List[float]] = None,
    drift_from_spine: float = 0.0,
    intent_class: IntentClass = IntentClass.CONTINUE,
    thresholds: DetectionThresholds = DEFAULT_DETECTION_THRESHOLDS,
    fsm_state: Optional["DriftDetectionState"] = None,
    drift_vs_anchor: Optional[float] = None,
) -> DetectionResult:
    """Write Intercept: runs AS a segment is written.

    Sequence:
      1. Compute objective_hash
      2. Call detect_branch_candidate() with current observation
      3. Build CoherenceFingerprint with the new state + count
      4. Persist fingerprint via registry
      5. Return the DetectionResult (with recommendation if materialized)

    This is the prescriptive hook — callers invoke it from their segment
    write path and act on `result.materialized_recommendation` when
    present (typically: call create_branch with declaration_type=RETROACTIVE).
    """
    store = as_structural_store(store)
    objective_hash = compute_objective_hash(current_objective)

    result = detect_branch_candidate(
        store=store,
        episode_id=episode_id,
        segment_id=segment_id,
        sequence_index=sequence_index,
        drift_from_spine=drift_from_spine,
        intent_class=intent_class,
        objective_hash=objective_hash,
        thresholds=thresholds,
        fsm_state=fsm_state,
        drift_vs_anchor=drift_vs_anchor,
    )

    fingerprint = CoherenceFingerprint(
        episode_id=episode_id,
        segment_id=segment_id,
        sequence_index=sequence_index,
        topic_vector=topic_vector or [],
        intent_class=intent_class,
        objective_hash=objective_hash,
        drift_from_spine=drift_from_spine,
        consecutive_drift_count=result.consecutive_drift_count,
        detection_state=result.new_state,
    )

    registry = CoherenceFingerprintRegistry(store)
    registry.write(fingerprint)

    return result
