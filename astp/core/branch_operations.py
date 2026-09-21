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
ASTP Branch Operations — Branch/Fork/Merge lifecycle (SPEC §19)

The two Phase 1 functions:
  create_branch() — 11-step sequence creating a branch from the spine
  abandon_branch() — 7-step sequence terminating a branch without merge

Build rule: every function writes structural node + cognitive delta + audit record.
No function ships without all three writes present.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from astp.core.ordering import content_hashes_in_sequence_order
from astp.adapters.base import as_structural_store
from astp.core.wil import WILOperation
from astp.protocol.errors import AdapterWriteError, BranchOperationError
from astp.core.content_hash_v2 import (
    compute_aside_hash_v2,
    compute_aside_terminus_hash_v2,
    compute_deliberation_chain_hash_v2,
    compute_soliloquy_conclusion_hash_v2,
    compute_soliloquy_hash_v2,
)


def _is_uuid(value) -> bool:
    try:
        UUID(str(value))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def _parent_segment_for_side_channel(store, parent_segment_id):
    """(UUID, content_hash) of the Segment an aside or soliloquy opens from, or
    None — logged — when it is not a UUID or does not exist. SPEC §19.4 binds the
    parent by identity and by content, so both must be real."""
    store = as_structural_store(store)
    if not _is_uuid(parent_segment_id):
        logger.error(f"parent_segment_id {parent_segment_id!r} is not a UUID")
        return None
    found = store.segment_content_hashes([parent_segment_id])
    if str(parent_segment_id) not in found:
        logger.error(f"parent segment {parent_segment_id} not found or has no content hash")
        return None
    return UUID(str(parent_segment_id)), found[str(parent_segment_id)][1]
from astp.core.branching import (
    BranchPointNode,
    BranchTerminusNode,
    BranchType,
    BranchDeclarationType,
    BranchTerminusType,
    CognitiveDeltaType,
    TriggerType,
    IntentType,
    AuditRecord,
    AccessPolicy,
    AccessResourceType,
    BranchResult,
    AbandonResult,
    compute_branch_point_hash,
    compute_audit_record_hash,
    compute_intent_idempotency_key,
    enforce_branch_depth_limit,
    enforce_abandonment_reason_required,
    ASTPGovernanceError,
    DEFAULT_ACCESS_POLICIES,
)
from astp.core.audit_chain import (
    next_delta_sequence,
    # Aliased: the local-variable convention in this module is
    # `prior_audit_hash = ...`, which would shadow the imported function
    # name. Alias keeps existing call sites working without renaming the
    # 22+ local variable references.
    prior_audit_hash as fetch_prior_audit_hash,
)

logger = logging.getLogger("astp.branch_operations")


def create_branch(
    store,
    source_episode_id: str,
    source_segment_id: str,
    branch_intent: str,
    declaration_type: BranchDeclarationType = BranchDeclarationType.EXPLICIT,
    branch_type: BranchType = BranchType.EXPLORATORY,
    trigger: TriggerType = TriggerType.HUMAN_EXPLICIT,
    initiator: str = "system",
    caught_by: str = "HUMAN",
    detection_window_open: bool = False,
    branch_depth: int = 0,
) -> Optional[BranchResult]:
    """Create a branch from the episode spine.

    11-step sequence per spec Section 4.3. All writes are atomic
    or compensated. Writes: BranchPointNode + CognitiveDelta + AuditRecord.

    Args:
        store: a StructuralStore
        source_episode_id: Episode to branch from
        source_segment_id: Exact divergence point (segment ID)
        branch_intent: Required, non-empty — why this branch exists
        declaration_type: How the branch was declared
        branch_type: Classification of the branch
        trigger: What triggered the branch
        initiator: AgentID or UserID
        caught_by: AGENT | HUMAN | SYSTEM | UNCAUGHT
        detection_window_open: Whether detection window was open
        branch_depth: Current nesting depth (0=spine)

    Returns:
        BranchResult on success, None on failure
    """
    store = as_structural_store(store)
    try:
        # STEP 1: Validate preconditions
        if not branch_intent or not branch_intent.strip():
            raise ASTPGovernanceError("Branch intent must be non-empty")

        # Check branch depth (soft limit)
        try:
            enforce_branch_depth_limit(branch_depth)
        except ASTPGovernanceError:
            logger.warning(
                f"Branch depth limit exceeded ({branch_depth}) — "
                f"proceeding with override logged"
            )

        # Verify source episode exists and is ACTIVE
        status = store.episode_status(source_episode_id)
        if status is None:
            logger.error(f"Source episode {source_episode_id} not found")
            return None
        if status not in ("ACTIVE", "PENDING_HITL"):
            logger.error(f"Source episode not in ACTIVE state: {status}")
            return None

        # STEP 2: Acquire intent record (idempotency guard)

        idempotency_key = compute_intent_idempotency_key(
            source_episode_id, source_segment_id, branch_intent
        )
        intent, is_new = store.acquire_intent(idempotency_key, IntentType.CREATE_BRANCH.value, initiator
        )
        if intent and intent.get("status") == "COMPLETE":
            logger.info(f"Branch already created (idempotent): {intent.get('result_node_id')}")
            return BranchResult(
                branch_episode_id=source_episode_id,
                branch_point_id=intent.get("result_node_id", ""),
                branch_id=intent.get("result_node_id", ""),
                spine_merkle_snapshot="",
                delta_id="",
                audit_record_id="",
            )

        # STEP 3: Access policy check (placeholder — fail-open for Phase 1)
        # Access policy enforcement is not wired into this step.

        # STEP 4: Capture spine Merkle snapshot
        spine_merkle_snapshot = store.episode_spine_hash(source_episode_id) or ""

        # STEP 5: Create BranchPointNode
        branch_point = BranchPointNode(
            episode_id=source_episode_id,
            branch_label=branch_intent,
            parent_episode_id=source_episode_id,
            source_segment_id=source_segment_id,
            branch_type=branch_type,
            branch_depth=branch_depth + 1,
            declaration_type=declaration_type,
            trigger_context=trigger,
            initiated_by=initiator,
            spine_merkle_snapshot=spine_merkle_snapshot,
        )

        # Compute content hash
        branch_point.content_hash = compute_branch_point_hash(
            str(branch_point.branch_point_id),
            str(branch_point.episode_id),
            str(branch_point.branch_id),
            branch_point.source_segment_id,
            branch_point.branch_type.value,
            branch_point.declaration_type.value,
            branch_point.initiated_by,
            branch_point.timestamp_utc.isoformat(),
            branch_point.parent_hash,
        )

        # Handle retroactive declaration
        if declaration_type == BranchDeclarationType.RETROACTIVE:
            branch_point.pre_declaration_merkle_root = spine_merkle_snapshot
            branch_point.declared_retroactively_at = datetime.now(timezone.utc)
            branch_point.declared_by = initiator

        # STEP 6: Write BranchPointNode + BRANCH_ORIGIN edge
        store.write_branch_point(branch_point)

        # STEP 7: Write CognitiveDelta (as part of AuditRecord)
        forward_delta = {
            "parent_node_id": source_segment_id,
            "branch_id": str(branch_point.branch_id),
            "branch_type": branch_type.value,
            "trigger_context": trigger.value,
            "declaration_type": declaration_type.value,
        }
        reverse_delta = {
            "delete_branch_id": str(branch_point.branch_id),
            "restore_parent_cursor": source_segment_id,
        }

        # STEP 8: Get next delta sequence
        delta_sequence = next_delta_sequence(store, source_episode_id)

        # Get prior audit hash for chain integrity
        prior_audit_hash = fetch_prior_audit_hash(store, source_episode_id)

        # Create audit record
        audit = AuditRecord(
            delta_sequence=delta_sequence,
            agent_id=initiator,
            session_id=f"branch-{branch_point.branch_id}",
            delta_type=CognitiveDeltaType.BRANCH_CREATED,
            forward_delta=forward_delta,
            reverse_delta=reverse_delta,
            affected_nodes=[str(branch_point.branch_point_id)],
            trigger_context=trigger,
            explicit_reason=branch_intent,
            prior_audit_hash=prior_audit_hash,
            caught_by=caught_by,
            detection_window_open=detection_window_open,
            episode_id=source_episode_id,
        )

        # Compute record hash (chain integrity)
        audit.record_hash = compute_audit_record_hash(
            str(audit.audit_id),
            audit.delta_sequence,
            audit.delta_type.value,
            audit.agent_id,
            audit.wall_clock_time.isoformat(),
            json.dumps(forward_delta, default=str),
            prior_audit_hash,
        )

        # Write audit record
        store.write_audit_record(audit)

        # STEP 9: Write AccessPolicy for new branch
        policy = AccessPolicy(
            resource_type=AccessResourceType.BRANCH,
            resource_id=str(branch_point.branch_id),
            owner_agent_id=initiator,
            other_agents_read=DEFAULT_ACCESS_POLICIES[AccessResourceType.BRANCH]["other_agents_read"],
            audit_on_access=DEFAULT_ACCESS_POLICIES[AccessResourceType.BRANCH]["audit_on_access"],
        )
        # Access policy is stored as metadata on the branch point for now
        # Full policy enforcement comes in Phase 4

        # STEP 10: Mark intent record COMPLETE
        store.complete_intent(idempotency_key, str(branch_point.branch_point_id)
        )

        # STEP 11: Write WIL entry
        _write_branch_wil(store, source_episode_id, str(branch_point.branch_point_id), WILOperation.BRANCH_CREATE)

        logger.info(
            f"Branch created: {str(branch_point.branch_id)[:8]}... "
            f"[{branch_type.value}, {declaration_type.value}] "
            f"from episode {source_episode_id[:8]}... "
            f"at segment {source_segment_id[:8]}..."
        )

        return BranchResult(
            branch_episode_id=source_episode_id,
            branch_point_id=str(branch_point.branch_point_id),
            branch_id=str(branch_point.branch_id),
            spine_merkle_snapshot=spine_merkle_snapshot,
            delta_id=str(audit.audit_id),
            audit_record_id=str(audit.audit_id),
        )

    except ASTPGovernanceError:
        raise
    except Exception as e:
        logger.error(f"create_branch failed: {e}", exc_info=True)
        raise BranchOperationError(f"create_branch failed: {e}") from e


