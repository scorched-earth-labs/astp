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

import re
from pathlib import Path

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

    def test_segment_commit_is_emitted_by_the_library(self):
        """SEGMENT_COMMIT now has a coordinated write path (SPEC S12.4 Tier 1).

        It previously had none: callers wrote the segment directly and the
        absence of a ledger entry was indistinguishable from a lost one.
        """
        from ariadne.adapters.neo4j import wil as wil_adapter

        assert hasattr(wil_adapter, "execute_segment_commit")
        source = Path(wil_adapter.__file__).read_text(encoding="utf-8")
        assert "WILOperation.SEGMENT_COMMIT" in source

    def test_episode_create_is_emitted_by_the_library(self):
        """EPISODE_CREATE has a coordinated write path (SPEC §12.4 Tier 1).

        Episode creation had no ledger entry at all: the episode appeared and
        nothing recorded that it was meant to. An interrupted create was
        indistinguishable from one that never started.
        """
        from ariadne.adapters.neo4j import wil as wil_adapter

        assert hasattr(wil_adapter, "execute_episode_create")
        source = Path(wil_adapter.__file__).read_text(encoding="utf-8")
        assert "WILOperation.EPISODE_CREATE" in source

    def test_episode_create_delegates_to_the_writer(self):
        """Must call create_episode_node, not carry a second copy of the MERGE."""
        from ariadne.adapters.neo4j import wil as wil_adapter

        source = Path(wil_adapter.__file__).read_text(encoding="utf-8")
        body = source[source.index("async def execute_episode_create"):
                      source.index("async def execute_signal_commit")]
        assert "create_episode_node" in body
        assert "MERGE (e:AriadneEpisode" not in body

    def test_consultation_commit_is_emitted_by_the_library(self):
        from ariadne.adapters.neo4j import wil as wil_adapter

        assert hasattr(wil_adapter, "execute_consultation_commit")
        source = Path(wil_adapter.__file__).read_text(encoding="utf-8")
        assert "WILOperation.CONSULTATION_COMMIT" in source

    def test_consultation_commit_writes_entries_in_sequence(self):
        """Each entry's previous_hash references the prior entry's content_hash.

        Writing them out of order builds the chain backwards, which is the
        failure G-8 exists to catch.
        """
        from ariadne.adapters.neo4j import wil as wil_adapter

        source = Path(wil_adapter.__file__).read_text(encoding="utf-8")
        body = source[source.index("async def execute_consultation_commit"):
                      source.index("async def execute_attachment_commit")]
        assert "sorted(entries, key=lambda e: e.sequence)" in body

    def test_collaboration_has_no_separate_operation(self):
        """Collaboration is a ConsultationType, not an operation.

        A second register name would encode in the ledger what the node already
        records, and the two would drift.
        """
        assert "COLLABORATION_COMMIT" not in {m.value for m in WILOperation}

    def test_attachment_commit_is_emitted_by_the_library(self):
        from ariadne.adapters.neo4j import wil as wil_adapter

        assert hasattr(wil_adapter, "execute_attachment_commit")
        source = Path(wil_adapter.__file__).read_text(encoding="utf-8")
        assert "WILOperation.ATTACHMENT_COMMIT" in source

    def test_attachment_commit_delegates_to_the_writer(self):
        from ariadne.adapters.neo4j import wil as wil_adapter

        source = Path(wil_adapter.__file__).read_text(encoding="utf-8")
        body = source[source.index("async def execute_attachment_commit"):
                      source.index("async def execute_codicil_append")]
        assert "create_attachment_node" in body
        assert "MERGE (a:AriadneAttachment" not in body

    def test_codicil_append_is_emitted_by_the_library(self):
        """CODICIL_APPEND had neither a ledger entry nor a writer to ledger."""
        from ariadne.adapters.neo4j import wil as wil_adapter

        assert hasattr(wil_adapter, "execute_codicil_append")
        source = Path(wil_adapter.__file__).read_text(encoding="utf-8")
        assert "WILOperation.CODICIL_APPEND" in source

    def test_crystallization_ledgers_the_whole_lock_sequence(self):
        """The intent must span acquire -> delta -> release, not just the write.

        An interruption partway leaves the episode pinned in
        CRYSTALLIZATION_PENDING; an incomplete entry beside a pinned episode is
        the signature a recovery needs. Ledgering only the delta write would
        leave the stuck state unexplained.
        """
        from ariadne.adapters.neo4j import wil as wil_adapter

        source = Path(wil_adapter.__file__).read_text(encoding="utf-8")
        body = source[source.index("async def execute_crystallization"):
                      source.index("async def execute_episode_close")]
        assert "acquire_crystallization_lock" in body
        assert "write_crystallization_delta" in body
        assert "release_crystallization_lock" in body
        # Compare CALL sites, not first occurrence — the names also appear in
        # the function's import block, which sits above everything.
        assert (body.index("await declare_write_intent(")
                < body.index("await acquire_crystallization_lock("))

    def test_crystallization_releases_the_lock_before_failing(self):
        """Order matters: a lock left held blocks every later write."""
        from ariadne.adapters.neo4j import wil as wil_adapter

        source = Path(wil_adapter.__file__).read_text(encoding="utf-8")
        body = source[source.index("async def execute_crystallization"):
                      source.index("async def execute_episode_close")]
        handler = body[body.index("except Exception as e:"):]
        assert (handler.index("await release_crystallization_lock(")
                < handler.index("await fail_write_intent("))

    def test_failed_lock_fails_the_intent(self):
        """A lock that was never acquired wrote nothing, so the entry must not
        be left dangling as a false recovery candidate."""
        from ariadne.adapters.neo4j import wil as wil_adapter

        source = Path(wil_adapter.__file__).read_text(encoding="utf-8")
        body = source[source.index("async def execute_crystallization"):
                      source.index("async def execute_episode_close")]
        assert "if not locked:" in body
        after = body[body.index("if not locked:"):]
        assert "fail_write_intent" in after[:600]

    def test_archive_ledgers_its_implicit_crystallization(self):
        """Archiving may auto-crystallize; when it does, that is a real
        crystallization and gets its own entry rather than being implied."""
        from ariadne.adapters.neo4j import wil as wil_adapter

        source = Path(wil_adapter.__file__).read_text(encoding="utf-8")
        body = source[source.index("async def execute_episode_archive"):
                      source.index("async def execute_crystallization")]
        assert "archive_episode" in body
        assert "redis_client=redis_client" in body

    def test_episode_close_is_emitted_by_the_library(self):
        from ariadne.adapters.neo4j import wil as wil_adapter

        assert hasattr(wil_adapter, "execute_episode_close")
        source = Path(wil_adapter.__file__).read_text(encoding="utf-8")
        assert "WILOperation.EPISODE_CLOSE" in source

    def test_episode_close_writes_record_and_transition_together(self):
        """Both halves inside one intent — see the docstring on the function."""
        from ariadne.adapters.neo4j import wil as wil_adapter

        source = Path(wil_adapter.__file__).read_text(encoding="utf-8")
        body = source[source.index("async def execute_episode_close"):
                      source.index("async def execute_signal_commit")]
        assert "create_closure_record_node" in body
        assert "update_episode_status" in body
        assert "MERGE (cl:AriadneClosureRecord" not in body

    def test_codicil_append_delegates_to_the_writer(self):
        from ariadne.adapters.neo4j import wil as wil_adapter

        source = Path(wil_adapter.__file__).read_text(encoding="utf-8")
        body = source[source.index("async def execute_codicil_append"):
                      source.index("async def execute_signal_commit")]
        assert "create_codicil_node" in body
        assert "MERGE (cod:AriadneCodicil" not in body

    def test_segment_commit_delegates_to_the_guarded_writer(self):
        """It must go through create_segment_node, not inline its own Cypher.

        create_segment_node enforces G-1 and the crystallization lock. A
        coordinated write that duplicated the MERGE would bypass both — a
        ledger entry is not a licence to skip governance.
        """
        from ariadne.adapters.neo4j import wil as wil_adapter

        source = Path(wil_adapter.__file__).read_text(encoding="utf-8")
        body = source[source.index("async def execute_segment_commit"):
                      source.index("async def execute_episode_seal")]
        assert "create_segment_node" in body
        assert "MERGE (s:AriadneSegment" not in body


