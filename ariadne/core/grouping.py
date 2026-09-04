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
Episode Grouping Interface — Amendment v2.0 §7-§9 schema primitives.

Defines `MembershipRecord` (the protocol's owned artifact — the assertion
that an Episode belongs to a Grouping) and `ConformanceDeclaration` (a
native grouping implementation's registration as conforming to the
EpisodeGrouping behavioral interface).

The amendment's design principle: a Grouping itself may live OUTSIDE
Ariadne's structural layer (e.g., Claude's native Project store, Notion's
Database, SEL/Thermyt's Collection). The protocol cannot fully verify or
control that native construct. What the protocol DOES own is the
`MembershipRecord` — the verifiable assertion that an Episode belongs to
a Grouping. **The grouping is opaque; the membership record is the
protocol's artifact.** See amendment §3 (Part II).

Both `MembershipRecord` and `ConformanceDeclaration` use the
immutable-with-succession pattern (Gap 6 and Gap 7 respectively). A
record/declaration is created once and never modified. State changes
produce a new record/declaration with `supersedes_record_id` /
`superseded_by` linking the chain. Forward pointers (`superseded_by_*`)
are EXCLUDED from content hashes per the §10 forward-pointer-exclusion
rule.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from ariadne.core.hash_canonical import hash_preimage


# ── Enums ────────────────────────────────────────────────────────────────────


class MembershipRole(str, Enum):
    """An Episode's role within a Grouping — Amendment v2.0 §7.

    Included in `MembershipRecord.content_hash` per Gap 6: role changes
    are role-content changes, not lifecycle annotations, so the hash
    commits to the role. Role changes therefore create a NEW
    MembershipRecord via succession; the prior record is preserved.
    """

    PRIMARY = "PRIMARY"          # Episode is centrally about this grouping's scope
    SUPPORTING = "SUPPORTING"    # Episode contributes substantively but isn't central
    REFERENCE = "REFERENCE"      # Episode is cited but not authored within this grouping
    ARCHIVED = "ARCHIVED"        # Episode is preserved in grouping for history; no longer active


class GroupingSystem(str, Enum):
    """Identifiers for known native grouping implementations. The protocol
    does not constrain implementations to register from this list — any
    string identifier is valid — but these are the conformance-declared
    reference implementations.

    Implementations register their conformance via `ConformanceDeclaration`.
    See amendment §4.1 for reference declarations.
    """

    # Reserved values; implementations may declare arbitrary group_system strings.
    ARIADNE_NATIVE = "ariadne_native"   # protocol's own internal grouping (if used)
    SEL_THERMYT_COLLECTION = "sel-thermyt:Collection"
    CLAUDE_PROJECT = "claude:Project"
    NOTION_DATABASE = "notion:Database"


# ── Capability ──────────────────────────────────────────────────────────────


class Capability(BaseModel):
    """A capability declared by a native grouping implementation in its
    ConformanceDeclaration. Open-ended by design — implementations declare
    what their native construct supports (e.g., archival, role
    distinction, ownership transfer). The protocol treats capabilities
    as opaque identifiers; consumers reason over them.
    """

    capability_id: str                 # e.g., "supports_archival", "supports_role_distinction"
    description: Optional[str] = None  # human-readable note


# ── MembershipRecord ────────────────────────────────────────────────────────


class MembershipRecord(BaseModel):
    """A typed Episode→Grouping membership assertion — Amendment v2.0 §7.

    Immutable after creation. Role changes are recorded by creating a new
    `MembershipRecord` with `supersedes_record_id` pointing to the prior
    record. The prior record's `superseded_by_record_id` is updated
    (forward-pointer-only; excluded from content_hash per §10). The
    active record for an (episode_id, group_id, group_system) tuple is
    the record with no `superseded_by_record_id`.
    """

    # Identity — immutable
    record_id: UUID = Field(default_factory=uuid4)
    episode_id: UUID
    group_id: str                       # External identifier (UUID or implementation-specific)
    group_system: str                   # e.g., "sel-thermyt:Collection", "claude:Project"
    asserted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    asserted_by: str                    # agent_id or user_id

    # Role — included in content_hash per Gap 6
    membership_role: MembershipRole

    # Succession — Gap 6
    # supersedes_record_id is INCLUDED in this record's content_hash
    # (this record's commitment to the chain history).
    supersedes_record_id: Optional[UUID] = None
    succession_reason: Optional[str] = None

    # Forward pointer — EXCLUDED from content_hash per §10
    superseded_by_record_id: Optional[UUID] = None

    # Integrity
    content_hash: Optional[str] = None


