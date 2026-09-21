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
Cross-Episode Linking — SPEC §20 Part I schema primitives.

Defines the `EpisodeLink` node and its supporting enums, governance, and
content-hash computation. This is the protocol-level type module — adapter
modules import from here, never the reverse.

The link types and their mutual-exclusivity rules are per SPEC §20 →3.
The content-hash preimage excludes `quarantine_resolved_at` and
`quarantine_resolution` per SPEC §20 →2 — resolution fields record
lifecycle events after link creation and would otherwise invalidate the
hash on every quarantine close. The audit log is the authoritative record
of quarantine resolutions; the content hash commits to the link as
asserted, not as later resolved.

This module does NOT modify existing protocol content-hash functions. It
introduces a new hash function (`compute_episode_link_content_hash`) for a
new node type. The existing `sha3_256` primitive is reused.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from astp.adapters.base import as_structural_store
from astp.core.hash_canonical import hash_preimage


# ── Enums ────────────────────────────────────────────────────────────────────


class LinkType(str, Enum):
    """Cross-episode link vocabulary — SPEC §20 →3.

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
    """Lifecycle state of a cross-episode link — SPEC §20 →6.

    State transitions are specified in the SPEC §20 →6 state machine. The
    QUARANTINED state requires explicit human review for exit; there is no
    automatic transition to BROKEN.
    """

    VALID = "VALID"               # Target exists and version delta within tolerance
    STALE = "STALE"               # Target has advanced minor/patch since link creation
    FROZEN = "FROZEN"             # Target is crystallized; link permanently anchored
    BROKEN = "BROKEN"             # Target unreachable or deleted
    QUARANTINED = "QUARANTINED"   # Flagged for integrity review; excluded from active traversal


class QuarantineResolution(str, Enum):
    """Terminal resolution of a quarantined link — SPEC §20 →11.3.1.

    Set when a quarantine exits. CONFIRMED returns the link to VALID;
    DISSOLVED transitions to BROKEN; ESCALATED keeps the link in
    QUARANTINED but signals that the TTL was exceeded and human review is
    overdue (the QUARANTINE_ESCALATED audit event also fires — §11.3.3).
    """

    CONFIRMED = "CONFIRMED"       # Link validated by human review; → VALID
    DISSOLVED = "DISSOLVED"       # Link invalidated by human review; → BROKEN
    ESCALATED = "ESCALATED"       # TTL exceeded; remains QUARANTINED; human review required


class SignalType(str, Enum):
    """Inference signal types — SPEC §20 →4.

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
    """A typed cross-episode link — SPEC §20 →2.

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

    # Semantic characterization — SPEC §20 →2
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

    # Quarantine — SPEC §20 →2; resolved_at + resolution EXCLUDED from content_hash
    quarantine_reason: Optional[str] = None
    quarantined_at: Optional[datetime] = None
    quarantine_resolved_at: Optional[datetime] = None
    quarantine_resolution: Optional[QuarantineResolution] = None

    # Integrity
    # Each end's Episode root when that end was sealed at link creation, else None
    # (SPEC §20 →2, 5.0.0). A sealed end with None is nonconformant; the writer
    # fills these from the graph before stamping.
    source_episode_root: Optional[str] = None
    target_episode_root: Optional[str] = None

    content_hash: Optional[str] = None  # EPISODE_LINK:v2: (see compute_episode_link_content_hash)


# ── Governance ───────────────────────────────────────────────────────────────


# Per SPEC §20 →3 mutual exclusivity table. Each entry is an unordered
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
    same (source, target) pair, per SPEC §20 →3.

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
                f"(SPEC §20 →3 mutual exclusivity)."
            )


# ── Content hash ─────────────────────────────────────────────────────────────


# Fields included in the EpisodeLink content_hash preimage, in canonical
# order. Mutable health-state fields are included so that drift detection
# can be cryptographically tied to the link's anchor state at write time.
# `quarantine_resolved_at` and `quarantine_resolution` are EXCLUDED per
# SPEC §20 →2 hash preimage note.
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


def compute_episode_link_content_hash(link: EpisodeLink) -> str:
    """`EPISODE_LINK:v2:` (SPEC §20 →2): the two Episode identifiers, each end's
    Episode root when that end was sealed at link creation, the type, exact
    strength, whether inferred, every inference signal (each `LINK_SIGNAL:v2:`)
    in the order recorded, the threshold, the retroactive flag and the version
    strings. Health, quarantine and `created_by` are lifecycle and provenance —
    the audit chain's — and are not bound, so the hash is fixed at creation."""
    from astp.core.content_hash_v2 import compute_episode_link_hash_v2, compute_link_signal_hash_v2
    signal_hashes = [compute_link_signal_hash_v2(sig.signal_type.value, sig.signal_weight, sig.signal_value, sig.computed_at)
                     for sig in link.inference_signals]
    return compute_episode_link_hash_v2(
        link.link_id, link.source_episode, link.target_episode, link.source_episode_root, link.target_episode_root,
        link.created_at, link.link_type.value, link.link_strength, link.is_inferred, signal_hashes,
        link.inference_threshold, link.retroactive, link.source_version, link.target_version,
    )


