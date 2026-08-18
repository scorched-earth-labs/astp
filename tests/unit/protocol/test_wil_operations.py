"""WIL operation vocabulary and the BFM ledger write helper.

`_write_branch_wil` previously took `operation: str` and every BFM call site
passed a literal. Eight of the ten literals in use were absent from
`WILOperation`, so the enum read as the authoritative list of ledger
operations without actually being one — anything downstream that trusted it
was silently incomplete.

The helper also wraps its whole body in a blanket `except Exception`, so a bad
value would have vanished rather than failed. These tests pin both halves: the
vocabulary is complete, and a violation of it is loud.
"""

import pytest

from ariadne.core.wil import WILOperation
from ariadne.core.branch_operations import _write_branch_wil


# Every operation `_write_branch_wil` is called with across branch_operations.py.
BFM_OPERATIONS = [
    "BRANCH_CREATE",
    "BRANCH_ABANDON",
    "FORK_CREATE",
    "FORK_RESOLVE",
    "DEPARTURE_FORK_CREATE",
    "MERGE_EXECUTE",
    "ASIDE_OPEN",
    "ASIDE_CLOSE",
    "SOLILOQUY_INIT",
    "SOLILOQUY_CONCLUDE",
]


class _FakeSession:
    def __init__(self, sink):
        self._sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, _cypher, params):
        self._sink.append(params)


class _FakeDriver:
    def __init__(self):
        self.writes = []

    def session(self):
        return _FakeSession(self.writes)


class _BrokenDriver:
    def session(self):
        raise RuntimeError("neo4j unavailable")


class TestWILOperationVocabulary:
    @pytest.mark.parametrize("name", BFM_OPERATIONS)
    def test_bfm_operation_is_a_member(self, name):
        assert WILOperation[name].value == name

    def test_member_name_matches_value(self):
        """Values are persisted on AriadneWILEntry nodes — they must not drift."""
        for member in WILOperation:
            assert member.name == member.value

    def test_segment_commit_is_a_member(self):
        """Segment commits appear on AriadneWILEntry nodes in the field.

        The value is written by downstream consumers rather than by this
        library — see the note on the member. It still has to be part of the
        vocabulary, or anything treating WILOperation as authoritative is
        incomplete for the single most common operation in the graph.
        """
        assert WILOperation.SEGMENT_COMMIT.value == "SEGMENT_COMMIT"

    def test_segment_commit_is_not_yet_emitted_here(self):
        """Documents a known gap so closing it is a deliberate, visible change.

        `create_segment_node` writes the segment without declaring a write
        intent, so this library never emits SEGMENT_COMMIT. When segment
        commits get the coordinated-write treatment SIGNAL_COMMIT has, this
        test should fail and be replaced by coverage of the real write path.
        """
        from pathlib import Path

        ariadne_root = Path(__file__).resolve().parents[3] / "ariadne"
        emitted = [
            path
            for path in ariadne_root.rglob("*.py")
            if "WILOperation.SEGMENT_COMMIT" in path.read_text(encoding="utf-8")
        ]
        assert emitted == [], (
            "SEGMENT_COMMIT is now emitted by the library — the segment write "
            "path has ledger coverage. Replace this test with coverage of it."
        )


class TestBranchWILWrite:
    @pytest.mark.parametrize("name", BFM_OPERATIONS)
    def test_writes_plain_string_value(self, name):
        driver = _FakeDriver()
        _write_branch_wil(driver, "ep-1", "node-1", WILOperation[name])

        assert len(driver.writes) == 1, "ledger write did not reach the driver"
        operation = driver.writes[0]["operation"]
        # The driver must receive a primitive, and it must equal the value
        # already stored on existing nodes — this change is not a migration.
        assert type(operation) is str
        assert operation == name

    def test_legacy_bare_string_is_coerced(self):
        driver = _FakeDriver()
        _write_branch_wil(driver, "ep-1", "node-1", "SOLILOQUY_INIT")
        assert driver.writes[0]["operation"] == "SOLILOQUY_INIT"

    def test_unknown_operation_raises(self):
        """Must NOT be swallowed by the blanket handler — that is the whole point."""
        with pytest.raises(ValueError):
            _write_branch_wil(_FakeDriver(), "ep-1", "node-1", "NOT_A_REAL_OP")

    def test_driver_failure_stays_non_fatal(self):
        """A ledger hiccup must never fail the branch operation around it."""
        _write_branch_wil(_BrokenDriver(), "ep-1", "node-1", WILOperation.BRANCH_CREATE)
