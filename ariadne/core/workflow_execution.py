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
Workflow & Execution DAG — Amendment v3.0 Layer 3 schema primitives.

Defines the three Layer 3 node types (WorkflowDeclaration, ExecutionNode,
SkillInvocation), their enums, content-hash computation, and audit delta
payloads. This is the protocol-level type module — adapter modules import
from here, never the reverse.

Layer 3 nodes do NOT participate in Spine hash computation (Amendment v3.0
§2, invariant L3-I1). Cross-layer references to Layer 1/2 entities are by
node_id only.

Immutability invariants per Amendment v3.0 §9:
- ExecutionNode and SkillInvocation are fully immutable after creation
  (L3-I3); retries produce new nodes (L3-I5)
- WorkflowDeclaration's mutation surface is restricted to status,
  status_updated_at, error_detail (L3-I4)

Hash preimage rules per Amendment v3.0 §8:
- WorkflowDeclaration excludes status, status_updated_at, error_detail
- ExecutionNode includes all fields except content_hash itself
- SkillInvocation excludes registry_id (reserved for future Skill Registry
  amendment per §13.2; populating registry_id later MUST NOT invalidate
  content_hash)

Sole-writer principle per Amendment v3.0 §3: every write recorded here
must be performed by the workspace's declared Cognitive Implementation
Authority for the relevant node type. The CIA identifier is mandatory on
every audit delta (§11).

This module does NOT modify existing protocol content-hash functions. It
introduces three new hash functions and reuses the canonical preimage
helper from `ariadne.core.hash_canonical`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from ariadne.core.hash_canonical import hash_preimage


# ── Enums ────────────────────────────────────────────────────────────────────


class WorkflowStatus(str, Enum):
    """Lifecycle state of a WorkflowDeclaration — Amendment v3.0 §10.

    State machine:
        DECLARED → IN_PROGRESS (auto-transition on first ExecutionNode write)
        DECLARED → INTERRUPTED (process killed before any step)
        IN_PROGRESS → {COMPLETED, FAILED, INTERRUPTED} (terminal via close)

    The three terminal states are not transitionable; once entered, the
    workflow is closed permanently.
    """

    DECLARED = "DECLARED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


class ExecutionStatus(str, Enum):
    """Terminal status of an ExecutionNode — Amendment v3.0 §5.

    Written once at creation; no update path. A retried step produces a
    new ExecutionNode rather than mutating the prior one (invariant
    L3-I5).
    """

    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


class SkillStatus(str, Enum):
    """Terminal status of a SkillInvocation — Amendment v3.0 §6.

    Written once at creation; no update path.
    """

    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


class ErrorType(str, Enum):
    """Categorization of execution failure — Amendment v3.0 §5.

    Required on ExecutionNode when status is not COMPLETED. The
    classification is coarse-grained by design; finer detail belongs in
    error_detail.
    """

    AGENT_ERROR = "AGENT_ERROR"
    TIMEOUT = "TIMEOUT"
    DEPENDENCY_FAILURE = "DEPENDENCY_FAILURE"
    SKILL_ERROR = "SKILL_ERROR"
    UNKNOWN = "UNKNOWN"


class PrecedesEdgeType(str, Enum):
    """Edge property on the ExecutionNode PRECEDES relation — Amendment v3.0 §7.

    Implementations storing the PRECEDES edge MUST record this property
    even when the default SEQUENTIAL applies; the alternative values
    carry semantic weight in forensic queries.
    """

    SEQUENTIAL = "SEQUENTIAL"
    CONDITIONAL = "CONDITIONAL"
    PARALLEL = "PARALLEL"


# Layer 3 protocol schema version. Bumps follow SemVer per Amendment v2.0
# conformance rules: additive fields → minor; hash preimage changes →
# major; field renaming → major. Amendment v3.0 ships at 3.0.0 because it
# introduces Layer 3 as a new protocol surface (no prior version to bump
# from). Subsequent Layer 3 amendments will bump from here.
LAYER_3_SCHEMA_VERSION: str = "3.0.0"


