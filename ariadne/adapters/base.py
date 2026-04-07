"""
Ariadne Adapter Service Interface (ASI)

Abstract base class defining the contract that any database adapter must
implement to be a conforming Ariadne persistence backend.

The Neo4j adapter in ariadne.adapters.neo4j is the reference implementation.
Other adapters (PostgreSQL/AGE, Neptune, ArangoDB, SQL-based) must implement
this interface to guarantee protocol compliance.

Protocol guarantees that adapters must preserve:
- Governance rules G1-G9 (enforced at the protocol layer, but adapters
  must not circumvent them)
- Hash chain integrity (content_hash, spine_hash, episode_root_hash)
- Write ordering invariants (declared via WIL)
- Immutability of sealed episodes
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from uuid import UUID

from ariadne.core.schema import (
    EpisodeNode,
    EpisodeStatus,
    ExclusionRecord,
    SealNode,
    SegmentNode,
    SignalNode,
    DocumentNode,
    CodicilNode,
    EpisodeClosureRecord,
    AmendmentLink,
    ConsultationNode,
    ExchangeEntry,
    ConsultationParticipantNode,
)


class AriadneAdapter(ABC):
    """
    Abstract adapter interface for Ariadne persistence backends.

    Implementations must handle:
    1. Schema initialization (constraints, indexes)
    2. Node CRUD for all Ariadne node types
    3. Edge creation (CONTAINS, TRIGGERED, REFERENCES, etc.)
    4. Query operations for UI and agent consumption

    Adapters do NOT enforce governance rules — that's the protocol layer's job.
    Adapters MUST NOT silently swallow writes (fail loudly on error).
    """

    # ── Schema Lifecycle ─────────────────────────────────────────────────────

    @abstractmethod
    async def initialize_schema(self) -> None:
        """Create constraints, indexes, and schema version seed.
        Called once on startup. Must be idempotent."""
        ...

    # ── Episode Operations ───────────────────────────────────────────────────

    @abstractmethod
    async def create_episode(self, episode: EpisodeNode) -> None:
        """Persist a new episode node. MERGE semantics (idempotent)."""
        ...

    @abstractmethod
    async def update_episode_status(
        self, episode_id: UUID, status: EpisodeStatus, **fields: Any
    ) -> None:
        """Update episode status and optional fields (sealed_at, spine_hash, etc.)."""
        ...

    @abstractmethod
    async def get_episode(self, episode_id: UUID) -> Optional[Dict[str, Any]]:
        """Retrieve a single episode by ID. Returns None if not found."""
        ...

    # ── Segment Operations ───────────────────────────────────────────────────

    @abstractmethod
    async def create_segment(
        self, segment: SegmentNode, episode_status: EpisodeStatus
    ) -> None:
        """Persist a segment and create CONTAINS edge to its episode.
        Caller is responsible for G-1 enforcement before calling."""
        ...

    @abstractmethod
    async def list_segments(
        self, episode_id: UUID, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """List segments for an episode, ordered by sequence_index."""
        ...

    # ── Signal Operations ────────────────────────────────────────────────────

    @abstractmethod
    async def create_signal(
        self, signal: SignalNode, episode_status: EpisodeStatus
    ) -> None:
        """Persist a signal node and create RECEIVED_BY edge to its episode."""
        ...

    @abstractmethod
    async def list_signals(
        self, episode_id: UUID, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """List signals for an episode."""
        ...

    # ── Seal Operations ──────────────────────────────────────────────────────

    @abstractmethod
    async def create_seal(self, seal: SealNode) -> None:
        """Persist a seal node and create SEALED_BY edge to its episode."""
        ...

    # ── Exclusion Operations ─────────────────────────────────────────────────

    @abstractmethod
    async def create_exclusion(self, exclusion: ExclusionRecord) -> None:
        """Persist an exclusion record."""
        ...

    # ── Document Operations ──────────────────────────────────────────────────

    @abstractmethod
    async def create_document(self, document: DocumentNode) -> None:
        """Persist a document node and create ATTACHED_TO edge to its episode."""
        ...

    # ── Consultation Operations ──────────────────────────────────────────────

    @abstractmethod
    async def create_consultation(self, consultation: ConsultationNode) -> None:
        """Persist a consultation node."""
        ...

    @abstractmethod
    async def create_exchange_entry(self, entry: ExchangeEntry) -> None:
        """Persist an exchange entry in a consultation's hash chain."""
        ...

    @abstractmethod
    async def create_consultation_participant(
        self, participant: ConsultationParticipantNode
    ) -> None:
        """Record a participation record on the consulted agent's episode."""
        ...

    # ── Closure Operations ───────────────────────────────────────────────────

    @abstractmethod
    async def create_closure_record(self, closure: EpisodeClosureRecord) -> None:
        """Persist an episode closure record."""
        ...

    @abstractmethod
    async def create_codicil(self, codicil: CodicilNode) -> None:
        """Persist a codicil (post-closure addendum)."""
        ...

    @abstractmethod
    async def create_amendment_link(self, amendment: AmendmentLink) -> None:
        """Link a new episode to a sealed source episode."""
        ...

    # ── Query Operations ─────────────────────────────────────────────────────

    @abstractmethod
    async def list_episodes(
        self,
        workspace_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        status: Optional[EpisodeStatus] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List episodes with optional filters."""
        ...

    @abstractmethod
    async def get_episode_detail(self, episode_id: UUID) -> Optional[Dict[str, Any]]:
        """Get full episode detail including segment/signal counts."""
        ...

    # ── Edge Operations ──────────────────────────────────────────────────────

    @abstractmethod
    async def create_segment_reference(
        self,
        source_segment_id: UUID,
        target_segment_id: UUID,
        reference_type: str,
    ) -> None:
        """Create a REFERENCES edge between segments."""
        ...
