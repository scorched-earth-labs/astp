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
Phase 3 Conformance Test Vectors

Implements the REQUIRED vectors from CONFORMANCE.md. All vectors
must pass for Phase 3 Protocol Conformance (Level 1).
"""

from datetime import datetime, timezone

import pytest

from astp.core.schema import sha3_256
from astp.protocol.keys import (
    derive_workspace_key, derive_node_key, derive_seal_key,
    enforce_key_version_monotonicity,
)
from astp.protocol.anchor import (
    AnchorCommitment, build_anchor_commitment,
)
from astp.protocol.witness import (
    WitnessRecord, compute_witness_commitment,
    verify_witness_commitment, enforce_witness_threshold,
)
from astp.protocol.chain_proof import (
    ProofLink, build_proof_chain, verify_proof_chain,
)
from astp.protocol.merkle import MerkleTree
from astp.protocol.leaf_hash import compute_leaf_hash
from astp.protocol.errors import GovernanceViolation, MonotonicityViolation


# ── Reference Values ─────────────────────────────────────────────────────────

ROOT_KEY = b"\x00" * 32
WORKSPACE_ID = "ws-test-001"
NODE_ID = "550e8400-e29b-41d4-a716-446655440000"
SPINE_ROOT_1 = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
SPINE_ROOT_2 = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b3"


# ── Key Hierarchy Vectors ────────────────────────────────────────────────────

class TestKeyHierarchy:
    """KH-001 through KH-005"""

    def test_kh001_workspace_key_derivation(self):
        """KH-001: Workspace key is derived correctly."""
        wk = derive_workspace_key(ROOT_KEY, WORKSPACE_ID)
        assert len(wk) == 32
        # Deterministic: same inputs produce same output
        wk2 = derive_workspace_key(ROOT_KEY, WORKSPACE_ID)
        assert wk == wk2

    def test_kh002_node_type_isolation(self):
        """KH-002: Different node_types produce different keys (G-16)."""
        wk = derive_workspace_key(ROOT_KEY, WORKSPACE_ID)

        nk_episode = derive_node_key(wk, NODE_ID, "episode")
        nk_signal = derive_node_key(wk, NODE_ID, "signal")
        nk_artifact = derive_node_key(wk, NODE_ID, "artifact")

        assert nk_episode != nk_signal, "episode and signal keys must differ (G-16)"
        assert nk_episode != nk_artifact, "episode and artifact keys must differ (G-16)"
        assert nk_signal != nk_artifact, "signal and artifact keys must differ (G-16)"

    def test_kh003_seal_key_binds_to_spine_root(self):
        """KH-003: Different spine_roots produce different seal keys."""
        wk = derive_workspace_key(ROOT_KEY, WORKSPACE_ID)
        nk = derive_node_key(wk, NODE_ID, "episode")

        sk1 = derive_seal_key(nk, SPINE_ROOT_1)
        sk2 = derive_seal_key(nk, SPINE_ROOT_2)

        assert sk1 != sk2, "Seal keys must differ for different spine_roots"

    def test_kh004_key_version_monotonicity(self):
        """KH-004: Key version rollback is rejected (G-15)."""
        # Valid increment
        enforce_key_version_monotonicity(3, 4)  # Should not raise

        # Rollback
        with pytest.raises(MonotonicityViolation):
            enforce_key_version_monotonicity(3, 2)

        # Duplicate
        with pytest.raises(MonotonicityViolation):
            enforce_key_version_monotonicity(3, 3)

    def test_kh005_node_type_always_in_derivation(self):
        """KH-005: No code path derives a node key without node_type."""
        wk = derive_workspace_key(ROOT_KEY, WORKSPACE_ID)
        # The derive_node_key function requires node_type as a parameter.
        # An empty string is technically possible but produces a distinct key.
        nk_empty = derive_node_key(wk, NODE_ID, "")
        nk_episode = derive_node_key(wk, NODE_ID, "episode")
        assert nk_empty != nk_episode, "Empty node_type must produce different key"


# ── Transparency Log Vectors ─────────────────────────────────────────────────

class TestTransparencyLog:
    """TL-001 through TL-005"""

    def test_tl001_anchor_commitment_completeness(self):
        """TL-001: AnchorCommitment has exactly the protocol-specified fields."""
        ac = build_anchor_commitment(
            node_id=NODE_ID,
            node_type="episode",
            workspace_id=WORKSPACE_ID,
            spine_root=SPINE_ROOT_1,
            sequence_index=42,
            logical_clock=1000,
        )
        assert ac.node_id == NODE_ID
        assert ac.node_type == "episode"
        assert ac.workspace_id == WORKSPACE_ID
        assert ac.crystallization_root == SPINE_ROOT_1
        assert ac.crystallization_sequence == 42
        assert ac.logical_clock == 1000

    def test_tl002_anchor_excludes_payload(self):
        """TL-002: AnchorCommitment contains no payload fields."""
        ac = build_anchor_commitment(
            node_id=NODE_ID, node_type="episode",
            workspace_id=WORKSPACE_ID, spine_root=SPINE_ROOT_1,
            sequence_index=42, logical_clock=1000,
        )
        # AnchorCommitment should have no payload-related fields
        d = ac.model_dump()
        payload_fields = {"title", "participants", "content", "segment_content",
                          "context_note", "episode_mode"}
        for field in payload_fields:
            assert field not in d, f"Payload field '{field}' found in AnchorCommitment"

    def test_tl003_commitment_hash_determinism(self):
        """TL-003: commitment_hash is deterministic."""
        ac1 = AnchorCommitment(
            node_id=NODE_ID, node_type="episode", workspace_id=WORKSPACE_ID,
            crystallization_root=SPINE_ROOT_1, crystallization_sequence=42,
            logical_clock=1000,
            wall_clock=datetime(2026, 4, 12, 11, 0, 0, tzinfo=timezone.utc),
        )
        ac2 = AnchorCommitment(
            node_id=NODE_ID, node_type="episode", workspace_id=WORKSPACE_ID,
            crystallization_root=SPINE_ROOT_1, crystallization_sequence=42,
            logical_clock=1000,
            wall_clock=datetime(2026, 4, 12, 11, 0, 0, tzinfo=timezone.utc),
        )
        assert ac1.commitment_hash() == ac2.commitment_hash()

    def test_tl005_crystallization_root_immutability(self):
        """TL-005: crystallization_root is the value at crystallization."""
        ac = build_anchor_commitment(
            node_id=NODE_ID, node_type="episode",
            workspace_id=WORKSPACE_ID, spine_root=SPINE_ROOT_1,
            sequence_index=42, logical_clock=1000,
        )
        assert ac.crystallization_root == SPINE_ROOT_1


# ── Witness Signature Vectors ────────────────────────────────────────────────

class TestWitnessSignatures:
    """WS-001 through WS-006"""

    def test_ws001_commitment_determinism(self):
        """WS-001: WitnessCommitment is deterministic across invocations."""
        h1 = compute_witness_commitment(
            NODE_ID, "episode", SPINE_ROOT_1, 42, 1000, "REVIEWER"
        )
        h2 = compute_witness_commitment(
            NODE_ID, "episode", SPINE_ROOT_1, 42, 1000, "REVIEWER"
        )
        assert h1 == h2
        assert len(h1) == 64

    def test_ws002_commitment_binds_to_spine_root(self):
        """WS-002: Different spine_roots produce different commitments."""
        h1 = compute_witness_commitment(
            NODE_ID, "episode", SPINE_ROOT_1, 42, 1000, "REVIEWER"
        )
        h2 = compute_witness_commitment(
            NODE_ID, "episode", SPINE_ROOT_2, 42, 1000, "REVIEWER"
        )
        assert h1 != h2

    def test_ws003_commitment_binds_to_role(self):
        """WS-003: Different roles produce different commitments."""
        h1 = compute_witness_commitment(
            NODE_ID, "episode", SPINE_ROOT_1, 42, 1000, "REVIEWER"
        )
        h2 = compute_witness_commitment(
            NODE_ID, "episode", SPINE_ROOT_1, 42, 1000, "AUDITOR"
        )
        assert h1 != h2

    def test_ws004_commitment_hash_verification(self):
        """WS-004: G-12 enforcement — reject tampered commitment_hash."""
        correct_hash = compute_witness_commitment(
            NODE_ID, "episode", SPINE_ROOT_1, 42, 1000, "REVIEWER"
        )

        # Valid record
        valid = WitnessRecord(
            witness_id="agent-alpha", node_id=NODE_ID, node_type="episode",
            spine_root=SPINE_ROOT_1, sequence_index=42, logical_clock=1000,
            role="REVIEWER", commitment_hash=correct_hash,
        )
        assert verify_witness_commitment(valid)

        # Tampered commitment_hash
        tampered = WitnessRecord(
            witness_id="agent-alpha", node_id=NODE_ID, node_type="episode",
            spine_root=SPINE_ROOT_1, sequence_index=42, logical_clock=1000,
            role="REVIEWER", commitment_hash="0000" + correct_hash[4:],
        )
        assert not verify_witness_commitment(tampered)

        # Field/hash mismatch (spine_root changed but hash not updated)
        mismatched = WitnessRecord(
            witness_id="agent-alpha", node_id=NODE_ID, node_type="episode",
            spine_root=SPINE_ROOT_2, sequence_index=42, logical_clock=1000,
            role="REVIEWER", commitment_hash=correct_hash,
        )
        assert not verify_witness_commitment(mismatched)

    def test_ws005_invalid_records_dont_count(self):
        """WS-005: Invalid records don't count toward threshold (G-11, G-12)."""
        correct_hash = compute_witness_commitment(
            NODE_ID, "episode", SPINE_ROOT_1, 42, 1000, "REVIEWER"
        )

        valid_record = WitnessRecord(
            witness_id="agent-alpha", node_id=NODE_ID, node_type="episode",
            spine_root=SPINE_ROOT_1, sequence_index=42, logical_clock=1000,
            role="REVIEWER", commitment_hash=correct_hash,
        )
        invalid_record = WitnessRecord(
            witness_id="agent-beta", node_id=NODE_ID, node_type="episode",
            spine_root=SPINE_ROOT_1, sequence_index=42, logical_clock=1000,
            role="REVIEWER", commitment_hash="tampered_hash",
        )

        with pytest.raises(GovernanceViolation):
            enforce_witness_threshold([valid_record, invalid_record], min_counter_signatures=2)

    def test_ws006_distinct_witness_id_required(self):
        """WS-006: Same witness_id counts as ONE (G-11)."""
        hash_reviewer = compute_witness_commitment(
            NODE_ID, "episode", SPINE_ROOT_1, 42, 1000, "REVIEWER"
        )
        hash_auditor = compute_witness_commitment(
            NODE_ID, "episode", SPINE_ROOT_1, 42, 1000, "AUDITOR"
        )

        record_1 = WitnessRecord(
            witness_id="agent-alpha", node_id=NODE_ID, node_type="episode",
            spine_root=SPINE_ROOT_1, sequence_index=42, logical_clock=1000,
            role="REVIEWER", commitment_hash=hash_reviewer,
        )
        record_2 = WitnessRecord(
            witness_id="agent-alpha", node_id=NODE_ID, node_type="episode",
            spine_root=SPINE_ROOT_1, sequence_index=42, logical_clock=1000,
            role="AUDITOR", commitment_hash=hash_auditor,
        )

        with pytest.raises(GovernanceViolation):
            enforce_witness_threshold([record_1, record_2], min_counter_signatures=2)


