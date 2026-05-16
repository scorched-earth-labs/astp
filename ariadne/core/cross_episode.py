"""
Cross-Episode Linking — Amendment v2.0 schema primitives.

Defines the `EpisodeLink` node and its supporting enums, governance, and
content-hash computation. This is the protocol-level type module — adapter
modules import from here, never the reverse.

The link types and their mutual-exclusivity rules are per Amendment v2.0 §3.
The content-hash preimage excludes `quarantine_resolved_at` and
`quarantine_resolution` per Amendment v2.0 §2 — resolution fields record
lifecycle events after link creation and would otherwise invalidate the
hash on every quarantine close. The audit log is the authoritative record
of quarantine resolutions; the content hash commits to the link as
asserted, not as later resolved.

This module does NOT modify existing protocol content-hash functions. It
introduces a new hash function (`compute_episode_link_content_hash`) for a
new node type. The existing `sha3_256` primitive is reused.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from ariadne.core.schema import sha3_256


# ── Enums ────────────────────────────────────────────────────────────────────


class LinkType(str, Enum):
    """Cross-episode link vocabulary — Amendment v2.0 §3.

    Mutual exclusivity (a single (source, target) pair cannot carry both):
      - CONTINUES_FROM ⊕ SUPERSEDES
      - CONTINUES_FROM ⊕ BRANCHES_FROM

    SUPERSEDES and BRANCHES_FROM are NOT mutually exclusive with each other.
    All other link types are compatible with all others.
    """

    CONTINUES_FROM = "CONTINUES_FROM"     # Direct continuation of prior episode
    SUPERSEDES = "SUPERSEDES"             # This episode replaces target
    BRANCHES_FROM = "BRANCHES_FROM"       # Divergent thread from target
    INFORMED_BY = "INFORMED_BY"           # Prior knowledge dependency, not continuation
    REFERENCES = "REFERENCES"             # Audit-only citation; non-loading on resumption
    SPAWNED_FROM = "SPAWNED_FROM"         # Task/sub-episode origin
    MERGED_INTO = "MERGED_INTO"           # Convergence record
    PEER_REVIEWED_BY = "PEER_REVIEWED_BY" # Cross-agent review relationship


class LinkHealthState(str, Enum):
    """Lifecycle state of a cross-episode link — Amendment v2.0 §6.

    State transitions are specified in the amendment §6 state machine. The
    QUARANTINED state requires explicit human review for exit; there is no
    automatic transition to BROKEN.
    """

    VALID = "VALID"               # Target exists and version delta within tolerance
    STALE = "STALE"               # Target has advanced minor/patch since link creation
    FROZEN = "FROZEN"             # Target is crystallized; link permanently anchored
    BROKEN = "BROKEN"             # Target unreachable or deleted
    QUARANTINED = "QUARANTINED"   # Flagged for integrity review; excluded from active traversal


class QuarantineResolution(str, Enum):
    """Terminal resolution of a quarantined link — Amendment v2.0 §11.3.1.

    Set when a quarantine exits. CONFIRMED returns the link to VALID;
    DISSOLVED transitions to BROKEN; ESCALATED keeps the link in
    QUARANTINED but signals that the TTL was exceeded and human review is
    overdue (the QUARANTINE_ESCALATED audit event also fires — §11.3.3).
    """

    CONFIRMED = "CONFIRMED"       # Link validated by human review; → VALID
    DISSOLVED = "DISSOLVED"       # Link invalidated by human review; → BROKEN
    ESCALATED = "ESCALATED"       # TTL exceeded; remains QUARANTINED; human review required


class SignalType(str, Enum):
    """Inference signal types — Amendment v2.0 §4.

    The protocol enumerates the signal types that may contribute to a
    candidate's composite score. The combination (weights, composite
    formula) is implementation-side per §12 behavioral tier. The signals
    themselves are recorded for audit-the-decision per §12.2.
    """

    SEMANTIC_SIMILARITY = "SEMANTIC_SIMILARITY"
    PARTICIPANT_OVERLAP = "PARTICIPANT_OVERLAP"
    TEMPORAL_PROXIMITY = "TEMPORAL_PROXIMITY"
    EXPLICIT_REFERENCE = "EXPLICIT_REFERENCE"
    SHARED_ARTIFACT = "SHARED_ARTIFACT"


# ── Models ───────────────────────────────────────────────────────────────────


class Signal(BaseModel):
    """A single inference signal contributing to a candidate's composite score.

    Recorded on every inferred `EpisodeLink` in the `inference_signals`
    list. The protocol does not mandate how signals are combined (§12
    behavioral tier); it mandates that all contributing signals are
    recorded with their weights and values.
    """

    signal_type: SignalType
    signal_weight: float  # weight applied in composite score computation
    signal_value: float   # raw signal value before weighting
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EpisodeLink(BaseModel):
    """A typed cross-episode link — Amendment v2.0 §2.

    Identity fields (link_id, source_episode, target_episode, created_at,
    created_by) are immutable. Inference-provenance fields are immutable
    once set. Health-state fields are mutable; quarantine-resolution
    fields are mutable and explicitly excluded from `content_hash`.
    """

    # Identity — immutable
    link_id: UUID = Field(default_factory=uuid4)
    source_episode: UUID
    target_episode: UUID
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str  # agent_id

    # Semantic characterization — Gap 1
    link_type: LinkType
    link_strength: float = Field(ge=0.0, le=1.0)  # 0.0 = no relationship, 1.0 = near-identical
    is_inferred: bool                              # true = system-generated; false = human-asserted

    # Inference provenance — immutable once set
    inference_signals: list[Signal] = Field(default_factory=list)
    inference_threshold: Optional[float] = None    # value of DISCOVERY_THRESHOLD at inference time
    retroactive: bool = False                      # true = link created after source crystallization

    # Health state — mutable
    health_state: LinkHealthState = LinkHealthState.VALID
    health_checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_version: Optional[str] = None           # SemVer of source at link creation
    target_version: Optional[str] = None           # SemVer of target at link creation

    # Quarantine — Gap 4; resolved_at + resolution EXCLUDED from content_hash
    quarantine_reason: Optional[str] = None
    quarantined_at: Optional[datetime] = None
    quarantine_resolved_at: Optional[datetime] = None
    quarantine_resolution: Optional[QuarantineResolution] = None

    # Integrity
    content_hash: Optional[str] = None  # SHA3-256 of canonical preimage (see compute_episode_link_content_hash)


# ── Governance ───────────────────────────────────────────────────────────────


# Per Amendment v2.0 §3 mutual exclusivity table. Each entry is an unordered
# pair {LinkType, LinkType} that cannot both exist on a single (source,
# target) pair. Checked by enforce_link_mutual_exclusivity.
_MUTUALLY_EXCLUSIVE_LINK_TYPES: frozenset[frozenset[LinkType]] = frozenset({
    frozenset({LinkType.CONTINUES_FROM, LinkType.SUPERSEDES}),
    frozenset({LinkType.CONTINUES_FROM, LinkType.BRANCHES_FROM}),
})


class LinkGovernanceError(Exception):
    """Raised when a link assertion violates governance rules from §3."""


def enforce_link_mutual_exclusivity(
    new_link_type: LinkType,
    existing_link_types_for_pair: list[LinkType],
) -> None:
    """Check whether `new_link_type` can coexist with existing types on the
    same (source, target) pair, per Amendment v2.0 §3.

    Raises LinkGovernanceError on violation. Returns None on success.

    The caller is responsible for scoping `existing_link_types_for_pair` to
    links sharing the same (source_episode, target_episode) pair as the
    new link being asserted.
    """
    for existing in existing_link_types_for_pair:
        pair = frozenset({new_link_type, existing})
        if pair in _MUTUALLY_EXCLUSIVE_LINK_TYPES:
            raise LinkGovernanceError(
                f"Link type {new_link_type.value} cannot coexist with "
                f"{existing.value} on the same (source, target) pair "
                f"(Amendment v2.0 §3 mutual exclusivity)."
            )


# ── Content hash ─────────────────────────────────────────────────────────────


# Fields included in the EpisodeLink content_hash preimage, in canonical
# order. Mutable health-state fields are included so that drift detection
# can be cryptographically tied to the link's anchor state at write time.
# `quarantine_resolved_at` and `quarantine_resolution` are EXCLUDED per
# Amendment v2.0 §2 hash preimage note.
_HASH_PREIMAGE_FIELDS: tuple[str, ...] = (
    "link_id",
    "source_episode",
    "target_episode",
    "created_at",
    "created_by",
    "link_type",
    "link_strength",
    "is_inferred",
    "inference_signals",
    "inference_threshold",
    "retroactive",
    "health_state",
    "health_checked_at",
    "source_version",
    "target_version",
    "quarantine_reason",
    "quarantined_at",
)


def _canonical_value(value):
    """Recursive canonical-form serialization helper.

    Datetimes → ISO 8601 with UTC offset. UUIDs → hex string. Enums →
    .value. None → null. Floats → repr (no precision loss). Lists →
    recurse. Pydantic models → dict then recurse.
    """
    if value is None:
        return None
    if isinstance(value, (UUID,)):
        return str(value)
    if isinstance(value, datetime):
        # Always normalize to UTC for hash stability.
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bool):
        return value  # JSON-encodes as true/false
    if isinstance(value, (int,)):
        return value
    if isinstance(value, float):
        # repr() produces a round-trippable representation. Avoids platform
        # float→string differences that would break hash stability.
        return repr(value)
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return [_canonical_value(v) for v in value]
    if isinstance(value, BaseModel):
        return {k: _canonical_value(v) for k, v in value.model_dump().items()}
    if isinstance(value, dict):
        return {k: _canonical_value(v) for k, v in value.items()}
    raise TypeError(f"Unhashable value type {type(value).__name__}: {value!r}")


def compute_episode_link_content_hash(link: EpisodeLink) -> str:
    """SHA3-256 of the EpisodeLink canonical preimage.

    Preimage is a JSON object with keys in _HASH_PREIMAGE_FIELDS order and
    canonically serialized values. JSON serialization uses sort_keys=False
    (we already control the field order) and separators=(',', ':') (no
    whitespace). The preimage is encoded as UTF-8 before hashing.

    Excludes `quarantine_resolved_at` and `quarantine_resolution` per
    Amendment v2.0 §2 — these are mutable lifecycle annotations whose
    integrity lives in the audit log, not the content hash.
    """
    preimage: dict = {}
    for field_name in _HASH_PREIMAGE_FIELDS:
        preimage[field_name] = _canonical_value(getattr(link, field_name))
    # sort_keys=False — we use the explicit _HASH_PREIMAGE_FIELDS ordering.
    serialized = json.dumps(preimage, sort_keys=False, separators=(",", ":"), ensure_ascii=False)
    return sha3_256(serialized.encode("utf-8"))


def stamp_content_hash(link: EpisodeLink) -> EpisodeLink:
    """Compute and set `content_hash` on the given link. Returns the same
    instance for chaining. Idempotent: re-stamping with unchanged fields
    yields the same hash; changes to mutable fields (e.g., health_state)
    update the hash on re-stamp."""
    link.content_hash = compute_episode_link_content_hash(link)
    return link
