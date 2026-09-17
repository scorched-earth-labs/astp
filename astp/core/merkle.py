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
Adaptive Merkle Tree

Key properties that distinguish this from a standard static Merkle tree:
1. ORDERING FUNCTION: Leaves sorted by configurable criteria before construction
2. SELECTIVE RECALCULATION: O(log n) updates when data changes or is appended
3. COMPACT FINGERPRINT: Leftmost branch array for efficient external verification
4. THRESHOLD SIGNIFICANCE: Fingerprint comparison reveals change importance
5. INCREMENTAL GROWTH: Tree extends naturally as data is appended

Applied to Ariadne:
- Episode segments are leaves, ordered chronologically (default) or by importance
- As segments are appended, only the affected branch path is recalculated
- The leftmost branch fingerprint is the Episode's compact external proof
- Comparing fingerprints across crystallization points reveals what changed and how significantly
- The tree grows with the episode; no full rebuild required

This module replaces the static compute_spine_hash() with an incremental structure
that keeps these adaptive properties while maintaining cryptographic integrity.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("astp.core.merkle")


# ============================================================================
# Hash Primitives (consistent with schema.py)
# ============================================================================

def _sha3_256(data: bytes) -> str:
    """Canonical hash function for all Ariadne content hashing. Returns hex string."""
    return hashlib.sha3_256(data).hexdigest()


def _leaf_hash(content_hash: str) -> str:
    """Domain-separated leaf hash. Prevents second-preimage attacks on tree structure."""
    return _sha3_256(b"LEAF:" + content_hash.encode())


def _node_hash(left: str, right: str) -> str:
    """Domain-separated internal node hash."""
    return _sha3_256(b"NODE:" + left.encode() + right.encode())


# ============================================================================
# Ordering Functions
# ============================================================================

class OrderingCriteria(str, Enum):
    """Ordering criteria for adaptive Merkle tree leaves."""
    CHRONOLOGICAL = "chronological"     # Default for episodes — sequence_index order
    IMPORTANCE = "importance"           # Spine segments before branch segments
    SIZE = "size"                       # Larger segments first


@dataclass
class LeafEntry:
    """A leaf in the adaptive Merkle tree with metadata for ordering."""
    content_hash: str           # SHA3-256 of the content
    sequence_index: int         # Original position in the episode
    importance: int = 0         # 0=normal, 1=spine, 2=crystallization
    size: int = 0               # Content size in bytes
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def leaf_hash(self) -> str:
        """Compute the domain-separated leaf hash."""
        return _leaf_hash(self.content_hash)


def chronological_ordering(leaves: List[LeafEntry]) -> List[LeafEntry]:
    """Order by sequence_index (default for episodes)."""
    return sorted(leaves, key=lambda l: l.sequence_index)


def importance_ordering(leaves: List[LeafEntry]) -> List[LeafEntry]:
    """Order by importance (spine first), then chronologically within tier."""
    return sorted(leaves, key=lambda l: (-l.importance, l.sequence_index))


ORDERING_FUNCTIONS: Dict[OrderingCriteria, Callable] = {
    OrderingCriteria.CHRONOLOGICAL: chronological_ordering,
    OrderingCriteria.IMPORTANCE: importance_ordering,
}


# ============================================================================
# Adaptive Merkle Tree
# ============================================================================

@dataclass
class MerkleNode:
    """A node in the adaptive Merkle tree."""
    hash: str
    left: Optional['MerkleNode'] = None
    right: Optional['MerkleNode'] = None
    level: int = 0              # 0 = leaf level
    index: int = 0              # Position at this level


