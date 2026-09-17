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
SPEC §21 — Layer 3 Workflow & Execution DAG schema + governance unit tests.

Covers the protocol-core surface of `astp.core.workflow_execution`:
- Enum vocabulary (WorkflowStatus, ExecutionStatus, SkillStatus, ErrorType, PrecedesEdgeType)
- WorkflowDeclaration / ExecutionNode / SkillInvocation instantiation
- Hash preimage determinism + exclusion discipline (§8, §9)
- Immutability invariants (L3-I3, L3-I4, L3-I5 — enforced semantically here;
  full enforcement is wire-tier per implementation)
- Workflow status state machine (§10)
- ExecutionNode error-field consistency (§5)
- `CognitiveDeltaType` additions (WORKFLOW_DECLARED, EXECUTION_RECORDED,
  SKILL_INVOKED, WORKFLOW_CLOSED)
- Delta payload shapes

Adapter-layer behavior (Neo4j writes, audit emission, CIA enforcement) is
exercised by integration tests against a live implementation — protocol-core
tests here are pure / mock-free.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from astp.core.branching import CognitiveDeltaType
from astp.core.workflow_execution import (
    ErrorType,
    ExecutionNode,
    ExecutionRecordedDelta,
    ExecutionStatus,
    LAYER_3_SCHEMA_VERSION,
    Layer3GovernanceError,
    PrecedesEdgeType,
    SkillInvocation,
    SkillInvokedDelta,
    SkillStatus,
    WorkflowClosedDelta,
    WorkflowDeclaration,
    WorkflowDeclaredDelta,
    WorkflowStatus,
    compute_execution_node_content_hash,
    compute_skill_invocation_content_hash,
    compute_workflow_declaration_content_hash,
    enforce_execution_error_consistency,
    enforce_workflow_status_transition,
    stamp_execution_node_hash,
    stamp_skill_invocation_hash,
    stamp_workflow_declaration_hash,
)


# ─── Enum vocabulary ────────────────────────────────────────────────────────


class TestWorkflowStatus:
    def test_five_states_per_amendment_section_10(self):
        # SPEC §21 §10 declares exactly these five values.
        assert {s.value for s in WorkflowStatus} == {
            "DECLARED",
            "IN_PROGRESS",
            "COMPLETED",
            "FAILED",
            "INTERRUPTED",
        }


class TestExecutionStatus:
    def test_three_terminal_values(self):
        # ExecutionNode status is terminal-on-write (§5).
        assert {s.value for s in ExecutionStatus} == {
            "COMPLETED",
            "FAILED",
            "INTERRUPTED",
        }


class TestSkillStatus:
    def test_three_terminal_values(self):
        # SkillInvocation status is terminal-on-write (§6).
        assert {s.value for s in SkillStatus} == {
            "COMPLETED",
            "FAILED",
            "INTERRUPTED",
        }


class TestErrorType:
    def test_five_error_categories(self):
        assert {e.value for e in ErrorType} == {
            "AGENT_ERROR",
            "TIMEOUT",
            "DEPENDENCY_FAILURE",
            "SKILL_ERROR",
            "UNKNOWN",
        }


class TestPrecedesEdgeType:
    def test_three_edge_modes(self):
        # §7 PRECEDES edge property values.
        assert {p.value for p in PrecedesEdgeType} == {
            "SEQUENTIAL",
            "CONDITIONAL",
            "PARALLEL",
        }


class TestSchemaVersion:
    def test_layer_3_schema_version_is_3_0_0(self):
        # Layer 3 ships at schema version 3.0.0.
        assert LAYER_3_SCHEMA_VERSION == "3.0.0"


class TestCognitiveDeltaTypeAdditions:
    """SPEC §21 adds four Layer 3 audit events to the existing
    CognitiveDeltaType vocabulary. They must coexist with all prior
    values from BFM, cross-episode linking, and grouping amendments."""

    def test_layer_3_events_registered(self):
        assert CognitiveDeltaType.WORKFLOW_DECLARED.value == "WORKFLOW_DECLARED"
        assert CognitiveDeltaType.EXECUTION_RECORDED.value == "EXECUTION_RECORDED"
        assert CognitiveDeltaType.SKILL_INVOKED.value == "SKILL_INVOKED"
        assert CognitiveDeltaType.WORKFLOW_CLOSED.value == "WORKFLOW_CLOSED"

    def test_v2_link_events_still_present(self):
        # Regression: prior amendment values must not be displaced.
        assert CognitiveDeltaType.LINK_ACCEPTED.value == "LINK_ACCEPTED"
        assert CognitiveDeltaType.LINK_PROPOSED.value == "LINK_PROPOSED"

    def test_v2_grouping_events_still_present(self):
        assert (
            CognitiveDeltaType.MEMBERSHIP_RECORD_CREATED.value
            == "MEMBERSHIP_RECORD_CREATED"
        )

    def test_phase1_branch_events_still_present(self):
        assert CognitiveDeltaType.BRANCH_CREATED.value == "BRANCH_CREATED"