# ── ConformanceDeclaration ──────────────────────────────────────────────────


class ConformanceDeclaration(BaseModel):
    """Registration that a native grouping implementation conforms to the
    EpisodeGrouping behavioral interface — Amendment v2.0 §8.

    Versioned via SemVer (Gap 7). Version bump semantics:
      - Major (field rename, type change, removal, capability removal):
        new declaration via succession. Existing MembershipRecords retain
        reference to the old declaration version.
      - Minor (new optional field, new capability): new declaration with
        succession, but old MembershipRecords remain valid.
      - Patch (documentation, threshold default): same as minor.

    Implementations register ONE declaration per (group_system, version).
    The active declaration is the one with no `superseded_by`.
    """

    # Identity — immutable
    declaration_id: UUID = Field(default_factory=uuid4)
    group_id: str                       # The grouping this declaration covers
    group_system: str                   # The native construct type
    declared_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    declared_by: str                    # agent_id

    # Versioning — Gap 7
    declaration_version: str            # SemVer string (e.g., "1.0.0", "2.1.3")

    # Capabilities — included in content_hash
    capabilities: list[Capability] = Field(default_factory=list)

    # Forward pointer — EXCLUDED from content_hash per §10
    superseded_by: Optional[UUID] = None

    # Integrity
    declaration_hash: Optional[str] = None


# ── Governance ──────────────────────────────────────────────────────────────


class GroupingGovernanceError(Exception):
    """Raised when a grouping operation violates protocol governance."""


def enforce_semver_format(version: str) -> tuple[int, int, int]:
    """Parse + validate a SemVer string. Returns (major, minor, patch).

    Raises GroupingGovernanceError if the string is not a valid SemVer
    `major.minor.patch` triplet. We deliberately reject pre-release and
    build-metadata suffixes — those are out of scope for Phase 1 of
    grouping. Implementations needing them can extend in a future
    amendment.
    """
    parts = version.split(".")
    if len(parts) != 3:
        raise GroupingGovernanceError(
            f"declaration_version {version!r} must be a SemVer major.minor.patch triplet"
        )
    try:
        major, minor, patch = (int(p) for p in parts)
    except ValueError:
        raise GroupingGovernanceError(
            f"declaration_version {version!r} must contain only numeric parts"
        ) from None
    if major < 0 or minor < 0 or patch < 0:
        raise GroupingGovernanceError(
            f"declaration_version {version!r} parts must be non-negative"
        )
    return (major, minor, patch)


def classify_version_bump(old_version: str, new_version: str) -> str:
    """Classify a SemVer bump as 'major', 'minor', 'patch', or raise.

    Returns the bump kind. Raises GroupingGovernanceError if the new
    version is not strictly greater than the old, or if the bump skips
    levels (e.g., 1.0.0 → 1.2.0 is "minor" but 1.0.0 → 3.0.0 is also
    accepted as "major" — we don't enforce single-step bumps because
    real-world version histories often skip).
    """
    old = enforce_semver_format(old_version)
    new = enforce_semver_format(new_version)
    if new <= old:
        raise GroupingGovernanceError(
            f"new declaration_version {new_version} must be strictly greater than {old_version}"
        )
    if new[0] != old[0]:
        return "major"
    if new[1] != old[1]:
        return "minor"
    return "patch"


# ── Content hash — MembershipRecord ─────────────────────────────────────────