class AdaptiveMerkleTree:
    """
    Adaptive Merkle tree with incremental updates and compact fingerprints.

    Key behaviours:
    - Claim 1: Ordered construction from data collection using ordering function
    - Claim 2: Selective recalculation on change detection
    - Claim 3: Only affected nodes recalculated
    - Claim 4: Compact substring/subset fingerprint from branch
    - Claim 5: Configurable ordering criteria

    Usage:
        tree = AdaptiveMerkleTree(ordering=OrderingCriteria.CHRONOLOGICAL)

        # Add leaves incrementally
        tree.append_leaf(LeafEntry(content_hash="abc123", sequence_index=0))
        tree.append_leaf(LeafEntry(content_hash="def456", sequence_index=1))

        # Get the root hash (compatible with compute_spine_hash)
        root = tree.root_hash

        # Get the compact fingerprint (leftmost branch array)
        fingerprint = tree.extract_fingerprint()

        # Compare fingerprints for significance
        diff = AdaptiveMerkleTree.compare_fingerprints(fp1, fp2)
    """

    def __init__(
        self,
        ordering: OrderingCriteria = OrderingCriteria.CHRONOLOGICAL,
        unique_identifier: Optional[str] = None,
    ):
        self._ordering = ordering
        self._order_fn = ORDERING_FUNCTIONS.get(ordering, chronological_ordering)
        self._unique_id = unique_identifier  # Episode ID — becomes first leaf
        self._leaves: List[LeafEntry] = []
        self._leaf_hashes: List[str] = []    # Cached leaf-level hashes
        self._levels: List[List[str]] = []   # All levels of the tree [leaves, ..., root]
        self._root: Optional[str] = None
        self._dirty = True                   # Needs rebuild

    @property
    def root_hash(self) -> Optional[str]:
        """The Merkle root hash. Recomputes only affected nodes if dirty."""
        if self._dirty:
            self._rebuild()
        return self._root

    @property
    def leaf_count(self) -> int:
        return len(self._leaves)

    @property
    def tree_depth(self) -> int:
        """Depth of the tree (number of levels from leaf to root)."""
        if not self._leaves:
            return 0
        return len(self._levels)

    def append_leaf(self, entry: LeafEntry) -> None:
        """
        Append a new leaf to the tree. O(log n) update.

        Detects the addition and recalculates only affected nodes.
        """
        self._leaves.append(entry)
        leaf_hash = entry.leaf_hash
        self._leaf_hashes.append(leaf_hash)

        if not self._levels:
            # First leaf — initialize tree
            self._levels = [[leaf_hash]]
            self._root = leaf_hash
            self._dirty = False
            return

        # Incremental update: add the new leaf and propagate up
        # Only the rightmost branch path needs recalculation
        self._incremental_append(leaf_hash)
        self._dirty = False

    def update_leaf(self, index: int, new_content_hash: str) -> None:
        """
        Update a leaf's content hash. O(log n) recalculation.

        Only nodes affected by the change are recalculated.
        """
        if index >= len(self._leaves):
            raise IndexError(f"Leaf index {index} out of range (have {len(self._leaves)})")

        self._leaves[index].content_hash = new_content_hash
        new_leaf_hash = _leaf_hash(new_content_hash)
        self._leaf_hashes[index] = new_leaf_hash

        # Selective recalculation: walk from the changed leaf to the root,
        # recalculating only the affected path
        self._selective_recalculate(index)
        self._dirty = False

    def build_from_leaves(self, leaves: List[LeafEntry]) -> str:
        """
        Build the tree from a complete set of leaves.

        Applies the ordering function before construction.
        Returns the root hash.
        """
        self._leaves = list(leaves)

        # Apply ordering function
        ordered = self._order_fn(self._leaves)
        self._leaves = ordered

        # Optionally prepend unique identifier as first leaf
        if self._unique_id:
            uid_entry = LeafEntry(
                content_hash=_sha3_256(self._unique_id.encode()),
                sequence_index=-1,
                importance=2,  # Highest importance
                metadata={"type": "unique_identifier"},
            )
            self._leaves.insert(0, uid_entry)

        self._leaf_hashes = [entry.leaf_hash for entry in self._leaves]
        self._rebuild()
        return self._root

    # ========================================================================
    # Compact Fingerprint
    # ========================================================================

    def extract_fingerprint(self, branch: str = "leftmost", k: int = 8) -> str:
        """
        Extract a compact fingerprint from a branch of the tree.

        The fingerprint is constructed from the leftmost leaf,
        nodes along the leftmost branch, and the root.

        Each component contributes a substring of
        length k characters, producing a compact fixed-format fingerprint.

        Args:
            branch: "leftmost" (default) or "rightmost"
            k: Number of hex characters per component

        Returns:
            Compact hexadecimal fingerprint string
        """
        if not self._levels:
            return ""

        components = self._extract_branch_path(branch)

        # Extract k-character substrings from each component
        fingerprint_parts = [comp[:k] for comp in components]
        return "".join(fingerprint_parts)

    def extract_full_branch_array(self, branch: str = "leftmost") -> List[str]:
        """
        Extract the full branch array (all hashes along a branch path).

        Array comprising leftmost leaf, branch nodes, and root.
        This is the full-resolution version of the fingerprint.
        """
        return self._extract_branch_path(branch)

    @staticmethod
    def compare_fingerprints(
        fp1: str,
        fp2: str,
        k: int = 8,
    ) -> Dict[str, Any]:
        """
        Compare two fingerprints for significance.

        The position of the first difference indicates the
        importance of the change. Earlier differences = more significant changes
        (because the ordering function places important data leftward/upward).

        Returns:
            {
                "identical": bool,
                "first_diff_position": int or None,
                "first_diff_component": int or None,  # Which tree level differs
                "significance": "critical" | "moderate" | "minor" | "none",
                "components_changed": int,
            }
        """
        if fp1 == fp2:
            return {
                "identical": True,
                "first_diff_position": None,
                "first_diff_component": None,
                "significance": "none",
                "components_changed": 0,
            }

        # Find first difference position
        first_diff = None
        for i, (c1, c2) in enumerate(zip(fp1, fp2)):
            if c1 != c2:
                first_diff = i
                break

        # If one is longer, the difference is at the extension point
        if first_diff is None:
            first_diff = min(len(fp1), len(fp2))

        # Which component (tree level) does the difference fall in?
        component = first_diff // k if k > 0 else 0
        total_components = max(len(fp1), len(fp2)) // k if k > 0 else 1

        # Count total components changed
        components_changed = 0
        for i in range(0, max(len(fp1), len(fp2)), k):
            chunk1 = fp1[i:i+k] if i < len(fp1) else ""
            chunk2 = fp2[i:i+k] if i < len(fp2) else ""
            if chunk1 != chunk2:
                components_changed += 1

        # Significance based on which component differs first
        # Threshold position separating significant from minor changes
        # Component 0 = leaf/UID (most significant)
        # Last component = root (changes on any modification)
        if component == 0:
            significance = "critical"  # Change at the foundation
        elif component < total_components // 2:
            significance = "moderate"  # Change in lower tree levels
        else:
            significance = "minor"     # Change near the root (any append does this)

        return {
            "identical": False,
            "first_diff_position": first_diff,
            "first_diff_component": component,
            "significance": significance,
            "components_changed": components_changed,
        }

    # ========================================================================
    # Internal: Tree Construction & Update
    # ========================================================================

    def _rebuild(self) -> None:
        """Full rebuild of the tree from leaf hashes. Used for initial construction."""
        if not self._leaf_hashes:
            self._root = None
            self._levels = []
            return

        # Build bottom-up
        current_level = list(self._leaf_hashes)
        self._levels = [current_level]

        while len(current_level) > 1:
            next_level = []
            for i in range(0, len(current_level), 2):
                if i + 1 < len(current_level):
                    combined = _node_hash(current_level[i], current_level[i + 1])
                else:
                    combined = current_level[i]  # Odd node passes through
                next_level.append(combined)
            self._levels.append(next_level)
            current_level = next_level

        self._root = current_level[0]
        self._dirty = False

    def _incremental_append(self, new_leaf_hash: str) -> None:
        """
        Append a new leaf and update only the affected path. O(log n).

        Only recalculates nodes affected by the addition.
        """
        # Add to leaf level
        self._levels[0].append(new_leaf_hash)

        # Walk up the tree, recalculating only the rightmost path
        for level_idx in range(len(self._levels) - 1):
            current_level = self._levels[level_idx]
            next_level = self._levels[level_idx + 1]

            # The new/changed node is the last in this level
            pos = len(current_level) - 1
            parent_pos = pos // 2

            # Compute parent hash
            if pos % 2 == 0:
                # New node is a left child — it's its own parent (odd count)
                parent_hash = current_level[pos]
            else:
                # New node is a right child — combine with left sibling
                parent_hash = _node_hash(current_level[pos - 1], current_level[pos])

            # Update or append parent
            if parent_pos < len(next_level):
                next_level[parent_pos] = parent_hash
            else:
                next_level.append(parent_hash)

        # Check if we need a new root level
        if len(self._levels[-1]) > 1:
            # Current top level has more than one node — reduce
            top = self._levels[-1]
            new_top = []
            for i in range(0, len(top), 2):
                if i + 1 < len(top):
                    new_top.append(_node_hash(top[i], top[i + 1]))
                else:
                    new_top.append(top[i])
            self._levels.append(new_top)

        self._root = self._levels[-1][0]

    def _selective_recalculate(self, leaf_index: int) -> None:
        """
        Recalculate only the path from a changed leaf to the root. O(log n).

        Determines affected nodes and recalculates only those.
        """
        # Update leaf level
        self._levels[0][leaf_index] = self._leaf_hashes[leaf_index]

        # Walk up, recalculating each parent on the affected path
        pos = leaf_index
        for level_idx in range(len(self._levels) - 1):
            current_level = self._levels[level_idx]
            next_level = self._levels[level_idx + 1]

            parent_pos = pos // 2
            left_child = pos - (pos % 2)
            right_child = left_child + 1

            if right_child < len(current_level):
                parent_hash = _node_hash(current_level[left_child], current_level[right_child])
            else:
                parent_hash = current_level[left_child]  # Odd — passes through

            next_level[parent_pos] = parent_hash
            pos = parent_pos

        self._root = self._levels[-1][0]

    def _extract_branch_path(self, branch: str = "leftmost") -> List[str]:
        """Extract hashes along a branch path from leaf to root."""
        if not self._levels:
            return []

        components = []
        if branch == "leftmost":
            # Leftmost leaf, then leftmost branch nodes to root
            for level in self._levels:
                if level:
                    components.append(level[0])
        elif branch == "rightmost":
            for level in self._levels:
                if level:
                    components.append(level[-1])

        return components