# ─── Factories ──────────────────────────────────────────────────────────────


def _make_workflow(**overrides) -> WorkflowDeclaration:
    base = {
        "episode_id": uuid4(),
        "workflow_name": "test_workflow",
        "declared_by": "runtime@test_workspace",
    }
    base.update(overrides)
    return WorkflowDeclaration(**base)


def _make_execution(workflow_id: UUID, episode_id: UUID, **overrides) -> ExecutionNode:
    base = {
        "workflow_id": workflow_id,
        "episode_id": episode_id,
        "sequence_index": 0,
        "step_name": "test_step",
        "agent_id": "claude-code",
        "input_state": {"x": 1},
        "status": ExecutionStatus.COMPLETED,
    }
    base.update(overrides)
    return ExecutionNode(**base)


def _make_skill(
    execution_node_id: UUID, workflow_id: UUID, episode_id: UUID, **overrides
) -> SkillInvocation:
    base = {
        "execution_node_id": execution_node_id,
        "workflow_id": workflow_id,
        "episode_id": episode_id,
        "skill_id": "fs.read_file",
        "skill_source": "CODING_AGENT",
        "invoked_by": "claude-code",
        "input_parameters": {"path": "/tmp/x"},
        "status": SkillStatus.COMPLETED,
    }
    base.update(overrides)
    return SkillInvocation(**base)


# ─── WorkflowDeclaration ────────────────────────────────────────────────────


class TestWorkflowDeclarationInstantiation:
    def test_required_fields_with_defaults(self):
        wf = _make_workflow()
        assert isinstance(wf.node_id, UUID)
        assert wf.node_type == "WorkflowDeclaration"
        assert wf.schema_version == "3.0.0"
        assert wf.status == WorkflowStatus.DECLARED  # default per §10
        assert wf.intention_id is None
        assert wf.mandate_id is None
        assert wf.workflow_version == "1.0.0"
        assert wf.content_hash is None  # not yet stamped

    def test_mandate_id_is_optional(self):
        # mandate_id is nullable (§4) — workflows not spawned from a BDI
        # delegation mandate simply omit it.
        wf = _make_workflow(mandate_id=None)
        assert wf.mandate_id is None
        wf2 = _make_workflow(mandate_id=uuid4())
        assert isinstance(wf2.mandate_id, UUID)


class TestWorkflowDeclarationHash:
    def test_determinism(self):
        wf = _make_workflow()
        h1 = compute_workflow_declaration_content_hash(wf)
        h2 = compute_workflow_declaration_content_hash(wf)
        assert h1 == h2
        assert len(h1) == 64  # SHA3-256 hex

    def test_excludes_status_mutation_surface_per_section_4(self):
        """SPEC §21 §4 + §8: status, status_updated_at,
        error_detail are the controlled mutation surface and MUST NOT
        contribute to content_hash. Mutating them must not change the
        hash, so the declaration's commit-time fingerprint survives
        state transitions."""
        wf = _make_workflow()
        baseline = compute_workflow_declaration_content_hash(wf)

        wf.status = WorkflowStatus.IN_PROGRESS
        wf.status_updated_at = datetime.now(timezone.utc)
        assert compute_workflow_declaration_content_hash(wf) == baseline

        wf.status = WorkflowStatus.FAILED
        wf.error_detail = {"reason": "test"}
        assert compute_workflow_declaration_content_hash(wf) == baseline

    def test_includes_mandate_id_even_when_null(self):
        """SPEC §21 §4 hash preimage note: mandate_id is immutable
        provenance, INCLUDED in the hash. A workflow with mandate_id=None
        must produce a different hash than the same workflow with a
        non-null mandate_id (the nullability is part of the immutable
        record)."""
        wf_a = _make_workflow(mandate_id=None)
        wf_b = _make_workflow(mandate_id=uuid4())
        # Make all other fields identical
        wf_b.node_id = wf_a.node_id
        wf_b.episode_id = wf_a.episode_id
        wf_b.declared_at = wf_a.declared_at
        wf_b.status_updated_at = wf_a.status_updated_at

        assert (
            compute_workflow_declaration_content_hash(wf_a)
            != compute_workflow_declaration_content_hash(wf_b)
        )

    def test_includes_intention_id(self):
        """Like mandate_id, intention_id is immutable provenance and
        belongs to the hash preimage."""
        intention = uuid4()
        wf_a = _make_workflow(intention_id=None)
        wf_b = _make_workflow(intention_id=intention)
        # Align other fields
        wf_b.node_id = wf_a.node_id
        wf_b.episode_id = wf_a.episode_id
        wf_b.declared_at = wf_a.declared_at
        wf_b.status_updated_at = wf_a.status_updated_at

        assert (
            compute_workflow_declaration_content_hash(wf_a)
            != compute_workflow_declaration_content_hash(wf_b)
        )

    def test_stamp_populates_content_hash(self):
        wf = _make_workflow()
        stamped = stamp_workflow_declaration_hash(wf)
        assert stamped is wf  # returns same instance
        assert wf.content_hash is not None
        assert len(wf.content_hash) == 64


