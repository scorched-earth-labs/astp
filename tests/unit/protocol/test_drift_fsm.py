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
"""Derivative + hysteresis drift FSM (astp.core.drift_fsm) + its wiring into
detect_branch_candidate.

Pins Clotho's v4 model against the validated reference simulator
(ignis-os/scripts/aci_fsm_sim.py) and the calibration episodes. The FSM is pure
(no Neo4j/Redis), so the bulk runs without a driver; detect_branch_candidate's
routing (legacy when fsm_state is None, FSM when provided) is checked on a
non-materializing turn so no driver is touched.
"""
from __future__ import annotations

from astp.core.drift_fsm import (
    DriftDetectionState,
    DriftFSMThresholds,
    advance_drift_fsm,
)
from astp.core.coherence import detect_branch_candidate
from astp.core.branching import DetectionState


def _run(drifts, thresholds=None):
    """Replay (seq, drift) pairs; return per-turn DriftFSMResults."""
    s = DriftDetectionState()
    out = []
    for seq, d in drifts:
        r = advance_drift_fsm(s, d, seq, thresholds or DriftFSMThresholds())
        s = r.new_state
        out.append(r)
    return out


# ── Warm-up gate ─────────────────────────────────────────────────────────


def test_first_turn_has_no_derivative():
    r = advance_drift_fsm(DriftDetectionState(), 0.0, 2)
    assert r.delta_drift is None
    assert r.fsm_state == "NOMINAL"
    assert not r.triggered_on_derivative


def test_first_computable_delta_is_warm_up_ignored():
    # seq2 drift 0 → no delta; seq4 0.5 → Δ+0.5 but warm-up → no trigger.
    res = _run([(2, 0.0), (4, 0.5)])
    assert res[1].delta_drift == 0.5
    assert not res[1].triggered_on_derivative
    assert res[1].fsm_state == "NOMINAL"


# ── Derivative trigger + sustained → MATERIALIZED ────────────────────────


def test_derivative_trigger_then_sustained_materializes():
    # warm-up, then a jump that sustains for N=2 turns above the floor.
    res = _run([(2, 0.0), (4, 0.30), (6, 0.30), (8, 0.65), (10, 0.60), (12, 0.58)])
    seqs_trig = [i for i, r in enumerate(res) if r.triggered_on_derivative]
    assert res[3].triggered_on_derivative          # seq8 jump → CANDIDATE
    assert any(r.materialized for r in res)         # sustains → MATERIALIZED
    mat_idx = next(i for i, r in enumerate(res) if r.materialized)
    assert res[mat_idx].fsm_state == "COOLDOWN"     # enters cooldown on materialize


def test_candidate_decays_is_false_alarm():
    # Jump triggers CANDIDATE, but drift immediately drops below floor → cleared.
    res = _run([(2, 0.0), (4, 0.30), (6, 0.28), (8, 0.60), (10, 0.10)])
    assert res[3].triggered_on_derivative           # seq8 → CANDIDATE
    assert not any(r.materialized for r in res)      # never confirms
    assert res[4].fsm_state == "NOMINAL"             # back to nominal


# ── Cooldown suppression (the M test) ────────────────────────────────────


def test_bf6c3143_weather_materializes_daycjob_suppressed():
    # The validated stress-test episode: weather pivot materializes (seq10);
    # the 2nd pivot (seq18 Δ+0.188) lands inside the M=4 cooldown and is
    # suppressed — neither triggers nor materializes.
    drifts = [(2,0.0),(4,0.303),(6,0.266),(8,0.499),(10,0.431),(12,0.344),
              (14,0.199),(16,0.202),(18,0.390),(20,0.340),(22,0.269),(24,0.297)]
    res = _run(drifts)
    by_seq = {drifts[i][0]: res[i] for i in range(len(drifts))}
    assert by_seq[8].triggered_on_derivative         # weather trigger
    assert by_seq[10].materialized                    # confirms
    assert by_seq[10].fsm_state == "COOLDOWN"
    # seq18 day-job is inside cooldown → not a fresh trigger, not materialized
    assert not by_seq[18].triggered_on_derivative
    assert not by_seq[18].materialized
    # exactly one materialization in the episode
    assert sum(1 for r in res if r.materialized) == 1


