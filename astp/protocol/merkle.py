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
Ariadne Protocol v2 — Merkle Tree

Position-binding Merkle tree with domain-separated hashing and
inclusion proof generation. Operates on pre-computed leaf hashes
from leaf_hash.py — the tree itself is node-type-agnostic.

Domain separation:
  - Leaf level: SHA3-256(b"LEAF:" + leaf_hash)
  - Internal nodes: SHA3-256(b"NODE:" + left + right)
"""

from typing import List, Optional

from pydantic import BaseModel

from astp.core.schema import sha3_256


def _domain_leaf(leaf_hash: str) -> str:
    """Domain-separated leaf hash. Prevents second-preimage attacks."""
    return sha3_256(b"LEAF:" + leaf_hash.encode())


def _domain_node(left: str, right: str) -> str:
    """Domain-separated internal node hash."""
    return sha3_256(b"NODE:" + left.encode() + right.encode())


class InclusionProof(BaseModel):
    """Position-binding Merkle inclusion proof (P2).

    Proves that a node with a given leaf_hash exists at a specific
    position in the tree, verifiable against the spine_root.
    """
    sequence_index: int
    leaf_hash: str
    merkle_path: List[str]  # Sibling hashes from leaf to root
    path_directions: List[str]  # "left" or "right" — which side the sibling is on
    spine_root: str


class MerkleTree:
    """Binary Merkle tree with domain separation and inclusion proofs.

    Build from pre-computed leaf hashes (from leaf_hash.py).
    The tree is node-type-agnostic — it operates on hash strings only.
    """

    def __init__(self):
        self._leaf_hashes: List[str] = []  # Pre-domain-separation
        self._domain_leaves: List[str] = []  # Post-domain-separation
        self._levels: List[List[str]] = []
        self._root: Optional[str] = None

    @property
    def root_hash(self) -> Optional[str]:
        """The Merkle root hash."""
        return self._root

    @property
    def leaf_count(self) -> int:
        return len(self._leaf_hashes)

    @property
    def depth(self) -> int:
        return len(self._levels)

    def build(self, leaf_hashes: List[str]) -> str:
        """Build the tree from a list of pre-computed leaf hashes.

        Args:
            leaf_hashes: Position-binding hashes from compute_leaf_hash()

        Returns:
            The root hash
        """
        if not leaf_hashes:
            raise ValueError("Cannot build Merkle tree from empty leaf set")

        self._leaf_hashes = list(leaf_hashes)
        self._domain_leaves = [_domain_leaf(h) for h in leaf_hashes]

        # Build bottom-up
        current_level = list(self._domain_leaves)
        self._levels = [current_level]

        while len(current_level) > 1:
            next_level = []
            for i in range(0, len(current_level), 2):
                if i + 1 < len(current_level):
                    combined = _domain_node(current_level[i], current_level[i + 1])
                else:
                    combined = current_level[i]  # Odd node passes through
                next_level.append(combined)
            self._levels.append(next_level)
            current_level = next_level

        self._root = current_level[0]
        return self._root

    def append_leaf(self, leaf_hash: str) -> str:
        """Append a leaf and incrementally update the tree. O(log n).

        Returns the new root hash.
        """
        self._leaf_hashes.append(leaf_hash)
        domain_leaf = _domain_leaf(leaf_hash)
        self._domain_leaves.append(domain_leaf)

        if not self._levels:
            self._levels = [[domain_leaf]]
            self._root = domain_leaf
            return self._root

        # Add to leaf level
        self._levels[0].append(domain_leaf)

        # Walk up, recalculating rightmost path
        for level_idx in range(len(self._levels) - 1):
            current = self._levels[level_idx]
            next_level = self._levels[level_idx + 1]

            pos = len(current) - 1
            parent_pos = pos // 2

            if pos % 2 == 0:
                parent_hash = current[pos]
            else:
                parent_hash = _domain_node(current[pos - 1], current[pos])

            if parent_pos < len(next_level):
                next_level[parent_pos] = parent_hash
            else:
                next_level.append(parent_hash)

        # Check if we need a new root level
        if len(self._levels[-1]) > 1:
            top = self._levels[-1]
            new_top = []
            for i in range(0, len(top), 2):
                if i + 1 < len(top):
                    new_top.append(_domain_node(top[i], top[i + 1]))
                else:
                    new_top.append(top[i])
            self._levels.append(new_top)

        self._root = self._levels[-1][0]
        return self._root

    def generate_inclusion_proof(self, leaf_index: int) -> InclusionProof:
        """Generate a P2 position-binding inclusion proof for a leaf.

        The proof contains sibling hashes along the path from leaf to root.
        A verifier recomputes the leaf's domain hash and walks up using
        the siblings to reconstruct the root.

        Args:
            leaf_index: Index into the leaf_hashes list

        Returns:
            InclusionProof verifiable against self.root_hash
        """
        if leaf_index >= len(self._leaf_hashes):
            raise IndexError(f"Leaf index {leaf_index} out of range (have {self.leaf_count})")

        merkle_path = []
        path_directions = []
        pos = leaf_index

        for level_idx in range(len(self._levels) - 1):
            level = self._levels[level_idx]
            if pos % 2 == 0:
                # Current is left child — sibling is right
                if pos + 1 < len(level):
                    merkle_path.append(level[pos + 1])
                    path_directions.append("right")
                # else: odd node, no sibling
            else:
                # Current is right child — sibling is left
                merkle_path.append(level[pos - 1])
                path_directions.append("left")
            pos = pos // 2

        return InclusionProof(
            sequence_index=leaf_index,
            leaf_hash=self._leaf_hashes[leaf_index],
            merkle_path=merkle_path,
            path_directions=path_directions,
            spine_root=self._root or "",
        )

    @staticmethod
    def verify_inclusion_proof(proof: InclusionProof) -> bool:
        """Verify a P2 position-binding inclusion proof.

        Recomputes the root from the leaf hash and merkle path,
        then compares against the claimed spine_root.

        Returns:
            True if the proof is valid
        """
        current = _domain_leaf(proof.leaf_hash)

        for sibling, direction in zip(proof.merkle_path, proof.path_directions):
            if direction == "right":
                current = _domain_node(current, sibling)
            else:
                current = _domain_node(sibling, current)

        return current == proof.spine_root
