"""
Ariadne Neo4j write operations.
All writes are gated by ARIADNE_ENABLED feature flag.

Spec 5 of Phase 2 Ariadne Persistence Layer.

IMPORTANT: Neo4j session.run() signature is run(query, parameters=None, **kwargs).
All parameters are passed as an explicit dict (positional arg) to avoid collisions
with session.run()'s own 'parameters' argument. See bdi.py commit history for context.
"""

import logging
import os
from uuid import UUID

from ariadne.core.schema import (
    AriadneGovernanceError,
    DocumentNode,
    EpisodeNode,
    EpisodeStatus,
    ExclusionRecord,
    ReferenceType,
    SealNode,
    SegmentNode,
    SignalNode,
    enforce_G1_write_guard,
    enforce_G5_placement_rationale,
    enforce_G7_triggered_edge,
    validate_signal_classification,
)

logger = logging.getLogger("ariadne.adapters.neo4j")

ARIADNE_ENABLED = os.getenv("ARIADNE_ENABLED", "false").lower() == "true"


def _ariadne_guard() -> bool:
    if not ARIADNE_ENABLED:
        return False
    return True


# ── Schema Initialization ────────────────────────────────────────────────────

SCHEMA_CONSTRAINTS = [
    "CREATE CONSTRAINT ariadne_episode_id IF NOT EXISTS FOR (e:AriadneEpisode) REQUIRE e.episode_id IS UNIQUE",
    "CREATE CONSTRAINT ariadne_segment_id IF NOT EXISTS FOR (s:AriadneSegment) REQUIRE s.segment_id IS UNIQUE",
    "CREATE CONSTRAINT ariadne_signal_id IF NOT EXISTS FOR (sig:AriadneSignal) REQUIRE sig.signal_id IS UNIQUE",
    "CREATE CONSTRAINT ariadne_seal_id IF NOT EXISTS FOR (seal:AriadneSeal) REQUIRE seal.seal_id IS UNIQUE",
    "CREATE CONSTRAINT ariadne_exclusion_id IF NOT EXISTS FOR (ex:AriadneExclusion) REQUIRE ex.exclusion_id IS UNIQUE",
    # Spec 7: Crystallization delta uniqueness
    "CREATE CONSTRAINT ariadne_crystallization_delta_id IF NOT EXISTS FOR (cd:AriadneCrystallizationDelta) REQUIRE cd.delta_id IS UNIQUE",
    # Spec 8: WIL and manifest uniqueness
    "CREATE CONSTRAINT ariadne_wil_intent_id IF NOT EXISTS FOR (w:AriadneWILEntry) REQUIRE w.intent_id IS UNIQUE",
    "CREATE CONSTRAINT ariadne_manifest_episode_id IF NOT EXISTS FOR (m:AriadneSignalManifest) REQUIRE m.episode_id IS UNIQUE",
    # Spec 9: Consultation Node uniqueness
    "CREATE CONSTRAINT ariadne_consultation_id IF NOT EXISTS FOR (c:AriadneConsultation) REQUIRE c.consultation_id IS UNIQUE",
    "CREATE CONSTRAINT ariadne_exchange_entry_id IF NOT EXISTS FOR (ex:AriadneExchangeEntry) REQUIRE ex.entry_id IS UNIQUE",
    "CREATE CONSTRAINT ariadne_consultation_participant_id IF NOT EXISTS FOR (cp:AriadneConsultationParticipant) REQUIRE cp.participant_id IS UNIQUE",
    # Document Nodes
    "CREATE CONSTRAINT ariadne_document_id IF NOT EXISTS FOR (doc:AriadneDocument) REQUIRE doc.document_id IS UNIQUE",
    # Spec: Episode Closure
    "CREATE CONSTRAINT ariadne_codicil_id IF NOT EXISTS FOR (cod:AriadneCodicil) REQUIRE cod.codicil_id IS UNIQUE",
    "CREATE CONSTRAINT ariadne_closure_id IF NOT EXISTS FOR (cl:AriadneClosureRecord) REQUIRE cl.closure_id IS UNIQUE",
    "CREATE CONSTRAINT ariadne_amendment_id IF NOT EXISTS FOR (am:AriadneAmendment) REQUIRE am.amendment_id IS UNIQUE",
    # HITL Event Nodes (Protocol Amendment v1.2.0)
    "CREATE CONSTRAINT ariadne_hitl_event_id IF NOT EXISTS FOR (h:AriadneHITLEvent) REQUIRE h.hitl_event_id IS UNIQUE",
    # Branch/Fork/Merge (Phase 1)
    "CREATE CONSTRAINT ariadne_branch_point_id IF NOT EXISTS FOR (bp:AriadneBranchPoint) REQUIRE bp.branch_point_id IS UNIQUE",
    "CREATE CONSTRAINT ariadne_branch_terminus_id IF NOT EXISTS FOR (bt:AriadneBranchTerminus) REQUIRE bt.terminus_id IS UNIQUE",
    "CREATE CONSTRAINT ariadne_audit_record_id IF NOT EXISTS FOR (ar:AriadneAuditRecord) REQUIRE ar.audit_id IS UNIQUE",
    "CREATE CONSTRAINT ariadne_intent_record_id IF NOT EXISTS FOR (ir:AriadneIntentRecord) REQUIRE ir.intent_id IS UNIQUE",
    "CREATE CONSTRAINT ariadne_intent_idempotency IF NOT EXISTS FOR (ir:AriadneIntentRecord) REQUIRE ir.idempotency_key IS UNIQUE",
]

