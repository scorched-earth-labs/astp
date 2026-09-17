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
Ariadne Protocol v2 — Retrieval Audit Record

Side-channel record of every agent retrieval operation. This is the
read-path observability complement: WIL tracks writes, retrieval
audit tracks reads.

RetrievalAuditRecord is NOT a delta — reads don't change state.
It has no pre/post state hashes, no delta_id. It records what an
agent saw, when, and through which snapshot boundary.

Per SPEC.md Section 11 (Side-Effect Contract): retrieval audit
records are side-channel data. They MUST NOT be included in any
hash computation (content_hash, leaf_hash, spine_root).
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from astp.core.schema import sha3_256


class RetrievalAuditRecord(BaseModel):
    """Records a single agent retrieval operation.

    Created after each successful retrieval tool call. Stored on
    separate AriadneRetrievalAudit nodes in Neo4j — never on
    segment nodes, never in any hash preimage.
    """
    record_id: UUID = Field(default_factory=uuid4)
    episode_id: str
    actor: str  # agent_id performing the retrieval
    tool_name: str  # retrieve_episode_segment | retrieve_segment_range | retrieve_recent_episode_context
    parameters: Dict[str, Any] = Field(default_factory=dict)
    segment_count: int = 0
    segment_ids: List[str] = Field(default_factory=list)
    snapshot_index: Optional[int] = None  # spine snapshot boundary at retrieval time
    wall_clock: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": str(self.record_id),
            "episode_id": self.episode_id,
            "actor": self.actor,
            "tool_name": self.tool_name,
            "parameters": self.parameters,
            "segment_count": self.segment_count,
            "segment_ids": self.segment_ids,
            "snapshot_index": self.snapshot_index,
            "wall_clock": self.wall_clock.isoformat(),
        }


def compute_retrieval_audit_hash(record: RetrievalAuditRecord) -> str:
    """Hash of a retrieval audit record for chain linking.

    Note: this hash is for audit chain integrity only — it is
    never included in any spine or episode hash computation.
    """
    payload = {
        "record_id": str(record.record_id),
        "episode_id": record.episode_id,
        "actor": record.actor,
        "tool_name": record.tool_name,
        "segment_count": record.segment_count,
        "snapshot_index": record.snapshot_index,
        "wall_clock": record.wall_clock.isoformat(),
    }
    return sha3_256(json.dumps(payload, sort_keys=True).encode())
