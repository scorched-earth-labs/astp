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
Ariadne Neo4j write operations.
All writes are gated by ARIADNE_ENABLED feature flag.

Spec 5 of Phase 2 Ariadne Persistence Layer.

IMPORTANT: Neo4j session.run() signature is run(query, parameters=None, **kwargs).
All parameters are passed as an explicit dict (positional arg) to avoid collisions
with session.run()'s own 'parameters' argument. See bdi.py commit history for context.
"""

import logging
import os
from typing import List, Optional
from uuid import UUID

from astp.core.schema import (
    AmendmentLink,
    AriadneGovernanceError,
    AttachmentNode,
    CodicilNode,
    ConsultationNode,
    ConsultationParticipantNode,
    ExchangeEntry,
    DocumentNode,
    EpisodeNode,
    EpisodeClosureRecord,
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

logger = logging.getLogger("astp.adapters.neo4j")

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
    # Branch/Fork/Merge (Phase 2)
    "CREATE CONSTRAINT ariadne_fork_point_id IF NOT EXISTS FOR (fp:AriadneForkPoint) REQUIRE fp.fork_point_id IS UNIQUE",
    "CREATE CONSTRAINT ariadne_merge_point_id IF NOT EXISTS FOR (mp:AriadneMergePoint) REQUIRE mp.merge_point_id IS UNIQUE",
    # Phase 3 — Social/Internal Primitives
    "CREATE CONSTRAINT ariadne_aside_id IF NOT EXISTS FOR (a:AriadneAside) REQUIRE a.aside_id IS UNIQUE",
    "CREATE CONSTRAINT ariadne_aside_terminus_id IF NOT EXISTS FOR (at:AriadneAsideTerminus) REQUIRE at.aside_terminus_id IS UNIQUE",
    "CREATE CONSTRAINT ariadne_soliloquy_id IF NOT EXISTS FOR (sol:AriadneSoliloquy) REQUIRE sol.soliloquy_id IS UNIQUE",
    "CREATE CONSTRAINT ariadne_soliloquy_conclusion_id IF NOT EXISTS FOR (sc:AriadneSoliloquyConclusion) REQUIRE sc.conclusion_id IS UNIQUE",
    # Phase 4 — Coherence Fingerprint Registry
    "CREATE CONSTRAINT ariadne_fingerprint_id IF NOT EXISTS FOR (fp:AriadneCoherenceFingerprint) REQUIRE fp.fingerprint_id IS UNIQUE",
    # Phase D — Orphan detection (dedup: one marker per orphaned fork)
    "CREATE CONSTRAINT ariadne_fork_orphan_marker_fork_id IF NOT EXISTS FOR (m:AriadneForkOrphanMarker) REQUIRE m.fork_id IS UNIQUE",
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
    # Branch/Fork/Merge indexes (Phase 2)
    "CREATE INDEX ariadne_fork_point_fork_id IF NOT EXISTS FOR (fp:AriadneForkPoint) ON (fp.fork_id)",
    "CREATE INDEX ariadne_fork_point_origin IF NOT EXISTS FOR (fp:AriadneForkPoint) ON (fp.origin_episode_id)",
    "CREATE INDEX ariadne_merge_point_merge_id IF NOT EXISTS FOR (mp:AriadneMergePoint) ON (mp.merge_id)",
    "CREATE INDEX ariadne_merge_point_target IF NOT EXISTS FOR (mp:AriadneMergePoint) ON (mp.target_episode_id)",
    # Phase 3 indexes
    "CREATE INDEX ariadne_aside_episode IF NOT EXISTS FOR (a:AriadneAside) ON (a.parent_episode_id)",
    "CREATE INDEX ariadne_aside_status IF NOT EXISTS FOR (a:AriadneAside) ON (a.aside_status)",
    "CREATE INDEX ariadne_aside_target_agent IF NOT EXISTS FOR (a:AriadneAside) ON (a.target_agent_id)",
    "CREATE INDEX ariadne_soliloquy_episode IF NOT EXISTS FOR (sol:AriadneSoliloquy) ON (sol.parent_episode_id)",
    "CREATE INDEX ariadne_soliloquy_status IF NOT EXISTS FOR (sol:AriadneSoliloquy) ON (sol.soliloquy_status)",
    "CREATE INDEX ariadne_soliloquy_owner IF NOT EXISTS FOR (sol:AriadneSoliloquy) ON (sol.initiated_by_agent)",
    # Phase 4 indexes
    "CREATE INDEX ariadne_fingerprint_episode IF NOT EXISTS FOR (fp:AriadneCoherenceFingerprint) ON (fp.episode_id)",
    "CREATE INDEX ariadne_fingerprint_segment IF NOT EXISTS FOR (fp:AriadneCoherenceFingerprint) ON (fp.segment_id)",
    "CREATE INDEX ariadne_fingerprint_sequence IF NOT EXISTS FOR (fp:AriadneCoherenceFingerprint) ON (fp.sequence_index)",
    "CREATE INDEX ariadne_fingerprint_state IF NOT EXISTS FOR (fp:AriadneCoherenceFingerprint) ON (fp.detection_state)",
    # Phase D — Orphan detection (fork_id already indexed via its uniqueness constraint)
    "CREATE INDEX ariadne_fork_orphan_marker_origin IF NOT EXISTS FOR (m:AriadneForkOrphanMarker) ON (m.origin_episode_id)",
    "CREATE INDEX ariadne_fork_orphan_marker_class IF NOT EXISTS FOR (m:AriadneForkOrphanMarker) ON (m.orphan_class)",
    # Cross-Episode Linking (Amendment v2.0). Label is `AriadneEpisodeLink`
    # for consistency with the Ariadne* prefix convention; the amendment's
    # bare `EpisodeLink` notation is the protocol-level abstraction.
    "CREATE CONSTRAINT ariadne_episode_link_id IF NOT EXISTS FOR (l:AriadneEpisodeLink) REQUIRE l.link_id IS UNIQUE",
    "CREATE INDEX ariadne_episode_link_health IF NOT EXISTS FOR (l:AriadneEpisodeLink) ON (l.health_state)",
    "CREATE INDEX ariadne_episode_link_source IF NOT EXISTS FOR (l:AriadneEpisodeLink) ON (l.source_episode)",
    "CREATE INDEX ariadne_episode_link_target IF NOT EXISTS FOR (l:AriadneEpisodeLink) ON (l.target_episode)",
    # Episode Grouping (Amendment v2.0 §7-§8). Same labeling convention.
    "CREATE CONSTRAINT ariadne_membership_record_id IF NOT EXISTS FOR (m:AriadneMembershipRecord) REQUIRE m.record_id IS UNIQUE",
    "CREATE INDEX ariadne_membership_episode IF NOT EXISTS FOR (m:AriadneMembershipRecord) ON (m.episode_id)",
    "CREATE INDEX ariadne_membership_group IF NOT EXISTS FOR (m:AriadneMembershipRecord) ON (m.group_id)",
    "CREATE INDEX ariadne_membership_system IF NOT EXISTS FOR (m:AriadneMembershipRecord) ON (m.group_system)",
    "CREATE CONSTRAINT ariadne_conformance_declaration_id IF NOT EXISTS FOR (cd:AriadneConformanceDeclaration) REQUIRE cd.declaration_id IS UNIQUE",
    "CREATE INDEX ariadne_conformance_system IF NOT EXISTS FOR (cd:AriadneConformanceDeclaration) ON (cd.group_system)",
    "CREATE INDEX ariadne_conformance_group IF NOT EXISTS FOR (cd:AriadneConformanceDeclaration) ON (cd.group_id)",
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
    from astp.core.crystallization import enforce_crystallization_lock_guard
    enforce_crystallization_lock_guard(episode_status.value)  # Spec 7
    # Every field SegmentNode declares is persisted. Four used to be dropped
    # here — content_text, retention_tier, signal_versions_read and
    # pending_hitl_ref — so the adapter silently wrote a lossy node: the model
    # said the data existed, the graph did not have it, and nothing failed.
    #
    # None of them are decorative. content_text is the durable content readers
    # reconstruct an episode from; retention_tier separates PERSISTENT
    # conversation from EPHEMERAL evaluation records; signal_versions_read is
    # the SPEC S4.5 stale-read audit; pending_hitl_ref is the SPEC S4.6
    # advisory gate that marks a segment CONDITIONALLY_VALID. A consumer that
    # needed any of them had to bypass this function and write its own Cypher,
    # which is exactly what downstream did.
    params = {
        "segment_id": str(segment.segment_id),
        "episode_id": str(segment.episode_id),
        "segment_type": segment.segment_type.value,
        "sequence_index": segment.sequence_index,
        "content_hash": segment.content_hash,
        "content_ref": segment.content_ref,
        "content_text": segment.content_text,
        "authored_at": segment.authored_at.isoformat(),
        "author": segment.author,
        "retention_tier": segment.retention_tier.value,
        "signal_versions_read": list(segment.signal_versions_read or []),
        "pending_hitl_ref": segment.pending_hitl_ref,
    }
    async with driver.session() as session:
        await session.run("""
            MERGE (s:AriadneSegment {segment_id: $segment_id})
            ON CREATE SET
              s.episode_id           = $episode_id,
              s.segment_type         = $segment_type,
              s.sequence_index       = $sequence_index,
              s.content_hash         = $content_hash,
              s.content_ref          = $content_ref,
              s.content_text         = $content_text,
              s.authored_at          = $authored_at,
              s.author               = $author,
              s.retention_tier       = $retention_tier,
              s.signal_versions_read = $signal_versions_read,
              s.pending_hitl_ref     = $pending_hitl_ref
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
    from astp.core.crystallization import enforce_crystallization_lock_guard
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


#: Episode properties `update_episode_status` may set alongside the status.
#: An allowlist, not a passthrough: Cypher cannot parameterise a property NAME,
#: so the SET clause is built from these keys as literals. Accepting arbitrary
#: caller-supplied names here would be a Cypher injection.
_UPDATABLE_EPISODE_FIELDS = frozenset({
    "sealed_at",
    "archived_at",
    "spine_hash",
    "signal_manifest_hash",
    "episode_root_hash",
    "crystallization_status",
    "closing_initiated_at",
    "grace_period_expires_at",
})


async def update_episode_status(driver, episode_id, status, **fields) -> None:
    """Set an episode's lifecycle status, and optionally related fields.

    `AriadneAdapter.update_episode_status` was declared abstract and never
    implemented, so every lifecycle transition — close, seal, archive — was
    written as ad-hoc Cypher by whoever needed it.

    Unknown field names raise rather than being silently dropped: a transition
    that quietly fails to record `sealed_at` looks identical to one that
    recorded it.
    """
    if not _ariadne_guard():
        return

    unknown = sorted(set(fields) - _UPDATABLE_EPISODE_FIELDS)
    if unknown:
        raise AriadneGovernanceError(
            f"update_episode_status: unknown episode field(s) {unknown}; "
            f"allowed: {sorted(_UPDATABLE_EPISODE_FIELDS)}"
        )

    status_value = status.value if hasattr(status, "value") else str(status)
    params = {"episode_id": str(episode_id), "episode_status": status_value}
    assignments = ["e.episode_status = $episode_status"]
    for key, value in fields.items():
        params[key] = value
        assignments.append(f"e.{key} = ${key}")

    async with driver.session() as session:
        await session.run(
            "MATCH (e:AriadneEpisode {episode_id: $episode_id})\nSET " + ",\n    ".join(assignments),
            params,
        )


