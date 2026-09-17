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
"""Unit tests for the segment node type (astp.nodes.segment).

Covers the minimal inline SegmentPayload, the create_segment_node convenience,
self-registration on import, hash determinism (metadata excluded), validation,
round-trip, and an episode→segments audit-trail scenario.
"""
import pytest

from astp.core.schema import sha3_256
from astp.nodes import create_node
from astp.nodes.episode import create_episode_node
from astp.nodes.segment import SegmentPayload, create_segment_node
from astp.protocol.node import CognitiveNode
from astp.protocol.registry import REGISTRY


def test_segment_type_registered_on_import():
    # Importing astp.nodes.segment (above) self-registered the type.
    assert REGISTRY.is_registered("segment")
    assert REGISTRY.get("segment").temporal_profile == "point"


def test_create_segment_node_complete():
    n = create_segment_node(
        "agent-1", 1, segment_type="conversation", content="hello", author="agent-1"
    )
    assert isinstance(n, CognitiveNode)
    assert n.node_type == "segment"
    assert n.content_hash and n.leaf_hash
    assert n.payload["segment_type"] == "conversation"
    assert n.payload["content"] == "hello"


def test_author_defaults_to_agent_id():
    n = create_segment_node("agent-7", 1, segment_type="annotation", content="note")
    assert n.payload["author"] == "agent-7"


def test_content_hash_covers_content_excludes_metadata():
    a = create_segment_node("a", 1, segment_type="conversation", content="X", author="a",
                            metadata={"k": "v1"})
    b = create_segment_node("a", 1, segment_type="conversation", content="X", author="a",
                            metadata={"k": "v2"})
    # metadata differs but is excluded from the hash → identical content_hash
    assert a.content_hash == b.content_hash
    # content differs → different content_hash
    c = create_segment_node("a", 1, segment_type="conversation", content="Y", author="a")
    assert c.content_hash != a.content_hash


def test_content_hash_matches_canonical():
    p = SegmentPayload(segment_type="conversation", author="a", content="hello")
    assert p.compute_content_hash() == sha3_256(p.to_content_hash_input())


def test_validate_requires_type_and_author():
    with pytest.raises(ValueError):
        create_node("segment", agent_id="a", sequence_index=1,
                    payload=SegmentPayload(segment_type="", author="a", content="x"))
    with pytest.raises(ValueError):
        create_node("segment", agent_id="a", sequence_index=1,
                    payload=SegmentPayload(segment_type="conversation", author="", content="x"))


def test_payload_round_trip():
    p = SegmentPayload(segment_type="artifact", author="agent-a", content="C", metadata={"m": 1})
    assert SegmentPayload.from_dict(p.to_dict()).to_dict() == p.to_dict()


def test_episode_segments_audit_trail_scenario():
    """Create an episode, append segments parented to it."""
    episode = create_episode_node("agent-1", 0, title="Demo", context_note="show audit trail")
    seg1 = create_segment_node("agent-1", 1, segment_type="conversation",
                               content="user asks a question", parent_node_id=episode.node_id)
    seg2 = create_segment_node("agent-1", 2, segment_type="conversation",
                               content="agent answers", parent_node_id=episode.node_id)
    # both segments belong to the episode
    assert seg1.parent_node_id == episode.node_id
    assert seg2.parent_node_id == episode.node_id
    # distinct cryptographic identities, monotonic timeline
    assert seg1.leaf_hash != seg2.leaf_hash
    assert seg1.sequence_index < seg2.sequence_index
