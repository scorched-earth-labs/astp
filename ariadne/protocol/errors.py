"""
Ariadne Protocol v2 — Exception Hierarchy

Base exceptions for all protocol-level errors. These are structural
errors indicating protocol non-conformance, not application errors.
"""


class AriadneProtocolError(Exception):
    """Base exception for all Ariadne v2 protocol violations."""
    pass


class GovernanceViolation(AriadneProtocolError):
    """A governance rule has been violated."""
    pass


class ReparentingViolation(GovernanceViolation):
    """Attempted to change a node's parent_node_id after creation.

    Reparenting is a governance violation, not a valid operation.
    A node's parentage is a fact about its origin. To correct
    incorrect parentage: create a new node with correct parentage,
    issue a deprecation record on the original.
    """
    pass


class VerificationError(AriadneProtocolError):
    """Hash verification or integrity check failed."""
    pass


class StaleRootError(AriadneProtocolError):
    """Compare-and-swap failed on spine_root — concurrent writer detected."""
    pass


class MonotonicityViolation(GovernanceViolation):
    """A monotonically increasing value decreased (logical clock, sequence index)."""
    pass
