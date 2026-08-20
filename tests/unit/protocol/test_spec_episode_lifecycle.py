"""SPEC §4.4.1 must list exactly the states EpisodeStatus defines.

This section was wrong from the day it was written. On 2026-04-07 the enum
already carried CREATED, CLOSING, CLOSING_PENDING_SEAL, CLOSED,
CRYSTALLIZATION_PENDING and CRYSTALLIZED. Two days later the v2 SPEC rewrite
described the lifecycle as "ACTIVE, REBALANCING, SEALING, SEALED,
SEALING_FAILED, REBALANCE_FAILED, ARCHIVED, EXPIRED" — four states the
implementation has never had, and six of its real ones missing.

It survived sixteen months because nothing could compare the two. That is the
same failure as the WIL operation register: a fact stated in two places with no
mechanism to notice when they disagree. This is the mechanism.
"""
from __future__ import annotations

import re
from pathlib import Path

from ariadne.core.schema import EpisodeStatus

SPEC = Path(__file__).resolve().parents[3] / "SPEC.md"


def _spec_states() -> set[str]:
    text = SPEC.read_text(encoding="utf-8")
    start = text.index("#### 4.4.1 Episode Lifecycle States")
    section = text[start:]
    # The table ends at the first paragraph after it.
    section = section[: section.index("**Crystallization is a fact")]
    return set(re.findall(r"^\|\s*`([A-Z_]+)`\s*\|", section, re.M))


def test_spec_section_exists():
    assert "#### 4.4.1 Episode Lifecycle States" in SPEC.read_text(encoding="utf-8")


def test_table_parses():
    states = _spec_states()
    assert len(states) >= 8, f"only {len(states)} states parsed — the table moved or broke"


def test_every_enum_state_is_documented():
    missing = sorted({m.value for m in EpisodeStatus} - _spec_states())
    assert missing == [], (
        f"EpisodeStatus values absent from SPEC §4.4.1: {missing}. "
        "An implementer reading the spec would build a state machine that "
        "cannot interoperate."
    )


def test_no_documented_state_is_fictional():
    """The original failure mode: the spec named states that never existed."""
    extra = sorted(_spec_states() - {m.value for m in EpisodeStatus})
    assert extra == [], (
        f"SPEC §4.4.1 documents states EpisodeStatus does not define: {extra}."
    )


def test_the_four_never_implemented_states_stay_gone():
    """Named explicitly so a revert is legible rather than a silent regression."""
    fictional = {"REBALANCING", "SEALING_FAILED", "REBALANCE_FAILED", "EXPIRED"}
    assert not (fictional & _spec_states())
    assert not (fictional & {m.value for m in EpisodeStatus})