SCHEMA_INDEXES = [
    "CREATE INDEX ariadne_episode_status IF NOT EXISTS FOR (e:AriadneEpisode) ON (e.episode_status)",
    "CREATE INDEX ariadne_episode_agent IF NOT EXISTS FOR (e:AriadneEpisode) ON (e.agent_id)",
    "CREATE INDEX ariadne_episode_schema_version IF NOT EXISTS FOR (e:AriadneEpisode) ON (e.schema_version)",
    "CREATE INDEX ariadne_episode_opened_at IF NOT EXISTS FOR (e:AriadneEpisode) ON (e.opened_at)",
    "CREATE INDEX ariadne_episode_workspace IF NOT EXISTS FOR (e:AriadneEpisode) ON (e.workspace_id)",
    "CREATE INDEX ariadne_segment_episode IF NOT EXISTS FOR (s:AriadneSegment) ON (s.episode_id)",
    "CREATE INDEX ariadne_signal_episode IF NOT EXISTS FOR (sig:AriadneSignal) ON (sig.episode_id)",
    "CREATE INDEX ariadne_signal_type IF NOT EXISTS FOR (sig:AriadneSignal) ON (sig.signal_type)",
    "CREATE INDEX ariadne_signal_class IF NOT EXISTS FOR (sig:AriadneSignal) ON (sig.signal_class)",
    "CREATE INDEX ariadne_signal_status IF NOT EXISTS FOR (sig:AriadneSignal) ON (sig.signal_status)",
    # Spec 6: BDI Bridge indexes for intention-episode linkage
    "CREATE INDEX ariadne_intention_episode IF NOT EXISTS FOR (i:Intention) ON (i.episode_id)",
    "CREATE INDEX ariadne_intention_status IF NOT EXISTS FOR (i:Intention) ON (i.status)",
    "CREATE INDEX ariadne_intention_key IF NOT EXISTS FOR (i:Intention) ON (i.intention_key)",
    # Spec 7: Crystallization delta indexes
    "CREATE INDEX ariadne_crystallization_episode IF NOT EXISTS FOR (cd:AriadneCrystallizationDelta) ON (cd.episode_id)",
    "CREATE INDEX ariadne_crystallization_chain_position IF NOT EXISTS FOR (cd:AriadneCrystallizationDelta) ON (cd.chain_position)",
    # Spec 8: WIL indexes
    "CREATE INDEX ariadne_wil_episode IF NOT EXISTS FOR (w:AriadneWILEntry) ON (w.episode_id)",
    "CREATE INDEX ariadne_wil_status IF NOT EXISTS FOR (w:AriadneWILEntry) ON (w.status)",
    # Spec 9: Consultation indexes
    "CREATE INDEX ariadne_consultation_episode IF NOT EXISTS FOR (c:AriadneConsultation) ON (c.episode_id)",
    "CREATE INDEX ariadne_consultation_type IF NOT EXISTS FOR (c:AriadneConsultation) ON (c.consultation_type)",
    "CREATE INDEX ariadne_consultation_initiating_agent IF NOT EXISTS FOR (c:AriadneConsultation) ON (c.initiating_agent)",
    "CREATE INDEX ariadne_exchange_consultation IF NOT EXISTS FOR (ex:AriadneExchangeEntry) ON (ex.consultation_id)",
    "CREATE INDEX ariadne_participant_consultation IF NOT EXISTS FOR (cp:AriadneConsultationParticipant) ON (cp.consultation_id)",
    "CREATE INDEX ariadne_participant_episode IF NOT EXISTS FOR (cp:AriadneConsultationParticipant) ON (cp.episode_id)",
    # Document indexes
    "CREATE INDEX ariadne_document_episode IF NOT EXISTS FOR (doc:AriadneDocument) ON (doc.episode_id)",
    # Episode Closure indexes
    "CREATE INDEX ariadne_codicil_episode IF NOT EXISTS FOR (cod:AriadneCodicil) ON (cod.episode_id)",
    "CREATE INDEX ariadne_closure_episode IF NOT EXISTS FOR (cl:AriadneClosureRecord) ON (cl.episode_id)",
    "CREATE INDEX ariadne_amendment_source IF NOT EXISTS FOR (am:AriadneAmendment) ON (am.source_episode_id)",
    # HITL Event indexes (Protocol Amendment v1.2.0)
    "CREATE INDEX ariadne_hitl_episode IF NOT EXISTS FOR (h:AriadneHITLEvent) ON (h.episode_id)",
    "CREATE INDEX ariadne_hitl_status IF NOT EXISTS FOR (h:AriadneHITLEvent) ON (h.status)",
    "CREATE INDEX ariadne_hitl_gate_type IF NOT EXISTS FOR (h:AriadneHITLEvent) ON (h.gate_type)",
    "CREATE INDEX ariadne_hitl_request_id IF NOT EXISTS FOR (h:AriadneHITLEvent) ON (h.hitl_request_id)",
    # Branch/Fork/Merge indexes (Phase 1)
    "CREATE INDEX ariadne_branch_point_episode IF NOT EXISTS FOR (bp:AriadneBranchPoint) ON (bp.episode_id)",
    "CREATE INDEX ariadne_branch_point_branch_id IF NOT EXISTS FOR (bp:AriadneBranchPoint) ON (bp.branch_id)",
    "CREATE INDEX ariadne_branch_terminus_branch IF NOT EXISTS FOR (bt:AriadneBranchTerminus) ON (bt.branch_id)",
    "CREATE INDEX ariadne_audit_episode IF NOT EXISTS FOR (ar:AriadneAuditRecord) ON (ar.episode_id)",
    "CREATE INDEX ariadne_audit_sequence IF NOT EXISTS FOR (ar:AriadneAuditRecord) ON (ar.delta_sequence)",
    "CREATE INDEX ariadne_intent_status IF NOT EXISTS FOR (ir:AriadneIntentRecord) ON (ir.status)",
    "CREATE INDEX ariadne_episode_parent IF NOT EXISTS FOR (e:AriadneEpisode) ON (e.parent_episode_id)",
]

