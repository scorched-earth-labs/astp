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
Phase 3 — Schema Unit Tests

Aside + Soliloquy schemas, hash domain separation, Merkle placeholder
policy, governance rules (human-initiation, accessibility, return obligation).
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from astp.core.branching import (
    AccessLevel,
    AriadneGovernanceError,
    AsideClosedDelta,
    AsideOpenedDelta,
    AsideSegmentNode,
    AsideStatus,
    AsideTerminusNode,
    AsideTerminationStatus,
    SoliloquyConcludedDelta,
    SoliloquyConclusionNode,
    SoliloquyContentHashPolicy,
    SoliloquyInitiatedDelta,
    SoliloquySegmentNode,
    SoliloquyStatus,
    SoliloquyTerminationStatus,
    SoliloquyVisibilityPolicy,
    check_aside_return_obligation,
    check_soliloquy_return_obligation,
    compute_aside_hash,
    compute_deliberation_chain_hash,
    compute_soliloquy_conclusion_hash,
    compute_soliloquy_content_hash,
    enforce_aside_close_reason,
    enforce_aside_human_initiated,
    enforce_aside_target_agent,
    enforce_soliloquy_conclusion_required,
    enforce_soliloquy_human_accessible,
    enforce_soliloquy_purpose_required,
)


class TestAsideSchema:
    def test_instantiates_with_required_fields(self):
        a = AsideSegmentNode(
            parent_episode_id=uuid4(),
            parent_segment_id="seg-1",
            aside_label="clarify scope",
            initiated_by_human="devin",
            target_agent_id="clotho",
        )
        assert a.return_obligation is True
        assert a.content_refs == []

    def test_aside_terminus_captures_scan_result(self):
        t = AsideTerminusNode(
            aside_id=uuid4(),
            parent_episode_id=uuid4(),
            close_reason="resolved",
            final_content_hash="h",
            reference_scan_passed=False,
            external_references_found=["seg-x", "seg-y"],
        )
        assert t.reference_scan_passed is False
        assert len(t.external_references_found) == 2
        assert t.termination_status == AsideTerminationStatus.CLOSED


class TestSoliloquySchema:
    def test_default_policy_enforces_decision_1(self):
        """Decision 1: human_accessible=ALWAYS, others=ESCALATION_ONLY, audit_on_access=true."""
        p = SoliloquyVisibilityPolicy()
        assert p.human_accessible is True
        assert p.owner_agent_access == "ALWAYS"
        assert p.other_agents_access == AccessLevel.ESCALATION_ONLY
        assert p.content_hash_policy == SoliloquyContentHashPolicy.HASH_PLACEHOLDER
        assert p.audit_on_access is True

    def test_soliloquy_node_defaults(self):
        s = SoliloquySegmentNode(
            parent_episode_id=uuid4(),
            parent_segment_id="seg-1",
            soliloquy_purpose="decide between options",
            initiated_by_agent="clotho",
        )
        assert s.deliberation_chain == []
        assert s.visibility_policy.human_accessible is True

    def test_conclusion_binds_both_hashes(self):
        c = SoliloquyConclusionNode(
            soliloquy_id=uuid4(),
            parent_episode_id=uuid4(),
            conclusion_summary="decided A",
            conclusion_content_hash="pub",
            deliberation_chain_hash="priv",
            merged_into_segment_id="seg-merge",
        )
        assert c.termination_status == SoliloquyTerminationStatus.ABSORBED


class TestHashDomainSeparation:
    def test_aside_hash_deterministic(self):
        ts = datetime(2026, 4, 21, tzinfo=timezone.utc).isoformat()
        h1 = compute_aside_hash("a", "ep", "seg", "human", "agent", ts, "p")
        h2 = compute_aside_hash("a", "ep", "seg", "human", "agent", ts, "p")
        assert h1 == h2
        assert len(h1) == 64

    def test_soliloquy_placeholder_vs_full_differ(self):
        ts = datetime.now(timezone.utc).isoformat()
        chain = ["seg-a", "seg-b", "seg-c"]
        placeholder_policy = SoliloquyVisibilityPolicy(
            content_hash_policy=SoliloquyContentHashPolicy.HASH_PLACEHOLDER,
        )
        full_policy = SoliloquyVisibilityPolicy(
            content_hash_policy=SoliloquyContentHashPolicy.FULL_CONTENT,
        )
        h_placeholder = compute_soliloquy_content_hash(
            "sid", "ep", "seg", "agent", ts, chain, placeholder_policy
        )
        h_full = compute_soliloquy_content_hash(
            "sid", "ep", "seg", "agent", ts, chain, full_policy
        )
        assert h_placeholder != h_full

    def test_placeholder_ignores_chain_content(self):
        """HASH_PLACEHOLDER preserves the chain without exposing content."""
        ts = datetime.now(timezone.utc).isoformat()
        p = SoliloquyVisibilityPolicy(
            content_hash_policy=SoliloquyContentHashPolicy.HASH_PLACEHOLDER,
        )
        h1 = compute_soliloquy_content_hash(
            "sid", "ep", "seg", "agent", ts, ["chain-A"], p,
        )
        h2 = compute_soliloquy_content_hash(
            "sid", "ep", "seg", "agent", ts, ["chain-B-DIFFERENT"], p,
        )
        # Placeholder hash does not depend on chain content — just identity + ts
        assert h1 == h2

    def test_full_content_hash_changes_with_chain(self):
        ts = datetime.now(timezone.utc).isoformat()
        p = SoliloquyVisibilityPolicy(
            content_hash_policy=SoliloquyContentHashPolicy.FULL_CONTENT,
        )
        h1 = compute_soliloquy_content_hash("s", "e", "g", "a", ts, ["x"], p)
        h2 = compute_soliloquy_content_hash("s", "e", "g", "a", ts, ["y"], p)
        assert h1 != h2

    def test_deliberation_chain_hash_tamper_evident(self):
        h1 = compute_deliberation_chain_hash("sid", ["a", "b", "c"])
        h2 = compute_deliberation_chain_hash("sid", ["a", "b", "c"])
        h3 = compute_deliberation_chain_hash("sid", ["a", "b", "c-TAMPERED"])
        assert h1 == h2
        assert h1 != h3

    def test_aside_and_soliloquy_hashes_use_different_domains(self):
        """Domain separation: ASIDE: vs SOLILOQUY_*: produce different hashes
        for structurally equivalent preimages."""
        ts = datetime.now(timezone.utc).isoformat()
        aside_h = compute_aside_hash("x", "x", "x", "x", "x", ts, "x")
        concl_h = compute_soliloquy_conclusion_hash("x", "x", "x", ts)
        assert aside_h != concl_h


