"""
Amendment v2.0 — Episode Grouping schema + governance unit tests.

Covers the protocol-core surface of `ariadne.core.grouping`:
- Enum vocabulary (MembershipRole, GroupingSystem)
- Capability, MembershipRecord, ConformanceDeclaration instantiation
- Content hash properties (determinism, role inclusion per Gap 6,
  forward-pointer exclusion per §10)
- SemVer governance (enforce_semver_format, classify_version_bump)
- Audit delta payload shapes
- CognitiveDeltaType additions (MEMBERSHIP_RECORD_CREATED,
  MEMBERSHIP_RECORD_SUPERSEDED, DECLARATION_VERSION_BUMPED,
  DECLARATION_SUPERSEDED)

Adapter behavior (Neo4j writes, succession chain integrity, audit
emission) is exercised by integration smoke tests during development —
protocol-core tests here are pure / mock-free.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from ariadne.core.branching import CognitiveDeltaType
from ariadne.core.grouping import (
    Capability,
    ConformanceDeclaration,
    DeclarationSupersededDelta,
    DeclarationVersionBumpedDelta,
    GroupingGovernanceError,
    GroupingSystem,
    MembershipRecord,
    MembershipRecordCreatedDelta,
    MembershipRecordSupersededDelta,
    MembershipRole,
    classify_version_bump,
    compute_conformance_declaration_hash,
    compute_membership_record_content_hash,
    enforce_semver_format,
    stamp_conformance_declaration_hash,
    stamp_membership_record_hash,
)


# ─── Enum vocabulary ────────────────────────────────────────────────────────


class TestMembershipRole:
    def test_four_roles_per_section_7(self):
        assert {r.value for r in MembershipRole} == {
            "PRIMARY",
            "SUPPORTING",
            "REFERENCE",
            "ARCHIVED",
        }


class TestGroupingSystem:
    def test_reference_implementations_registered(self):
        # Open-ended — these are reference values, implementations may
        # declare arbitrary group_system strings.
        assert GroupingSystem.ARIADNE_NATIVE.value == "ariadne_native"
        assert GroupingSystem.SEL_THERMYT_COLLECTION.value == "sel-thermyt:Collection"
        assert GroupingSystem.CLAUDE_PROJECT.value == "claude:Project"
        assert GroupingSystem.NOTION_DATABASE.value == "notion:Database"


class TestCognitiveDeltaTypeAdditions:
    def test_grouping_events_registered(self):
        assert CognitiveDeltaType.MEMBERSHIP_RECORD_CREATED.value == "MEMBERSHIP_RECORD_CREATED"
        assert CognitiveDeltaType.MEMBERSHIP_RECORD_SUPERSEDED.value == "MEMBERSHIP_RECORD_SUPERSEDED"
        assert CognitiveDeltaType.DECLARATION_VERSION_BUMPED.value == "DECLARATION_VERSION_BUMPED"
        assert CognitiveDeltaType.DECLARATION_SUPERSEDED.value == "DECLARATION_SUPERSEDED"

    def test_existing_link_values_still_present(self):
        # Regression check: grouping additions did not displace linking.
        assert CognitiveDeltaType.LINK_ACCEPTED.value == "LINK_ACCEPTED"
        assert CognitiveDeltaType.LINK_PROPOSED.value == "LINK_PROPOSED"

    def test_existing_bfm_values_still_present(self):
        # Regression check: still have the original BFM vocabulary.
        assert CognitiveDeltaType.BRANCH_CREATED.value == "BRANCH_CREATED"
        assert CognitiveDeltaType.MERGE_EXECUTED.value == "MERGE_EXECUTED"


# ─── Capability ─────────────────────────────────────────────────────────────


class TestCapability:
    def test_capability_id_only(self):
        cap = Capability(capability_id="supports_archival")
        assert cap.capability_id == "supports_archival"
        assert cap.description is None

    def test_capability_with_description(self):
        cap = Capability(capability_id="supports_archival", description="moves to read-only state")
        assert cap.description == "moves to read-only state"


# ─── MembershipRecord ──────────────────────────────────────────────────────


def _make_membership(**overrides) -> MembershipRecord:
    base = {
        "episode_id": uuid4(),
        "group_id": "test-group",
        "group_system": "sel-thermyt:Collection",
        "asserted_by": "Devin",
        "membership_role": MembershipRole.PRIMARY,
    }
    base.update(overrides)
    return MembershipRecord(**base)


class TestMembershipRecordInstantiation:
    def test_required_fields(self):
        rec = _make_membership()
        assert isinstance(rec.record_id, UUID)
        assert rec.supersedes_record_id is None
        assert rec.superseded_by_record_id is None
        assert rec.content_hash is None  # not yet stamped

    def test_succession_fields_optional(self):
        prior = uuid4()
        rec = _make_membership(
            supersedes_record_id=prior, succession_reason="role re-prioritized"
        )
        assert rec.supersedes_record_id == prior
        assert rec.succession_reason == "role re-prioritized"


# ─── MembershipRecord content hash ─────────────────────────────────────────


class TestMembershipRecordContentHash:
    def test_determinism(self):
        rec = _make_membership()
        h1 = compute_membership_record_content_hash(rec)
        h2 = compute_membership_record_content_hash(rec)
        assert h1 == h2
        assert len(h1) == 64

    def test_membership_role_IS_in_hash_per_gap_6(self):
        """Critical: Gap 6 explicitly includes role in the hash. Changing
        the role on a record must change the hash — that's why role
        changes require succession (a new record), not mutation."""
        rec = _make_membership(membership_role=MembershipRole.PRIMARY)
        baseline = compute_membership_record_content_hash(rec)

        # Build a peer record with SAME identity but different role.
        rec_b = _make_membership(membership_role=MembershipRole.SUPPORTING)
        rec_b.record_id = rec.record_id
        rec_b.episode_id = rec.episode_id
        rec_b.group_id = rec.group_id
        rec_b.group_system = rec.group_system
        rec_b.asserted_at = rec.asserted_at
        rec_b.asserted_by = rec.asserted_by

        assert compute_membership_record_content_hash(rec_b) != baseline

    def test_superseded_by_record_id_NOT_in_hash_per_section_10(self):
        """§10 forward-pointer-exclusion rule: superseded_by_record_id is
        a mutable forward pointer set by a LATER operation. Including it
        would invalidate the hash on succession. Excluding it lets the
        chain advance without breaking integrity."""
        rec = _make_membership()
        baseline = compute_membership_record_content_hash(rec)
        rec.superseded_by_record_id = uuid4()  # simulate succession
        assert compute_membership_record_content_hash(rec) == baseline

    def test_supersedes_record_id_IS_in_hash(self):
        """The chain's commitment to its predecessor is part of the
        content. supersedes_record_id is included so a record's hash
        commits to "this record specifically replaced THAT prior one." """
        rec = _make_membership()
        baseline = compute_membership_record_content_hash(rec)
        rec.supersedes_record_id = uuid4()
        assert compute_membership_record_content_hash(rec) != baseline

    def test_stamp_membership_record_hash_idempotent(self):
        rec = _make_membership()
        stamp_membership_record_hash(rec)
        h1 = rec.content_hash
        stamp_membership_record_hash(rec)
        assert rec.content_hash == h1

    def test_stamp_returns_same_instance(self):
        rec = _make_membership()
        assert stamp_membership_record_hash(rec) is rec


# ─── ConformanceDeclaration ────────────────────────────────────────────────


def _make_declaration(**overrides) -> ConformanceDeclaration:
    base = {
        "group_id": "test-group",
        "group_system": "sel-thermyt:Collection",
        "declared_by": "clotho",
        "declaration_version": "1.0.0",
        "capabilities": [Capability(capability_id="supports_archival")],
    }
    base.update(overrides)
    return ConformanceDeclaration(**base)


class TestConformanceDeclaration:
    def test_required_fields(self):
        decl = _make_declaration()
        assert isinstance(decl.declaration_id, UUID)
        assert decl.declaration_version == "1.0.0"
        assert len(decl.capabilities) == 1
        assert decl.superseded_by is None
        assert decl.declaration_hash is None


class TestConformanceDeclarationHash:
    def test_determinism(self):
        decl = _make_declaration()
        h1 = compute_conformance_declaration_hash(decl)
        h2 = compute_conformance_declaration_hash(decl)
        assert h1 == h2

    def test_superseded_by_NOT_in_hash_per_section_10(self):
        decl = _make_declaration()
        baseline = compute_conformance_declaration_hash(decl)
        decl.superseded_by = uuid4()
        assert compute_conformance_declaration_hash(decl) == baseline

    def test_version_IS_in_hash(self):
        decl_a = _make_declaration(declaration_version="1.0.0")
        decl_b = _make_declaration(declaration_version="1.0.1")
        decl_b.declaration_id = decl_a.declaration_id
        decl_b.declared_at = decl_a.declared_at
        assert compute_conformance_declaration_hash(decl_a) != compute_conformance_declaration_hash(decl_b)

    def test_capabilities_IS_in_hash(self):
        decl_a = _make_declaration(
            capabilities=[Capability(capability_id="cap_a")]
        )
        decl_b = _make_declaration(
            capabilities=[Capability(capability_id="cap_b")]
        )
        decl_b.declaration_id = decl_a.declaration_id
        decl_b.declared_at = decl_a.declared_at
        assert compute_conformance_declaration_hash(decl_a) != compute_conformance_declaration_hash(decl_b)

    def test_stamp_idempotent(self):
        decl = _make_declaration()
        stamp_conformance_declaration_hash(decl)
        h1 = decl.declaration_hash
        stamp_conformance_declaration_hash(decl)
        assert decl.declaration_hash == h1


# ─── SemVer governance ─────────────────────────────────────────────────────


class TestSemVerEnforcement:
    @pytest.mark.parametrize("ver", ["1.0.0", "0.0.1", "10.20.30", "999.999.999"])
    def test_valid_versions_parse(self, ver):
        result = enforce_semver_format(ver)
        assert len(result) == 3
        assert all(isinstance(p, int) for p in result)

    @pytest.mark.parametrize("ver", ["1.0", "1", "1.0.0.0", "v1.0.0", "1.0.0-alpha", ""])
    def test_invalid_versions_rejected(self, ver):
        with pytest.raises(GroupingGovernanceError):
            enforce_semver_format(ver)

    def test_negative_parts_rejected(self):
        with pytest.raises(GroupingGovernanceError):
            enforce_semver_format("-1.0.0")

    def test_non_numeric_parts_rejected(self):
        with pytest.raises(GroupingGovernanceError):
            enforce_semver_format("1.x.0")


class TestVersionBumpClassification:
    def test_patch_bump(self):
        assert classify_version_bump("1.0.0", "1.0.1") == "patch"
        assert classify_version_bump("1.0.5", "1.0.10") == "patch"

    def test_minor_bump(self):
        assert classify_version_bump("1.0.0", "1.1.0") == "minor"
        assert classify_version_bump("1.2.5", "1.3.0") == "minor"
        # Minor bump can skip patch versions
        assert classify_version_bump("1.0.5", "1.1.0") == "minor"

    def test_major_bump(self):
        assert classify_version_bump("1.0.0", "2.0.0") == "major"
        assert classify_version_bump("1.5.3", "2.0.0") == "major"
        # Major bump can skip versions
        assert classify_version_bump("1.0.0", "3.0.0") == "major"

    def test_decrease_rejected(self):
        with pytest.raises(GroupingGovernanceError, match="strictly greater"):
            classify_version_bump("2.0.0", "1.0.0")

    def test_same_version_rejected(self):
        with pytest.raises(GroupingGovernanceError, match="strictly greater"):
            classify_version_bump("1.0.0", "1.0.0")

    def test_invalid_format_rejected(self):
        with pytest.raises(GroupingGovernanceError):
            classify_version_bump("1.0", "1.0.1")


# ─── Audit delta payloads ──────────────────────────────────────────────────


class TestAuditDeltaPayloads:
    def test_membership_record_created_delta(self):
        rid = str(uuid4())
        delta = MembershipRecordCreatedDelta(
            record_id=rid,
            episode_id=str(uuid4()),
            group_id="group-1",
            group_system="sel-thermyt:Collection",
            membership_role="PRIMARY",
            reverse_delete_record_id=rid,
        )
        assert delta.supersedes_record_id is None  # default
        assert delta.reverse_delete_record_id == rid

    def test_membership_record_superseded_delta(self):
        old = str(uuid4())
        new = str(uuid4())
        delta = MembershipRecordSupersededDelta(
            old_record_id=old,
            new_record_id=new,
            episode_id=str(uuid4()),
            group_id="group-1",
            group_system="sel-thermyt:Collection",
            old_role="PRIMARY",
            new_role="SUPPORTING",
            reverse_delete_new_record_id=new,
            reverse_restore_old_record_id=old,
        )
        assert delta.old_role != delta.new_role  # the whole point of the event

    def test_declaration_version_bumped_delta(self):
        old = str(uuid4())
        new = str(uuid4())
        delta = DeclarationVersionBumpedDelta(
            old_declaration_id=old,
            new_declaration_id=new,
            group_system="sel-thermyt:Collection",
            group_id="group-1",
            old_version="1.0.0",
            new_version="1.1.0",
            bump_kind="minor",
            reverse_delete_new_declaration_id=new,
            reverse_restore_old_declaration_id=old,
        )
        assert delta.bump_kind in ("minor", "patch")

    def test_declaration_superseded_delta(self):
        delta = DeclarationSupersededDelta(
            old_declaration_id=str(uuid4()),
            new_declaration_id=str(uuid4()),
            group_system="sel-thermyt:Collection",
            group_id="group-1",
            old_version="1.5.0",
            new_version="2.0.0",
            reverse_delete_new_declaration_id="abc",
            reverse_restore_old_declaration_id="def",
        )
        assert delta.old_version == "1.5.0"
        assert delta.new_version == "2.0.0"