SCHEMA_VERSION_SEED = """
MERGE (sv:AriadneSchemaVersion {version: "1.2.0"})
ON CREATE SET
  sv.seeded_at            = datetime(),
  sv.hash_algorithm       = "SHA3-256",
  sv.domain_separation    = "LEAF: prefix for leaves; NODE: prefix for internal nodes; HITL_CTX: for HITL context; HITL_RES: for HITL resolution",
  sv.episode_root_formula = "H(NODE: spine_hash || signal_manifest_hash || exclusion_hash)",
  sv.status               = "ACTIVE",
  sv.notes                = "v1.2.0: HITLEventNode as first-class Ariadne node type with two-phase lifecycle, HITL_GATE edges, and governance rule G-10."
"""


async def initialize_ariadne_schema(driver) -> None:
    """Create all Ariadne constraints, indexes, and schema version seed.
    Called on startup when ARIADNE_ENABLED=true."""
    if not _ariadne_guard():
        logger.info("Ariadne schema init skipped (ARIADNE_ENABLED=false)")
        return

    logger.info("Initializing Ariadne Neo4j schema...")
    async with driver.session() as session:
        for constraint in SCHEMA_CONSTRAINTS:
            await session.run(constraint)
        for index in SCHEMA_INDEXES:
            await session.run(index)
        await session.run(SCHEMA_VERSION_SEED)
    logger.info("Ariadne Neo4j schema initialized (5 constraints, 9 indexes, schema version seed)")


# ── Node Creation ─────────────────────────────────────────────────────────────

def _serialize_uuid(val) -> str:
    """Convert UUID or string to string for Neo4j."""
    return str(val) if val is not None else None


def _episode_params(episode: EpisodeNode) -> dict:
    """Build Neo4j parameter dict from EpisodeNode, avoiding session.run() kwarg collision."""
    return {
        "episode_id": str(episode.episode_id),
        "schema_version": episode.schema_version,
        "agent_id": episode.agent_id,
        "opened_at": episode.opened_at.isoformat(),
        "episode_status": episode.episode_status.value,
        "crystallization_status": episode.crystallization_status.value if episode.crystallization_status else None,
        "participants": episode.participants,
        "parent_episode_id": str(episode.parent_episode_id) if episode.parent_episode_id else None,
        "fork_reason": episode.fork_reason,
        "workspace_id": episode.workspace_id,
        "title": episode.title,
        "context_note": episode.context_note,
        "episode_type": episode.episode_type,
        "initiated_by": episode.initiated_by,
        "episode_mode": episode.episode_mode,
    }


async def create_episode_node(driver, episode: EpisodeNode) -> None:
    if not _ariadne_guard():
        return
    params = _episode_params(episode)
    async with driver.session() as session:
        await session.run("""
            MERGE (e:AriadneEpisode {episode_id: $episode_id})
            ON CREATE SET
              e.schema_version         = $schema_version,
              e.agent_id               = $agent_id,
              e.opened_at              = $opened_at,
              e.episode_status         = $episode_status,
              e.crystallization_status = $crystallization_status,
              e.participants           = $participants,
              e.parent_episode_id      = $parent_episode_id,
              e.fork_reason            = $fork_reason,
              e.workspace_id           = $workspace_id,
              e.title                  = $title,
              e.context_note           = $context_note,
              e.episode_type           = $episode_type,
              e.initiated_by           = $initiated_by,
              e.spine_hash             = null,
              e.signal_manifest_hash   = null,
              e.episode_root_hash      = null,
              e.sealed_at              = null,
              e.archived_at            = null
        """, params)


async def create_segment_node(driver, segment: SegmentNode, episode_status: EpisodeStatus) -> None:
    if not _ariadne_guard():
        return
    enforce_G1_write_guard(episode_status)  # Rule G-1
    from ariadne.core.crystallization import enforce_crystallization_lock_guard
    enforce_crystallization_lock_guard(episode_status.value)  # Spec 7
    params = {
        "segment_id": str(segment.segment_id),
        "episode_id": str(segment.episode_id),
        "segment_type": segment.segment_type.value,
        "sequence_index": segment.sequence_index,
        "content_hash": segment.content_hash,
        "content_ref": segment.content_ref,
        "authored_at": segment.authored_at.isoformat(),
        "author": segment.author,
    }
    async with driver.session() as session:
        await session.run("""
            MERGE (s:AriadneSegment {segment_id: $segment_id})
            ON CREATE SET
              s.episode_id     = $episode_id,
              s.segment_type   = $segment_type,
              s.sequence_index = $sequence_index,
              s.content_hash   = $content_hash,
              s.content_ref    = $content_ref,
              s.authored_at    = $authored_at,
              s.author         = $author
        """, params)
        # CONTAINS edge: EpisodeNode -> SegmentNode
        await session.run("""
            MATCH (e:AriadneEpisode {episode_id: $episode_id})
            MATCH (s:AriadneSegment {segment_id: $segment_id})
            MERGE (e)-[:CONTAINS {sequence_index: $sequence_index}]->(s)
        """, {
            "episode_id": str(segment.episode_id),
            "segment_id": str(segment.segment_id),
            "sequence_index": segment.sequence_index,
        })


