"""
Write Intent Log (WIL) — cross-system write coordination standard.

Protocol-level definitions: enums, models, write ordering invariant,
TTL policy, provisional state guard. Database-agnostic.

Three storage invariants from OQ-D01 resolution:
1. Redis as ephemeral coordinator, not persistent store
2. Blob -> Neo4j -> QDrant write ordering (formal invariant)
3. Provisional state never enters persistent storage

Spec 8 of Phase 2 Ariadne Persistence Layer.
Source: CLO-CONSOLIDATED-1.1 S6, S8; OQ-D01 Resolution.
"""

import logging
import os
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from ariadne.core.schema import AriadneGovernanceError, sha3_256

logger = logging.getLogger(__name__)

ARIADNE_ENABLED = os.getenv("ARIADNE_ENABLED", "false").lower() == "true"

# PROVISIONAL_WINDOW_PENDING_EMPIRICAL_VALIDATION
# 4 hours is the conservative upper bound per OQ-D01 resolution.
# Measurement target: T_wil_p99 = P99(delta write initiated -> Neo4j write confirmed)
PROVISIONAL_WINDOW_HOURS = float(os.getenv("ARIADNE_PROVISIONAL_WINDOW_HOURS", "4"))
PROVISIONAL_WINDOW_SECONDS = int(PROVISIONAL_WINDOW_HOURS * 3600)


# ── Enums ─────────────────────────────────────────────────────────────────────

class WILOperation(str, Enum):
    EPISODE_CREATE = "EPISODE_CREATE"
    # Segment appended to the spine.
    #
    # NOT YET EMITTED BY THIS LIBRARY. `create_segment_node` (adapters/neo4j/
    # writer.py) currently writes the segment directly, without declaring a
    # write intent — segment commits are the one core spine operation with no
    # ledger coverage. The member is defined here because the value already
    # exists on AriadneWILEntry nodes in the field: downstream writers filled
    # the gap out-of-band, so the vocabulary must account for it even though
    # the coordinated write path does not exist yet.
    #
    # Closing that gap means giving create_segment_node the same
    # declare_write_intent / record_store_completion treatment SIGNAL_COMMIT
    # gets in adapters/neo4j/wil.py. Tracked separately — it is a behavioural
    # change on the hottest write path in the protocol, not a vocabulary edit.
    SEGMENT_COMMIT = "SEGMENT_COMMIT"
    SIGNAL_COMMIT = "SIGNAL_COMMIT"
    EPISODE_SEAL = "EPISODE_SEAL"
    MANIFEST_FINALIZE = "MANIFEST_FINALIZE"
    CRYSTALLIZATION = "CRYSTALLIZATION"
    EPISODE_ARCHIVE = "EPISODE_ARCHIVE"
    EPISODE_CLOSE = "EPISODE_CLOSE"                  # Episode sealed (closure)
    CODICIL_APPEND = "CODICIL_APPEND"                # Codicil added to sealed episode
    ATTACHMENT_COMMIT = "ATTACHMENT_COMMIT"          # External content injected (S4.7)
    CONSULTATION_COMMIT = "CONSULTATION_COMMIT"      # Cross-agent exchange (G-8, G-9)
    # Branch / Fork / Merge lifecycle (SPEC S19).
    #
    # Every BFM ledger write goes through `_write_branch_wil` in
    # branch_operations.py. These members exist so that helper can take a
    # WILOperation rather than a bare str — previously it accepted any string
    # and eight of the ten operations it is called with were absent here, which
    # made this enum read as the authoritative operation list without being one.
    #
    # NOTE: these values are intentionally NOT aligned with the corresponding
    # CognitiveDeltaType names (SOLILOQUY_INIT here vs SOLILOQUY_INITIATED
    # there). They are distinct vocabularies — the delta type records a
    # reasoning event, this records a durability intent — and the values below
    # are already persisted on AriadneWILEntry nodes in the field. Renaming
    # them is a data migration, not an edit.
    BRANCH_CREATE = "BRANCH_CREATE"                  # Branch created from spine
    BRANCH_ABANDON = "BRANCH_ABANDON"                # Branch terminated without merge
    FORK_CREATE = "FORK_CREATE"                      # Fork opened from a spine point
    FORK_RESOLVE = "FORK_RESOLVE"                    # Fork resolved back to the spine
    DEPARTURE_FORK_CREATE = "DEPARTURE_FORK_CREATE"  # Departure fork opened
    MERGE_EXECUTE = "MERGE_EXECUTE"                  # Merge point committed
    ASIDE_OPEN = "ASIDE_OPEN"                        # Aside segment opened
    ASIDE_CLOSE = "ASIDE_CLOSE"                      # Aside segment closed
    SOLILOQUY_INIT = "SOLILOQUY_INIT"                # Soliloquy initiated
    SOLILOQUY_CONCLUDE = "SOLILOQUY_CONCLUDE"        # Soliloquy concluded


class WILStatus(str, Enum):
    PENDING = "PENDING"      # completed_at is null — write in progress
    COMPLETE = "COMPLETE"    # all stores confirmed
    FAILED = "FAILED"        # write failed; recovery required
    REPLAYING = "REPLAYING"  # recovery in progress


class StoreLayer(str, Enum):
    """
    Storage layers in write-ordering priority.
    Blob -> Neo4j -> QDrant is a formal invariant, not a convention.
    """
    BLOB = "blob"      # Highest durability — always written first
    NEO4J = "neo4j"    # Authoritative structural record — written second
    REDIS = "redis"    # Ephemeral coordinator — written concurrently with Neo4j
    QDRANT = "qdrant"  # Semantic search — written last; degradation is recoverable


