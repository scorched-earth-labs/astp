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
Ariadne Branch/Fork/Merge Schema — Phase 1: Branch Lifecycle

Foundation schema types for the branch/fork/merge taxonomy:
- BranchPointNode, BranchTerminusNode — structural nodes
- AuditRecord — tamper-evident audit chain
- AccessPolicy — fail-closed access control
- IntentRecord — concurrent operation guard
- CognitiveDelta payloads — forward + reverse delta records
- Hash functions with domain-separated prefixes
- Governance rules (branch depth limit, access policy enforcement)

Build rule: no function ships without all three writes present
(structural node + cognitive delta + audit record).

Spec reference: Ariadne Branch/Fork/Merge Build Specification v1.0
Issued by: Clotho, Suite Lead — Ariadne State Tree Protocol
"""

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from ariadne.core.drift_fsm import DriftDetectionState

from pydantic import BaseModel, Field

from ariadne.core.schema import sha3_256, AriadneGovernanceError, ARIADNE_SCHEMA_VERSION


# ============================================================================
# Enums
# ============================================================================


class BranchType(str, Enum):
    """Classification of why a branch was created."""
    EXPLORATORY = "exploratory"     # What-if scenario
    TOPIC_SHIFT = "topic_shift"     # New topic within episode
    CORRECTIVE = "corrective"       # Fixing a wrong direction
    PARALLEL = "parallel"           # Concurrent work streams


class BranchDeclarationType(str, Enum):
    """How the branch was declared."""
    EXPLICIT = "explicit"           # Declared at creation time
    INFERRED = "inferred"           # System-detected via coherence fingerprint
    RETROACTIVE = "retroactive"     # Declared after the fact (the Clotho case)


class BranchTerminusType(str, Enum):
    """How a branch was terminated."""
    ABANDONED = "abandoned"         # Branch terminated without merge
    MERGED = "merged"               # Branch merged back to target


class CognitiveDeltaType(str, Enum):
    """Types of cognitive state transitions recorded in the audit chain."""
    # Phase 1 — Branch Lifecycle
    BRANCH_CREATED = "BRANCH_CREATED"
    BRANCH_ABANDONED = "BRANCH_ABANDONED"
    # Phase 2 — Resolution Primitives (registered now, implemented later)
    FORK_CREATED = "FORK_CREATED"
    FORK_RESOLVED = "FORK_RESOLVED"
    MERGE_EXECUTED = "MERGE_EXECUTED"
    # Phase D — Departure Fork Lifecycle (single directional departure, origin continues)
    DEPARTURE_FORK_CREATED = "DEPARTURE_FORK_CREATED"
    DEPARTURE_FORK_COMPLETED = "DEPARTURE_FORK_COMPLETED"
    DEPARTURE_FORK_ABANDONED = "DEPARTURE_FORK_ABANDONED"
    DEPARTURE_FORK_RETURNED = "DEPARTURE_FORK_RETURNED"
    # Phase 3 — Social/Internal Primitives
    ASIDE_OPENED = "ASIDE_OPENED"
    ASIDE_CLOSED = "ASIDE_CLOSED"
    SOLILOQUY_INITIATED = "SOLILOQUY_INITIATED"
    SOLILOQUY_CONCLUDED = "SOLILOQUY_CONCLUDED"
    # Amendment v2.0 — Cross-Episode Linking. LINK_ACCEPTED fires on every
    # link assertion (whether human-asserted or auto-accepted from
    # discovery above AUTO_ACCEPT_THRESHOLD). LINK_PROPOSED fires when
    # discovery surfaces a candidate ≥ DISCOVERY_THRESHOLD for human
    # review. LINK_REJECTED fires when a human rejects a proposed
    # candidate. CANDIDATE_REJECTED fires when discovery scores a
    # candidate BELOW DISCOVERY_THRESHOLD — recorded for calibration
    # tuning (§1 calibration narrative).
    LINK_PROPOSED = "LINK_PROPOSED"
    LINK_ACCEPTED = "LINK_ACCEPTED"
    LINK_REJECTED = "LINK_REJECTED"
    CANDIDATE_REJECTED = "CANDIDATE_REJECTED"
    # Amendment v2.0 — Episode Grouping. Per §11.4 consolidated audit
    # registry: MEMBERSHIP_RECORD_CREATED fires on every new MembershipRecord
    # (whether initial or succession). MEMBERSHIP_RECORD_SUPERSEDED fires
    # additionally when the new record supersedes a prior — both events
    # describe one operation from different angles. DECLARATION_VERSION_BUMPED
    # fires on compatible (minor/patch) version bumps; DECLARATION_SUPERSEDED
    # on breaking (major) version bumps.
    MEMBERSHIP_RECORD_CREATED = "MEMBERSHIP_RECORD_CREATED"
    MEMBERSHIP_RECORD_SUPERSEDED = "MEMBERSHIP_RECORD_SUPERSEDED"
    DECLARATION_VERSION_BUMPED = "DECLARATION_VERSION_BUMPED"
    DECLARATION_SUPERSEDED = "DECLARATION_SUPERSEDED"
    # Amendment v3.0 — Layer 3 Codification (Workflow & Execution DAG).
    # Per §11 audit event registry: WORKFLOW_DECLARED fires on every
    # WorkflowDeclaration creation. EXECUTION_RECORDED fires on every
    # ExecutionNode creation (and is the wire-tier signal that the
    # workflow's auto-transition DECLARED → IN_PROGRESS occurred on the
    # first such write). SKILL_INVOKED fires on every SkillInvocation
    # creation. WORKFLOW_CLOSED fires on every transition of
    # WorkflowDeclaration.status into a terminal state (COMPLETED,
    # FAILED, INTERRUPTED) via the close operation. Every Layer 3
    # audit event MUST carry the cia_identifier of the workspace's
    # designated Cognitive Implementation Authority for the node type
    # being written (§3 sole-writer principle, §11 audit chain
    # integrity).
    WORKFLOW_DECLARED = "WORKFLOW_DECLARED"
    EXECUTION_RECORDED = "EXECUTION_RECORDED"
    SKILL_INVOKED = "SKILL_INVOKED"
    WORKFLOW_CLOSED = "WORKFLOW_CLOSED"


class TriggerType(str, Enum):
    """What triggered the state transition."""
    HUMAN_EXPLICIT = "human_explicit"           # User declared the branch
    AGENT_DETECTED = "agent_detected"           # Agent detected coherence drift
    SYSTEM_AUTOMATIC = "system_automatic"       # System-level detection
    RETROACTIVE_DECLARATION = "retroactive"     # Declared after the fact


class AccessResourceType(str, Enum):
    """Resource types for access policy."""
    BRANCH = "BRANCH"
    FORK = "FORK"
    ASIDE = "ASIDE"
    SOLILOQUY = "SOLILOQUY"


class AccessLevel(str, Enum):
    """Access levels for agents."""
    ALWAYS = "ALWAYS"
    OPEN = "OPEN"
    ESCALATION_ONLY = "ESCALATION_ONLY"
    BLOCKED = "BLOCKED"


class IntentStatus(str, Enum):
    """Status of an intent record."""
    PENDING = "PENDING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class IntentType(str, Enum):
    """Types of intents that can be acquired."""
    CREATE_BRANCH = "CREATE_BRANCH"
    CREATE_FORK = "CREATE_FORK"
    CREATE_DEPARTURE_FORK = "CREATE_DEPARTURE_FORK"
    MERGE = "MERGE"
    ABANDON_BRANCH = "ABANDON_BRANCH"


# ============================================================================
# Delta Payloads
# ============================================================================


class BranchCreatedDelta(BaseModel):
    """Forward + reverse delta for BRANCH_CREATED."""
    # Forward delta (what happened)
    parent_node_id: str
    branch_id: str
    branch_type: BranchType
    trigger_context: TriggerType
    declaration_type: BranchDeclarationType
    # Reverse delta (how to undo)
    reverse_delete_branch_id: str
    reverse_restore_parent_cursor: str


class BranchAbandonedDelta(BaseModel):
    """Forward + reverse delta for BRANCH_ABANDONED."""
    # Forward delta
    branch_id: str
    abandon_reason: str
    final_state_snapshot: str     # Merkle root at abandonment
    # Reverse delta
    reverse_restore_branch_to_active: str
    reverse_clear_abandon_record: str


# ============================================================================
# Node Models
# ============================================================================


class BranchPointNode(BaseModel):
    """Created by create_branch() — marks where a branch diverges from the spine.

    BranchPointNode is immutable after creation. Lifecycle state is DERIVED
    from the presence or absence of a matching BranchTerminusNode.
    """
    branch_point_id: UUID = Field(default_factory=uuid4)
    episode_id: UUID
    branch_id: UUID = Field(default_factory=uuid4)  # Stable branch identifier
    branch_label: str                                # Human-readable intent
    parent_episode_id: UUID                          # Spine episode this branches from
    source_segment_id: str                           # Exact divergence point
    branch_type: BranchType
    branch_depth: int = 0                            # 0=spine, 1=first branch, max 4 (soft)
    declaration_type: BranchDeclarationType
    trigger_context: TriggerType
    initiated_by: str                                # AgentID or UserID
    spine_merkle_snapshot: str                        # Merkle root at branch point
    content_hash: str = ""                           # Computed after creation
    parent_hash: str = ""                            # Hash of preceding spine node
    timestamp_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = ARIADNE_SCHEMA_VERSION

    # Retroactive declaration fields (only populated when declaration_type=RETROACTIVE)
    pre_declaration_merkle_root: Optional[str] = None
    declared_retroactively_at: Optional[datetime] = None
    declared_by: Optional[str] = None


class BranchTerminusNode(BaseModel):
    """Created by abandon_branch() or execute_merge() — marks branch end.

    Terminal node — once created, the branch cannot be reopened.
    """
    terminus_id: UUID = Field(default_factory=uuid4)
    episode_id: UUID
    branch_id: UUID                                  # Matches originating BranchPoint
    terminus_type: BranchTerminusType
    branch_point_hash: str                           # Hash of originating BranchPoint (integrity link)
    final_merkle_root: str                           # Branch state at terminus
    duration_ms: int = 0                             # Branch lifespan
    timestamp_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = ARIADNE_SCHEMA_VERSION

    # Abandonment fields (populated when terminus_type=ABANDONED)
    abandonment_reason: Optional[str] = None

    # Merge fields (populated when terminus_type=MERGED, Phase 2)
    merge_target_id: Optional[str] = None
    merge_delta: Optional[Dict[str, Any]] = None


# ============================================================================
# Audit Record
# ============================================================================


class AuditRecord(BaseModel):
    """Tamper-evident audit chain entry.

    Append-only. No record is ever mutated after write. Rollback creates
    a new forward record — it does not erase history.
    """
    audit_id: UUID = Field(default_factory=uuid4)
    delta_sequence: int                              # Global monotonic integer, never resets

    # Who
    agent_id: str
    session_id: str
    human_actor: Optional[str] = None                # HumanIdentifier if human-initiated

    # When
    wall_clock_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    episode_time: int = 0                            # Logical clock value

    # What
    delta_type: CognitiveDeltaType
    forward_delta: Dict[str, Any] = Field(default_factory=dict)
    reverse_delta: Dict[str, Any] = Field(default_factory=dict)
    affected_nodes: List[str] = Field(default_factory=list)

    # Why
    trigger_context: TriggerType
    explicit_reason: Optional[str] = None

    # Integrity
    prior_audit_hash: str = "GENESIS"                # SHA3-256 of prior AuditRecord
    record_hash: str = ""                            # SHA3-256 of this record

    # Detection metadata
    caught_by: str = "SYSTEM"                        # AGENT | HUMAN | SYSTEM | UNCAUGHT
    detection_window_open: bool = False

    # Episode reference
    episode_id: str = ""
    schema_version: str = ARIADNE_SCHEMA_VERSION


# ============================================================================
# Access Policy
# ============================================================================


class AccessPolicy(BaseModel):
    """Access control for branch/fork/aside/soliloquy resources.

    Enforcement rule: fail-closed. If the policy check cannot be completed,
    access is denied. Every denial writes an AuditRecord.
    """
    policy_id: UUID = Field(default_factory=uuid4)
    resource_type: AccessResourceType
    resource_id: str
    owner_agent_id: str

    # Read policy
    human_read: str = "ALWAYS"
    owner_agent_read: str = "ALWAYS"
    other_agents_read: AccessLevel = AccessLevel.OPEN

    # Write policy
    owner_agent_write: str = "ALWAYS"
    other_agents_write: AccessLevel = AccessLevel.BLOCKED

    # Governance
    escalation_path: Optional[str] = None
    audit_on_access: bool = False

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# Default policies by resource type
DEFAULT_ACCESS_POLICIES = {
    AccessResourceType.BRANCH: {"other_agents_read": AccessLevel.OPEN, "audit_on_access": False},
    AccessResourceType.FORK: {"other_agents_read": AccessLevel.OPEN, "audit_on_access": False},
    AccessResourceType.ASIDE: {"other_agents_read": AccessLevel.OPEN, "audit_on_access": False},
    AccessResourceType.SOLILOQUY: {"other_agents_read": AccessLevel.ESCALATION_ONLY, "audit_on_access": True},
}


# ============================================================================
# Intent Record
# ============================================================================


class IntentRecord(BaseModel):
    """Prevents concurrent branch creation conflicts.

    Usage: acquire intent before creating a branch. If an intent with the
    same idempotency_key already exists and is COMPLETE, return the existing
    result (idempotent). If PENDING, wait or fail.
    """
    intent_id: UUID = Field(default_factory=uuid4)
    intent_type: IntentType
    idempotency_key: str                             # SHA3-256(source_episode_id + source_segment_id + intent_hash)
    initiator_id: str
    status: IntentStatus = IntentStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    result_node_id: Optional[str] = None             # Populated on COMPLETE


# ============================================================================
# Result Types
# ============================================================================


class BranchResult(BaseModel):
    """Result of create_branch()."""
    branch_episode_id: str
    branch_point_id: str
    branch_id: str
    spine_merkle_snapshot: str
    delta_id: str
    audit_record_id: str
    lifecycle_state: str = "ACTIVE"


class AbandonResult(BaseModel):
    """Result of abandon_branch()."""
    episode_id: str
    branch_id: str
    final_merkle_root: str
    terminus_id: str
    delta_id: str
    audit_record_id: str
    lifecycle_state: str = "ABANDONED"
    artifacts_preserved: List[str] = Field(default_factory=list)


# ============================================================================
# Hash Functions
# ============================================================================


def compute_branch_point_hash(
    branch_point_id: str,
    episode_id: str,
    branch_id: str,
    source_segment_id: str,
    branch_type: str,
    declaration_type: str,
    initiated_by: str,
    timestamp: str,
    parent_hash: str,
) -> str:
    """Compute the content hash of a BranchPointNode.

    Domain separation prefix: BRANCH_POINT:
    """
    preimage = (
        f"{branch_point_id}:{episode_id}:{branch_id}:{source_segment_id}:"
        f"{branch_type}:{declaration_type}:{initiated_by}:{timestamp}:{parent_hash}"
    )
    return sha3_256(b"BRANCH_POINT:" + preimage.encode())


def compute_branch_terminus_hash(
    terminus_id: str,
    branch_id: str,
    terminus_type: str,
    branch_point_hash: str,
    final_merkle_root: str,
    timestamp: str,
) -> str:
    """Compute the content hash of a BranchTerminusNode.

    Domain separation prefix: BRANCH_TERMINUS:
    """
    preimage = (
        f"{terminus_id}:{branch_id}:{terminus_type}:"
        f"{branch_point_hash}:{final_merkle_root}:{timestamp}"
    )
    return sha3_256(b"BRANCH_TERMINUS:" + preimage.encode())


def compute_audit_record_hash(
    audit_id: str,
    delta_sequence: int,
    delta_type: str,
    agent_id: str,
    wall_clock_time: str,
    forward_delta_json: str,
    prior_audit_hash: str,
) -> str:
    """Compute the tamper-evident hash of an AuditRecord.

    Domain separation prefix: AUDIT:
    Chain integrity: prior_audit_hash links to previous record.
    """
    preimage = (
        f"{audit_id}:{delta_sequence}:{delta_type}:{agent_id}:"
        f"{wall_clock_time}:{forward_delta_json}:{prior_audit_hash}"
    )
    return sha3_256(b"AUDIT:" + preimage.encode())


def compute_intent_idempotency_key(
    source_episode_id: str,
    source_segment_id: str,
    intent_hash: str,
) -> str:
    """Compute the idempotency key for an intent record.

    Prevents concurrent creation of the same branch.
    """
    preimage = f"{source_episode_id}:{source_segment_id}:{intent_hash}"
    return sha3_256(b"INTENT:" + preimage.encode())


# ============================================================================
# Governance Rules
# ============================================================================


def enforce_branch_depth_limit(
    current_depth: int,
    max_depth: int = 4,
) -> None:
    """Enforce soft limit on branch nesting depth.

    Raises AriadneGovernanceError if depth exceeds max_depth.
    The limit is soft — callers may catch and log the override.
    """
    if current_depth >= max_depth:
        raise AriadneGovernanceError(
            f"Branch depth limit exceeded: depth={current_depth}, "
            f"max={max_depth}. Override requires explicit logging."
        )


def enforce_access_policy(
    policy: AccessPolicy,
    requesting_agent_id: str,
    access_type: str = "read",
) -> bool:
    """Check access policy. Fail-closed: returns False if policy cannot be evaluated.

    Args:
        policy: The access policy for the resource
        requesting_agent_id: Who is requesting access
        access_type: "read" or "write"

    Returns:
        True if access is granted, False if denied
    """
    if requesting_agent_id == policy.owner_agent_id:
        return True

    if access_type == "read":
        return policy.other_agents_read in (AccessLevel.ALWAYS, AccessLevel.OPEN)
    elif access_type == "write":
        return policy.other_agents_write in (AccessLevel.ALWAYS, AccessLevel.OPEN)

    return False  # Fail-closed


def enforce_abandonment_reason_required(reason: Optional[str]) -> None:
    """Abandonment reason must be non-empty."""
    if not reason or not reason.strip():
        raise AriadneGovernanceError(
            "Branch abandonment requires a non-empty reason. "
            "ABANDONED is terminal — the reason is the audit trail."
        )




# ============================================================================
# Phase 2 — Resolution Primitives
# ============================================================================


class MergeType(str, Enum):
    """Classification of how a merge resolved."""
    CLEAN = "CLEAN"         # No conflicts
    RESOLVED = "RESOLVED"   # Conflicts present but all resolved
    PARTIAL = "PARTIAL"     # Some conflicts deferred


class MergeStrategy(str, Enum):
    """How execute_merge should handle conflicts."""
    AUTO = "AUTO"                           # Never resolves conflicts silently — returns manifest
    MANUAL_REVIEW = "MANUAL_REVIEW"         # Human must supply all resolutions
    AGENT_RESOLVED = "AGENT_RESOLVED"       # Agent-supplied resolutions
    CONCLUSION_ONLY = "CONCLUSION_ONLY"     # Merge only the branch's synthesis, not every segment


class ForkResolutionOutcome(str, Enum):
    """Outcome of a fork resolution."""
    PROMOTED = "PROMOTED"         # Selected branch promoted back to spine
    ABANDONED = "ABANDONED"       # Discarded forks abandoned


# ============================================================================
# Phase 2 — Delta Payloads
# ============================================================================


class ForkCreatedDelta(BaseModel):
    """Forward + reverse delta for FORK_CREATED."""
    origin_episode_id: str
    origin_segment_id: str
    fork_id: str
    fork_objective: str
    fork_intent: str
    fork_point_ids: List[str]
    carried_artifacts: List[str] = Field(default_factory=list)
    # Reverse
    reverse_delete_fork_id: str
    reverse_delete_fork_point_ids: List[str]


class ForkResolvedDelta(BaseModel):
    """Forward + reverse delta for FORK_RESOLVED."""
    fork_id: str
    selected_fork_point_id: str
    discarded_fork_point_ids: List[str]
    resolution_rationale: str
    # Reverse
    reverse_restore_discarded: List[str]
    reverse_clear_resolution: str


class MergeExecutedDelta(BaseModel):
    """Forward + reverse delta for MERGE_EXECUTED."""
    source_episode_id: str
    target_episode_id: str
    merge_id: str
    merge_type: MergeType
    merge_map: Dict[str, Any] = Field(default_factory=dict)
    conflict_resolutions: List[Dict[str, Any]] = Field(default_factory=list)
    source_merkle_root: str
    target_merkle_root_pre: str
    target_merkle_root_post: str
    # Reverse
    reverse_split_to_source_branches: List[str]
    reverse_clear_merge_record: str


# ============================================================================
# Phase 2 — Node and Edge Models
# ============================================================================


class ForkPointNode(BaseModel):
    """Created by create_fork() — one node per fork branch.

    Forks differ from branches: a fork produces a new Episode with a
    distinct objective. A single create_fork() call typically writes
    N ForkPointNodes (one per alternative path).
    """
    fork_point_id: UUID = Field(default_factory=uuid4)
    fork_id: UUID                                     # Shared across sibling fork points
    episode_id: UUID                                   # New forked episode ID
    origin_episode_id: UUID                            # Episode the fork originated from
    origin_segment_id: str                             # Provenance anchor
    fork_objective: str                                # New Episode's objective
    fork_intent: str                                   # Why a fork, not a branch
    carried_artifacts: List[str] = Field(default_factory=list)
    initiator: str
    participants: List[str] = Field(default_factory=list)
    sibling_count: int = 1                             # Total forks created in this call
    sibling_index: int = 0                             # Position among siblings
    content_hash: str = ""
    parent_hash: str = ""
    timestamp_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = ARIADNE_SCHEMA_VERSION


class MergePointNode(BaseModel):
    """Created by execute_merge() — records the three-way merge on the target spine.

    Contains all three Merkle roots for integrity verification:
    source (branch state at merge), target_pre (spine before merge),
    target_post (spine after merge, must match recomputed value).
    """
    merge_point_id: UUID = Field(default_factory=uuid4)
    merge_id: UUID = Field(default_factory=uuid4)
    source_episode_id: str
    source_branch_id: str
    target_episode_id: str
    merge_type: MergeType
    source_merkle_root: str
    target_merkle_root_pre: str
    target_merkle_root_post: str
    common_ancestor_id: str
    conflict_segments: List[str] = Field(default_factory=list)
    resolution_artifacts: List[str] = Field(default_factory=list)
    merge_coherence_delta: float = 0.0
    merge_summary: str = ""
    initiator: str
    content_hash: str = ""
    parent_hash: str = ""
    timestamp_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = ARIADNE_SCHEMA_VERSION


class BranchReturnEdge(BaseModel):
    """Connects BranchTerminus (MERGED) to the merge target spine.

    Edge written at the same time as the MergePointNode.
    """
    edge_id: UUID = Field(default_factory=uuid4)
    branch_id: str
    terminus_id: str
    merge_point_id: str
    target_episode_id: str
    synthesis_summary: str = ""
    nodes_integrated: int = 0
    timestamp_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================================
# Phase 2 — Conflict Manifest
# ============================================================================


class ConflictSegment(BaseModel):
    """A single conflict surfaced by three-way merge."""
    segment_id: str
    ancestor_content_hash: str
    source_content_hash: str
    target_content_hash: str
    description: str = ""


class ConflictResolution(BaseModel):
    """A caller-supplied resolution for a specific conflict segment."""
    segment_id: str
    resolution_type: str         # "TAKE_SOURCE" | "TAKE_TARGET" | "CUSTOM"
    resolved_content_hash: str
    resolver: str
    rationale: str = ""


class ConflictManifest(BaseModel):
    """Returned by execute_merge() when conflicts exist without resolutions.

    Merge does NOT proceed — the caller must re-invoke with resolutions.
    """
    merge_id: UUID = Field(default_factory=uuid4)
    source_episode_id: str
    target_episode_id: str
    common_ancestor_id: str
    conflicts: List[ConflictSegment] = Field(default_factory=list)
    source_merkle_root: str
    target_merkle_root_pre: str
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================================
# Phase 2 — Result Types
# ============================================================================


class CommonAncestorResult(BaseModel):
    """Result of find_common_ancestor()."""
    common_ancestor_node_id: str
    branch_delta_from_ancestor: List[str] = Field(default_factory=list)
    target_delta_from_ancestor: List[str] = Field(default_factory=list)


class ForkResult(BaseModel):
    """Result of create_fork()."""
    fork_id: str
    fork_point_ids: List[str]
    origin_episode_id: str
    origin_segment_id: str
    delta_id: str
    audit_record_id: str


class ResolveForkResult(BaseModel):
    """Result of resolve_fork()."""
    fork_id: str
    selected_fork_point_id: str
    discarded_fork_point_ids: List[str]
    discarded_terminus_ids: List[str]
    delta_id: str
    audit_record_id: str


class MergeResult(BaseModel):
    """Result of execute_merge() on the success path.

    When conflicts exist without resolutions, execute_merge returns a
    ConflictManifest instead of a MergeResult.
    """
    merge_id: str
    merge_point_id: str
    merge_type: MergeType
    source_merkle_root: str
    target_merkle_root_pre: str
    target_merkle_root_post: str
    conflict_segments: List[str] = Field(default_factory=list)
    resolution_artifacts: List[str] = Field(default_factory=list)
    terminus_id: str
    delta_id: str
    audit_record_id: str


class MergeIntegrityResult(BaseModel):
    """Result of verify_merge_integrity()."""
    merge_id: str
    source_valid: bool
    target_pre_valid: bool
    target_post_valid: bool
    integrity_holds: bool


# ============================================================================
# Phase 2 — Hash Functions
# ============================================================================


def compute_fork_point_hash(
    fork_point_id: str,
    fork_id: str,
    episode_id: str,
    origin_episode_id: str,
    origin_segment_id: str,
    fork_objective: str,
    initiator: str,
    sibling_index: int,
    timestamp: str,
    parent_hash: str,
) -> str:
    """Compute the content hash of a ForkPointNode.

    Domain separation prefix: FORK_POINT:
    """
    preimage = (
        f"{fork_point_id}:{fork_id}:{episode_id}:{origin_episode_id}:"
        f"{origin_segment_id}:{fork_objective}:{initiator}:{sibling_index}:"
        f"{timestamp}:{parent_hash}"
    )
    return sha3_256(b"FORK_POINT:" + preimage.encode())


# ============================================================================
# Phase D — Departure Fork Lifecycle
#
# A DEPARTURE fork is distinct from the speculative fork above. It is a single
# directional departure: one topic diverges into one new episode while the
# originating episode CONTINUES uninterrupted. There are no siblings and no
# resolve/promote/discard — "fork is a verb, not a noun; if not abandoned it IS
# an episode." (Ariadne BFM Phase D, Episode 49372907, Clotho + Devin.)
# ============================================================================


class ForkCreationTrigger(str, Enum):
    """What precipitated a departure fork. EXPLORATORY_THREAD routes to the
    speculative create_fork(), not create_departure_fork()."""
    TOPIC_SHIFT = "TOPIC_SHIFT"            # distinct new topic diverged (ACI or human)
    PARALLEL_THREAD = "PARALLEL_THREAD"    # a parallel line of inquiry opened
    EXPLICIT_FORK = "EXPLICIT_FORK"        # human/agent explicitly requested a fork
    AGENT_ESCALATION = "AGENT_ESCALATION"  # ACI-detected escalation (trigger segment required)


class DepartureForkStatus(str, Enum):
    """Lifecycle status of a departure-fork episode. Distinct vocabulary from the
    speculative fork's PROMOTED/DISCARDED — an ABANDONED departure is not a
    DISCARDED alternative. ACTIVE covers both in-progress and parked (resumed)."""
    ACTIVE = "ACTIVE"          # available for work (in-progress OR parked)
    COMPLETED = "COMPLETED"    # the fork's own work is done (guards formal return)
    ABANDONED = "ABANDONED"    # never developed / no longer pursued (terminal)


class ForkReturnType(str, Enum):
    """How a completed departure fork's work is brought back to the origin. A
    fork return is DECLARATIVE (cross-episode assertion), never the branch's
    STRUCTURAL MERGED (shared spine) — hence INCORPORATED, not MERGED."""
    INCORPORATED = "INCORPORATED"    # origin incorporates the fork's work
    ACKNOWLEDGED = "ACKNOWLEDGED"    # noted, not incorporated
    SUPERSEDED = "SUPERSEDED"        # origin moved past it; informational


class OrphanClass(str, Enum):
    """Which structural inconsistency a ForkOrphanMarker records (Ariadne BFM Phase D,
    orphan detection). A/B/C are the partial-failure classes; D is the stale-ACTIVE
    hygiene class. Tags the MARKER (distinct from ForkOrphanClass, set on the episode)."""
    CLASS_A = "CLASS_A"    # dangling DepartureForkPointNode — no fork episode
    CLASS_B = "CLASS_B"    # unanchored fork episode — no DepartureForkPointNode
    CLASS_C = "CLASS_C"    # ForkReturnNode present but fork_status not COMPLETED
    CLASS_D = "CLASS_D"    # stale ACTIVE fork — no spine activity past the threshold


class ForkOrphanClass(str, Enum):
    """Set on a fork EPISODE when a Class-B orphan cannot be re-anchored because its
    originating episode is unreachable. Distinct from OrphanClass (which tags the marker)."""
    UNANCHORED = "UNANCHORED"    # a fork with no recoverable origin


class DepartureForkPointNode(BaseModel):
    """Written to the ORIGINATING episode's spine by create_departure_fork() —
    the single departure marker. Distinct label/hash-domain from the speculative
    ForkPointNode. `spine_tip_hash_at_departure` must equal the fork episode's
    `fork_origin_spine_tip_hash` (cross-verifiable integrity invariant)."""
    fork_point_id: UUID = Field(default_factory=uuid4)
    fork_id: UUID                                     # shared with the fork episode's provenance
    fork_episode_id: UUID                             # the created (continuing) fork episode
    origin_episode_id: UUID                           # episode the departure left from
    origin_segment_id: str                            # provenance anchor (departure point)
    fork_objective: str                               # the fork episode's objective
    fork_creation_trigger: ForkCreationTrigger
    fork_title_snapshot: str = ""                     # fork title at creation (display)
    spine_tip_hash_at_departure: str                  # origin spine tip hash at departure
    initiator: str
    content_hash: str = ""
    parent_hash: str = ""
    timestamp_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = ARIADNE_SCHEMA_VERSION
    # Orphan-recovery diagnostic flags — set by recovery only; NOT part of content_hash,
    # so a retroactively-recovered point hashes identically to one written on time (§19.3.7).
    orphaned: Optional[bool] = None                       # Class-A: dangling point (no fork episode)
    retroactive: Optional[bool] = None                    # Class-B: point re-written by recovery
    orphan_recovery_timestamp: Optional[datetime] = None  # when recovery wrote/flagged it


class DepartureForkResult(BaseModel):
    """Return value of create_departure_fork()."""
    fork_id: str
    fork_point_id: str
    fork_episode_id: str
    origin_episode_id: str
    origin_segment_id: str
    spine_tip_hash_at_departure: str
    delta_id: str
    audit_record_id: str


class DepartureForkCreatedDelta(BaseModel):
    """Forward + reverse delta for DEPARTURE_FORK_CREATED."""
    origin_episode_id: str
    origin_segment_id: str
    fork_id: str
    fork_episode_id: str
    fork_objective: str
    fork_creation_trigger: str
    spine_tip_hash_at_departure: str
    reverse_delete_fork_id: str
    reverse_delete_fork_point_id: str
    reverse_delete_fork_episode_id: str


def compute_departure_fork_point_hash(
    fork_point_id: str,
    fork_id: str,
    fork_episode_id: str,
    origin_episode_id: str,
    origin_segment_id: str,
    fork_objective: str,
    fork_creation_trigger: str,
    spine_tip_hash_at_departure: str,
    initiator: str,
    timestamp: str,
    parent_hash: str,
) -> str:
    """Compute the content hash of a DepartureForkPointNode.

    Domain separation prefix: DEPARTURE_FORK_POINT: (distinct from FORK_POINT:).
    """
    preimage = (
        f"{fork_point_id}:{fork_id}:{fork_episode_id}:{origin_episode_id}:"
        f"{origin_segment_id}:{fork_objective}:{fork_creation_trigger}:"
        f"{spine_tip_hash_at_departure}:{initiator}:{timestamp}:{parent_hash}"
    )
    return sha3_256(b"DEPARTURE_FORK_POINT:" + preimage.encode())


class ForkReturnNode(BaseModel):
    """Written to the ORIGINATING episode's spine by declare_fork_return() when a
    COMPLETED departure fork's work is formally brought back. DECLARATIVE (the origin
    asserts incorporation across two independent spines) — never the branch's
    structural merge. Only written on an explicit return; resumption writes nothing.
    (Ariadne BFM Phase D.)"""
    fork_return_id: UUID = Field(default_factory=uuid4)
    fork_id: UUID                                     # the returned departure fork
    fork_episode_id: UUID                             # the (COMPLETED) fork episode
    origin_episode_id: UUID                           # the episode being returned to
    return_type: ForkReturnType                       # INCORPORATED | ACKNOWLEDGED | SUPERSEDED
    synthesis_summary: str = ""                       # what the origin takes from the fork
    fork_final_spine_tip_hash: str = ""               # fork episode's tip at return (integrity)
    returned_by: str                                  # the originating agent (authority)
    content_hash: str = ""
    parent_hash: str = ""
    timestamp_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = ARIADNE_SCHEMA_VERSION


class ForkReturnResult(BaseModel):
    """Return value of declare_fork_return()."""
    fork_return_id: str
    fork_id: str
    origin_episode_id: str
    return_type: str
    delta_id: str
    audit_record_id: str


def compute_fork_return_hash(
    fork_return_id: str,
    fork_id: str,
    fork_episode_id: str,
    origin_episode_id: str,
    return_type: str,
    synthesis_summary: str,
    fork_final_spine_tip_hash: str,
    returned_by: str,
    timestamp: str,
    parent_hash: str,
) -> str:
    """Compute the content hash of a ForkReturnNode.

    Domain separation prefix: FORK_RETURN: (distinct from FORK_POINT: / MERGE_POINT:).
    """
    preimage = (
        f"{fork_return_id}:{fork_id}:{fork_episode_id}:{origin_episode_id}:"
        f"{return_type}:{synthesis_summary}:{fork_final_spine_tip_hash}:"
        f"{returned_by}:{timestamp}:{parent_hash}"
    )
    return sha3_256(b"FORK_RETURN:" + preimage.encode())


class ForkOrphanMarker(BaseModel):
    """A non-chained diagnostic satellite recording that a departure fork was found in a
    structurally-inconsistent state (Ariadne BFM Phase D, orphan detection). Written to the
    ORIGIN spine by orphan recovery. Self-hashed for tamper-evidence (domain
    FORK_ORPHAN_MARKER:) but NOT a member of the origin spine's Merkle chain — it has no
    parent_hash and writing it never changes the origin episode's root/tip. Read-only after
    write; ONE marker per orphaned fork (dedup on fork_id); excluded from departure-registry
    queries (which match DepartureForkPointNode / ForkReturnNode only)."""
    fork_orphan_marker_id: UUID = Field(default_factory=uuid4)
    fork_id: UUID                                     # the orphaned fork (dedup key: one per fork)
    origin_episode_id: UUID                           # the originating episode it hangs off
    orphan_class: OrphanClass
    sequence_index: int                               # positional record on the origin spine (satellite)
    detection_run_id: UUID                            # the detection sweep that found it
    recovery_action: str                              # human-readable description of what recovery did
    requires_operator_review: bool                    # true for Class A; false for auto-recovered
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    content_hash: str = ""                            # self-tamper-evidence (NOT a spine chain link)
    schema_version: str = ARIADNE_SCHEMA_VERSION


def compute_fork_orphan_marker_hash(
    fork_orphan_marker_id: str,
    fork_id: str,
    origin_episode_id: str,
    orphan_class: str,
    sequence_index: int,
    detection_run_id: str,
    recovery_action: str,
    requires_operator_review: bool,
    detected_at: str,
) -> str:
    """Compute the SELF content hash of a ForkOrphanMarker.

    Domain separation prefix: FORK_ORPHAN_MARKER:. This is a self-integrity hash ONLY — the
    marker is a diagnostic satellite, NOT chained into the origin spine's Merkle root, so it
    carries no parent_hash and writing it does not alter origin spine integrity.
    """
    preimage = (
        f"{fork_orphan_marker_id}:{fork_id}:{origin_episode_id}:{orphan_class}:"
        f"{sequence_index}:{detection_run_id}:{recovery_action}:"
        f"{requires_operator_review}:{detected_at}"
    )
    return sha3_256(b"FORK_ORPHAN_MARKER:" + preimage.encode())


def compute_merge_point_hash(
    merge_point_id: str,
    merge_id: str,
    source_episode_id: str,
    target_episode_id: str,
    source_merkle_root: str,
    target_merkle_root_pre: str,
    target_merkle_root_post: str,
    common_ancestor_id: str,
    timestamp: str,
    parent_hash: str,
) -> str:
    """Compute the content hash of a MergePointNode.

    Domain separation prefix: MERGE_POINT:
    All three Merkle roots bound into the hash — tamper-evident.
    """
    preimage = (
        f"{merge_point_id}:{merge_id}:{source_episode_id}:{target_episode_id}:"
        f"{source_merkle_root}:{target_merkle_root_pre}:{target_merkle_root_post}:"
        f"{common_ancestor_id}:{timestamp}:{parent_hash}"
    )
    return sha3_256(b"MERGE_POINT:" + preimage.encode())


def compute_conflict_manifest_hash(
    merge_id: str,
    source_episode_id: str,
    target_episode_id: str,
    conflict_segment_ids: List[str],
) -> str:
    """Compute a content hash for a conflict manifest (for audit trail)."""
    conflicts_str = ",".join(sorted(conflict_segment_ids))
    preimage = (
        f"{merge_id}:{source_episode_id}:{target_episode_id}:{conflicts_str}"
    )
    return sha3_256(b"CONFLICT_MANIFEST:" + preimage.encode())


# ============================================================================
# Phase 2 — Governance Rules
# ============================================================================


def enforce_fork_objective_required(objective: Optional[str]) -> None:
    """Fork objective must be non-empty — a fork without objective is a branch."""
    if not objective or not objective.strip():
        raise AriadneGovernanceError(
            "Fork creation requires a non-empty fork_objective. "
            "A fork without an objective is indistinguishable from a branch."
        )


def enforce_fork_sibling_count(count: int) -> None:
    """Fork must have at least 2 alternatives — a 1-path fork is a branch."""
    if count < 2:
        raise AriadneGovernanceError(
            f"Fork requires at least 2 alternatives (got {count}). "
            "Single-path divergence is a branch, not a fork."
        )


def enforce_merge_summary_required(summary: Optional[str]) -> None:
    """Merge summary must be non-empty — the synthesis is the audit trail."""
    if not summary or not summary.strip():
        raise AriadneGovernanceError(
            "Merge execution requires a non-empty merge_summary. "
            "The synthesis is the audit trail of what the merge produced."
        )




# ============================================================================
# Phase 3 — Social/Internal Primitives
# ============================================================================


class AsideStatus(str, Enum):
    """Lifecycle status of an aside, derived from presence of close record."""
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class SoliloquyStatus(str, Enum):
    """Lifecycle status of a soliloquy."""
    ACTIVE = "ACTIVE"
    CONCLUDED = "CONCLUDED"


class AsideTerminationStatus(str, Enum):
    """How an aside was terminated."""
    CLOSED = "CLOSED"
    ABANDONED = "ABANDONED"         # Unclosed at episode close — audit violation


class SoliloquyTerminationStatus(str, Enum):
    ABSORBED = "ABSORBED"           # Conclusion merged to spine
    ABANDONED = "ABANDONED"         # Unclosed — audit violation


class SoliloquyContentHashPolicy(str, Enum):
    """How a soliloquy's content hash is computed for the Merkle chain."""
    HASH_PLACEHOLDER = "HASH_PLACEHOLDER"   # Preserve chain without content exposure
    FULL_CONTENT = "FULL_CONTENT"           # Hash the deliberation chain directly