async def create_signal_node(
    driver,
    signal: SignalNode,
    episode_status: EpisodeStatus,
    triggered_segment_ids: list[str] | None = None,
) -> None:
    if not _ariadne_guard():
        return
    enforce_G1_write_guard(episode_status)  # Rule G-1
    from ariadne.core.crystallization import enforce_crystallization_lock_guard
    enforce_crystallization_lock_guard(episode_status.value)  # Spec 7
    enforce_G5_placement_rationale(signal)  # Rule G-5
    validate_signal_classification(signal)  # Taxonomy rules
    has_triggered = bool(triggered_segment_ids)
    enforce_G7_triggered_edge(signal, has_triggered)  # Rule G-7

    params = {
        "signal_id": str(signal.signal_id),
        "episode_id": str(signal.episode_id),
        "signal_type": signal.signal_type.value,
        "signal_class": signal.signal_class.value,
        "signal_source": signal.signal_source,
        "received_at": signal.received_at.isoformat(),
        "signal_status": signal.signal_status.value,
        "content_hash": signal.content_hash,
        "content_ref": signal.content_ref,
        "placement": signal.placement.value,
        "placement_rationale": signal.placement_rationale,
        "influenced_segments": signal.influenced_segments,
        "persistence_confirmed": signal.persistence_confirmed,
        "payload_ref": signal.payload_ref,
    }
    async with driver.session() as session:
        await session.run("""
            MERGE (sig:AriadneSignal {signal_id: $signal_id})
            ON CREATE SET
              sig.episode_id             = $episode_id,
              sig.signal_type            = $signal_type,
              sig.signal_class           = $signal_class,
              sig.signal_source          = $signal_source,
              sig.received_at            = $received_at,
              sig.signal_status          = $signal_status,
              sig.content_hash           = $content_hash,
              sig.content_ref            = $content_ref,
              sig.placement              = $placement,
              sig.placement_rationale    = $placement_rationale,
              sig.influenced_segments    = $influenced_segments,
              sig.persistence_confirmed  = $persistence_confirmed,
              sig.payload_ref            = $payload_ref
        """, params)
        # RECEIVED edge: EpisodeNode -> SignalNode
        await session.run("""
            MATCH (e:AriadneEpisode {episode_id: $episode_id})
            MATCH (sig:AriadneSignal {signal_id: $signal_id})
            MERGE (e)-[:RECEIVED {received_at: $received_at}]->(sig)
        """, {
            "episode_id": str(signal.episode_id),
            "signal_id": str(signal.signal_id),
            "received_at": signal.received_at.isoformat(),
        })
        # TRIGGERED edges for causal signals (Rule G-7)
        if triggered_segment_ids:
            for seg_id in triggered_segment_ids:
                await session.run("""
                    MATCH (sig:AriadneSignal {signal_id: $signal_id})
                    MATCH (s:AriadneSegment {segment_id: $segment_id})
                    MERGE (sig)-[:TRIGGERED]->(s)
                """, {
                    "signal_id": str(signal.signal_id),
                    "segment_id": seg_id,
                })


async def create_seal_node(driver, seal: SealNode) -> None:
    if not _ariadne_guard():
        return
    params = {
        "seal_id": str(seal.seal_id),
        "episode_id": str(seal.episode_id),
        "sealed_at": seal.sealed_at.isoformat(),
        "sealed_by": seal.sealed_by,
        "spine_hash": seal.spine_hash,
        "signal_manifest_hash": seal.signal_manifest_hash,
        "exclusion_hash": seal.exclusion_hash,
        "episode_root_hash": seal.episode_root_hash,
        "write_intent_id": str(seal.write_intent_id),
        "seal_status": seal.seal_status.value,
        "agent_signature": seal.agent_signature,
        "mnemosyne_countersignature": seal.mnemosyne_countersignature,
    }
    async with driver.session() as session:
        await session.run("""
            MERGE (seal:AriadneSeal {seal_id: $seal_id})
            ON CREATE SET
              seal.episode_id                    = $episode_id,
              seal.sealed_at                     = $sealed_at,
              seal.sealed_by                     = $sealed_by,
              seal.spine_hash                    = $spine_hash,
              seal.signal_manifest_hash          = $signal_manifest_hash,
              seal.exclusion_hash                = $exclusion_hash,
              seal.episode_root_hash             = $episode_root_hash,
              seal.write_intent_id               = $write_intent_id,
              seal.seal_status                   = $seal_status,
              seal.agent_signature               = $agent_signature,
              seal.mnemosyne_countersignature    = $mnemosyne_countersignature
        """, params)
        # SEALS edge: SealNode -> EpisodeNode
        await session.run("""
            MATCH (seal:AriadneSeal {seal_id: $seal_id})
            MATCH (e:AriadneEpisode {episode_id: $episode_id})
            MERGE (seal)-[:SEALS {sealed_at: $sealed_at}]->(e)
        """, {
            "seal_id": str(seal.seal_id),
            "episode_id": str(seal.episode_id),
            "sealed_at": seal.sealed_at.isoformat(),
        })
        # Update episode status to SEALED
        await session.run("""
            MATCH (e:AriadneEpisode {episode_id: $episode_id})
            SET e.episode_status       = 'SEALED',
                e.sealed_at            = $sealed_at,
                e.spine_hash           = $spine_hash,
                e.signal_manifest_hash = $signal_manifest_hash,
                e.episode_root_hash    = $episode_root_hash
        """, {
            "episode_id": str(seal.episode_id),
            "sealed_at": seal.sealed_at.isoformat(),
            "spine_hash": seal.spine_hash,
            "signal_manifest_hash": seal.signal_manifest_hash,
            "episode_root_hash": seal.episode_root_hash,
        })


async def create_exclusion_record(driver, exclusion: ExclusionRecord) -> None:
    if not _ariadne_guard():
        return
    params = {
        "exclusion_id": str(exclusion.exclusion_id),
        "episode_id": str(exclusion.episode_id),
        "signal_id": str(exclusion.signal_id),
        "excluded_at": exclusion.excluded_at.isoformat(),
        "exclusion_reason": exclusion.exclusion_reason.value,
        "signal_content_hash": exclusion.signal_content_hash,
    }
    async with driver.session() as session:
        await session.run("""
            MERGE (ex:AriadneExclusion {exclusion_id: $exclusion_id})
            ON CREATE SET
              ex.episode_id          = $episode_id,
              ex.signal_id           = $signal_id,
              ex.excluded_at         = $excluded_at,
              ex.exclusion_reason    = $exclusion_reason,
              ex.signal_content_hash = $signal_content_hash
        """, params)


