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
    AmendmentLink,
    ConsultationNode,
    ConsultationParticipantNode,
    ExchangeEntry,
    AttachmentNode,
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


class TestAttachmentWriterParity:
    BODY = _writer_body("create_attachment_node", "create_codicil_node")

    @pytest.mark.parametrize("field", sorted(AttachmentNode.model_fields))
    def test_field_is_bound_as_a_parameter(self, field):
        assert field in _persisted_params(self.BODY), (
            f"AttachmentNode.{field} is declared but create_attachment_node "
            "never binds it"
        )

    def test_every_field_is_set_in_cypher(self):
        expected = set(AttachmentNode.model_fields) - {"attachment_id"}  # MERGE key
        missing = sorted(expected - _cypher_assignments(self.BODY))
        assert missing == [], f"declared but never SET: {missing}"

    def test_links_to_the_episode(self):
        assert "ATTACHED_TO" in self.BODY

    def test_g1_is_not_enforced(self):
        """Attaching is not a spine write — see the writer's docstring."""
        assert "enforce_G1_write_guard" not in self.BODY

    def test_carries_no_vendor_or_text_specific_fields(self):
        """The mistake AttachmentNode exists to avoid.

        DocumentNode claimed protocol status while carrying drive_url (a
        vendor) and content_text / char_count (assuming the attachment is
        text). Those are what made the claim untrue, so their absence here is
        the point of the node, not an oversight.
        """
        for leaked in ("drive_url", "content_text", "char_count", "filename"):
            assert leaked not in AttachmentNode.model_fields


class TestAmendmentLinkWriterParity:
    """The last abstract adapter method that had no implementation."""

    BODY = _writer_body("create_amendment_link_node", "create_attachment_node")

    @pytest.mark.parametrize("field", sorted(AmendmentLink.model_fields))
    def test_field_is_bound_as_a_parameter(self, field):
        assert field in _persisted_params(self.BODY), (
            f"AmendmentLink.{field} is declared but create_amendment_link_node "
            "never binds it"
        )

    def test_every_field_is_set_in_cypher(self):
        expected = set(AmendmentLink.model_fields) - {"amendment_id"}  # MERGE key
        missing = sorted(expected - _cypher_assignments(self.BODY))
        assert missing == [], f"declared but never SET: {missing}"

    def test_writes_both_directions(self):
        """AMENDS to the source, PRODUCES to the new episode.

        The link is not symmetric: following provenance backwards wants the
        source, asking "what came of this" wants the amendment. One edge would
        make the other direction a scan.
        """
        assert "AMENDS" in self.BODY
        assert "PRODUCES" in self.BODY

    def test_g1_is_not_enforced(self):
        """The source is sealed by definition — that is the precondition for
        amending it, not an obstacle. Nothing about the sealed record changes."""
        assert "enforce_G1_write_guard" not in self.BODY


class TestAdapterSurfaceComplete:
    """Every abstract adapter method should have a Neo4j implementation.

    Four were missing when this work started — create_codicil,
    create_closure_record, update_episode_status and create_amendment_link —
    and each one is why some consumer hand-wrote Cypher instead of calling the
    adapter. A declared-but-unimplemented method is worse than an absent one:
    it looks like a supported path.
    """

    #: Implementations whose names diverge from the abstract method.
    ALIASES = {
        "initialize_schema": "initialize_ariadne_schema",
        "create_document": "write_document_node_sync",  # sync, by design
    }

    #: Abstract methods with no Neo4j implementation.
    #:
    #: Empty, and it should stay that way. It briefly held the three
    #: consultation methods, on the belief that v3.5.0 had retired consultation
    #: from the protocol. It had not: G-8 and G-9 have governed consultation
    #: since v1, so the retirement premise was wrong and the methods were
    #: implemented rather than removed (4.2.0).
    KNOWN_UNIMPLEMENTED: set[str] = set()

    def _unimplemented(self) -> list[str]:
        import re as _re

        root = Path(__file__).resolve().parents[3] / "ariadne"
        base = (root / "adapters" / "base.py").read_text(encoding="utf-8")
        abstract = _re.findall(r"@abstractmethod\s*\n\s*async def (\w+)\(", base)

        impl = ""
        for path in (root / "adapters" / "neo4j").glob("*.py"):
            impl += path.read_text(encoding="utf-8")
        defined = set(_re.findall(r"^(?:async )?def (\w+)\(", impl, _re.M))

        missing = []
        for name in abstract:
            if self.ALIASES.get(name) in defined:
                continue
            if any(name in d or d in name for d in defined):
                continue
            missing.append(name)
        return sorted(missing)

    def test_no_unexpected_abstract_method_lacks_an_implementation(self):
        unexpected = sorted(set(self._unimplemented()) - self.KNOWN_UNIMPLEMENTED)
        assert unexpected == [], (
            f"abstract adapter methods with no Neo4j implementation: {unexpected}"
        )

    def test_the_known_gap_has_not_grown(self):
        """And shrinks the list when one is closed, rather than going stale."""
        stale = sorted(self.KNOWN_UNIMPLEMENTED - set(self._unimplemented()))
        assert stale == [], (
            f"these are implemented now — remove them from KNOWN_UNIMPLEMENTED: {stale}"
        )


class TestConsultationWriterParity:
    """Consultation is protocol surface — G-8 and G-9 have governed it since v1."""

    CONSULTATION = _writer_body("create_consultation_node", "create_exchange_entry_node")
    ENTRY = _writer_body("create_exchange_entry_node", "create_consultation_participant_node")
    PARTICIPANT = _writer_body("create_consultation_participant_node", "create_amendment_link_node")

    @pytest.mark.parametrize("field", sorted(ConsultationNode.model_fields))
    def test_consultation_field_is_bound(self, field):
        assert field in _persisted_params(self.CONSULTATION)

    @pytest.mark.parametrize("field", sorted(ExchangeEntry.model_fields))
    def test_entry_field_is_bound(self, field):
        assert field in _persisted_params(self.ENTRY)

    @pytest.mark.parametrize("field", sorted(ConsultationParticipantNode.model_fields))
    def test_participant_field_is_bound(self, field):
        assert field in _persisted_params(self.PARTICIPANT)

    def test_consultation_lives_in_the_initiating_episode(self):
        """D2 — the consultation is a branch on the initiator's episode."""
        assert "INITIATED" in self.CONSULTATION

    def test_entries_hang_off_the_consultation(self):
        assert "CONTAINS_ENTRY" in self.ENTRY

    def test_participant_hangs_off_the_consulted_episode(self):
        """D3 — the consulted agent records participation, not the exchange."""
        assert "PARTICIPATED_IN" in self.PARTICIPANT

    def test_the_chain_field_is_written(self):
        """previous_hash is what G-8 governs; without it there is no chain."""
        assert "previous_hash" in _persisted_params(self.ENTRY)
