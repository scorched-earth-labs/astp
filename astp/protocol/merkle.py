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
ASTP — Merkle Tree

Position-binding Merkle tree with domain-separated hashing and
inclusion proof generation. Operates on pre-computed leaf hashes
from leaf_hash.py — the tree itself is node-type-agnostic.

Domain separation:
  - Leaf level: SHA3-256(b"LEAF:" + leaf_hash)
  - Internal nodes: SHA3-256(b"NODE:" + left + right)
"""

from typing import List, Optional

from pydantic import BaseModel

from astp.protocol.hashing import sha3_256


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


# ── spine_algorithm_version 2 (SPEC 5.0.0) ──────────

TREE_LEAF_V2_PREFIX = b"TREE_LEAF:v2:"
TREE_NODE_V2_PREFIX = b"TREE_NODE:v2:"


def compute_merkle_root_v2(leaf_inputs: List[str]) -> str:
    """Merkle root over 32-byte inputs, hashed as **raw bytes**.

    The tree is the one SPEC §5.4 has always described — pair from the left, carry
    an unpaired node up unchanged, refuse an empty list — and differs from
    versions 0 and 1 only in encoding: a hash value enters as its 32 raw bytes,
    not as 64 ASCII hex characters, under prefixes of its own.
    """
    import hashlib

    if not leaf_inputs:
        raise ValueError("the root of an empty leaf list is undefined")
    level = [hashlib.sha3_256(TREE_LEAF_V2_PREFIX + bytes.fromhex(x)).digest() for x in leaf_inputs]
    while len(level) > 1:
        level = [
            hashlib.sha3_256(TREE_NODE_V2_PREFIX + level[i] + level[i + 1]).digest() if i + 1 < len(level) else level[i]
            for i in range(0, len(level), 2)
        ]
    return level[0].hex()


def _tree_v2_levels(leaf_inputs: List[str]) -> List[List[bytes]]:
    """Every level of the version 2 tree, leaf level first, as raw bytes."""
    import hashlib

    if not leaf_inputs:
        raise ValueError("the root of an empty leaf list is undefined")
    level = [hashlib.sha3_256(TREE_LEAF_V2_PREFIX + bytes.fromhex(x)).digest() for x in leaf_inputs]
    levels = [level]
    while len(level) > 1:
        level = [
            hashlib.sha3_256(TREE_NODE_V2_PREFIX + level[i] + level[i + 1]).digest() if i + 1 < len(level) else level[i]
            for i in range(0, len(level), 2)
        ]
        levels.append(level)
    return levels


def expected_sibling_count_v2(leaf_index: int, leaf_count: int) -> int:
    """How many siblings a proof for ``leaf_index`` in a tree of ``leaf_count``
    leaves must carry. Derived from the shape of the tree alone: at each level a
    node has a sibling unless it is the unpaired last node, which is carried up
    without hashing."""
    if not 0 <= leaf_index < leaf_count:
        raise ValueError("leaf_index out of range")
    n, pos, siblings = leaf_count, leaf_index, 0
    while n > 1:
        if not (pos % 2 == 0 and pos == n - 1):      # unpaired last node: no sibling at this level
            siblings += 1
        pos, n = pos // 2, (n + 1) // 2
    return siblings


class InclusionProofV2(BaseModel):
    """Position-binding inclusion proof over the version 2 tree (SPEC 5.0.0 §9.2).

    The path shape is not stated by the prover: a verifier derives, from
    ``leaf_index`` and ``leaf_count``, at which levels a sibling exists and on
    which side it sits. A proof therefore commits to the leaf and to its
    position: no sibling list verifies at any position other than the one the
    tree gave it. It does not commit to the tree's size — a ``leaf_count`` that
    yields the same path shape verifies too — so the size of a sealed spine is
    a claim of the seal record, never of a proof. ``leaf_hash`` is a
    ``hash_version`` 2 leaf hash, which itself binds the node's
    ``sequence_index``; ``leaf_index`` is the leaf's position in the spine's leaf
    list (ephemeral Segments are not leaves, so the two numbers differ once any
    have been excluded).
    """
    leaf_index: int
    leaf_count: int
    leaf_hash: str
    siblings: List[str]      # raw-bytes tree siblings, leaf level first, hex here; only where one exists
    spine_root: str


def generate_inclusion_proof_v2(leaf_inputs: List[str], leaf_index: int) -> InclusionProofV2:
    levels = _tree_v2_levels(leaf_inputs)
    if not 0 <= leaf_index < len(leaf_inputs):
        raise IndexError(f"leaf index {leaf_index} out of range (have {len(leaf_inputs)})")
    siblings, pos = [], leaf_index
    for level in levels[:-1]:
        if pos % 2 == 0:
            if pos + 1 < len(level):
                siblings.append(level[pos + 1].hex())
        else:
            siblings.append(level[pos - 1].hex())
        pos //= 2
    return InclusionProofV2(leaf_index=leaf_index, leaf_count=len(leaf_inputs), leaf_hash=leaf_inputs[leaf_index],
                            siblings=siblings, spine_root=levels[-1][0].hex())


def verify_inclusion_proof_v2(proof: InclusionProofV2) -> bool:
    """Recompute the root from the leaf and the siblings, placing each sibling on
    the side the leaf's position dictates, and compare with ``spine_root``. A
    proof with the wrong number of siblings for its stated position is invalid
    before any hashing is done."""
    import hashlib

    try:
        expected = expected_sibling_count_v2(proof.leaf_index, proof.leaf_count)
    except ValueError:
        return False
    if len(proof.siblings) != expected:
        return False
    current = hashlib.sha3_256(TREE_LEAF_V2_PREFIX + bytes.fromhex(proof.leaf_hash)).digest()
    n, pos, k = proof.leaf_count, proof.leaf_index, 0
    while n > 1:
        if not (pos % 2 == 0 and pos == n - 1):
            sibling = bytes.fromhex(proof.siblings[k]); k += 1
            current = hashlib.sha3_256(TREE_NODE_V2_PREFIX + (current + sibling if pos % 2 == 0 else sibling + current)).digest()
        pos, n = pos // 2, (n + 1) // 2
    return current.hex() == proof.spine_root