def compute_episode_link_content_hash_4x(link: EpisodeLink) -> str:
    """The 4.x preimage (`_HASH_PREIMAGE_FIELDS`, canonical JSON) — retained only
    to verify links written before 5.0.0. It bound the health and quarantine
    fields, so it changed whenever a link's health did."""
    return hash_preimage(link, _HASH_PREIMAGE_FIELDS)


def stamp_content_hash(link: EpisodeLink) -> EpisodeLink:
    """Compute and set `content_hash` on the given link (`EPISODE_LINK:v2:`).
    Returns the same instance for chaining. The hash is a function of the
    link's immutable claim only: re-stamping after a health change yields the
    same hash. Fill `source_episode_root` / `target_episode_root` first when the
    ends are sealed — the writer does this from the graph."""
    link.content_hash = compute_episode_link_content_hash(link)
    return link


# ── Audit delta payloads ─────────────────────────────────────────────────────


class LinkAcceptedDelta(BaseModel):
    """Forward + reverse delta for `CognitiveDeltaType.LINK_ACCEPTED`.

    Carried on the AuditRecord for every cross-episode link assertion. The
    reverse delta records what to do to undo: delete the link node and the
    LINKED_TO edge by link_id. Reversal does NOT re-emit a corresponding
    `LINK_REJECTED` — the audit chain is append-only; reversal is a new
    forward event of its own.
    """

    # Forward delta (what happened)
    link_id: str
    source_episode: str
    target_episode: str
    link_type: str               # LinkType.value
    link_strength: float
    is_inferred: bool
    retroactive: bool

    # Reverse delta (how to undo)
    reverse_delete_link_id: str


class LinkProposedDelta(BaseModel):
    """Forward delta for `CognitiveDeltaType.LINK_PROPOSED` (SPEC §20 →5).

    Fires when discovery surfaces a candidate at or above
    DISCOVERY_THRESHOLD but below AUTO_ACCEPT_THRESHOLD — i.e., the
    system thinks this link is likely correct but wants human review
    before committing.

    The audit-the-decision pattern (§12.2): record full inference
    signals + thresholds in effect at proposal time so the candidate
    is interpretable later (post-hoc calibration of threshold values).

    No reverse delta — proposals are append-only. Rejection of a
    proposed candidate emits a separate LINK_REJECTED event; acceptance
    emits LINK_ACCEPTED + creates the EpisodeLink. The proposal record
    survives in the audit log either way.
    """

    source_episode: str
    target_episode: str
    proposed_link_type: str              # LinkType.value
    composite_score: float               # final score that crossed DISCOVERY_THRESHOLD
    inference_signals: list[Signal]      # full signal breakdown for audit-the-decision
    discovery_threshold_at_creation: float
    auto_accept_threshold_at_creation: float