async def create_segment_reference_edge(
    driver,
    from_segment_id: str,
    to_segment_id: str,
    reference_type: ReferenceType,
) -> None:
    """REFERENCES edge: SegmentNode -> SegmentNode."""
    if not _ariadne_guard():
        return
    async with driver.session() as session:
        await session.run("""
            MATCH (a:AriadneSegment {segment_id: $from_id})
            MATCH (b:AriadneSegment {segment_id: $to_id})
            MERGE (a)-[:REFERENCES {reference_type: $ref_type}]->(b)
        """, {
            "from_id": from_segment_id,
            "to_id": to_segment_id,
            "ref_type": reference_type.value,
        })


async def create_branch_episode(
    driver,
    branch_episode: EpisodeNode,
    parent_episode_id: str,
    fork_at_segment_id: str,
) -> None:
    """
    Creates a branch episode and the BRANCHES_FROM edge.
    Rule G-2: parent episode must be in ACTIVE state.
    """
    if not _ariadne_guard():
        return
    async with driver.session() as session:
        # Verify G-2
        result = await session.run("""
            MATCH (e:AriadneEpisode {episode_id: $parent_id})
            RETURN e.episode_status AS status
        """, {"parent_id": parent_episode_id})
        record = await result.single()
        if not record or record["status"] != EpisodeStatus.ACTIVE.value:
            raise AriadneGovernanceError(
                f"G-2 violation: Cannot branch from episode {parent_episode_id} "
                f"-- it is not in ACTIVE state."
            )
    await create_episode_node(driver, branch_episode)
    async with driver.session() as session:
        await session.run("""
            MATCH (parent:AriadneEpisode {episode_id: $parent_id})
            MATCH (branch:AriadneEpisode {episode_id: $branch_id})
            MERGE (branch)-[:BRANCHES_FROM {
              fork_at_segment: $fork_segment,
              fork_reason:     $fork_reason
            }]->(parent)
        """, {
            "parent_id": parent_episode_id,
            "branch_id": str(branch_episode.episode_id),
            "fork_segment": fork_at_segment_id,
            "fork_reason": branch_episode.fork_reason or "",
        })


def write_document_node_sync(driver, document: DocumentNode) -> None:
    """
    Create an AriadneDocument node and ATTACHED_TO edge to its episode.
    Sync variant — safe to call from non-async artifact service.

    This is used both by the user-upload path (server.py endpoint) and
    the artifact→Ariadne bridge (when agent-produced artifacts are published).
    """
    if not _ariadne_guard():
        return

    try:
        with driver.session() as session:
            # Verify episode exists
            result = session.run(
                "MATCH (e:AriadneEpisode {episode_id: $ep_id}) RETURN e.episode_id AS id",
                {"ep_id": str(document.episode_id)},
            )
            if not result.single():
                logger.warning(
                    f"Ariadne: Cannot attach document — episode {document.episode_id} not found"
                )
                return

            # Create document node
            session.run("""
                CREATE (doc:AriadneDocument {
                    document_id:    $doc_id,
                    episode_id:     $episode_id,
                    filename:       $filename,
                    mime_type:      $mime_type,
                    source:         $source,
                    source_ref:     $source_ref,
                    drive_url:      $drive_url,
                    content_hash:   $content_hash,
                    content_text:   $content_text,
                    char_count:     $char_count,
                    attached_by:    $attached_by,
                    attached_at:    $attached_at,
                    schema_version: $schema_version
                })
            """, {
                "doc_id": str(document.document_id),
                "episode_id": str(document.episode_id),
                "filename": document.filename,
                "mime_type": document.mime_type or "text/markdown",
                "source": document.source,
                "source_ref": document.source_ref,
                "drive_url": document.drive_url,
                "content_hash": document.content_hash,
                "content_text": (document.content_text or "")[:50000],
                "char_count": document.char_count,
                "attached_by": document.attached_by,
                "attached_at": document.attached_at.isoformat()
                    if hasattr(document.attached_at, 'isoformat')
                    else str(document.attached_at),
                "schema_version": document.schema_version,
            })

            # ATTACHED_TO edge
            session.run("""
                MATCH (e:AriadneEpisode {episode_id: $episode_id})
                MATCH (doc:AriadneDocument {document_id: $doc_id})
                CREATE (doc)-[:ATTACHED_TO {attached_at: $attached_at}]->(e)
            """, {
                "episode_id": str(document.episode_id),
                "doc_id": str(document.document_id),
                "attached_at": document.attached_at.isoformat()
                    if hasattr(document.attached_at, 'isoformat')
                    else str(document.attached_at),
            })

            logger.info(
                f"Ariadne: Document '{document.filename}' attached to episode "
                f"{str(document.episode_id)[:8]}..."
            )

    except Exception as e:
        logger.warning(f"Ariadne: Failed to write document node: {e}")


# ── HITL Event Writer (Protocol Amendment v1.2.0) ────────────────────────────