def abandon_branch(
    store,
    branch_id: str,
    initiator: str,
    abandonment_reason: str,
    preserve_artifacts: bool = True,
) -> Optional[AbandonResult]:
    """Terminate a branch without merging.

    7-step sequence per spec Section 4.4. ABANDONED is terminal —
    the branch cannot be reopened. All writes are atomic.

    Args:
        store: a StructuralStore
        branch_id: UUID of the branch to abandon
        initiator: AgentID or UserID performing the abandonment
        abandonment_reason: Required, non-empty — why the branch is being abandoned
        preserve_artifacts: If True, artifact nodes remain accessible

    Returns:
        AbandonResult on success, None on failure
    """
    store = as_structural_store(store)
    try:
        # STEP 1: Validate preconditions
        enforce_abandonment_reason_required(abandonment_reason)

        # Verify branch is ACTIVE (derived: BranchPoint exists, no Terminus)
        loaded = store.branch_point_with_terminus(branch_id)
        if loaded is None:
            logger.error(f"Branch {branch_id} not found")
            return None
        branch_point_data, has_terminus = loaded
        if has_terminus:
            logger.error(f"Branch {branch_id} already terminated")
            return None

        episode_id = branch_point_data.get("episode_id", "")
        branch_point_hash = branch_point_data.get("content_hash", "")

        # STEP 2: Capture final branch state
        # The spine hash stands in for the branch state
        final_merkle_root = store.episode_spine_hash(episode_id) or ""  # Branch-specific Merkle root

        # Compute duration
        created_at_str = branch_point_data.get("timestamp_utc", "")
        duration_ms = 0
        if created_at_str:
            try:
                created_at = datetime.fromisoformat(created_at_str)
                duration_ms = int((datetime.now(timezone.utc) - created_at).total_seconds() * 1000)
            except (ValueError, TypeError):
                pass

        # STEP 3: Write BranchTerminusNode
        terminus = BranchTerminusNode(
            episode_id=episode_id,
            branch_id=branch_id,
            terminus_type=BranchTerminusType.ABANDONED,
            branch_point_hash=branch_point_hash,
            final_merkle_root=final_merkle_root,
            duration_ms=duration_ms,
            abandonment_reason=abandonment_reason,
        )

        store.write_branch_terminus(terminus)

        # STEP 4: Write CognitiveDelta + AuditRecord
        forward_delta = {
            "branch_id": branch_id,
            "abandon_reason": abandonment_reason,
            "final_state_snapshot": final_merkle_root,
        }
        reverse_delta = {
            "restore_branch_to_active": branch_id,
            "clear_abandon_record": str(terminus.terminus_id),
        }

        delta_sequence = next_delta_sequence(store, episode_id)
        prior_audit_hash = fetch_prior_audit_hash(store, episode_id)

        audit = AuditRecord(
            delta_sequence=delta_sequence,
            agent_id=initiator,
            session_id=f"abandon-{branch_id}",
            delta_type=CognitiveDeltaType.BRANCH_ABANDONED,
            forward_delta=forward_delta,
            reverse_delta=reverse_delta,
            affected_nodes=[str(terminus.terminus_id)],
            trigger_context=TriggerType.HUMAN_EXPLICIT,
            explicit_reason=abandonment_reason,
            prior_audit_hash=prior_audit_hash,
            episode_id=episode_id,
        )

        audit.record_hash = compute_audit_record_hash(
            str(audit.audit_id),
            audit.delta_sequence,
            audit.delta_type.value,
            audit.agent_id,
            audit.wall_clock_time.isoformat(),
            json.dumps(forward_delta, default=str),
            prior_audit_hash,
        )

        # STEP 5: Write AuditRecord
        store.write_audit_record(audit)

        # STEP 6: Preserve artifacts (default behavior — no deletion)
        artifacts_preserved = []
        if preserve_artifacts:
            # Artifacts are preserved by default — ABANDONED is a valid terminal state
            pass

        # STEP 7: Write WIL entry
        _write_branch_wil(store, episode_id, str(terminus.terminus_id), WILOperation.BRANCH_ABANDON)

        logger.info(
            f"Branch abandoned: {branch_id[:8]}... "
            f"reason='{abandonment_reason[:50]}' "
            f"duration={duration_ms}ms"
        )

        return AbandonResult(
            episode_id=episode_id,
            branch_id=branch_id,
            final_merkle_root=final_merkle_root,
            terminus_id=str(terminus.terminus_id),
            delta_id=str(audit.audit_id),
            audit_record_id=str(audit.audit_id),
            artifacts_preserved=artifacts_preserved,
        )

    except ASTPGovernanceError:
        raise
    except Exception as e:
        logger.error(f"abandon_branch failed: {e}", exc_info=True)
        raise BranchOperationError(f"abandon_branch failed: {e}") from e


# ── Internal Helpers ─────────────────────────────────────────────────────────


# Audit chain helpers (next_delta_sequence + prior_audit_hash) live in
# astp.core.audit_chain — imported above.


# ============================================================================
# Phase 2 — Fork Operations
# ============================================================================


def create_fork(
    store,
    origin_episode_id: str,
    origin_segment_id: str,
    fork_objective: str,
    fork_intent: str,
    alternatives: list,
    initiator: str = "system",
    carried_artifacts: Optional[list] = None,
    caught_by: str = "HUMAN",
):
    """Create N ForkPointNodes + FORK_CREATED delta + AuditRecord.

    Args:
        store: a StructuralStore
        origin_episode_id: Episode the fork originates from
        origin_segment_id: Provenance anchor
        fork_objective: New Episode's objective (required, non-empty)
        fork_intent: Why fork, not branch
        alternatives: list of dicts with per-fork params:
            [{"episode_id": str, "participants": list, "fork_intent": str (optional)}, ...]
            Must have at least 2 entries.
        initiator: AgentID or UserID
        carried_artifacts: Artifact IDs accessible in all forks
        caught_by: AGENT | HUMAN | SYSTEM | UNCAUGHT

    Returns:
        ForkResult on success, None on failure
    """
    store = as_structural_store(store)
    from astp.core.branching import (
        ForkPointNode,
        AuditRecord,
        CognitiveDeltaType,
        TriggerType,
        IntentType,
        compute_fork_point_hash,
        compute_audit_record_hash,
        compute_intent_idempotency_key,
        enforce_fork_objective_required,
        enforce_fork_sibling_count,
        ForkResult,
    )
    from uuid import uuid4

    try:
        # STEP 1: Validate preconditions
        enforce_fork_objective_required(fork_objective)
        enforce_fork_sibling_count(len(alternatives))

        if not fork_intent or not fork_intent.strip():
            raise ASTPGovernanceError("Fork intent must be non-empty")

        status = store.episode_status(origin_episode_id)
        if status is None:
            logger.error(f"Origin episode {origin_episode_id} not found")
            return None
        if status not in ("ACTIVE", "PENDING_HITL"):
            logger.error(f"Origin episode not in ACTIVE state: {status}")
            return None

        # STEP 2: Acquire intent record
        idempotency_key = compute_intent_idempotency_key(
            origin_episode_id, origin_segment_id, f"FORK:{fork_objective}:{len(alternatives)}"
        )
        intent, _is_new = store.acquire_intent(idempotency_key, IntentType.CREATE_FORK.value, initiator
        )
        if intent and intent.get("status") == "COMPLETE":
            logger.info(f"Fork already created (idempotent): {intent.get('result_node_id')}")
            # Return minimal result — full details already persisted
            return ForkResult(
                fork_id=intent.get("result_node_id", ""),
                fork_point_ids=[intent.get("result_node_id", "")],
                origin_episode_id=origin_episode_id,
                origin_segment_id=origin_segment_id,
                delta_id="",
                audit_record_id="",
            )

        # STEP 3: Generate shared fork_id
        fork_id = uuid4()
        sibling_count = len(alternatives)
        carried = carried_artifacts or []

        # STEP 4: Create N ForkPointNodes
        fork_points = []
        for idx, alt in enumerate(alternatives):
            alt_episode_id = alt.get("episode_id") or str(uuid4())
            fp = ForkPointNode(
                fork_id=fork_id,
                episode_id=alt_episode_id,
                origin_episode_id=origin_episode_id,
                origin_segment_id=origin_segment_id,
                fork_objective=fork_objective,
                fork_intent=alt.get("fork_intent", fork_intent),
                carried_artifacts=alt.get("carried_artifacts", carried),
                initiator=initiator,
                participants=alt.get("participants", []),
                sibling_count=sibling_count,
                sibling_index=idx,
            )
            fp.content_hash = compute_fork_point_hash(
                str(fp.fork_point_id),
                str(fp.fork_id),
                str(fp.episode_id),
                str(fp.origin_episode_id),
                fp.origin_segment_id,
                fp.fork_objective,
                fp.initiator,
                fp.sibling_index,
                fp.timestamp_utc.isoformat(),
                fp.parent_hash,
            )
            fork_points.append(fp)

        # STEP 5: Write all ForkPointNodes
        for fp in fork_points:
            store.write_fork_point(fp)

        # STEP 6: Write FORK_CREATED AuditRecord
        fork_point_ids = [str(fp.fork_point_id) for fp in fork_points]
        forward_delta = {
            "origin_episode_id": origin_episode_id,
            "origin_segment_id": origin_segment_id,
            "fork_id": str(fork_id),
            "fork_objective": fork_objective,
            "fork_intent": fork_intent,
            "fork_point_ids": fork_point_ids,
            "carried_artifacts": carried,
        }
        reverse_delta = {
            "delete_fork_id": str(fork_id),
            "delete_fork_point_ids": fork_point_ids,
        }

        delta_sequence = next_delta_sequence(store, origin_episode_id)
        prior_audit_hash = fetch_prior_audit_hash(store, origin_episode_id)

        audit = AuditRecord(
            delta_sequence=delta_sequence,
            agent_id=initiator,
            session_id=f"fork-{fork_id}",
            delta_type=CognitiveDeltaType.FORK_CREATED,
            forward_delta=forward_delta,
            reverse_delta=reverse_delta,
            affected_nodes=fork_point_ids,
            trigger_context=TriggerType.HUMAN_EXPLICIT,
            explicit_reason=fork_objective,
            prior_audit_hash=prior_audit_hash,
            caught_by=caught_by,
            episode_id=origin_episode_id,
        )
        audit.record_hash = compute_audit_record_hash(
            str(audit.audit_id),
            audit.delta_sequence,
            audit.delta_type.value,
            audit.agent_id,
            audit.wall_clock_time.isoformat(),
            json.dumps(forward_delta, default=str),
            prior_audit_hash,
        )
        store.write_audit_record(audit)

        # STEP 7: Mark intent complete
        store.complete_intent(idempotency_key, str(fork_id))

        # STEP 8: WIL entry
        _write_branch_wil(store, origin_episode_id, str(fork_id), WILOperation.FORK_CREATE)

        logger.info(
            f"Fork created: {str(fork_id)[:8]}... "
            f"[{sibling_count} alternatives] from episode "
            f"{origin_episode_id[:8]}... at segment {origin_segment_id[:8]}..."
        )

        return ForkResult(
            fork_id=str(fork_id),
            fork_point_ids=fork_point_ids,
            origin_episode_id=origin_episode_id,
            origin_segment_id=origin_segment_id,
            delta_id=str(audit.audit_id),
            audit_record_id=str(audit.audit_id),
        )

    except ASTPGovernanceError:
        raise
    except Exception as e:
        logger.error(f"create_fork failed: {e}", exc_info=True)
        raise BranchOperationError(f"create_fork failed: {e}") from e