class LinkRejectedDelta(BaseModel):
    """Forward delta for `CognitiveDeltaType.LINK_REJECTED`.

    Fires when a human rejects a candidate that was previously surfaced
    via LINK_PROPOSED. Carries the original audit_event_id of the
    proposal so the calibration loop can correlate proposed-and-rejected
    candidates and tune scoring weights / thresholds.

    Per the §5 RejectionReason enum, the reason categorizes the
    rejection so the calibration signal has structure.
    """

    proposed_audit_event_id: str  # the LINK_PROPOSED audit_id this rejects
    source_episode: str
    target_episode: str
    proposed_link_type: str
    rejecting_agent: str
    rejection_reason: str         # RejectionReason value (see below)
    rejection_note: Optional[str] = None  # optional free-text


class CandidateRejectedDelta(BaseModel):
    """Forward delta for `CognitiveDeltaType.CANDIDATE_REJECTED` (SPEC §20 →5).

    Fires when discovery scores a candidate strictly BELOW
    DISCOVERY_THRESHOLD. The candidate is NOT surfaced for human review;
    the event exists purely for calibration — implementations can analyze
    rejected-at-score-X patterns to tune DISCOVERY_THRESHOLD.

    Carries full signals to make retrospective "would this candidate have
    been useful if our threshold were lower" analysis possible.
    """

    source_episode: str
    target_episode: str
    proposed_link_type: str          # the link_type that would have been used
    composite_score: float
    inference_signals: list[Signal]
    discovery_threshold_at_creation: float


class RejectionReason(str, Enum):
    """Structured rejection reasons per SPEC §20 →5.

    Used by LinkRejectedDelta — implementations should pick the most
    specific value. NOT_RELATED and LOW_CONFIDENCE are the calibration-
    actionable ones (signal that the threshold is too low or the signal
    weights are off).
    """

    LOW_CONFIDENCE = "LOW_CONFIDENCE"               # Score above threshold but relationship not meaningful
    WRONG_RELATIONSHIP_TYPE = "WRONG_RELATIONSHIP_TYPE"  # Relationship exists but link_type incorrect
    NOT_RELATED = "NOT_RELATED"                     # Episodes are not meaningfully related
    DUPLICATE_OF_EXISTING = "DUPLICATE_OF_EXISTING"  # Already captured by another link


# ── Operation layer: assertion + audit emission ─────────────────────────────