# ============================================================================
# Phase 3 — Delta Payloads
# ============================================================================


class AsideOpenedDelta(BaseModel):
    """Forward + reverse delta for ASIDE_OPENED."""
    parent_episode_id: str
    parent_segment_id: str
    aside_id: str
    aside_label: str
    initiated_by_human: str
    target_agent_id: str
    return_obligation: bool = True
    # Reverse
    reverse_delete_aside_id: str


class AsideClosedDelta(BaseModel):
    """Forward + reverse delta for ASIDE_CLOSED."""
    aside_id: str
    close_reason: str
    final_content_hash: str
    reference_scan_passed: bool
    external_references_found: List[str] = Field(default_factory=list)
    notification_targets: List[str] = Field(default_factory=list)
    # Reverse
    reverse_restore_aside_to_open: str


class SoliloquyInitiatedDelta(BaseModel):
    """Forward + reverse delta for SOLILOQUY_INITIATED."""
    parent_episode_id: str
    parent_segment_id: str
    soliloquy_id: str
    soliloquy_purpose: str
    initiated_by_agent: str
    visibility_policy: Dict[str, Any]
    # Reverse
    reverse_delete_soliloquy_id: str


class SoliloquyConcludedDelta(BaseModel):
    """Forward + reverse delta for SOLILOQUY_CONCLUDED."""
    soliloquy_id: str
    conclusion_summary: str
    conclusion_content_hash: str
    deliberation_chain_hash: str
    merged_into_segment_id: str
    # Reverse
    reverse_restore_soliloquy_to_active: str


