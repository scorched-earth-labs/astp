"""The crystallization lock must restore what it displaced.

`release_crystallization_lock` used to set CRYSTALLIZED on success. That
conflated a lifecycle status with a fact stored elsewhere — `is_episode_crystallized`
counts CrystallizationDelta nodes and never reads `episode_status` — and it was
outright wrong mid-closure: an episode crystallizing during a seal is in
CLOSING, and landing it in CRYSTALLIZED strands it outside the closure workflow
with no documented transition back.

SPEC §4.4.1 makes restoring the prior status explicitly permitted, and required
for correctness in that case.
"""
from __future__ import annotations

import re
from pathlib import Path

SOURCE = (
    Path(__file__).resolve().parents[3]
    / "ariadne" / "adapters" / "neo4j" / "crystallization.py"
).read_text(encoding="utf-8")


def _fn(name: str, nxt: str) -> str:
    return SOURCE[SOURCE.index(f"async def {name}"): SOURCE.index(f"async def {nxt}")]


def _code(name: str, nxt: str) -> str:
    """Function body with its docstring removed.

    Assertions about what the code does must not be satisfied — or broken — by
    prose that merely describes it. The docstring here explains the CRYSTALLIZED
    behaviour that was removed, which would otherwise defeat the test asserting
    it is gone.
    """
    body = _fn(name, nxt)
    return re.sub(r'"""(?:.|\n)*?"""', "", body, count=1)


class TestAcquire:
    BODY = _code("acquire_crystallization_lock", "release_crystallization_lock")

    def test_records_the_displaced_status(self):
        assert "crystallization_prior_status = prior" in self.BODY

    def test_captures_prior_in_the_same_statement_that_overwrites_it(self):
        """Reading it separately would race another writer."""
        assert "WITH e, e.episode_status AS prior" in self.BODY

    def test_acquirable_during_closure(self):
        """ACTIVE-only made the protocol lock unusable for the seal flow."""
        for state in ("ACTIVE", "CLOSING", "CLOSING_PENDING_SEAL"):
            assert state in self.BODY
        assert "WHERE e.episode_status = 'ACTIVE'" not in self.BODY

    def test_still_refuses_on_blocking_hitl(self):
        """SPEC §7 / G-18 — unchanged by the widening."""
        assert "pending_hitl" in self.BODY


class TestRelease:
    BODY = _code("release_crystallization_lock", "write_crystallization_delta")

    def test_restores_the_prior_status(self):
        assert "coalesce(e.crystallization_prior_status, 'ACTIVE')" in self.BODY

    def test_no_longer_sets_crystallized(self):
        """The regression this exists to prevent."""
        assert "CRYSTALLIZED" not in self.BODY

    def test_clears_the_prior_status_marker(self):
        assert "e.crystallization_prior_status = null" in self.BODY

    def test_falls_back_when_no_prior_recorded(self):
        """Locks taken before this change, or by a caller using its own Cypher."""
        assert "'ACTIVE'" in self.BODY