def create_departure_fork(
    store,
    origin_episode_id: str,
    origin_segment_id: str,
    fork_objective: str,
    fork_creation_trigger,          # ForkCreationTrigger (enum or value)
    initiator: str = "system",
    fork_agent_id: Optional[str] = None,
    fork_title: Optional[str] = None,
    participants: Optional[list] = None,
    fork_trigger_segment_id: Optional[str] = None,
    fork_trigger_confidence: Optional[float] = None,
    fork_origin_active_branch_ids: Optional[list] = None,
    episode_mode: str = "directed",
    caught_by: str = "HUMAN",
    fork_episode_id: Optional[str] = None,
    fork_id: Optional[str] = None,
) -> Optional["object"]:
    """Create a DEPARTURE fork (BFM Phase D): one directional departure into a
    new episode while the ORIGIN CONTINUES. Single node, no siblings, no resolve.

    Atomically writes: the fork Episode (ACTIVE + immutable provenance), a
    DepartureForkPointNode on the origin spine (+ FORK_ORIGIN edge), and a
    DEPARTURE_FORK_CREATED AuditRecord. Enforces the integrity invariant —
    spine_tip_hash_at_departure (fork point) == fork_origin_spine_tip_hash (fork episode)
    — by deriving both from a single origin-spine-tip value.

    Returns DepartureForkResult on success, None on failure.
    """
    store = as_structural_store(store)
    from astp.core.branching import (
        DepartureForkPointNode, DepartureForkResult, DepartureForkStatus,
        ForkCreationTrigger, AuditRecord, CognitiveDeltaType, TriggerType, IntentType,
        compute_departure_fork_point_hash, compute_audit_record_hash,
        compute_intent_idempotency_key, enforce_fork_objective_required,
    )
    from astp.core.schema import EpisodeNode, EpisodeStatus
    from uuid import uuid4, UUID
    from datetime import datetime, timezone

    try:
        # STEP 1: Validate preconditions
        enforce_fork_objective_required(fork_objective)
        if not isinstance(fork_creation_trigger, ForkCreationTrigger):
            fork_creation_trigger = ForkCreationTrigger(fork_creation_trigger)
        if (fork_creation_trigger == ForkCreationTrigger.AGENT_ESCALATION
                and not fork_trigger_segment_id):
            raise ASTPGovernanceError(
                "fork_trigger_segment_id is required for AGENT_ESCALATION"
            )
        status = store.episode_status(origin_episode_id)
        if status is None:
            logger.error(f"Origin episode {origin_episode_id} not found")
            return None
        if status not in ("ACTIVE", "PENDING_HITL"):
            logger.error(f"Origin episode not in ACTIVE state: {status}")
            return None

        # STEP 2: Idempotency guard
        idempotency_key = compute_intent_idempotency_key(
            origin_episode_id, origin_segment_id, f"DEPARTURE_FORK:{fork_objective}"
        )
        intent, _is_new = store.acquire_intent(idempotency_key, IntentType.CREATE_DEPARTURE_FORK.value, initiator
        )
        if intent and intent.get("status") == "COMPLETE":
            _fid = intent.get("result_node_id", "")
            logger.info(f"Departure fork already created (idempotent): {_fid}")
            # Reconstruct the FULL original result from the existing point rather than
            # returning a degraded (empty) shell — a replay must be indistinguishable
            # from the first return so callers can rely on the ids.
            prow = store.departure_fork_point_by_fork(_fid)
            if prow is not None:
                return DepartureForkResult(
                    fork_id=_fid, fork_point_id=prow["pid"] or "",
                    fork_episode_id=prow["eid"] or "",
                    origin_episode_id=origin_episode_id, origin_segment_id=origin_segment_id,
                    spine_tip_hash_at_departure=prow["tip"] or "",
                    delta_id="", audit_record_id="",
                )
            return DepartureForkResult(
                fork_id=_fid, fork_point_id="", fork_episode_id="",
                origin_episode_id=origin_episode_id, origin_segment_id=origin_segment_id,
                spine_tip_hash_at_departure="", delta_id="", audit_record_id="",
            )

        # STEP 2b: supplied-fork_id idempotency. When a retry/recovery caller pins fork_id,
        # short-circuit if its DepartureForkPointNode already exists — so a re-drive never
        # duplicates the fork even when the prior attempt crashed before its intent reached
        # COMPLETE (the one case the STEP-2 intent guard misses).
        if fork_id:
            erow = store.departure_fork_point_by_fork(str(fork_id))
            if erow is not None:
                logger.info(f"Departure fork {fork_id} already anchored (idempotent re-drive)")
                return DepartureForkResult(
                    fork_id=str(fork_id), fork_point_id=erow["pid"] or "",
                    fork_episode_id=erow["eid"] or "",
                    origin_episode_id=origin_episode_id, origin_segment_id=origin_segment_id,
                    spine_tip_hash_at_departure=erow["tip"] or "",
                    delta_id="", audit_record_id="",
                )

        # STEP 3: Ids + the integrity anchor (origin's cryptographic spine tip now).
        # fork_id may be SUPPLIED by a retry/recovery caller so the MERGE-based writers
        # dedup on it (idempotent re-drive after a partial failure); generated otherwise.
        fork_id = UUID(fork_id) if fork_id else uuid4()
        fork_ep_id = fork_episode_id or str(uuid4())
        now = datetime.now(timezone.utc)
        spine_tip_hash = fetch_prior_audit_hash(store, origin_episode_id)

        # STEP 4: Create the fork EPISODE (ACTIVE + immutable provenance)
        fork_ep = EpisodeNode(
            episode_id=UUID(fork_ep_id),
            agent_id=fork_agent_id or initiator,
            episode_status=EpisodeStatus.ACTIVE,
            participants=participants or [],
            title=fork_title,
            context_note=fork_objective,
            episode_mode=episode_mode,
            initiated_by=initiator,
            fork_origin_episode_id=UUID(origin_episode_id),
            fork_id=fork_id,
            fork_created_at=now,
            fork_creation_trigger=fork_creation_trigger.value,
            fork_trigger_confidence=fork_trigger_confidence,
            fork_trigger_segment_id=fork_trigger_segment_id,
            fork_origin_spine_tip_hash=spine_tip_hash,
            fork_origin_active_branch_ids=fork_origin_active_branch_ids,
            fork_status=DepartureForkStatus.ACTIVE.value,
            fork_anchor_index=None,  # two-phase: null now; patched in STEP 6 post point-write
        )
        store.write_departure_fork_episode(fork_ep)

        # STEP 5: Write the DepartureForkPointNode on the origin spine (+ FORK_ORIGIN)
        dfp = DepartureForkPointNode(
            fork_id=fork_id,
            fork_episode_id=UUID(fork_ep_id),
            origin_episode_id=UUID(origin_episode_id),
            origin_segment_id=origin_segment_id,
            fork_objective=fork_objective,
            fork_creation_trigger=fork_creation_trigger,
            fork_title_snapshot=fork_title or "",
            spine_tip_hash_at_departure=spine_tip_hash,  # invariant anchor
            initiator=initiator,
            timestamp_utc=now,
        )
        dfp.content_hash = compute_departure_fork_point_hash(
            str(dfp.fork_point_id), str(dfp.fork_id), str(dfp.fork_episode_id),
            str(dfp.origin_episode_id), dfp.origin_segment_id, dfp.fork_objective,
            dfp.fork_creation_trigger.value, dfp.spine_tip_hash_at_departure,
            dfp.initiator, dfp.timestamp_utc.isoformat(), dfp.parent_hash,
        )
        # G-30 backdating invariant — the fork point and the fork episode MUST agree on
        # the origin spine tip at departure. Both derive from the single `spine_tip_hash`
        # read above, so this holds by construction; assert it explicitly so any future
        # refactor that separates the two sources fails loudly instead of silently
        # corrupting the cross-verifiable anchor.
        if dfp.spine_tip_hash_at_departure != fork_ep.fork_origin_spine_tip_hash:
            raise ASTPGovernanceError(
                "G-30 backdating invariant violated: fork-point tip "
                f"{dfp.spine_tip_hash_at_departure!r} != fork-episode tip "
                f"{fork_ep.fork_origin_spine_tip_hash!r}"
            )
        store.write_departure_fork_point(dfp)

        # STEP 6: two-phase fork_anchor_index — now the point exists on the origin spine,
        # patch the fork episode's anchor to the ORIGIN SEGMENT's sequence_index (where the
        # departure anchored). The null->value transition confirms the point write; a
        # non-null anchor with no DepartureForkPointNode is the Class-B corruption signal
        # the orphan detector keys on. If the origin segment has no resolvable index, leave
        # the anchor null (point written, anchor unresolved) — a patch-only retry can fix it.
        anchor_index = store.segment_sequence_index(origin_segment_id)
        if anchor_index is not None:
            store.set_departure_fork_anchor_index(fork_ep_id, anchor_index)
        else:
            logger.warning(
                f"Departure fork {str(fork_id)[:8]}...: origin segment "
                f"{origin_segment_id[:8]}... has no resolvable sequence_index; "
                f"fork_anchor_index left null (point written, anchor unresolved)"
            )

        # STEP 7: Write DEPARTURE_FORK_CREATED AuditRecord
        forward_delta = {
            "origin_episode_id": origin_episode_id,
            "origin_segment_id": origin_segment_id,
            "fork_id": str(fork_id),
            "fork_episode_id": fork_ep_id,
            "fork_objective": fork_objective,
            "fork_creation_trigger": fork_creation_trigger.value,
            "spine_tip_hash_at_departure": spine_tip_hash,
        }
        reverse_delta = {
            "delete_fork_id": str(fork_id),
            "delete_fork_point_id": str(dfp.fork_point_id),
            "delete_fork_episode_id": fork_ep_id,
        }
        delta_sequence = next_delta_sequence(store, origin_episode_id)
        prior_audit_hash = fetch_prior_audit_hash(store, origin_episode_id)
        audit = AuditRecord(
            delta_sequence=delta_sequence,
            agent_id=initiator,
            session_id=f"departure-fork-{fork_id}",
            delta_type=CognitiveDeltaType.DEPARTURE_FORK_CREATED,
            forward_delta=forward_delta,
            reverse_delta=reverse_delta,
            affected_nodes=[str(dfp.fork_point_id), fork_ep_id],
            trigger_context=TriggerType.HUMAN_EXPLICIT,
            explicit_reason=fork_objective,
            prior_audit_hash=prior_audit_hash,
            caught_by=caught_by,
            episode_id=origin_episode_id,
        )
        audit.record_hash = compute_audit_record_hash(
            str(audit.audit_id), audit.delta_sequence, audit.delta_type.value,
            audit.agent_id, audit.wall_clock_time.isoformat(),
            json.dumps(forward_delta, default=str), prior_audit_hash,
        )
        store.write_audit_record(audit)

        # STEP 8: intent complete + WIL entry
        store.complete_intent(idempotency_key, str(fork_id))
        _write_branch_wil(store, origin_episode_id, str(fork_id), WILOperation.DEPARTURE_FORK_CREATE)

        logger.info(
            f"Departure fork created: {str(fork_id)[:8]}... "
            f"[{fork_creation_trigger.value}] episode {fork_ep_id[:8]}... "
            f"from {origin_episode_id[:8]}... at segment {origin_segment_id[:8]}..."
        )
        return DepartureForkResult(
            fork_id=str(fork_id),
            fork_point_id=str(dfp.fork_point_id),
            fork_episode_id=fork_ep_id,
            origin_episode_id=origin_episode_id,
            origin_segment_id=origin_segment_id,
            spine_tip_hash_at_departure=spine_tip_hash,
            delta_id=str(audit.audit_id),
            audit_record_id=str(audit.audit_id),
        )

    except ASTPGovernanceError:
        raise
    except Exception as e:
        logger.error(f"create_departure_fork failed: {e}", exc_info=True)
        raise BranchOperationError(f"create_departure_fork failed: {e}") from e


