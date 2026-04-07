"""
Ariadne Episode/Segment Schema — Canonical schema definition module.

All other Ariadne modules import from here. Defines:
- Neo4j node type enums and Pydantic models
- SHA3-256 hash utilities with Merkle domain separation
- Governance rule enforcement (G-1, G-5, G-7, taxonomy)

Spec 5 of Phase 2 Ariadne Persistence Layer.
Source: CLO-CONSOLIDATED-1.1, Phase 1 Architecture Synthesis.
"""

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────────────────

class EpisodeStatus(str, Enum):
    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    CLOSING = "CLOSING"                          # Closure initiated; final contributions permitted
    CLOSING_PENDING_SEAL = "CLOSING_PENDING_SEAL"  # All contributions in; grace period active
    CLOSED = "CLOSED"                            # Merkle root sealed; episode immutable
    CRYSTALLIZATION_PENDING = "CRYSTALLIZATION_PENDING"
    CRYSTALLIZED = "CRYSTALLIZED"
    SEALING = "SEALING"
    SEALED = "SEALED"
    ARCHIVED = "ARCHIVED"


class CrystallizationStatus(str, Enum):
    PROVISIONAL = "provisional"
    CRYSTALLIZED = "crystallized"
    CRYSTALLIZED_WITH_EXCLUSIONS = "crystallized_with_exclusions"


class SegmentType(str, Enum):
    CONVERSATION = "CONVERSATION"
    REASONING = "REASONING"
    ARTIFACT = "ARTIFACT"
    ANNOTATION = "ANNOTATION"
    CONSULTATION = "CONSULTATION"      # Inter-agent consultation exchange
    COLLABORATION = "COLLABORATION"    # Multi-round collaboration session


class SignalType(str, Enum):
    """Retention policy classification."""
    EPHEMERAL = "EPHEMERAL"
    PERSISTENT = "PERSISTENT"
    STRUCTURAL = "STRUCTURAL"


class SignalClass(str, Enum):
    """Causal role classification."""
    causal = "causal"
    contextual = "contextual"
    observational = "observational"
    ephemeral = "ephemeral"


class SignalStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    COMMITTED = "COMMITTED"
    ATTESTED = "ATTESTED"
    EXCLUDED = "EXCLUDED"


class SignalPlacement(str, Enum):
    SPINE = "SPINE"
    BRANCH_LEAF = "BRANCH_LEAF"
    EXCLUDED_MANIFEST = "EXCLUDED_MANIFEST"


class SealStatus(str, Enum):
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"


class ExclusionReason(str, Enum):
    EPHEMERAL_BY_TYPE = "EPHEMERAL_BY_TYPE"
    FAILED_VALIDATION = "FAILED_VALIDATION"
    DUPLICATE = "DUPLICATE"
    POLICY_EXCLUDED = "POLICY_EXCLUDED"
    PERSISTENCE_UNCONFIRMED = "PERSISTENCE_UNCONFIRMED"
    OBSERVATIONAL_POLICY = "OBSERVATIONAL_POLICY"
    VOLUME_LIMIT_EXCEEDED = "VOLUME_LIMIT_EXCEEDED"


class ReferenceType(str, Enum):
    CITES = "CITES"
    CONTINUES = "CONTINUES"
    SUPERSEDES = "SUPERSEDES"


class ConsultationType(str, Enum):
    """Behavioral classification of the consultation."""
    ADVISORY = "advisory"          # One-shot question, answer informs but doesn't delegate
    DELEGATED = "delegated"        # Work handed off; branch doesn't rejoin until delegate completes
    COLLABORATIVE = "collaborative" # Iterative multi-round; output emerges from back-and-forth
    ESCALATION = "escalation"      # Consultation initiated due to uncertainty or authority gap


class ExchangeRole(str, Enum):
    INITIATOR = "initiator"        # The agent who opened the consultation
    CONSULTANT = "consultant"      # The agent responding to the consultation
    PARTICIPANT = "participant"    # Additional participant in a collaboration round


# ── Node Models ───────────────────────────────────────────────────────────────

ARIADNE_SCHEMA_VERSION = "1.1.0"


