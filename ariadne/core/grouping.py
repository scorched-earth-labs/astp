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

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from ariadne.core.schema import sha3_256


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


# ── Canonical value serializer ──────────────────────────────────────────────


def _canonical_value(value):
    """Mirror of the canonicalizer in cross_episode.py — datetimes → UTC ISO
    8601, UUIDs → str, enums → .value, floats → repr, Pydantic models → dict.

    Duplicated by intent: both hash systems should be self-contained. If
    we ever lift this into a shared `hash_canonical.py` module, both
    modules can collapse onto it. For Phase 1 the duplication is the
    smaller risk than coupling the two hash implementations.
    """
    if value is None:
        return None
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
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


def compute_membership_record_content_hash(record: MembershipRecord) -> str:
    """SHA3-256 of the MembershipRecord canonical preimage — §7.

    Includes `membership_role` per Gap 6. Mutating role requires a new
    record (via succession), so the hash on the original record stays
    valid as the historical commitment to "this episode had this role
    at this time."

    Excludes `superseded_by_record_id` per §10 — that's a forward
    pointer set by a LATER operation; the integrity is maintained
    through the audit log, not through the hash.
    """
    preimage = {f: _canonical_value(getattr(record, f)) for f in _MEMBERSHIP_HASH_PREIMAGE_FIELDS}
    serialized = json.dumps(preimage, sort_keys=False, separators=(",", ":"), ensure_ascii=False)
    return sha3_256(serialized.encode("utf-8"))


def compute_conformance_declaration_hash(declaration: ConformanceDeclaration) -> str:
    """SHA3-256 of the ConformanceDeclaration canonical preimage — §8.

    Excludes `superseded_by` per §10 forward-pointer-exclusion. The
    declaration's hash commits to the declaration as authored; succession
    is recorded separately via the audit chain.
    """
    preimage = {f: _canonical_value(getattr(declaration, f)) for f in _DECLARATION_HASH_PREIMAGE_FIELDS}
    serialized = json.dumps(preimage, sort_keys=False, separators=(",", ":"), ensure_ascii=False)
    return sha3_256(serialized.encode("utf-8"))


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


class MembershipRoleChangedDelta(BaseModel):
    """Forward + reverse delta for MEMBERSHIP_ROLE_CHANGED.

    Specialization of MEMBERSHIP_RECORD_CREATED for the case where the
    succession is specifically a role change. Carries both the old and
    new role for clarity in the audit trail.
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