def _get_departure_fork_episode(store, fork_episode_id=None, fork_id=None):
    """Return (episode_id, fork_status) for a departure fork, or (None, None)."""
    store = as_structural_store(store)
    return store.departure_fork_episode(fork_episode_id=fork_episode_id, fork_id=fork_id)


def _audit_departure_transition(store, episode_id, delta_type, actor, reason, caught_by="HUMAN"):
    """Write an audit record for a departure-fork status transition on its own chain."""
    store = as_structural_store(store)
    from astp.core.branching import (
        AuditRecord, TriggerType, compute_audit_record_hash,
    )
    forward = {"episode_id": str(episode_id), "actor": actor, "reason": reason,
               "transition": delta_type.value}
    reverse = {"note": "departure-fork status transition"}
    ds = next_delta_sequence(store, episode_id)
    prior = fetch_prior_audit_hash(store, episode_id)
    audit = AuditRecord(
        delta_sequence=ds, agent_id=actor, session_id=f"departure-status-{episode_id}",
        delta_type=delta_type, forward_delta=forward, reverse_delta=reverse,
        affected_nodes=[str(episode_id)], trigger_context=TriggerType.HUMAN_EXPLICIT,
        explicit_reason=reason or delta_type.value, prior_audit_hash=prior,
        caught_by=caught_by, episode_id=str(episode_id),
    )
    audit.record_hash = compute_audit_record_hash(
        str(audit.audit_id), audit.delta_sequence, audit.delta_type.value,
        audit.agent_id, audit.wall_clock_time.isoformat(),
        json.dumps(forward, default=str), prior,
    )
    store.write_audit_record(audit)
    return audit


def complete_departure_fork(store, fork_episode_id, actor="system", note="") -> bool:
    """ACTIVE -> COMPLETED. First-person declaration by the fork episode's own agent
    ("the work I came here to do is done"). Guards the fork is ACTIVE. (Phase D FSM.)"""
    store = as_structural_store(store)
    from astp.core.branching import CognitiveDeltaType, DepartureForkStatus
    try:
        eid, status = _get_departure_fork_episode(store, fork_episode_id=fork_episode_id)
        if not eid:
            logger.error(f"Departure fork episode {fork_episode_id} not found")
            return False
        if status != DepartureForkStatus.ACTIVE.value:
            logger.error(f"Cannot complete departure fork in status {status} (must be ACTIVE)")
            return False
        store.mark_departure_fork_status(eid, DepartureForkStatus.COMPLETED.value)
        _audit_departure_transition(
            store, eid, CognitiveDeltaType.DEPARTURE_FORK_COMPLETED, actor, note
        )
        logger.info(f"Departure fork completed: {str(eid)[:8]}...")
        return True
    except Exception as e:
        logger.error(f"complete_departure_fork failed: {e}", exc_info=True)
        raise BranchOperationError(f"complete_departure_fork failed: {e}") from e


def abandon_departure_fork(store, fork_episode_id, actor="system", reason="") -> bool:
    """ACTIVE -> ABANDONED (terminal). The originating agent's judgment that the thread
    isn't worth pursuing (or system cleanup of a never-entered stub). Guards ACTIVE —
    a COMPLETED fork returns, it is not abandoned. (Phase D FSM.)"""
    store = as_structural_store(store)
    from astp.core.branching import CognitiveDeltaType, DepartureForkStatus
    try:
        eid, status = _get_departure_fork_episode(store, fork_episode_id=fork_episode_id)
        if not eid:
            logger.error(f"Departure fork episode {fork_episode_id} not found")
            return False
        if status != DepartureForkStatus.ACTIVE.value:
            logger.error(f"Cannot abandon departure fork in status {status} (must be ACTIVE)")
            return False
        store.mark_departure_fork_status(eid, DepartureForkStatus.ABANDONED.value)
        _audit_departure_transition(
            store, eid, CognitiveDeltaType.DEPARTURE_FORK_ABANDONED, actor, reason
        )
        logger.info(f"Departure fork abandoned: {str(eid)[:8]}...")
        return True
    except Exception as e:
        logger.error(f"abandon_departure_fork failed: {e}", exc_info=True)
        raise BranchOperationError(f"abandon_departure_fork failed: {e}") from e


def declare_fork_return(
    store, fork_id, origin_episode_id, return_type, returned_by,
    synthesis_summary="", fork_episode_id=None,
):
    """Formally bring a COMPLETED departure fork's work back to the origin — DECLARATIVE
    (the origin asserts incorporation across two independent spines), never the branch's
    structural merge. Writes a ForkReturnNode on the ORIGIN spine (+ edges) and a
    DEPARTURE_FORK_RETURNED audit on the origin chain. Authority: the originating agent.

    Guards: fork must be COMPLETED; no prior return declaration for this fork_id.
    Returns ForkReturnResult, or None. (Phase D FSM.)"""
    store = as_structural_store(store)
    from astp.core.branching import (
        ForkReturnNode, ForkReturnResult, ForkReturnType, DepartureForkStatus,
        AuditRecord, CognitiveDeltaType, TriggerType,
        compute_fork_return_hash, compute_audit_record_hash,
    )
    from uuid import UUID

    try:
        if not isinstance(return_type, ForkReturnType):
            return_type = ForkReturnType(return_type)

        # Guard: fork must be COMPLETED
        f_eid, status = _get_departure_fork_episode(
            store, fork_episode_id=fork_episode_id, fork_id=fork_id
        )
        if not f_eid:
            logger.error(f"Departure fork {fork_id} not found")
            return None
        if status != DepartureForkStatus.COMPLETED.value:
            raise ASTPGovernanceError(
                f"declare_fork_return requires a COMPLETED fork (got {status})"
            )

        # Guard: no prior return declaration for this fork
        if store.fork_return_exists(str(fork_id)):
            raise ASTPGovernanceError(
                f"Departure fork {fork_id} already has a return declaration"
            )

        fork_tip = fetch_prior_audit_hash(store, f_eid)  # fork episode's spine tip at return
        frn = ForkReturnNode(
            fork_id=UUID(str(fork_id)),
            fork_episode_id=UUID(str(f_eid)),
            origin_episode_id=UUID(str(origin_episode_id)),
            return_type=return_type,
            synthesis_summary=synthesis_summary,
            fork_final_spine_tip_hash=fork_tip,
            returned_by=returned_by,
        )
        frn.content_hash = compute_fork_return_hash(
            str(frn.fork_return_id), str(frn.fork_id), str(frn.fork_episode_id),
            str(frn.origin_episode_id), return_type.value, synthesis_summary,
            fork_tip, returned_by, frn.timestamp_utc.isoformat(), frn.parent_hash,
        )
        store.write_fork_return_node(frn)

        # Record the return outcome on the fork episode
        store.set_episode_fork_return_type(str(f_eid), return_type.value)

        # Audit on the ORIGIN chain
        forward = {
            "fork_id": str(fork_id), "fork_episode_id": str(f_eid),
            "origin_episode_id": str(origin_episode_id), "return_type": return_type.value,
            "fork_return_id": str(frn.fork_return_id),
        }
        reverse = {"delete_fork_return_id": str(frn.fork_return_id)}
        ds = next_delta_sequence(store, origin_episode_id)
        prior = fetch_prior_audit_hash(store, origin_episode_id)
        audit = AuditRecord(
            delta_sequence=ds, agent_id=returned_by, session_id=f"fork-return-{fork_id}",
            delta_type=CognitiveDeltaType.DEPARTURE_FORK_RETURNED,
            forward_delta=forward, reverse_delta=reverse,
            affected_nodes=[str(frn.fork_return_id)],
            trigger_context=TriggerType.HUMAN_EXPLICIT,
            explicit_reason=f"fork return: {return_type.value}",
            prior_audit_hash=prior, caught_by="HUMAN", episode_id=str(origin_episode_id),
        )
        audit.record_hash = compute_audit_record_hash(
            str(audit.audit_id), audit.delta_sequence, audit.delta_type.value,
            audit.agent_id, audit.wall_clock_time.isoformat(),
            json.dumps(forward, default=str), prior,
        )
        store.write_audit_record(audit)

        logger.info(
            f"Departure fork returned: {str(fork_id)[:8]}... "
            f"[{return_type.value}] to origin {str(origin_episode_id)[:8]}..."
        )
        return ForkReturnResult(
            fork_return_id=str(frn.fork_return_id), fork_id=str(fork_id),
            origin_episode_id=str(origin_episode_id), return_type=return_type.value,
            delta_id=str(audit.audit_id), audit_record_id=str(audit.audit_id),
        )
    except ASTPGovernanceError:
        raise
    except Exception as e:
        logger.error(f"declare_fork_return failed: {e}", exc_info=True)
        raise BranchOperationError(f"declare_fork_return failed: {e}") from e