# Fields included in MembershipRecord content_hash, per Amendment v2.0 §7
# (note: Gap 6 explicitly includes membership_role; supersedes_record_id is
# included as the chain's commitment to its predecessor; superseded_by_*
# is EXCLUDED per the §10 forward-pointer-exclusion rule).
_MEMBERSHIP_HASH_PREIMAGE_FIELDS: tuple[str, ...] = (
    "record_id",
    "episode_id",
    "group_id",
    "group_system",
    "asserted_at",
    "asserted_by",
    "membership_role",
    "supersedes_record_id",
    "succession_reason",
)


# ── Content hash — ConformanceDeclaration ───────────────────────────────────


# Per Amendment v2.0 §8 + §10. Excludes superseded_by (forward pointer).
_DECLARATION_HASH_PREIMAGE_FIELDS: tuple[str, ...] = (
    "declaration_id",
    "group_id",
    "group_system",
    "declared_at",
    "declared_by",
    "declaration_version",
    "capabilities",
)


# Canonicalization rules + JSON serialization live in
# ariadne.core.hash_canonical. Both functions below delegate to the shared
# `hash_preimage` helper with their respective field tuples.


def compute_membership_record_content_hash(record: MembershipRecord) -> str:
    """SHA3-256 of the MembershipRecord canonical preimage — §7.

    Includes `membership_role` per Gap 6. Mutating role requires a new
    record (via succession), so the hash on the original record stays
    valid as the historical commitment to "this episode had this role
    at this time."

    Excludes `superseded_by_record_id` per §10 — that's a forward
    pointer set by a LATER operation; integrity is maintained through
    the audit log, not the hash.
    """
    return hash_preimage(record, _MEMBERSHIP_HASH_PREIMAGE_FIELDS)


def compute_conformance_declaration_hash(declaration: ConformanceDeclaration) -> str:
    """SHA3-256 of the ConformanceDeclaration canonical preimage — §8.

    Excludes `superseded_by` per §10 forward-pointer-exclusion. The
    declaration's hash commits to the declaration as authored;
    succession is recorded separately via the audit chain.
    """
    return hash_preimage(declaration, _DECLARATION_HASH_PREIMAGE_FIELDS)


def stamp_membership_record_hash(record: MembershipRecord) -> MembershipRecord:
    """Compute and set `content_hash` on the membership record."""
    record.content_hash = compute_membership_record_content_hash(record)
    return record


def stamp_conformance_declaration_hash(
    declaration: ConformanceDeclaration,
) -> ConformanceDeclaration:
    """Compute and set `declaration_hash` on the conformance declaration."""
    declaration.declaration_hash = compute_conformance_declaration_hash(declaration)
    return declaration


# ── Audit delta payloads ────────────────────────────────────────────────────


class MembershipRecordCreatedDelta(BaseModel):
    """Forward + reverse delta for MEMBERSHIP_RECORD_CREATED.

    Fires on every new MembershipRecord assertion (whether initial or
    succession). The reverse delta records that the operation is undone
    by deleting the record AND any SUPERSEDES edge it created.
    """

    # Forward
    record_id: str
    episode_id: str
    group_id: str
    group_system: str
    membership_role: str                 # MembershipRole.value
    supersedes_record_id: Optional[str] = None

    # Reverse
    reverse_delete_record_id: str


class MembershipRecordSupersededDelta(BaseModel):
    """Forward + reverse delta for MEMBERSHIP_RECORD_SUPERSEDED.

    Fires alongside MEMBERSHIP_RECORD_CREATED on any succession event:
    MRC describes the creation of the new record; MRS describes the
    supersession itself (old → new). Two distinct facts about one
    operation. Carries old and new roles to make role-change history
    queryable from the audit log without joining back to the records.
    """

    old_record_id: str
    new_record_id: str
    episode_id: str
    group_id: str
    group_system: str
    old_role: str
    new_role: str

    # Reverse: delete the new record + clear the old record's forward pointer
    reverse_delete_new_record_id: str
    reverse_restore_old_record_id: str


class DeclarationVersionBumpedDelta(BaseModel):
    """Forward + reverse delta for DECLARATION_VERSION_BUMPED (compatible
    minor/patch bump). The new declaration is registered with a SUPERSEDES
    edge to the prior; existing MembershipRecords remain valid against
    either version per §7 version semantics table.
    """

    old_declaration_id: str
    new_declaration_id: str
    group_system: str
    group_id: str
    old_version: str
    new_version: str
    bump_kind: str                       # "minor" | "patch"

    reverse_delete_new_declaration_id: str
    reverse_restore_old_declaration_id: str


