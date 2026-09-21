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
"""WIL operation vocabulary and the BFM ledger write helper.

`WILOperation` is the authoritative list of ledger operations, so every
operation a BFM call site ledgers must be a member, and the enum must match
the SPEC §12.4.1 register.

`_write_branch_wil` wraps its ledger write in a blanket `except Exception`; a
bad operation value must still fail loudly rather than vanish into it. These
tests pin both halves: the vocabulary is complete, and a violation of it is
loud.
"""

import re
from pathlib import Path

import pytest

from astp.adapters.memory import InMemoryStore
from astp.core.branch_operations import _write_branch_wil
from astp.core.wil import WILOperation


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


class _BrokenStore(InMemoryStore):
    """A store whose ledger write fails."""

    def write_completed_wil_entry(self, *a, **k):
        raise RuntimeError("store unavailable")


class TestWILOperationVocabulary:
    @pytest.mark.parametrize("name", BFM_OPERATIONS)
    def test_bfm_operation_is_a_member(self, name):
        assert WILOperation[name].value == name

    def test_member_name_matches_value(self):
        """Values are persisted on AriadneWILEntry nodes — they must not drift."""
        for member in WILOperation:
            assert member.name == member.value

    def test_segment_commit_is_a_member(self):
        """SEGMENT_COMMIT is part of the vocabulary — without it, anything
        treating WILOperation as authoritative is incomplete for the single
        most common operation in the graph.
        """
        assert WILOperation.SEGMENT_COMMIT.value == "SEGMENT_COMMIT"


    def test_collaboration_has_no_separate_operation(self):
        """Collaboration is a ConsultationType, not an operation.

        A second register name would encode in the ledger what the node already
        records, and the two would drift.
        """
        assert "COLLABORATION_COMMIT" not in {m.value for m in WILOperation}


def _spec_slice(text: str, start_marker: str, end_marker: str) -> str:
    """SPEC.md text from ``start_marker`` up to the next ``end_marker``."""
    start = text.find(start_marker)
    assert start != -1, f"SPEC.md no longer contains {start_marker!r}"
    end = text.find(end_marker, start)
    assert end != -1, f"SPEC.md no longer contains {end_marker!r} after {start_marker!r}"
    return text[start:end]


class TestSpecRegisterAgreement:
    """SPEC §12.4.1 registers every operation value. The enum must match it.

    This is the drift guard: the register exists both as SPEC text and as
    code, and the two must not disagree.
    """

    @staticmethod
    def _spec_register() -> dict:
        spec = Path(__file__).resolve().parents[3] / "SPEC.md"
        text = spec.read_text(encoding="utf-8")
        section = _spec_slice(text, "#### 12.4.1 Operation Register", "The register is closed")
        register = {}
        for row in re.finditer(
            r"^\|\s*`([A-Z_]+)`\s*\|\s*([12])\s*\|",
            section,
            re.M,
        ):
            register[row.group(1)] = int(row.group(2))
        return register

    def test_spec_table_parses(self):
        """The table is found and readable — not a pinned row count.

        Pinning the count breaks on every deliberate register change while
        catching nothing the two-way agreement tests below do not already
        catch. The floor exists to fail a broken regex that matches nothing or
        a couple of stray rows.
        """
        register = self._spec_register()
        assert len(register) >= 15, (
            f"only {len(register)} rows parsed out of the §12.4.1 register — "
            "the table moved or the parser broke"
        )
        assert all(tier in (1, 2) for tier in register.values())

    def test_every_spec_operation_is_an_enum_member(self):
        missing = [op for op in self._spec_register() if op not in WILOperation.__members__]
        assert missing == [], f"registered in SPEC but absent from WILOperation: {missing}"

    def test_every_enum_member_is_registered_in_spec(self):
        register = self._spec_register()
        missing = [m.value for m in WILOperation if m.value not in register]
        assert missing == [], f"in WILOperation but absent from SPEC §12.4.1: {missing}"

    def test_bfm_operations_are_tier_2(self):
        """Single store, completed entry at commit, never replayed (G-38)."""
        register = self._spec_register()
        for name in BFM_OPERATIONS:
            assert register[name] == 2, f"{name} registered Tier {register[name]}"


    def test_close_and_seal_are_distinct_operations(self):
        """Closing produces a closure record and CLOSED; sealing produces a
        SealNode, the spine hash and SEALED. Registering both means neither may
        stand in for the other."""
        register = self._spec_register()
        assert register["EPISODE_CLOSE"] == 1
        assert register["EPISODE_SEAL"] == 1


    def test_register_states_no_ledgering_obligation(self):
        """§12.4.2 defers WHICH operations must be ledgered to 4.0.0.

        Guards against a well-meaning edit reintroducing per-operation MUST /
        SHOULD levels into the register table. Those are conformance-breaking
        and belong to a MAJOR release with a ratifying Episode of Record, not
        to this table.
        """
        spec = Path(__file__).resolve().parents[3] / "SPEC.md"
        text = spec.read_text(encoding="utf-8")
        section = _spec_slice(
            text, "#### 12.4.1 Operation Register", "#### 12.4.2 Ledgering Obligations"
        )
        rows = re.findall(r"^\|\s*`[A-Z_]+`\s*\|.*$", section, re.M)
        offenders = [r for r in rows if re.search(r"\b(MUST|SHOULD|MAY)\b", r)]
        assert offenders == [], (
            "requirement levels reappeared in the §12.4.1 register; "
            f"obligations are deferred to 4.0.0 per §12.4.2: {offenders}"
        )


class TestBranchWILWrite:
    @pytest.mark.parametrize("name", BFM_OPERATIONS)
    def test_writes_plain_string_value(self, name):
        store = InMemoryStore()
        _write_branch_wil(store, "ep-1", "node-1", WILOperation[name])

        assert len(store.wil_entries) == 1, "ledger write did not reach the store"
        operation = next(iter(store.wil_entries.values()))["operation"]
        # The store must receive a primitive, and it must equal the value
        # already stored on existing nodes — this change is not a migration.
        assert type(operation) is str
        assert operation == name

    def test_legacy_bare_string_is_coerced(self):
        store = InMemoryStore()
        _write_branch_wil(store, "ep-1", "node-1", "SOLILOQUY_INIT")
        assert next(iter(store.wil_entries.values()))["operation"] == "SOLILOQUY_INIT"

    def test_unknown_operation_raises(self):
        """Must NOT be swallowed by the blanket handler — that is the whole point."""
        with pytest.raises(ValueError):
            _write_branch_wil(InMemoryStore(), "ep-1", "node-1", "NOT_A_REAL_OP")

    def test_store_failure_raises(self):
        """5.1.0: a ledger entry that cannot be written fails the operation that
        needed it (G-39) — it is never silently skipped."""
        from astp.protocol.errors import AdapterWriteError
        with pytest.raises(AdapterWriteError):
            _write_branch_wil(_BrokenStore(), "ep-1", "node-1", WILOperation.BRANCH_CREATE)