class EpisodeNode(BaseModel):
    episode_id: UUID = Field(default_factory=uuid4)
    schema_version: str = ARIADNE_SCHEMA_VERSION
    agent_id: str  # FK to agent identity
    opened_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sealed_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None
    episode_status: EpisodeStatus = EpisodeStatus.CREATED
    crystallization_status: Optional[CrystallizationStatus] = None
    participants: list[str] = Field(default_factory=list)  # agent_ids
    spine_hash: Optional[str] = None  # SHA3-256 Merkle root; null until sealed
    spine_fingerprint: Optional[str] = None  # Adaptive Merkle leftmost branch fingerprint (Patent Fig. 2)
    spine_depth: Optional[int] = None  # Merkle tree depth (fingerprint component count)
    signal_manifest_hash: Optional[str] = None  # null until sealed
    episode_root_hash: Optional[str] = None  # H(spine || signal_manifest || exclusion); null until sealed
    parent_episode_id: Optional[UUID] = None
    fork_reason: Optional[str] = None
    workspace_id: Optional[str] = None  # Links to PostgreSQL workspace
    title: Optional[str] = None  # Human-readable episode title
    context_note: Optional[str] = None  # Cognitive anchor — user's statement of intent
    episode_type: Optional[str] = None  # Taxonomy: exploration, technical_review, planning, etc.
    initiated_by: Optional[str] = None  # User ID who created the episode
    episode_mode: str = "directed"  # "directed" (user drives) | "collaborative" (agents contribute unprompted)


class RetentionTier(str, Enum):
    """Retention classification for segments in crystallization and memory consolidation."""
    PERSISTENT = "PERSISTENT"  # Default — included in spine hash, survives crystallization
    EPHEMERAL = "EPHEMERAL"    # Excluded from spine hash — PASS decisions, evaluation metadata


class SegmentNode(BaseModel):
    segment_id: UUID = Field(default_factory=uuid4)
    episode_id: UUID
    segment_type: SegmentType
    sequence_index: int  # immutable after creation
    content_hash: str  # SHA3-256 of serialized content
    content_ref: str  # StoragePointer URI
    content_text: Optional[str] = None  # Durable content storage — actual text on the node
    authored_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    author: str  # agent_id
    retention_tier: RetentionTier = RetentionTier.PERSISTENT  # PERSISTENT | EPHEMERAL


class SignalNode(BaseModel):
    signal_id: UUID = Field(default_factory=uuid4)
    episode_id: UUID
    signal_type: SignalType
    signal_class: SignalClass
    signal_source: str
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    signal_status: SignalStatus = SignalStatus.RECEIVED
    content_hash: str
    content_ref: Optional[str] = None  # null for EPHEMERAL
    placement: SignalPlacement
    placement_rationale: Optional[str] = None  # REQUIRED if placement=EXCLUDED_MANIFEST
    influenced_segments: list[str] = Field(default_factory=list)  # segment UUIDs
    persistence_confirmed: bool = False
    payload_ref: Optional[str] = None


class SealNode(BaseModel):
    seal_id: UUID = Field(default_factory=uuid4)
    episode_id: UUID
    sealed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sealed_by: str  # agent_id
    spine_hash: str  # SHA3-256
    signal_manifest_hash: str
    exclusion_hash: str
    episode_root_hash: str  # H(spine || signal_manifest || exclusion)
    write_intent_id: UUID
    seal_status: SealStatus = SealStatus.PENDING
    agent_signature: Optional[str] = None
    mnemosyne_countersignature: Optional[str] = None


class ExclusionRecord(BaseModel):
    exclusion_id: UUID = Field(default_factory=uuid4)
    episode_id: UUID
    signal_id: UUID
    excluded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    exclusion_reason: ExclusionReason
    signal_content_hash: str  # content is NOT stored; only the hash commitment


class ConsultationNode(BaseModel):
    """
    First-class Ariadne node representing a cross-agent consultation.
    Lives in the initiating agent's episode as a branch.
    D2: branch event, not spine append. D4: created BEFORE exchange begins.
    """
    consultation_id: UUID = Field(default_factory=uuid4)
    episode_id: UUID
    consultation_type: ConsultationType
    initiating_agent: str
    consulting_agent: str
    initiated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None
    initiating_context_hash: str
    consultation_prompt: str  # stored directly in Neo4j
    consultation_prompt_hash: str
    resolution_type: Optional[str] = None  # synthesized | abandoned | deferred | escalated
    resolution_hash: Optional[str] = None
    consultation_node_hash: Optional[str] = None  # H(initiation_hash || resolution_hash)
    schema_version: str = ARIADNE_SCHEMA_VERSION


class ExchangeEntry(BaseModel):
    """
    A single turn within a ConsultationNode exchange.
    Forms a hash chain: each entry's previous_hash references the prior entry's content_hash.
    Content stored directly in Neo4j per D5.
    """
    entry_id: UUID = Field(default_factory=uuid4)
    consultation_id: UUID
    sequence: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    speaker: str
    role: ExchangeRole
    content: str  # stored directly in Neo4j
    content_hash: str
    previous_hash: str  # "GENESIS" for entry 0
    round_number: Optional[int] = None  # populated for COLLABORATIVE type


class ConsultationParticipantNode(BaseModel):
    """
    Lightweight participation record on the CONSULTED agent's episode.
    D3: consulted agent records participation, not the full exchange.
    """
    participant_id: UUID = Field(default_factory=uuid4)
    consultation_id: UUID
    episode_id: UUID  # consulted agent's episode
    initiating_agent: str
    initiating_episode_id: UUID
    participated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None
    consultation_type: ConsultationType
    schema_version: str = ARIADNE_SCHEMA_VERSION


