"""
Ariadne Segment Payload — segment-specific extension of NodePayload.

A segment is a point-in-time record of one action within an episode (a chat
turn, a tool call, an annotation). This reference-implementation payload is
deliberately minimal: segment_type, author, and inline content. The content
is hashed directly, so the content_hash is the segment's tamper-evidence.

`metadata` is an open extension bag and is NOT part of the canonical hash
preimage (only segment_type + author + content are), matching EpisodePayload.
"""

import json
from typing import Any, Dict, Optional

from ariadne.protocol.node import NodePayload


class SegmentPayload(NodePayload):
    """Minimal segment payload: a typed, authored, content-bearing record."""

    def __init__(
        self,
        segment_type: str = "",
        author: str = "",
        content: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.segment_type = segment_type
        self.author = author
        self.content = content
        self.metadata = metadata or {}

    def validate(self) -> None:
        """Validate segment-specific invariants."""
        if not self.segment_type:
            raise ValueError("segment_type is required for a segment payload")
        if not self.author:
            raise ValueError("author is required for a segment payload")

    def to_content_hash_input(self) -> bytes:
        """Canonical bytes for content_hash — sorted-key JSON over the
        hash-bearing fields. `metadata` is intentionally excluded so it can
        evolve without changing the segment's cryptographic identity."""
        canonical = {
            "segment_type": self.segment_type,
            "author": self.author,
            "content": self.content,
        }
        return json.dumps(canonical, sort_keys=True).encode("utf-8")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage."""
        return {
            "segment_type": self.segment_type,
            "author": self.author,
            "content": self.content,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SegmentPayload":
        """Deserialize from storage."""
        return cls(
            segment_type=d.get("segment_type", ""),
            author=d.get("author", ""),
            content=d.get("content", ""),
            metadata=d.get("metadata", {}),
        )