def assert_episode_link(
    store,
    link: EpisodeLink,
    *,
    session_id: Optional[str] = None,
    explicit_reason: Optional[str] = None,
) -> EpisodeLink:
    """Operation-layer entry point for asserting a cross-episode link.

    Wraps the low-level `StructuralStore.write_episode_link` adapter with audit-chain
    emission. This is the function the server endpoint and Faculty code
    paths should call — they should NOT call `StructuralStore.write_episode_link`
    directly, because doing so bypasses the audit chain.

    Args:
        store: a StructuralStore (a raw driver of the reference store is accepted for one release).
        link: EpisodeLink to assert. `created_by` must be set (audit
            chain requires an actor). `content_hash` will be stamped if
            not already present.
        session_id: Optional session/context identifier for the audit
            record. Defaults to a synthetic `link-<short_id>` if omitted —
            matches the BFM pattern (`branch-<branch_id>`).
        explicit_reason: Optional free-text rationale captured on the
            AuditRecord. For Phase 1 (manual assertion) this is usually
            the user's reason from the API call.

    Returns the link with `content_hash` populated. The link is now
    persisted in the store and the audit chain has advanced by one record.

    Phase 1 scope: this function emits LINK_ACCEPTED only — every
    successful assertion is treated as an acceptance event. Phase 2's
    discovery flow will introduce LINK_PROPOSED + LINK_REJECTED emissions
    via separate operation functions.
    """
    # Deferred imports — adapter + audit chain primitives. Done inline so
    # the operation function can be referenced without pulling the full
    # adapter graph in environments that don't need it (e.g., schema
    # validation tools, type-only imports).
    store = as_structural_store(store)
    import json as _json
    from astp.core.audit_chain import next_delta_sequence, prior_audit_hash
    from astp.core.branching import (
        AuditRecord,
        CognitiveDeltaType,
        TriggerType,
        compute_audit_record_hash,
    )

    # 1. Write the link node + edge through the adapter. The adapter
    # enforces endpoint existence + mutual-exclusivity governance and
    # stamps content_hash if not already set.
    store.write_episode_link(link)

    # 2. Build the forward + reverse deltas for the audit record.
    delta = LinkAcceptedDelta(
        link_id=str(link.link_id),
        source_episode=str(link.source_episode),
        target_episode=str(link.target_episode),
        link_type=link.link_type.value,
        link_strength=link.link_strength,
        is_inferred=link.is_inferred,
        retroactive=link.retroactive,
        reverse_delete_link_id=str(link.link_id),
    )
    forward_delta_dict = delta.model_dump()
    reverse_delta_dict = {"operation": "delete_episode_link", "link_id": str(link.link_id)}

    # 3. Acquire delta_sequence + prior hash from the audit chain for the
    # source episode. Source episode is the audit anchor — the episode
    # "asserting" the relationship owns the audit chain entry.
    src_episode_id = str(link.source_episode)
    delta_sequence = next_delta_sequence(store, src_episode_id)
    prior_hash = prior_audit_hash(store, src_episode_id)

    # 4. Build and hash the AuditRecord, then write it.
    short_link_id = str(link.link_id)[:8]
    audit = AuditRecord(
        delta_sequence=delta_sequence,
        agent_id=link.created_by,
        session_id=session_id or f"link-{short_link_id}",
        delta_type=CognitiveDeltaType.LINK_ACCEPTED,
        forward_delta=forward_delta_dict,
        reverse_delta=reverse_delta_dict,
        affected_nodes=[str(link.link_id), src_episode_id, str(link.target_episode)],
        # Phase 1 manual assertion is always human-explicit. Phase 2's
        # discovery flow will switch this to AGENT_DETECTED when LINK_PROPOSED
        # fires from an automated candidate sweep.
        trigger_context=TriggerType.HUMAN_EXPLICIT,
        explicit_reason=explicit_reason,
        prior_audit_hash=prior_hash,
        caught_by="HUMAN",
        episode_id=src_episode_id,
    )
    audit.record_hash = compute_audit_record_hash(
        str(audit.audit_id),
        audit.delta_sequence,
        audit.delta_type.value,
        audit.agent_id,
        audit.wall_clock_time.isoformat(),
        _json.dumps(forward_delta_dict, default=str, sort_keys=True),
        prior_hash,
    )
    store.write_audit_record(audit)

    return link


# ── Phase 2: Discovery operation layer ──────────────────────────────────────
#
# These operations emit audit-only events. None create EpisodeLink nodes.
# They feed the calibration loop and (for LINK_PROPOSED) the human-review
# queue. See SPEC §20 →5 and →12.2 (audit-the-decision pattern).


