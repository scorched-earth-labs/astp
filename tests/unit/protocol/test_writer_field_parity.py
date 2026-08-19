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

from ariadne.core.schema import SegmentNode, SignalNode

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
