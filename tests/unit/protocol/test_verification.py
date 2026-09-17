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
The Five-Test Gate — Phase 1 Completion Criterion

These five tests must ALL pass for Phase 1 to be considered complete.
Each test verifies that a specific class of tampering is detectable
by the DeltaVerifier.

Test 1: Content tampering detection
Test 2: Sequence index modification detection
Test 3: Segment insertion/deletion detection
Test 4: Audit chain tampering detection
Test 5: Backdated wall_clock detection
"""

from datetime import datetime, timezone, timedelta
from uuid import uuid4

from astp.core.schema import sha3_256
from astp.protocol.node import CognitiveNode
from astp.protocol.leaf_hash import compute_leaf_hash_from_node
from astp.protocol.merkle import MerkleTree
from astp.protocol.audit import AuditRecord, AuditChain
from astp.protocol.verification import (
    DeltaVerifier,
    verify_content_integrity,
    verify_position_integrity,
    verify_spine_root,
    verify_audit_chain,
    verify_clock_monotonicity,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_node(seq: int, content: str = "", parent_id=None) -> CognitiveNode:
    """Create a test CognitiveNode with computed leaf_hash."""
    content_hash = sha3_256(content.encode() if content else f"content-{seq}".encode())
    node = CognitiveNode(
        node_type="episode",
        schema_version="2.0.0",
        sequence_index=seq,
        tree_leaf_index=seq,
        content_hash=content_hash,
        authored_by="test-agent",
        parent_node_id=parent_id,
    )
    node.leaf_hash = compute_leaf_hash_from_node(node)
    return node


def _make_nodes(count: int = 5) -> list[CognitiveNode]:
    """Create a list of test nodes with consecutive sequence indices."""
    parent_id = uuid4()
    return [_make_node(i, f"segment-content-{i}", parent_id) for i in range(count)]


def _build_tree(nodes: list[CognitiveNode]) -> tuple[MerkleTree, str]:
    """Build a Merkle tree from nodes and return (tree, root_hash)."""
    tree = MerkleTree()
    leaf_hashes = [n.leaf_hash for n in nodes]
    root = tree.build(leaf_hashes)
    return tree, root


def _make_audit_chain(count: int = 5) -> list[AuditRecord]:
    """Create a valid audit chain with correct linking."""
    chain = AuditChain()
    node_id = uuid4()
    base_time = datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc)

    records = []
    for i in range(count):
        record = AuditRecord(
            node_id=node_id,
            delta_id=uuid4(),
            delta_type="CONTENT",
            actor="test-agent",
            wall_clock=base_time + timedelta(minutes=i),
            logical_clock=i + 1,
            pre_state_hash=sha3_256(f"pre-{i}".encode()),
            post_state_hash=sha3_256(f"post-{i}".encode()),
            delta_hash=sha3_256(f"delta-{i}".encode()),
        )
        chain.append(record)
        records.append(record)

    return records


# ── Test 1: Content Tampering Detection ──────────────────────────────────────

class TestContentTampering:
    """Verifier must detect when content_hash has been modified."""

    def test_clean_data_passes(self):
        nodes = _make_nodes(5)
        passed, failures = verify_content_integrity(nodes)
        assert passed, f"Clean data should pass: {failures}"

    def test_tampered_content_detected(self):
        nodes = _make_nodes(5)
        # Tamper: change content_hash without recomputing leaf_hash
        nodes[2].content_hash = sha3_256(b"tampered-content")
        passed, failures = verify_content_integrity(nodes)
        assert not passed, "Tampered content should be detected"
        assert any("sequence_index=2" in f for f in failures)

    def test_tampered_content_changes_root(self):
        nodes = _make_nodes(5)
        _, original_root = _build_tree(nodes)
        # Tamper and recompute leaf hash (sophisticated attacker)
        nodes[2].content_hash = sha3_256(b"tampered-content")
        nodes[2].leaf_hash = compute_leaf_hash_from_node(nodes[2])
        _, tampered_root = _build_tree(nodes)
        assert original_root != tampered_root


# ── Test 2: Sequence Index Modification Detection ────────────────────────────

class TestSequenceIndexModification:
    """Verifier must detect when sequence_index has been swapped or changed."""

    def test_clean_sequence_passes(self):
        nodes = _make_nodes(5)
        passed, failures = verify_position_integrity(nodes)
        assert passed, f"Clean sequence should pass: {failures}"

    def test_swapped_positions_detected(self):
        nodes = _make_nodes(5)
        # Swap sequence_index of nodes 2 and 3
        nodes[2].sequence_index, nodes[3].sequence_index = (
            nodes[3].sequence_index,
            nodes[2].sequence_index,
        )
        # leaf_hash no longer matches because sequence_index is in preimage
        passed, failures = verify_content_integrity(nodes)
        assert not passed, "Swapped positions should break leaf_hash verification"

    def test_position_swap_changes_leaf_hash(self):
        node = _make_node(5, "test-content")
        original_hash = node.leaf_hash
        node.sequence_index = 99
        recomputed = compute_leaf_hash_from_node(node)
        assert original_hash != recomputed, "Changing sequence_index must change leaf_hash"


# ── Test 3: Segment Insertion/Deletion Detection ─────────────────────────────

class TestInsertionDeletion:
    """Verifier must detect when nodes are added or removed."""

    def test_insertion_changes_root(self):
        nodes = _make_nodes(5)
        _, original_root = _build_tree(nodes)
        # Insert a new node
        extra = _make_node(5, "inserted-content", nodes[0].parent_node_id)
        nodes_with_extra = nodes + [extra]
        _, new_root = _build_tree(nodes_with_extra)
        assert original_root != new_root, "Insertion must change root hash"

    def test_deletion_changes_root(self):
        nodes = _make_nodes(5)
        _, original_root = _build_tree(nodes)
        # Delete a node
        nodes_minus_one = nodes[:2] + nodes[3:]
        _, new_root = _build_tree(nodes_minus_one)
        assert original_root != new_root, "Deletion must change root hash"

    def test_count_mismatch_detected(self):
        nodes = _make_nodes(5)
        _, original_root = _build_tree(nodes)
        # Add a node — root won't match
        extra = _make_node(5, "extra", nodes[0].parent_node_id)
        nodes_with_extra = nodes + [extra]
        passed, failures = verify_spine_root(nodes_with_extra, original_root)
        assert not passed, "Extra node should cause root mismatch"

    def test_deletion_breaks_position_integrity(self):
        nodes = _make_nodes(5)
        # Remove node at index 2 — creates gap: 0,1,3,4
        nodes_with_gap = nodes[:2] + nodes[3:]
        passed, failures = verify_position_integrity(nodes_with_gap)
        assert not passed, "Gap in sequence should be detected"


# ── Test 4: Audit Chain Tampering Detection ──────────────────────────────────

class TestAuditChainTampering:
    """Verifier must detect when audit records have been modified."""

    def test_clean_chain_passes(self):
        records = _make_audit_chain(5)
        passed, failures = verify_audit_chain(records)
        assert passed, f"Clean audit chain should pass: {failures}"

    def test_tampered_record_detected(self):
        records = _make_audit_chain(5)
        # Tamper with record 2's pre_state_hash
        records[2].pre_state_hash = sha3_256(b"tampered-state")
        passed, failures = verify_audit_chain(records)
        assert not passed, "Tampered audit record should be detected"
        # The break is detected at record 3 (whose prev_audit_hash
        # won't match the recomputed hash of tampered record 2)
        assert any("record 3" in f for f in failures)

    def test_deleted_record_detected(self):
        records = _make_audit_chain(5)
        # Delete record 2 — record 3's prev_audit_hash won't match
        records_with_gap = records[:2] + records[3:]
        passed, failures = verify_audit_chain(records_with_gap)
        assert not passed, "Deleted audit record should break the chain"


# ── Test 5: Backdated Wall Clock Detection ───────────────────────────────────

class TestBackdatedClock:
    """Verifier must detect when logical clock decreases."""

    def test_clean_clocks_pass(self):
        records = _make_audit_chain(5)
        passed, failures = verify_clock_monotonicity(records)
        assert passed, f"Clean clocks should pass: {failures}"

    def test_backdated_clock_detected(self):
        records = _make_audit_chain(5)
        # Set record 3's logical clock to less than record 2's
        records[3].logical_clock = records[2].logical_clock - 1
        passed, failures = verify_clock_monotonicity(records)
        assert not passed, "Backdated clock should be detected"
        assert any("record 3" in f for f in failures)

    def test_equal_clock_detected(self):
        records = _make_audit_chain(5)
        # Equal clock (not strictly increasing) is also a violation
        records[3].logical_clock = records[2].logical_clock
        passed, failures = verify_clock_monotonicity(records)
        assert not passed, "Non-strictly-increasing clock should be detected"


# ── Integration: The Five-Test Gate ──────────────────────────────────────────

class TestFiveTestGate:
    """DeltaVerifier.verify_all() must pass all five checks on clean data
    and detect each individual tampering type."""

    def test_clean_data_passes_all_five(self):
        nodes = _make_nodes(5)
        _, root = _build_tree(nodes)
        records = _make_audit_chain(5)

        result = DeltaVerifier.verify_all(nodes, records, root)
        assert result.all_passed, (
            f"Clean data should pass all 5 tests. "
            f"Passed: {result.passed_count}/5. "
            f"Failures: {result.failure_details}"
        )

    def test_content_tampering_caught(self):
        nodes = _make_nodes(5)
        _, root = _build_tree(nodes)
        records = _make_audit_chain(5)

        nodes[2].content_hash = sha3_256(b"tampered")
        result = DeltaVerifier.verify_all(nodes, records, root)
        assert not result.content_integrity
        assert not result.all_passed

    def test_sequence_modification_caught(self):
        nodes = _make_nodes(5)
        _, root = _build_tree(nodes)
        records = _make_audit_chain(5)

        # Swap positions 2 and 3
        nodes[2].sequence_index, nodes[3].sequence_index = 3, 2
        result = DeltaVerifier.verify_all(nodes, records, root)
        assert not result.content_integrity  # leaf hashes won't match
        assert not result.all_passed

    def test_insertion_caught(self):
        nodes = _make_nodes(5)
        _, root = _build_tree(nodes)
        records = _make_audit_chain(5)

        extra = _make_node(5, "extra", nodes[0].parent_node_id)
        result = DeltaVerifier.verify_all(nodes + [extra], records, root)
        assert not result.count_integrity  # root mismatch
        assert not result.all_passed

    def test_audit_tampering_caught(self):
        nodes = _make_nodes(5)
        _, root = _build_tree(nodes)
        records = _make_audit_chain(5)

        records[2].pre_state_hash = sha3_256(b"tampered")
        result = DeltaVerifier.verify_all(nodes, records, root)
        assert not result.audit_chain_integrity
        assert not result.all_passed

    def test_backdated_clock_caught(self):
        nodes = _make_nodes(5)
        _, root = _build_tree(nodes)
        records = _make_audit_chain(5)

        records[3].logical_clock = 0
        result = DeltaVerifier.verify_all(nodes, records, root)
        assert not result.clock_monotonicity
        assert not result.all_passed