class DocumentNode(BaseModel):
    """
    First-class document attachment in Ariadne.
    Provides verifiable integrity of data injection — the hash proves
    the document content hasn't changed since attachment.
    Protocol-level primitive: any Ariadne implementation needs this.
    """
    document_id: UUID = Field(default_factory=uuid4)
    episode_id: UUID
    filename: str
    mime_type: Optional[str] = None
    source: str = "local"  # "local" | "google_drive"
    source_ref: Optional[str] = None  # Drive file ID or local path
    drive_url: Optional[str] = None  # Google Drive web link
    content_hash: str  # SHA3-256 of document content
    content_text: Optional[str] = None  # Extracted text stored durably
    char_count: int = 0
    attached_by: str = ""  # user_id
    attached_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = ARIADNE_SCHEMA_VERSION


class CodicilNode(BaseModel):
    """
    A bounded, timestamped addendum to a CLOSED episode.
    Preserves integrity of the sealed record while permitting post-closure additions.
    Codicils are appended, never integrated into the original record.
    """
    codicil_id: UUID = Field(default_factory=uuid4)
    episode_id: UUID
    author: str  # user_id or agent_id
    content: str  # stored directly in Neo4j
    content_hash: str  # SHA3-256
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = ARIADNE_SCHEMA_VERSION


class EpisodeClosureRecord(BaseModel):
    """
    Structured record generated at episode seal time.
    Contains the summary, carried-forward items, and closure metadata.
    """
    closure_id: UUID = Field(default_factory=uuid4)
    episode_id: UUID
    sealed_by: str  # user_id
    sealed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    summary: Optional[str] = None  # User-provided closure summary
    closure_notes: Optional[str] = None  # Optional notes entered during seal
    carried_forward_items: list[str] = Field(default_factory=list)  # Open items carried to next episode
    artifact_count: int = 0
    segment_count: int = 0
    participant_count: int = 0
    codicil_count: int = 0
    amendment_episode_id: Optional[UUID] = None  # Set if episode was reopened as amendment


class AmendmentLink(BaseModel):
    """
    Links a new episode to a sealed source episode.
    Created when a user 'reopens' an archived episode.
    The original remains sealed; the new episode inherits context.
    """
    amendment_id: UUID = Field(default_factory=uuid4)
    source_episode_id: UUID  # The sealed/archived episode
    amendment_episode_id: UUID  # The new episode
    source_root_hash: Optional[str] = None  # Merkle root of sealed source
    source_title: Optional[str] = None
    source_closed_at: Optional[datetime] = None
    source_participants: list[str] = Field(default_factory=list)
    amendment_count: int = 1  # Depth in amendment chain
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str = ""


# ── Hash Utilities ────────────────────────────────────────────────────────────

def sha3_256(data: bytes) -> str:
    """Canonical hash function for all Ariadne content hashing. Returns hex string."""
    return hashlib.sha3_256(data).hexdigest()


def compute_spine_hash(segment_content_hashes: list[str], spine_signal_hashes: list[str]) -> str:
    """
    Merkle spine hash over ordered segments + SPINE-placed signals.

    Now delegates to the Adaptive Merkle Tree (patent-pending technology)
    which produces an identical root hash but also supports:
    - O(log n) incremental updates
    - Compact branch fingerprints for external verification
    - Threshold-based significance comparison
    - Configurable ordering functions

    For the full adaptive API (fingerprints, incremental appends, significance
    comparison), use ignis.ariadne.adaptive_merkle.AdaptiveMerkleTree directly.

    Input ordering: segments by sequence_index ASC, then SPINE signals by received_at ASC.
    Domain separation: each leaf prefixed with b'LEAF:' before hashing.
    Internal nodes prefixed with b'NODE:'.
    """
    from ariadne.core.merkle import compute_spine_hash_adaptive
    return compute_spine_hash_adaptive(segment_content_hashes, spine_signal_hashes)


def compute_episode_root_hash(spine_hash: str, signal_manifest_hash: str, exclusion_hash: str) -> str:
    """
    episode_root_hash = H(NODE: spine_hash || signal_manifest_hash || exclusion_hash)
    This is the canonical three-component root per CLO-CONSOLIDATED-1.1 S5.3.
    """
    return sha3_256(
        b"NODE:" +
        spine_hash.encode() +
        signal_manifest_hash.encode() +
        exclusion_hash.encode()
    )


# ── Governance Rule Enforcement ───────────────────────────────────────────────

class AriadneGovernanceError(Exception):
    """Raised when a governance rule (G-1 through G-7) would be violated."""
    pass


