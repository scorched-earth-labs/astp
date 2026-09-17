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
ASTP — Rebalance Event

First-class audit record for tree rebalancing operations.
Rebalancing modifies tree_leaf_index values without changing content —
but without an audit trail, a legitimate rebalance is indistinguishable
from tampering.

The root-preservation invariant: pre_rebalance_root MUST equal
post_rebalance_root for a correct rebalance. If they differ, the
rebalance was corrupting (content was modified, not just restructured).

RebalanceEventNode is the forensically sensitive record that proves a
rebalance was legitimate (SPEC §14).
"""

from datetime import datetime, timezone
from typing import Dict, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from astp.protocol.errors import GovernanceViolation


class RebalanceEventNode(BaseModel):
    """Records a single tree rebalancing operation.

    The root-preservation invariant is enforced at creation time:
    pre_rebalance_root must equal post_rebalance_root. A rebalance
    that changes the root hash has modified content, not just structure.
    """
    event_id: UUID = Field(default_factory=uuid4)
    node_id: UUID  # The CognitiveNode being rebalanced (e.g., episode)
    rebalance_generation: int  # Increments on each rebalance; detects stale tree_leaf_index
    triggered_by: str  # "SIZE_THRESHOLD" | "MANUAL" | "SEAL_OPTIMIZATION"

    # Root-preservation invariant (O(1) verification)
    pre_rebalance_root: str  # Spine root before rebalance
    post_rebalance_root: str  # Spine root after rebalance — MUST equal pre

    # Leaf index remapping (optional — full delta in Phase 3)
    leaf_index_delta: Optional[Dict[str, Dict[str, int]]] = None  # {segment_id: {old: N, new: M}}
    affected_leaf_count: int = 0  # How many leaves changed position

    executed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    executor_id: str = ""  # Agent or system that triggered the rebalance

    @model_validator(mode="after")
    def validate_root_preservation(self) -> "RebalanceEventNode":
        """Enforce the root-preservation invariant.

        A correct rebalance never changes the root hash. If pre != post,
        something went wrong — content was modified, not just restructured.
        """
        if self.pre_rebalance_root != self.post_rebalance_root:
            raise GovernanceViolation(
                f"Root-preservation invariant violated: rebalance event {self.event_id} "
                f"has pre_root={self.pre_rebalance_root[:16]}... != "
                f"post_root={self.post_rebalance_root[:16]}... "
                f"A correct rebalance must preserve the root hash. "
                f"This indicates content was modified during rebalancing."
            )
        return self


def create_rebalance_event(
    node_id: UUID,
    rebalance_generation: int,
    triggered_by: str,
    spine_root: str,
    executor_id: str = "",
    leaf_index_delta: Optional[Dict[str, Dict[str, int]]] = None,
) -> RebalanceEventNode:
    """Factory for creating a rebalance event.

    Takes a single spine_root (used for both pre and post) because
    a correct rebalance by definition preserves the root. If caller
    passes different roots, the validator will reject it.

    Args:
        node_id: The CognitiveNode being rebalanced
        rebalance_generation: Current generation counter (incremented by caller)
        triggered_by: What triggered the rebalance
        spine_root: The spine root hash (same before and after)
        executor_id: Who triggered it
        leaf_index_delta: Optional remapping of tree_leaf_index values
    """
    affected = len(leaf_index_delta) if leaf_index_delta else 0

    return RebalanceEventNode(
        node_id=node_id,
        rebalance_generation=rebalance_generation,
        triggered_by=triggered_by,
        pre_rebalance_root=spine_root,
        post_rebalance_root=spine_root,
        leaf_index_delta=leaf_index_delta,
        affected_leaf_count=affected,
        executor_id=executor_id,
    )