class DeclarationSupersededDelta(BaseModel):
    """Forward + reverse delta for DECLARATION_SUPERSEDED (major version
    bump). Breaking change: existing MembershipRecords retain reference
    to the prior version; new records use the new declaration.
    """

    old_declaration_id: str
    new_declaration_id: str
    group_system: str
    group_id: str
    old_version: str
    new_version: str                     # major bump

    reverse_delete_new_declaration_id: str
    reverse_restore_old_declaration_id: str


# ── Operation layer: assertion + audit emission ─────────────────────────────


# Per-group audit chain anchor. Declaration events have no natural episode
# home — they describe protocol-level changes to a grouping's conformance,
# not work done within an episode. We anchor them to a synthetic chain id
# `declaration:{group_system}:{group_id}` so each group has its own ordered
# declaration history. Same chain machinery as episode-anchored events;
# different namespace.
def _declaration_audit_chain_id(group_system: str, group_id: str) -> str:
    return f"declaration:{group_system}:{group_id}"


def assert_membership_record(
    driver,
    record: MembershipRecord,
    *,
    session_id: Optional[str] = None,
    explicit_reason: Optional[str] = None,
) -> MembershipRecord:
    """Operation-layer entry point for asserting a membership.

    Wraps the adapter-level `write_membership_record_sync` with audit
    chain emission. Emits MEMBERSHIP_RECORD_CREATED unconditionally;
    additionally emits MEMBERSHIP_RECORD_SUPERSEDED if the new record
    supersedes a prior — both events describe one operation. Audit
    chain is anchored at the record's episode_id.

    Use this in preference to the bare writer so the audit chain
    advances. The bare writer is for cases where the caller already
    has audit handling (e.g., bulk migration with batched audit).
    """
    import json as _json
    from ariadne.adapters.neo4j.writer import (
        write_audit_record_sync,
        write_membership_record_sync,
    )
    from ariadne.core.branching import (
        AuditRecord,
        CognitiveDeltaType,
        TriggerType,
        compute_audit_record_hash,
    )
    from ariadne.core.audit_chain import next_delta_sequence, prior_audit_hash

    # 1. Write the membership record (governance + hash stamping + edge).
    write_membership_record_sync(driver, record)

    # 2. Build MEMBERSHIP_RECORD_CREATED audit record.
    created_delta = MembershipRecordCreatedDelta(
        record_id=str(record.record_id),
        episode_id=str(record.episode_id),
        group_id=record.group_id,
        group_system=record.group_system,
        membership_role=record.membership_role.value,
        supersedes_record_id=(
            str(record.supersedes_record_id) if record.supersedes_record_id else None
        ),
        reverse_delete_record_id=str(record.record_id),
    )
    created_forward = created_delta.model_dump()
    created_reverse = {
        "operation": "delete_membership_record",
        "record_id": str(record.record_id),
    }

    episode_id_str = str(record.episode_id)
    seq_a = next_delta_sequence(driver, episode_id_str)
    prior_a = prior_audit_hash(driver, episode_id_str)

    short_record_id = str(record.record_id)[:8]
    audit_created = AuditRecord(
        delta_sequence=seq_a,
        agent_id=record.asserted_by,
        session_id=session_id or f"membership-{short_record_id}",
        delta_type=CognitiveDeltaType.MEMBERSHIP_RECORD_CREATED,
        forward_delta=created_forward,
        reverse_delta=created_reverse,
        affected_nodes=[str(record.record_id), episode_id_str],
        trigger_context=TriggerType.HUMAN_EXPLICIT,
        explicit_reason=explicit_reason,
        prior_audit_hash=prior_a,
        caught_by="HUMAN",
        episode_id=episode_id_str,
    )
    audit_created.record_hash = compute_audit_record_hash(
        str(audit_created.audit_id),
        audit_created.delta_sequence,
        audit_created.delta_type.value,
        audit_created.agent_id,
        audit_created.wall_clock_time.isoformat(),
        _json.dumps(created_forward, default=str, sort_keys=True),
        prior_a,
    )
    write_audit_record_sync(driver, audit_created)

    # 3. If this is a succession, fetch the prior record's role and emit
    # MEMBERSHIP_RECORD_SUPERSEDED in addition.
    if record.supersedes_record_id is not None:
        with driver.session() as session:
            prior_row = session.run(
                "MATCH (m:AriadneMembershipRecord {record_id: $rid}) "
                "RETURN m.membership_role AS role",
                {"rid": str(record.supersedes_record_id)},
            ).single()
        old_role = prior_row["role"] if prior_row else "(unknown)"

        superseded_delta = MembershipRecordSupersededDelta(
            old_record_id=str(record.supersedes_record_id),
            new_record_id=str(record.record_id),
            episode_id=episode_id_str,
            group_id=record.group_id,
            group_system=record.group_system,
            old_role=old_role,
            new_role=record.membership_role.value,
            reverse_delete_new_record_id=str(record.record_id),
            reverse_restore_old_record_id=str(record.supersedes_record_id),
        )
        superseded_forward = superseded_delta.model_dump()
        superseded_reverse = {
            "operation": "restore_membership_record",
            "old_record_id": str(record.supersedes_record_id),
            "new_record_id": str(record.record_id),
        }

        seq_b = next_delta_sequence(driver, episode_id_str)
        prior_b = audit_created.record_hash  # Chain directly off the just-written record

        audit_superseded = AuditRecord(
            delta_sequence=seq_b,
            agent_id=record.asserted_by,
            session_id=session_id or f"membership-{short_record_id}",
            delta_type=CognitiveDeltaType.MEMBERSHIP_RECORD_SUPERSEDED,
            forward_delta=superseded_forward,
            reverse_delta=superseded_reverse,
            affected_nodes=[
                str(record.record_id),
                str(record.supersedes_record_id),
                episode_id_str,
            ],
            trigger_context=TriggerType.HUMAN_EXPLICIT,
            explicit_reason=record.succession_reason or explicit_reason,
            prior_audit_hash=prior_b,
            caught_by="HUMAN",
            episode_id=episode_id_str,
        )
        audit_superseded.record_hash = compute_audit_record_hash(
            str(audit_superseded.audit_id),
            audit_superseded.delta_sequence,
            audit_superseded.delta_type.value,
            audit_superseded.agent_id,
            audit_superseded.wall_clock_time.isoformat(),
            _json.dumps(superseded_forward, default=str, sort_keys=True),
            prior_b,
        )
        write_audit_record_sync(driver, audit_superseded)

    return record


