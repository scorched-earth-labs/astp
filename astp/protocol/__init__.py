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
ASTP — Node-Generic Cognitive Persistence

The protocol layer operates on CognitiveNode exclusively. It never
imports from astp.nodes.* — that boundary is the namespace firewall.

Core primitives:
    CognitiveNode, CognitiveEdge, NodePayload — universal node types
    compute_leaf_hash — position-binding leaf hash (the cryptographic core)
    MerkleTree, InclusionProof — integrity verification tree
    DeltaVerifier, VerificationResult — five-test tamper detection gate
    AuditRecord, AuditChain — tamper-evident audit trail
    ContentDelta, StructuralDelta — atomic state transition records
    VersionVector — multi-agent coordination
    NodeTypeRegistry — open enum for node types

Trust infrastructure (SPEC §16):
    derive_workspace_key, derive_node_key, derive_seal_key — key hierarchy
    AnchorCommitment, TransparencyLogAdapter — transparency log anchoring
    WitnessRecord, enforce_witness_threshold — witness signatures
    ProofChain, verify_proof_chain — cross-node chain proofs
"""

from astp.protocol.node import CognitiveNode, CognitiveEdge, NodePayload
from astp.protocol.registry import NodeTypeRegistry, NodeTypeDefinition, REGISTRY
from astp.protocol.leaf_hash import compute_leaf_hash, compute_leaf_hash_from_node
from astp.protocol.merkle import MerkleTree, InclusionProof
from astp.protocol.delta import ContentDelta, StructuralDelta, DeltaRecord
from astp.protocol.audit import AuditRecord, AuditChain, compute_audit_hash
from astp.protocol.retrieval_audit import RetrievalAuditRecord, compute_retrieval_audit_hash
from astp.protocol.rebalance import RebalanceEventNode, create_rebalance_event
from astp.protocol.keys import (
    derive_workspace_key, derive_node_key, derive_seal_key,
    NodeKeyRecord, enforce_key_version_monotonicity,
    compute_public_key_fingerprint,
)
from astp.protocol.anchor import (
    AnchorCommitment, AnchorReceipt, TransparencyLogAdapter,
    build_anchor_commitment,
)
from astp.protocol.witness import (
    WitnessRole, WitnessRecord, compute_witness_commitment,
    verify_witness_commitment, enforce_witness_threshold,
)
from astp.protocol.chain_proof import (
    ProofLink, ProofChain, ChainVerificationResult,
    compute_chain_root, build_proof_chain, verify_proof_chain,
)
from astp.protocol.verification import DeltaVerifier, VerificationResult
from astp.protocol.version_vector import VersionVector
from astp.protocol.governance import (
    enforce_write_guard,
    enforce_reparenting_prohibition,
    enforce_sequence_monotonicity,
    enforce_logical_clock_monotonicity,
    enforce_node_type_registered,
)
from astp.protocol.errors import (
    ASTPProtocolError,
    AriadneProtocolError,  # retained alias
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
    "RetrievalAuditRecord",
    "compute_retrieval_audit_hash",
    # Rebalance
    "RebalanceEventNode",
    "create_rebalance_event",
    # Keys
    "derive_workspace_key",
    "derive_node_key",
    "derive_seal_key",
    "NodeKeyRecord",
    "enforce_key_version_monotonicity",
    "compute_public_key_fingerprint",
    # Anchoring
    "AnchorCommitment",
    "AnchorReceipt",
    "TransparencyLogAdapter",
    "build_anchor_commitment",
    # Witness
    "WitnessRole",
    "WitnessRecord",
    "compute_witness_commitment",
    "verify_witness_commitment",
    "enforce_witness_threshold",
    # Chain proofs
    "ProofLink",
    "ProofChain",
    "ChainVerificationResult",
    "compute_chain_root",
    "build_proof_chain",
    "verify_proof_chain",
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
    "ASTPProtocolError",
    "AriadneProtocolError",  # retained alias
    "GovernanceViolation",
    "ReparentingViolation",
    "VerificationError",
    "StaleRootError",
    "MonotonicityViolation",
]