# ============================================================================
# Compatibility: Drop-in replacement for compute_spine_hash
# ============================================================================

def compute_adaptive_spine_hash(
    segment_content_hashes: List[str],
    spine_signal_hashes: List[str],
    episode_id: Optional[str] = None,
    ordering: OrderingCriteria = OrderingCriteria.CHRONOLOGICAL,
    hitl_node_hashes: Optional[List[str]] = None,
) -> Tuple[str, 'AdaptiveMerkleTree']:
    """
    Build an adaptive Merkle tree from segment, signal, and HITL node hashes.

    Drop-in compatible with compute_spine_hash() but returns both the
    root hash AND the tree instance (for fingerprint extraction, incremental
    updates, and significance comparison).

    Args:
        segment_content_hashes: Ordered segment content hashes
        spine_signal_hashes: SPINE-placed signal hashes
        episode_id: Optional unique identifier (becomes first leaf)
        ordering: Ordering criteria for leaves
        hitl_node_hashes: Resolved HITL event node_hashes (causal anchors)

    Returns:
        (root_hash, tree_instance)
    """
    tree = AdaptiveMerkleTree(ordering=ordering, unique_identifier=episode_id)

    # Build leaf entries from segment hashes
    leaves = []
    for i, h in enumerate(segment_content_hashes):
        leaves.append(LeafEntry(
            content_hash=h,
            sequence_index=i,
            importance=0,
            metadata={"type": "segment"},
        ))

    # Add signal hashes as leaves (lower importance)
    for i, h in enumerate(spine_signal_hashes):
        leaves.append(LeafEntry(
            content_hash=h,
            sequence_index=len(segment_content_hashes) + i,
            importance=0,
            metadata={"type": "signal"},
        ))

    # Add HITL node hashes as causal anchor leaves (high importance)
    # Human decisions are spine anchors — they carry the authorization
    # chain for all subsequent segments.
    for i, h in enumerate(hitl_node_hashes or []):
        leaves.append(LeafEntry(
            content_hash=h,
            sequence_index=len(segment_content_hashes) + len(spine_signal_hashes) + i,
            importance=2,  # High importance — causal anchor
            metadata={"type": "hitl_anchor"},
        ))

    if not leaves:
        raise ValueError("Cannot compute spine_hash: no leaves provided")

    root = tree.build_from_leaves(leaves)
    return root, tree


def compute_spine_hash_adaptive(
    segment_content_hashes: List[str],
    spine_signal_hashes: List[str],
) -> str:
    """
    Backward-compatible wrapper that returns only the root hash.

    Same signature as the original compute_spine_hash() — can be used
    as a drop-in replacement while the codebase migrates to the full
    adaptive tree API.
    """
    root, _ = compute_adaptive_spine_hash(
        segment_content_hashes,
        spine_signal_hashes,
    )
    return root