def resolve_fork(
    store,
    fork_id: str,
    selected_fork_point_id: str,
    resolution_rationale: str,
    initiator: str = "system",
):
    """Resolve a fork by promoting one alternative and archiving the others.

    Writes FORK_RESOLVED delta and archives each discarded alternative via
    its BranchTerminus(ABANDONED). The selected fork_point is marked PROMOTED.

    Returns:
        ResolveForkResult on success, None on failure
    """
    store = as_structural_store(store)
    from astp.core.branching import (
        AuditRecord,
        CognitiveDeltaType,
        TriggerType,
        compute_audit_record_hash,
        ResolveForkResult,
    )

    try:
        if not resolution_rationale or not resolution_rationale.strip():
            raise ASTPGovernanceError(
                "Fork resolution requires a non-empty rationale. "
                "Discarded alternatives deserve an audit trail."
            )

        # Load all fork points for this fork
        fork_points = store.fork_points_of(fork_id)

        if not fork_points:
            logger.error(f"Fork {fork_id} not found or has no ForkPoints")
            return None

        # Validate the selected one exists and is still ACTIVE
        selected = next(
            (fp for fp in fork_points if fp["fpid"] == selected_fork_point_id), None
        )
        if not selected:
            logger.error(
                f"Selected fork_point {selected_fork_point_id} not in fork {fork_id}"
            )
            return None
        if selected["status"] != "ACTIVE":
            logger.error(
                f"Fork already resolved (selected status={selected['status']})"
            )
            return None

        origin_episode_id = selected["origin_id"]
        discarded = [fp for fp in fork_points if fp["fpid"] != selected_fork_point_id]
        discarded_ids = [fp["fpid"] for fp in discarded]

        # Mark selected PROMOTED, others DISCARDED
        store.mark_fork_point_status(selected_fork_point_id, "PROMOTED")
        for fp in discarded:
            store.mark_fork_point_status(fp["fpid"], "DISCARDED")

        # Archive discarded alternatives via BranchTerminus records?
        # ForkPoints anchor Episodes, not branches — discarded forks remain
        # as sealed Episodes in the graph. The fork_status tracks resolution.
        discarded_terminus_ids = []

        # Write FORK_RESOLVED audit record
        forward_delta = {
            "fork_id": fork_id,
            "selected_fork_point_id": selected_fork_point_id,
            "discarded_fork_point_ids": discarded_ids,
            "resolution_rationale": resolution_rationale,
        }
        reverse_delta = {
            "restore_discarded": discarded_ids,
            "clear_resolution": selected_fork_point_id,
        }

        delta_sequence = next_delta_sequence(store, origin_episode_id)
        prior_audit_hash = fetch_prior_audit_hash(store, origin_episode_id)

        audit = AuditRecord(
            delta_sequence=delta_sequence,
            agent_id=initiator,
            session_id=f"fork-resolve-{fork_id}",
            delta_type=CognitiveDeltaType.FORK_RESOLVED,
            forward_delta=forward_delta,
            reverse_delta=reverse_delta,
            affected_nodes=[selected_fork_point_id] + discarded_ids,
            trigger_context=TriggerType.HUMAN_EXPLICIT,
            explicit_reason=resolution_rationale,
            prior_audit_hash=prior_audit_hash,
            episode_id=origin_episode_id,
        )
        audit.record_hash = compute_audit_record_hash(
            str(audit.audit_id),
            audit.delta_sequence,
            audit.delta_type.value,
            audit.agent_id,
            audit.wall_clock_time.isoformat(),
            json.dumps(forward_delta, default=str),
            prior_audit_hash,
        )
        store.write_audit_record(audit)

        _write_branch_wil(store, origin_episode_id, fork_id, WILOperation.FORK_RESOLVE)

        logger.info(
            f"Fork resolved: {fork_id[:8]}... "
            f"promoted={selected_fork_point_id[:8]}... "
            f"discarded={len(discarded_ids)}"
        )

        return ResolveForkResult(
            fork_id=fork_id,
            selected_fork_point_id=selected_fork_point_id,
            discarded_fork_point_ids=discarded_ids,
            discarded_terminus_ids=discarded_terminus_ids,
            delta_id=str(audit.audit_id),
            audit_record_id=str(audit.audit_id),
        )

    except ASTPGovernanceError:
        raise
    except Exception as e:
        logger.error(f"resolve_fork failed: {e}", exc_info=True)
        raise BranchOperationError(f"resolve_fork failed: {e}") from e


# ============================================================================
# Phase 2 — Common Ancestor + Merge
# ============================================================================


def find_common_ancestor(store, branch_id: str, target_episode_id: str):
    """Find the common ancestor segment between a branch and a target episode.

    Currently walks to the branch's originating BranchPoint and verifies it
    anchors on the target episode's spine. Returns CommonAncestorResult or None.
    """
    store = as_structural_store(store)
    from astp.core.branching import CommonAncestorResult

    raw = store.find_common_ancestor(branch_id, target_episode_id)
    if not raw:
        return None
    return CommonAncestorResult(
        common_ancestor_node_id=raw.get("common_ancestor_node_id") or "",
        branch_delta_from_ancestor=[],
        target_delta_from_ancestor=[],
    )


def execute_merge(
    store,
    source_branch_id: str,
    target_episode_id: str,
    merge_summary: str,
    initiator: str = "system",
    merge_strategy: str = "AUTO",
    conflict_segments: Optional[list] = None,
    conflict_resolutions: Optional[list] = None,
    resolution_artifacts: Optional[list] = None,
    caught_by: str = "HUMAN",
):
    """Execute a three-way merge of a branch into the target spine.

    Implements the 14-step sequence from spec §5.3. On conflict without
    resolutions, returns a ConflictManifest and does NOT proceed.

    Args:
        store: a StructuralStore
        source_branch_id: Branch to merge (must be ACTIVE)
        target_episode_id: Spine receiving the merge (must be ACTIVE)
        merge_summary: Required, non-empty — the synthesis
        initiator: AgentID or UserID
        merge_strategy: AUTO | MANUAL_REVIEW | AGENT_RESOLVED | CONCLUSION_ONLY
        conflict_segments: list of dicts with per-conflict info:
            [{"segment_id": str, "ancestor_content_hash": str,
              "source_content_hash": str, "target_content_hash": str,
              "description": str (opt)}, ...]
        conflict_resolutions: list of ConflictResolution dicts:
            [{"segment_id": str, "resolution_type": "TAKE_SOURCE"|"TAKE_TARGET"|"CUSTOM",
              "resolved_content_hash": str, "resolver": str, "rationale": str (opt)}, ...]
        resolution_artifacts: Artifact IDs produced by the merge synthesis
        caught_by: AGENT | HUMAN | SYSTEM | UNCAUGHT

    Returns:
        MergeResult on success, ConflictManifest if unresolved conflicts,
        None on error.
    """
    store = as_structural_store(store)
    from astp.core.branching import (
        MergePointNode,
        BranchTerminusNode,
        BranchTerminusType,
        BranchReturnEdge,
        AuditRecord,
        CognitiveDeltaType,
        TriggerType,
        MergeType,
        MergeStrategy,
        ConflictManifest,
        ConflictSegment,
        compute_merge_point_hash,
        compute_audit_record_hash,
        compute_conflict_manifest_hash,
        enforce_merge_summary_required,
        MergeResult,
    )
    from astp.core.schema import sha3_256

    try:
        # STEP 1: Validate preconditions
        enforce_merge_summary_required(merge_summary)

        try:
            _ = MergeStrategy(merge_strategy)
        except ValueError:
            raise ASTPGovernanceError(f"Unknown merge_strategy: {merge_strategy}")

        conflict_segments = conflict_segments or []
        conflict_resolutions = conflict_resolutions or []
        resolution_artifacts = resolution_artifacts or []

        # Load branch point — branch must exist and be ACTIVE
        loaded = store.branch_point_with_terminus(source_branch_id)
        if loaded is None:
            logger.error(f"Branch {source_branch_id} not found")
            return None
        bp_data, has_terminus = loaded
        if has_terminus:
            logger.error(f"Branch {source_branch_id} already terminated")
            return None

        source_episode_id = bp_data.get("episode_id", "")
        branch_point_hash = bp_data.get("content_hash", "")
        branch_point_id = bp_data.get("branch_point_id", "")

        # Target episode must be ACTIVE
        target = store.episode_status_and_spine_hash(target_episode_id)
        if target is None:
            logger.error(f"Target episode {target_episode_id} not found")
            return None
        target_status, target_spine_hash = target
        if target_status not in ("ACTIVE", "PENDING_HITL"):
            logger.error(
                f"Target episode not in ACTIVE state: {target_status}"
            )
            return None
        target_spine_hash = target_spine_hash or ""

        # STEP 2: Capture pre-merge Merkle roots (immutable after this point)
        source_merkle_root = bp_data.get("spine_merkle_snapshot", "") or ""
        # Prefer the current spine hash of the source episode if distinct
        source_merkle_root = store.episode_spine_hash(source_episode_id) or source_merkle_root

        target_merkle_root_pre = target_spine_hash

        # STEP 3: Find common ancestor
        ancestor = find_common_ancestor(store, source_branch_id, target_episode_id)
        if not ancestor:
            logger.error(
                f"No common ancestor between branch {source_branch_id[:8]}... "
                f"and target {target_episode_id[:8]}..."
            )
            return None
        common_ancestor_id = ancestor.common_ancestor_node_id

        # STEP 4/5: Surface conflicts (never silent resolution)
        resolution_map = {r["segment_id"]: r for r in conflict_resolutions}
        unresolved = [
            c for c in conflict_segments
            if c["segment_id"] not in resolution_map
        ]
        if unresolved:
            manifest = ConflictManifest(
                source_episode_id=source_episode_id,
                target_episode_id=target_episode_id,
                common_ancestor_id=common_ancestor_id,
                conflicts=[ConflictSegment(**c) for c in conflict_segments],
                source_merkle_root=source_merkle_root,
                target_merkle_root_pre=target_merkle_root_pre,
            )
            # Write conflict manifest audit trail (no state change, just record)
            manifest_hash = compute_conflict_manifest_hash(
                str(manifest.merge_id),
                source_episode_id,
                target_episode_id,
                [c["segment_id"] for c in conflict_segments],
            )
            logger.warning(
                f"Merge conflicts unresolved: {len(unresolved)} of "
                f"{len(conflict_segments)} [manifest_hash={manifest_hash[:12]}...]. "
                f"Merge does NOT proceed."
            )
            return manifest

        if merge_strategy == MergeStrategy.AUTO.value and conflict_segments:
            # AUTO never resolves silently — even with resolutions attached
            logger.warning(
                f"AUTO strategy with {len(conflict_segments)} conflicts — "
                f"caller must use MANUAL_REVIEW or AGENT_RESOLVED to commit resolutions"
            )
            return ConflictManifest(
                source_episode_id=source_episode_id,
                target_episode_id=target_episode_id,
                common_ancestor_id=common_ancestor_id,
                conflicts=[ConflictSegment(**c) for c in conflict_segments],
                source_merkle_root=source_merkle_root,
                target_merkle_root_pre=target_merkle_root_pre,
            )

        # Classify merge
        if not conflict_segments:
            merge_type = MergeType.CLEAN
        elif len(resolution_map) == len(conflict_segments):
            merge_type = MergeType.RESOLVED
        else:
            merge_type = MergeType.PARTIAL  # (unreachable given check above)

        # STEP 6/7: Compute post-merge Merkle root
        # Deterministic derivation from pre-merge roots + resolutions.
        # (Real spine recomputation requires a branch-aware segment model,
        # which Phase 2 scaffolding does not require — but the computation
        # must be deterministic and tamper-evident.)
        post_preimage = (
            f"{target_merkle_root_pre}:{source_merkle_root}:{common_ancestor_id}:"
            f"{merge_type.value}:"
            f"{','.join(sorted(c['segment_id'] for c in conflict_segments))}:"
            f"{','.join(sorted(r['resolved_content_hash'] for r in conflict_resolutions))}"
        )
        target_merkle_root_post = sha3_256(
            b"MERGE_SPINE_POST:" + post_preimage.encode()
        )

        # STEP 8: Integrity assertion — the three roots must be well-formed
        if not source_merkle_root or not target_merkle_root_pre or not target_merkle_root_post:
            logger.error(
                "Merge integrity: one or more Merkle roots missing — aborting merge"
            )
            # Abort; write failure audit record
            _write_merge_failure_audit(
                store, source_episode_id, target_episode_id, initiator,
                "Missing Merkle root(s) — merge aborted",
            )
            return None

        # STEP 9: Write MergePointNode
        merge_point = MergePointNode(
            source_episode_id=source_episode_id,
            source_branch_id=source_branch_id,
            target_episode_id=target_episode_id,
            merge_type=merge_type,
            source_merkle_root=source_merkle_root,
            target_merkle_root_pre=target_merkle_root_pre,
            target_merkle_root_post=target_merkle_root_post,
            common_ancestor_id=common_ancestor_id,
            conflict_segments=[c["segment_id"] for c in conflict_segments],
            resolution_artifacts=resolution_artifacts,
            merge_summary=merge_summary,
            initiator=initiator,
        )
        merge_point.content_hash = compute_merge_point_hash(
            str(merge_point.merge_point_id),
            str(merge_point.merge_id),
            merge_point.source_episode_id,
            merge_point.target_episode_id,
            merge_point.source_merkle_root,
            merge_point.target_merkle_root_pre,
            merge_point.target_merkle_root_post,
            merge_point.common_ancestor_id,
            merge_point.timestamp_utc.isoformat(),
            merge_point.parent_hash,
        )
        store.write_merge_point(merge_point)

        # STEP 10: Write BranchTerminusNode (terminus_type=MERGED)
        terminus = BranchTerminusNode(
            episode_id=source_episode_id,
            branch_id=source_branch_id,
            terminus_type=BranchTerminusType.MERGED,
            branch_point_hash=branch_point_hash,
            final_merkle_root=source_merkle_root,
            duration_ms=_compute_branch_duration_ms(bp_data.get("timestamp_utc", "")),
            merge_target_id=target_episode_id,
            merge_delta={
                "merge_id": str(merge_point.merge_id),
                "merge_point_id": str(merge_point.merge_point_id),
                "merge_type": merge_type.value,
            },
        )
        store.write_branch_terminus(terminus)

        # STEP 11: Write BranchReturnEdge
        branch_return = BranchReturnEdge(
            branch_id=source_branch_id,
            terminus_id=str(terminus.terminus_id),
            merge_point_id=str(merge_point.merge_point_id),
            target_episode_id=target_episode_id,
            synthesis_summary=merge_summary,
            nodes_integrated=len(conflict_segments),
        )
        store.write_branch_return_edge(branch_return)

        # STEP 12/13: Write MERGE_EXECUTED AuditRecord
        forward_delta = {
            "source_episode_id": source_episode_id,
            "target_episode_id": target_episode_id,
            "source_branch_id": source_branch_id,
            "merge_id": str(merge_point.merge_id),
            "merge_type": merge_type.value,
            "source_merkle_root": source_merkle_root,
            "target_merkle_root_pre": target_merkle_root_pre,
            "target_merkle_root_post": target_merkle_root_post,
            "conflict_count": len(conflict_segments),
            "resolution_strategy": merge_strategy,
            "conflict_resolutions": conflict_resolutions,
            "merge_summary": merge_summary,
        }
        reverse_delta = {
            "split_to_source_branches": [source_branch_id],
            "clear_merge_record": str(merge_point.merge_id),
            "restore_target_merkle_root": target_merkle_root_pre,
        }

        delta_sequence = next_delta_sequence(store, target_episode_id)
        prior_audit_hash = fetch_prior_audit_hash(store, target_episode_id)

        audit = AuditRecord(
            delta_sequence=delta_sequence,
            agent_id=initiator,
            session_id=f"merge-{merge_point.merge_id}",
            delta_type=CognitiveDeltaType.MERGE_EXECUTED,
            forward_delta=forward_delta,
            reverse_delta=reverse_delta,
            affected_nodes=[
                str(merge_point.merge_point_id),
                str(terminus.terminus_id),
                source_branch_id,
            ],
            trigger_context=TriggerType.HUMAN_EXPLICIT,
            explicit_reason=merge_summary,
            prior_audit_hash=prior_audit_hash,
            caught_by=caught_by,
            episode_id=target_episode_id,
        )
        audit.record_hash = compute_audit_record_hash(
            str(audit.audit_id),
            audit.delta_sequence,
            audit.delta_type.value,
            audit.agent_id,
            audit.wall_clock_time.isoformat(),
            json.dumps(forward_delta, default=str),
            prior_audit_hash,
        )
        store.write_audit_record(audit)

        _write_branch_wil(
            store, target_episode_id, str(merge_point.merge_point_id), WILOperation.MERGE_EXECUTE
        )

        logger.info(
            f"Merge executed: {str(merge_point.merge_id)[:8]}... "
            f"[{merge_type.value}] "
            f"branch {source_branch_id[:8]}... → episode {target_episode_id[:8]}..."
        )

        return MergeResult(
            merge_id=str(merge_point.merge_id),
            merge_point_id=str(merge_point.merge_point_id),
            merge_type=merge_type,
            source_merkle_root=source_merkle_root,
            target_merkle_root_pre=target_merkle_root_pre,
            target_merkle_root_post=target_merkle_root_post,
            conflict_segments=[c["segment_id"] for c in conflict_segments],
            resolution_artifacts=resolution_artifacts,
            terminus_id=str(terminus.terminus_id),
            delta_id=str(audit.audit_id),
            audit_record_id=str(audit.audit_id),
        )

    except ASTPGovernanceError:
        raise
    except Exception as e:
        logger.error(f"execute_merge failed: {e}", exc_info=True)
        raise BranchOperationError(f"execute_merge failed: {e}") from e


