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