# ─── ExecutionNode ──────────────────────────────────────────────────────────


class TestExecutionNodeInstantiation:
    def test_required_fields(self):
        wf = _make_workflow()
        node = _make_execution(wf.node_id, wf.episode_id)
        assert isinstance(node.node_id, UUID)
        assert node.node_type == "ExecutionNode"
        assert node.status == ExecutionStatus.COMPLETED
        assert node.error_type is None
        assert node.error_detail is None


class TestExecutionNodeHash:
    def test_determinism(self):
        wf = _make_workflow()
        node = _make_execution(wf.node_id, wf.episode_id)
        assert (
            compute_execution_node_content_hash(node)
            == compute_execution_node_content_hash(node)
        )

    def test_includes_status_per_section_5(self):
        """SPEC §21 §5: ExecutionNode.status is INCLUDED in the
        hash preimage — unlike WorkflowDeclaration, ExecutionNode's
        status is terminal-on-write and forensically meaningful as part
        of the immutable record."""
        wf = _make_workflow()
        node_completed = _make_execution(wf.node_id, wf.episode_id)
        node_failed = _make_execution(
            wf.node_id,
            wf.episode_id,
            status=ExecutionStatus.FAILED,
            error_type=ErrorType.AGENT_ERROR,
            error_detail={"reason": "test"},
        )
        # Align identity fields
        node_failed.node_id = node_completed.node_id
        node_failed.executed_at = node_completed.executed_at

        assert (
            compute_execution_node_content_hash(node_completed)
            != compute_execution_node_content_hash(node_failed)
        )

    def test_includes_input_state_and_output_state(self):
        wf = _make_workflow()
        a = _make_execution(wf.node_id, wf.episode_id, input_state={"x": 1})
        b = _make_execution(wf.node_id, wf.episode_id, input_state={"x": 2})
        b.node_id = a.node_id
        b.executed_at = a.executed_at
        assert (
            compute_execution_node_content_hash(a)
            != compute_execution_node_content_hash(b)
        )

    def test_stamp_populates_content_hash(self):
        wf = _make_workflow()
        node = _make_execution(wf.node_id, wf.episode_id)
        stamped = stamp_execution_node_hash(node)
        assert stamped is node
        assert node.content_hash is not None


# ─── SkillInvocation ────────────────────────────────────────────────────────


class TestSkillInvocationInstantiation:
    def test_required_fields(self):
        wf = _make_workflow()
        ex = _make_execution(wf.node_id, wf.episode_id)
        sk = _make_skill(ex.node_id, wf.node_id, wf.episode_id)
        assert isinstance(sk.node_id, UUID)
        assert sk.node_type == "SkillInvocation"
        assert sk.skill_id == "fs.read_file"
        assert sk.skill_source == "CODING_AGENT"
        assert sk.registry_id is None  # §13.2 — reserved, must be null
        assert sk.content_hash is None

    def test_skill_source_is_open_string(self):
        """SPEC §21 §6, §12: skill_source is implementation-defined.
        The protocol accepts any string value; conformance is about
        recording the chosen value, not constraining it."""
        wf = _make_workflow()
        ex = _make_execution(wf.node_id, wf.episode_id)
        for source in ["CODING_AGENT", "SDK_AGENT", "REGISTRY_CAPABILITY",
                       "CUSTOM_PROVIDER", "UNKNOWN", "anything-goes"]:
            sk = _make_skill(ex.node_id, wf.node_id, wf.episode_id, skill_source=source)
            assert sk.skill_source == source


