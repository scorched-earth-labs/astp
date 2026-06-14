"""
Ariadne Segment Node Type — a point-in-time record within an episode.

Segments form the audit trail: each recorded action (a chat turn, tool call,
or annotation) is a segment linked to its episode via ``parent_node_id``.

Importing this package self-registers "segment" with the NodeTypeRegistry —
the idiomatic pattern for a node type living in its own package without
touching the protocol layer.
"""

from ariadne.nodes.factory import register_node_type
from ariadne.nodes.segment.payload import SegmentPayload
from ariadne.nodes.segment.factory import create_segment_node

# Self-register on import (idempotent — re-registration overwrites with the
# same definition). temporal_profile="point": a segment is an instantaneous
# record, unlike an episode which is "bounded".
register_node_type("segment", "Segment", temporal_profile="point")

__all__ = ["SegmentPayload", "create_segment_node"]