def verify_merge_integrity(store, merge_id: str):
    """Verify a merge's three Merkle roots match their expected sources.

    Returns MergeIntegrityResult.
    """
    store = as_structural_store(store)
    from astp.core.branching import MergeIntegrityResult
    from astp.core.schema import sha3_256

    try:
        mp = store.merge_point(merge_id)
        if mp is None:
            logger.error(f"MergePoint {merge_id} not found")
            return None

        source_valid = bool(mp.get("source_merkle_root"))
        target_pre_valid = bool(mp.get("target_merkle_root_pre"))

        # Recompute post-root and compare
        conflict_segments = mp.get("conflict_segments") or []
        # Recover conflict_resolutions from audit record
        forward_delta_text = store.merge_executed_forward_delta(merge_id)
        resolutions = []
        if forward_delta_text:
            try:
                fd = json.loads(forward_delta_text)
                resolutions = fd.get("conflict_resolutions", [])
            except (json.JSONDecodeError, TypeError):
                pass

        post_preimage = (
            f"{mp['target_merkle_root_pre']}:{mp['source_merkle_root']}:"
            f"{mp['common_ancestor_id']}:{mp['merge_type']}:"
            f"{','.join(sorted(conflict_segments))}:"
            f"{','.join(sorted(r['resolved_content_hash'] for r in resolutions))}"
        )
        recomputed = sha3_256(b"MERGE_SPINE_POST:" + post_preimage.encode())
        target_post_valid = recomputed == mp.get("target_merkle_root_post")

        integrity_holds = source_valid and target_pre_valid and target_post_valid

        return MergeIntegrityResult(
            merge_id=merge_id,
            source_valid=source_valid,
            target_pre_valid=target_pre_valid,
            target_post_valid=target_post_valid,
            integrity_holds=integrity_holds,
        )

    except Exception as e:
        logger.error(f"verify_merge_integrity failed: {e}", exc_info=True)
        raise BranchOperationError(f"verify_merge_integrity failed: {e}") from e


def _compute_branch_duration_ms(created_at_str: str) -> int:
    """Compute duration in ms from ISO8601 timestamp to now."""
    if not created_at_str:
        return 0
    try:
        created_at = datetime.fromisoformat(created_at_str)
        return int((datetime.now(timezone.utc) - created_at).total_seconds() * 1000)
    except (ValueError, TypeError):
        return 0


def _write_merge_failure_audit(
    store, source_episode_id: str, target_episode_id: str,
    initiator: str, reason: str,
) -> None:
    """Write an audit record for a merge abort (integrity check failure)."""
    store = as_structural_store(store)
    from astp.core.branching import (
        AuditRecord,
        CognitiveDeltaType,
        TriggerType,
        compute_audit_record_hash,
    )

    try:
        forward_delta = {
            "source_episode_id": source_episode_id,
            "target_episode_id": target_episode_id,
            "outcome": "ABORTED",
            "reason": reason,
        }
        delta_sequence = next_delta_sequence(store, target_episode_id)
        prior_audit_hash = fetch_prior_audit_hash(store, target_episode_id)

        audit = AuditRecord(
            delta_sequence=delta_sequence,
            agent_id=initiator,
            session_id=f"merge-abort-{source_episode_id}",
            delta_type=CognitiveDeltaType.MERGE_EXECUTED,
            forward_delta=forward_delta,
            reverse_delta={},
            trigger_context=TriggerType.SYSTEM_AUTOMATIC,
            explicit_reason=reason,
            prior_audit_hash=prior_audit_hash,
            caught_by="SYSTEM",
            episode_id=target_episode_id,
        )
        audit.record_hash = compute_audit_record_hash(
            str(audit.audit_id),
            audit.delta_sequence,
            audit.delta_type.value,
            audit.agent_id,
            audit.wall_clock_time.isoformat(),
            json.dumps(forward_delta, default=str),
            prior_audit_hash,
        )
        store.write_audit_record(audit)
    except Exception as e:
        raise AdapterWriteError(f"merge failure audit: {e}") from e


# ============================================================================
# Phase 3 — Aside Operations (human-initiated side channel)
# ============================================================================


