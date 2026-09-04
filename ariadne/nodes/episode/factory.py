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
Ariadne Episode Factory — Convenience for creating episode CognitiveNodes.

Builds a CognitiveNode with node_type="episode" and an EpisodePayload,
computing the leaf hash automatically.
"""

from typing import List, Optional
from uuid import UUID

from ariadne.nodes.factory import create_node
from ariadne.nodes.episode.payload import EpisodePayload
from ariadne.protocol.node import CognitiveNode


def create_episode_node(
    agent_id: str,
    sequence_index: int,
    title: str = "",
    context_note: str = "",
    episode_type: str = "",
    episode_mode: str = "directed",
    workspace_id: str = "",
    participants: Optional[List[str]] = None,
    parent_node_id: Optional[UUID] = None,
) -> CognitiveNode:
    """Create a CognitiveNode representing an episode.

    Thin convenience over the generic ``create_node`` factory: builds the
    EpisodePayload and delegates. Output is identical to hand-assembly —
    same content_hash and leaf_hash — but now goes through the one governed
    creation path shared by every node type.

    Args:
        agent_id: The agent creating this episode
        sequence_index: Position in the agent's cognitive timeline
        title: Human-readable episode title
        context_note: Cognitive anchor — user's statement of intent
        episode_type: Taxonomy (exploration, technical_review, planning, etc.)
        episode_mode: "directed" or "collaborative"
        workspace_id: Links to external workspace
        participants: Agent IDs involved
        parent_node_id: Parent in the cognitive graph (e.g., predecessor episode)

    Returns:
        CognitiveNode with node_type="episode", computed content_hash and leaf_hash
    """
    payload = EpisodePayload(
        title=title,
        context_note=context_note,
        episode_type=episode_type,
        episode_mode=episode_mode,
        workspace_id=workspace_id,
        participants=participants or [agent_id],
    )
    return create_node(
        "episode",
        agent_id=agent_id,
        sequence_index=sequence_index,
        payload=payload,
        parent_node_id=parent_node_id,
    )
