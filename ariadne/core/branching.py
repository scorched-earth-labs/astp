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
    # Phase 3 — Social/Internal Primitives
    ASIDE_OPENED = "ASIDE_OPENED"
    ASIDE_CLOSED = "ASIDE_CLOSED"
    SOLILOQUY_INITIATED = "SOLILOQUY_INITIATED"
    SOLILOQUY_CONCLUDED = "SOLILOQUY_CONCLUDED"


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