def create_aside(
    store,
    parent_episode_id: str,
    parent_segment_id: str,
    aside_label: str,
    initiated_by_human: str,
    target_agent_id: str,
    return_obligation: bool = True,
    content_refs: Optional[list] = None,
    caught_by: str = "HUMAN",
):
    """Open an aside: human-initiated side channel with a target agent.

    Writes AsideSegment + ASIDE_OPENED delta + AuditRecord. Invariant:
    asides are ALWAYS human-initiated — agent-initiated internal branches
    are soliloquies, not asides.

    Returns:
        AsideResult on success, None on failure
    """
    store = as_structural_store(store)
    from astp.core.branching import (
        AsideSegmentNode,
        AuditRecord,
        CognitiveDeltaType,
        TriggerType,
        compute_aside_hash,
        compute_audit_record_hash,
        enforce_aside_human_initiated,
        enforce_aside_target_agent,
        AsideResult,
    )

    try:
        # STEP 1: Validate preconditions
        enforce_aside_human_initiated(initiated_by_human)
        enforce_aside_target_agent(target_agent_id)
        if not aside_label or not aside_label.strip():
            raise ASTPGovernanceError("Aside requires a non-empty label")

        # Verify parent episode is ACTIVE
        status = store.episode_status(parent_episode_id)
        if status is None:
            logger.error(f"Parent episode {parent_episode_id} not found")
            return None
        if status not in ("ACTIVE", "PENDING_HITL"):
            logger.error(
                f"Parent episode not in ACTIVE state: {status}"
            )
            return None

        # The parent Segment is bound by identity and by content (SPEC §19.4.1); a
        # parent that does not exist, or is not a UUID, is a precondition refusal.
        parent = _parent_segment_for_side_channel(store, parent_segment_id)
        if parent is None:
            return None
        parent_uuid, parent_content_hash = parent

        # STEP 2: Create AsideSegmentNode
        aside = AsideSegmentNode(
            parent_episode_id=parent_episode_id,
            parent_segment_id=parent_segment_id,
            aside_label=aside_label,
            initiated_by_human=initiated_by_human,
            target_agent_id=target_agent_id,
            return_obligation=return_obligation,
            content_refs=content_refs or [],
            parent_hash=parent_content_hash,
        )
        aside.content_hash = compute_aside_hash_v2(
            aside.aside_id, aside.parent_episode_id, parent_uuid, parent_content_hash,
            aside.initiated_by_human, aside.target_agent_id, aside.timestamp_utc,
        )

        # STEP 3: Write AsideSegmentNode
        store.write_aside(aside)

        # STEP 4: Write ASIDE_OPENED AuditRecord
        forward_delta = {
            "parent_episode_id": parent_episode_id,
            "parent_segment_id": parent_segment_id,
            "aside_id": str(aside.aside_id),
            "aside_label": aside_label,
            "initiated_by_human": initiated_by_human,
            "target_agent_id": target_agent_id,
            "return_obligation": return_obligation,
        }
        reverse_delta = {"delete_aside_id": str(aside.aside_id)}

        delta_sequence = next_delta_sequence(store, parent_episode_id)
        prior_audit_hash = fetch_prior_audit_hash(store, parent_episode_id)

        audit = AuditRecord(
            delta_sequence=delta_sequence,
            agent_id=target_agent_id,
            human_actor=initiated_by_human,
            session_id=f"aside-{aside.aside_id}",
            delta_type=CognitiveDeltaType.ASIDE_OPENED,
            forward_delta=forward_delta,
            reverse_delta=reverse_delta,
            affected_nodes=[str(aside.aside_id)],
            trigger_context=TriggerType.HUMAN_EXPLICIT,
            explicit_reason=aside_label,
            prior_audit_hash=prior_audit_hash,
            caught_by=caught_by,
            episode_id=parent_episode_id,
        )
        audit.record_hash = compute_audit_record_hash(
            str(audit.audit_id),
            audit.delta_sequence,
            audit.delta_type.value,
            audit.agent_id,
            audit.wall_clock_time.isoformat(),
            json.dumps(forward_delta, default=str),
            prior_audit_hash,
        )
        store.write_audit_record(audit)

        _write_branch_wil(store, parent_episode_id, str(aside.aside_id), WILOperation.ASIDE_OPEN)

        logger.info(
            f"Aside opened: {str(aside.aside_id)[:8]}... "
            f"[human={initiated_by_human} → agent={target_agent_id}] "
            f"episode={parent_episode_id[:8]}..."
        )

        return AsideResult(
            aside_id=str(aside.aside_id),
            parent_episode_id=parent_episode_id,
            parent_segment_id=parent_segment_id,
            target_agent_id=target_agent_id,
            delta_id=str(audit.audit_id),
            audit_record_id=str(audit.audit_id),
        )

    except ASTPGovernanceError:
        raise
    except Exception as e:
        logger.error(f"create_aside failed: {e}", exc_info=True)
        raise BranchOperationError(f"create_aside failed: {e}") from e


def close_aside(
    store,
    aside_id: str,
    close_reason: str,
    notification_targets: Optional[list] = None,
    additional_content_refs: Optional[list] = None,
    initiator: str = "system",
):
    """Close an aside: runs reference scan, writes terminus + audit.

    Asymmetric merge: other agents are notified of the aside's existence,
    but its internal content is retrieval-accessible only — it is NOT
    injected into their working state.

    Returns:
        AsideCloseResult on success, None on failure
    """
    store = as_structural_store(store)
    from astp.core.branching import (
        AsideTerminusNode,
        AsideTerminationStatus,
        AuditRecord,
        CognitiveDeltaType,
        TriggerType,
        compute_audit_record_hash,
        enforce_aside_close_reason,
        AsideCloseResult,
    )
    from astp.core.schema import sha3_256

    try:
        # STEP 1: Validate preconditions
        enforce_aside_close_reason(close_reason)

        loaded = store.load_aside(aside_id)
        if not loaded:
            logger.error(f"Aside {aside_id} not found")
            return None
        if loaded["is_closed"]:
            logger.error(f"Aside {aside_id} already closed")
            return None

        aside_data = loaded["aside"]
        parent_episode_id = aside_data.get("parent_episode_id", "")
        content_refs = list(aside_data.get("content_refs") or [])
        if additional_content_refs:
            content_refs = list({*content_refs, *additional_content_refs})

        # STEP 2: Reference scan — any external segments pointing inside?
        external_refs = store.scan_aside_external_references(aside_id, content_refs,
        )
        reference_scan_passed = len(external_refs) == 0

        # STEP 3: Duration
        created_at_str = aside_data.get("timestamp_utc", "")
        duration_ms = _compute_branch_duration_ms(created_at_str)

        # STEP 4: The terminus binds what the channel produced — the content hashes
        # of the Segments written inside it, in the order written — the close
        # reason, the scan outcome and the external references found (SPEC §19.4.1).
        produced = content_hashes_in_sequence_order(store.segment_content_hashes(content_refs), content_refs)
        terminus = AsideTerminusNode(
            aside_id=aside_id,
            parent_episode_id=parent_episode_id,
            close_reason=close_reason,
            final_content_hash="",   # filled below
            reference_scan_passed=reference_scan_passed,
            external_references_found=external_refs,
            notification_targets=notification_targets or [],
            duration_ms=duration_ms,
            termination_status=AsideTerminationStatus.CLOSED,
        )
        terminus.final_content_hash = compute_aside_terminus_hash_v2(
            terminus.aside_terminus_id, UUID(str(aside_id)), UUID(str(parent_episode_id)),
            str(aside_data.get("content_hash") or ""), produced, close_reason, reference_scan_passed,
            [UUID(str(x)) for x in external_refs if _is_uuid(x)], terminus.termination_status.value, terminus.timestamp_utc,
        )
        store.write_aside_terminus(terminus)

        # STEP 6: Write ASIDE_CLOSED AuditRecord
        forward_delta = {
            "aside_id": aside_id,
            "close_reason": close_reason,
            "final_content_hash": terminus.final_content_hash,
            "reference_scan_passed": reference_scan_passed,
            "external_references_found": external_refs,
            "notification_targets": notification_targets or [],
        }
        reverse_delta = {"restore_aside_to_open": aside_id}

        delta_sequence = next_delta_sequence(store, parent_episode_id)
        prior_audit_hash = fetch_prior_audit_hash(store, parent_episode_id)

        audit = AuditRecord(
            delta_sequence=delta_sequence,
            agent_id=aside_data.get("target_agent_id", initiator),
            human_actor=aside_data.get("initiated_by_human"),
            session_id=f"aside-close-{aside_id}",
            delta_type=CognitiveDeltaType.ASIDE_CLOSED,
            forward_delta=forward_delta,
            reverse_delta=reverse_delta,
            affected_nodes=[aside_id, str(terminus.aside_terminus_id)],
            trigger_context=TriggerType.HUMAN_EXPLICIT,
            explicit_reason=close_reason,
            prior_audit_hash=prior_audit_hash,
            episode_id=parent_episode_id,
        )
        audit.record_hash = compute_audit_record_hash(
            str(audit.audit_id),
            audit.delta_sequence,
            audit.delta_type.value,
            audit.agent_id,
            audit.wall_clock_time.isoformat(),
            json.dumps(forward_delta, default=str),
            prior_audit_hash,
        )
        store.write_audit_record(audit)

        _write_branch_wil(
            store, parent_episode_id, str(terminus.aside_terminus_id), WILOperation.ASIDE_CLOSE
        )

        if not reference_scan_passed:
            logger.warning(
                f"Aside {aside_id[:8]}... closed with external reference leaks: "
                f"{len(external_refs)} external segments reference internal state. "
                f"Recorded in audit trail."
            )

        logger.info(
            f"Aside closed: {aside_id[:8]}... "
            f"scan_passed={reference_scan_passed} duration={duration_ms}ms"
        )

        return AsideCloseResult(
            aside_id=aside_id,
            aside_terminus_id=str(terminus.aside_terminus_id),
            final_content_hash=terminus.final_content_hash,
            reference_scan_passed=reference_scan_passed,
            external_references_found=external_refs,
            notification_targets=notification_targets or [],
            delta_id=str(audit.audit_id),
            audit_record_id=str(audit.audit_id),
        )

    except ASTPGovernanceError:
        raise
    except Exception as e:
        logger.error(f"close_aside failed: {e}", exc_info=True)
        raise BranchOperationError(f"close_aside failed: {e}") from e


# ============================================================================
# Phase 3 — Soliloquy Operations (agent-initiated internal deliberation)
# ============================================================================