async def create_closure_record_node(driver, closure: EpisodeClosureRecord) -> None:
    """Persist the structured record generated when an episode is closed.

    Another abstract-only adapter method (`create_closure_record`) with no
    implementation, so :AriadneClosureRecord had no writer in the protocol —
    the same gap as codicils, and for the same reason it was hand-rolled
    downstream.

    The SEALS_EPISODE edge runs closure -> episode, matching the direction
    already in the live graph.
    """
    if not _ariadne_guard():
        return
    params = {
        "closure_id": str(closure.closure_id),
        "episode_id": str(closure.episode_id),
        "sealed_by": closure.sealed_by,
        "sealed_at": closure.sealed_at.isoformat(),
        "summary": closure.summary,
        "closure_notes": closure.closure_notes,
        "carried_forward_items": list(closure.carried_forward_items or []),
        "artifact_count": closure.artifact_count,
        "segment_count": closure.segment_count,
        "participant_count": closure.participant_count,
        "codicil_count": closure.codicil_count,
        "amendment_episode_id": (
            str(closure.amendment_episode_id) if closure.amendment_episode_id else None
        ),
    }
    async with driver.session() as session:
        await session.run("""
            MERGE (cl:AriadneClosureRecord {closure_id: $closure_id})
            ON CREATE SET
              cl.episode_id            = $episode_id,
              cl.sealed_by             = $sealed_by,
              cl.sealed_at             = $sealed_at,
              cl.summary               = $summary,
              cl.closure_notes         = $closure_notes,
              cl.carried_forward_items = $carried_forward_items,
              cl.artifact_count        = $artifact_count,
              cl.segment_count         = $segment_count,
              cl.participant_count     = $participant_count,
              cl.codicil_count         = $codicil_count,
              cl.amendment_episode_id  = $amendment_episode_id
        """, params)
        await session.run("""
            MATCH (e:AriadneEpisode {episode_id: $episode_id})
            MATCH (cl:AriadneClosureRecord {closure_id: $closure_id})
            MERGE (cl)-[:SEALS_EPISODE {sealed_at: $sealed_at}]->(e)
        """, {
            "episode_id": str(closure.episode_id),
            "closure_id": str(closure.closure_id),
            "sealed_at": closure.sealed_at.isoformat(),
        })


async def create_consultation_node(driver, consultation: ConsultationNode) -> None:
    """Persist a consultation — a cross-agent exchange within an Episode.

    Consultation is protocol surface: G-8 and G-9 have governed it since v1,
    and compute_consultation_node_hash / compute_exchange_chain_hash are
    protocol hash functions. v3.5.0 removed its WIL operations on the premise
    that the protocol does not define consultation; that premise contradicted
    the governance section and is corrected in 4.2.0.

    G-1 is not enforced: a consultation is a branch event, not a spine append
    (D2), so it does not extend the segment chain.
    """
    if not _ariadne_guard():
        return
    params = {
        "consultation_id": str(consultation.consultation_id),
        "episode_id": str(consultation.episode_id),
        "consultation_type": consultation.consultation_type.value,
        "initiating_agent": consultation.initiating_agent,
        "consulting_agent": consultation.consulting_agent,
        "initiated_at": consultation.initiated_at.isoformat(),
        "resolved_at": (
            consultation.resolved_at.isoformat() if consultation.resolved_at else None
        ),
        "initiating_context_hash": consultation.initiating_context_hash,
        "consultation_prompt": consultation.consultation_prompt,
        "consultation_prompt_hash": consultation.consultation_prompt_hash,
        "resolution_type": consultation.resolution_type,
        "resolution_hash": consultation.resolution_hash,
        "consultation_node_hash": consultation.consultation_node_hash,
        "schema_version": consultation.schema_version,
    }

    async with driver.session() as session:
        await session.run("""
            MERGE (c:AriadneConsultation {consultation_id: $consultation_id})
            ON CREATE SET
              c.episode_id               = $episode_id,
              c.consultation_type        = $consultation_type,
              c.initiating_agent         = $initiating_agent,
              c.consulting_agent         = $consulting_agent,
              c.initiated_at             = $initiated_at,
              c.resolved_at              = $resolved_at,
              c.initiating_context_hash  = $initiating_context_hash,
              c.consultation_prompt      = $consultation_prompt,
              c.consultation_prompt_hash = $consultation_prompt_hash,
              c.resolution_type          = $resolution_type,
              c.resolution_hash          = $resolution_hash,
              c.consultation_node_hash   = $consultation_node_hash,
              c.schema_version           = $schema_version
        """, params)
        # INITIATED: the consultation lives in the INITIATING agent's episode
        # (D2); the consulted agent records a participation node instead (D3).
        await session.run("""
            MATCH (e:AriadneEpisode {episode_id: $episode_id})
            MATCH (c:AriadneConsultation {consultation_id: $consultation_id})
            MERGE (e)-[:INITIATED {initiated_at: $initiated_at}]->(c)
        """, {
            "episode_id": str(consultation.episode_id),
            "consultation_id": str(consultation.consultation_id),
            "initiated_at": consultation.initiated_at.isoformat(),
        })


async def create_exchange_entry_node(driver, entry: ExchangeEntry) -> None:
    """Persist one turn in a consultation's hash-chained exchange.

    Each entry's previous_hash references the prior entry's content_hash
    ("GENESIS" for the first), which is what G-8 governs. The chain is why
    consultation is protocol surface at all: an ordered exchange whose
    integrity is verifiable is a protocol concern, whatever the interaction
    pattern layered on top is called.
    """
    if not _ariadne_guard():
        return
    params = {
        "entry_id": str(entry.entry_id),
        "consultation_id": str(entry.consultation_id),
        "sequence": entry.sequence,
        "timestamp": entry.timestamp.isoformat(),
        "speaker": entry.speaker,
        "role": entry.role.value,
        "content": entry.content,
        "content_hash": entry.content_hash,
        "previous_hash": entry.previous_hash,
        "round_number": entry.round_number,
    }
    async with driver.session() as session:
        await session.run("""
            MERGE (ex:AriadneExchangeEntry {entry_id: $entry_id})
            ON CREATE SET
              ex.consultation_id = $consultation_id,
              ex.sequence        = $sequence,
              ex.timestamp       = $timestamp,
              ex.speaker         = $speaker,
              ex.role            = $role,
              ex.content         = $content,
              ex.content_hash    = $content_hash,
              ex.previous_hash   = $previous_hash,
              ex.round_number    = $round_number
        """, params)
        await session.run("""
            MATCH (c:AriadneConsultation {consultation_id: $consultation_id})
            MATCH (ex:AriadneExchangeEntry {entry_id: $entry_id})
            MERGE (c)-[:CONTAINS_ENTRY {sequence: $sequence}]->(ex)
        """, {
            "consultation_id": str(entry.consultation_id),
            "entry_id": str(entry.entry_id),
            "sequence": entry.sequence,
        })


async def create_consultation_participant_node(
    driver, participant: ConsultationParticipantNode
) -> None:
    """Record participation on the CONSULTED agent's episode.

    D3: the consulted agent records that it participated, not the full
    exchange — the exchange belongs to the initiating agent's episode. Two
    records of one consultation from opposite sides, neither duplicating the
    other.
    """
    if not _ariadne_guard():
        return
    params = {
        "participant_id": str(participant.participant_id),
        "consultation_id": str(participant.consultation_id),
        "episode_id": str(participant.episode_id),
        "initiating_agent": participant.initiating_agent,
        "initiating_episode_id": str(participant.initiating_episode_id),
        "participated_at": participant.participated_at.isoformat(),
        "resolved_at": (
            participant.resolved_at.isoformat() if participant.resolved_at else None
        ),
        "consultation_type": participant.consultation_type.value,
        "schema_version": participant.schema_version,
    }
    async with driver.session() as session:
        await session.run("""
            MERGE (p:AriadneConsultationParticipant {participant_id: $participant_id})
            ON CREATE SET
              p.consultation_id       = $consultation_id,
              p.episode_id            = $episode_id,
              p.initiating_agent      = $initiating_agent,
              p.initiating_episode_id = $initiating_episode_id,
              p.participated_at       = $participated_at,
              p.resolved_at           = $resolved_at,
              p.consultation_type     = $consultation_type,
              p.schema_version        = $schema_version
        """, params)
        await session.run("""
            MATCH (e:AriadneEpisode {episode_id: $episode_id})
            MATCH (p:AriadneConsultationParticipant {participant_id: $participant_id})
            MERGE (e)-[:PARTICIPATED_IN {participated_at: $participated_at}]->(p)
        """, {
            "episode_id": str(participant.episode_id),
            "participant_id": str(participant.participant_id),
            "participated_at": participant.participated_at.isoformat(),
        })


async def create_amendment_link_node(driver, amendment: AmendmentLink) -> None:
    """Link a new Episode to a sealed source Episode.

    The last of the abstract adapter methods that was never implemented.
    `AriadneAdapter.create_amendment_link` was declared and left `...`, so
    consumers that needed to reopen a sealed episode wrote their own node and
    edges — the same gap as codicils, closure records and attachments.

    Writes the node and both edges: AMENDS to the source, PRODUCES to the new
    episode. Two edges rather than one because the link is not symmetric — a
    reader following provenance backwards wants the source, and one asking
    "what came of this episode" wants the amendment, and collapsing them would
    make one of those a scan.

    G-1 is NOT enforced. The source episode is sealed or archived by
    definition — that is the precondition for amending it, not an obstacle.
    Nothing about the sealed record changes: the amendment is a new episode
    beside it, which is the whole point of reopening rather than editing.
    """
    if not _ariadne_guard():
        return
    params = {
        "amendment_id": str(amendment.amendment_id),
        "source_episode_id": str(amendment.source_episode_id),
        "amendment_episode_id": str(amendment.amendment_episode_id),
        "source_root_hash": amendment.source_root_hash,
        "source_title": amendment.source_title,
        "source_closed_at": (
            amendment.source_closed_at.isoformat() if amendment.source_closed_at else None
        ),
        "source_participants": list(amendment.source_participants or []),
        "amendment_count": amendment.amendment_count,
        "created_at": amendment.created_at.isoformat(),
        "created_by": amendment.created_by,
    }
    async with driver.session() as session:
        await session.run("""
            MERGE (am:AriadneAmendment {amendment_id: $amendment_id})
            ON CREATE SET
              am.source_episode_id    = $source_episode_id,
              am.amendment_episode_id = $amendment_episode_id,
              am.source_root_hash     = $source_root_hash,
              am.source_title         = $source_title,
              am.source_closed_at     = $source_closed_at,
              am.source_participants  = $source_participants,
              am.amendment_count      = $amendment_count,
              am.created_at           = $created_at,
              am.created_by           = $created_by
        """, params)
        await session.run("""
            MATCH (am:AriadneAmendment {amendment_id: $amendment_id})
            MATCH (e:AriadneEpisode {episode_id: $source_episode_id})
            MERGE (am)-[:AMENDS]->(e)
        """, {
            "amendment_id": str(amendment.amendment_id),
            "source_episode_id": str(amendment.source_episode_id),
        })
        await session.run("""
            MATCH (am:AriadneAmendment {amendment_id: $amendment_id})
            MATCH (e:AriadneEpisode {episode_id: $amendment_episode_id})
            MERGE (am)-[:PRODUCES]->(e)
        """, {
            "amendment_id": str(amendment.amendment_id),
            "amendment_episode_id": str(amendment.amendment_episode_id),
        })


async def create_attachment_node(driver, attachment: AttachmentNode) -> None:
    """Persist an attachment — external content injected into an Episode (SPEC §4.7).

    G-1 is NOT enforced. Attaching is not a spine write: an AttachmentNode
    records that content was injected into an Episode's context, and does not
    extend the segment chain or alter the Merkle spine. Guarding it as though
    it were content would forbid attaching to a closed episode for no integrity
    reason, since nothing about the sealed record changes.
    """
    if not _ariadne_guard():
        return
    params = {
        "attachment_id": str(attachment.attachment_id),
        "episode_id": str(attachment.episode_id),
        "content_hash": attachment.content_hash,
        "media_type": attachment.media_type,
        "content_ref": attachment.content_ref,
        "attached_by": attachment.attached_by,
        "attached_at": attachment.attached_at.isoformat(),
        "schema_version": attachment.schema_version,
    }
    async with driver.session() as session:
        await session.run("""
            MERGE (a:AriadneAttachment {attachment_id: $attachment_id})
            ON CREATE SET
              a.episode_id     = $episode_id,
              a.content_hash   = $content_hash,
              a.media_type     = $media_type,
              a.content_ref    = $content_ref,
              a.attached_by    = $attached_by,
              a.attached_at    = $attached_at,
              a.schema_version = $schema_version
        """, params)
        await session.run("""
            MATCH (e:AriadneEpisode {episode_id: $episode_id})
            MATCH (a:AriadneAttachment {attachment_id: $attachment_id})
            MERGE (a)-[:ATTACHED_TO {attached_at: $attached_at}]->(e)
        """, {
            "episode_id": str(attachment.episode_id),
            "attachment_id": str(attachment.attachment_id),
            "attached_at": attachment.attached_at.isoformat(),
        })


