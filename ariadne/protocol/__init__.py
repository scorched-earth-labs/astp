"""
Ariadne Protocol v2 — Node-Generic Cognitive Persistence

The protocol layer operates on CognitiveNode exclusively. It never
imports from ariadne.nodes.* — that boundary is the namespace firewall.

Core primitives:
    CognitiveNode, CognitiveEdge, NodePayload — universal node types
    compute_leaf_hash — position-binding leaf hash (the cryptographic core)
    MerkleTree, InclusionProof — integrity verification tree
    DeltaVerifier, VerificationResult — five-test tamper detection gate
    AuditRecord, AuditChain — tamper-evident audit trail
    ContentDelta, StructuralDelta — atomic state transition records
    VersionVector — multi-agent coordination
    NodeTypeRegistry — open enum for node types
"""

from ariadne.protocol.node import CognitiveNode, CognitiveEdge, NodePayload
from ariadne.protocol.registry import NodeTypeRegistry, NodeTypeDefinition, REGISTRY
from ariadne.protocol.leaf_hash import compute_leaf_hash, compute_leaf_hash_from_node
from ariadne.protocol.merkle import MerkleTree, InclusionProof
from ariadne.protocol.delta import ContentDelta, StructuralDelta, DeltaRecord
from ariadne.protocol.audit import AuditRecord, AuditChain, compute_audit_hash
from ariadne.protocol.retrieval_audit import RetrievalAuditRecord, compute_retrieval_audit_hash
from ariadne.protocol.verification import DeltaVerifier, VerificationResult
from ariadne.protocol.version_vector import VersionVector
from ariadne.protocol.governance import (
    enforce_write_guard,
    enforce_reparenting_prohibition,
    enforce_sequence_monotonicity,
    enforce_logical_clock_monotonicity,
    enforce_node_type_registered,
)
from ariadne.protocol.errors import (
    AriadneProtocolError,
    GovernanceViolation,
    ReparentingViolation,
    VerificationError,
    StaleRootError,
    MonotonicityViolation,
)

__all__ = [
    # Primitives
    "CognitiveNode",
    "CognitiveEdge",
    "NodePayload",
    # Registry
    "NodeTypeRegistry",
    "NodeTypeDefinition",
    "REGISTRY",
    # Hashing
    "compute_leaf_hash",
    "compute_leaf_hash_from_node",
    # Tree
    "MerkleTree",
    "InclusionProof",
    # Deltas
    "ContentDelta",
    "StructuralDelta",
    "DeltaRecord",
    # Audit
    "AuditRecord",
    "AuditChain",
    "compute_audit_hash",
    # Verification
    "DeltaVerifier",
    "VerificationResult",
    # Version
    "VersionVector",
    # Governance
    "enforce_write_guard",
    "enforce_reparenting_prohibition",
    "enforce_sequence_monotonicity",
    "enforce_logical_clock_monotonicity",
    "enforce_node_type_registered",
    # Errors
    "AriadneProtocolError",
    "GovernanceViolation",
    "ReparentingViolation",
    "VerificationError",
    "StaleRootError",
    "MonotonicityViolation",
]