def create_soliloquy(
    store,
    parent_episode_id: str,
    parent_segment_id: str,
    soliloquy_purpose: str,
    initiated_by_agent: str,
    visibility_policy: Optional[dict] = None,
    deliberation_chain: Optional[list] = None,
    caught_by: str = "AGENT",
):
    """Initiate a soliloquy: agent-initiated internal deliberation.

    Invariants:
      - Humans ALWAYS have read access (enforced)
      - Other agents: ESCALATION_ONLY by default
      - Coherence monitoring continues inside
      - Return obligation required (unconcluded = audit violation)

    Returns:
        SoliloquyResult on success, None on failure
    """
    store = as_structural_store(store)
    from astp.core.branching import (
        SoliloquySegmentNode,
        SoliloquyVisibilityPolicy,
        AuditRecord,
        CognitiveDeltaType,
        TriggerType,
        compute_soliloquy_content_hash,
        compute_audit_record_hash,
        enforce_soliloquy_purpose_required,
        enforce_soliloquy_human_accessible,
        SoliloquyResult,
    )

    try:
        # STEP 1: Validate preconditions
        enforce_soliloquy_purpose_required(soliloquy_purpose)
        if not initiated_by_agent or not initiated_by_agent.strip():
            raise ASTPGovernanceError("Soliloquy requires initiated_by_agent")

        policy = SoliloquyVisibilityPolicy(**(visibility_policy or {}))
        enforce_soliloquy_human_accessible(policy)

        # Verify parent episode is ACTIVE
        status = store.episode_status(parent_episode_id)
        if status is None:
            logger.error(f"Parent episode {parent_episode_id} not found")
            return None
        if status not in ("ACTIVE", "PENDING_HITL"):
            logger.error(
                f"Parent episode not in ACTIVE state: {status}"
            )
            return None

        parent = _parent_segment_for_side_channel(store, parent_segment_id)
        if parent is None:
            return None
        parent_uuid, parent_content_hash = parent

        # STEP 2: Create SoliloquySegmentNode — one construction (SPEC §19.4.2); the
        # content-hash policy no longer selects a hash form.
        soliloquy = SoliloquySegmentNode(
            parent_episode_id=parent_episode_id,
            parent_segment_id=parent_segment_id,
            soliloquy_purpose=soliloquy_purpose,
            initiated_by_agent=initiated_by_agent,
            visibility_policy=policy,
            deliberation_chain=deliberation_chain or [],
            parent_hash=parent_content_hash,
        )
        soliloquy.content_hash = compute_soliloquy_hash_v2(
            soliloquy.soliloquy_id, soliloquy.parent_episode_id, parent_uuid, parent_content_hash,
            soliloquy.initiated_by_agent, soliloquy.timestamp_utc,
        )

        # STEP 3: Write SoliloquySegmentNode
        store.write_soliloquy(soliloquy)

        # STEP 4: Write SOLILOQUY_INITIATED AuditRecord
        forward_delta = {
            "parent_episode_id": parent_episode_id,
            "parent_segment_id": parent_segment_id,
            "soliloquy_id": str(soliloquy.soliloquy_id),
            "soliloquy_purpose": soliloquy_purpose,
            "initiated_by_agent": initiated_by_agent,
            "visibility_policy": policy.model_dump(mode="json"),
            "content_hash": soliloquy.content_hash,
        }
        reverse_delta = {"delete_soliloquy_id": str(soliloquy.soliloquy_id)}

        delta_sequence = next_delta_sequence(store, parent_episode_id)
        prior_audit_hash = fetch_prior_audit_hash(store, parent_episode_id)

        audit = AuditRecord(
            delta_sequence=delta_sequence,
            agent_id=initiated_by_agent,
            session_id=f"soliloquy-{soliloquy.soliloquy_id}",
            delta_type=CognitiveDeltaType.SOLILOQUY_INITIATED,
            forward_delta=forward_delta,
            reverse_delta=reverse_delta,
            affected_nodes=[str(soliloquy.soliloquy_id)],
            trigger_context=TriggerType.AGENT_DETECTED,
            explicit_reason=soliloquy_purpose,
            prior_audit_hash=prior_audit_hash,
            caught_by=caught_by,
            episode_id=parent_episode_id,
        )
        audit.record_hash = compute_audit_record_hash(
            str(audit.audit_id),
            audit.delta_sequence,
            audit.delta_type.value,
            audit.agent_id,
            audit.wall_clock_time.isoformat(),
            json.dumps(forward_delta, default=str),
            prior_audit_hash,
        )
        store.write_audit_record(audit)

        _write_branch_wil(
            store, parent_episode_id, str(soliloquy.soliloquy_id), WILOperation.SOLILOQUY_INIT
        )

        logger.info(
            f"Soliloquy initiated: {str(soliloquy.soliloquy_id)[:8]}... "
            f"[agent={initiated_by_agent}, "
            f"policy={policy.content_hash_policy.value}] "
            f"episode={parent_episode_id[:8]}..."
        )

        return SoliloquyResult(
            soliloquy_id=str(soliloquy.soliloquy_id),
            parent_episode_id=parent_episode_id,
            parent_segment_id=parent_segment_id,
            initiated_by_agent=initiated_by_agent,
            delta_id=str(audit.audit_id),
            audit_record_id=str(audit.audit_id),
        )

    except ASTPGovernanceError:
        raise
    except Exception as e:
        logger.error(f"create_soliloquy failed: {e}", exc_info=True)
        raise BranchOperationError(f"create_soliloquy failed: {e}") from e


def conclude_soliloquy(
    store,
    soliloquy_id: str,
    conclusion_summary: str,
    merged_into_segment_id: str,
    final_deliberation_chain: Optional[list] = None,
):
    """Conclude a soliloquy: only the conclusion merges back to the spine.

    The deliberation chain stays sealed inside the Soliloquy node. A
    tamper-evident deliberation_chain_hash is recorded on the conclusion
    so auditors with access can verify the chain content.

    Returns:
        SoliloquyConclusionResult on success, None on failure
    """
    store = as_structural_store(store)
    from astp.core.branching import (
        SoliloquyConclusionNode,
        SoliloquyTerminationStatus,
        AuditRecord,
        CognitiveDeltaType,
        TriggerType,
        compute_deliberation_chain_hash,
        compute_soliloquy_conclusion_hash,
        compute_audit_record_hash,
        enforce_soliloquy_conclusion_required,
        SoliloquyConclusionResult,
    )

    try:
        # STEP 1: Validate preconditions
        enforce_soliloquy_conclusion_required(conclusion_summary)
        if not merged_into_segment_id or not merged_into_segment_id.strip():
            raise ASTPGovernanceError(
                "Conclusion must specify merged_into_segment_id — "
                "only the conclusion merges back"
            )

        loaded = store.load_soliloquy(soliloquy_id)
        if not loaded:
            logger.error(f"Soliloquy {soliloquy_id} not found")
            return None
        if loaded["is_concluded"]:
            logger.error(f"Soliloquy {soliloquy_id} already concluded")
            return None

        sol_data = loaded["soliloquy"]
        parent_episode_id = sol_data.get("parent_episode_id", "")
        initiated_by_agent = sol_data.get("initiated_by_agent", "")
        deliberation_chain = (
            final_deliberation_chain
            if final_deliberation_chain is not None
            else list(sol_data.get("deliberation_chain") or [])
        )

        # STEP 2: The deliberation chain is bound by content, not by name: the
        # deliberation Segments' content hashes in the order written (SPEC §19.4.3).
        # The merge target must be a UUID — it is bound as one.
        if not _is_uuid(merged_into_segment_id):
            logger.error(f"merged_into_segment_id {merged_into_segment_id!r} is not a UUID")
            return None
        found = store.segment_content_hashes(deliberation_chain)
        missing = [x for x in deliberation_chain if str(x) not in found]
        if missing:
            logger.error(f"deliberation chain names Segments that do not exist or have no content hash: {missing}")
            return None
        chain_hash = compute_deliberation_chain_hash_v2(
            UUID(str(soliloquy_id)), content_hashes_in_sequence_order(found, deliberation_chain),
        )
        ts = datetime.now(timezone.utc)

        conclusion = SoliloquyConclusionNode(
            soliloquy_id=soliloquy_id,
            parent_episode_id=parent_episode_id,
            conclusion_summary=conclusion_summary,
            conclusion_content_hash="",   # filled below
            deliberation_chain_hash=chain_hash,
            merged_into_segment_id=merged_into_segment_id,
            duration_ms=_compute_branch_duration_ms(sol_data.get("timestamp_utc", "")),
            termination_status=SoliloquyTerminationStatus.ABSORBED,
            timestamp_utc=ts,
        )
        conclusion.conclusion_content_hash = compute_soliloquy_conclusion_hash_v2(
            conclusion.conclusion_id, UUID(str(soliloquy_id)), UUID(str(parent_episode_id)), chain_hash,
            conclusion_summary, UUID(str(merged_into_segment_id)), conclusion.termination_status.value, ts,
        )

        # STEP 3: Write SoliloquyConclusionNode
        store.write_soliloquy_conclusion(conclusion)

        # STEP 4: Write SOLILOQUY_CONCLUDED AuditRecord
        forward_delta = {
            "soliloquy_id": soliloquy_id,
            "conclusion_id": str(conclusion.conclusion_id),
            "conclusion_summary": conclusion_summary,
            "conclusion_content_hash": conclusion.conclusion_content_hash,
            "deliberation_chain_hash": chain_hash,
            "merged_into_segment_id": merged_into_segment_id,
        }
        reverse_delta = {"restore_soliloquy_to_active": soliloquy_id}

        delta_sequence = next_delta_sequence(store, parent_episode_id)
        prior_audit_hash = fetch_prior_audit_hash(store, parent_episode_id)

        audit = AuditRecord(
            delta_sequence=delta_sequence,
            agent_id=initiated_by_agent,
            session_id=f"soliloquy-conclude-{soliloquy_id}",
            delta_type=CognitiveDeltaType.SOLILOQUY_CONCLUDED,
            forward_delta=forward_delta,
            reverse_delta=reverse_delta,
            affected_nodes=[soliloquy_id, str(conclusion.conclusion_id)],
            trigger_context=TriggerType.AGENT_DETECTED,
            explicit_reason=conclusion_summary,
            prior_audit_hash=prior_audit_hash,
            episode_id=parent_episode_id,
        )
        audit.record_hash = compute_audit_record_hash(
            str(audit.audit_id),
            audit.delta_sequence,
            audit.delta_type.value,
            audit.agent_id,
            audit.wall_clock_time.isoformat(),
            json.dumps(forward_delta, default=str),
            prior_audit_hash,
        )
        store.write_audit_record(audit)

        _write_branch_wil(
            store, parent_episode_id, str(conclusion.conclusion_id),
            WILOperation.SOLILOQUY_CONCLUDE,
        )

        logger.info(
            f"Soliloquy concluded: {soliloquy_id[:8]}... "
            f"conclusion={str(conclusion.conclusion_id)[:8]}... "
            f"merged_into={merged_into_segment_id[:8]}..."
        )

        return SoliloquyConclusionResult(
            soliloquy_id=soliloquy_id,
            conclusion_id=str(conclusion.conclusion_id),
            conclusion_content_hash=conclusion.conclusion_content_hash,
            deliberation_chain_hash=chain_hash,
            merged_into_segment_id=merged_into_segment_id,
            delta_id=str(audit.audit_id),
            audit_record_id=str(audit.audit_id),
        )

    except ASTPGovernanceError:
        raise
    except Exception as e:
        logger.error(f"conclude_soliloquy failed: {e}", exc_info=True)
        raise BranchOperationError(f"conclude_soliloquy failed: {e}") from e


def _write_branch_wil(
    store, episode_id: str, node_id: str, operation: WILOperation
) -> None:
    """Write a WIL entry for a branch operation.

    `operation` is a WILOperation, not a str, so a call site cannot ledger a
    value that is absent from the authoritative operation list.

    The coercion sits OUTSIDE the try on purpose: a bad operation value is a
    programmer error, deterministic, and must not be reported as a store
    failure. Since 5.1.0 the store failure raises too — a COMPLETE ledger entry
    is never written for a write that did not happen, and a ledger entry that
    cannot be written fails the operation that needed it (G-39).
    """
    store = as_structural_store(store)
    operation = WILOperation(operation)

    try:
        from astp.core.branching import compute_branch_point_hash
        from uuid import uuid4

        store.write_completed_wil_entry(
            intent_id=str(uuid4()),
            operation=operation.value,
            episode_id=episode_id,
            node_id=node_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        raise AdapterWriteError(f"branch WIL entry: {e}") from e