async def create_codicil_node(driver, codicil: CodicilNode) -> None:
    """Persist a codicil — a bounded addendum to an already-closed episode.

    This had no Neo4j implementation: `AriadneAdapter.create_codicil` was
    declared abstract and never realised, so every consumer that needed a
    codicil wrote its own Cypher against :AriadneCodicil. That is why the
    operation was hand-rolled downstream rather than ledgered by the protocol.

    NOTE: G-1 is deliberately NOT enforced here. G-1 blocks writes to SEALING /
    SEALED / ARCHIVED episodes, and a codicil is the protocol's sanctioned
    exception — the whole point is a post-closure addendum that preserves the
    sealed record by being appended rather than integrated into it. Applying
    the guard would make the node type unwritable in the only state it exists
    for.
    """
    if not _ariadne_guard():
        return
    params = {
        "codicil_id": str(codicil.codicil_id),
        "episode_id": str(codicil.episode_id),
        "author": codicil.author,
        "content": codicil.content,
        "content_hash": codicil.content_hash,
        "created_at": codicil.created_at.isoformat(),
        "schema_version": codicil.schema_version,
    }
    async with driver.session() as session:
        await session.run("""
            MERGE (cod:AriadneCodicil {codicil_id: $codicil_id})
            ON CREATE SET
              cod.episode_id     = $episode_id,
              cod.author         = $author,
              cod.content        = $content,
              cod.content_hash   = $content_hash,
              cod.created_at     = $created_at,
              cod.schema_version = $schema_version
        """, params)
        # HAS_CODICIL edge: EpisodeNode -> CodicilNode
        await session.run("""
            MATCH (e:AriadneEpisode {episode_id: $episode_id})
            MATCH (cod:AriadneCodicil {codicil_id: $codicil_id})
            MERGE (e)-[:HAS_CODICIL {created_at: $created_at}]->(cod)
        """, {
            "episode_id": str(codicil.episode_id),
            "codicil_id": str(codicil.codicil_id),
            "created_at": codicil.created_at.isoformat(),
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


def write_attachment_node_sync(driver, attachment: AttachmentNode) -> None:
    """Sync variant of `create_attachment_node` (SPEC §4.7).

    Exists for the same reason `write_document_node_sync` does — callers that
    are not async and cannot become so without restructuring their caller in
    turn. Same node and edge as the async writer, so the two are
    indistinguishable in the graph.

    NOTE: this writes the node only. A caller performing an attachment owes an
    `ATTACHMENT_COMMIT` ledger entry under G-39, and this function cannot
    produce one — write-intent coordination is async by necessity. A sync
    caller must therefore either surface that its write is unledgered, or move
    to `execute_attachment_commit`. Silently attaching without an entry is the
    gap §12.4.2 forbids absorbing.
    """
    if not _ariadne_guard():
        return

    params = {
        "attachment_id": str(attachment.attachment_id),
        "episode_id": str(attachment.episode_id),
        "content_hash": attachment.content_hash,
        "media_type": attachment.media_type,
        "content_ref": attachment.content_ref,
        "attached_by": attachment.attached_by,
        "attached_at": attachment.attached_at.isoformat(),
        "schema_version": attachment.schema_version,
    }
    try:
        with driver.session() as session:
            session.run("""
                MERGE (a:AriadneAttachment {attachment_id: $attachment_id})
                ON CREATE SET
                  a.episode_id     = $episode_id,
                  a.content_hash   = $content_hash,
                  a.media_type     = $media_type,
                  a.content_ref    = $content_ref,
                  a.attached_by    = $attached_by,
                  a.attached_at    = $attached_at,
                  a.schema_version = $schema_version
            """, params)
            session.run("""
                MATCH (e:AriadneEpisode {episode_id: $episode_id})
                MATCH (a:AriadneAttachment {attachment_id: $attachment_id})
                MERGE (a)-[:ATTACHED_TO {attached_at: $attached_at}]->(e)
            """, {
                "episode_id": str(attachment.episode_id),
                "attachment_id": str(attachment.attachment_id),
                "attached_at": attachment.attached_at.isoformat(),
            })
    except Exception as e:
        logger.warning(f"Ariadne: attachment write failed (non-fatal): {e}")


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
        from astp.core.schema import ARIADNE_SCHEMA_VERSION

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
        from astp.core.schema import ARIADNE_SCHEMA_VERSION

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


# ── Branch/Fork/Merge Writer (Phase 2) ──────────────────────────────────────


def write_fork_point_sync(driver, fork_point) -> None:
    """Write a ForkPointNode + FORK_ORIGIN edge from origin episode.

    A single create_fork() call writes N ForkPointNodes sharing the same
    fork_id. Each ForkPoint anchors a new Episode.
    """
    if not _ariadne_guard():
        return

    try:
        from astp.core.schema import ARIADNE_SCHEMA_VERSION

        with driver.session() as session:
            session.run("""
                MERGE (fp:AriadneForkPoint {fork_point_id: $fork_point_id})
                ON CREATE SET
                  fp.fork_id             = $fork_id,
                  fp.episode_id          = $episode_id,
                  fp.origin_episode_id   = $origin_episode_id,
                  fp.origin_segment_id   = $origin_segment_id,
                  fp.fork_objective      = $fork_objective,
                  fp.fork_intent         = $fork_intent,
                  fp.carried_artifacts   = $carried_artifacts,
                  fp.initiator           = $initiator,
                  fp.participants        = $participants,
                  fp.sibling_count       = $sibling_count,
                  fp.sibling_index       = $sibling_index,
                  fp.content_hash        = $content_hash,
                  fp.parent_hash         = $parent_hash,
                  fp.timestamp_utc       = $timestamp_utc,
                  fp.schema_version      = $schema_version,
                  fp.fork_status         = 'ACTIVE'
            """, {
                "fork_point_id": str(fork_point.fork_point_id),
                "fork_id": str(fork_point.fork_id),
                "episode_id": str(fork_point.episode_id),
                "origin_episode_id": str(fork_point.origin_episode_id),
                "origin_segment_id": fork_point.origin_segment_id,
                "fork_objective": fork_point.fork_objective,
                "fork_intent": fork_point.fork_intent,
                "carried_artifacts": fork_point.carried_artifacts,
                "initiator": fork_point.initiator,
                "participants": fork_point.participants,
                "sibling_count": fork_point.sibling_count,
                "sibling_index": fork_point.sibling_index,
                "content_hash": fork_point.content_hash,
                "parent_hash": fork_point.parent_hash,
                "timestamp_utc": fork_point.timestamp_utc.isoformat(),
                "schema_version": ARIADNE_SCHEMA_VERSION,
            })

            # FORK_ORIGIN edge: origin Episode -> ForkPoint
            session.run("""
                MATCH (e:AriadneEpisode {episode_id: $origin_episode_id})
                MATCH (fp:AriadneForkPoint {fork_point_id: $fork_point_id})
                MERGE (e)-[:FORK_ORIGIN {
                    fork_id: $fork_id,
                    sibling_index: $sibling_index,
                    created_at: $timestamp_utc
                }]->(fp)
            """, {
                "origin_episode_id": str(fork_point.origin_episode_id),
                "fork_point_id": str(fork_point.fork_point_id),
                "fork_id": str(fork_point.fork_id),
                "sibling_index": fork_point.sibling_index,
                "timestamp_utc": fork_point.timestamp_utc.isoformat(),
            })

        logger.info(
            f"Ariadne: ForkPoint {str(fork_point.fork_point_id)[:8]}... "
            f"[{fork_point.sibling_index + 1}/{fork_point.sibling_count}] "
            f"(fork={str(fork_point.fork_id)[:8]}...)"
        )

    except Exception as e:
        logger.warning(f"Ariadne: Failed to write ForkPoint: {e}")


def write_departure_fork_episode_sync(driver, episode) -> None:
    """Write the new departure-fork AriadneEpisode node (ACTIVE) with its immutable
    fork provenance. Sync counterpart of create_episode_node, extended with the
    Phase-D fork_* provenance fields so episode + provenance land atomically inside
    create_departure_fork(). (Ariadne BFM Phase D.)"""
    if not _ariadne_guard():
        return
    try:
        with driver.session() as session:
            session.run("""
                MERGE (e:AriadneEpisode {episode_id: $episode_id})
                ON CREATE SET
                  e.schema_version              = $schema_version,
                  e.agent_id                    = $agent_id,
                  e.opened_at                   = $opened_at,
                  e.episode_status              = $episode_status,
                  e.participants                = $participants,
                  e.title                       = $title,
                  e.context_note                = $context_note,
                  e.episode_type                = $episode_type,
                  e.initiated_by                = $initiated_by,
                  e.episode_mode                = $episode_mode,
                  e.spine_hash                  = null,
                  e.signal_manifest_hash        = null,
                  e.episode_root_hash           = null,
                  e.sealed_at                   = null,
                  e.archived_at                 = null,
                  e.fork_origin_episode_id      = $fork_origin_episode_id,
                  e.fork_anchor_index           = $fork_anchor_index,
                  e.fork_id                     = $fork_id,
                  e.fork_created_at             = $fork_created_at,
                  e.fork_creation_trigger       = $fork_creation_trigger,
                  e.fork_trigger_confidence     = $fork_trigger_confidence,
                  e.fork_trigger_segment_id     = $fork_trigger_segment_id,
                  e.fork_origin_spine_tip_hash  = $fork_origin_spine_tip_hash,
                  e.fork_origin_active_branch_ids = $fork_origin_active_branch_ids,
                  e.fork_status                 = $fork_status
            """, {
                "episode_id": str(episode.episode_id),
                "schema_version": episode.schema_version,
                "agent_id": episode.agent_id,
                "opened_at": episode.opened_at.isoformat(),
                "episode_status": episode.episode_status.value,
                "participants": episode.participants,
                "title": episode.title,
                "context_note": episode.context_note,
                "episode_type": episode.episode_type,
                "initiated_by": episode.initiated_by,
                "episode_mode": episode.episode_mode,
                "fork_origin_episode_id": str(episode.fork_origin_episode_id) if episode.fork_origin_episode_id else None,
                "fork_anchor_index": episode.fork_anchor_index,
                "fork_id": str(episode.fork_id) if episode.fork_id else None,
                "fork_created_at": episode.fork_created_at.isoformat() if episode.fork_created_at else None,
                "fork_creation_trigger": episode.fork_creation_trigger,
                "fork_trigger_confidence": episode.fork_trigger_confidence,
                "fork_trigger_segment_id": episode.fork_trigger_segment_id,
                "fork_origin_spine_tip_hash": episode.fork_origin_spine_tip_hash,
                "fork_origin_active_branch_ids": episode.fork_origin_active_branch_ids,
                "fork_status": episode.fork_status,
            })
        logger.info(
            f"Ariadne: Departure-fork Episode {str(episode.episode_id)[:8]}... "
            f"created ACTIVE (origin={str(episode.fork_origin_episode_id)[:8] if episode.fork_origin_episode_id else '?'}...)"
        )
    except Exception as e:
        logger.warning(f"Ariadne: Failed to write departure-fork episode: {e}")


def write_departure_fork_point_sync(driver, fp) -> None:
    """Write a DepartureForkPointNode to the origin spine + FORK_ORIGIN edge
    (origin Episode -> departure fork point). Single node (no siblings)."""
    if not _ariadne_guard():
        return
    try:
        from astp.core.schema import ARIADNE_SCHEMA_VERSION
        with driver.session() as session:
            session.run("""
                MERGE (fp:AriadneDepartureForkPoint {fork_point_id: $fork_point_id})
                ON CREATE SET
                  fp.fork_id                     = $fork_id,
                  fp.fork_episode_id             = $fork_episode_id,
                  fp.origin_episode_id           = $origin_episode_id,
                  fp.origin_segment_id           = $origin_segment_id,
                  fp.fork_objective              = $fork_objective,
                  fp.fork_creation_trigger       = $fork_creation_trigger,
                  fp.fork_title_snapshot         = $fork_title_snapshot,
                  fp.spine_tip_hash_at_departure = $spine_tip_hash_at_departure,
                  fp.initiator                   = $initiator,
                  fp.content_hash                = $content_hash,
                  fp.parent_hash                 = $parent_hash,
                  fp.timestamp_utc               = $timestamp_utc,
                  fp.schema_version              = $schema_version
            """, {
                "fork_point_id": str(fp.fork_point_id),
                "fork_id": str(fp.fork_id),
                "fork_episode_id": str(fp.fork_episode_id),
                "origin_episode_id": str(fp.origin_episode_id),
                "origin_segment_id": fp.origin_segment_id,
                "fork_objective": fp.fork_objective,
                "fork_creation_trigger": fp.fork_creation_trigger.value,
                "fork_title_snapshot": fp.fork_title_snapshot,
                "spine_tip_hash_at_departure": fp.spine_tip_hash_at_departure,
                "initiator": fp.initiator,
                "content_hash": fp.content_hash,
                "parent_hash": fp.parent_hash,
                "timestamp_utc": fp.timestamp_utc.isoformat(),
                "schema_version": ARIADNE_SCHEMA_VERSION,
            })
            session.run("""
                MATCH (e:AriadneEpisode {episode_id: $origin_episode_id})
                MATCH (fp:AriadneDepartureForkPoint {fork_point_id: $fork_point_id})
                MERGE (e)-[:FORK_ORIGIN {
                    fork_id: $fork_id,
                    departure: true,
                    created_at: $timestamp_utc
                }]->(fp)
            """, {
                "origin_episode_id": str(fp.origin_episode_id),
                "fork_point_id": str(fp.fork_point_id),
                "fork_id": str(fp.fork_id),
                "timestamp_utc": fp.timestamp_utc.isoformat(),
            })
        logger.info(
            f"Ariadne: DepartureForkPoint {str(fp.fork_point_id)[:8]}... "
            f"[{fp.fork_creation_trigger.value}] (fork={str(fp.fork_id)[:8]}...)"
        )
    except Exception as e:
        logger.warning(f"Ariadne: Failed to write DepartureForkPoint: {e}")


def mark_departure_fork_status_sync(driver, fork_episode_id: str, status: str) -> None:
    """Update a departure-fork Episode's fork_status (ACTIVE -> COMPLETED | ABANDONED)."""
    if not _ariadne_guard():
        return
    try:
        from datetime import datetime, timezone
        with driver.session() as session:
            session.run("""
                MATCH (e:AriadneEpisode {episode_id: $episode_id})
                SET e.fork_status = $status, e.fork_status_updated_at = $ts
            """, {
                "episode_id": str(fork_episode_id),
                "status": status,
                "ts": datetime.now(timezone.utc).isoformat(),
            })
        logger.info(f"Ariadne: DepartureFork {str(fork_episode_id)[:8]}... -> {status}")
    except Exception as e:
        logger.warning(f"Ariadne: Failed to update departure-fork status: {e}")


def set_departure_fork_anchor_index_sync(driver, fork_episode_id: str, anchor_index: int) -> None:
    """Patch a departure-fork Episode's fork_anchor_index — the second phase of the
    two-phase field (STEP 6 of create_departure_fork). Set once, AFTER the
    DepartureForkPointNode is written to the origin spine: null -> the origin segment's
    sequence_index. The null->value transition is the "point was written" confirmation
    the orphan detector keys on (a non-null anchor with NO DepartureForkPointNode is the
    Class-B corruption indicator). Idempotent — re-patching to the same value is safe, so
    a patch-only retry after a STEP-5-done/STEP-6-missing partial failure is a clean fix.
    A write primitive; recovery orchestration (ignis-os) may call it directly."""
    if not _ariadne_guard():
        return
    try:
        with driver.session() as session:
            session.run("""
                MATCH (e:AriadneEpisode {episode_id: $episode_id})
                SET e.fork_anchor_index = $anchor_index
            """, {
                "episode_id": str(fork_episode_id),
                "anchor_index": anchor_index,
            })
        logger.info(
            f"Ariadne: DepartureFork {str(fork_episode_id)[:8]}... "
            f"fork_anchor_index -> {anchor_index}"
        )
    except Exception as e:
        logger.warning(f"Ariadne: Failed to patch fork_anchor_index: {e}")


def write_fork_return_node_sync(driver, frn) -> None:
    """Write a ForkReturnNode to the ORIGIN spine + FORK_RETURN edge (origin -> return
    node) + RETURNED_FROM edge (return node -> fork episode). Declarative return."""
    if not _ariadne_guard():
        return
    try:
        from astp.core.schema import ARIADNE_SCHEMA_VERSION
        with driver.session() as session:
            session.run("""
                MERGE (fr:AriadneForkReturn {fork_return_id: $fork_return_id})
                ON CREATE SET
                  fr.fork_id                    = $fork_id,
                  fr.fork_episode_id            = $fork_episode_id,
                  fr.origin_episode_id          = $origin_episode_id,
                  fr.return_type                = $return_type,
                  fr.synthesis_summary          = $synthesis_summary,
                  fr.fork_final_spine_tip_hash  = $fork_final_spine_tip_hash,
                  fr.returned_by                = $returned_by,
                  fr.content_hash               = $content_hash,
                  fr.parent_hash                = $parent_hash,
                  fr.timestamp_utc              = $timestamp_utc,
                  fr.schema_version             = $schema_version
            """, {
                "fork_return_id": str(frn.fork_return_id),
                "fork_id": str(frn.fork_id),
                "fork_episode_id": str(frn.fork_episode_id),
                "origin_episode_id": str(frn.origin_episode_id),
                "return_type": frn.return_type.value,
                "synthesis_summary": frn.synthesis_summary,
                "fork_final_spine_tip_hash": frn.fork_final_spine_tip_hash,
                "returned_by": frn.returned_by,
                "content_hash": frn.content_hash,
                "parent_hash": frn.parent_hash,
                "timestamp_utc": frn.timestamp_utc.isoformat(),
                "schema_version": ARIADNE_SCHEMA_VERSION,
            })
            session.run("""
                MATCH (e:AriadneEpisode {episode_id: $origin_episode_id})
                MATCH (fr:AriadneForkReturn {fork_return_id: $fork_return_id})
                MERGE (e)-[:FORK_RETURN {fork_id: $fork_id, created_at: $timestamp_utc}]->(fr)
            """, {
                "origin_episode_id": str(frn.origin_episode_id),
                "fork_return_id": str(frn.fork_return_id),
                "fork_id": str(frn.fork_id),
                "timestamp_utc": frn.timestamp_utc.isoformat(),
            })
            session.run("""
                MATCH (fr:AriadneForkReturn {fork_return_id: $fork_return_id})
                MATCH (fe:AriadneEpisode {episode_id: $fork_episode_id})
                MERGE (fr)-[:RETURNED_FROM {return_type: $return_type}]->(fe)
            """, {
                "fork_return_id": str(frn.fork_return_id),
                "fork_episode_id": str(frn.fork_episode_id),
                "return_type": frn.return_type.value,
            })
        logger.info(
            f"Ariadne: ForkReturn {str(frn.fork_return_id)[:8]}... "
            f"[{frn.return_type.value}] (fork={str(frn.fork_id)[:8]}...)"
        )
    except Exception as e:
        logger.warning(f"Ariadne: Failed to write ForkReturn: {e}")


# ── Phase D — Orphan-recovery write primitives (§19.3.7) ─────────────────────
# Protocol exposes the WRITES; detection + which-recovery-to-run is orchestrated by
# the consumer (ignis-os). All are append-only or set-once field mutations — no deletes.


def write_fork_orphan_marker_sync(driver, marker) -> None:
    """Write a ForkOrphanMarker as a NON-CHAINED diagnostic satellite off the ORIGIN episode
    (ORPHAN_MARKER edge). Self-hashed (content_hash) for tamper-evidence, but NOT a member of
    the origin spine's Merkle chain — writing it does not alter origin spine integrity. Dedup:
    MERGE on fork_id → ONE marker per orphaned fork (a re-detection sweep never piles up
    duplicates). Read-only after write; excluded from departure-registry queries."""
    if not _ariadne_guard():
        return
    try:
        from astp.core.schema import ARIADNE_SCHEMA_VERSION
        with driver.session() as session:
            session.run("""
                MERGE (m:AriadneForkOrphanMarker {fork_id: $fork_id})
                ON CREATE SET
                  m.fork_orphan_marker_id     = $fork_orphan_marker_id,
                  m.origin_episode_id         = $origin_episode_id,
                  m.orphan_class              = $orphan_class,
                  m.sequence_index            = $sequence_index,
                  m.detection_run_id          = $detection_run_id,
                  m.recovery_action           = $recovery_action,
                  m.requires_operator_review  = $requires_operator_review,
                  m.detected_at               = $detected_at,
                  m.content_hash              = $content_hash,
                  m.schema_version            = $schema_version
            """, {
                "fork_id": str(marker.fork_id),
                "fork_orphan_marker_id": str(marker.fork_orphan_marker_id),
                "origin_episode_id": str(marker.origin_episode_id),
                "orphan_class": marker.orphan_class.value,
                "sequence_index": marker.sequence_index,
                "detection_run_id": str(marker.detection_run_id),
                "recovery_action": marker.recovery_action,
                "requires_operator_review": marker.requires_operator_review,
                "detected_at": marker.detected_at.isoformat(),
                "content_hash": marker.content_hash,
                "schema_version": ARIADNE_SCHEMA_VERSION,
            })
            session.run("""
                MATCH (e:AriadneEpisode {episode_id: $origin_episode_id})
                MATCH (m:AriadneForkOrphanMarker {fork_id: $fork_id})
                MERGE (e)-[:ORPHAN_MARKER {orphan_class: $orphan_class}]->(m)
            """, {
                "origin_episode_id": str(marker.origin_episode_id),
                "fork_id": str(marker.fork_id),
                "orphan_class": marker.orphan_class.value,
            })
        logger.info(
            f"Ariadne: ForkOrphanMarker [{marker.orphan_class.value}] "
            f"(fork={str(marker.fork_id)[:8]}...) review={marker.requires_operator_review}"
        )
    except Exception as e:
        logger.warning(f"Ariadne: Failed to write ForkOrphanMarker: {e}")


def mark_departure_fork_point_orphaned_sync(driver, fork_point_id: str) -> None:
    """Class-A recovery: flag a dangling DepartureForkPointNode (its fork episode is missing)
    as orphaned. Append-only — the point is NEVER deleted; the flag + the ForkOrphanMarker are
    the resolution artifacts."""
    if not _ariadne_guard():
        return
    try:
        with driver.session() as session:
            session.run("""
                MATCH (fp:AriadneDepartureForkPoint {fork_point_id: $fork_point_id})
                SET fp.orphaned = true
            """, {"fork_point_id": str(fork_point_id)})
        logger.info(f"Ariadne: DepartureForkPoint {str(fork_point_id)[:8]}... flagged orphaned (Class A)")
    except Exception as e:
        logger.warning(f"Ariadne: Failed to flag departure fork point orphaned: {e}")


def write_retroactive_departure_fork_point_sync(driver, dfp, orphan_recovery_timestamp) -> None:
    """Class-B recovery (hash-consistent path): retroactively APPEND a DepartureForkPointNode
    that a failed write left missing. THE Spine-sensitive primitive — written self-contained
    for auditability. Discipline (mirrors RETROACTIVE branch declaration):
      * PURE APPEND — MERGE creates the missing point; no existing spine node or chain hash is
        read-modified or recomputed.
      * BACKDATED ANCHOR — `dfp.spine_tip_hash_at_departure` MUST be the fork episode's stored
        `fork_origin_spine_tip_hash`, so the cross-verifiable invariant (point tip == episode
        tip) holds by construction. The caller MUST have verified hash consistency vs the origin
        spine at fork_anchor_index BEFORE calling this — on mismatch, escalate, do NOT write.
      * FLAGS — the node is marked `retroactive=true` + `orphan_recovery_timestamp`; the
        FORK_ORIGIN edge is marked retroactive so the recovery is auditable.
    The point's content_hash is computed exactly as an on-time write, so a recovered point is
    byte-identical to one written on time (the retroactive flag is diagnostic metadata, outside
    the hash preimage)."""
    if not _ariadne_guard():
        return
    try:
        from astp.core.schema import ARIADNE_SCHEMA_VERSION
        ts = orphan_recovery_timestamp.isoformat() if hasattr(orphan_recovery_timestamp, "isoformat") else orphan_recovery_timestamp
        with driver.session() as session:
            session.run("""
                MERGE (fp:AriadneDepartureForkPoint {fork_point_id: $fork_point_id})
                ON CREATE SET
                  fp.fork_id                     = $fork_id,
                  fp.fork_episode_id             = $fork_episode_id,
                  fp.origin_episode_id           = $origin_episode_id,
                  fp.origin_segment_id           = $origin_segment_id,
                  fp.fork_objective              = $fork_objective,
                  fp.fork_creation_trigger       = $fork_creation_trigger,
                  fp.fork_title_snapshot         = $fork_title_snapshot,
                  fp.spine_tip_hash_at_departure = $spine_tip_hash_at_departure,
                  fp.initiator                   = $initiator,
                  fp.content_hash                = $content_hash,
                  fp.parent_hash                 = $parent_hash,
                  fp.timestamp_utc               = $timestamp_utc,
                  fp.schema_version              = $schema_version,
                  fp.retroactive                 = $retroactive,
                  fp.orphan_recovery_timestamp   = $orphan_recovery_timestamp
            """, {
                "fork_point_id": str(dfp.fork_point_id),
                "fork_id": str(dfp.fork_id),
                "fork_episode_id": str(dfp.fork_episode_id),
                "origin_episode_id": str(dfp.origin_episode_id),
                "origin_segment_id": dfp.origin_segment_id,
                "fork_objective": dfp.fork_objective,
                "fork_creation_trigger": dfp.fork_creation_trigger.value,
                "fork_title_snapshot": dfp.fork_title_snapshot,
                "spine_tip_hash_at_departure": dfp.spine_tip_hash_at_departure,
                "initiator": dfp.initiator,
                "content_hash": dfp.content_hash,
                "parent_hash": dfp.parent_hash,
                "timestamp_utc": dfp.timestamp_utc.isoformat(),
                "schema_version": ARIADNE_SCHEMA_VERSION,
                "retroactive": True,
                "orphan_recovery_timestamp": ts,
            })
            session.run("""
                MATCH (e:AriadneEpisode {episode_id: $origin_episode_id})
                MATCH (fp:AriadneDepartureForkPoint {fork_point_id: $fork_point_id})
                MERGE (e)-[:FORK_ORIGIN {
                    fork_id: $fork_id, departure: true, retroactive: true, created_at: $timestamp_utc
                }]->(fp)
            """, {
                "origin_episode_id": str(dfp.origin_episode_id),
                "fork_point_id": str(dfp.fork_point_id),
                "fork_id": str(dfp.fork_id),
                "timestamp_utc": dfp.timestamp_utc.isoformat(),
            })
        logger.info(
            f"Ariadne: RETROACTIVE DepartureForkPoint {str(dfp.fork_point_id)[:8]}... "
            f"written (Class-B recovery, fork={str(dfp.fork_id)[:8]}...)"
        )
    except Exception as e:
        logger.warning(f"Ariadne: Failed retroactive departure fork point write: {e}")


def mark_fork_episode_unanchored_sync(driver, fork_episode_id: str) -> None:
    """Class-B recovery (origin-unreachable path): a fork with no recoverable origin. Sets
    fork_orphaned=true + fork_orphan_class=UNANCHORED on the fork episode."""
    if not _ariadne_guard():
        return
    try:
        with driver.session() as session:
            session.run("""
                MATCH (e:AriadneEpisode {episode_id: $episode_id})
                SET e.fork_orphaned = true, e.fork_orphan_class = 'UNANCHORED'
            """, {"episode_id": str(fork_episode_id)})
        logger.info(f"Ariadne: Fork episode {str(fork_episode_id)[:8]}... marked UNANCHORED (Class B)")
    except Exception as e:
        logger.warning(f"Ariadne: Failed to mark fork episode unanchored: {e}")


def correct_fork_status_by_orphan_recovery_sync(driver, fork_episode_id: str) -> None:
    """Class-C recovery (ACTIVE sub-case): a ForkReturnNode exists but the fork episode was
    left non-COMPLETED. The ForkReturnNode is authoritative — set fork_status=COMPLETED +
    status_corrected_by_orphan_recovery=true + status_corrected_at. The ABANDONED sub-case is a
    data-integrity violation (operator review, NOT auto-corrected) and is intentionally not
    written by this primitive — the caller guards on status before calling."""
    if not _ariadne_guard():
        return
    try:
        from datetime import datetime, timezone
        with driver.session() as session:
            session.run("""
                MATCH (e:AriadneEpisode {episode_id: $episode_id})
                SET e.fork_status = 'COMPLETED',
                    e.status_corrected_by_orphan_recovery = true,
                    e.status_corrected_at = $ts
            """, {
                "episode_id": str(fork_episode_id),
                "ts": datetime.now(timezone.utc).isoformat(),
            })
        logger.info(f"Ariadne: Fork episode {str(fork_episode_id)[:8]}... status corrected -> COMPLETED (Class C)")
    except Exception as e:
        logger.warning(f"Ariadne: Failed to correct fork status by orphan recovery: {e}")


def mark_fork_point_status_sync(driver, fork_point_id: str, status: str) -> None:
    """Update a ForkPoint's fork_status — used by resolve_fork.

    status: 'ACTIVE' | 'PROMOTED' | 'DISCARDED'
    """
    if not _ariadne_guard():
        return

    try:
        with driver.session() as session:
            session.run("""
                MATCH (fp:AriadneForkPoint {fork_point_id: $fork_point_id})
                SET fp.fork_status = $status,
                    fp.resolved_at = $resolved_at
            """, {
                "fork_point_id": fork_point_id,
                "status": status,
                "resolved_at": __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat(),
            })
    except Exception as e:
        logger.warning(f"Ariadne: Failed to update fork point status: {e}")


def write_merge_point_sync(driver, merge_point) -> None:
    """Write a MergePointNode on the target spine with all three Merkle roots."""
    if not _ariadne_guard():
        return

    try:
        from astp.core.schema import ARIADNE_SCHEMA_VERSION

        with driver.session() as session:
            session.run("""
                MERGE (mp:AriadneMergePoint {merge_point_id: $merge_point_id})
                ON CREATE SET
                  mp.merge_id                 = $merge_id,
                  mp.source_episode_id        = $source_episode_id,
                  mp.source_branch_id         = $source_branch_id,
                  mp.target_episode_id        = $target_episode_id,
                  mp.merge_type               = $merge_type,
                  mp.source_merkle_root       = $source_merkle_root,
                  mp.target_merkle_root_pre   = $target_merkle_root_pre,
                  mp.target_merkle_root_post  = $target_merkle_root_post,
                  mp.common_ancestor_id       = $common_ancestor_id,
                  mp.conflict_segments        = $conflict_segments,
                  mp.resolution_artifacts     = $resolution_artifacts,
                  mp.merge_coherence_delta    = $merge_coherence_delta,
                  mp.merge_summary            = $merge_summary,
                  mp.initiator                = $initiator,
                  mp.content_hash             = $content_hash,
                  mp.parent_hash              = $parent_hash,
                  mp.timestamp_utc            = $timestamp_utc,
                  mp.schema_version           = $schema_version
            """, {
                "merge_point_id": str(merge_point.merge_point_id),
                "merge_id": str(merge_point.merge_id),
                "source_episode_id": merge_point.source_episode_id,
                "source_branch_id": merge_point.source_branch_id,
                "target_episode_id": merge_point.target_episode_id,
                "merge_type": merge_point.merge_type.value,
                "source_merkle_root": merge_point.source_merkle_root,
                "target_merkle_root_pre": merge_point.target_merkle_root_pre,
                "target_merkle_root_post": merge_point.target_merkle_root_post,
                "common_ancestor_id": merge_point.common_ancestor_id,
                "conflict_segments": merge_point.conflict_segments,
                "resolution_artifacts": merge_point.resolution_artifacts,
                "merge_coherence_delta": merge_point.merge_coherence_delta,
                "merge_summary": merge_point.merge_summary,
                "initiator": merge_point.initiator,
                "content_hash": merge_point.content_hash,
                "parent_hash": merge_point.parent_hash,
                "timestamp_utc": merge_point.timestamp_utc.isoformat(),
                "schema_version": ARIADNE_SCHEMA_VERSION,
            })

            # MERGE_INTO edge: source episode -> MergePoint
            session.run("""
                MATCH (src:AriadneEpisode {episode_id: $source_episode_id})
                MATCH (mp:AriadneMergePoint {merge_point_id: $merge_point_id})
                MERGE (src)-[:MERGE_INTO {
                    merge_id: $merge_id,
                    merged_at: $timestamp_utc
                }]->(mp)
            """, {
                "source_episode_id": merge_point.source_episode_id,
                "merge_point_id": str(merge_point.merge_point_id),
                "merge_id": str(merge_point.merge_id),
                "timestamp_utc": merge_point.timestamp_utc.isoformat(),
            })

            # MERGE_TARGET edge: MergePoint -> target episode
            session.run("""
                MATCH (mp:AriadneMergePoint {merge_point_id: $merge_point_id})
                MATCH (tgt:AriadneEpisode {episode_id: $target_episode_id})
                MERGE (mp)-[:MERGE_TARGET {
                    merge_id: $merge_id,
                    merged_at: $timestamp_utc
                }]->(tgt)
            """, {
                "target_episode_id": merge_point.target_episode_id,
                "merge_point_id": str(merge_point.merge_point_id),
                "merge_id": str(merge_point.merge_id),
                "timestamp_utc": merge_point.timestamp_utc.isoformat(),
            })

        logger.info(
            f"Ariadne: MergePoint {str(merge_point.merge_point_id)[:8]}... "
            f"[{merge_point.merge_type.value}] "
            f"(source={merge_point.source_episode_id[:8]}... → "
            f"target={merge_point.target_episode_id[:8]}...)"
        )

    except Exception as e:
        logger.warning(f"Ariadne: Failed to write MergePoint: {e}")


def write_branch_return_edge_sync(driver, branch_return) -> None:
    """Write BRANCH_RETURN edge from BranchTerminus(MERGED) to MergePoint."""
    if not _ariadne_guard():
        return

    try:
        with driver.session() as session:
            session.run("""
                MATCH (bt:AriadneBranchTerminus {terminus_id: $terminus_id})
                MATCH (mp:AriadneMergePoint {merge_point_id: $merge_point_id})
                MERGE (bt)-[:BRANCH_RETURN {
                    edge_id: $edge_id,
                    branch_id: $branch_id,
                    synthesis_summary: $synthesis_summary,
                    nodes_integrated: $nodes_integrated,
                    target_episode_id: $target_episode_id,
                    created_at: $timestamp_utc
                }]->(mp)
            """, {
                "edge_id": str(branch_return.edge_id),
                "terminus_id": branch_return.terminus_id,
                "merge_point_id": branch_return.merge_point_id,
                "branch_id": branch_return.branch_id,
                "synthesis_summary": branch_return.synthesis_summary,
                "nodes_integrated": branch_return.nodes_integrated,
                "target_episode_id": branch_return.target_episode_id,
                "timestamp_utc": branch_return.timestamp_utc.isoformat(),
            })

    except Exception as e:
        logger.warning(f"Ariadne: Failed to write BranchReturnEdge: {e}")


def find_common_ancestor_sync(
    driver,
    branch_id: str,
    target_episode_id: str,
) -> Optional[dict]:
    """Walk branch chain back to BranchPoint; confirm it anchors on target spine.

    Returns dict with common_ancestor_node_id (the BranchPoint's source segment)
    or None if no common ancestor found.
    """
    if not _ariadne_guard():
        return None

    try:
        with driver.session() as session:
            result = session.run("""
                MATCH (bp:AriadneBranchPoint {branch_id: $branch_id})
                MATCH (e:AriadneEpisode {episode_id: $target_episode_id})
                WHERE bp.parent_episode_id = e.episode_id
                RETURN bp.source_segment_id   AS ancestor_segment_id,
                       bp.branch_point_id     AS branch_point_id,
                       bp.parent_episode_id   AS parent_episode_id,
                       bp.spine_merkle_snapshot AS anchor_merkle
            """, {
                "branch_id": branch_id,
                "target_episode_id": target_episode_id,
            })
            record = result.single()
            if not record:
                return None
            return {
                "common_ancestor_node_id": record["ancestor_segment_id"],
                "branch_point_id": record["branch_point_id"],
                "parent_episode_id": record["parent_episode_id"],
                "anchor_merkle": record["anchor_merkle"],
            }

    except Exception as e:
        logger.warning(f"Ariadne: find_common_ancestor failed: {e}")
        return None


# ── Phase 3 — Aside / Soliloquy Writers ─────────────────────────────────────


def write_aside_sync(driver, aside) -> None:
    """Write an AsideSegmentNode + ASIDE_OPEN edge from parent episode."""
    if not _ariadne_guard():
        return

    try:
        from astp.core.schema import ARIADNE_SCHEMA_VERSION

        with driver.session() as session:
            session.run("""
                MERGE (a:AriadneAside {aside_id: $aside_id})
                ON CREATE SET
                  a.parent_episode_id   = $parent_episode_id,
                  a.parent_segment_id   = $parent_segment_id,
                  a.aside_label         = $aside_label,
                  a.initiated_by_human  = $initiated_by_human,
                  a.target_agent_id     = $target_agent_id,
                  a.return_obligation   = $return_obligation,
                  a.content_refs        = $content_refs,
                  a.content_hash        = $content_hash,
                  a.parent_hash         = $parent_hash,
                  a.timestamp_utc       = $timestamp_utc,
                  a.schema_version      = $schema_version,
                  a.aside_status        = 'OPEN'
            """, {
                "aside_id": str(aside.aside_id),
                "parent_episode_id": str(aside.parent_episode_id),
                "parent_segment_id": aside.parent_segment_id,
                "aside_label": aside.aside_label,
                "initiated_by_human": aside.initiated_by_human,
                "target_agent_id": aside.target_agent_id,
                "return_obligation": aside.return_obligation,
                "content_refs": aside.content_refs,
                "content_hash": aside.content_hash,
                "parent_hash": aside.parent_hash,
                "timestamp_utc": aside.timestamp_utc.isoformat(),
                "schema_version": ARIADNE_SCHEMA_VERSION,
            })
            # ASIDE_OPEN edge: parent episode -> Aside
            session.run("""
                MATCH (e:AriadneEpisode {episode_id: $parent_episode_id})
                MATCH (a:AriadneAside {aside_id: $aside_id})
                MERGE (e)-[:ASIDE_OPEN {
                    parent_segment_id: $parent_segment_id,
                    target_agent_id: $target_agent_id,
                    opened_at: $timestamp_utc
                }]->(a)
            """, {
                "parent_episode_id": str(aside.parent_episode_id),
                "aside_id": str(aside.aside_id),
                "parent_segment_id": aside.parent_segment_id,
                "target_agent_id": aside.target_agent_id,
                "timestamp_utc": aside.timestamp_utc.isoformat(),
            })

        logger.info(
            f"Ariadne: Aside {str(aside.aside_id)[:8]}... "
            f"[human={aside.initiated_by_human} → agent={aside.target_agent_id}] "
            f"(episode={str(aside.parent_episode_id)[:8]}...)"
        )

    except Exception as e:
        logger.warning(f"Ariadne: Failed to write Aside: {e}")


def write_aside_terminus_sync(driver, terminus) -> None:
    """Write an AsideTerminusNode closing an aside."""
    if not _ariadne_guard():
        return

    try:
        with driver.session() as session:
            session.run("""
                MERGE (at:AriadneAsideTerminus {aside_terminus_id: $aside_terminus_id})
                ON CREATE SET
                  at.aside_id                   = $aside_id,
                  at.parent_episode_id          = $parent_episode_id,
                  at.close_reason               = $close_reason,
                  at.final_content_hash         = $final_content_hash,
                  at.reference_scan_passed      = $reference_scan_passed,
                  at.external_references_found  = $external_references_found,
                  at.notification_targets       = $notification_targets,
                  at.duration_ms                = $duration_ms,
                  at.termination_status         = $termination_status,
                  at.timestamp_utc              = $timestamp_utc,
                  at.schema_version             = $schema_version
            """, {
                "aside_terminus_id": str(terminus.aside_terminus_id),
                "aside_id": str(terminus.aside_id),
                "parent_episode_id": str(terminus.parent_episode_id),
                "close_reason": terminus.close_reason,
                "final_content_hash": terminus.final_content_hash,
                "reference_scan_passed": terminus.reference_scan_passed,
                "external_references_found": terminus.external_references_found,
                "notification_targets": terminus.notification_targets,
                "duration_ms": terminus.duration_ms,
                "termination_status": terminus.termination_status.value,
                "timestamp_utc": terminus.timestamp_utc.isoformat(),
                "schema_version": terminus.schema_version,
            })
            # Link Aside -> AsideTerminus
            session.run("""
                MATCH (a:AriadneAside {aside_id: $aside_id})
                MATCH (at:AriadneAsideTerminus {aside_terminus_id: $aside_terminus_id})
                MERGE (a)-[:ASIDE_CLOSED {
                    closed_at: $timestamp_utc,
                    termination_status: $termination_status
                }]->(at)
                SET a.aside_status = 'CLOSED'
            """, {
                "aside_id": str(terminus.aside_id),
                "aside_terminus_id": str(terminus.aside_terminus_id),
                "timestamp_utc": terminus.timestamp_utc.isoformat(),
                "termination_status": terminus.termination_status.value,
            })

    except Exception as e:
        logger.warning(f"Ariadne: Failed to write AsideTerminus: {e}")


def load_aside_sync(driver, aside_id: str) -> Optional[dict]:
    """Load an aside node with its closure state."""
    if not _ariadne_guard():
        return None

    try:
        with driver.session() as session:
            result = session.run("""
                MATCH (a:AriadneAside {aside_id: $aside_id})
                OPTIONAL MATCH (a)-[:ASIDE_CLOSED]->(at:AriadneAsideTerminus)
                RETURN a {.*} AS aside, at IS NOT NULL AS is_closed
            """, {"aside_id": aside_id})
            record = result.single()
            if not record or not record["aside"]:
                return None
            return {
                "aside": dict(record["aside"]),
                "is_closed": record["is_closed"],
            }
    except Exception as e:
        logger.warning(f"Ariadne: load_aside failed: {e}")
        return None


def scan_aside_external_references_sync(
    driver, aside_id: str, content_refs: List[str],
) -> List[str]:
    """Find any segments OUTSIDE the aside that reference aside-internal segments.

    The spec requires this check on close: internal state must not leak
    into external constructs. Returns a list of offending external segment IDs.
    """
    if not _ariadne_guard():
        return []

    if not content_refs:
        return []

    try:
        with driver.session() as session:
            result = session.run("""
                MATCH (ext:AriadneSegment)-[:REFERENCES]->(internal:AriadneSegment)
                WHERE internal.segment_id IN $content_refs
                  AND NOT ext.segment_id IN $content_refs
                RETURN collect(DISTINCT ext.segment_id) AS offenders
            """, {"content_refs": content_refs})
            record = result.single()
            if not record:
                return []
            return list(record["offenders"] or [])
    except Exception as e:
        logger.warning(f"Ariadne: aside reference scan failed: {e}")
        return []


def write_soliloquy_sync(driver, soliloquy) -> None:
    """Write a SoliloquySegmentNode with visibility policy.

    Content hash is computed per the visibility policy (HASH_PLACEHOLDER
    preserves the Merkle chain without exposing content).
    """
    if not _ariadne_guard():
        return

    try:
        from astp.core.schema import ARIADNE_SCHEMA_VERSION
        import json

        with driver.session() as session:
            session.run("""
                MERGE (sol:AriadneSoliloquy {soliloquy_id: $soliloquy_id})
                ON CREATE SET
                  sol.parent_episode_id     = $parent_episode_id,
                  sol.parent_segment_id     = $parent_segment_id,
                  sol.soliloquy_purpose     = $soliloquy_purpose,
                  sol.initiated_by_agent    = $initiated_by_agent,
                  sol.visibility_policy     = $visibility_policy,
                  sol.deliberation_chain    = $deliberation_chain,
                  sol.content_hash          = $content_hash,
                  sol.parent_hash           = $parent_hash,
                  sol.timestamp_utc         = $timestamp_utc,
                  sol.schema_version        = $schema_version,
                  sol.soliloquy_status      = 'ACTIVE'
            """, {
                "soliloquy_id": str(soliloquy.soliloquy_id),
                "parent_episode_id": str(soliloquy.parent_episode_id),
                "parent_segment_id": soliloquy.parent_segment_id,
                "soliloquy_purpose": soliloquy.soliloquy_purpose,
                "initiated_by_agent": soliloquy.initiated_by_agent,
                "visibility_policy": json.dumps(
                    soliloquy.visibility_policy.model_dump(mode="json"),
                    default=str,
                ),
                "deliberation_chain": soliloquy.deliberation_chain,
                "content_hash": soliloquy.content_hash,
                "parent_hash": soliloquy.parent_hash,
                "timestamp_utc": soliloquy.timestamp_utc.isoformat(),
                "schema_version": ARIADNE_SCHEMA_VERSION,
            })
            # SOLILOQUY_OPEN edge: parent episode -> Soliloquy
            session.run("""
                MATCH (e:AriadneEpisode {episode_id: $parent_episode_id})
                MATCH (sol:AriadneSoliloquy {soliloquy_id: $soliloquy_id})
                MERGE (e)-[:SOLILOQUY_OPEN {
                    initiated_by_agent: $initiated_by_agent,
                    opened_at: $timestamp_utc
                }]->(sol)
            """, {
                "parent_episode_id": str(soliloquy.parent_episode_id),
                "soliloquy_id": str(soliloquy.soliloquy_id),
                "initiated_by_agent": soliloquy.initiated_by_agent,
                "timestamp_utc": soliloquy.timestamp_utc.isoformat(),
            })

        logger.info(
            f"Ariadne: Soliloquy {str(soliloquy.soliloquy_id)[:8]}... "
            f"[agent={soliloquy.initiated_by_agent}, "
            f"policy={soliloquy.visibility_policy.content_hash_policy.value}] "
            f"(episode={str(soliloquy.parent_episode_id)[:8]}...)"
        )

    except Exception as e:
        logger.warning(f"Ariadne: Failed to write Soliloquy: {e}")


def write_soliloquy_conclusion_sync(driver, conclusion) -> None:
    """Write a SoliloquyConclusionNode that merges back to the spine."""
    if not _ariadne_guard():
        return

    try:
        with driver.session() as session:
            session.run("""
                MERGE (sc:AriadneSoliloquyConclusion {conclusion_id: $conclusion_id})
                ON CREATE SET
                  sc.soliloquy_id             = $soliloquy_id,
                  sc.parent_episode_id        = $parent_episode_id,
                  sc.conclusion_summary       = $conclusion_summary,
                  sc.conclusion_content_hash  = $conclusion_content_hash,
                  sc.deliberation_chain_hash  = $deliberation_chain_hash,
                  sc.merged_into_segment_id   = $merged_into_segment_id,
                  sc.duration_ms              = $duration_ms,
                  sc.termination_status       = $termination_status,
                  sc.timestamp_utc            = $timestamp_utc,
                  sc.schema_version           = $schema_version
            """, {
                "conclusion_id": str(conclusion.conclusion_id),
                "soliloquy_id": str(conclusion.soliloquy_id),
                "parent_episode_id": str(conclusion.parent_episode_id),
                "conclusion_summary": conclusion.conclusion_summary,
                "conclusion_content_hash": conclusion.conclusion_content_hash,
                "deliberation_chain_hash": conclusion.deliberation_chain_hash,
                "merged_into_segment_id": conclusion.merged_into_segment_id,
                "duration_ms": conclusion.duration_ms,
                "termination_status": conclusion.termination_status.value,
                "timestamp_utc": conclusion.timestamp_utc.isoformat(),
                "schema_version": conclusion.schema_version,
            })
            # Link Soliloquy -> Conclusion
            session.run("""
                MATCH (sol:AriadneSoliloquy {soliloquy_id: $soliloquy_id})
                MATCH (sc:AriadneSoliloquyConclusion {conclusion_id: $conclusion_id})
                MERGE (sol)-[:SOLILOQUY_CONCLUDED {
                    concluded_at: $timestamp_utc,
                    termination_status: $termination_status
                }]->(sc)
                SET sol.soliloquy_status = 'CONCLUDED'
            """, {
                "soliloquy_id": str(conclusion.soliloquy_id),
                "conclusion_id": str(conclusion.conclusion_id),
                "timestamp_utc": conclusion.timestamp_utc.isoformat(),
                "termination_status": conclusion.termination_status.value,
            })

    except Exception as e:
        logger.warning(f"Ariadne: Failed to write SoliloquyConclusion: {e}")


def load_soliloquy_sync(driver, soliloquy_id: str) -> Optional[dict]:
    """Load a soliloquy with its conclusion state."""
    if not _ariadne_guard():
        return None

    try:
        with driver.session() as session:
            result = session.run("""
                MATCH (sol:AriadneSoliloquy {soliloquy_id: $soliloquy_id})
                OPTIONAL MATCH (sol)-[:SOLILOQUY_CONCLUDED]->(sc:AriadneSoliloquyConclusion)
                RETURN sol {.*} AS soliloquy, sc IS NOT NULL AS is_concluded
            """, {"soliloquy_id": soliloquy_id})
            record = result.single()
            if not record or not record["soliloquy"]:
                return None
            return {
                "soliloquy": dict(record["soliloquy"]),
                "is_concluded": record["is_concluded"],
            }
    except Exception as e:
        logger.warning(f"Ariadne: load_soliloquy failed: {e}")
        return None


# ── Phase 4 — Coherence Fingerprint Registry ────────────────────────────────


def write_coherence_fingerprint_sync(driver, fingerprint) -> None:
    """Persist a CoherenceFingerprint (write-time, per segment).

    topic_vector stored as a list of floats; the Neo4j driver handles
    the list primitive. For high-dimensional vectors (128+), consider
    an external vector store and store only a reference here.
    """
    if not _ariadne_guard():
        return

    try:
        from astp.core.schema import ARIADNE_SCHEMA_VERSION

        with driver.session() as session:
            session.run("""
                MERGE (fp:AriadneCoherenceFingerprint {fingerprint_id: $fingerprint_id})
                ON CREATE SET
                  fp.episode_id               = $episode_id,
                  fp.segment_id               = $segment_id,
                  fp.sequence_index           = $sequence_index,
                  fp.topic_vector             = $topic_vector,
                  fp.intent_class             = $intent_class,
                  fp.objective_hash           = $objective_hash,
                  fp.drift_from_spine         = $drift_from_spine,
                  fp.consecutive_drift_count  = $consecutive_drift_count,
                  fp.detection_state          = $detection_state,
                  fp.timestamp_utc            = $timestamp_utc,
                  fp.schema_version           = $schema_version
            """, {
                "fingerprint_id": str(fingerprint.fingerprint_id),
                "episode_id": fingerprint.episode_id,
                "segment_id": fingerprint.segment_id,
                "sequence_index": fingerprint.sequence_index,
                "topic_vector": fingerprint.topic_vector,
                "intent_class": fingerprint.intent_class.value,
                "objective_hash": fingerprint.objective_hash,
                "drift_from_spine": fingerprint.drift_from_spine,
                "consecutive_drift_count": fingerprint.consecutive_drift_count,
                "detection_state": fingerprint.detection_state.value,
                "timestamp_utc": fingerprint.timestamp_utc.isoformat(),
                "schema_version": ARIADNE_SCHEMA_VERSION,
            })
            # FINGERPRINTS edge: Episode -> Fingerprint
            session.run("""
                MATCH (e:AriadneEpisode {episode_id: $episode_id})
                MATCH (fp:AriadneCoherenceFingerprint {fingerprint_id: $fingerprint_id})
                MERGE (e)-[:FINGERPRINTS {sequence_index: $sequence_index}]->(fp)
            """, {
                "episode_id": fingerprint.episode_id,
                "fingerprint_id": str(fingerprint.fingerprint_id),
                "sequence_index": fingerprint.sequence_index,
            })

    except Exception as e:
        logger.warning(f"Ariadne: Failed to write CoherenceFingerprint: {e}")


def query_recent_fingerprints_sync(
    driver, episode_id: str, limit: int = 10,
) -> List[dict]:
    """Return the N most recent fingerprints for an episode, newest first."""
    if not _ariadne_guard():
        return []

    try:
        with driver.session() as session:
            result = session.run("""
                MATCH (fp:AriadneCoherenceFingerprint {episode_id: $episode_id})
                RETURN fp {.*} AS fingerprint
                ORDER BY fp.sequence_index DESC
                LIMIT $limit
            """, {"episode_id": episode_id, "limit": limit})
            return [dict(r["fingerprint"]) for r in result]
    except Exception as e:
        logger.warning(f"Ariadne: query_recent_fingerprints failed: {e}")
        return []


def get_last_fingerprint_sync(driver, episode_id: str) -> Optional[dict]:
    """Return the most recent fingerprint for an episode, or None."""
    rows = query_recent_fingerprints_sync(driver, episode_id, limit=1)
    return rows[0] if rows else None


def get_last_nominal_segment_sync(driver, episode_id: str) -> Optional[str]:
    """Return segment_id of the most recent fingerprint in NOMINAL state.

    Used to anchor a RETROACTIVE branch declaration at the last point
    before drift began.
    """
    if not _ariadne_guard():
        return None

    try:
        with driver.session() as session:
            result = session.run("""
                MATCH (fp:AriadneCoherenceFingerprint {episode_id: $episode_id})
                WHERE fp.detection_state = 'NOMINAL'
                RETURN fp.segment_id AS segment_id
                ORDER BY fp.sequence_index DESC
                LIMIT 1
            """, {"episode_id": episode_id})
            record = result.single()
            return record["segment_id"] if record else None
    except Exception as e:
        logger.warning(f"Ariadne: get_last_nominal_segment failed: {e}")
        return None


# ── Cross-Episode Linking (Amendment v2.0) ──────────────────────────────────


def write_episode_link_sync(driver, link) -> None:
    """Persist an EpisodeLink to Neo4j — Amendment v2.0 §2 + §11.1.2.

    Pre-write contract:
    1. Both source and target episodes must exist as `AriadneEpisode` nodes.
    2. The link must not violate mutual-exclusivity rules (§3) against
       existing links sharing the same (source_episode, target_episode) pair.
    3. `content_hash` is computed at write time if not already stamped.

    On success, creates:
    - `(:AriadneEpisodeLink {...})` node holding all link fields
    - `(:AriadneEpisode)-[:LINKED_TO {via: link_id}]->(:AriadneEpisode)` edge

    The relationship-property `via` carries the link_id for cheap lookup
    from edge to link node — agents traversing the episode graph can pick
    up the link metadata in one hop.

    Raises:
        LinkGovernanceError: if mutual-exclusivity rules are violated.
        ValueError: if source or target episode does not exist.
    """
    if not _ariadne_guard():
        return

    # Imports deferred to call time so the writer module stays
    # importable in environments where the core has not yet loaded
    # (e.g. schema-init bootstrap before episode types are wired).
    from astp.core.cross_episode import (
        EpisodeLink,
        compute_episode_link_content_hash,
        enforce_link_mutual_exclusivity,
        LinkType,
    )

    if not isinstance(link, EpisodeLink):
        raise TypeError(f"expected EpisodeLink, got {type(link).__name__}")

    src_id = str(link.source_episode)
    tgt_id = str(link.target_episode)

    with driver.session() as session:
        # 1. Both endpoints must exist.
        endpoints = session.run(
            """
            MATCH (s:AriadneEpisode {episode_id: $src})
            MATCH (t:AriadneEpisode {episode_id: $tgt})
            RETURN s.episode_id AS src_id, t.episode_id AS tgt_id
            """,
            {"src": src_id, "tgt": tgt_id},
        ).single()
        if endpoints is None:
            raise ValueError(
                f"Cannot create EpisodeLink: one or both endpoints not found "
                f"(source={src_id}, target={tgt_id})"
            )

        # 2. Mutual exclusivity check.
        existing = session.run(
            """
            MATCH (s:AriadneEpisode {episode_id: $src})-[r:LINKED_TO]->(t:AriadneEpisode {episode_id: $tgt})
            MATCH (l:AriadneEpisodeLink {link_id: r.via})
            RETURN l.link_type AS link_type
            """,
            {"src": src_id, "tgt": tgt_id},
        )
        existing_types = [LinkType(record["link_type"]) for record in existing]
        enforce_link_mutual_exclusivity(link.link_type, existing_types)

        # 3. Stamp hash if caller didn't.
        if not link.content_hash:
            link.content_hash = compute_episode_link_content_hash(link)

        # 4. Write node + edge in one transaction-equivalent block. Inline
        # signal serialization to a string list — Neo4j property graph
        # doesn't store nested maps cleanly. Full signal records live on
        # the audit trail; the node carries a compact representation.
        signals_compact = [
            f"{s.signal_type.value}:{s.signal_value:.4f}@w={s.signal_weight:.4f}"
            for s in link.inference_signals
        ]
        params = {
            "link_id": str(link.link_id),
            "source_episode": src_id,
            "target_episode": tgt_id,
            "created_at": link.created_at.isoformat(),
            "created_by": link.created_by,
            "link_type": link.link_type.value,
            "link_strength": link.link_strength,
            "is_inferred": link.is_inferred,
            "inference_signals": signals_compact,
            "inference_threshold": link.inference_threshold,
            "retroactive": link.retroactive,
            "health_state": link.health_state.value,
            "health_checked_at": link.health_checked_at.isoformat(),
            "source_version": link.source_version,
            "target_version": link.target_version,
            "quarantine_reason": link.quarantine_reason,
            "quarantined_at": link.quarantined_at.isoformat() if link.quarantined_at else None,
            "quarantine_resolved_at": (
                link.quarantine_resolved_at.isoformat() if link.quarantine_resolved_at else None
            ),
            "quarantine_resolution": (
                link.quarantine_resolution.value if link.quarantine_resolution else None
            ),
            "content_hash": link.content_hash,
        }
        session.run(
            """
            CREATE (l:AriadneEpisodeLink {
                link_id:                $link_id,
                source_episode:         $source_episode,
                target_episode:         $target_episode,
                created_at:             $created_at,
                created_by:             $created_by,
                link_type:              $link_type,
                link_strength:          $link_strength,
                is_inferred:            $is_inferred,
                inference_signals:      $inference_signals,
                inference_threshold:    $inference_threshold,
                retroactive:            $retroactive,
                health_state:           $health_state,
                health_checked_at:      $health_checked_at,
                source_version:         $source_version,
                target_version:         $target_version,
                quarantine_reason:      $quarantine_reason,
                quarantined_at:         $quarantined_at,
                quarantine_resolved_at: $quarantine_resolved_at,
                quarantine_resolution:  $quarantine_resolution,
                content_hash:           $content_hash
            })
            """,
            params,
        )
        session.run(
            """
            MATCH (s:AriadneEpisode {episode_id: $src})
            MATCH (t:AriadneEpisode {episode_id: $tgt})
            MERGE (s)-[r:LINKED_TO {via: $link_id}]->(t)
            ON CREATE SET r.created_at = $created_at, r.link_type = $link_type
            """,
            {
                "src": src_id,
                "tgt": tgt_id,
                "link_id": str(link.link_id),
                "created_at": link.created_at.isoformat(),
                "link_type": link.link_type.value,
            },
        )

    logger.info(
        f"Ariadne: EpisodeLink {str(link.link_id)[:8]}... "
        f"{link.link_type.value} from {src_id[:8]} → {tgt_id[:8]} "
        f"(strength={link.link_strength:.2f}, "
        f"{'inferred' if link.is_inferred else 'human-asserted'})"
    )


# ── Episode Grouping (Amendment v2.0 §7-§8) ────────────────────────────────


def write_membership_record_sync(driver, record) -> None:
    """Persist a MembershipRecord to Neo4j — Amendment v2.0 §7 + §11.1.2.

    Pre-write contract:
    1. The target Episode must exist (no orphan memberships).
    2. content_hash is stamped at write time if not already set.
    3. If supersedes_record_id is populated, the prior record must exist
       AND must not already be superseded — chain integrity.

    On success, creates:
    - `(:AriadneMembershipRecord {...})` node holding all immutable fields
    - `(:AriadneEpisode)-[:MEMBER_OF {via: record_id}]->(:AriadneEpisodeGroup)` edge

    The :AriadneEpisodeGroup node is stub-merged on first reference (same
    pattern as :Artifact and :ExternalSessionRef in the lineage writer).
    The grouping itself may live outside Ariadne's structural layer — see
    amendment §3 (Part II) on the boundary.

    If supersedes_record_id is set:
    - Creates `(new)-[:SUPERSEDES]->(prior)` edge
    - Sets prior.superseded_by_record_id (forward pointer — excluded from
      prior's content_hash per §10 forward-pointer-exclusion rule)

    Raises:
        ValueError: target episode not found, or prior record missing /
            already superseded.
    """
    if not _ariadne_guard():
        return

    from astp.core.grouping import (
        MembershipRecord,
        compute_membership_record_content_hash,
    )

    if not isinstance(record, MembershipRecord):
        raise TypeError(f"expected MembershipRecord, got {type(record).__name__}")

    episode_id = str(record.episode_id)

    with driver.session() as session:
        # 1. Episode must exist.
        ep = session.run(
            "MATCH (e:AriadneEpisode {episode_id: $id}) RETURN e.episode_id AS id",
            {"id": episode_id},
        ).single()
        if ep is None:
            raise ValueError(
                f"Cannot create MembershipRecord: episode {episode_id} not found"
            )

        # 2. Stamp hash if not already set.
        if not record.content_hash:
            record.content_hash = compute_membership_record_content_hash(record)

        # 3. Succession integrity check.
        if record.supersedes_record_id is not None:
            prior_id = str(record.supersedes_record_id)
            prior = session.run(
                """
                MATCH (m:AriadneMembershipRecord {record_id: $rid})
                RETURN m.record_id AS rid,
                       m.superseded_by_record_id AS sup_by,
                       m.episode_id AS episode_id,
                       m.group_id AS group_id,
                       m.group_system AS group_system
                """,
                {"rid": prior_id},
            ).single()
            if prior is None:
                raise ValueError(
                    f"Cannot create MembershipRecord: prior record {prior_id} not found"
                )
            if prior["sup_by"]:
                raise ValueError(
                    f"Cannot supersede {prior_id}: already superseded by {prior['sup_by']}"
                )
            # Chain integrity: new must reference the same episode + group.
            if prior["episode_id"] != episode_id:
                raise ValueError(
                    "Succession chain mismatch: new record's episode does not match prior's episode"
                )
            if prior["group_id"] != record.group_id or prior["group_system"] != record.group_system:
                raise ValueError(
                    "Succession chain mismatch: new record's (group_id, group_system) "
                    "does not match prior's"
                )

        # 4. Write membership-record node.
        params = {
            "record_id": str(record.record_id),
            "episode_id": episode_id,
            "group_id": record.group_id,
            "group_system": record.group_system,
            "asserted_at": record.asserted_at.isoformat(),
            "asserted_by": record.asserted_by,
            "membership_role": record.membership_role.value,
            "supersedes_record_id": (
                str(record.supersedes_record_id) if record.supersedes_record_id else None
            ),
            "succession_reason": record.succession_reason,
            # Forward pointer — set later by next succession; null at create.
            "superseded_by_record_id": None,
            "content_hash": record.content_hash,
        }
        session.run(
            """
            CREATE (m:AriadneMembershipRecord {
                record_id:               $record_id,
                episode_id:              $episode_id,
                group_id:                $group_id,
                group_system:            $group_system,
                asserted_at:             $asserted_at,
                asserted_by:             $asserted_by,
                membership_role:         $membership_role,
                supersedes_record_id:    $supersedes_record_id,
                succession_reason:       $succession_reason,
                superseded_by_record_id: $superseded_by_record_id,
                content_hash:            $content_hash
            })
            """,
            params,
        )

        # 5. Episode → Group edge. Stub-merge the group node (group may live
        # outside Ariadne; we keep a graph anchor).
        session.run(
            """
            MATCH (e:AriadneEpisode {episode_id: $ep_id})
            MERGE (g:AriadneEpisodeGroup {group_id: $group_id, group_system: $group_system})
            MERGE (e)-[r:MEMBER_OF {via: $record_id}]->(g)
              ON CREATE SET r.asserted_at = $asserted_at, r.membership_role = $membership_role
            """,
            {
                "ep_id": episode_id,
                "group_id": record.group_id,
                "group_system": record.group_system,
                "record_id": str(record.record_id),
                "asserted_at": record.asserted_at.isoformat(),
                "membership_role": record.membership_role.value,
            },
        )

        # 6. Succession edge + forward-pointer update on prior.
        if record.supersedes_record_id is not None:
            prior_id = str(record.supersedes_record_id)
            session.run(
                """
                MATCH (new:AriadneMembershipRecord {record_id: $new_id})
                MATCH (prior:AriadneMembershipRecord {record_id: $prior_id})
                MERGE (new)-[:SUPERSEDES]->(prior)
                SET prior.superseded_by_record_id = $new_id
                """,
                {"new_id": str(record.record_id), "prior_id": prior_id},
            )

    logger.info(
        f"Ariadne: MembershipRecord {str(record.record_id)[:8]}... "
        f"episode {episode_id[:8]} ∈ {record.group_system}:{record.group_id} "
        f"role={record.membership_role.value}"
        + (
            f" supersedes {str(record.supersedes_record_id)[:8]}..."
            if record.supersedes_record_id else ""
        )
    )


def write_conformance_declaration_sync(driver, declaration) -> None:
    """Persist a ConformanceDeclaration — Amendment v2.0 §8 + §11.1.2.

    Pre-write contract:
    1. SemVer format validation on declaration_version.
    2. declaration_hash stamped at write time if not already set.
    3. (Succession is a separate operation — this writer creates a single
       declaration. To register a version bump, use the operation layer.)

    On success, creates a `:AriadneConformanceDeclaration {...}` node. No
    edge is created here — the declaration registers a (group_system,
    group_id, version) and is referenced by MembershipRecords implicitly
    via shared (group_id, group_system).
    """
    if not _ariadne_guard():
        return

    from astp.core.grouping import (
        ConformanceDeclaration,
        compute_conformance_declaration_hash,
        enforce_semver_format,
    )

    if not isinstance(declaration, ConformanceDeclaration):
        raise TypeError(
            f"expected ConformanceDeclaration, got {type(declaration).__name__}"
        )

    # SemVer format validation.
    enforce_semver_format(declaration.declaration_version)

    if not declaration.declaration_hash:
        declaration.declaration_hash = compute_conformance_declaration_hash(declaration)

    # Serialize capabilities to a string list — same approach as
    # AriadneEpisodeLink.inference_signals. Full structured capabilities
    # are reconstructable from the audit chain; the Neo4j property is a
    # compact representation for index-friendly storage.
    capabilities_compact = [
        c.capability_id if c.description is None else f"{c.capability_id}:{c.description}"
        for c in declaration.capabilities
    ]

    params = {
        "declaration_id": str(declaration.declaration_id),
        "group_id": declaration.group_id,
        "group_system": declaration.group_system,
        "declared_at": declaration.declared_at.isoformat(),
        "declared_by": declaration.declared_by,
        "declaration_version": declaration.declaration_version,
        "capabilities": capabilities_compact,
        "superseded_by": str(declaration.superseded_by) if declaration.superseded_by else None,
        "declaration_hash": declaration.declaration_hash,
    }

    with driver.session() as session:
        session.run(
            """
            CREATE (cd:AriadneConformanceDeclaration {
                declaration_id:      $declaration_id,
                group_id:            $group_id,
                group_system:        $group_system,
                declared_at:         $declared_at,
                declared_by:         $declared_by,
                declaration_version: $declaration_version,
                capabilities:        $capabilities,
                superseded_by:       $superseded_by,
                declaration_hash:    $declaration_hash
            })
            """,
            params,
        )

    logger.info(
        f"Ariadne: ConformanceDeclaration {str(declaration.declaration_id)[:8]}... "
        f"for {declaration.group_system}:{declaration.group_id} "
        f"v{declaration.declaration_version} "
        f"({len(declaration.capabilities)} capabilities)"
    )


def supersede_conformance_declaration_sync(
    driver,
    old_declaration_id: str,
    new_declaration_id: str,
) -> None:
    """Wire a SUPERSEDED_BY edge from old to new and set the forward
    pointer on the old declaration. Used when a version bump registers
    a successor declaration.

    The forward pointer is excluded from the old declaration's
    declaration_hash per §10, so this mutation does NOT invalidate the
    integrity of the prior declaration.
    """
    if not _ariadne_guard():
        return

    with driver.session() as session:
        result = session.run(
            """
            MATCH (old:AriadneConformanceDeclaration {declaration_id: $old_id})
            MATCH (new:AriadneConformanceDeclaration {declaration_id: $new_id})
            MERGE (old)-[:SUPERSEDED_BY]->(new)
            SET old.superseded_by = $new_id
            RETURN old.declaration_id AS rid
            """,
            {"old_id": old_declaration_id, "new_id": new_declaration_id},
        ).single()
        if result is None:
            raise ValueError(
                f"Cannot link supersession: one or both declarations not found "
                f"(old={old_declaration_id}, new={new_declaration_id})"
            )

    logger.info(
        f"Ariadne: ConformanceDeclaration {old_declaration_id[:8]} "
        f"→ superseded by {new_declaration_id[:8]}"
    )