# ── Models ───────────────────────────────────────────────────────────────────


class WorkflowDeclaration(BaseModel):
    """A Layer 3 workflow intent record — Amendment v3.0 §4.

    Created at workflow initiation, before any execution step writes. The
    mutation surface is restricted to (status, status_updated_at,
    error_detail); every other field is immutable after creation.

    Hash preimage (§8): all immutable fields. status, status_updated_at,
    error_detail, and content_hash itself are excluded.

    `mandate_id` is included in the hash even though Mandate's full
    protocol surface is deferred to a companion amendment (§13.1). The
    field is the immutable provenance link from BDI deliberation to
    workflow execution; its nullability is itself part of the immutable
    record.
    """

    # Identity — immutable
    node_id: UUID = Field(default_factory=uuid4)
    node_type: str = Field(default="WorkflowDeclaration", frozen=True)
    schema_version: str = Field(default=LAYER_3_SCHEMA_VERSION)

    # Spine references — immutable, by ID only (§2 invariant L3-I1)
    episode_id: UUID
    intention_id: Optional[UUID] = None

    # Mandate provenance — immutable, hash-included (§4, §13.1)
    mandate_id: Optional[UUID] = None

    # Declaration content — immutable
    workflow_name: str
    workflow_version: str = "1.0.0"
    declared_by: str  # agent or CIA identifier
    declared_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Execution parameters — immutable
    input_context: dict[str, Any] = Field(default_factory=dict)
    expected_outputs: Optional[dict[str, Any]] = None
    timeout_ms: Optional[int] = None

    # Mutable terminal state — the only mutation surface in Layer 3 (§9, L3-I4)
    status: WorkflowStatus = WorkflowStatus.DECLARED
    status_updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error_detail: Optional[dict[str, Any]] = None

    # Integrity
    content_hash: Optional[str] = None  # SHA3-256 of canonical preimage


class ExecutionNode(BaseModel):
    """A Layer 3 atomic execution step record — Amendment v3.0 §5.

    Terminal-on-write: status is final at creation, no update path
    (invariant L3-I3). A retried step produces a new ExecutionNode with
    the same step_name, a new node_id, and a new sequence_index
    (invariant L3-I5).

    Hash preimage (§8): all fields except content_hash itself. Note that
    status is INCLUDED — unlike WorkflowDeclaration, ExecutionNode's
    status is terminal-on-write and forensically meaningful as part of
    the immutable record.
    """

    # Identity — immutable
    node_id: UUID = Field(default_factory=uuid4)
    node_type: str = Field(default="ExecutionNode", frozen=True)
    schema_version: str = Field(default=LAYER_3_SCHEMA_VERSION)

    # Parent references — immutable
    workflow_id: UUID  # → WorkflowDeclaration
    episode_id: UUID   # → EpisodeNode (denormalized for query speed; §5)

    # Sequence — immutable
    sequence_index: int
    step_name: str

    # Execution record — immutable
    agent_id: str
    executed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: Optional[int] = None

    # Input/output state — immutable
    input_state: dict[str, Any] = Field(default_factory=dict)
    output_state: Optional[dict[str, Any]] = None

    # Terminal status — written once
    status: ExecutionStatus
    error_detail: Optional[dict[str, Any]] = None
    error_type: Optional[ErrorType] = None

    # Integrity
    content_hash: Optional[str] = None  # SHA3-256 of canonical preimage