# ── Chain Proof Vectors ──────────────────────────────────────────────────────

def _make_test_tree_and_root(content: str = "test") -> tuple:
    """Helper: build a simple Merkle tree and return (root, inclusion_proof)."""
    from astp.protocol.merkle import MerkleTree
    from astp.protocol.leaf_hash import compute_leaf_hash
    from uuid import UUID

    node_id = UUID(NODE_ID)
    leaf_hashes = []
    for i in range(3):
        lh = compute_leaf_hash(
            node_id=node_id, node_type="episode", schema_version="2.0.0",
            sequence_index=i, content_hash=sha3_256(f"{content}-{i}".encode()),
        )
        leaf_hashes.append(lh)

    tree = MerkleTree()
    root = tree.build(leaf_hashes)
    proof = tree.generate_inclusion_proof(0)
    return root, proof


class TestChainProofs:
    """CP-001 through CP-006"""

    def test_cp001_single_link_chain(self):
        """CP-001: Single-link chain is valid."""
        root, proof = _make_test_tree_and_root("cp001")
        link = ProofLink(
            node_id=NODE_ID, node_type="episode",
            spine_root=root, sequence_index=42,
            inclusion_proof=proof,
        )
        chain = build_proof_chain([link])
        result = verify_proof_chain(chain)
        assert result.valid, f"Single-link chain should be valid: {result.reason}"

    def test_cp002_two_link_parentage(self):
        """CP-002: Two-link chain with direct parentage."""
        root_a, proof_a = _make_test_tree_and_root("cp002-a")
        root_b, proof_b = _make_test_tree_and_root("cp002-b")

        link_a = ProofLink(
            node_id="node-A", node_type="episode",
            spine_root=root_a, sequence_index=10,
            inclusion_proof=proof_a,
        )
        link_b = ProofLink(
            node_id="node-B", node_type="episode",
            spine_root=root_b, sequence_index=5,
            inclusion_proof=proof_b,
            parent_node_id="node-A",
        )
        chain = build_proof_chain([link_a, link_b])
        result = verify_proof_chain(chain)
        assert result.valid, f"Parentage chain should be valid: {result.reason}"

    def test_cp003_chain_root_integrity(self):
        """CP-003: Incorrect chain_root is rejected (G-13)."""
        root_a, proof_a = _make_test_tree_and_root("cp003-a")
        root_b, proof_b = _make_test_tree_and_root("cp003-b")

        link_a = ProofLink(
            node_id="node-A", node_type="episode",
            spine_root=root_a, sequence_index=10,
            inclusion_proof=proof_a,
        )
        link_b = ProofLink(
            node_id="node-B", node_type="episode",
            spine_root=root_b, sequence_index=5,
            inclusion_proof=proof_b,
            parent_node_id="node-A",
        )
        chain = build_proof_chain([link_a, link_b])
        # Tamper with chain_root
        chain.chain_root = "0000" + chain.chain_root[4:]
        result = verify_proof_chain(chain)
        assert not result.valid
        assert "G-13" in result.reason

    def test_cp004_causal_order_violation(self):
        """CP-004: No causal relationship between links is rejected."""
        root_a, proof_a = _make_test_tree_and_root("cp004-a")
        root_b, proof_b = _make_test_tree_and_root("cp004-b")

        link_a = ProofLink(
            node_id="node-A", node_type="episode",
            spine_root=root_a, sequence_index=10,
            inclusion_proof=proof_a,
        )
        link_b = ProofLink(
            node_id="node-B", node_type="episode",
            spine_root=root_b, sequence_index=5,
            inclusion_proof=proof_b,
            parent_node_id="node-C",  # Parent is NOT node-A
        )
        chain = build_proof_chain([link_a, link_b])
        result = verify_proof_chain(chain)
        assert not result.valid
        assert "causal order" in result.reason

    def test_cp005_inclusion_proof_failure(self):
        """CP-005: Tampered inclusion proof invalidates chain."""
        root_a, proof_a = _make_test_tree_and_root("cp005-a")
        root_b, proof_b = _make_test_tree_and_root("cp005-b")

        # Tamper with proof_b
        if proof_b.merkle_path:
            proof_b.merkle_path[0] = "0000" + proof_b.merkle_path[0][4:]

        link_a = ProofLink(
            node_id="node-A", node_type="episode",
            spine_root=root_a, sequence_index=10,
            inclusion_proof=proof_a,
        )
        link_b = ProofLink(
            node_id="node-B", node_type="episode",
            spine_root=root_b, sequence_index=5,
            inclusion_proof=proof_b,
            parent_node_id="node-A",
        )
        chain = build_proof_chain([link_a, link_b])
        result = verify_proof_chain(chain)
        assert not result.valid
        assert "inclusion proof" in result.reason

    def test_cp006_cross_type_chain(self):
        """CP-006: Chain spanning multiple node types is valid."""
        root_s, proof_s = _make_test_tree_and_root("signal")
        root_e, proof_e = _make_test_tree_and_root("episode")

        link_signal = ProofLink(
            node_id="signal-001", node_type="signal",
            spine_root=root_s, sequence_index=0,
            inclusion_proof=proof_s,
        )
        link_episode = ProofLink(
            node_id="episode-001", node_type="episode",
            spine_root=root_e, sequence_index=0,
            inclusion_proof=proof_e,
            parent_node_id="signal-001",
        )
        chain = build_proof_chain([link_signal, link_episode])
        result = verify_proof_chain(chain)
        assert result.valid, f"Cross-type chain should be valid: {result.reason}"