# ============================================================================
# Phase 3 — Node Models
# ============================================================================


class SoliloquyVisibilityPolicy(BaseModel):
    """Per-soliloquy visibility policy. Defaults enforce Decision 1."""
    human_accessible: bool = True                              # ALWAYS — non-negotiable
    owner_agent_access: str = "ALWAYS"
    other_agents_access: AccessLevel = AccessLevel.ESCALATION_ONLY
    content_hash_policy: SoliloquyContentHashPolicy = SoliloquyContentHashPolicy.HASH_PLACEHOLDER
    audit_on_access: bool = True
    deployment_override_permitted: bool = False                # Must be explicit per deployment


class AsideSegmentNode(BaseModel):
    """Created by create_aside() — human-initiated side channel with target agent.

    Invariant: asides are ALWAYS human-initiated. Agent-initiated internal
    branches are soliloquies, not asides.
    """
    aside_id: UUID = Field(default_factory=uuid4)
    parent_episode_id: UUID
    parent_segment_id: str                                      # Where the aside opened
    aside_label: str                                            # Human-readable purpose
    initiated_by_human: str                                     # Human identifier — required
    target_agent_id: str                                        # Agent the aside runs with
    return_obligation: bool = True                              # Must be closed before episode seal
    content_refs: List[str] = Field(default_factory=list)       # Segments/artifacts produced in aside
    content_hash: str = ""
    parent_hash: str = ""
    timestamp_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = ARIADNE_SCHEMA_VERSION