class SkillInvocation(BaseModel):
    """A Layer 3 skill invocation record — Amendment v3.0 §6.

    Terminal-on-write (invariant L3-I3). Child of ExecutionNode;
    optional — an ExecutionNode may have zero SkillInvocation children.

    `skill_id` and `skill_source` are open behavioral-tier strings (§12);
    the protocol records what was chosen, not which values are valid.

    Hash preimage (§8): all fields except content_hash and registry_id.
    registry_id is excluded by design (§13.2) so that a future Skill
    Registry amendment can populate it via backfill without invalidating
    any existing SkillInvocation hash.
    """

    # Identity — immutable
    node_id: UUID = Field(default_factory=uuid4)
    node_type: str = Field(default="SkillInvocation", frozen=True)
    schema_version: str = Field(default=LAYER_3_SCHEMA_VERSION)

    # Parent references — immutable
    execution_node_id: UUID  # → ExecutionNode
    workflow_id: UUID        # → WorkflowDeclaration (denormalized)
    episode_id: UUID         # → EpisodeNode (denormalized)

    # Skill identity — open behavioral-tier surface (§6, §12)
    skill_id: str            # implementation-defined; no registry validation
    skill_source: str        # implementation-defined enum value
    skill_version: Optional[str] = None

    # Invocation record — immutable
    invoked_by: str
    invoked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: Optional[int] = None

    # Parameters & result — immutable
    input_parameters: dict[str, Any] = Field(default_factory=dict)
    output_result: Optional[dict[str, Any]] = None

    # Terminal status — written once
    status: SkillStatus
    error_detail: Optional[dict[str, Any]] = None

    # Reserved — Skill Registry bridge (§13.2). Excluded from content_hash.
    # Conforming implementations MUST leave this null until the future
    # Skill Registry amendment defines its semantics.
    registry_id: Optional[UUID] = None

    # Integrity
    content_hash: Optional[str] = None


# ── Governance ───────────────────────────────────────────────────────────────


class Layer3GovernanceError(Exception):
    """Raised when a Layer 3 operation violates governance rules from §3, §9."""


def enforce_workflow_status_transition(
    current: WorkflowStatus,
    target: WorkflowStatus,
) -> None:
    """Check whether a workflow status transition is permitted by the §10
    state machine.

    Raises Layer3GovernanceError on violation. Returns None on success.

    Permitted transitions:
        DECLARED → IN_PROGRESS, INTERRUPTED
        IN_PROGRESS → COMPLETED, FAILED, INTERRUPTED

    Terminal states (COMPLETED, FAILED, INTERRUPTED) have no outbound
    transitions; entering any of them closes the workflow permanently.
    """
    permitted: dict[WorkflowStatus, set[WorkflowStatus]] = {
        WorkflowStatus.DECLARED: {WorkflowStatus.IN_PROGRESS, WorkflowStatus.INTERRUPTED},
        WorkflowStatus.IN_PROGRESS: {
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.INTERRUPTED,
        },
        WorkflowStatus.COMPLETED: set(),
        WorkflowStatus.FAILED: set(),
        WorkflowStatus.INTERRUPTED: set(),
    }
    if target not in permitted[current]:
        raise Layer3GovernanceError(
            f"Workflow status transition {current.value} → {target.value} is "
            f"not permitted by Amendment v3.0 §10 state machine."
        )


def enforce_execution_error_consistency(node: ExecutionNode) -> None:
    """Check that an ExecutionNode's error fields are consistent with its
    status, per §5.

    Raises Layer3GovernanceError on violation. Returns None on success.

    Rule: when status is FAILED or INTERRUPTED, error_type MUST be set.
    error_detail SHOULD be set (recommended but not enforced — some
    failure modes legitimately produce no detail payload).

    A COMPLETED ExecutionNode MUST have error_type and error_detail both
    null.
    """
    if node.status == ExecutionStatus.COMPLETED:
        if node.error_type is not None or node.error_detail is not None:
            raise Layer3GovernanceError(
                "ExecutionNode with status=COMPLETED must have null "
                "error_type and error_detail (Amendment v3.0 §5)."
            )
    else:
        # FAILED or INTERRUPTED
        if node.error_type is None:
            raise Layer3GovernanceError(
                f"ExecutionNode with status={node.status.value} must have "
                f"error_type set (Amendment v3.0 §5)."
            )


# ── Content hash ─────────────────────────────────────────────────────────────


