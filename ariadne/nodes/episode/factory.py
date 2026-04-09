"""
Ariadne Episode Factory — Convenience for creating episode CognitiveNodes.

Builds a CognitiveNode with node_type="episode" and an EpisodePayload,
computing the leaf hash automatically.
"""

from typing import List, Optional
from uuid import UUID

from ariadne.core.schema import sha3_256
from ariadne.protocol.node import CognitiveNode
from ariadne.protocol.leaf_hash import compute_leaf_hash_from_node
from ariadne.nodes.episode.payload import EpisodePayload


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

    Builds the EpisodePayload, computes content_hash and leaf_hash,
    and returns a fully-formed CognitiveNode ready for persistence.

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
    payload.validate()

    content_hash = payload.compute_content_hash()

    node = CognitiveNode(
        node_type="episode",
        schema_version="2.0.0",
        sequence_index=sequence_index,
        tree_leaf_index=sequence_index,  # Initially equal; diverges on rebalance
        content_hash=content_hash,
        authored_by=agent_id,
        parent_node_id=parent_node_id,
        payload=payload.to_dict(),
    )

    # Compute and set the position-binding leaf hash
    node.leaf_hash = compute_leaf_hash_from_node(node)

    return node
