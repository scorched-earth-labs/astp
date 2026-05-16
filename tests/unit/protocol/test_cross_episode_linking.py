"""
Amendment v2.0 — Cross-Episode Linking schema + governance unit tests.

Covers the protocol-core surface of `ariadne.core.cross_episode`:
- Enum vocabulary (LinkType, LinkHealthState, QuarantineResolution, SignalType)
- `EpisodeLink` instantiation + field validation
- `compute_episode_link_content_hash` — determinism, mutability isolation
- `enforce_link_mutual_exclusivity` — §3 governance rules
- `LinkAcceptedDelta` payload shape
- `CognitiveDeltaType` additions (LINK_PROPOSED, LINK_ACCEPTED, LINK_REJECTED)

Adapter-layer behavior (Neo4j writes, audit emission, chain integrity) is
exercised by integration smoke tests against a live Neo4j during
development — protocol-core tests here are pure / mock-free.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from ariadne.core.branching import CognitiveDeltaType
from ariadne.core.cross_episode import (
    EpisodeLink,
    LinkAcceptedDelta,
    LinkGovernanceError,
    LinkHealthState,
    LinkType,
    QuarantineResolution,
    Signal,
    SignalType,
    compute_episode_link_content_hash,
    enforce_link_mutual_exclusivity,
    stamp_content_hash,
)


# ─── Enum vocabulary ────────────────────────────────────────────────────────


class TestLinkType:
    def test_eight_types_per_amendment_section_3(self):
        # Amendment v2.0 §3 declares exactly these eight values.
        assert {lt.value for lt in LinkType} == {
            "CONTINUES_FROM",
            "SUPERSEDES",
            "BRANCHES_FROM",
            "INFORMED_BY",
            "REFERENCES",
            "SPAWNED_FROM",
            "MERGED_INTO",
            "PEER_REVIEWED_BY",
        }


class TestLinkHealthState:
    def test_five_states_including_quarantined(self):
        # QUARANTINED is the Gap 4 addition relative to v1.x.
        assert {hs.value for hs in LinkHealthState} == {
            "VALID",
            "STALE",
            "FROZEN",
            "BROKEN",
            "QUARANTINED",
        }


class TestQuarantineResolution:
    def test_three_resolutions(self):
        assert {qr.value for qr in QuarantineResolution} == {
            "CONFIRMED",
            "DISSOLVED",
            "ESCALATED",
        }


class TestSignalType:
    def test_five_signal_kinds(self):
        assert {st.value for st in SignalType} == {
            "SEMANTIC_SIMILARITY",
            "PARTICIPANT_OVERLAP",
            "TEMPORAL_PROXIMITY",
            "EXPLICIT_REFERENCE",
            "SHARED_ARTIFACT",
        }


class TestCognitiveDeltaTypeAdditions:
    """Amendment v2.0 adds three link events to the existing audit
    delta-type vocabulary. They must coexist with the existing BFM values."""

    def test_link_events_registered(self):
        assert CognitiveDeltaType.LINK_PROPOSED.value == "LINK_PROPOSED"
        assert CognitiveDeltaType.LINK_ACCEPTED.value == "LINK_ACCEPTED"
        assert CognitiveDeltaType.LINK_REJECTED.value == "LINK_REJECTED"

    def test_existing_bfm_values_still_present(self):
        # Regression check: the addition must not have displaced anything.
        assert CognitiveDeltaType.BRANCH_CREATED.value == "BRANCH_CREATED"
        assert CognitiveDeltaType.FORK_CREATED.value == "FORK_CREATED"
        assert CognitiveDeltaType.MERGE_EXECUTED.value == "MERGE_EXECUTED"


# ─── EpisodeLink instantiation ──────────────────────────────────────────────


def _make_link(**overrides) -> EpisodeLink:
    """Build a baseline EpisodeLink for tests. Overrides take precedence."""
    base = {
        "source_episode": uuid4(),
        "target_episode": uuid4(),
        "created_by": "clotho",
        "link_type": LinkType.CONTINUES_FROM,
        "link_strength": 0.8,
        "is_inferred": False,
    }
    base.update(overrides)
    return EpisodeLink(**base)


class TestEpisodeLinkInstantiation:
    def test_required_fields(self):
        link = _make_link()
        assert isinstance(link.link_id, UUID)
        assert link.health_state == LinkHealthState.VALID  # default
        assert link.is_inferred is False
        assert link.inference_signals == []
        assert link.retroactive is False
        assert link.content_hash is None  # not yet stamped

    def test_link_strength_range_validation(self):
        # link_strength must be in [0.0, 1.0]. Pydantic Field constraints.
        with pytest.raises(Exception):
            _make_link(link_strength=1.5)
        with pytest.raises(Exception):
            _make_link(link_strength=-0.1)

    def test_inference_signals_attached(self):
        sig = Signal(
            signal_type=SignalType.SEMANTIC_SIMILARITY,
            signal_weight=0.7,
            signal_value=0.85,
        )
        link = _make_link(is_inferred=True, inference_signals=[sig], inference_threshold=0.55)
        assert len(link.inference_signals) == 1
        assert link.inference_signals[0].signal_type == SignalType.SEMANTIC_SIMILARITY
        assert link.inference_threshold == 0.55


# ─── Content hash ───────────────────────────────────────────────────────────


class TestContentHash:
    def test_determinism(self):
        link = _make_link()
        h1 = compute_episode_link_content_hash(link)
        h2 = compute_episode_link_content_hash(link)
        assert h1 == h2
        assert len(h1) == 64  # SHA3-256 hex

    def test_excludes_quarantine_resolution_fields_per_section_2(self):
        """Amendment v2.0 §2 hash preimage note: quarantine_resolved_at
        and quarantine_resolution are EXCLUDED. Mutating them must not
        change the hash, so the link's commit-time fingerprint survives
        quarantine close."""
        link = _make_link()
        baseline = compute_episode_link_content_hash(link)
        link.quarantine_resolution = QuarantineResolution.CONFIRMED
        link.quarantine_resolved_at = datetime.now(timezone.utc)
        assert compute_episode_link_content_hash(link) == baseline

    def test_includes_health_state(self):
        """Health state IS in the preimage so drift detection ties
        cryptographically to the anchor state at write time."""
        link = _make_link()
        baseline = compute_episode_link_content_hash(link)
        link.health_state = LinkHealthState.STALE
        assert compute_episode_link_content_hash(link) != baseline

    def test_includes_link_strength(self):
        link = _make_link(link_strength=0.5)
        baseline = compute_episode_link_content_hash(link)
        link.link_strength = 0.51
        assert compute_episode_link_content_hash(link) != baseline

    def test_different_link_types_yield_different_hashes(self):
        kwargs = {
            "source_episode": uuid4(),
            "target_episode": uuid4(),
            "created_by": "clotho",
            "link_strength": 0.5,
            "is_inferred": False,
        }
        h_continues = compute_episode_link_content_hash(
            EpisodeLink(link_type=LinkType.CONTINUES_FROM, **kwargs)
        )
        h_informed = compute_episode_link_content_hash(
            EpisodeLink(link_type=LinkType.INFORMED_BY, **kwargs)
        )
        assert h_continues != h_informed

    def test_stamp_content_hash_idempotent(self):
        link = _make_link()
        stamp_content_hash(link)
        h1 = link.content_hash
        stamp_content_hash(link)
        assert link.content_hash == h1

    def test_stamp_returns_same_instance(self):
        link = _make_link()
        assert stamp_content_hash(link) is link


# ─── Mutual exclusivity governance (§3) ────────────────────────────────────


class TestMutualExclusivity:
    def test_continues_blocks_supersedes(self):
        with pytest.raises(LinkGovernanceError, match="cannot coexist"):
            enforce_link_mutual_exclusivity(
                LinkType.SUPERSEDES, [LinkType.CONTINUES_FROM]
            )

    def test_supersedes_blocks_continues(self):
        # Mutex is symmetric on the pair.
        with pytest.raises(LinkGovernanceError, match="cannot coexist"):
            enforce_link_mutual_exclusivity(
                LinkType.CONTINUES_FROM, [LinkType.SUPERSEDES]
            )

    def test_continues_blocks_branches(self):
        with pytest.raises(LinkGovernanceError, match="cannot coexist"):
            enforce_link_mutual_exclusivity(
                LinkType.BRANCHES_FROM, [LinkType.CONTINUES_FROM]
            )

    def test_supersedes_and_branches_are_compatible(self):
        """Critical: §3 says SUPERSEDES and BRANCHES_FROM are NOT mutually
        exclusive — only CONTINUES_FROM is mutex with each of them
        individually. A pair can carry both SUPERSEDES and BRANCHES_FROM."""
        # Both directions should succeed (i.e., not raise).
        enforce_link_mutual_exclusivity(LinkType.SUPERSEDES, [LinkType.BRANCHES_FROM])
        enforce_link_mutual_exclusivity(LinkType.BRANCHES_FROM, [LinkType.SUPERSEDES])

    def test_informed_by_compatible_with_all(self):
        # INFORMED_BY has no mutex entries; should coexist with every other type.
        for other in LinkType:
            enforce_link_mutual_exclusivity(LinkType.INFORMED_BY, [other])
            enforce_link_mutual_exclusivity(other, [LinkType.INFORMED_BY])

    def test_references_compatible_with_all(self):
        for other in LinkType:
            enforce_link_mutual_exclusivity(LinkType.REFERENCES, [other])

    def test_empty_existing_always_succeeds(self):
        # No existing links → no constraints to check.
        for lt in LinkType:
            enforce_link_mutual_exclusivity(lt, [])

    def test_multiple_existing_with_one_conflict_raises(self):
        with pytest.raises(LinkGovernanceError):
            enforce_link_mutual_exclusivity(
                LinkType.SUPERSEDES,
                [LinkType.INFORMED_BY, LinkType.CONTINUES_FROM, LinkType.REFERENCES],
            )


# ─── Audit payload ──────────────────────────────────────────────────────────


class TestLinkAcceptedDelta:
    def test_instantiates_with_required_fields(self):
        link_id = str(uuid4())
        delta = LinkAcceptedDelta(
            link_id=link_id,
            source_episode=str(uuid4()),
            target_episode=str(uuid4()),
            link_type="CONTINUES_FROM",
            link_strength=0.85,
            is_inferred=False,
            retroactive=False,
            reverse_delete_link_id=link_id,
        )
        assert delta.link_id == link_id
        assert delta.reverse_delete_link_id == link_id  # reverse op references the same id

    def test_model_dump_carries_all_fields(self):
        link_id = str(uuid4())
        delta = LinkAcceptedDelta(
            link_id=link_id,
            source_episode=str(uuid4()),
            target_episode=str(uuid4()),
            link_type="INFORMED_BY",
            link_strength=0.6,
            is_inferred=True,
            retroactive=True,
            reverse_delete_link_id=link_id,
        )
        dumped = delta.model_dump()
        # Forward + reverse keys all present for AuditRecord.forward_delta JSON
        assert set(dumped.keys()) == {
            "link_id",
            "source_episode",
            "target_episode",
            "link_type",
            "link_strength",
            "is_inferred",
            "retroactive",
            "reverse_delete_link_id",
        }
        assert dumped["is_inferred"] is True
        assert dumped["retroactive"] is True