# WorkflowDeclaration hash preimage fields, in canonical order. Excludes
# status, status_updated_at, error_detail (the mutation surface) and
# content_hash itself. mandate_id is INCLUDED — it is immutable provenance
# per §4 hash preimage note.
_WORKFLOW_DECLARATION_HASH_FIELDS: tuple[str, ...] = (
    "node_id",
    "node_type",
    "schema_version",
    "episode_id",
    "intention_id",
    "mandate_id",
    "workflow_name",
    "workflow_version",
    "declared_by",
    "declared_at",
    "input_context",
    "expected_outputs",
    "timeout_ms",
)


# ExecutionNode hash preimage fields. All fields except content_hash.
# status is INCLUDED — terminal-on-write, forensically meaningful.
_EXECUTION_NODE_HASH_FIELDS: tuple[str, ...] = (
    "node_id",
    "node_type",
    "schema_version",
    "workflow_id",
    "episode_id",
    "sequence_index",
    "step_name",
    "agent_id",
    "executed_at",
    "duration_ms",
    "input_state",
    "output_state",
    "status",
    "error_detail",
    "error_type",
)


# SkillInvocation hash preimage fields. Excludes registry_id (§13.2
# forward-compatibility provision) and content_hash itself.
_SKILL_INVOCATION_HASH_FIELDS: tuple[str, ...] = (
    "node_id",
    "node_type",
    "schema_version",
    "execution_node_id",
    "workflow_id",
    "episode_id",
    "skill_id",
    "skill_source",
    "skill_version",
    "invoked_by",
    "invoked_at",
    "duration_ms",
    "input_parameters",
    "output_result",
    "status",
    "error_detail",
)


def compute_workflow_declaration_content_hash(node: WorkflowDeclaration) -> str:
    """SHA3-256 of the WorkflowDeclaration canonical preimage.

    Excludes status, status_updated_at, error_detail (the mutation
    surface per §4, §9 L3-I4). Excludes content_hash itself.
    """
    return hash_preimage(node, _WORKFLOW_DECLARATION_HASH_FIELDS)


def compute_execution_node_content_hash(node: ExecutionNode) -> str:
    """SHA3-256 of the ExecutionNode canonical preimage.

    Includes every field except content_hash itself. ExecutionNode is
    fully immutable (§9 L3-I3), so the entire field set commits.
    """
    return hash_preimage(node, _EXECUTION_NODE_HASH_FIELDS)


def compute_skill_invocation_content_hash(node: SkillInvocation) -> str:
    """SHA3-256 of the SkillInvocation canonical preimage.

    Excludes registry_id (§13.2 forward-compatibility) and content_hash
    itself. Populating registry_id later via Skill Registry backfill MUST
    NOT invalidate the hash.
    """
    return hash_preimage(node, _SKILL_INVOCATION_HASH_FIELDS)


def stamp_workflow_declaration_hash(node: WorkflowDeclaration) -> WorkflowDeclaration:
    """Compute and set content_hash on a WorkflowDeclaration. Returns the
    same instance for chaining. Re-stamping with unchanged immutable
    fields yields the same hash; mutations to the permitted three fields
    (status, status_updated_at, error_detail) do not change the hash."""
    node.content_hash = compute_workflow_declaration_content_hash(node)
    return node


def stamp_execution_node_hash(node: ExecutionNode) -> ExecutionNode:
    """Compute and set content_hash on an ExecutionNode. Returns the same
    instance for chaining."""
    node.content_hash = compute_execution_node_content_hash(node)
    return node


def stamp_skill_invocation_hash(node: SkillInvocation) -> SkillInvocation:
    """Compute and set content_hash on a SkillInvocation. Returns the same
    instance for chaining. Populating registry_id later does not affect
    the hash."""
    node.content_hash = compute_skill_invocation_content_hash(node)
    return node


# ── Audit delta payloads ─────────────────────────────────────────────────────


