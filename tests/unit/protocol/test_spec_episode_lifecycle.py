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
"""SPEC §4.4.1 must list exactly the states EpisodeStatus defines.

The Episode lifecycle is stated twice — in the SPEC §4.4.1 table and in the
`EpisodeStatus` enum. These tests compare the two so neither can gain or lose
a state without the other.
"""
from __future__ import annotations

import re
from pathlib import Path

from astp.core.schema import EpisodeStatus

SPEC = Path(__file__).resolve().parents[3] / "SPEC.md"


SECTION_HEADING = "#### 4.4.1 Episode Lifecycle States"
# The state table ends at the first paragraph after it.
TABLE_END = "**Crystallization is a fact"


def _spec_states() -> set[str]:
    text = SPEC.read_text(encoding="utf-8")
    start = text.find(SECTION_HEADING)
    assert start != -1, f"SPEC.md has no {SECTION_HEADING!r} heading"
    end = text.find(TABLE_END, start)
    assert end != -1, (
        f"SPEC.md §4.4.1 no longer contains the paragraph starting {TABLE_END!r}, "
        "which this test uses to find the end of the state table"
    )
    section = text[start:end]
    return set(re.findall(r"^\|\s*`([A-Z_]+)`\s*\|", section, re.M))


def test_spec_section_exists():
    assert SECTION_HEADING in SPEC.read_text(encoding="utf-8")


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
    """SPEC must not name a state the enum does not define."""
    extra = sorted(_spec_states() - {m.value for m in EpisodeStatus})
    assert extra == [], (
        f"SPEC §4.4.1 documents states EpisodeStatus does not define: {extra}."
    )


def test_the_four_never_implemented_states_stay_gone():
    """Named explicitly so a revert is legible rather than a silent regression."""
    fictional = {"REBALANCING", "SEALING_FAILED", "REBALANCE_FAILED", "EXPIRED"}
    assert not (fictional & _spec_states())
    assert not (fictional & {m.value for m in EpisodeStatus})