def enforce_G1_write_guard(episode_status: EpisodeStatus) -> None:
    """Rule G-1: No segment or signal may be written to SEALING, SEALED, or ARCHIVED episodes."""
    if episode_status in (EpisodeStatus.SEALING, EpisodeStatus.SEALED, EpisodeStatus.ARCHIVED):
        raise AriadneGovernanceError(
            f"G-1 violation: Cannot write to episode in {episode_status} state."
        )


def enforce_G5_placement_rationale(signal: SignalNode) -> None:
    """Rule G-5: placement_rationale is required when placement=EXCLUDED_MANIFEST."""
    if signal.placement == SignalPlacement.EXCLUDED_MANIFEST and not signal.placement_rationale:
        raise AriadneGovernanceError(
            f"G-5 violation: Signal {signal.signal_id} has placement=EXCLUDED_MANIFEST "
            f"but no placement_rationale."
        )


def enforce_G7_triggered_edge(signal: SignalNode, has_triggered_edge: bool) -> None:
    """Rule G-7: causal signals require a TRIGGERED edge to at least one segment."""
    if signal.signal_class == SignalClass.causal and not has_triggered_edge:
        raise AriadneGovernanceError(
            f"G-7 violation: Signal {signal.signal_id} has signal_class=causal "
            f"but no TRIGGERED edge. Add the TRIGGERED edge before committing."
        )


def validate_signal_classification(signal: SignalNode) -> None:
    """
    Validates the dual taxonomy composition rules from CLO-03 S3.1.
    EPHEMERAL type + causal class requires placement=BRANCH_LEAF (not SPINE).
    STRUCTURAL type must have signal_class=causal (structural signals are by definition causal).
    """
    if signal.signal_type == SignalType.STRUCTURAL and signal.signal_class != SignalClass.causal:
        raise AriadneGovernanceError(
            f"G-taxonomy violation: STRUCTURAL signals must have signal_class=causal. "
            f"Signal {signal.signal_id} has signal_class={signal.signal_class}."
        )
    if (signal.signal_type == SignalType.EPHEMERAL
            and signal.signal_class == SignalClass.causal
            and signal.placement == SignalPlacement.SPINE):
        raise AriadneGovernanceError(
            f"G-taxonomy violation: EPHEMERAL/causal signals must use BRANCH_LEAF placement, "
            f"not SPINE. Signal {signal.signal_id}."
        )


# ── Consultation Hash Utilities (Spec 9) ────────────────────────────────────


def compute_exchange_chain_hash(entries: list[ExchangeEntry]) -> str:
    """
    Returns the hash of the final entry in an exchange chain.
    Verifies chain integrity before returning.
    """
    if not entries:
        raise ValueError("Cannot compute exchange chain hash: no entries")
    for i, entry in enumerate(entries):
        if i == 0:
            if entry.previous_hash != "GENESIS":
                raise AriadneGovernanceError(
                    f"Exchange chain integrity violation: entry 0 previous_hash "
                    f"must be 'GENESIS', got '{entry.previous_hash}'"
                )
        else:
            expected = entries[i - 1].content_hash
            if entry.previous_hash != expected:
                raise AriadneGovernanceError(
                    f"Exchange chain integrity violation at entry {i}: "
                    f"previous_hash {entry.previous_hash!r} != "
                    f"prior entry content_hash {expected!r}"
                )
    return entries[-1].content_hash


def compute_consultation_node_hash(initiation_hash: str, resolution_hash: str) -> str:
    """H(NODE: initiation_hash || resolution_hash) — incorporated into episode spine."""
    return sha3_256(b"NODE:" + initiation_hash.encode() + resolution_hash.encode())


def compute_initiation_hash(
    episode_id: str, consultation_id: str, initiated_at: str, initiating_context_hash: str,
) -> str:
    """Hash at branch point — written before any exchange occurs."""
    return sha3_256(
        b"NODE:" + episode_id.encode() + consultation_id.encode() +
        initiated_at.encode() + initiating_context_hash.encode()
    )


# ── Consultation Governance Rules (Spec 9) ──────────────────────────────────


def enforce_G8_initiation_before_exchange(
    initiation_hash: Optional[str], has_exchange_entries: bool,
) -> None:
    """Rule G-8: Exchange entries may not exist without a prior initiation hash."""
    if has_exchange_entries and initiation_hash is None:
        raise AriadneGovernanceError(
            "G-8 violation: Exchange entries exist but no initiation_hash is set."
        )


def enforce_G9_resolution_requires_entries(
    resolution_hash: Optional[str], exchange_entries: list,
) -> None:
    """Rule G-9: A consultation cannot be resolved without at least one exchange entry."""
    if resolution_hash is not None and len(exchange_entries) == 0:
        raise AriadneGovernanceError(
            "G-9 violation: resolution_hash is set but exchange_entries is empty."
        )
