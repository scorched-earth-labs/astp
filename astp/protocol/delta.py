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
ASTP — Delta Records

Every state transition (segment append, rebalance, seal) is recorded
as a DeltaRecord. The pre_root → post_root chain is the authoritative
truth that makes both coordinator and structural-store state auditable.

Two channels:
  - ContentDelta: segment appends, content updates
  - StructuralDelta: rebalancing, tree shape changes
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ContentDelta(BaseModel):
    """Records a content mutation (segment append or update).

    The sequence_index is included for verification — recomputing
    the leaf hash from (sequence_index, content_hash, ...) must
    produce a hash consistent with the post_root.
    """
    delta_id: UUID = Field(default_factory=uuid4)
    node_id: UUID  # The cognitive node this delta belongs to
    segment_id: UUID  # The segment being appended/modified
    sequence_index: int  # Immutable position — for verification
    previous_content_hash: str  # Content hash before change (empty string for appends)
    new_content_hash: str  # Content hash after change
    pre_root: str  # Spine root before this delta
    post_root: str  # Spine root after this delta
    wall_clock: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    logical_clock: int = 0
    author: str = ""


class StructuralDelta(BaseModel):
    """Records a structural mutation (rebalancing, tree shape change).

    The sequence_indices_unchanged field is an explicit invariant
    assertion. A verifier seeing False knows something has gone
    wrong regardless of hash validity.
    """
    delta_id: UUID = Field(default_factory=uuid4)
    node_id: UUID  # The cognitive node this delta belongs to
    delta_type: str  # "REBALANCE" | "NODE_PROMOTION" | "NODE_DEMOTION"
    sequence_indices_unchanged: bool = True  # INVARIANT — must be True
    pre_rebalance_root: str
    post_rebalance_root: str
    wall_clock: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    logical_clock: int = 0
    author: str = ""


class DeltaRecord(BaseModel):
    """Unified delta record wrapping either content or structural change.

    The pre_root → post_root chain is what makes the system auditable.
    A broken chain (where one record's post_root doesn't match the
    next record's pre_root) indicates tampering or data loss.
    """
    delta_id: UUID = Field(default_factory=uuid4)
    delta_type: str  # "CONTENT" | "STRUCTURAL" | "LIFECYCLE"
    node_id: UUID
    pre_root: str  # The compare-and-swap condition
    post_root: str  # The result being committed
    applied_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    logical_clock: int = 0
    author: str = ""
    content_delta: Optional[ContentDelta] = None
    structural_delta: Optional[StructuralDelta] = None
