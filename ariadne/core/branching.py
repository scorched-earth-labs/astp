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