class AsideTerminusNode(BaseModel):
    """Created by close_aside() — records the aside close.

    Asymmetric merge: other agents are NOTIFIED of the aside's existence,
    but the internal content is retrieval-accessible only, not injected
    into working state.
    """
    aside_terminus_id: UUID = Field(default_factory=uuid4)
    aside_id: UUID
    parent_episode_id: UUID
    close_reason: str
    final_content_hash: str
    reference_scan_passed: bool                                 # No external refs held internal state
    external_references_found: List[str] = Field(default_factory=list)
    notification_targets: List[str] = Field(default_factory=list)
    duration_ms: int = 0
    termination_status: AsideTerminationStatus = AsideTerminationStatus.CLOSED
    timestamp_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = ARIADNE_SCHEMA_VERSION


class SoliloquySegmentNode(BaseModel):
    """Created by create_soliloquy() — agent-initiated private deliberation.

    Invariants:
      - Human-accessible ALWAYS (never private to humans)
      - Other agents: ESCALATION_ONLY by default
      - Coherence monitoring continues inside the soliloquy
      - Return obligation required — unclosed is an audit violation
    """
    soliloquy_id: UUID = Field(default_factory=uuid4)
    parent_episode_id: UUID
    parent_segment_id: str
    soliloquy_purpose: str                                      # Why the agent is deliberating
    initiated_by_agent: str                                     # Agent identifier
    visibility_policy: SoliloquyVisibilityPolicy = Field(
        default_factory=SoliloquyVisibilityPolicy
    )
    deliberation_chain: List[str] = Field(default_factory=list)  # Internal reasoning segment IDs
    content_hash: str = ""                                      # Computed via policy (placeholder or full)
    parent_hash: str = ""
    timestamp_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = ARIADNE_SCHEMA_VERSION


