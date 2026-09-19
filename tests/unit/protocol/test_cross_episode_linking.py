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
SPEC §20 Part I — Cross-Episode Linking schema + governance unit tests.

Covers the protocol-core surface of `astp.core.cross_episode`:
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
from pydantic import ValidationError

from astp.core.branching import CognitiveDeltaType
from astp.core.cross_episode import (
    CandidateRejectedDelta,
    EpisodeLink,
    LinkAcceptedDelta,
    LinkGovernanceError,
    LinkHealthState,
    LinkProposedDelta,
    LinkRejectedDelta,
    LinkType,
    QuarantineResolution,
    RejectionReason,
    Signal,
    SignalType,
    compute_episode_link_content_hash,
    enforce_link_mutual_exclusivity,
    stamp_content_hash,
)


# ─── Enum vocabulary ────────────────────────────────────────────────────────


class TestLinkType:
    def test_eight_types_per_amendment_section_3(self):
        # SPEC §20 →3 declares exactly these eight values.
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
        # QUARANTINED requires explicit human review to exit (SPEC §20 →6).
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
    """SPEC §20 adds three link events to the existing audit
    delta-type vocabulary. They must coexist with the existing BFM values."""

    def test_link_events_registered(self):
        assert CognitiveDeltaType.LINK_PROPOSED.value == "LINK_PROPOSED"
        assert CognitiveDeltaType.LINK_ACCEPTED.value == "LINK_ACCEPTED"
        assert CognitiveDeltaType.LINK_REJECTED.value == "LINK_REJECTED"
        assert CognitiveDeltaType.CANDIDATE_REJECTED.value == "CANDIDATE_REJECTED"

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
        "created_by": "agent-a",
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
        with pytest.raises(ValidationError):
            _make_link(link_strength=1.5)
        with pytest.raises(ValidationError):
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
        """SPEC §20 →2 hash preimage note: quarantine_resolved_at
        and quarantine_resolution are EXCLUDED. Mutating them must not
        change the hash, so the link's commit-time fingerprint survives
        quarantine close."""
        link = _make_link()
        baseline = compute_episode_link_content_hash(link)
        link.quarantine_resolution = QuarantineResolution.CONFIRMED
        link.quarantine_resolved_at = datetime.now(timezone.utc)
        assert compute_episode_link_content_hash(link) == baseline

    def test_excludes_health_state_and_binds_the_ends_roots(self):
        """5.0.0 (SPEC §20 →2): the hash is fixed at creation. Health, quarantine
        and created_by are lifecycle and provenance — the audit chain's — and a
        4.x hash that moved with health committed to nothing stable. What the
        hash does bind is each end's Episode root when that end was sealed."""
        link = _make_link()
        baseline = compute_episode_link_content_hash(link)
        link.health_state = LinkHealthState.STALE
        link.created_by = "someone-else"
        assert compute_episode_link_content_hash(link) == baseline
        link.source_episode_root = "ab" * 32
        assert compute_episode_link_content_hash(link) != baseline
        # the 4.x form is retained, for verifying links already written, and did move with health
        from astp.core.cross_episode import compute_episode_link_content_hash_4x
        link = _make_link(); old = compute_episode_link_content_hash_4x(link)
        link.health_state = LinkHealthState.STALE
        assert compute_episode_link_content_hash_4x(link) != old

    def test_includes_link_strength(self):
        link = _make_link(link_strength=0.5)
        baseline = compute_episode_link_content_hash(link)
        link.link_strength = 0.51
        assert compute_episode_link_content_hash(link) != baseline

    def test_different_link_types_yield_different_hashes(self):
        kwargs = {
            "source_episode": uuid4(),
            "target_episode": uuid4(),
            "created_by": "agent-a",
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


# ─── Phase 2 — Discovery primitives ─────────────────────────────────────────


def _make_signal(
    signal_type: SignalType = SignalType.SEMANTIC_SIMILARITY,
    strength: float = 0.82,
    weight: float = 0.5,
) -> Signal:
    return Signal(
        signal_type=signal_type,
        signal_weight=weight,
        signal_value=strength,
    )


class TestRejectionReason:
    def test_four_reasons_per_amendment_section_5(self):
        # SPEC §20 →5 declares these four structured rejection reasons.
        assert {r.value for r in RejectionReason} == {
            "LOW_CONFIDENCE",
            "WRONG_RELATIONSHIP_TYPE",
            "NOT_RELATED",
            "DUPLICATE_OF_EXISTING",
        }


class TestLinkProposedDelta:
    def test_carries_signals_and_thresholds_for_audit_the_decision(self):
        # §12.2 — proposal record must carry enough state to re-evaluate later.
        delta = LinkProposedDelta(
            source_episode=str(uuid4()),
            target_episode=str(uuid4()),
            proposed_link_type="INFORMED_BY",
            composite_score=0.81,
            inference_signals=[_make_signal(), _make_signal(
                SignalType.SHARED_ARTIFACT, 0.4
            )],
            discovery_threshold_at_creation=0.75,
            auto_accept_threshold_at_creation=0.90,
        )
        dumped = delta.model_dump()
        assert dumped["composite_score"] == 0.81
        assert len(dumped["inference_signals"]) == 2
        assert dumped["discovery_threshold_at_creation"] == 0.75
        # threshold values are frozen on the record — calibration relies on
        # being able to interpret a historical score against the threshold
        # in effect at creation time.
        assert dumped["auto_accept_threshold_at_creation"] == 0.90


class TestLinkRejectedDelta:
    def test_references_proposal_audit_id(self):
        proposal_id = str(uuid4())
        delta = LinkRejectedDelta(
            proposed_audit_event_id=proposal_id,
            source_episode=str(uuid4()),
            target_episode=str(uuid4()),
            proposed_link_type="REFERENCES",
            rejecting_agent="agent-a",
            rejection_reason=RejectionReason.NOT_RELATED.value,
        )
        assert delta.proposed_audit_event_id == proposal_id
        assert delta.rejection_reason == "NOT_RELATED"
        assert delta.rejection_note is None

    def test_optional_note_carries_through_dump(self):
        delta = LinkRejectedDelta(
            proposed_audit_event_id=str(uuid4()),
            source_episode=str(uuid4()),
            target_episode=str(uuid4()),
            proposed_link_type="REFERENCES",
            rejecting_agent="agent-a",
            rejection_reason=RejectionReason.WRONG_RELATIONSHIP_TYPE.value,
            rejection_note="should be SUPERSEDES instead",
        )
        assert delta.model_dump()["rejection_note"] == "should be SUPERSEDES instead"


class TestCandidateRejectedDelta:
    def test_records_sub_threshold_score_with_signals(self):
        # Calibration use case: candidate scored below DISCOVERY_THRESHOLD,
        # not surfaced for review, but recorded for later threshold tuning.
        delta = CandidateRejectedDelta(
            source_episode=str(uuid4()),
            target_episode=str(uuid4()),
            proposed_link_type="REFERENCES",
            composite_score=0.62,
            inference_signals=[_make_signal(strength=0.62)],
            discovery_threshold_at_creation=0.75,
        )
        dumped = delta.model_dump()
        assert dumped["composite_score"] < dumped["discovery_threshold_at_creation"]
        assert len(dumped["inference_signals"]) == 1


# ─── Phase 2 — Operation layer (driver-mocked) ──────────────────────────────


class _FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def single(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class _FakeSession:
    def __init__(self, store):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, params=None):
        return self.store.run(query, params or {})


class _FakeDriver:
    """Captures AuditRecord writes for assertion. Returns empty results for
    audit-chain lookups so the first record on each chain anchors to
    GENESIS."""

    def __init__(self):
        self.audit_records = []

    def session(self):
        return _FakeSession(self)

    def run(self, query, params):
        q = " ".join(query.split())
        # Chain lookups — return empty so caller falls back to seq=1, prior=GENESIS.
        if "AriadneAuditRecord" in q and "RETURN" in q and "MERGE" not in q:
            return _FakeResult([])
        # AuditRecord MERGE — capture the write.
        if "MERGE (ar:AriadneAuditRecord" in q:
            self.audit_records.append(dict(params))
            return _FakeResult([])
        # Episode→AuditRecord edge — accept silently.
        if "AUDIT_TRAIL" in q:
            return _FakeResult([])
        return _FakeResult([])


class TestProposeLinkCandidate:
    def test_emits_link_proposed_audit_event(self):
        from astp.core.cross_episode import propose_link_candidate

        driver = _FakeDriver()
        src = str(uuid4())
        tgt = str(uuid4())
        audit_id = propose_link_candidate(
            driver,
            source_episode=src,
            target_episode=tgt,
            proposed_link_type=LinkType.INFORMED_BY,
            composite_score=0.82,
            inference_signals=[_make_signal()],
            discovery_threshold=0.75,
            auto_accept_threshold=0.90,
            proposing_agent="agent-a",
        )
        assert UUID(audit_id)
        assert len(driver.audit_records) == 1
        rec = driver.audit_records[0]
        assert rec["delta_type"] == "LINK_PROPOSED"
        assert rec["agent_id"] == "agent-a"
        assert rec["caught_by"] == "AGENT"
        assert rec["trigger_context"] == "agent_detected"
        assert rec["prior_audit_hash"] == "GENESIS"
        # delta_sequence must start at 1 on a fresh chain.
        assert rec["delta_sequence"] == 1
        # Audit is anchored on the source episode.
        assert rec["episode_id"] == src

    def test_records_thresholds_at_proposal_time(self):
        from astp.core.cross_episode import propose_link_candidate
        import json as _json

        driver = _FakeDriver()
        propose_link_candidate(
            driver,
            source_episode=str(uuid4()),
            target_episode=str(uuid4()),
            proposed_link_type=LinkType.REFERENCES,
            composite_score=0.78,
            inference_signals=[_make_signal()],
            discovery_threshold=0.70,
            auto_accept_threshold=0.95,
            proposing_agent="agent-a",
        )
        forward = _json.loads(driver.audit_records[0]["forward_delta"])
        # The whole point of audit-the-decision (§12.2) — thresholds are
        # frozen on the record so the score is reinterpretable later.
        assert forward["discovery_threshold_at_creation"] == 0.70
        assert forward["auto_accept_threshold_at_creation"] == 0.95
        assert forward["composite_score"] == 0.78


class TestRecordCandidateRejection:
    def test_emits_candidate_rejected_audit_event(self):
        from astp.core.cross_episode import record_candidate_rejection

        driver = _FakeDriver()
        audit_id = record_candidate_rejection(
            driver,
            source_episode=str(uuid4()),
            target_episode=str(uuid4()),
            proposed_link_type=LinkType.REFERENCES,
            composite_score=0.55,
            inference_signals=[_make_signal(strength=0.55)],
            discovery_threshold=0.75,
            detecting_agent="agent-a",
        )
        assert UUID(audit_id)
        rec = driver.audit_records[0]
        assert rec["delta_type"] == "CANDIDATE_REJECTED"
        assert rec["trigger_context"] == "agent_detected"
        assert rec["caught_by"] == "AGENT"


class TestRecordLinkRejection:
    def test_carries_proposed_audit_event_id_for_correlation(self):
        from astp.core.cross_episode import record_link_rejection
        import json as _json

        driver = _FakeDriver()
        proposal_id = str(uuid4())
        record_link_rejection(
            driver,
            proposed_audit_event_id=proposal_id,
            source_episode=str(uuid4()),
            target_episode=str(uuid4()),
            proposed_link_type=LinkType.REFERENCES,
            rejecting_agent="human-1",
            rejection_reason=RejectionReason.NOT_RELATED,
            rejection_note="overlap is coincidental",
        )
        rec = driver.audit_records[0]
        assert rec["delta_type"] == "LINK_REJECTED"
        # Human-driven rejection from a review queue.
        assert rec["caught_by"] == "HUMAN"
        assert rec["trigger_context"] == "human_explicit"
        forward = _json.loads(rec["forward_delta"])
        assert forward["proposed_audit_event_id"] == proposal_id
        assert forward["rejection_reason"] == "NOT_RELATED"
        assert forward["rejection_note"] == "overlap is coincidental"