class WorkflowDeclaredDelta(BaseModel):
    """Forward + reverse delta for `CognitiveDeltaType.WORKFLOW_DECLARED`.

    Emitted when a WorkflowDeclaration is created by the workspace's
    designated CIA for workflow declarations (§3, §11).

    Reverse delta deletes the node by node_id. WorkflowDeclaration's
    mutation surface is restricted to status/status_updated_at/
    error_detail, so reversal is full node removal; no field-restoration
    state is required.
    """

    # Forward delta (what happened)
    workflow_id: str          # WorkflowDeclaration.node_id
    episode_id: str
    intention_id: Optional[str] = None
    mandate_id: Optional[str] = None
    declared_by: str
    declared_at: datetime
    content_hash: str

    # CIA attribution — mandatory per §11
    cia_identifier: str

    # Reverse delta (how to undo)
    reverse_delete_workflow_id: str


class ExecutionRecordedDelta(BaseModel):
    """Forward + reverse delta for `CognitiveDeltaType.EXECUTION_RECORDED`.

    Emitted when an ExecutionNode is created (§5, §11). ExecutionNodes
    are immutable (L3-I3), so reversal is deletion. Note that reversing
    an ExecutionNode write does not roll back the WorkflowDeclaration's
    auto-transition to IN_PROGRESS; that is a separate event observed
    via the next status mutation (or its absence).
    """

    execution_node_id: str
    workflow_id: str
    episode_id: str
    sequence_index: int
    agent_id: str
    status: ExecutionStatus
    executed_at: datetime
    content_hash: str

    cia_identifier: str

    reverse_delete_execution_node_id: str


class SkillInvokedDelta(BaseModel):
    """Forward + reverse delta for `CognitiveDeltaType.SKILL_INVOKED`.

    Emitted when a SkillInvocation is created (§6, §11). SkillInvocation
    is immutable (L3-I3); reversal is deletion. skill_source is captured
    in the delta payload to support audit-the-decision queries even
    after the node is deleted on reversal.
    """

    skill_invocation_id: str
    execution_node_id: str
    workflow_id: str
    episode_id: str
    skill_id: str
    skill_source: str
    invoked_by: str
    invoked_at: datetime
    status: SkillStatus
    content_hash: str

    cia_identifier: str

    reverse_delete_skill_invocation_id: str


class WorkflowClosedDelta(BaseModel):
    """Forward + reverse delta for `CognitiveDeltaType.WORKFLOW_CLOSED`.

    Emitted when WorkflowDeclaration.status transitions from IN_PROGRESS
    (or, in the no-step case, DECLARED) to a terminal state (COMPLETED,
    FAILED, INTERRUPTED). The forward delta records the new status and
    the timestamp; the reverse delta carries the prior status so that
    reversal restores it.

    NOTE on reversal: terminal-state transitions are not normally
    reversible at the protocol level (§10 forbids transitions out of
    terminal states). Implementations SHOULD treat WORKFLOW_CLOSED as
    effectively one-way; the reverse delta exists for audit-chain
    rollback consistency, not as a permitted operation.
    """

    workflow_id: str
    final_status: WorkflowStatus
    status_updated_at: datetime
    error_detail: Optional[dict[str, Any]] = None

    cia_identifier: str

    # Reverse delta (how to undo — see NOTE above)
    reverse_prior_status: WorkflowStatus
    reverse_prior_status_updated_at: datetime
    reverse_prior_error_detail: Optional[dict[str, Any]] = None


__all__ = [
    # Enums
    "WorkflowStatus",
    "ExecutionStatus",
    "SkillStatus",
    "ErrorType",
    "PrecedesEdgeType",
    # Schema version
    "LAYER_3_SCHEMA_VERSION",
    # Models
    "WorkflowDeclaration",
    "ExecutionNode",
    "SkillInvocation",
    # Governance
    "Layer3GovernanceError",
    "enforce_workflow_status_transition",
    "enforce_execution_error_consistency",
    # Hash functions
    "compute_workflow_declaration_content_hash",
    "compute_execution_node_content_hash",
    "compute_skill_invocation_content_hash",
    "stamp_workflow_declaration_hash",
    "stamp_execution_node_hash",
    "stamp_skill_invocation_hash",
    # Delta payloads
    "WorkflowDeclaredDelta",
    "ExecutionRecordedDelta",
    "SkillInvokedDelta",
    "WorkflowClosedDelta",
]