class SoliloquyConclusionNode(BaseModel):
    """Created by conclude_soliloquy() — the conclusion that merges back to spine.

    Only this conclusion is absorbed into the parent episode. The
    deliberation chain stays sealed inside the SoliloquySegmentNode.
    """
    conclusion_id: UUID = Field(default_factory=uuid4)
    soliloquy_id: UUID
    parent_episode_id: UUID
    conclusion_summary: str                                     # What the agent concluded
    conclusion_content_hash: str                                # Hash of the public conclusion
    deliberation_chain_hash: str                                # Tamper-evident hash of private chain
    merged_into_segment_id: str                                 # Spine segment that received the conclusion
    duration_ms: int = 0
    termination_status: SoliloquyTerminationStatus = SoliloquyTerminationStatus.ABSORBED
    timestamp_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = ARIADNE_SCHEMA_VERSION


# ============================================================================
# Phase 3 — Result Types
# ============================================================================


class AsideResult(BaseModel):
    aside_id: str
    parent_episode_id: str
    parent_segment_id: str
    target_agent_id: str
    delta_id: str
    audit_record_id: str
    status: AsideStatus = AsideStatus.OPEN


class AsideCloseResult(BaseModel):
    aside_id: str
    aside_terminus_id: str
    final_content_hash: str
    reference_scan_passed: bool
    external_references_found: List[str] = Field(default_factory=list)
    notification_targets: List[str] = Field(default_factory=list)
    delta_id: str
    audit_record_id: str


