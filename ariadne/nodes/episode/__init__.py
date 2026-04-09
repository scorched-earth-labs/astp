"""
Ariadne Episode Node Type — the Phase 1 instantiation.

Episodes are bounded units of agent work with a formal lifecycle.
This is the first parameterization of CognitiveNode; the protocol
layer operates identically regardless of node type.
"""

from ariadne.nodes.episode.payload import EpisodePayload
from ariadne.nodes.episode.lifecycle import EpisodeState, VALID_TRANSITIONS
from ariadne.nodes.episode.factory import create_episode_node

__all__ = [
    "EpisodePayload",
    "EpisodeState",
    "VALID_TRANSITIONS",
    "create_episode_node",
]
