"""A node writer must persist every field its model declares.

`create_segment_node` dropped four of SegmentNode's twelve fields —
content_text, retention_tier, signal_versions_read, pending_hitl_ref. The model
said the data existed; the graph did not have it; nothing failed. A consumer
that needed any of them had no option but to bypass the adapter and hand-write
Cypher, which is what downstream did, and which is how a "conforming" write
path quietly stops being the write path.

Same shape as the WIL operation register: a declaration and its implementation
kept in sync by hand, with no mechanism to notice when they diverge.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from ariadne.core.schema import (
    CodicilNode,
    EpisodeClosureRecord,
    SegmentNode,
    SignalNode,
)

WRITER = Path(__file__).resolve().parents[3] / "ariadne" / "adapters" / "neo4j" / "writer.py"
SOURCE = WRITER.read_text(encoding="utf-8")


def _writer_body(fn_name: str, next_fn: str) -> str:
    return SOURCE[SOURCE.index(f"async def {fn_name}"): SOURCE.index(f"async def {next_fn}")]


def _persisted_params(body: str) -> set[str]:
    """Parameter names the function binds into its Cypher."""
    return set(re.findall(r'"(\w+)":', body))


def _cypher_assignments(body: str) -> set[str]:
    """Node properties the Cypher actually SETs."""
    return set(re.findall(r"^\s*\w+\.(\w+)\s*=", body, re.M))


class TestSegmentWriterParity:
    BODY = _writer_body("create_segment_node", "create_signal_node")

    @pytest.mark.parametrize("field", sorted(SegmentNode.model_fields))
    def test_field_is_bound_as_a_parameter(self, field):
        assert field in _persisted_params(self.BODY), (
            f"SegmentNode.{field} is declared on the model but create_segment_node "
            "never binds it — the node would be written without it, silently"
        )

    def test_every_field_is_set_in_cypher(self):
        # segment_id is the MERGE key, so it is matched rather than SET.
        expected = set(SegmentNode.model_fields) - {"segment_id"}
        missing = sorted(expected - _cypher_assignments(self.BODY))
        assert missing == [], f"declared but never SET on the node: {missing}"

    def test_the_four_regressed_fields_specifically(self):
        """Named explicitly so the regression is legible in a failure report."""
        body = self.BODY
        for field in ("content_text", "retention_tier", "signal_versions_read", "pending_hitl_ref"):
            assert field in _persisted_params(body), f"{field} dropped again"


class TestSignalWriterParity:
    """Same invariant for signals — checked so the fix is not segment-only."""

    BODY = _writer_body("create_signal_node", "create_seal_node")

    def test_signal_fields_are_bound(self):
        params = _persisted_params(self.BODY)
        missing = sorted(f for f in SignalNode.model_fields if f not in params)
        assert missing == [], f"SignalNode fields never bound by create_signal_node: {missing}"


class TestCodicilWriterParity:
    """create_codicil_node had no implementation at all until now."""

    BODY = _writer_body("create_codicil_node", "create_exclusion_record")

    @pytest.mark.parametrize("field", sorted(CodicilNode.model_fields))
    def test_field_is_bound_as_a_parameter(self, field):
        assert field in _persisted_params(self.BODY), (
            f"CodicilNode.{field} is declared on the model but "
            "create_codicil_node never binds it"
        )

    def test_every_field_is_set_in_cypher(self):
        expected = set(CodicilNode.model_fields) - {"codicil_id"}  # MERGE key
        missing = sorted(expected - _cypher_assignments(self.BODY))
        assert missing == [], f"declared but never SET on the node: {missing}"

    def test_g1_is_deliberately_not_enforced(self):
        """A codicil is the sanctioned post-closure write.

        G-1 blocks writes to SEALING / SEALED / ARCHIVED episodes. A codicil
        exists precisely to add to a closed episode without integrating into
        the sealed record, so enforcing G-1 here would make the node type
        unwritable in the only state it is for. Pinned because "this writer is
        missing its guard" is exactly the kind of thing a later reader fixes by
        adding one.
        """
        assert "enforce_G1_write_guard" not in self.BODY

    def test_links_the_codicil_to_its_episode(self):
        assert "HAS_CODICIL" in self.BODY


class TestClosureRecordWriterParity:
    """create_closure_record_node had no implementation until now."""

    BODY = _writer_body("create_closure_record_node", "create_codicil_node")

    @pytest.mark.parametrize("field", sorted(EpisodeClosureRecord.model_fields))
    def test_field_is_bound_as_a_parameter(self, field):
        assert field in _persisted_params(self.BODY), (
            f"EpisodeClosureRecord.{field} is declared on the model but "
            "create_closure_record_node never binds it"
        )

    def test_every_field_is_set_in_cypher(self):
        expected = set(EpisodeClosureRecord.model_fields) - {"closure_id"}  # MERGE key
        missing = sorted(expected - _cypher_assignments(self.BODY))
        assert missing == [], f"declared but never SET on the node: {missing}"

    def test_links_closure_to_episode(self):
        """Edge direction is closure -> episode, matching the live graph."""
        assert "SEALS_EPISODE" in self.BODY
        assert "(cl)-[:SEALS_EPISODE" in self.BODY


class TestUpdateEpisodeStatus:
    """Property names cannot be parameterised in Cypher, so the field set is
    an allowlist rather than a passthrough."""

    def test_rejects_unknown_fields(self):
        import asyncio

        from ariadne.core.schema import AriadneGovernanceError, EpisodeStatus
        from ariadne.adapters.neo4j.writer import update_episode_status

        with pytest.raises(AriadneGovernanceError):
            asyncio.run(update_episode_status(
                object(), "ep-1", EpisodeStatus.CLOSED,
                **{"sealed_at) SET e.pwned = true //": "x"},
            ))

    def test_allowlist_covers_the_lifecycle_fields(self):
        from ariadne.adapters.neo4j.writer import _UPDATABLE_EPISODE_FIELDS

        for field in ("sealed_at", "archived_at", "spine_hash"):
            assert field in _UPDATABLE_EPISODE_FIELDS