def write_hitl_event_invocation_sync(driver, hitl_event) -> None:
    """Write Phase 1 of a HITL event — the invocation record.

    Creates an AriadneHITLEvent node in INVOKED status and a HITL_GATE
    edge from the episode. The node is immutable after this write until
    the INVOKED → RESOLVED transition.

    Sync variant — called from HITLService.request_intervention() which
    runs in the server's sync context.
    """
    if not _ariadne_guard():
        return

    try:
        from ariadne.core.schema import ARIADNE_SCHEMA_VERSION

        with driver.session() as session:
            # Create HITLEventNode
            session.run("""
                MERGE (h:AriadneHITLEvent {hitl_event_id: $hitl_event_id})
                ON CREATE SET
                  h.episode_id            = $episode_id,
                  h.hitl_request_id       = $hitl_request_id,
                  h.gate_type             = $gate_type,
                  h.status                = $status,
                  h.requesting_agent      = $requesting_agent,
                  h.invoked_at            = $invoked_at,
                  h.timeout_at            = $timeout_at,
                  h.spine_snapshot_index  = $spine_snapshot_index,
                  h.context_hash          = $context_hash,
                  h.invocation_signature  = $invocation_signature,
                  h.invocation_key_fingerprint = $invocation_key_fingerprint,
                  h.schema_version        = $schema_version
            """, {
                "hitl_event_id": str(hitl_event.hitl_event_id),
                "episode_id": str(hitl_event.episode_id),
                "hitl_request_id": hitl_event.hitl_request_id,
                "gate_type": hitl_event.gate_type.value,
                "status": hitl_event.status.value,
                "requesting_agent": hitl_event.requesting_agent,
                "invoked_at": hitl_event.invoked_at.isoformat()
                    if hasattr(hitl_event.invoked_at, 'isoformat')
                    else str(hitl_event.invoked_at),
                "timeout_at": hitl_event.timeout_at.isoformat()
                    if hitl_event.timeout_at and hasattr(hitl_event.timeout_at, 'isoformat')
                    else None,
                "spine_snapshot_index": hitl_event.spine_snapshot_index,
                "context_hash": hitl_event.context_hash,
                "invocation_signature": hitl_event.invocation_signature,
                "invocation_key_fingerprint": hitl_event.invocation_key_fingerprint,
                "schema_version": ARIADNE_SCHEMA_VERSION,
            })

            # HITL_GATE edge: Episode -> HITLEvent
            blocking = hitl_event.gate_type.value in (
                "approval_required", "compliance_checkpoint"
            )
            session.run("""
                MATCH (e:AriadneEpisode {episode_id: $episode_id})
                MATCH (h:AriadneHITLEvent {hitl_event_id: $hitl_event_id})
                MERGE (e)-[:HITL_GATE {
                    gate_type: $gate_type,
                    invoked_at: $invoked_at,
                    blocking: $blocking,
                    dependency: $dependency
                }]->(h)
            """, {
                "episode_id": str(hitl_event.episode_id),
                "hitl_event_id": str(hitl_event.hitl_event_id),
                "gate_type": hitl_event.gate_type.value,
                "invoked_at": hitl_event.invoked_at.isoformat()
                    if hasattr(hitl_event.invoked_at, 'isoformat')
                    else str(hitl_event.invoked_at),
                "blocking": blocking,
                "dependency": "BLOCKS" if blocking else "FOLLOWS",
            })

        logger.info(
            f"Ariadne: HITL invocation recorded {str(hitl_event.hitl_event_id)[:8]}... "
            f"[{hitl_event.requesting_agent} → {hitl_event.gate_type.value}] "
            f"(episode={str(hitl_event.episode_id)[:8]}...)"
        )

    except Exception as e:
        logger.warning(f"Ariadne: Failed to write HITL invocation: {e}")


def write_hitl_event_resolution_sync(
    driver,
    hitl_event_id: str,
    decision: str,
    resolved_by: str,
    resolved_at: str,
    rationale: str,
    resolution_hash: str,
    node_hash: str,
    pending_duration_ms: int = None,
    resolution_signature: str = None,
    resolution_key_fingerprint: str = None,
) -> None:
    """Write Phase 2 of a HITL event — the resolution record.

    Updates an existing AriadneHITLEvent node from INVOKED to RESOLVED
    (or TIMED_OUT/ESCALATED). This is the one permitted mutation on an
    otherwise immutable node — enforced by G-10 governance.

    Sync variant — called from resolve_hitl_request in server.py.
    """
    if not _ariadne_guard():
        return

    try:
        with driver.session() as session:
            result = session.run("""
                MATCH (h:AriadneHITLEvent {hitl_event_id: $hitl_event_id})
                WHERE h.status = 'invoked'
                SET h.status              = $status,
                    h.decision            = $decision,
                    h.resolved_by         = $resolved_by,
                    h.resolved_at         = $resolved_at,
                    h.rationale           = $rationale,
                    h.resolution_hash     = $resolution_hash,
                    h.node_hash           = $node_hash,
                    h.pending_duration_ms = $pending_duration_ms,
                    h.resolution_signature = $resolution_signature,
                    h.resolution_key_fingerprint = $resolution_key_fingerprint
                RETURN h.hitl_event_id AS updated
            """, {
                "hitl_event_id": hitl_event_id,
                "status": "resolved" if decision != "timed_out" else "timed_out",
                "decision": decision,
                "resolved_by": resolved_by,
                "resolved_at": resolved_at,
                "rationale": rationale or "",
                "resolution_hash": resolution_hash,
                "node_hash": node_hash,
                "pending_duration_ms": pending_duration_ms,
                "resolution_signature": resolution_signature,
                "resolution_key_fingerprint": resolution_key_fingerprint,
            })

            record = result.single()
            if record:
                logger.info(
                    f"Ariadne: HITL resolution recorded {hitl_event_id[:8]}... "
                    f"[decision={decision}, by={resolved_by}]"
                )
            else:
                logger.warning(
                    f"Ariadne: HITL event {hitl_event_id[:8]}... not found "
                    f"or not in INVOKED status — resolution not recorded"
                )

    except Exception as e:
        logger.warning(f"Ariadne: Failed to write HITL resolution: {e}")


# ── Branch/Fork/Merge Writer (Phase 1) ──────────────────────────────────────