def propose_link_candidate(
    store,
    *,
    source_episode: str,
    target_episode: str,
    proposed_link_type: LinkType,
    composite_score: float,
    inference_signals: list[Signal],
    discovery_threshold: float,
    auto_accept_threshold: float,
    proposing_agent: str,
    session_id: Optional[str] = None,
) -> str:
    """Emit a `LINK_PROPOSED` audit event for human review.

    Used by the Phase 2 discovery flow when a candidate scores at or above
    `discovery_threshold` but strictly below `auto_accept_threshold`.
    The candidate is surfaced for human review; no EpisodeLink is created
    yet. Acceptance flows through `assert_episode_link` (which emits
    LINK_ACCEPTED + creates the link). Rejection flows through
    `record_link_rejection` (which references this proposal's audit_id).

    The audit-the-decision pattern (§12.2): full signal breakdown +
    threshold values at proposal time are recorded so the calibration
    loop can analyze "what scored where" without re-running the model.

    Returns the audit_id of the LINK_PROPOSED record so the caller can
    surface it in the review queue and later correlate the
    accept/reject decision back to the proposal.
    """
    store = as_structural_store(store)
    import json as _json
    from astp.core.audit_chain import next_delta_sequence, prior_audit_hash
    from astp.core.branching import (
        AuditRecord,
        CognitiveDeltaType,
        TriggerType,
        compute_audit_record_hash,
    )

    delta = LinkProposedDelta(
        source_episode=source_episode,
        target_episode=target_episode,
        proposed_link_type=proposed_link_type.value,
        composite_score=composite_score,
        inference_signals=inference_signals,
        discovery_threshold_at_creation=discovery_threshold,
        auto_accept_threshold_at_creation=auto_accept_threshold,
    )
    forward_delta_dict = delta.model_dump()
    # Proposals are append-only — rejection is a separate forward event.
    reverse_delta_dict = {"operation": "noop", "reason": "proposals are append-only"}

    delta_sequence = next_delta_sequence(store, source_episode)
    prior_hash = prior_audit_hash(store, source_episode)

    audit = AuditRecord(
        delta_sequence=delta_sequence,
        agent_id=proposing_agent,
        session_id=session_id or f"propose-{source_episode[:8]}",
        delta_type=CognitiveDeltaType.LINK_PROPOSED,
        forward_delta=forward_delta_dict,
        reverse_delta=reverse_delta_dict,
        affected_nodes=[source_episode, target_episode],
        trigger_context=TriggerType.AGENT_DETECTED,
        explicit_reason=None,
        prior_audit_hash=prior_hash,
        caught_by="AGENT",
        episode_id=source_episode,
    )
    audit.record_hash = compute_audit_record_hash(
        str(audit.audit_id),
        audit.delta_sequence,
        audit.delta_type.value,
        audit.agent_id,
        audit.wall_clock_time.isoformat(),
        _json.dumps(forward_delta_dict, default=str, sort_keys=True),
        prior_hash,
    )
    store.write_audit_record(audit)

    return str(audit.audit_id)


def record_candidate_rejection(
    store,
    *,
    source_episode: str,
    target_episode: str,
    proposed_link_type: LinkType,
    composite_score: float,
    inference_signals: list[Signal],
    discovery_threshold: float,
    detecting_agent: str,
    session_id: Optional[str] = None,
) -> str:
    """Emit a `CANDIDATE_REJECTED` audit event for calibration.

    Used by the Phase 2 discovery flow when a candidate scores strictly
    BELOW `discovery_threshold`. The candidate is not surfaced for
    review — this event exists purely so the calibration loop can analyze
    sub-threshold scoring patterns and tune DISCOVERY_THRESHOLD over time.

    Per §1, high-volume CANDIDATE_REJECTED events at scores just below
    threshold are the primary signal for lowering the threshold.

    Returns the audit_id of the CANDIDATE_REJECTED record.
    """
    store = as_structural_store(store)
    import json as _json
    from astp.core.audit_chain import next_delta_sequence, prior_audit_hash
    from astp.core.branching import (
        AuditRecord,
        CognitiveDeltaType,
        TriggerType,
        compute_audit_record_hash,
    )

    delta = CandidateRejectedDelta(
        source_episode=source_episode,
        target_episode=target_episode,
        proposed_link_type=proposed_link_type.value,
        composite_score=composite_score,
        inference_signals=inference_signals,
        discovery_threshold_at_creation=discovery_threshold,
    )
    forward_delta_dict = delta.model_dump()
    reverse_delta_dict = {"operation": "noop", "reason": "candidate rejections are append-only"}

    delta_sequence = next_delta_sequence(store, source_episode)
    prior_hash = prior_audit_hash(store, source_episode)

    audit = AuditRecord(
        delta_sequence=delta_sequence,
        agent_id=detecting_agent,
        session_id=session_id or f"reject-{source_episode[:8]}",
        delta_type=CognitiveDeltaType.CANDIDATE_REJECTED,
        forward_delta=forward_delta_dict,
        reverse_delta=reverse_delta_dict,
        affected_nodes=[source_episode, target_episode],
        trigger_context=TriggerType.AGENT_DETECTED,
        explicit_reason=None,
        prior_audit_hash=prior_hash,
        caught_by="AGENT",
        episode_id=source_episode,
    )
    audit.record_hash = compute_audit_record_hash(
        str(audit.audit_id),
        audit.delta_sequence,
        audit.delta_type.value,
        audit.agent_id,
        audit.wall_clock_time.isoformat(),
        _json.dumps(forward_delta_dict, default=str, sort_keys=True),
        prior_hash,
    )
    store.write_audit_record(audit)

    return str(audit.audit_id)