class TestGovernanceRules:
    def test_aside_must_be_human_initiated(self):
        with pytest.raises(AriadneGovernanceError):
            enforce_aside_human_initiated(None)
        with pytest.raises(AriadneGovernanceError):
            enforce_aside_human_initiated("")
        enforce_aside_human_initiated("devin")  # no raise

    def test_aside_target_agent_required(self):
        with pytest.raises(AriadneGovernanceError):
            enforce_aside_target_agent(None)
        enforce_aside_target_agent("clotho")

    def test_aside_close_reason_required(self):
        with pytest.raises(AriadneGovernanceError):
            enforce_aside_close_reason("")
        enforce_aside_close_reason("completed")

    def test_soliloquy_purpose_required(self):
        with pytest.raises(AriadneGovernanceError):
            enforce_soliloquy_purpose_required(None)
        enforce_soliloquy_purpose_required("decide")

    def test_soliloquy_human_accessible_non_negotiable(self):
        """Humans ALWAYS have read access — deployment cannot turn this off silently."""
        bad = SoliloquyVisibilityPolicy(human_accessible=False)
        with pytest.raises(AriadneGovernanceError):
            enforce_soliloquy_human_accessible(bad)
        good = SoliloquyVisibilityPolicy()
        enforce_soliloquy_human_accessible(good)

    def test_soliloquy_conclusion_summary_required(self):
        """Only the conclusion merges back — silence is not an exit."""
        with pytest.raises(AriadneGovernanceError):
            enforce_soliloquy_conclusion_required("")
        enforce_soliloquy_conclusion_required("decided")

    def test_aside_return_obligation_enforced_at_seal(self):
        # Open aside at seal → violation
        with pytest.raises(AriadneGovernanceError):
            check_aside_return_obligation(aside_open=True, episode_sealing=True)
        # Closed aside at seal → OK
        check_aside_return_obligation(aside_open=False, episode_sealing=True)
        # Open aside not at seal → OK
        check_aside_return_obligation(aside_open=True, episode_sealing=False)

    def test_soliloquy_return_obligation_enforced_at_seal(self):
        with pytest.raises(AriadneGovernanceError):
            check_soliloquy_return_obligation(
                soliloquy_active=True, episode_sealing=True,
            )
        check_soliloquy_return_obligation(
            soliloquy_active=False, episode_sealing=True,
        )


class TestDeltaPayloads:
    def test_aside_opened_has_forward_and_reverse(self):
        d = AsideOpenedDelta(
            parent_episode_id="ep",
            parent_segment_id="seg",
            aside_id="a",
            aside_label="lbl",
            initiated_by_human="h",
            target_agent_id="ag",
            reverse_delete_aside_id="a",
        )
        assert d.return_obligation is True

    def test_soliloquy_concluded_records_both_hashes(self):
        d = SoliloquyConcludedDelta(
            soliloquy_id="s",
            conclusion_summary="decided",
            conclusion_content_hash="pub",
            deliberation_chain_hash="priv",
            merged_into_segment_id="seg",
            reverse_restore_soliloquy_to_active="s",
        )
        assert d.conclusion_content_hash != d.deliberation_chain_hash


class TestEnums:
    def test_aside_status_values(self):
        assert AsideStatus.OPEN.value == "OPEN"
        assert AsideStatus.CLOSED.value == "CLOSED"

    def test_soliloquy_status_values(self):
        assert SoliloquyStatus.ACTIVE.value == "ACTIVE"
        assert SoliloquyStatus.CONCLUDED.value == "CONCLUDED"

    def test_content_hash_policy_values(self):
        assert SoliloquyContentHashPolicy.HASH_PLACEHOLDER.value == "HASH_PLACEHOLDER"
        assert SoliloquyContentHashPolicy.FULL_CONTENT.value == "FULL_CONTENT"