class TestSkillInvocationHash:
    def test_excludes_registry_id_per_section_13_2(self):
        """SPEC §21 §13.2: registry_id is reserved for a future
        Skill Registry amendment and EXCLUDED from content_hash, so that
        backfill population (when the registry ships) does not invalidate
        any existing SkillInvocation hash."""
        wf = _make_workflow()
        ex = _make_execution(wf.node_id, wf.episode_id)
        sk = _make_skill(ex.node_id, wf.node_id, wf.episode_id)
        baseline = compute_skill_invocation_content_hash(sk)

        # Simulate a future backfill populating registry_id
        sk.registry_id = uuid4()
        assert compute_skill_invocation_content_hash(sk) == baseline

    def test_includes_skill_source(self):
        """Audit-the-decision (§12.2): whichever skill_source value the
        implementation chose, it MUST contribute to the hash so the
        record commits to the choice immutably."""
        wf = _make_workflow()
        ex = _make_execution(wf.node_id, wf.episode_id)
        a = _make_skill(ex.node_id, wf.node_id, wf.episode_id, skill_source="CODING_AGENT")
        b = _make_skill(ex.node_id, wf.node_id, wf.episode_id, skill_source="SDK_AGENT")
        b.node_id = a.node_id
        b.invoked_at = a.invoked_at
        assert (
            compute_skill_invocation_content_hash(a)
            != compute_skill_invocation_content_hash(b)
        )

    def test_stamp_populates_content_hash(self):
        wf = _make_workflow()
        ex = _make_execution(wf.node_id, wf.episode_id)
        sk = _make_skill(ex.node_id, wf.node_id, wf.episode_id)
        stamped = stamp_skill_invocation_hash(sk)
        assert stamped is sk
        assert sk.content_hash is not None


# ─── Status state machine ──────────────────────────────────────────────────


class TestWorkflowStatusTransitions:
    """SPEC §21 §10 state machine — permitted transitions only."""

    def test_declared_to_in_progress_permitted(self):
        enforce_workflow_status_transition(
            WorkflowStatus.DECLARED, WorkflowStatus.IN_PROGRESS
        )

    def test_declared_to_interrupted_permitted(self):
        # The "declared but never started → process killed" case.
        enforce_workflow_status_transition(
            WorkflowStatus.DECLARED, WorkflowStatus.INTERRUPTED
        )

    def test_in_progress_to_terminal_states_permitted(self):
        for terminal in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED,
                         WorkflowStatus.INTERRUPTED):
            enforce_workflow_status_transition(WorkflowStatus.IN_PROGRESS, terminal)

    def test_declared_to_completed_forbidden(self):
        # Skipping IN_PROGRESS is not permitted — close requires an
        # in-progress workflow (which auto-transitions on first step).
        with pytest.raises(Layer3GovernanceError):
            enforce_workflow_status_transition(
                WorkflowStatus.DECLARED, WorkflowStatus.COMPLETED
            )

    def test_terminal_states_have_no_outbound_transitions(self):
        # COMPLETED, FAILED, INTERRUPTED close the workflow permanently.
        for terminal in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED,
                         WorkflowStatus.INTERRUPTED):
            for target in WorkflowStatus:
                with pytest.raises(Layer3GovernanceError):
                    enforce_workflow_status_transition(terminal, target)


# ─── ExecutionNode error-field consistency ────────────────────────────────


