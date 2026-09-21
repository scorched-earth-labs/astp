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
ASTP Adapter Service Interface (ASI)

Abstract base class defining the contract that any database adapter must
implement to be a conforming ASTP persistence backend.

The Neo4j adapter in astp.adapters.neo4j is the reference implementation.
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

from astp.core.schema import (
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


class ASTPAdapter(ABC):
    """
    Abstract adapter interface for ASTP persistence backends.

    Implementations must handle:
    1. Schema initialization (constraints, indexes)
    2. Node CRUD for all ASTP node types
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

    # ── Agent Retrieval Operations ───────────────────────────────────────────
    # These methods expose Episode segment content to agents via tool calls.
    # Agent-directed retrieval is a protocol-level capability: any conforming
    # adapter must support it. This is the read-path complement to the WIL
    # write-path — write ordering on the way in, agent-directed retrieval
    # on the way out.

    @abstractmethod
    async def get_segment_by_id(
        self,
        episode_id: UUID,
        segment_id: UUID,
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve a single segment by ID with full content.
        Returns None if the segment does not exist or does not belong to
        the specified episode (episode scoping is a security requirement —
        never return segments across episode boundaries without explicit
        cross-episode authorization).
        """
        ...

    @abstractmethod
    async def get_segment_range(
        self,
        episode_id: UUID,
        from_index: int,
        to_index: int,
        segment_types: Optional[List[str]] = None,
        authors: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve a contiguous range of segments by sequence_index (inclusive).
        Primary tool for collaborative mode — agent wants turns N through M.

        segment_types: optional filter e.g. ["CONVERSATION", "COLLABORATION"]
        authors: optional filter by agent_id or "user"

        Returns ordered by sequence_index ASC.
        """
        ...

    @abstractmethod
    async def get_episode_spine(
        self,
        episode_id: UUID,
        limit: int = 20,
        before_index: Optional[int] = None,
        segment_types: Optional[List[str]] = None,
        retention_tier: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve the most recent N segments from the Episode spine.

        before_index: if provided, retrieves N segments before this spine
        position. Use the agent's current sequence_index to get prior
        context without knowing exact turn numbers.

        segment_types: optional filter by type
        retention_tier: optional filter — "PERSISTENT" or "EPHEMERAL"

        Returns ordered by sequence_index ASC.
        """
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


AriadneAdapter = ASTPAdapter  # name retained for callers written before astp 0.6.0


# ── Structural store — the contract the operations layer writes through ──────
#
# The branch / fork / merge / aside / soliloquy operations (astp.core.branch_operations),
# cross-episode linking (astp.core.cross_episode), grouping (astp.core.grouping),
# coherence (astp.core.coherence) and the audit-chain helpers (astp.core.audit_chain)
# read and write the structural record through this contract and nothing else.
# No store is named in the operations layer: an implementation supplies one of
# these, and the reference Neo4j implementation is astp.adapters.neo4j.store.
#
# Every method is synchronous. A method that cannot complete raises — a store
# failure as AdapterWriteError (chained), a governance violation as its own
# ASTPProtocolError subclass — and never returns a default (SPEC §15 item 7).
# A *read* that finds nothing returns None or an empty collection; that is a
# result, not a failure.


class StructuralStore(ABC):
    """The storage contract of the operations layer (SPEC §15, §19, §20).

    Node arguments are the pydantic models of ``astp.core.branching``,
    ``astp.core.cross_episode`` and ``astp.core.grouping``; identifiers are the
    canonical string form of the UUID. Reads return plain dicts keyed by the
    property names those models use.
    """

    # ── Episodes ───────────────────────────────────────────────────────────

    @abstractmethod
    def episode_status(self, episode_id: str) -> Optional[str]:
        """The Episode's lifecycle status, or None when the Episode does not exist."""
        ...

    @abstractmethod
    def episode_spine_hash(self, episode_id: str) -> Optional[str]:
        """The Episode's current spine hash, or None when unset or the Episode does not exist."""
        ...

    @abstractmethod
    def episode_status_and_spine_hash(self, episode_id: str) -> Optional[tuple]:
        """``(status, spine_hash)`` read together, or None when the Episode does not exist."""
        ...

    @abstractmethod
    def departure_fork_episode(self, fork_episode_id: Optional[str] = None,
                               fork_id: Optional[str] = None) -> tuple:
        """``(episode_id, fork_status)`` of a departure-fork Episode found by its
        own id or by ``fork_id``; ``(None, None)`` when there is none."""
        ...

    @abstractmethod
    def write_departure_fork_episode(self, episode: Any) -> None: ...

    @abstractmethod
    def set_episode_fork_return_type(self, episode_id: str, return_type: str) -> None: ...

    @abstractmethod
    def mark_departure_fork_status(self, fork_episode_id: str, status: str) -> None: ...

    @abstractmethod
    def set_departure_fork_anchor_index(self, fork_episode_id: str, anchor_index: int) -> None: ...

    # ── Segments ───────────────────────────────────────────────────────────

    @abstractmethod
    def segment_sequence_index(self, segment_id: str) -> Optional[int]:
        """The Segment's ``sequence_index``, or None when it does not exist."""
        ...

    @abstractmethod
    def segment_content_hashes(self, segment_ids) -> Dict[str, tuple]:
        """``segment_id -> (sequence_index, content_hash)`` for the Segments that exist
        among ``segment_ids`` and carry a content hash (SPEC §19.4)."""
        ...

    # ── Branches ───────────────────────────────────────────────────────────

    @abstractmethod
    def write_branch_point(self, branch_point: Any) -> None: ...

    @abstractmethod
    def branch_point_with_terminus(self, branch_id: str) -> Optional[tuple]:
        """``(branch_point_properties, has_terminus)`` or None when the branch does not exist."""
        ...

    @abstractmethod
    def write_branch_terminus(self, terminus: Any) -> None: ...

    @abstractmethod
    def write_branch_return_edge(self, branch_return: Any) -> None: ...

    @abstractmethod
    def find_common_ancestor(self, branch_id: str, target_episode_id: str) -> Optional[dict]: ...

    # ── Forks ──────────────────────────────────────────────────────────────

    @abstractmethod
    def write_fork_point(self, fork_point: Any) -> None: ...

    @abstractmethod
    def fork_points_of(self, fork_id: str) -> List[dict]:
        """Every ForkPoint of a fork: ``fpid``, ``eid``, ``status``, ``origin_id``."""
        ...

    @abstractmethod
    def mark_fork_point_status(self, fork_point_id: str, status: str) -> None: ...

    @abstractmethod
    def write_departure_fork_point(self, fork_point: Any) -> None: ...

    @abstractmethod
    def departure_fork_point_by_fork(self, fork_id: str) -> Optional[dict]:
        """``pid``, ``eid``, ``tip`` of the DepartureForkPoint of ``fork_id``, or None."""
        ...

    @abstractmethod
    def write_fork_return_node(self, fork_return: Any) -> None: ...

    @abstractmethod
    def fork_return_exists(self, fork_id: str) -> bool: ...

    # ── Merges ─────────────────────────────────────────────────────────────

    @abstractmethod
    def write_merge_point(self, merge_point: Any) -> None: ...

    @abstractmethod
    def merge_point(self, merge_id: str) -> Optional[dict]:
        """The MergePoint's properties, or None."""
        ...

    @abstractmethod
    def merge_executed_forward_delta(self, merge_id: str) -> Optional[str]:
        """The stored ``forward_delta`` text of the MERGE_EXECUTED audit record that
        names ``merge_id``, or None."""
        ...

    # ── Asides and soliloquies ─────────────────────────────────────────────

    @abstractmethod
    def write_aside(self, aside: Any) -> None: ...

    @abstractmethod
    def write_aside_terminus(self, terminus: Any) -> None: ...

    @abstractmethod
    def load_aside(self, aside_id: str) -> Optional[dict]: ...

    @abstractmethod
    def scan_aside_external_references(self, aside_id: str, content_refs: List[str]) -> List[str]:
        """The content refs among ``content_refs`` that resolve outside the aside (G-26)."""
        ...

    @abstractmethod
    def write_soliloquy(self, soliloquy: Any) -> None: ...

    @abstractmethod
    def write_soliloquy_conclusion(self, conclusion: Any) -> None: ...

    @abstractmethod
    def load_soliloquy(self, soliloquy_id: str) -> Optional[dict]: ...

    # ── Coherence ──────────────────────────────────────────────────────────

    @abstractmethod
    def write_coherence_fingerprint(self, fingerprint: Any) -> None: ...

    @abstractmethod
    def recent_fingerprints(self, episode_id: str, limit: int = 10) -> List[dict]: ...

    @abstractmethod
    def last_fingerprint(self, episode_id: str) -> Optional[dict]: ...

    @abstractmethod
    def last_nominal_segment(self, episode_id: str) -> Optional[str]: ...

    # ── Cross-episode links and grouping ───────────────────────────────────

    @abstractmethod
    def write_episode_link(self, link: Any) -> None: ...

    @abstractmethod
    def write_membership_record(self, record: Any) -> None: ...

    @abstractmethod
    def membership_record_role(self, record_id: str) -> Optional[str]:
        """The ``membership_role`` of a MembershipRecord, or None."""
        ...

    @abstractmethod
    def write_conformance_declaration(self, declaration: Any) -> None: ...

    @abstractmethod
    def supersede_conformance_declaration(self, old_declaration_id: str, new_declaration_id: str) -> None: ...

    # ── Audit chain, intents, write-intent ledger ──────────────────────────

    @abstractmethod
    def write_audit_record(self, audit: Any) -> None: ...

    @abstractmethod
    def max_delta_sequence(self, chain_key: str) -> Optional[int]:
        """The highest ``delta_sequence`` on the chain, or None when the chain is empty."""
        ...

    @abstractmethod
    def latest_audit_record_hash(self, chain_key: str) -> Optional[str]:
        """The ``record_hash`` of the chain's most recent record, or None when the chain is empty."""
        ...

    @abstractmethod
    def acquire_intent(self, idempotency_key: str, intent_type: str, initiator_id: str) -> tuple:
        """``(intent_properties, is_new)``: an existing intent (COMPLETE or in progress)
        is returned with ``is_new=False``; otherwise the intent is created."""
        ...

    @abstractmethod
    def complete_intent(self, idempotency_key: str, result_node_id: str) -> None: ...

    @abstractmethod
    def write_completed_wil_entry(self, intent_id: str, operation: str, episode_id: str,
                                  node_id: str, timestamp: str) -> None:
        """Ledger a structural write that has already completed (G-39): one
        ``COMPLETE`` entry whose pre- and post-state hash is ``node_id``."""
        ...


def as_structural_store(store_or_driver: Any) -> "StructuralStore":
    """Accept either a ``StructuralStore`` or, for callers written before astp
    0.7.0, a raw driver of the reference store — which is wrapped in the
    reference implementation. The raw-driver form is retained for one release."""
    if isinstance(store_or_driver, StructuralStore):
        return store_or_driver
    from astp.adapters.neo4j.store import Neo4jStructuralStore
    return Neo4jStructuralStore(store_or_driver)
