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
ASTP — Cross-Node Chain Proofs

Verifiable sequence of CognitiveNode states establishing causal
ordering across nodes, node types, and AI architectures.

A ProofChain is self-contained: a verifier needs only the chain
data and the ASTP Merkle algorithm to verify it. No access to
the originating implementation's storage or key material is required.

Per IMPLEMENTATION-PHASE3.md Section 6.
"""

from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from astp.protocol.hashing import sha3_256
from astp.protocol.anchor import AnchorReceipt
from astp.protocol.merkle import MerkleTree, InclusionProof
from astp.protocol.witness import WitnessRecord


class ProofLink(BaseModel):
    """One link in a ProofChain — represents a CognitiveNode state."""
    node_id: str
    node_type: str
    spine_root: str
    sequence_index: int
    logical_clock: int = 0
    inclusion_proof: Optional[InclusionProof] = None
    parent_node_id: Optional[str] = None  # Causal parent
    anchor_receipt: Optional[AnchorReceipt] = None
    witness_records: List[WitnessRecord] = Field(default_factory=list)


class ProofChain(BaseModel):
    """A verifiable causal chain across CognitiveNodes."""
    chain_id: str = Field(default_factory=lambda: str(uuid4()))
    links: List[ProofLink]
    chain_root: str  # SHA3-256 of concatenated link spine_roots (G-13)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    protocol_version: str = "2.3.0"


class ChainVerificationResult(BaseModel):
    """Result of ProofChain verification."""
    valid: bool
    reason: Optional[str] = None
    links_verified: int = 0
    total_links: int = 0


# ── Chain Root Computation ───────────────────────────────────────────────────

def compute_chain_root(links: List[ProofLink]) -> str:
    """Compute chain_root as SHA3-256 of concatenated spine_roots.

    Simple concatenation hash (not a Merkle tree). Any modification
    to any link's spine_root changes the chain root (G-13).

    Args:
        links: Ordered proof links (root cause → effect)

    Returns:
        SHA3-256 hex string of the concatenated spine roots
    """
    concatenated = b""
    for link in links:
        concatenated += bytes.fromhex(link.spine_root)
    return sha3_256(concatenated)


# ── Chain Construction ───────────────────────────────────────────────────────

def build_proof_chain(links: List[ProofLink]) -> ProofChain:
    """Build a ProofChain from an ordered list of ProofLinks.

    Args:
        links: Ordered from root cause to effect

    Returns:
        ProofChain with computed chain_root
    """
    return ProofChain(
        links=links,
        chain_root=compute_chain_root(links),
    )


# ── Chain Verification ───────────────────────────────────────────────────────

def verify_proof_chain(chain: ProofChain) -> ChainVerificationResult:
    """Verify a ProofChain. Protocol-mandatory algorithm.

    Four conditions must all hold:
    1. Each link's inclusion_proof verifies against its spine_root
    2. Causal ordering: consecutive links have parent-child relationship
    3. Temporal consistency: anchor_receipt timestamps are non-decreasing
    4. Chain root integrity: chain_root matches recomputed value (G-13)

    This algorithm is self-contained — it requires no external state.
    """
    total = len(chain.links)

    if total == 0:
        return ChainVerificationResult(
            valid=False, reason="empty chain", total_links=0
        )

    # Condition 1: Verify each link's inclusion proof
    for i, link in enumerate(chain.links):
        if link.inclusion_proof is not None:
            # §16.5.3 (1): the proof is verified against the link's spine_root.
            # A proof that is valid for some other root proves nothing here.
            if link.inclusion_proof.spine_root != link.spine_root:
                return ChainVerificationResult(
                    valid=False,
                    reason=(
                        f"link {i} inclusion proof is for a different spine_root "
                        f"than the link declares"
                    ),
                    links_verified=i,
                    total_links=total,
                )
            if not MerkleTree.verify_inclusion_proof(link.inclusion_proof):
                return ChainVerificationResult(
                    valid=False,
                    reason=f"link {i} inclusion proof verification failed",
                    links_verified=i,
                    total_links=total,
                )

    # Condition 2: Verify causal ordering
    for i in range(1, total):
        prev = chain.links[i - 1]
        curr = chain.links[i]
        if curr.parent_node_id != prev.node_id:
            # Check if prev.node_id is an ancestor via parent chain
            if not _is_ancestor(prev.node_id, curr, chain.links[:i]):
                return ChainVerificationResult(
                    valid=False,
                    reason=(
                        f"causal order violation — link {i} has no causal "
                        f"relationship to link {i-1}"
                    ),
                    links_verified=i,
                    total_links=total,
                )

    # Condition 3: Temporal consistency (cross-architecture)
    receipted = [l for l in chain.links if l.anchor_receipt is not None]
    for i in range(1, len(receipted)):
        if receipted[i].anchor_receipt.log_timestamp < receipted[i-1].anchor_receipt.log_timestamp:
            return ChainVerificationResult(
                valid=False,
                reason="temporal consistency violation — anchor timestamps out of order",
                links_verified=total,
                total_links=total,
            )

    # Condition 4: Chain root integrity (G-13)
    expected_root = compute_chain_root(chain.links)
    if chain.chain_root != expected_root:
        return ChainVerificationResult(
            valid=False,
            reason="chain_root integrity failure (G-13)",
            links_verified=total,
            total_links=total,
        )

    return ChainVerificationResult(
        valid=True,
        links_verified=total,
        total_links=total,
    )


def _is_ancestor(
    target_node_id: str,
    current_link: ProofLink,
    prior_links: List[ProofLink],
) -> bool:
    """Check if target_node_id is reachable via the parent chain."""
    # Walk up the parent chain through prior links
    visited = set()
    parent_id = current_link.parent_node_id

    while parent_id and parent_id not in visited:
        if parent_id == target_node_id:
            return True
        visited.add(parent_id)
        # Find the link with this node_id in prior links
        parent_link = next(
            (l for l in prior_links if l.node_id == parent_id), None
        )
        if parent_link is None:
            break
        parent_id = parent_link.parent_node_id

    return False