class SoliloquyResult(BaseModel):
    soliloquy_id: str
    parent_episode_id: str
    parent_segment_id: str
    initiated_by_agent: str
    delta_id: str
    audit_record_id: str
    status: SoliloquyStatus = SoliloquyStatus.ACTIVE


class SoliloquyConclusionResult(BaseModel):
    soliloquy_id: str
    conclusion_id: str
    conclusion_content_hash: str
    deliberation_chain_hash: str
    merged_into_segment_id: str
    delta_id: str
    audit_record_id: str


# ============================================================================
# Phase 3 — Hash Functions
# ============================================================================


def compute_aside_hash(
    aside_id: str,
    parent_episode_id: str,
    parent_segment_id: str,
    initiated_by_human: str,
    target_agent_id: str,
    timestamp: str,
    parent_hash: str,
) -> str:
    """Compute the content hash of an AsideSegmentNode.

    Domain separation prefix: ASIDE:
    """
    preimage = (
        f"{aside_id}:{parent_episode_id}:{parent_segment_id}:"
        f"{initiated_by_human}:{target_agent_id}:{timestamp}:{parent_hash}"
    )
    return sha3_256(b"ASIDE:" + preimage.encode())


def compute_soliloquy_content_hash(
    soliloquy_id: str,
    parent_episode_id: str,
    parent_segment_id: str,
    initiated_by_agent: str,
    timestamp: str,
    deliberation_chain: List[str],
    policy: SoliloquyVisibilityPolicy,
) -> str:
    """Compute the content hash of a SoliloquySegmentNode per visibility policy.

    HASH_PLACEHOLDER: hashes only identity + timestamp (chain preserved, content hidden)
    FULL_CONTENT:    hashes the deliberation chain directly

    Domain separation prefix: SOLILOQUY_PLACEHOLDER: or SOLILOQUY_FULL:
    """
    if policy.content_hash_policy == SoliloquyContentHashPolicy.HASH_PLACEHOLDER:
        preimage = (
            f"{soliloquy_id}:{parent_episode_id}:{parent_segment_id}:"
            f"{initiated_by_agent}:{timestamp}"
        )
        return sha3_256(b"SOLILOQUY_PLACEHOLDER:" + preimage.encode())
    else:
        chain_str = "|".join(deliberation_chain)
        preimage = (
            f"{soliloquy_id}:{parent_episode_id}:{parent_segment_id}:"
            f"{initiated_by_agent}:{timestamp}:{chain_str}"
        )
        return sha3_256(b"SOLILOQUY_FULL:" + preimage.encode())


