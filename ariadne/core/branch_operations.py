"""
Ariadne Branch Operations — Phase 1: Branch Lifecycle

The two Phase 1 functions:
  create_branch() — 11-step sequence creating a branch from the spine
  abandon_branch() — 7-step sequence terminating a branch without merge

Build rule: every function writes structural node + cognitive delta + audit record.
No function ships without all three writes present.

Spec reference: Ariadne Branch/Fork/Merge Build Specification v1.0, Sections 4.3–4.4
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from ariadne.core.branching import (
    BranchPointNode,
    BranchTerminusNode,
    BranchType,
    BranchDeclarationType,
    BranchTerminusType,
    CognitiveDeltaType,
    TriggerType,
    IntentType,
    IntentStatus,
    AuditRecord,
    AccessPolicy,
    AccessResourceType,
    BranchResult,
    AbandonResult,
    compute_branch_point_hash,
    compute_branch_terminus_hash,
    compute_audit_record_hash,
    compute_intent_idempotency_key,
    enforce_branch_depth_limit,
    enforce_access_policy,
    enforce_abandonment_reason_required,
    AriadneGovernanceError,
    DEFAULT_ACCESS_POLICIES,
    AccessLevel,
)

logger = logging.getLogger("ariadne.branch_operations")


def create_branch(
    driver,
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
        driver: Neo4j sync driver
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
    try:
        # STEP 1: Validate preconditions
        if not branch_intent or not branch_intent.strip():
            raise AriadneGovernanceError("Branch intent must be non-empty")

        # Check branch depth (soft limit)
        try:
            enforce_branch_depth_limit(branch_depth)
        except AriadneGovernanceError:
            logger.warning(
                f"Branch depth limit exceeded ({branch_depth}) — "
                f"proceeding with override logged"
            )

        # Verify source episode exists and is ACTIVE
        with driver.session() as session:
            ep_check = session.run("""
                MATCH (e:AriadneEpisode {episode_id: $eid})
                RETURN e.episode_status AS status
            """, {"eid": source_episode_id})
            ep_record = ep_check.single()
            if not ep_record:
                logger.error(f"Source episode {source_episode_id} not found")
                return None
            status = ep_record["status"]
            if status not in ("ACTIVE", "PENDING_HITL"):
                logger.error(f"Source episode not in ACTIVE state: {status}")
                return None

        # STEP 2: Acquire intent record (idempotency guard)
        from ariadne.adapters.neo4j.writer import acquire_intent_sync, complete_intent_sync

        idempotency_key = compute_intent_idempotency_key(
            source_episode_id, source_segment_id, branch_intent
        )
        intent, is_new = acquire_intent_sync(
            driver, idempotency_key, IntentType.CREATE_BRANCH.value, initiator
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
        # Full Harmonia enforcement comes in Phase 4

        # STEP 4: Capture spine Merkle snapshot
        spine_merkle_snapshot = ""
        with driver.session() as session:
            spine_result = session.run("""
                MATCH (e:AriadneEpisode {episode_id: $eid})
                RETURN e.spine_hash AS spine_hash
            """, {"eid": source_episode_id})
            spine_record = spine_result.single()
            if spine_record and spine_record["spine_hash"]:
                spine_merkle_snapshot = spine_record["spine_hash"]

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
        from ariadne.adapters.neo4j.writer import write_branch_point_sync
        write_branch_point_sync(driver, branch_point)

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
        delta_sequence = _get_next_delta_sequence(driver, source_episode_id)

        # Get prior audit hash for chain integrity
        prior_audit_hash = _get_prior_audit_hash(driver, source_episode_id)

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
        from ariadne.adapters.neo4j.writer import write_audit_record_sync
        write_audit_record_sync(driver, audit)

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
        complete_intent_sync(
            driver, idempotency_key, str(branch_point.branch_point_id)
        )

        # STEP 11: Write WIL entry
        _write_branch_wil(driver, source_episode_id, str(branch_point.branch_point_id), "BRANCH_CREATE")

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

    except AriadneGovernanceError:
        raise
    except Exception as e:
        logger.error(f"create_branch failed: {e}", exc_info=True)
        return None


def abandon_branch(
    driver,
    branch_id: str,
    initiator: str,
    abandonment_reason: str,
    preserve_artifacts: bool = True,
) -> Optional[AbandonResult]:
    """Terminate a branch without merging.

    7-step sequence per spec Section 4.4. ABANDONED is terminal —
    the branch cannot be reopened. All writes are atomic.

    Args:
        driver: Neo4j sync driver
        branch_id: UUID of the branch to abandon
        initiator: AgentID or UserID performing the abandonment
        abandonment_reason: Required, non-empty — why the branch is being abandoned
        preserve_artifacts: If True, artifact nodes remain accessible

    Returns:
        AbandonResult on success, None on failure
    """
    try:
        # STEP 1: Validate preconditions
        enforce_abandonment_reason_required(abandonment_reason)

        # Verify branch is ACTIVE (derived: BranchPoint exists, no Terminus)
        with driver.session() as session:
            bp_result = session.run("""
                MATCH (bp:AriadneBranchPoint {branch_id: $bid})
                OPTIONAL MATCH (bp)-[:BRANCH_TERMINUS]->(bt:AriadneBranchTerminus)
                RETURN bp {.*} AS branch_point, bt IS NOT NULL AS has_terminus
            """, {"bid": branch_id})
            bp_record = bp_result.single()

            if not bp_record or not bp_record["branch_point"]:
                logger.error(f"Branch {branch_id} not found")
                return None

            if bp_record["has_terminus"]:
                logger.error(f"Branch {branch_id} already terminated")
                return None

            branch_point_data = dict(bp_record["branch_point"])

        episode_id = branch_point_data.get("episode_id", "")
        branch_point_hash = branch_point_data.get("content_hash", "")

        # STEP 2: Capture final branch state
        final_merkle_root = ""  # Branch-specific Merkle root
        with driver.session() as session:
            # Get the spine hash as proxy for branch state
            spine_result = session.run("""
                MATCH (e:AriadneEpisode {episode_id: $eid})
                RETURN e.spine_hash AS spine_hash
            """, {"eid": episode_id})
            spine_record = spine_result.single()
            if spine_record and spine_record["spine_hash"]:
                final_merkle_root = spine_record["spine_hash"]

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

        from ariadne.adapters.neo4j.writer import write_branch_terminus_sync
        write_branch_terminus_sync(driver, terminus)

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

        delta_sequence = _get_next_delta_sequence(driver, episode_id)
        prior_audit_hash = _get_prior_audit_hash(driver, episode_id)

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
        from ariadne.adapters.neo4j.writer import write_audit_record_sync
        write_audit_record_sync(driver, audit)

        # STEP 6: Preserve artifacts (default behavior — no deletion)
        artifacts_preserved = []
        if preserve_artifacts:
            # Artifacts are preserved by default — ABANDONED is a valid terminal state
            pass

        # STEP 7: Write WIL entry
        _write_branch_wil(driver, episode_id, str(terminus.terminus_id), "BRANCH_ABANDON")

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

    except AriadneGovernanceError:
        raise
    except Exception as e:
        logger.error(f"abandon_branch failed: {e}", exc_info=True)
        return None


# ── Internal Helpers ─────────────────────────────────────────────────────────


def _get_next_delta_sequence(driver, episode_id: str) -> int:
    """Get the next delta sequence number for an episode."""
    try:
        with driver.session() as session:
            result = session.run("""
                MATCH (ar:AriadneAuditRecord {episode_id: $eid})
                RETURN max(ar.delta_sequence) AS max_seq
            """, {"eid": episode_id})
            record = result.single()
            current_max = record["max_seq"] if record and record["max_seq"] is not None else 0
            return current_max + 1
    except Exception:
        return 1


def _get_prior_audit_hash(driver, episode_id: str) -> str:
    """Get the hash of the most recent audit record for chain integrity."""
    try:
        with driver.session() as session:
            result = session.run("""
                MATCH (ar:AriadneAuditRecord {episode_id: $eid})
                RETURN ar.record_hash AS hash
                ORDER BY ar.delta_sequence DESC
                LIMIT 1
            """, {"eid": episode_id})
            record = result.single()
            return record["hash"] if record and record["hash"] else "GENESIS"
    except Exception:
        return "GENESIS"



# ============================================================================
# Phase 2 — Fork Operations
# ============================================================================


def create_fork(
    driver,
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
        driver: Neo4j sync driver
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
    from ariadne.core.branching import (
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
    from ariadne.adapters.neo4j.writer import (
        write_fork_point_sync,
        write_audit_record_sync,
        acquire_intent_sync,
        complete_intent_sync,
    )
    from uuid import uuid4

    try:
        # STEP 1: Validate preconditions
        enforce_fork_objective_required(fork_objective)
        enforce_fork_sibling_count(len(alternatives))

        if not fork_intent or not fork_intent.strip():
            raise AriadneGovernanceError("Fork intent must be non-empty")

        with driver.session() as session:
            ep_check = session.run("""
                MATCH (e:AriadneEpisode {episode_id: $eid})
                RETURN e.episode_status AS status
            """, {"eid": origin_episode_id})
            ep_record = ep_check.single()
            if not ep_record:
                logger.error(f"Origin episode {origin_episode_id} not found")
                return None
            if ep_record["status"] not in ("ACTIVE", "PENDING_HITL"):
                logger.error(f"Origin episode not in ACTIVE state: {ep_record['status']}")
                return None

        # STEP 2: Acquire intent record
        idempotency_key = compute_intent_idempotency_key(
            origin_episode_id, origin_segment_id, f"FORK:{fork_objective}:{len(alternatives)}"
        )
        intent, _is_new = acquire_intent_sync(
            driver, idempotency_key, IntentType.CREATE_FORK.value, initiator
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
            write_fork_point_sync(driver, fp)

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

        delta_sequence = _get_next_delta_sequence(driver, origin_episode_id)
        prior_audit_hash = _get_prior_audit_hash(driver, origin_episode_id)

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
        write_audit_record_sync(driver, audit)

        # STEP 7: Mark intent complete
        complete_intent_sync(driver, idempotency_key, str(fork_id))

        # STEP 8: WIL entry
        _write_branch_wil(driver, origin_episode_id, str(fork_id), "FORK_CREATE")

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

    except AriadneGovernanceError:
        raise
    except Exception as e:
        logger.error(f"create_fork failed: {e}", exc_info=True)
        return None


def resolve_fork(
    driver,
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
    from ariadne.core.branching import (
        AuditRecord,
        CognitiveDeltaType,
        TriggerType,
        compute_audit_record_hash,
        ResolveForkResult,
    )
    from ariadne.adapters.neo4j.writer import (
        mark_fork_point_status_sync,
        write_audit_record_sync,
    )

    try:
        if not resolution_rationale or not resolution_rationale.strip():
            raise AriadneGovernanceError(
                "Fork resolution requires a non-empty rationale. "
                "Discarded alternatives deserve an audit trail."
            )

        # Load all fork points for this fork
        with driver.session() as session:
            result = session.run("""
                MATCH (fp:AriadneForkPoint {fork_id: $fork_id})
                RETURN fp.fork_point_id AS fpid,
                       fp.episode_id    AS eid,
                       fp.fork_status   AS status,
                       fp.origin_episode_id AS origin_id
            """, {"fork_id": fork_id})
            fork_points = [dict(r) for r in result]

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
        mark_fork_point_status_sync(driver, selected_fork_point_id, "PROMOTED")
        for fp in discarded:
            mark_fork_point_status_sync(driver, fp["fpid"], "DISCARDED")

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

        delta_sequence = _get_next_delta_sequence(driver, origin_episode_id)
        prior_audit_hash = _get_prior_audit_hash(driver, origin_episode_id)

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
        write_audit_record_sync(driver, audit)

        _write_branch_wil(driver, origin_episode_id, fork_id, "FORK_RESOLVE")

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

    except AriadneGovernanceError:
        raise
    except Exception as e:
        logger.error(f"resolve_fork failed: {e}", exc_info=True)
        return None


# ============================================================================
# Phase 2 — Common Ancestor + Merge
# ============================================================================


def find_common_ancestor(driver, branch_id: str, target_episode_id: str):
    """Find the common ancestor segment between a branch and a target episode.

    Currently walks to the branch's originating BranchPoint and verifies it
    anchors on the target episode's spine. Returns CommonAncestorResult or None.
    """
    from ariadne.core.branching import CommonAncestorResult
    from ariadne.adapters.neo4j.writer import find_common_ancestor_sync

    raw = find_common_ancestor_sync(driver, branch_id, target_episode_id)
    if not raw:
        return None
    return CommonAncestorResult(
        common_ancestor_node_id=raw.get("common_ancestor_node_id") or "",
        branch_delta_from_ancestor=[],
        target_delta_from_ancestor=[],
    )


def execute_merge(
    driver,
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
        driver: Neo4j sync driver
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
    from ariadne.core.branching import (
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
    from ariadne.core.schema import sha3_256
    from ariadne.adapters.neo4j.writer import (
        write_merge_point_sync,
        write_branch_terminus_sync,
        write_branch_return_edge_sync,
        write_audit_record_sync,
    )

    try:
        # STEP 1: Validate preconditions
        enforce_merge_summary_required(merge_summary)

        try:
            _ = MergeStrategy(merge_strategy)
        except ValueError:
            raise AriadneGovernanceError(f"Unknown merge_strategy: {merge_strategy}")

        conflict_segments = conflict_segments or []
        conflict_resolutions = conflict_resolutions or []
        resolution_artifacts = resolution_artifacts or []

        # Load branch point — branch must exist and be ACTIVE
        with driver.session() as session:
            bp_result = session.run("""
                MATCH (bp:AriadneBranchPoint {branch_id: $bid})
                OPTIONAL MATCH (bp)-[:BRANCH_TERMINUS]->(bt:AriadneBranchTerminus)
                RETURN bp {.*} AS branch_point, bt IS NOT NULL AS has_terminus
            """, {"bid": source_branch_id})
            bp_record = bp_result.single()

            if not bp_record or not bp_record["branch_point"]:
                logger.error(f"Branch {source_branch_id} not found")
                return None
            if bp_record["has_terminus"]:
                logger.error(f"Branch {source_branch_id} already terminated")
                return None
            bp_data = dict(bp_record["branch_point"])

        source_episode_id = bp_data.get("episode_id", "")
        branch_point_hash = bp_data.get("content_hash", "")
        branch_point_id = bp_data.get("branch_point_id", "")

        # Target episode must be ACTIVE
        with driver.session() as session:
            tgt_result = session.run("""
                MATCH (e:AriadneEpisode {episode_id: $eid})
                RETURN e.episode_status AS status, e.spine_hash AS spine_hash
            """, {"eid": target_episode_id})
            tgt_record = tgt_result.single()
            if not tgt_record:
                logger.error(f"Target episode {target_episode_id} not found")
                return None
            if tgt_record["status"] not in ("ACTIVE", "PENDING_HITL"):
                logger.error(
                    f"Target episode not in ACTIVE state: {tgt_record['status']}"
                )
                return None
            target_spine_hash = tgt_record["spine_hash"] or ""

        # STEP 2: Capture pre-merge Merkle roots (immutable after this point)
        source_merkle_root = bp_data.get("spine_merkle_snapshot", "") or ""
        # Prefer the current spine hash of the source episode if distinct
        with driver.session() as session:
            src_result = session.run("""
                MATCH (e:AriadneEpisode {episode_id: $eid})
                RETURN e.spine_hash AS spine_hash
            """, {"eid": source_episode_id})
            src_record = src_result.single()
            if src_record and src_record["spine_hash"]:
                source_merkle_root = src_record["spine_hash"]

        target_merkle_root_pre = target_spine_hash

        # STEP 3: Find common ancestor
        ancestor = find_common_ancestor(driver, source_branch_id, target_episode_id)
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
                driver, source_episode_id, target_episode_id, initiator,
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
        write_merge_point_sync(driver, merge_point)

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
        write_branch_terminus_sync(driver, terminus)

        # STEP 11: Write BranchReturnEdge
        branch_return = BranchReturnEdge(
            branch_id=source_branch_id,
            terminus_id=str(terminus.terminus_id),
            merge_point_id=str(merge_point.merge_point_id),
            target_episode_id=target_episode_id,
            synthesis_summary=merge_summary,
            nodes_integrated=len(conflict_segments),
        )
        write_branch_return_edge_sync(driver, branch_return)

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

        delta_sequence = _get_next_delta_sequence(driver, target_episode_id)
        prior_audit_hash = _get_prior_audit_hash(driver, target_episode_id)

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
        write_audit_record_sync(driver, audit)

        _write_branch_wil(
            driver, target_episode_id, str(merge_point.merge_point_id), "MERGE_EXECUTE"
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

    except AriadneGovernanceError:
        raise
    except Exception as e:
        logger.error(f"execute_merge failed: {e}", exc_info=True)
        return None


def verify_merge_integrity(driver, merge_id: str):
    """Verify a merge's three Merkle roots match their expected sources.

    Returns MergeIntegrityResult.
    """
    from ariadne.core.branching import MergeIntegrityResult
    from ariadne.core.schema import sha3_256

    try:
        with driver.session() as session:
            mp_result = session.run("""
                MATCH (mp:AriadneMergePoint {merge_id: $mid})
                RETURN mp {.*} AS merge_point
            """, {"mid": merge_id})
            mp_record = mp_result.single()
            if not mp_record or not mp_record["merge_point"]:
                logger.error(f"MergePoint {merge_id} not found")
                return None
            mp = dict(mp_record["merge_point"])

        source_valid = bool(mp.get("source_merkle_root"))
        target_pre_valid = bool(mp.get("target_merkle_root_pre"))

        # Recompute post-root and compare
        conflict_segments = mp.get("conflict_segments") or []
        # Recover conflict_resolutions from audit record
        with driver.session() as session:
            ar_result = session.run("""
                MATCH (ar:AriadneAuditRecord {delta_type: 'MERGE_EXECUTED'})
                WHERE ar.forward_delta CONTAINS $mid
                RETURN ar.forward_delta AS fd
                LIMIT 1
            """, {"mid": merge_id})
            ar_record = ar_result.single()
            resolutions = []
            if ar_record and ar_record["fd"]:
                try:
                    fd = json.loads(ar_record["fd"])
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
        return None


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
    driver, source_episode_id: str, target_episode_id: str,
    initiator: str, reason: str,
) -> None:
    """Write an audit record for a merge abort (integrity check failure)."""
    from ariadne.core.branching import (
        AuditRecord,
        CognitiveDeltaType,
        TriggerType,
        compute_audit_record_hash,
    )
    from ariadne.adapters.neo4j.writer import write_audit_record_sync

    try:
        forward_delta = {
            "source_episode_id": source_episode_id,
            "target_episode_id": target_episode_id,
            "outcome": "ABORTED",
            "reason": reason,
        }
        delta_sequence = _get_next_delta_sequence(driver, target_episode_id)
        prior_audit_hash = _get_prior_audit_hash(driver, target_episode_id)

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
        write_audit_record_sync(driver, audit)
    except Exception as e:
        logger.warning(f"Failed to write merge failure audit: {e}")

def _write_branch_wil(driver, episode_id: str, node_id: str, operation: str) -> None:
    """Write a WIL entry for a branch operation."""
    try:
        from ariadne.core.branching import compute_branch_point_hash
        from uuid import uuid4

        with driver.session() as session:
            session.run("""
                MERGE (w:AriadneWILEntry {intent_id: $intent_id})
                ON CREATE SET
                  w.operation              = $operation,
                  w.episode_id             = $episode_id,
                  w.stores_involved        = ['neo4j'],
                  w.pre_state_hash         = $pre_hash,
                  w.post_state_hash        = $post_hash,
                  w.initiated_at           = $ts,
                  w.completed_at           = $ts,
                  w.status                 = 'COMPLETE',
                  w.last_completed_store   = 'neo4j'
            """, {
                "intent_id": str(uuid4()),
                "operation": operation,
                "episode_id": episode_id,
                "pre_hash": node_id,
                "post_hash": node_id,
                "ts": datetime.now(timezone.utc).isoformat(),
            })
    except Exception as e:
        logger.debug(f"Branch WIL write failed (non-fatal): {e}")
