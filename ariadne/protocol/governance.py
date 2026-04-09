"""
Ariadne Protocol v2 — Generic Governance Rules

Node-type-agnostic governance enforcement. These rules apply to all
CognitiveNodes regardless of type. Episode-specific governance belongs
in ariadne.nodes.episode, not here.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from ariadne.protocol.errors import (
    GovernanceViolation,
    MonotonicityViolation,
    ReparentingViolation,
)


def enforce_write_guard(sealed_at: Optional[datetime]) -> None:
    """No writes to sealed nodes.

    Generic equivalent of v1 G-1. Any node with a non-null sealed_at
    is frozen — no further modifications are permitted.
    """
    if sealed_at is not None:
        raise GovernanceViolation(
            f"Write rejected: node is sealed (sealed_at={sealed_at.isoformat()}). "
            f"Sealed nodes are immutable. To amend, create a new node "
            f"and link it via a deprecation record."
        )


def enforce_reparenting_prohibition(
    current_parent: Optional[UUID],
    proposed_parent: Optional[UUID],
) -> None:
    """Reparenting is a governance violation, not a valid operation.

    A node's parentage is a fact about its origin. parent_node_id
    is in the leaf hash preimage — changing it would mutate history.
    """
    if current_parent is not None and proposed_parent != current_parent:
        raise ReparentingViolation(
            f"Reparenting violation: cannot change parent_node_id from "
            f"{current_parent} to {proposed_parent}. Parent is immutable "
            f"after creation. To correct: create a new node with the "
            f"correct parent and deprecate the original."
        )


def enforce_sequence_monotonicity(current_max: int, proposed: int) -> None:
    """New sequence_index must be strictly greater than the current maximum.

    sequence_index is the temporal anchor — it encodes causal position
    in the cognitive timeline. Non-monotonic sequence indices indicate
    either a bug or an insertion attack.
    """
    if proposed <= current_max:
        raise MonotonicityViolation(
            f"Sequence monotonicity violation: proposed sequence_index "
            f"{proposed} is not greater than current max {current_max}."
        )


def enforce_logical_clock_monotonicity(prev_clock: int, new_clock: int) -> None:
    """Logical clock must be strictly monotonically increasing.

    A decreasing logical clock indicates either clock tampering
    or a backdated event — both are integrity violations.
    """
    if new_clock <= prev_clock:
        raise MonotonicityViolation(
            f"Logical clock monotonicity violation: new clock {new_clock} "
            f"is not greater than previous {prev_clock}."
        )


def enforce_node_type_registered(node_type: str) -> None:
    """Node type must be registered in the NodeTypeRegistry."""
    from ariadne.protocol.registry import REGISTRY
    if not REGISTRY.is_registered(node_type):
        raise GovernanceViolation(
            f"Unknown node type '{node_type}'. "
            f"Registered types: {REGISTRY.list_types()}"
        )