# ── ELEVATION_FLOOR running estimate ─────────────────────────────────────


def test_running_floor_accumulates_over_scored_turns():
    s = DriftDetectionState()
    for seq, d in [(2, 0.0), (4, 0.3), (6, 0.5)]:
        s = advance_drift_fsm(s, d, seq).new_state
    # seq2 baseline excluded; scored turns are seq4(0.3), seq6(0.5)
    assert s.scored_turns == 2
    assert abs(s.elevation_floor(0.5) - (0.4 + 0.5 * 0.1)) < 1e-6   # mean .4, σ .1


# ── Wiring into detect_branch_candidate ──────────────────────────────────


def test_detect_branch_candidate_legacy_when_no_fsm_state():
    # fsm_state=None → legacy streak path; FSM fields stay empty. driver unused
    # on this non-materializing call (drift below legacy thresholds).
    # Use a minimal stub driver that yields no prior fingerprint.
    class _NoRowsSession:
        def run(self, *a, **k):
            class _R:
                def single(self_): return None
                def __iter__(self_): return iter([])
            return _R()
        def __enter__(self): return self
        def __exit__(self, *a): return False
    class _Driver:
        def session(self, *a, **k): return _NoRowsSession()
    res = detect_branch_candidate(_Driver(), "ep", "seg", 4, drift_from_spine=0.1)
    assert res.new_fsm_state is None
    assert res.triggered_on_derivative is False


def test_detect_branch_candidate_fsm_path_returns_new_state():
    # fsm_state provided → FSM path; a non-materializing turn never touches the
    # driver, so driver=None is safe.
    st = DriftDetectionState(prev_drift=0.20, warmed=True, scored_turns=3,
                             drift_sum=0.9, drift_sq_sum=0.3)
    res = detect_branch_candidate(None, "ep", "seg", 6, drift_from_spine=0.18,
                                  fsm_state=st)
    assert res.new_fsm_state is not None
    assert res.delta_drift is not None
    assert res.new_state in (DetectionState.NOMINAL, DetectionState.CANDIDATE)


# ── Pre-pivot anchor: jump-and-park (Clotho's ruling, Episode 839c5f91) ──────
#
# The S3 calibration failure: a pivot jumps, the live (EWM) centroid chases it,
# so the next turn on the SAME parked topic reads as decayed live-drift and the
# sustain gate resets. drift_vs_anchor measures the parked turn against the
# pre-pivot centroid, where it stays elevated — so a jump-and-park materializes.
# Drifts chosen so the live floor sits ~0.53 at the sustain turn: live 0.40
# (below) vs anchor 0.60 (above).

_JUMP_PARK = [
    (2, 0.00),   # baseline (prev None)
    (4, 0.50),   # warm-up (skipped)
    (6, 0.58),   # Δ+0.08 > 0.055 → CANDIDATE, sustain 1
    (8, 0.40),   # live drift collapses (centroid chased); anchor stays high
]


def _run_with_anchor(seq_drift, anchors):
    """Replay (seq, drift) with a parallel anchors dict {seq: drift_vs_anchor}."""
    s = DriftDetectionState()
    out = []
    for seq, d in seq_drift:
        r = advance_drift_fsm(s, d, seq, drift_vs_anchor=anchors.get(seq))
        s = r.new_state
        out.append((seq, r))
    return out


def test_anchor_sustains_jump_and_park():
    # With the pre-pivot anchor high (0.60) on the parked turn, sustain holds → materialize.
    out = _run_with_anchor(_JUMP_PARK, {8: 0.60})
    by = {seq: r for seq, r in out}
    assert by[6].fsm_state == "CANDIDATE"
    assert by[8].materialized is True
    assert by[8].fsm_state == "COOLDOWN"
    assert by[8].drift_vs_anchor == 0.60   # echoed for telemetry


def test_without_anchor_jump_and_park_decays():
    # Same drifts, no anchor → live-drift collapse resets the candidate (the old
    # broken behavior; confirms back-compat when drift_vs_anchor is absent).
    out = _run_with_anchor(_JUMP_PARK, {})  # no anchors
    by = {seq: r for seq, r in out}
    assert by[6].fsm_state == "CANDIDATE"
    assert by[8].materialized is False
    assert by[8].fsm_state == "NOMINAL"    # decayed → reset
