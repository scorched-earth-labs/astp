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
Write Intent Log (WIL) — cross-system write coordination standard.

Protocol-level definitions: the operation register, the entry model, the
write-ordering invariant over storage *roles*, and the provisional-state
guard. No store is named: a role is what the protocol knows (SPEC §12.1), and
a provider is a deployment's choice recorded nowhere in normative text.

Three storage invariants (SPEC §12.1):
1. The ephemeral coordinator holds coordination state, never the record
2. durable content -> authoritative structural -> ephemeral coordinator
   -> semantic index write ordering (formal invariant)
3. Provisional state never enters persistent storage
"""

import logging
import os
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator

from astp.core.schema import ASTPGovernanceError

logger = logging.getLogger(__name__)


# PROVISIONAL_WINDOW_PENDING_EMPIRICAL_VALIDATION
# 4 hours is the conservative upper bound.
# Measurement target: T_wil_p99 = P99(delta write initiated -> structural-store write confirmed)
PROVISIONAL_WINDOW_HOURS = float(
    os.getenv("ASTP_PROVISIONAL_WINDOW_HOURS", os.getenv("ARIADNE_PROVISIONAL_WINDOW_HOURS", "4"))
)  # the ARIADNE_ name is honoured for deployments configured before astp 0.6.0
PROVISIONAL_WINDOW_SECONDS = int(PROVISIONAL_WINDOW_HOURS * 3600)


# ── Enums ─────────────────────────────────────────────────────────────────────

class WILOperation(str, Enum):
    EPISODE_CREATE = "EPISODE_CREATE"
    # Segment appended to the spine. An implementation's coordinated write
    # path ledgers it; a bare node write without one is the gap §12.4.2 forbids.
    SEGMENT_COMMIT = "SEGMENT_COMMIT"
    SIGNAL_COMMIT = "SIGNAL_COMMIT"
    EPISODE_SEAL = "EPISODE_SEAL"
    MANIFEST_FINALIZE = "MANIFEST_FINALIZE"
    CRYSTALLIZATION = "CRYSTALLIZATION"
    EPISODE_ARCHIVE = "EPISODE_ARCHIVE"
    EPISODE_CLOSE = "EPISODE_CLOSE"                  # Episode sealed (closure)
    CODICIL_APPEND = "CODICIL_APPEND"                # Codicil added to sealed episode
    ATTACHMENT_COMMIT = "ATTACHMENT_COMMIT"          # External content injected (§4.7)
    CONSULTATION_COMMIT = "CONSULTATION_COMMIT"      # Cross-agent exchange (G-8, G-9)
    # Branch / Fork / Merge lifecycle (SPEC §19).
    #
    # Every BFM ledger write goes through `_write_branch_wil` in
    # branch_operations.py. These members exist so that helper can take a
    # WILOperation rather than a bare str.
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


class StoreRole(str, Enum):
    """The four storage roles of SPEC §12.1, in write-ordering priority:
    durable content -> authoritative structural -> ephemeral coordinator ->
    semantic index. The order is a formal invariant, not a convention.

    Roles are named by role. Wherever a role is recorded — a ledger entry's
    ``stores_involved``, a conformance declaration — its value is one of these.
    Ledger entries written under 4.x carry the reference deployment's provider
    names; they are stored data and are not rewritten. ``store_role_of`` maps
    them by the fixed correspondence §12.1 requires the reference
    implementation to publish.
    """
    DURABLE_CONTENT = "durable_content"                  # written first
    AUTHORITATIVE_STRUCTURAL = "authoritative_structural"  # written second
    EPHEMERAL_COORDINATOR = "ephemeral_coordinator"      # concurrently with the structural store
    SEMANTIC_INDEX = "semantic_index"                    # written last; degradation is recoverable


# The fixed correspondence of SPEC §12.1: the provider names the reference
# deployment recorded in 4.x ledger entries, and the role each names. Stored
# data — a reader maps, a writer does not emit them.
LEGACY_STORE_VALUES: dict[str, StoreRole] = {
    "blob": StoreRole.DURABLE_CONTENT,
    "neo4j": StoreRole.AUTHORITATIVE_STRUCTURAL,
    "redis": StoreRole.EPHEMERAL_COORDINATOR,
    "qdrant": StoreRole.SEMANTIC_INDEX,
}


def store_role_of(value) -> StoreRole:
    """The role a stored ``stores_involved`` value names: a role name, or a 4.x
    provider name of the reference deployment (``LEGACY_STORE_VALUES``).
    Anything else is refused."""
    if isinstance(value, StoreRole):
        return value
    raw = getattr(value, "value", value)
    try:
        return StoreRole(raw)
    except ValueError:
        pass
    if raw in LEGACY_STORE_VALUES:
        return LEGACY_STORE_VALUES[raw]
    raise ValueError(f"unknown store value {raw!r}")


class WritePhase(str, Enum):
    """Three-phase write protocol (SPEC §12.2)."""
    INTENT_DECLARED = "INTENT_DECLARED"
    WRITE_EXECUTION = "WRITE_EXECUTION"
    COMPLETION = "COMPLETION"


# ── WIL Entry ────────────────────────────────────────────────────────────────

class WriteIntentEntry(BaseModel):
    """
    WIL entry schema (SPEC §12.2).
    An incomplete entry (completed_at is null) indicates an interrupted write.
    All writes are idempotent — re-execution is safe.
    """
    intent_id: UUID = Field(default_factory=uuid4)
    operation: WILOperation
    episode_id: UUID
    stores_involved: list[str]       # role names (§12.1); a 4.x provider name is read via store_role_of
    pre_state_hash: str              # SHA3-256 of state before write
    post_state_hash: str             # Expected hash after write
    initiated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    completed_at: Optional[datetime] = None  # null = in progress
    status: WILStatus = WILStatus.PENDING
    last_completed_store: Optional[str] = None
    failure_reason: Optional[str] = None

    @field_validator("stores_involved", mode="before")
    @classmethod
    def _stores_name_a_role(cls, stores):
        values = [getattr(s, "value", s) for s in (stores or [])]
        for v in values:
            store_role_of(v)  # refuses anything that is neither a role nor a retained 4.x value
        return values

    @field_validator("last_completed_store", mode="before")
    @classmethod
    def _last_store_names_a_role(cls, store):
        if store is None:
            return None
        value = getattr(store, "value", store)
        store_role_of(value)
        return value


# ── Write Ordering Invariant ─────────────────────────────────────────────────

WRITE_ORDER: list[StoreRole] = [
    StoreRole.DURABLE_CONTENT,          # 1st: highest durability
    StoreRole.AUTHORITATIVE_STRUCTURAL, # 2nd: the structural record
    StoreRole.EPHEMERAL_COORDINATOR,    # 3rd: coordination state
    StoreRole.SEMANTIC_INDEX,           # 4th: degradation always recoverable
]

# Semantic-index degradation is recoverable by construction: the record is
# reconstructable from the structural store and the durable content store.
# Search is degraded but identity is intact.
SEMANTIC_INDEX_DEGRADATION_RECOVERABLE = True  # Invariant — must remain True


def enforce_write_order(stores: list) -> list:
    """The given stores in mandatory write order (§12.1). Each store is a role,
    or a value ``store_role_of`` resolves to one (a deployment's own provider
    enum whose values are the retained 4.x names, for instance); the input
    values are returned, ordered by their roles. Raises ASTPGovernanceError
    for a value that names no role."""
    try:
        roles = {s: store_role_of(s) for s in stores}
    except ValueError as e:
        raise ASTPGovernanceError(f"Write ordering violation: {e}. All stores must name a role in WRITE_ORDER.") from e
    return sorted(stores, key=lambda s: WRITE_ORDER.index(roles[s]))


# ── Provisional State Guard ──────────────────────────────────────────────────
# Invariant 3 (SPEC §12.1): provisional state never enters persistent storage.

PROVISIONAL_PERSISTENT_STORES = {
    StoreRole.DURABLE_CONTENT, StoreRole.AUTHORITATIVE_STRUCTURAL, StoreRole.SEMANTIC_INDEX,
}


def enforce_provisional_state_guard(
    is_provisional: bool,
    target_store,
    data_description: str,
) -> None:
    """
    Raises ASTPGovernanceError if provisional data is written to a persistent store.
    Provisional data may only live in the ephemeral coordinator during the
    provisional window. ``target_store`` is a role or a value ``store_role_of`` resolves.
    """
    role = store_role_of(target_store)
    if is_provisional and role in PROVISIONAL_PERSISTENT_STORES:
        raise ASTPGovernanceError(
            f"Provisional state invariant violation: Attempted to write provisional "
            f"data '{data_description}' to persistent store '{role.value}'. "
            f"Provisional state may only exist in the ephemeral coordinator during the "
            f"provisional window (max {PROVISIONAL_WINDOW_HOURS}h). "
            f"Data must be fully crystallized before writing to {role.value}."
        )
