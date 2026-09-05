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
Ariadne Protocol v2 — Delta Verification

The DeltaVerifier is the Phase 1 completion criterion. It encapsulates
five tampering test cases that any conforming implementation must detect:

1. Content tampering — content_hash mismatch → leaf_hash → root mismatch
2. Sequence index modification — position-binding catches reordering
3. Segment insertion/deletion — count mismatch + chain breaks
4. Audit chain tampering — prev_audit_hash chain breaks
5. Backdated wall_clock — logical clock monotonicity violation

A verifier catching only case 1 is a content integrity verifier.
Cases 2-5 are required for temporal integrity. All five must pass.
"""

from typing import List, Optional

from pydantic import BaseModel

from ariadne.protocol.audit import AuditRecord, compute_audit_hash, GENESIS_HASH
from ariadne.protocol.leaf_hash import compute_leaf_hash
from ariadne.protocol.merkle import MerkleTree
from ariadne.protocol.node import CognitiveNode


class VerificationResult(BaseModel):
    """Structured result from the five-test verification gate."""
    content_integrity: bool = False
    position_integrity: bool = False
    count_integrity: bool = False
    audit_chain_integrity: bool = False
    clock_monotonicity: bool = False

    failure_details: List[str] = []

    @property
    def all_passed(self) -> bool:
        return (
            self.content_integrity
            and self.position_integrity
            and self.count_integrity
            and self.audit_chain_integrity
            and self.clock_monotonicity
        )

    @property
    def passed_count(self) -> int:
        return sum([
            self.content_integrity,
            self.position_integrity,
            self.count_integrity,
            self.audit_chain_integrity,
            self.clock_monotonicity,
        ])


def verify_content_integrity(nodes: List[CognitiveNode]) -> tuple[bool, List[str]]:
    """Test 1: Verify each node's stored leaf_hash matches recomputation.

    Content tampering changes content_hash, which changes the recomputed
    leaf_hash, which no longer matches the stored leaf_hash.
    """
    failures = []
    for node in nodes:
        if node.leaf_hash is None:
            failures.append(f"Node {node.node_id}: leaf_hash is None (not computed)")
            continue

        recomputed = compute_leaf_hash(
            node_id=node.node_id,
            node_type=node.node_type,
            schema_version=node.schema_version,
            sequence_index=node.sequence_index,
            content_hash=node.content_hash,
            sealed_at=node.sealed_at,
            parent_node_id=node.parent_node_id,
        )
        if recomputed != node.leaf_hash:
            failures.append(
                f"Node {node.node_id} at sequence_index={node.sequence_index}: "
                f"leaf_hash mismatch (stored={node.leaf_hash[:16]}..., "
                f"recomputed={recomputed[:16]}...)"
            )

    return len(failures) == 0, failures


def verify_position_integrity(nodes: List[CognitiveNode]) -> tuple[bool, List[str]]:
    """Test 2: Verify sequence_index is consecutive with no gaps.

    Swapping two nodes' positions or inserting between positions
    would produce non-consecutive sequence indices.
    """
    failures = []
    sorted_nodes = sorted(nodes, key=lambda n: n.sequence_index)

    for i in range(len(sorted_nodes) - 1):
        current = sorted_nodes[i].sequence_index
        next_idx = sorted_nodes[i + 1].sequence_index
        if next_idx != current + 1:
            failures.append(
                f"Gap at sequence_index {current} → {next_idx} "
                f"(expected {current + 1})"
            )

    return len(failures) == 0, failures


def verify_spine_root(
    nodes: List[CognitiveNode],
    expected_root: str,
) -> tuple[bool, List[str]]:
    """Test 3: Verify the Merkle root matches expected.

    Insertion or deletion of nodes changes the leaf set,
    producing a different root hash.
    """
    failures = []

    sorted_nodes = sorted(nodes, key=lambda n: n.sequence_index)
    leaf_hashes = []
    for node in sorted_nodes:
        if node.leaf_hash is None:
            failures.append(f"Node {node.node_id}: leaf_hash is None")
            continue
        leaf_hashes.append(node.leaf_hash)

    if failures:
        return False, failures

    tree = MerkleTree()
    computed_root = tree.build(leaf_hashes)

    if computed_root != expected_root:
        failures.append(
            f"Spine root mismatch: expected={expected_root[:16]}..., "
            f"computed={computed_root[:16]}... "
            f"(leaf count: {len(leaf_hashes)})"
        )

    return len(failures) == 0, failures


def verify_audit_chain(records: List[AuditRecord]) -> tuple[bool, List[str]]:
    """Test 4: Verify the audit chain's prev_audit_hash links.

    Tampering with any audit record produces a different hash,
    breaking the chain at the next record.
    """
    failures = []
    expected_prev = GENESIS_HASH

    for i, record in enumerate(records):
        if record.prev_audit_hash != expected_prev:
            failures.append(
                f"Audit chain break at record {i} ({record.record_id}): "
                f"prev_audit_hash={record.prev_audit_hash[:16]}..., "
                f"expected={expected_prev[:16]}..."
            )
        expected_prev = compute_audit_hash(record)

    return len(failures) == 0, failures


def verify_clock_monotonicity(records: List[AuditRecord]) -> tuple[bool, List[str]]:
    """Test 5: Verify logical clock is strictly monotonically increasing.

    A decreasing logical clock indicates backdating — either clock
    tampering or an out-of-order event insertion.
    """
    failures = []

    for i in range(len(records) - 1):
        current = records[i].logical_clock
        next_clock = records[i + 1].logical_clock
        if next_clock <= current:
            failures.append(
                f"Clock monotonicity violation at record {i+1}: "
                f"logical_clock={next_clock} <= previous={current}"
            )

    return len(failures) == 0, failures


class DeltaVerifier:
    """The Phase 1 five-test gate.

    Runs all five verification checks and returns a structured
    VerificationResult. All five must pass for the data to be
    considered tamper-free.
    """

    @staticmethod
    def verify_all(
        nodes: List[CognitiveNode],
        audit_records: List[AuditRecord],
        expected_root: str,
    ) -> VerificationResult:
        """Run all five verification tests.

        Args:
            nodes: CognitiveNodes to verify (must have leaf_hash computed)
            audit_records: Audit chain records in order
            expected_root: Expected Merkle spine root hash

        Returns:
            VerificationResult with per-test pass/fail and failure details
        """
        result = VerificationResult()
        all_failures = []

        # Test 1: Content integrity
        passed, failures = verify_content_integrity(nodes)
        result.content_integrity = passed
        all_failures.extend(failures)

        # Test 2: Position integrity
        passed, failures = verify_position_integrity(nodes)
        result.position_integrity = passed
        all_failures.extend(failures)

        # Test 3: Spine root / count integrity
        passed, failures = verify_spine_root(nodes, expected_root)
        result.count_integrity = passed
        all_failures.extend(failures)

        # Test 4: Audit chain integrity
        passed, failures = verify_audit_chain(audit_records)
        result.audit_chain_integrity = passed
        all_failures.extend(failures)

        # Test 5: Clock monotonicity
        passed, failures = verify_clock_monotonicity(audit_records)
        result.clock_monotonicity = passed
        all_failures.extend(failures)

        result.failure_details = all_failures
        return result
