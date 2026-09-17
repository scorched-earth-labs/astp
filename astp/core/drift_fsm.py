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
"""ACI drift detection — derivative + hysteresis state machine (pure logic).

Absolute per-turn drift is not thresholdable (EWM centroid chasing + compressed
embedding space); the signal lives in the *rate of change* (derivative) plus
*sustained elevation*, with a *hysteresis cooldown* to suppress re-fires.

This module is PURE: no Neo4j, no Redis, no I/O. `DriftDetectionState` is the
working state; the caller persists it between turns (the reference deployment
keeps it in the ephemeral coordinator under
`ariadne::drift_fsm_state::{episode_id}`) — this package has no coordinator of
its own. `advance_drift_fsm` is the single transition step.

Default calibration: DELTA_THRESHOLD=0.055, N=2, M=4, ELEVATION_FLOOR=mean+0.5σ
over scored turns, first-content warm-up turn ignored. Callers are expected to
filter out turns with no exchange (agent-only work batches) before calling, so
every call here is an exchange turn and M counts exchanges only.
"""
from __future__ import annotations

import math
from typing import Literal, Optional

from pydantic import BaseModel

FSMState = Literal["NOMINAL", "CANDIDATE", "MATERIALIZED", "COOLDOWN"]


class DriftFSMThresholds(BaseModel):
    """Default thresholds (overridable for tuning)."""
    delta_threshold: float = 0.055     # derivative trigger
    n_sustained: int = 2               # turns of elevation to confirm a pivot
    m_cooldown: int = 4                # post-materialize suppression (EXCHANGE turns)
    floor_sigma: float = 0.5           # ELEVATION_FLOOR = mean + k·σ


DEFAULT_DRIFT_FSM_THRESHOLDS = DriftFSMThresholds()


class DriftDetectionState(BaseModel):
    """Per-episode FSM working state. Caller serializes to/from Redis.

    Holds everything the transition needs across turns — it cannot be
    reconstructed from a single drift value. Running stats (`drift_sum`,
    `drift_sq_sum`, `scored_turns`) accumulate over scored EXCHANGE turns to
    compute the episode-relative ELEVATION_FLOOR online.
    """
    fsm_state: FSMState = "NOMINAL"
    candidate_turn: Optional[int] = None
    candidate_drift: Optional[float] = None
    max_delta_since_trigger: float = 0.0
    sustained_count: int = 0
    cooldown_remaining: int = 0
    prev_drift: Optional[float] = None      # drift[t-1]; None => first turn
    warmed: bool = False                    # first computable delta ignored
    # Online mean/variance over scored turns (the 0→first-content turn excluded).
    drift_sum: float = 0.0
    drift_sq_sum: float = 0.0
    scored_turns: int = 0

    def elevation_floor(self, floor_sigma: float) -> float:
        """mean + floor_sigma·σ over scored turns; mean only until σ is defined."""
        if self.scored_turns < 1:
            return 0.0
        mean = self.drift_sum / self.scored_turns
        if self.scored_turns < 2:
            return mean
        var = max(0.0, (self.drift_sq_sum / self.scored_turns) - mean * mean)
        return mean + floor_sigma * math.sqrt(var)


class DriftFSMResult(BaseModel):
    """What one transition produced (the caller maps this onto DetectionResult)."""
    new_state: DriftDetectionState
    fsm_state: FSMState
    delta_drift: Optional[float] = None
    drift_vs_anchor: Optional[float] = None  # echoed for telemetry (sustain-gate input)
    triggered_on_derivative: bool = False
    materialized: bool = False            # True only on the turn it confirms a pivot


def advance_drift_fsm(
    state: DriftDetectionState,
    drift: float,
    sequence_index: int,
    thresholds: DriftFSMThresholds = DEFAULT_DRIFT_FSM_THRESHOLDS,
    drift_vs_anchor: Optional[float] = None,
) -> DriftFSMResult:
    """One FSM step for one scored (EXCHANGE) turn. Returns a new state.

    Pure: does not mutate `state`.
      - warm-up: first turn (prev None) and the first computable delta are ignored
      - NOMINAL → CANDIDATE on Δdrift > delta_threshold
      - CANDIDATE → MATERIALIZED on sustain-drift > floor for N turns; → NOMINAL if it decays
      - MATERIALIZED → COOLDOWN for M turns, suppressing all triggers

    `drift` is always vs the live (EWM) centroid — it drives the derivative
    trigger and the running floor. `drift_vs_anchor` (caller-supplied, the pre-pivot
    "where we were" centroid) is used for the
    SUSTAIN gate only, so a jump-and-park pivot doesn't read as decayed when the
    live centroid chases it. None → sustain falls back to `drift` (back-compat).
    The protocol stays embedding-agnostic: the caller owns the centroid snapshot
    and the cosine; the FSM only sees the two scalars.
    """
    s = state.model_copy(deep=True)
    delta = None if s.prev_drift is None else drift - s.prev_drift
    materialized = False
    triggered = False

    # ── First turn: no derivative yet (the 0→drift baseline). ───────────────
    if delta is None:
        s.prev_drift = drift
        return DriftFSMResult(new_state=s, fsm_state=s.fsm_state, delta_drift=None)

    # ── Scored turn: accrue running stats for the floor (post-baseline). ────
    s.drift_sum += drift
    s.drift_sq_sum += drift * drift
    s.scored_turns += 1
    floor = s.elevation_floor(thresholds.floor_sigma)

    in_cooldown = s.cooldown_remaining > 0
    if in_cooldown:
        # Suppress any trigger inside the cooldown window (M EXCHANGE turns).
        s.cooldown_remaining -= 1
        if s.cooldown_remaining <= 0:
            s.fsm_state = "NOMINAL"
    elif not s.warmed:
        # First computable delta is the 0→first-content jump — a guaranteed
        # artifact. Skip it; live FSM begins next turn.
        s.warmed = True
    elif s.fsm_state == "CANDIDATE":
        s.max_delta_since_trigger = max(s.max_delta_since_trigger, delta)
        # Sustain gate measures against the pre-pivot anchor when the caller
        # supplies it (so the chasing live centroid can't make a parked pivot
        # look decayed); falls back to live drift otherwise.
        sustain_drift = drift_vs_anchor if drift_vs_anchor is not None else drift
        if sustain_drift > floor:
            s.sustained_count += 1
            if s.sustained_count >= thresholds.n_sustained:
                s.fsm_state = "COOLDOWN"
                s.cooldown_remaining = thresholds.m_cooldown
                materialized = True
        else:
            # Decayed before sustaining — false alarm.
            s.fsm_state = "NOMINAL"
            s.candidate_turn = None
            s.candidate_drift = None
            s.sustained_count = 0
            s.max_delta_since_trigger = 0.0
    elif delta > thresholds.delta_threshold:
        s.fsm_state = "CANDIDATE"
        s.candidate_turn = sequence_index
        s.candidate_drift = drift
        s.max_delta_since_trigger = delta
        s.sustained_count = 1 if drift > floor else 0
        triggered = True

    s.prev_drift = drift
    return DriftFSMResult(
        new_state=s,
        fsm_state=s.fsm_state,
        delta_drift=delta,
        drift_vs_anchor=drift_vs_anchor,
        triggered_on_derivative=triggered,
        materialized=materialized,
    )