def record_link_rejection(
    store,
    *,
    proposed_audit_event_id: str,
    source_episode: str,
    target_episode: str,
    proposed_link_type: LinkType,
    rejecting_agent: str,
    rejection_reason: RejectionReason,
    rejection_note: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    """Emit a `LINK_REJECTED` audit event when a human rejects a proposed candidate.

    Carries `proposed_audit_event_id` so the calibration loop can pair
    LINK_PROPOSED → LINK_REJECTED events and learn from the score-at-
    proposal vs. human-judgment delta. The `rejection_reason` is the
    structured signal — NOT_RELATED at a high composite_score is the
    strongest evidence that the scoring weights need adjustment.

    Returns the audit_id of the LINK_REJECTED record.
    """
    store = as_structural_store(store)
    import json as _json
    from astp.core.audit_chain import next_delta_sequence, prior_audit_hash
    from astp.core.branching import (
        AuditRecord,
        CognitiveDeltaType,
        TriggerType,
        compute_audit_record_hash,
    )

    delta = LinkRejectedDelta(
        proposed_audit_event_id=proposed_audit_event_id,
        source_episode=source_episode,
        target_episode=target_episode,
        proposed_link_type=proposed_link_type.value,
        rejecting_agent=rejecting_agent,
        rejection_reason=rejection_reason.value,
        rejection_note=rejection_note,
    )
    forward_delta_dict = delta.model_dump()
    reverse_delta_dict = {"operation": "noop", "reason": "link rejections are append-only"}

    delta_sequence = next_delta_sequence(store, source_episode)
    prior_hash = prior_audit_hash(store, source_episode)

    audit = AuditRecord(
        delta_sequence=delta_sequence,
        agent_id=rejecting_agent,
        session_id=session_id or f"reject-{source_episode[:8]}",
        delta_type=CognitiveDeltaType.LINK_REJECTED,
        forward_delta=forward_delta_dict,
        reverse_delta=reverse_delta_dict,
        affected_nodes=[source_episode, target_episode],
        trigger_context=TriggerType.HUMAN_EXPLICIT,
        explicit_reason=rejection_note,
        prior_audit_hash=prior_hash,
        caught_by="HUMAN",
        episode_id=source_episode,
    )
    audit.record_hash = compute_audit_record_hash(
        str(audit.audit_id),
        audit.delta_sequence,
        audit.delta_type.value,
        audit.agent_id,
        audit.wall_clock_time.isoformat(),
        _json.dumps(forward_delta_dict, default=str, sort_keys=True),
        prior_hash,
    )
    store.write_audit_record(audit)

    return str(audit.audit_id)


# Audit chain helpers (next_delta_sequence + prior_audit_hash) live in
# astp.core.audit_chain — shared across all operation-layer modules
# that advance the audit log.