def write_branch_point_sync(driver, branch_point) -> None:
    """Write a BranchPointNode + BRANCH_ORIGIN edge from episode."""
    if not _ariadne_guard():
        return

    try:
        from ariadne.core.schema import ARIADNE_SCHEMA_VERSION

        with driver.session() as session:
            session.run("""
                MERGE (bp:AriadneBranchPoint {branch_point_id: $branch_point_id})
                ON CREATE SET
                  bp.episode_id             = $episode_id,
                  bp.branch_id              = $branch_id,
                  bp.branch_label           = $branch_label,
                  bp.parent_episode_id      = $parent_episode_id,
                  bp.source_segment_id      = $source_segment_id,
                  bp.branch_type            = $branch_type,
                  bp.branch_depth           = $branch_depth,
                  bp.declaration_type       = $declaration_type,
                  bp.trigger_context        = $trigger_context,
                  bp.initiated_by           = $initiated_by,
                  bp.spine_merkle_snapshot   = $spine_merkle_snapshot,
                  bp.content_hash           = $content_hash,
                  bp.parent_hash            = $parent_hash,
                  bp.timestamp_utc          = $timestamp_utc,
                  bp.schema_version         = $schema_version,
                  bp.pre_declaration_merkle_root = $pre_declaration_merkle_root,
                  bp.declared_retroactively_at   = $declared_retroactively_at,
                  bp.declared_by            = $declared_by
            """, {
                "branch_point_id": str(branch_point.branch_point_id),
                "episode_id": str(branch_point.episode_id),
                "branch_id": str(branch_point.branch_id),
                "branch_label": branch_point.branch_label,
                "parent_episode_id": str(branch_point.parent_episode_id),
                "source_segment_id": branch_point.source_segment_id,
                "branch_type": branch_point.branch_type.value,
                "branch_depth": branch_point.branch_depth,
                "declaration_type": branch_point.declaration_type.value,
                "trigger_context": branch_point.trigger_context.value,
                "initiated_by": branch_point.initiated_by,
                "spine_merkle_snapshot": branch_point.spine_merkle_snapshot,
                "content_hash": branch_point.content_hash,
                "parent_hash": branch_point.parent_hash,
                "timestamp_utc": branch_point.timestamp_utc.isoformat(),
                "schema_version": ARIADNE_SCHEMA_VERSION,
                "pre_declaration_merkle_root": branch_point.pre_declaration_merkle_root,
                "declared_retroactively_at": branch_point.declared_retroactively_at.isoformat() if branch_point.declared_retroactively_at else None,
                "declared_by": branch_point.declared_by,
            })

            # BRANCH_ORIGIN edge: Episode -> BranchPoint
            session.run("""
                MATCH (e:AriadneEpisode {episode_id: $episode_id})
                MATCH (bp:AriadneBranchPoint {branch_point_id: $branch_point_id})
                MERGE (e)-[:BRANCH_ORIGIN {
                    branch_id: $branch_id,
                    branch_type: $branch_type,
                    created_at: $timestamp_utc
                }]->(bp)
            """, {
                "episode_id": str(branch_point.parent_episode_id),
                "branch_point_id": str(branch_point.branch_point_id),
                "branch_id": str(branch_point.branch_id),
                "branch_type": branch_point.branch_type.value,
                "timestamp_utc": branch_point.timestamp_utc.isoformat(),
            })

        logger.info(
            f"Ariadne: BranchPoint {str(branch_point.branch_point_id)[:8]}... "
            f"[{branch_point.initiated_by} → {branch_point.branch_type.value}] "
            f"(episode={str(branch_point.episode_id)[:8]}...)"
        )

    except Exception as e:
        logger.warning(f"Ariadne: Failed to write BranchPoint: {e}")


def write_branch_terminus_sync(driver, terminus) -> None:
    """Write a BranchTerminusNode marking branch end."""
    if not _ariadne_guard():
        return

    try:
        with driver.session() as session:
            session.run("""
                MERGE (bt:AriadneBranchTerminus {terminus_id: $terminus_id})
                ON CREATE SET
                  bt.episode_id           = $episode_id,
                  bt.branch_id            = $branch_id,
                  bt.terminus_type         = $terminus_type,
                  bt.branch_point_hash     = $branch_point_hash,
                  bt.final_merkle_root     = $final_merkle_root,
                  bt.duration_ms           = $duration_ms,
                  bt.timestamp_utc         = $timestamp_utc,
                  bt.schema_version        = $schema_version,
                  bt.abandonment_reason    = $abandonment_reason,
                  bt.merge_target_id       = $merge_target_id
            """, {
                "terminus_id": str(terminus.terminus_id),
                "episode_id": str(terminus.episode_id),
                "branch_id": str(terminus.branch_id),
                "terminus_type": terminus.terminus_type.value,
                "branch_point_hash": terminus.branch_point_hash,
                "final_merkle_root": terminus.final_merkle_root,
                "duration_ms": terminus.duration_ms,
                "timestamp_utc": terminus.timestamp_utc.isoformat(),
                "schema_version": terminus.schema_version,
                "abandonment_reason": terminus.abandonment_reason,
                "merge_target_id": terminus.merge_target_id,
            })

            # Link terminus to branch point
            session.run("""
                MATCH (bp:AriadneBranchPoint {branch_id: $branch_id})
                MATCH (bt:AriadneBranchTerminus {terminus_id: $terminus_id})
                MERGE (bp)-[:BRANCH_TERMINUS {
                    terminus_type: $terminus_type,
                    created_at: $timestamp_utc
                }]->(bt)
            """, {
                "branch_id": str(terminus.branch_id),
                "terminus_id": str(terminus.terminus_id),
                "terminus_type": terminus.terminus_type.value,
                "timestamp_utc": terminus.timestamp_utc.isoformat(),
            })

        logger.info(
            f"Ariadne: BranchTerminus {str(terminus.terminus_id)[:8]}... "
            f"[{terminus.terminus_type.value}] "
            f"(branch={str(terminus.branch_id)[:8]}...)"
        )

    except Exception as e:
        logger.warning(f"Ariadne: Failed to write BranchTerminus: {e}")


