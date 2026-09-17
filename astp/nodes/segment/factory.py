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
"""
Ariadne Segment Factory — convenience for creating segment CognitiveNodes.

Thin wrapper over the generic ``create_node`` factory: builds a SegmentPayload
and delegates, so segment creation is now a one-call operation like episode
creation (the friction this addresses). Link a segment to its episode by
passing the episode's node_id as ``parent_node_id``.
"""

from typing import Any, Dict, Optional
from uuid import UUID

from astp.nodes.factory import create_node
from astp.nodes.segment.payload import SegmentPayload
from astp.protocol.node import CognitiveNode


def create_segment_node(
    agent_id: str,
    sequence_index: int,
    *,
    segment_type: str,
    content: str,
    author: str = "",
    parent_node_id: Optional[UUID] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> CognitiveNode:
    """Create a CognitiveNode representing a segment.

    Args:
        agent_id: The agent creating this segment.
        sequence_index: Position in the agent's cognitive timeline.
        segment_type: Open type tag (e.g. "conversation", "artifact", "annotation").
        content: The segment's inline content (hashed into content_hash).
        author: Who authored the segment; defaults to ``agent_id`` if empty.
        parent_node_id: The episode (or parent node) this segment belongs to.
        metadata: Optional extension bag (excluded from the content hash).

    Returns:
        CognitiveNode with node_type="segment", computed content_hash and leaf_hash.
    """
    payload = SegmentPayload(
        segment_type=segment_type,
        author=author or agent_id,
        content=content,
        metadata=metadata,
    )
    return create_node(
        "segment",
        agent_id=agent_id,
        sequence_index=sequence_index,
        payload=payload,
        parent_node_id=parent_node_id,
    )