class TestSpecRegisterAgreement:
    """SPEC S12.4.1 registers every operation value. The enum must match it.

    This is the drift guard. WILOperation was previously missing eight of the
    ten operations its own writer emitted, and nothing failed — the register
    existed only as code, so there was nothing for the code to disagree with.
    """

    @staticmethod
    def _spec_register() -> dict:
        spec = Path(__file__).resolve().parents[3] / "SPEC.md"
        text = spec.read_text(encoding="utf-8")
        section = text[text.index("#### 12.4.1 Operation Register"):]
        section = section[: section.index("The register is closed")]
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
        assert missing == [], f"in WILOperation but absent from SPEC S12.4.1: {missing}"

    def test_bfm_operations_are_tier_2(self):
        """Single store, completed entry at commit, never replayed (G-38)."""
        register = self._spec_register()
        for name in BFM_OPERATIONS:
            assert register[name] == 2, f"{name} registered Tier {register[name]}"

    def test_every_registered_operation_is_emitted(self):
        """G-39's precondition, and the reference implementation's own compliance.

        §12.4.2 (G-39) requires a ledger entry for every registered operation an
        implementation performs. This library performs all of them, so this test
        IS its conformance check — not merely a readiness gate as it was while
        the obligation was still deferred.

        It was deferred precisely because stating the requirement while the
        reference implementation ledgered almost none of them would have
        published a rule this library fails.

        If this fails, either a new operation was registered without a writer —
        which recreates exactly the gap §12.4.2 exists to acknowledge — or a
        writer stopped emitting one.
        """
        import re as _re
        from pathlib import Path as _Path

        root = _Path(__file__).resolve().parents[3] / "ariadne"
        source = "\n".join(
            p.read_text(encoding="utf-8") for p in root.rglob("*.py")
        )
        emitted = set(_re.findall(r"WILOperation\.([A-Z_]+)", source))
        registered = {m.value for m in WILOperation}

        unemitted = sorted(registered - emitted)
        assert unemitted == [], (
            f"registered but never emitted by this library: {unemitted}. "
            "Either wire a write path or reconsider whether the operation "
            "belongs in the register."
        )

    def test_close_and_seal_are_distinct_operations(self):
        """Closing produces a closure record and CLOSED; sealing produces a
        SealNode, the spine hash and SEALED. Registering both means neither may
        stand in for the other."""
        register = self._spec_register()
        assert register["EPISODE_CLOSE"] == 1
        assert register["EPISODE_SEAL"] == 1

    def test_coordinated_writes_are_tier_1(self):
        """Everything this library declares an intent for must be Tier 1.

        Derived from the source rather than listed, so wiring a new coordinated
        write cannot quietly introduce one registered as Tier 2 — the tier is a
        claim about the entry's form, and a coordinated write that claims Tier 2
        would be lying about its own shape.
        """
        import re as _re
        from ariadne.adapters.neo4j import wil as wil_adapter

        source = Path(wil_adapter.__file__).read_text(encoding="utf-8")
        coordinated = set(_re.findall(
            r"declare_write_intent\(\s*\n?\s*redis_client,\s*WILOperation\.([A-Z_]+)",
            source,
        ))
        assert coordinated, "no coordinated writes found — the parser broke"

        register = self._spec_register()
        for name in sorted(coordinated):
            assert name in register, f"{name} is coordinated but absent from §12.4.1"
            assert register[name] == 1, (
                f"{name} is coordinated but registered Tier {register[name]}"
            )

    def test_register_states_no_ledgering_obligation(self):
        """S12.4.2 defers WHICH operations must be ledgered to 4.0.0.

        Guards against a well-meaning edit reintroducing per-operation MUST /
        SHOULD levels into the register table. Those are conformance-breaking
        and belong to a MAJOR release with a ratifying Episode of Record, not
        to this table.
        """
        spec = Path(__file__).resolve().parents[3] / "SPEC.md"
        text = spec.read_text(encoding="utf-8")
        section = text[text.index("#### 12.4.1 Operation Register"):
                       text.index("#### 12.4.2 Ledgering Obligations")]
        rows = re.findall(r"^\|\s*`[A-Z_]+`\s*\|.*$", section, re.M)
        offenders = [r for r in rows if re.search(r"\b(MUST|SHOULD|MAY)\b", r)]
        assert offenders == [], (
            "requirement levels reappeared in the S12.4.1 register; "
            f"obligations are deferred to 4.0.0 per S12.4.2: {offenders}"
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