def compute_deliberation_chain_hash(
    soliloquy_id: str,
    deliberation_chain: List[str],
) -> str:
    """Tamper-evident hash of the private deliberation chain.

    Stored on the conclusion node so that an auditor with access can
    verify the deliberation content without the content being exposed
    in the public conclusion.

    Domain separation prefix: DELIBERATION_CHAIN:
    """
    chain_str = "|".join(deliberation_chain)
    preimage = f"{soliloquy_id}:{chain_str}"
    return sha3_256(b"DELIBERATION_CHAIN:" + preimage.encode())


def compute_soliloquy_conclusion_hash(
    conclusion_id: str,
    soliloquy_id: str,
    conclusion_summary: str,
    timestamp: str,
) -> str:
    """Hash of the public conclusion that merges back to spine.

    Domain separation prefix: SOLILOQUY_CONCLUSION:
    """
    preimage = f"{conclusion_id}:{soliloquy_id}:{conclusion_summary}:{timestamp}"
    return sha3_256(b"SOLILOQUY_CONCLUSION:" + preimage.encode())


# ============================================================================
# Phase 3 — Governance Rules
# ============================================================================


def enforce_aside_human_initiated(initiated_by_human: Optional[str]) -> None:
    """Asides are ALWAYS human-initiated. An agent-initiated internal branch
    is a soliloquy, not an aside."""
    if not initiated_by_human or not initiated_by_human.strip():
        raise AriadneGovernanceError(
            "Asides must be human-initiated — initiated_by_human is required. "
            "Agent-initiated internal branches are soliloquies."
        )


def enforce_aside_target_agent(target_agent_id: Optional[str]) -> None:
    """Aside runs with a specific target agent — required."""
    if not target_agent_id or not target_agent_id.strip():
        raise AriadneGovernanceError(
            "Asides require a target_agent_id — aside runs with exactly one agent."
        )


def enforce_aside_close_reason(reason: Optional[str]) -> None:
    """Asides must be closed with a non-empty reason."""
    if not reason or not reason.strip():
        raise AriadneGovernanceError(
            "Closing an aside requires a non-empty close_reason. "
            "Return obligation is part of the audit trail."
        )


def enforce_soliloquy_purpose_required(purpose: Optional[str]) -> None:
    """Soliloquies must have a non-empty purpose."""
    if not purpose or not purpose.strip():
        raise AriadneGovernanceError(
            "Soliloquy creation requires a non-empty purpose. "
            "A soliloquy without purpose is indistinguishable from silence."
        )


def enforce_soliloquy_human_accessible(policy: SoliloquyVisibilityPolicy) -> None:
    """Non-negotiable: humans always have read access to soliloquies."""
    if not policy.human_accessible:
        raise AriadneGovernanceError(
            "Soliloquy visibility policy violation: human_accessible=false. "
            "Humans ALWAYS have read access — this is non-negotiable. "
            "Deliberation content can be private to other agents, never to humans."
        )


def enforce_soliloquy_conclusion_required(summary: Optional[str]) -> None:
    """Concluding a soliloquy requires a non-empty summary — only the
    conclusion merges back to the spine."""
    if not summary or not summary.strip():
        raise AriadneGovernanceError(
            "Soliloquy conclusion requires a non-empty summary. "
            "Only the conclusion merges back — silence is not an exit."
        )


def check_aside_return_obligation(aside_open: bool, episode_sealing: bool = False) -> None:
    """On episode seal, any still-open aside is an audit violation."""
    if aside_open and episode_sealing:
        raise AriadneGovernanceError(
            "Return obligation violated: aside is still OPEN at episode seal. "
            "Unclosed asides are audit violations — close or explicitly abandon."
        )


def check_soliloquy_return_obligation(
    soliloquy_active: bool, episode_sealing: bool = False,
) -> None:
    """On episode seal, any still-active soliloquy is an audit violation."""
    if soliloquy_active and episode_sealing:
        raise AriadneGovernanceError(
            "Return obligation violated: soliloquy is still ACTIVE at episode seal. "
            "Unconcluded soliloquies are audit violations — conclude or explicitly abandon."
        )




# ============================================================================
# Phase 4 — Prescriptive Enforcement
# ============================================================================


class DetectionState(str, Enum):
    """Coherence-drift detection state.

    States advance as drift persists; they revert when drift resolves.
    MATERIALIZED is the threshold at which a branch should be declared.
    """
    NOMINAL = "NOMINAL"
    WATCHING = "WATCHING"
    CANDIDATE = "CANDIDATE"
    MATERIALIZED = "MATERIALIZED"


class IntentClass(str, Enum):
    """The caller's classification of what this segment is doing."""
    CONTINUE = "CONTINUE"       # Same thread as spine
    EXPAND = "EXPAND"           # Widens scope but stays on thread
    SHIFT = "SHIFT"             # Topic-adjacent but divergent
    RESOLVE = "RESOLVE"         # Closes an open thread
    INTRODUCE = "INTRODUCE"     # New topic — immediate branch candidate


# ============================================================================
# Phase 4 — Coherence Fingerprint
# ============================================================================


class CoherenceFingerprint(BaseModel):
    """Per-segment coherence fingerprint, computed at write time.

    Write-time computation is the critical invariant — retroactive
    computation detects branches after they've formed, whereas write-time
    fingerprinting enables detection AS the window opens.

    topic_vector is caller-supplied; if unavailable the registry falls
    back to objective_hash-only detection.
    """
    fingerprint_id: UUID = Field(default_factory=uuid4)
    episode_id: str
    segment_id: str
    sequence_index: int = 0
    topic_vector: List[float] = Field(default_factory=list)     # Caller-supplied embedding
    intent_class: IntentClass = IntentClass.CONTINUE
    objective_hash: str = ""                                    # Hash of current episode objective
    drift_from_spine: float = 0.0                               # 0.0–1.0 cosine distance
    consecutive_drift_count: int = 0                            # Persisted across turns
    detection_state: DetectionState = DetectionState.NOMINAL
    timestamp_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = ARIADNE_SCHEMA_VERSION


