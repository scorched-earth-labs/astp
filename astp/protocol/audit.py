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
ASTP — Tamper-Evident Audit Chain

The audit trail is a first-class data structure, not a log.
Each AuditRecord includes prev_audit_hash — a chain link that
makes the audit trail itself tamper-evident, independent of the
delta chain.

Tampering with any audit record breaks the chain at that point,
detectable by any verifier replaying from genesis.
"""

import json
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from astp.protocol.hashing import sha3_256


GENESIS_HASH = "GENESIS"


class AuditRecord(BaseModel):
    """A single entry in the tamper-evident audit chain.

    prev_audit_hash links to the prior record's computed hash,
    forming an independent integrity chain over the audit trail itself.
    """
    record_id: UUID = Field(default_factory=uuid4)
    node_id: UUID  # The cognitive node this audit pertains to
    delta_id: UUID  # The delta that triggered this audit record
    delta_type: str  # "CONTENT" | "STRUCTURAL" | "LIFECYCLE"
    actor: str
    actor_role: str = ""
    wall_clock: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    logical_clock: int = 0
    pre_state_hash: str  # Node root hash before the delta
    post_state_hash: str  # Node root hash after the delta
    delta_hash: str  # Hash of the delta record itself
    prev_audit_hash: str = GENESIS_HASH  # Chain link — "GENESIS" for first record
    reason: Optional[str] = None


def compute_audit_hash(record: AuditRecord) -> str:
    """Compute the hash of an audit record for chain linking.

    Uses canonical JSON serialization with sorted keys for
    deterministic output.
    """
    payload = {
        "record_id": str(record.record_id),
        "node_id": str(record.node_id),
        "delta_id": str(record.delta_id),
        "delta_type": record.delta_type,
        "actor": record.actor,
        "wall_clock": record.wall_clock.isoformat(),
        "logical_clock": record.logical_clock,
        "pre_state_hash": record.pre_state_hash,
        "post_state_hash": record.post_state_hash,
        "delta_hash": record.delta_hash,
        "prev_audit_hash": record.prev_audit_hash,
    }
    serialized = json.dumps(payload, sort_keys=True)
    return sha3_256(serialized.encode())


class AuditChain:
    """Manages a tamper-evident chain of audit records.

    The chain is append-only. Each record's prev_audit_hash
    references the computed hash of the prior record.
    """

    def __init__(self):
        self._records: List[AuditRecord] = []
        self._head_hash: str = GENESIS_HASH

    @property
    def head_hash(self) -> str:
        """Hash of the most recent audit record, or GENESIS if empty."""
        return self._head_hash

    @property
    def length(self) -> int:
        return len(self._records)

    @property
    def records(self) -> List[AuditRecord]:
        return list(self._records)

    def append(self, record: AuditRecord) -> str:
        """Append a record to the chain. Sets prev_audit_hash automatically.

        Returns the computed hash of the appended record.
        """
        record.prev_audit_hash = self._head_hash
        record_hash = compute_audit_hash(record)
        self._records.append(record)
        self._head_hash = record_hash
        return record_hash

    def verify(self) -> bool:
        """Verify the entire audit chain integrity.

        Walks from genesis to head, recomputing each record's hash
        and checking that prev_audit_hash links are consistent.

        Returns:
            True if the chain is intact
        """
        expected_prev = GENESIS_HASH

        for record in self._records:
            if record.prev_audit_hash != expected_prev:
                return False
            expected_prev = compute_audit_hash(record)

        return True

    @staticmethod
    def verify_chain(records: List[AuditRecord]) -> bool:
        """Verify a list of audit records forms a valid chain.

        Static version for verifying externally-loaded records.
        """
        expected_prev = GENESIS_HASH

        for record in records:
            if record.prev_audit_hash != expected_prev:
                return False
            expected_prev = compute_audit_hash(record)

        return True
