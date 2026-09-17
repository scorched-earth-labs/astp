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
"""The crystallization lock must restore what it displaced.

`release_crystallization_lock` must not set CRYSTALLIZED on success. Whether an
episode is crystallized is a fact stored elsewhere — `is_episode_crystallized`
counts CrystallizationDelta nodes and never reads `episode_status` — and an
episode crystallizing during a seal is in CLOSING: landing it in CRYSTALLIZED
would strand it outside the closure workflow with no documented transition back.

SPEC §4.4.1 makes restoring the prior status explicitly permitted, and required
for correctness in that case.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

ADAPTER = (
    Path(__file__).resolve().parents[3]
    / "astp" / "adapters" / "neo4j" / "crystallization.py"
)


@lru_cache(maxsize=None)
def _source() -> str:
    return ADAPTER.read_text(encoding="utf-8")


def _fn(name: str, nxt: str) -> str:
    """Source text from ``async def name`` up to ``async def nxt``.

    Called from inside tests (never at import), so a renamed or reordered
    function fails the test that depends on it instead of breaking collection.
    """
    source = _source()
    start = source.find(f"async def {name}")
    assert start != -1, f"`async def {name}` not found in {ADAPTER.name}"
    end = source.find(f"async def {nxt}", start)
    assert end != -1, (
        f"`async def {nxt}` not found after `{name}` in {ADAPTER.name} — "
        "it bounds the slice this test inspects"
    )
    return source[start:end]


def _code(name: str, nxt: str) -> str:
    """Function body with its docstring removed.

    Assertions about what the code does must not be satisfied — or broken — by
    prose that merely describes it: the docstring names CRYSTALLIZED, which
    would otherwise defeat the test asserting the code never sets it.
    """
    body = _fn(name, nxt)
    return re.sub(r'"""(?:.|\n)*?"""', "", body, count=1)


class TestAcquire:
    @property
    def BODY(self) -> str:
        return _code("acquire_crystallization_lock", "release_crystallization_lock")

    def test_records_the_displaced_status(self):
        assert "crystallization_prior_status = prior" in self.BODY

    def test_captures_prior_in_the_same_statement_that_overwrites_it(self):
        """Reading it separately would race another writer."""
        assert "WITH e, e.episode_status AS prior" in self.BODY

    def test_acquirable_during_closure(self):
        """The lock must be usable by the seal flow, not from ACTIVE only."""
        for state in ("ACTIVE", "CLOSING", "CLOSING_PENDING_SEAL"):
            assert state in self.BODY
        assert "WHERE e.episode_status = 'ACTIVE'" not in self.BODY

    def test_still_refuses_on_blocking_hitl(self):
        """G-18: a blocking HITL gate refuses the lock."""
        assert "pending_hitl" in self.BODY


class TestRelease:
    @property
    def BODY(self) -> str:
        return _code("release_crystallization_lock", "write_crystallization_delta")

    def test_restores_the_prior_status(self):
        assert "coalesce(e.crystallization_prior_status, 'ACTIVE')" in self.BODY

    def test_no_longer_sets_crystallized(self):
        """Release restores the displaced status; it never sets CRYSTALLIZED."""
        assert "CRYSTALLIZED" not in self.BODY

    def test_clears_the_prior_status_marker(self):
        assert "e.crystallization_prior_status = null" in self.BODY

    def test_falls_back_when_no_prior_recorded(self):
        """A lock with no recorded prior status (e.g. taken by a caller's own Cypher) falls back to ACTIVE."""
        assert "'ACTIVE'" in self.BODY
