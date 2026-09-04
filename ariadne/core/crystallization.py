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
CRYSTALLIZATION_DELTA — first-class spine event for Ariadne episode chains.

Protocol-level definitions: models, enums, hash construction, version vectors,
governance guards. Database-agnostic — no persistence operations.

Architectural decision: OQ-D02 (2026-03-08)
Decision: Crystallization is a state transition IN the chain, not a receipt ABOUT it.

Spec 7 of Phase 2 Ariadne Persistence Layer.
Source: OQ-D02 Resolution, CLO-CONSOLIDATED-1.1 S5.5-5.7.
"""

import json
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from ariadne.core.schema import (
    ARIADNE_SCHEMA_VERSION,
    AriadneGovernanceError,
    EpisodeStatus,
    compute_spine_hash,
    sha3_256,
)

logger = logging.getLogger(__name__)


# ── Enums ─────────────────────────────────────────────────────────────────────

class CrystallizationScope(str, Enum):
    EPISODE = "EPISODE"  # Crystallizes a single episode
    BRANCH = "BRANCH"    # Crystallizes a branch before merge
    SPINE = "SPINE"      # Crystallizes the full spine chain


class DeltaType(str, Enum):
    APPEND = "APPEND"
    MODIFY = "MODIFY"
    BRANCH = "BRANCH"
    MERGE = "MERGE"
    CRYSTALLIZATION = "CRYSTALLIZATION"
    ARCHIVE = "ARCHIVE"
    EXPIRY = "EXPIRY"


# ── Version Tracking ─────────────────────────────────────────────────────────

class EpisodeVersionVector(BaseModel):
    """
    Three-layer versioning per OQ-D02 resolution.

    content_version:   increments on APPEND, MODIFY, BRANCH, MERGE
    lifecycle_version: increments on CRYSTALLIZATION, ARCHIVE, EXPIRY
    chain_version:     increments on ALL deltas (spine position)

    Crystallization increments lifecycle_version and chain_version only.
    It does NOT increment content_version — episode content is unchanged.
    """
    content_version: int = 0
    lifecycle_version: int = 0
    chain_version: int = 0  # Merkle spine position of this delta

    def increment_for_delta(self, delta_type: DeltaType) -> "EpisodeVersionVector":
        """Returns a new vector with appropriate fields incremented."""
        content = self.content_version
        lifecycle = self.lifecycle_version
        chain = self.chain_version + 1  # always increments

        if delta_type in (DeltaType.APPEND, DeltaType.MODIFY,
                          DeltaType.BRANCH, DeltaType.MERGE):
            content += 1
        elif delta_type in (DeltaType.CRYSTALLIZATION,
                            DeltaType.ARCHIVE, DeltaType.EXPIRY):
            lifecycle += 1

        return EpisodeVersionVector(
            content_version=content,
            lifecycle_version=lifecycle,
            chain_version=chain,
        )


# ── CrystallizationContent ──────────────────────────────────────────────────

class CrystallizationContent(BaseModel):
    """
    The content payload of a CRYSTALLIZATION_DELTA node.

    predecessor_hash and sealed_chain_root serve distinct semantic purposes:
    - predecessor_hash is a causal link (what came immediately before)
    - sealed_chain_root is an integrity assertion (what the whole chain looks like)
    In a re-crystallization scenario these will diverge; that divergence is
    meaningful audit data and must be preserved, not collapsed.
    """
    predecessor_hash: str           # SHA3-256 of terminal delta before this node
    sealed_chain_root: str          # Merkle root of [D1..DN]
    verification_timestamp: datetime
    verification_authority: str     # agent_id that triggered crystallization
    schema_version: str             # Schema version at crystallization time
    crystallization_scope: CrystallizationScope
    successor_episode_id: Optional[str] = None  # For BRANCH scope: parent episode


# ── CrystallizationDeltaNode ────────────────────────────────────────────────

class CrystallizationDeltaNode(BaseModel):
    """
    CRYSTALLIZATION_DELTA — first-class spine event.
    Structural analogy: blockchain block header.
    """
    delta_id: UUID = Field(default_factory=uuid4)
    episode_id: UUID
    delta_type: DeltaType = DeltaType.CRYSTALLIZATION
    chain_position: int  # Strictly > any prior CRYSTALLIZATION_DELTA
    content: CrystallizationContent
    content_hash: str    # SHA3-256 of serialized CrystallizationContent
    node_hash: str       # SHA3-256 of (b'LEAF:' + content_hash + predecessor_hash)
    version_vector: EpisodeVersionVector
    immutable: bool = True  # Always True; enforced at write time
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @model_validator(mode="after")
    def validate_immutability_flag(self) -> "CrystallizationDeltaNode":
        if not self.immutable:
            raise ValueError(
                "CrystallizationDeltaNode.immutable must always be True. "
                "Crystallization nodes are immutable by architectural requirement."
            )
        return self

    @model_validator(mode="after")
    def validate_delta_type(self) -> "CrystallizationDeltaNode":
        if self.delta_type != DeltaType.CRYSTALLIZATION:
            raise ValueError(
                "CrystallizationDeltaNode.delta_type must be CRYSTALLIZATION."
            )
        return self


# ── Hash Construction ────────────────────────────────────────────────────────

def compute_crystallization_content_hash(content: CrystallizationContent) -> str:
    """SHA3-256 of the serialized CrystallizationContent (canonical JSON)."""
    payload = {
        "predecessor_hash": content.predecessor_hash,
        "sealed_chain_root": content.sealed_chain_root,
        "verification_timestamp": content.verification_timestamp.isoformat(),
        "verification_authority": content.verification_authority,
        "schema_version": content.schema_version,
        "crystallization_scope": content.crystallization_scope.value,
        "successor_episode_id": content.successor_episode_id,
    }
    serialized = json.dumps(payload, sort_keys=True)
    return sha3_256(serialized.encode())


def compute_crystallization_node_hash(content_hash: str, predecessor_hash: str) -> str:
    """
    node_hash = SHA3-256(b'LEAF:' + content_hash + predecessor_hash)
    No self-reference — predecessor_hash is hN, not this node's own hash.
    """
    return sha3_256(
        b"LEAF:" +
        content_hash.encode() +
        predecessor_hash.encode()
    )


def build_crystallization_delta(
    episode_id: UUID,
    predecessor_hash: str,
    sealed_chain_root: str,
    verification_authority: str,
    chain_position: int,
    version_vector: EpisodeVersionVector,
    schema_version: str = "1.0.0",
    crystallization_scope: CrystallizationScope = CrystallizationScope.EPISODE,
    successor_episode_id: Optional[str] = None,
) -> CrystallizationDeltaNode:
    """
    Factory function — the only sanctioned way to create a crystallization delta.
    Caller must ensure CRYSTALLIZATION_PENDING lock is held before calling.
    """
    now = datetime.now(timezone.utc)
    content = CrystallizationContent(
        predecessor_hash=predecessor_hash,
        sealed_chain_root=sealed_chain_root,
        verification_timestamp=now,
        verification_authority=verification_authority,
        schema_version=schema_version,
        crystallization_scope=crystallization_scope,
        successor_episode_id=successor_episode_id,
    )
    content_hash = compute_crystallization_content_hash(content)
    node_hash = compute_crystallization_node_hash(content_hash, predecessor_hash)
    new_version = version_vector.increment_for_delta(DeltaType.CRYSTALLIZATION)

    return CrystallizationDeltaNode(
        episode_id=episode_id,
        chain_position=chain_position,
        content=content,
        content_hash=content_hash,
        node_hash=node_hash,
        version_vector=new_version,
    )


# ── CRYSTALLIZATION_PENDING Lock (Protocol-Level Guards) ────────────────────

class CrystallizationLockError(AriadneGovernanceError):
    """Raised when a write is attempted on an episode with CRYSTALLIZATION_PENDING."""
    pass


def enforce_crystallization_lock_guard(episode_status: str) -> None:
    """
    Called from create_segment_node() and create_signal_node().
    Raises CrystallizationLockError if the episode is CRYSTALLIZATION_PENDING
    or PENDING_HITL (blocking HITL gate requires human decision before
    the episode can advance).

    Note: Only blocking HITL gates (APPROVAL_REQUIRED, COMPLIANCE_CHECKPOINT)
    set PENDING_HITL. Advisory gates leave the episode ACTIVE.
    """
    if episode_status == "CRYSTALLIZATION_PENDING":
        raise CrystallizationLockError(
            "Write rejected: episode is in CRYSTALLIZATION_PENDING state. "
            "No further deltas may be appended until crystallization completes or is rolled back."
        )
    if episode_status == "PENDING_HITL":
        raise CrystallizationLockError(
            "Write rejected: episode is in PENDING_HITL state. "
            "A blocking HITL gate is awaiting human decision. "
            "Resolve the HITL request before appending further deltas."
        )


# ── Immutability Guard ───────────────────────────────────────────────────────

async def attempt_amend_crystallization_delta(driver, delta_id: str, correcting_agent: str) -> None:
    """
    This function always raises. It exists to make the architectural invariant
    explicit. Erroneous crystallizations are corrected via successor episodes,
    not in-place amendment. See OQ-D02 Immutability Governance section.
    """
    raise AriadneGovernanceError(
        f"Immutability violation: CrystallizationDelta {delta_id} cannot be amended. "
        f"Crystallization nodes are immutable by architectural requirement. "
        f"To correct an erroneous crystallization: open a successor episode and "
        f"record a RELATIONSHIP_DELTA that supersedes this crystallization. "
        f"The original record is preserved in the historical chain."
    )


# ── Verification (Protocol-Level Logic) ────────────────────────────────────

class CrystallizationVerificationResult(BaseModel):
    episode_id: str
    delta_id: str
    phase_1_passed: bool  # predecessor_hash matches hN
    phase_2_passed: bool  # chain_root_hash matches reconstructed Merkle root
    verified: bool        # True only if both phases pass
    failure_reason: Optional[str] = None


def verify_crystallization_hashes(
    stored_content_hash: str,
    stored_predecessor_hash: str,
    stored_node_hash: str,
    stored_sealed_chain_root: str,
    segment_content_hashes: list[str],
    spine_signal_hashes: list[str],
    episode_id: str,
    delta_id: str,
) -> CrystallizationVerificationResult:
    """
    Pure protocol-level two-phase verification per OQ-D02.
    Phase 1: predecessor_hash -> node_hash consistency
    Phase 2: sealed_chain_root matches reconstructed Merkle root

    Adapter is responsible for fetching stored values from the database
    and passing them to this function.
    """
    # Phase 1: verify node_hash consistency
    reconstructed_node_hash = compute_crystallization_node_hash(
        stored_content_hash, stored_predecessor_hash
    )
    phase_1 = (reconstructed_node_hash == stored_node_hash)

    # Phase 2: verify sealed_chain_root matches reconstructed Merkle root
    phase_2 = False
    try:
        reconstructed_root = compute_spine_hash(
            segment_content_hashes, spine_signal_hashes
        )
        phase_2 = (reconstructed_root == stored_sealed_chain_root)
    except ValueError:
        pass

    failure_reason = None
    if not phase_1:
        failure_reason = "Phase 1 failed: node_hash does not match recomputed value"
    elif not phase_2:
        failure_reason = "Phase 2 failed: sealed_chain_root does not match reconstructed Merkle root"

    return CrystallizationVerificationResult(
        episode_id=episode_id,
        delta_id=delta_id,
        phase_1_passed=phase_1,
        phase_2_passed=phase_2,
        verified=phase_1 and phase_2,
        failure_reason=failure_reason,
    )


# ── Convenience ──────────────────────────────────────────────────────────────

def compute_spine_hash_for_episode(
    segment_content_hashes: list[str],
    spine_signal_hashes: list[str],
) -> str:
    """Convenience wrapper around compute_spine_hash for episode-level use."""
    return compute_spine_hash(segment_content_hashes, spine_signal_hashes)