def register_conformance_declaration(
    driver,
    declaration: ConformanceDeclaration,
) -> ConformanceDeclaration:
    """Persist an initial ConformanceDeclaration (no version bump).

    Per §11.4 audit registry, initial declaration registration does NOT
    fire a dedicated audit event — only version bumps do
    (DECLARATION_VERSION_BUMPED / DECLARATION_SUPERSEDED). The
    declaration_hash itself is the cryptographic anchor for "this
    declaration existed as written at this time."

    For Phase 1, this is a thin wrapper over the adapter. If a future
    amendment adds a DECLARATION_CREATED event, this is the natural
    place to emit it.
    """
    from ariadne.adapters.neo4j.writer import write_conformance_declaration_sync

    write_conformance_declaration_sync(driver, declaration)
    return declaration


def bump_conformance_declaration(
    driver,
    new_declaration: ConformanceDeclaration,
    prior_declaration_id: str,
    *,
    prior_version: str,
    session_id: Optional[str] = None,
    explicit_reason: Optional[str] = None,
) -> tuple[ConformanceDeclaration, str]:
    """Operation-layer entry point for bumping a ConformanceDeclaration.

    Classifies the version bump (`classify_version_bump`), writes the
    new declaration, links it as the successor to the prior declaration,
    and emits the appropriate audit event:
      - major bump → `DECLARATION_SUPERSEDED` (breaking)
      - minor/patch → `DECLARATION_VERSION_BUMPED` (compatible)

    Audit chain is anchored at `_declaration_audit_chain_id(group_system,
    group_id)` — declarations have no natural episode home, so each
    (group_system, group_id) pair has its own audit chain.

    Returns (new_declaration, bump_kind) — bump_kind is one of "major" |
    "minor" | "patch" for caller convenience.

    Raises:
        GroupingGovernanceError: if version classification fails.
    """
    import json as _json
    from ariadne.adapters.neo4j.writer import (
        supersede_conformance_declaration_sync,
        write_audit_record_sync,
        write_conformance_declaration_sync,
    )
    from ariadne.core.branching import (
        AuditRecord,
        CognitiveDeltaType,
        TriggerType,
        compute_audit_record_hash,
    )
    from ariadne.core.audit_chain import next_delta_sequence, prior_audit_hash

    # 1. Classify (raises on invalid). This validates SemVer + ordering
    # BEFORE we write the new declaration, so failures don't leave a
    # half-applied state.
    bump_kind = classify_version_bump(prior_version, new_declaration.declaration_version)

    # 2. Write the new declaration.
    write_conformance_declaration_sync(driver, new_declaration)

    # 3. Link supersession + set forward pointer on prior.
    supersede_conformance_declaration_sync(
        driver, prior_declaration_id, str(new_declaration.declaration_id)
    )

    # 4. Build the delta payload + emit the appropriate audit event.
    if bump_kind == "major":
        delta = DeclarationSupersededDelta(
            old_declaration_id=prior_declaration_id,
            new_declaration_id=str(new_declaration.declaration_id),
            group_system=new_declaration.group_system,
            group_id=new_declaration.group_id,
            old_version=prior_version,
            new_version=new_declaration.declaration_version,
            reverse_delete_new_declaration_id=str(new_declaration.declaration_id),
            reverse_restore_old_declaration_id=prior_declaration_id,
        )
        delta_type = CognitiveDeltaType.DECLARATION_SUPERSEDED
    else:
        # minor or patch
        delta = DeclarationVersionBumpedDelta(
            old_declaration_id=prior_declaration_id,
            new_declaration_id=str(new_declaration.declaration_id),
            group_system=new_declaration.group_system,
            group_id=new_declaration.group_id,
            old_version=prior_version,
            new_version=new_declaration.declaration_version,
            bump_kind=bump_kind,
            reverse_delete_new_declaration_id=str(new_declaration.declaration_id),
            reverse_restore_old_declaration_id=prior_declaration_id,
        )
        delta_type = CognitiveDeltaType.DECLARATION_VERSION_BUMPED

    forward_delta = delta.model_dump()
    reverse_delta = {
        "operation": "restore_conformance_declaration",
        "old_declaration_id": prior_declaration_id,
        "new_declaration_id": str(new_declaration.declaration_id),
    }

    chain_key = _declaration_audit_chain_id(
        new_declaration.group_system, new_declaration.group_id
    )
    seq = next_delta_sequence(driver, chain_key)
    prior_hash = prior_audit_hash(driver, chain_key)

    audit = AuditRecord(
        delta_sequence=seq,
        agent_id=new_declaration.declared_by,
        session_id=session_id
        or f"declaration-{str(new_declaration.declaration_id)[:8]}",
        delta_type=delta_type,
        forward_delta=forward_delta,
        reverse_delta=reverse_delta,
        affected_nodes=[
            str(new_declaration.declaration_id),
            prior_declaration_id,
        ],
        trigger_context=TriggerType.HUMAN_EXPLICIT,
        explicit_reason=explicit_reason,
        prior_audit_hash=prior_hash,
        caught_by="HUMAN",
        episode_id=chain_key,  # Synthetic chain anchor for declaration events.
    )
    audit.record_hash = compute_audit_record_hash(
        str(audit.audit_id),
        audit.delta_sequence,
        audit.delta_type.value,
        audit.agent_id,
        audit.wall_clock_time.isoformat(),
        _json.dumps(forward_delta, default=str, sort_keys=True),
        prior_hash,
    )
    write_audit_record_sync(driver, audit)

    return new_declaration, bump_kind
