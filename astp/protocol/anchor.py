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
Ariadne Protocol v2 — Transparency Log Anchoring

Provides external, independently verifiable proof that a node's
state existed at a specific point in time. Anchoring occurs at
crystallization boundaries (G-14).

The AnchorCommitment contains only protocol-surface data — no
payload internals. The TransparencyLogAdapter is an abstract
interface; implementations provide a concrete adapter for their
chosen log backend.

Per IMPLEMENTATION-PHASE3.md Section 4.
"""

import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from astp.core.schema import sha3_256


class AnchorCommitment(BaseModel):
    """Data submitted to the transparency log at crystallization.

    Contains only protocol-surface fields. No payload internals
    are anchored (TL-002). This is a structural commitment, not
    a content commitment.
    """
    node_id: str
    node_type: str
    workspace_id: str
    crystallization_root: str  # spine_root at crystallization
    crystallization_sequence: int  # sequence_index of last segment
    logical_clock: int
    wall_clock: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    protocol_version: str = "2.3.0"

    def canonical_json(self) -> str:
        """Canonical JSON serialization for commitment hashing.

        Keys in lexicographic order, no whitespace, datetime in
        ISO 8601 UTC (YYYY-MM-DDTHH:MM:SSZ), integers as numbers.
        This serialization is protocol-mandatory (TL-003).
        """
        return json.dumps({
            "crystallization_root": self.crystallization_root,
            "crystallization_sequence": self.crystallization_sequence,
            "logical_clock": self.logical_clock,
            "node_id": self.node_id,
            "node_type": self.node_type,
            "protocol_version": self.protocol_version,
            "wall_clock": self.wall_clock.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "workspace_id": self.workspace_id,
        }, sort_keys=True, separators=(",", ":"))

    def commitment_hash(self) -> str:
        """SHA3-256 of the canonical JSON serialization."""
        return sha3_256(self.canonical_json().encode("utf-8"))


class AnchorReceipt(BaseModel):
    """Receipt from the transparency log after anchor submission."""
    log_id: str  # Identifies the transparency log
    log_entry_id: str  # Log-specific entry identifier
    commitment_hash: str  # SHA3-256 of the AnchorCommitment
    log_timestamp: datetime  # Timestamp assigned by the log
    inclusion_proof: Optional[bytes] = None  # Log's own inclusion proof
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TransparencyLogAdapter(ABC):
    """Abstract interface for transparency log backends.

    Implementations provide a concrete adapter for their chosen
    log technology (Merkle tree append-only log, blockchain,
    RFC 3161 trusted timestamping service, etc.).
    """

    @abstractmethod
    async def submit(self, commitment: AnchorCommitment) -> AnchorReceipt:
        """Submit an anchor commitment. Returns a receipt with log proof.
        MUST be called at crystallization (G-14)."""
        ...

    @abstractmethod
    async def verify(self, receipt: AnchorReceipt) -> bool:
        """Verify that a receipt is valid for its claimed log."""
        ...

    @abstractmethod
    async def retrieve(
        self, node_id: str, crystallization_root: str
    ) -> Optional[AnchorReceipt]:
        """Retrieve a previously submitted receipt by node and root."""
        ...


def build_anchor_commitment(
    node_id: str,
    node_type: str,
    workspace_id: str,
    spine_root: str,
    sequence_index: int,
    logical_clock: int,
    protocol_version: str = "2.3.0",
) -> AnchorCommitment:
    """Factory for building an AnchorCommitment at crystallization.

    The spine_root MUST be the value at crystallization time, not
    a live reference. If post-crystallization spine mutation is
    possible, capture spine_root before any mutation can occur.
    """
    return AnchorCommitment(
        node_id=node_id,
        node_type=node_type,
        workspace_id=workspace_id,
        crystallization_root=spine_root,
        crystallization_sequence=sequence_index,
        logical_clock=logical_clock,
        protocol_version=protocol_version,
    )
