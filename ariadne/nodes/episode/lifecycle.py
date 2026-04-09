"""
Ariadne Episode Lifecycle — State Machine

Episode-specific lifecycle states and valid transitions.
This is isolated in the episode layer — the protocol layer
does not know about episode states.
"""

from enum import Enum
from typing import Dict, Set

from ariadne.protocol.errors import GovernanceViolation


class EpisodeState(str, Enum):
    ACTIVE = "ACTIVE"
    REBALANCING = "REBALANCING"
    SEALING = "SEALING"
    SEALED = "SEALED"
    SEALING_FAILED = "SEALING_FAILED"
    REBALANCE_FAILED = "REBALANCE_FAILED"
    ARCHIVED = "ARCHIVED"
    EXPIRED = "EXPIRED"


VALID_TRANSITIONS: Dict[EpisodeState, Set[EpisodeState]] = {
    EpisodeState.ACTIVE: {
        EpisodeState.REBALANCING,
        EpisodeState.SEALING,
        EpisodeState.ARCHIVED,
    },
    EpisodeState.REBALANCING: {
        EpisodeState.ACTIVE,
        EpisodeState.REBALANCE_FAILED,
    },
    EpisodeState.REBALANCE_FAILED: {
        EpisodeState.ACTIVE,
        EpisodeState.ARCHIVED,
    },
    EpisodeState.SEALING: {
        EpisodeState.SEALED,
        EpisodeState.SEALING_FAILED,
    },
    EpisodeState.SEALING_FAILED: {
        EpisodeState.ACTIVE,
        EpisodeState.ARCHIVED,
    },
    EpisodeState.SEALED: {
        EpisodeState.ARCHIVED,
    },
    EpisodeState.ARCHIVED: {
        EpisodeState.EXPIRED,
    },
    EpisodeState.EXPIRED: set(),
}


def enforce_transition(current: EpisodeState, target: EpisodeState) -> None:
    """Validate a lifecycle state transition.

    Raises GovernanceViolation if the transition is not permitted.
    """
    valid = VALID_TRANSITIONS.get(current, set())
    if target not in valid:
        raise GovernanceViolation(
            f"Invalid episode transition: {current.value} → {target.value}. "
            f"Valid transitions from {current.value}: "
            f"{', '.join(s.value for s in valid) if valid else 'none (terminal state)'}."
        )