class TestExecutionErrorConsistency:
    """SPEC §21 §5 error-field rules."""

    def test_completed_requires_null_error_fields(self):
        wf = _make_workflow()
        node = _make_execution(wf.node_id, wf.episode_id, status=ExecutionStatus.COMPLETED)
        enforce_execution_error_consistency(node)  # ok

        node.error_type = ErrorType.AGENT_ERROR
        with pytest.raises(Layer3GovernanceError):
            enforce_execution_error_consistency(node)

    def test_failed_requires_error_type(self):
        wf = _make_workflow()
        node = _make_execution(
            wf.node_id, wf.episode_id,
            status=ExecutionStatus.FAILED,
            error_type=ErrorType.AGENT_ERROR,
            error_detail={"trace": "..."},
        )
        enforce_execution_error_consistency(node)  # ok

        node.error_type = None
        with pytest.raises(Layer3GovernanceError):
            enforce_execution_error_consistency(node)

    def test_interrupted_requires_error_type(self):
        wf = _make_workflow()
        node = _make_execution(
            wf.node_id, wf.episode_id,
            status=ExecutionStatus.INTERRUPTED,
            error_type=ErrorType.TIMEOUT,
        )
        enforce_execution_error_consistency(node)  # ok

        node.error_type = None
        with pytest.raises(Layer3GovernanceError):
            enforce_execution_error_consistency(node)


# ─── Delta payloads ────────────────────────────────────────────────────────


class TestDeltaPayloads:
    """§11 audit event registry — every Layer 3 audit event carries a
    cia_identifier. The delta payload classes enforce that at construction
    time via required fields."""

    def test_workflow_declared_delta_requires_cia(self):
        with pytest.raises(ValidationError):
            WorkflowDeclaredDelta(
                workflow_id=str(uuid4()),
                episode_id=str(uuid4()),
                declared_by="agent",
                declared_at=datetime.now(timezone.utc),
                content_hash="x" * 64,
                # cia_identifier OMITTED — must fail
                reverse_delete_workflow_id=str(uuid4()),
            )

    def test_workflow_declared_delta_with_cia_succeeds(self):
        d = WorkflowDeclaredDelta(
            workflow_id=str(uuid4()),
            episode_id=str(uuid4()),
            declared_by="agent",
            declared_at=datetime.now(timezone.utc),
            content_hash="x" * 64,
            cia_identifier="runtime@host",
            reverse_delete_workflow_id=str(uuid4()),
        )
        assert d.cia_identifier == "runtime@host"
        # Optional provenance fields default to None
        assert d.intention_id is None
        assert d.mandate_id is None

    def test_execution_recorded_delta_shape(self):
        wf_id = str(uuid4())
        ex_id = str(uuid4())
        d = ExecutionRecordedDelta(
            execution_node_id=ex_id,
            workflow_id=wf_id,
            episode_id=str(uuid4()),
            sequence_index=0,
            agent_id="claude-code",
            status=ExecutionStatus.COMPLETED,
            executed_at=datetime.now(timezone.utc),
            content_hash="x" * 64,
            cia_identifier="runtime@host",
            reverse_delete_execution_node_id=ex_id,
        )
        assert d.execution_node_id == ex_id

    def test_skill_invoked_delta_carries_skill_source(self):
        """Audit-the-decision: the skill_source value chosen by the
        implementation must travel in the delta for post-hoc forensic
        queries, even if the SkillInvocation is later deleted on
        reversal."""
        d = SkillInvokedDelta(
            skill_invocation_id=str(uuid4()),
            execution_node_id=str(uuid4()),
            workflow_id=str(uuid4()),
            episode_id=str(uuid4()),
            skill_id="fs.read_file",
            skill_source="CODING_AGENT",
            invoked_by="claude-code",
            invoked_at=datetime.now(timezone.utc),
            status=SkillStatus.COMPLETED,
            content_hash="x" * 64,
            cia_identifier="runtime@host",
            reverse_delete_skill_invocation_id=str(uuid4()),
        )
        assert d.skill_source == "CODING_AGENT"

    def test_workflow_closed_delta_carries_prior_state(self):
        """§11: WORKFLOW_CLOSED reverse delta carries prior status +
        timestamp + error_detail so the audit chain can reconstruct
        pre-close state on rollback (even though terminal transitions
        are not normally reversed at the protocol level)."""
        prior_ts = datetime.now(timezone.utc)
        d = WorkflowClosedDelta(
            workflow_id=str(uuid4()),
            final_status=WorkflowStatus.COMPLETED,
            status_updated_at=datetime.now(timezone.utc),
            error_detail=None,
            cia_identifier="runtime@host",
            reverse_prior_status=WorkflowStatus.IN_PROGRESS,
            reverse_prior_status_updated_at=prior_ts,
            reverse_prior_error_detail=None,
        )
        assert d.reverse_prior_status == WorkflowStatus.IN_PROGRESS
        assert d.reverse_prior_status_updated_at == prior_ts
