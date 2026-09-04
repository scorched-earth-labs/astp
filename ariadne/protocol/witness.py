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
Ariadne Protocol v2 — Witness Signatures

Multi-party attestation that a node's state was observed and verified.
The witness record includes a cryptographic commitment binding the
witness to a specific spine_root, sequence_index, and role.

WitnessCommitment is pipe-delimited UTF-8, then SHA3-256 hashed.
This format is simpler than JSON and eliminates serialization
ambiguity across architectures.

Per IMPLEMENTATION-PHASE3.md Section 5.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from ariadne.core.schema import sha3_256
from ariadne.protocol.errors import GovernanceViolation


class WitnessRole(str, Enum):
    REVIEWER = "REVIEWER"
    AUDITOR = "AUDITOR"
    COUNTER_SIGNER = "COUNTER_SIGNER"
    OBSERVER = "OBSERVER"
    SEAL_WITNESS = "SEAL_WITNESS"
    CHAIN_ANCHOR = "CHAIN_ANCHOR"
    CUSTOM = "CUSTOM"


def compute_witness_commitment(
    node_id: str,
    node_type: str,
    spine_root: str,
    sequence_index: int,
    logical_clock: int,
    role: str,
) -> str:
    """Compute the WitnessCommitment hash.

    Pipe-delimited UTF-8 string, then SHA3-256. Field order is
    fixed and protocol-mandatory:
      node_id|node_type|spine_root|sequence_index|logical_clock|role

    Integer fields are serialized as decimal strings.

    Args:
        node_id: CognitiveNode identifier
        node_type: Node type string
        spine_root: Hex-encoded spine root being witnessed
        sequence_index: sequence_index at witnessing time
        logical_clock: Logical clock value
        role: WitnessRole value string

    Returns:
        SHA3-256 hex string of the commitment
    """
    preimage = (
        f"{node_id}|{node_type}|{spine_root}|"
        f"{sequence_index}|{logical_clock}|{role}"
    )
    return sha3_256(preimage.encode("utf-8"))


class WitnessRecord(BaseModel):
    """A witness attestation of a specific node state.

    The commitment_hash binds the witness to a specific spine_root,
    sequence_index, and role. The signature is over the commitment_hash.
    """
    witness_id: str  # agent_id of the witness
    node_id: str
    node_type: str
    spine_root: str
    sequence_index: int
    logical_clock: int
    wall_clock: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    role: str  # WitnessRole value
    role_detail: Optional[str] = None  # For CUSTOM role
    commitment_hash: str  # SHA3-256 of WitnessCommitment
    signature: bytes = b""  # Signature over commitment_hash
    public_key_fingerprint: str = ""
    protocol_version: str = "2.3.0"


def verify_witness_commitment(record: WitnessRecord) -> bool:
    """Verify that a WitnessRecord's commitment_hash matches its fields (G-12).

    Recomputes the commitment hash from the record's fields and
    compares to the stored value. Returns False if they don't match.

    This does NOT verify the signature — only the commitment integrity.
    Signature verification requires the witness's public key and is
    implementation-defined.
    """
    expected = compute_witness_commitment(
        node_id=record.node_id,
        node_type=record.node_type,
        spine_root=record.spine_root,
        sequence_index=record.sequence_index,
        logical_clock=record.logical_clock,
        role=record.role,
    )
    return record.commitment_hash == expected


def enforce_witness_threshold(
    witness_records: List[WitnessRecord],
    min_counter_signatures: int,
) -> None:
    """Enforce G-11: require distinct witness_id values meeting threshold.

    Multiple records from the same witness_id count as ONE witness.
    Only records with valid commitment hashes (G-12) are counted.

    Args:
        witness_records: All witness records for the node
        min_counter_signatures: Workspace policy threshold

    Raises:
        GovernanceViolation: If threshold is not met
    """
    # Filter to valid records only (G-12)
    valid_records = [r for r in witness_records if verify_witness_commitment(r)]

    # Count distinct witness_id values
    distinct_witnesses = set(r.witness_id for r in valid_records)

    if len(distinct_witnesses) < min_counter_signatures:
        raise GovernanceViolation(
            f"Witness threshold not met (G-11): "
            f"{len(distinct_witnesses)} distinct valid witnesses, "
            f"threshold requires {min_counter_signatures}."
        )