# ============================================================================
# Phase 4 — Detection Thresholds (Tunable)
# ============================================================================


class DetectionThresholds(BaseModel):
    """Detection-state transition thresholds.

    Spec §7.2: initial values require empirical calibration.
    Implement as per-episode-type tunable parameters.
    """
    watching_drift: float = 0.3
    watching_consecutive_turns: int = 1
    candidate_drift: float = 0.3
    candidate_consecutive_turns: int = 3
    materialized_drift: float = 0.5
    materialized_consecutive_turns: int = 5
    # Any objective-hash change forces IMMEDIATE CANDIDATE regardless of drift
    objective_change_forces_candidate: bool = True


DEFAULT_DETECTION_THRESHOLDS = DetectionThresholds()


# ============================================================================
# Phase 4 — Detection Result
# ============================================================================


class DetectionResult(BaseModel):
    """Outcome of advance_detection_state() / the derivative+hysteresis FSM."""
    episode_id: str
    segment_id: str
    prior_state: DetectionState
    new_state: DetectionState
    consecutive_drift_count: int
    drift_from_spine: float
    materialized_recommendation: Optional[Dict[str, Any]] = None
    # Populated when new_state == MATERIALIZED — a recommendation to
    # create_branch(declaration_type=RETROACTIVE) at the last nominal point.

    # Derivative+hysteresis FSM (populated only when detect_branch_candidate is
    # given an fsm_state). The caller (ignis-os) persists `new_fsm_state` to
    # Redis between turns. All None/False on the legacy streak path.
    new_fsm_state: Optional[DriftDetectionState] = None
    delta_drift: Optional[float] = None
    triggered_on_derivative: bool = False


# ============================================================================
# Phase 4 — Confirmation Cache
# ============================================================================


class ConfirmedAction(BaseModel):
    """A user confirmation cached to prevent the confirmation loop."""
    action_description: str
    confirmed_by: str
    confirmed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    valid_for_turns: int = 10
    confirmed_at_turn: int


class ConfirmationCache:
    """In-memory TTL-by-turn cache of confirmed actions.

    A confirmation is valid for N turns from when it was granted. After
    expiry the cache discards the entry and the caller must re-ask.
    """

    def __init__(self):
        self._entries: Dict[str, ConfirmedAction] = {}

    def record(
        self,
        action_description: str,
        confirmed_by: str,
        current_turn: int,
        valid_for_turns: int = 10,
    ) -> ConfirmedAction:
        key = self._key(action_description)
        entry = ConfirmedAction(
            action_description=action_description,
            confirmed_by=confirmed_by,
            confirmed_at_turn=current_turn,
            valid_for_turns=valid_for_turns,
        )
        self._entries[key] = entry
        return entry

    def is_confirmed(self, action_description: str, current_turn: int) -> bool:
        key = self._key(action_description)
        entry = self._entries.get(key)
        if entry is None:
            return False
        if current_turn - entry.confirmed_at_turn > entry.valid_for_turns:
            # Expired — discard
            del self._entries[key]
            return False
        return True

    def get(self, action_description: str) -> Optional[ConfirmedAction]:
        return self._entries.get(self._key(action_description))

    def invalidate(self, action_description: str) -> None:
        self._entries.pop(self._key(action_description), None)

    def clear(self) -> None:
        self._entries.clear()

    @staticmethod
    def _key(action_description: str) -> str:
        """Canonicalize action description for cache lookup."""
        return sha3_256(b"CONFIRMATION:" + action_description.strip().lower().encode())


# ============================================================================
# Phase 4 — Hash Functions
# ============================================================================


def compute_fingerprint_hash(
    fingerprint_id: str,
    episode_id: str,
    segment_id: str,
    objective_hash: str,
    intent_class: str,
    timestamp: str,
) -> str:
    """Domain separation prefix: FINGERPRINT:"""
    preimage = (
        f"{fingerprint_id}:{episode_id}:{segment_id}:"
        f"{objective_hash}:{intent_class}:{timestamp}"
    )
    return sha3_256(b"FINGERPRINT:" + preimage.encode())


def compute_objective_hash(objective: str) -> str:
    """Hash the current episode objective string for change detection.

    Domain separation prefix: OBJECTIVE:
    """
    return sha3_256(b"OBJECTIVE:" + (objective or "").strip().encode())


# ============================================================================
# Phase 4 — State Machine
# ============================================================================


def advance_detection_state(
    prior_state: DetectionState,
    prior_consecutive_count: int,
    drift_from_spine: float,
    objective_changed: bool,
    intent_class: IntentClass,
    thresholds: DetectionThresholds = DEFAULT_DETECTION_THRESHOLDS,
) -> tuple[DetectionState, int]:
    """Advance the detection state given a new observation.

    Returns (new_state, new_consecutive_drift_count).

    State transitions:
      - objective_changed => CANDIDATE (immediate, consecutive count preserved)
      - intent_class == INTRODUCE => CANDIDATE (immediate)
      - drift >= materialized_drift AND consecutive_count + 1 >= materialized_turns
          => MATERIALIZED
      - drift >= candidate_drift AND consecutive_count + 1 >= candidate_turns
          => CANDIDATE
      - drift >= watching_drift AND consecutive_count + 1 >= watching_turns
          => WATCHING
      - drift below watching_drift => reset consecutive to 0, state back to NOMINAL
    """
    # Immediate promotion by objective change
    if objective_changed and thresholds.objective_change_forces_candidate:
        return DetectionState.CANDIDATE, prior_consecutive_count + 1

    # INTRODUCE intent is an immediate candidate
    if intent_class == IntentClass.INTRODUCE:
        return DetectionState.CANDIDATE, prior_consecutive_count + 1

    # Drift resolved — reset state
    if drift_from_spine < thresholds.watching_drift:
        return DetectionState.NOMINAL, 0

    # Drift present — increment consecutive count
    new_count = prior_consecutive_count + 1

    # Check thresholds in descending order of severity
    if (drift_from_spine >= thresholds.materialized_drift
            and new_count >= thresholds.materialized_consecutive_turns):
        return DetectionState.MATERIALIZED, new_count

    if (drift_from_spine >= thresholds.candidate_drift
            and new_count >= thresholds.candidate_consecutive_turns):
        return DetectionState.CANDIDATE, new_count

    if (drift_from_spine >= thresholds.watching_drift
            and new_count >= thresholds.watching_consecutive_turns):
        return DetectionState.WATCHING, new_count

    # Drift present but not yet at WATCHING threshold (shouldn't reach here
    # given the watching check above — kept for clarity)
    return DetectionState.NOMINAL, new_count


def compute_materialized_recommendation(
    episode_id: str,
    segment_id: str,
    last_nominal_segment_id: Optional[str],
    drift_from_spine: float,
) -> Dict[str, Any]:
    """Build a retroactive-branch recommendation payload.

    Returned when detection advances to MATERIALIZED. The caller can feed
    this directly into create_branch(declaration_type=RETROACTIVE).
    """
    return {
        "recommended_action": "CREATE_BRANCH_RETROACTIVE",
        "source_episode_id": episode_id,
        "source_segment_id": last_nominal_segment_id or segment_id,
        "drift_from_spine": drift_from_spine,
        "rationale": (
            "Detection state advanced to MATERIALIZED. "
            "Declare branch retroactively at the last nominal segment."
        ),
    }


def enforce_write_time_fingerprint(fingerprint: Optional[CoherenceFingerprint]) -> None:
    """Fingerprint must be present at write time — not retroactively.

    Spec §7.1: retroactive fingerprinting defeats the detection window.
    """
    if fingerprint is None:
        raise AriadneGovernanceError(
            "Coherence fingerprint must be computed at segment write time. "
            "Retroactive fingerprinting defeats the detection window."
        )