def write_audit_record_sync(driver, audit) -> None:
    """Write an AuditRecord to the tamper-evident audit chain."""
    if not _ariadne_guard():
        return

    try:
        import json

        with driver.session() as session:
            session.run("""
                MERGE (ar:AriadneAuditRecord {audit_id: $audit_id})
                ON CREATE SET
                  ar.delta_sequence       = $delta_sequence,
                  ar.agent_id             = $agent_id,
                  ar.session_id           = $session_id,
                  ar.human_actor          = $human_actor,
                  ar.wall_clock_time      = $wall_clock_time,
                  ar.episode_time         = $episode_time,
                  ar.delta_type           = $delta_type,
                  ar.forward_delta        = $forward_delta,
                  ar.reverse_delta        = $reverse_delta,
                  ar.affected_nodes       = $affected_nodes,
                  ar.trigger_context      = $trigger_context,
                  ar.explicit_reason      = $explicit_reason,
                  ar.prior_audit_hash     = $prior_audit_hash,
                  ar.record_hash          = $record_hash,
                  ar.caught_by            = $caught_by,
                  ar.detection_window_open = $detection_window_open,
                  ar.episode_id           = $episode_id,
                  ar.schema_version       = $schema_version
            """, {
                "audit_id": str(audit.audit_id),
                "delta_sequence": audit.delta_sequence,
                "agent_id": audit.agent_id,
                "session_id": audit.session_id,
                "human_actor": audit.human_actor,
                "wall_clock_time": audit.wall_clock_time.isoformat(),
                "episode_time": audit.episode_time,
                "delta_type": audit.delta_type.value,
                "forward_delta": json.dumps(audit.forward_delta, default=str),
                "reverse_delta": json.dumps(audit.reverse_delta, default=str),
                "affected_nodes": audit.affected_nodes,
                "trigger_context": audit.trigger_context.value,
                "explicit_reason": audit.explicit_reason,
                "prior_audit_hash": audit.prior_audit_hash,
                "record_hash": audit.record_hash,
                "caught_by": audit.caught_by,
                "detection_window_open": audit.detection_window_open,
                "episode_id": audit.episode_id,
                "schema_version": audit.schema_version,
            })

            # Link to episode
            if audit.episode_id:
                session.run("""
                    MATCH (e:AriadneEpisode {episode_id: $episode_id})
                    MATCH (ar:AriadneAuditRecord {audit_id: $audit_id})
                    MERGE (e)-[:AUDIT_TRAIL {delta_sequence: $delta_sequence}]->(ar)
                """, {
                    "episode_id": audit.episode_id,
                    "audit_id": str(audit.audit_id),
                    "delta_sequence": audit.delta_sequence,
                })

        logger.info(
            f"Ariadne: AuditRecord #{audit.delta_sequence} "
            f"[{audit.delta_type.value}] "
            f"(episode={audit.episode_id[:8]}...)"
        )

    except Exception as e:
        logger.warning(f"Ariadne: Failed to write AuditRecord: {e}")


def write_intent_record_sync(driver, intent) -> None:
    """Write an IntentRecord for concurrent operation guard."""
    if not _ariadne_guard():
        return

    try:
        with driver.session() as session:
            session.run("""
                MERGE (ir:AriadneIntentRecord {intent_id: $intent_id})
                ON CREATE SET
                  ir.intent_type        = $intent_type,
                  ir.idempotency_key    = $idempotency_key,
                  ir.initiator_id       = $initiator_id,
                  ir.status             = $status,
                  ir.created_at         = $created_at,
                  ir.completed_at       = $completed_at,
                  ir.result_node_id     = $result_node_id
            """, {
                "intent_id": str(intent.intent_id),
                "intent_type": intent.intent_type.value,
                "idempotency_key": intent.idempotency_key,
                "initiator_id": intent.initiator_id,
                "status": intent.status.value,
                "created_at": intent.created_at.isoformat(),
                "completed_at": intent.completed_at.isoformat() if intent.completed_at else None,
                "result_node_id": intent.result_node_id,
            })

    except Exception as e:
        logger.warning(f"Ariadne: Failed to write IntentRecord: {e}")


def acquire_intent_sync(driver, idempotency_key: str, intent_type: str, initiator_id: str):
    """Acquire an intent record atomically. Returns existing if COMPLETE (idempotent).

    Returns: (IntentRecord dict, is_new: bool)
    """
    if not _ariadne_guard():
        return None, False

    try:
        from uuid import uuid4
        from datetime import datetime, timezone

        with driver.session() as session:
            # Check for existing
            result = session.run("""
                MATCH (ir:AriadneIntentRecord {idempotency_key: $key})
                RETURN ir {.*} AS intent
            """, {"key": idempotency_key})
            record = result.single()

            if record:
                intent = dict(record["intent"])
                if intent.get("status") == "COMPLETE":
                    return intent, False  # Idempotent — return existing
                if intent.get("status") == "PENDING":
                    return intent, False  # Already in progress

            # Create new intent
            intent_id = str(uuid4())
            now = datetime.now(timezone.utc).isoformat()
            session.run("""
                MERGE (ir:AriadneIntentRecord {idempotency_key: $key})
                ON CREATE SET
                  ir.intent_id      = $intent_id,
                  ir.intent_type    = $intent_type,
                  ir.initiator_id   = $initiator_id,
                  ir.status         = 'PENDING',
                  ir.created_at     = $created_at
            """, {
                "key": idempotency_key,
                "intent_id": intent_id,
                "intent_type": intent_type,
                "initiator_id": initiator_id,
                "created_at": now,
            })

            return {"intent_id": intent_id, "idempotency_key": idempotency_key, "status": "PENDING"}, True

    except Exception as e:
        logger.warning(f"Ariadne: Failed to acquire intent: {e}")
        return None, False


def complete_intent_sync(driver, idempotency_key: str, result_node_id: str) -> None:
    """Mark an intent record as COMPLETE with the result node ID."""
    if not _ariadne_guard():
        return

    try:
        from datetime import datetime, timezone

        with driver.session() as session:
            session.run("""
                MATCH (ir:AriadneIntentRecord {idempotency_key: $key})
                WHERE ir.status = 'PENDING'
                SET ir.status = 'COMPLETE',
                    ir.completed_at = $completed_at,
                    ir.result_node_id = $result_node_id
            """, {
                "key": idempotency_key,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "result_node_id": result_node_id,
            })

    except Exception as e:
        logger.warning(f"Ariadne: Failed to complete intent: {e}")