class WritePhase(str, Enum):
    """Three-phase write protocol per CLO-06 S6.3."""
    INTENT_DECLARED = "INTENT_DECLARED"
    WRITE_EXECUTION = "WRITE_EXECUTION"
    COMPLETION = "COMPLETION"


# ── WIL Entry ────────────────────────────────────────────────────────────────

class WriteIntentEntry(BaseModel):
    """
    WIL entry schema per CLO-06 S6.2.
    An incomplete entry (completed_at is null) indicates an interrupted write.
    All writes are idempotent — re-execution is safe.
    """
    intent_id: UUID = Field(default_factory=uuid4)
    operation: WILOperation
    episode_id: UUID
    stores_involved: list[StoreLayer]
    pre_state_hash: str              # SHA3-256 of state before write
    post_state_hash: str             # Expected hash after write
    initiated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    completed_at: Optional[datetime] = None  # null = in progress
    status: WILStatus = WILStatus.PENDING
    last_completed_store: Optional[StoreLayer] = None
    failure_reason: Optional[str] = None


# ── Write Ordering Invariant ─────────────────────────────────────────────────

WRITE_ORDER: list[StoreLayer] = [
    StoreLayer.BLOB,    # 1st: highest durability
    StoreLayer.NEO4J,   # 2nd: authoritative structural record
    StoreLayer.REDIS,   # 3rd: ephemeral coordinator
    StoreLayer.QDRANT,  # 4th: semantic search; degradation always recoverable
]

# QDrant degradation recovery guarantee: agents can always reconstruct from
# Neo4j (structure) + Blob (content). Search is degraded but identity is intact.
QDRANT_DEGRADATION_RECOVERABLE = True  # Invariant — must remain True


def enforce_write_order(stores: list[StoreLayer]) -> list[StoreLayer]:
    """
    Returns stores sorted in mandatory write order (Blob -> Neo4j -> Redis -> QDrant).
    Raises AriadneGovernanceError for unknown store layers.
    """
    ordered = [s for s in WRITE_ORDER if s in stores]
    if set(ordered) != set(stores):
        unknown = set(stores) - set(WRITE_ORDER)
        raise AriadneGovernanceError(
            f"Write ordering violation: Unknown store layer(s) {unknown}. "
            f"All stores must be declared in WRITE_ORDER."
        )
    return ordered


# ── Redis Key Schema and TTL Policy ──────────────────────────────────────────
# Per CLO-08 S8.3: Every ariadne::* key carries an explicit TTL.

REDIS_TTL_POLICY: dict[str, int] = {
    "ariadne::episode::{id}": 4 * 3600,                # Session lifetime max (4h)
    "ariadne::branch::{id}": 2 * 3600,                 # Branch lifetime max (2h)
    "ariadne::merkle::{id}": 15 * 60,                  # 15 minutes; renewed on verification
    "ariadne::manifest::{id}": PROVISIONAL_WINDOW_SECONDS,  # Provisional window duration
    "ariadne::wil::{id}": 24 * 3600,                   # WIL entries: 24h before graduation
    "ariadne::consultation::{id}": 4 * 3600,           # Active consultation: 4h (same as episode)
}


def get_redis_ttl(key_pattern: str) -> int:
    """
    Returns the mandatory TTL in seconds for a given Redis key pattern.
    Raises AriadneGovernanceError if not in the policy.
    """
    for pattern, ttl in REDIS_TTL_POLICY.items():
        prefix = pattern.split("{")[0]
        if key_pattern.startswith(prefix):
            return ttl
    raise AriadneGovernanceError(
        f"Redis TTL policy violation: No TTL defined for key '{key_pattern}'. "
        f"All ariadne::* Redis keys must have an explicit TTL. "
        f"Add this key pattern to REDIS_TTL_POLICY before writing."
    )


def build_redis_episode_key(episode_id: str) -> str:
    return f"ariadne::episode::{episode_id}"


def build_redis_manifest_key(episode_id: str) -> str:
    return f"ariadne::manifest::{episode_id}"


def build_redis_wil_key(intent_id: str) -> str:
    return f"ariadne::wil::{intent_id}"


def build_redis_merkle_key(leaf_id: str) -> str:
    return f"ariadne::merkle::{leaf_id}"


# ── Provisional State Guard ──────────────────────────────────────────────────
# Invariant 3 from OQ-D01: Provisional state never enters persistent storage.

PROVISIONAL_PERSISTENT_STORES = {StoreLayer.NEO4J, StoreLayer.QDRANT, StoreLayer.BLOB}


def enforce_provisional_state_guard(
    is_provisional: bool,
    target_store: StoreLayer,
    data_description: str,
) -> None:
    """
    Raises AriadneGovernanceError if provisional data is written to a persistent store.
    Provisional data may only live in Redis during the provisional window.
    """
    if is_provisional and target_store in PROVISIONAL_PERSISTENT_STORES:
        raise AriadneGovernanceError(
            f"Provisional state invariant violation: Attempted to write provisional "
            f"data '{data_description}' to persistent store '{target_store.value}'. "
            f"Provisional state may only exist in Redis during the provisional window "
            f"(max {PROVISIONAL_WINDOW_HOURS}h). "
            f"Data must be fully crystallized before writing to {target_store.value}."
        )
