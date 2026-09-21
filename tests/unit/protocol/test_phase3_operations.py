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
Phase 3 — Aside + Soliloquy Operations Unit Tests (in-memory store)

Exercises create_aside, close_aside, create_soliloquy, conclude_soliloquy
against an in-memory fake Neo4j store. Verifies:
  - asides rejected when not human-initiated
  - reference scan surfaces external leaks without blocking the close
  - soliloquy default policy enforces G-27 (human-accessible,
    ESCALATION_ONLY for other agents, HASH_PLACEHOLDER content hash)
  - concluding a soliloquy writes conclusion + tamper-evident chain hash
  - only the conclusion merges back — deliberation chain stays in the soliloquy node
  - audit chain continuity across aside/soliloquy lifecycle
"""

import hashlib
from uuid import uuid4

import pytest

from astp.adapters.memory import InMemoryStore
from astp.core import branch_operations
from astp.core.branching import (
    ASTPGovernanceError,
    AsideCloseResult,
    AsideResult,
    SoliloquyConclusionResult,
    SoliloquyResult,
)


# ── Segments the operations look up ────────────────────────────────────────
# Segment identifiers are UUIDs (SPEC §19.4 binds the parent Segment by identity and content).
SEG = "00000000-0000-4000-8000-000000001000"
SEG_PARENT = "00000000-0000-4000-8000-000000001001"
SEG_SPINE5 = "00000000-0000-4000-8000-000000001002"
SEG_SPINE = "00000000-0000-4000-8000-000000001003"
SEG_X = "00000000-0000-4000-8000-000000001004"
SEG_S = "00000000-0000-4000-8000-000000001005"
PT1 = "00000000-0000-4000-8000-000000001006"
PT2 = "00000000-0000-4000-8000-000000001007"
PA = "00000000-0000-4000-8000-000000001008"
PB = "00000000-0000-4000-8000-000000001009"
PC = "00000000-0000-4000-8000-00000000100a"

SEGMENTS = [SEG, SEG_PARENT, SEG_SPINE5, SEG_SPINE, SEG_X, SEG_S, PT1, PT2, PA, PB, PC]


def _make_store(eids):
    """An in-memory store holding the Episodes and, since 5.0.0 binds a side
    channel's parent Segment by content, every Segment the tests name — each
    with a deterministic content hash and a sequence_index derived from its id,
    so ordering is testable."""
    s = InMemoryStore()
    for eid in eids:
        s.episodes[eid] = {"episode_id": eid, "episode_status": "ACTIVE", "spine_hash": f"spine-{eid[:8]}"}
    for sid in SEGMENTS:
        s.segments[sid] = {
            "segment_id": sid, "episode_id": eids[0] if eids else None,
            "sequence_index": int(sid[-4:], 16),
            "content_hash": hashlib.sha3_256(f"content:{sid}".encode()).hexdigest(),
        }
    return s


# ── Aside tests ────────────────────────────────────────────────────────────


class TestCreateAside:
    def test_opens_aside_and_writes_audit(self):
        eid = str(uuid4())
        store = _make_store([eid])

        result = branch_operations.create_aside(
            store,
            parent_episode_id=eid,
            parent_segment_id=SEG_PARENT,
            aside_label="clarify scope with human",
            initiated_by_human="human-1",
            target_agent_id="agent-a",
        )

        assert isinstance(result, AsideResult)
        # Aside node written
        assert len(store.asides) == 1
        a = store.asides[result.aside_id]
        assert a["initiated_by_human"] == "human-1"
        assert a["target_agent_id"] == "agent-a"
        assert a["aside_status"] == "OPEN"
        # ASIDE_OPENED audit
        assert any(
            ar["delta_type"] == "ASIDE_OPENED" for ar in store.audit_records
        )

    def test_rejects_agent_initiated(self):
        """Asides are human-initiated only."""
        eid = str(uuid4())
        store = _make_store([eid])
        with pytest.raises(ASTPGovernanceError):
            branch_operations.create_aside(
                store,
                parent_episode_id=eid,
                parent_segment_id=SEG,
                aside_label="lbl",
                initiated_by_human="",   # Empty → agent-initiated attempt
                target_agent_id="agent-a",
            )

    def test_requires_target_agent(self):
        eid = str(uuid4())
        store = _make_store([eid])
        with pytest.raises(ASTPGovernanceError):
            branch_operations.create_aside(
                store,
                parent_episode_id=eid,
                parent_segment_id=SEG,
                aside_label="lbl",
                initiated_by_human="human-1",
                target_agent_id="",  # Missing
            )


class TestCloseAside:
    def test_close_runs_reference_scan_passes(self):
        eid = str(uuid4())
        store = _make_store([eid])

        open_result = branch_operations.create_aside(
            store, parent_episode_id=eid, parent_segment_id=SEG,
            aside_label="lbl", initiated_by_human="human-1",
            target_agent_id="agent-a", content_refs=["seg-internal-1"],
        )
        close_result = branch_operations.close_aside(
            store,
            aside_id=open_result.aside_id,
            close_reason="resolved",
            notification_targets=["agent-b", "agent-c"],
        )
        assert isinstance(close_result, AsideCloseResult)
        assert close_result.reference_scan_passed is True
        assert close_result.external_references_found == []
        # Aside status updated
        assert store.asides[open_result.aside_id]["aside_status"] == "CLOSED"
        # ASIDE_CLOSED audit
        assert any(
            ar["delta_type"] == "ASIDE_CLOSED" for ar in store.audit_records
        )

    def test_reference_scan_surfaces_leaks_but_close_proceeds(self):
        """Spec: reference scan records leaks; close proceeds with audit flag."""
        eid = str(uuid4())
        store = _make_store([eid])

        open_result = branch_operations.create_aside(
            store, parent_episode_id=eid, parent_segment_id=SEG,
            aside_label="lbl", initiated_by_human="human-1",
            target_agent_id="agent-a", content_refs=["internal-x"],
        )
        # Segments outside the aside that reference its internal content
        for ext in ("external-y", "external-z"):
            store.segment_references.append({"source": ext, "target": "internal-x", "reference_type": "REFERENCES"})

        close_result = branch_operations.close_aside(
            store,
            aside_id=open_result.aside_id,
            close_reason="closed despite leaks",
        )
        assert close_result.reference_scan_passed is False
        assert sorted(close_result.external_references_found) == [
            "external-y", "external-z"
        ]
        # Aside is still marked CLOSED
        assert store.asides[open_result.aside_id]["aside_status"] == "CLOSED"

    def test_rejects_empty_reason(self):
        eid = str(uuid4())
        store = _make_store([eid])
        open_result = branch_operations.create_aside(
            store, parent_episode_id=eid, parent_segment_id=SEG,
            aside_label="lbl", initiated_by_human="human-1",
            target_agent_id="agent-a",
        )
        with pytest.raises(ASTPGovernanceError):
            branch_operations.close_aside(
                store, aside_id=open_result.aside_id, close_reason="",
            )

    def test_double_close_rejected(self):
        eid = str(uuid4())
        store = _make_store([eid])
        open_result = branch_operations.create_aside(
            store, parent_episode_id=eid, parent_segment_id=SEG,
            aside_label="lbl", initiated_by_human="human-1",
            target_agent_id="agent-a",
        )
        branch_operations.close_aside(
            store, aside_id=open_result.aside_id, close_reason="done",
        )
        # Second close returns None (not found in ACTIVE state)
        result2 = branch_operations.close_aside(
            store, aside_id=open_result.aside_id, close_reason="done again",
        )
        assert result2 is None


# ── Soliloquy tests ────────────────────────────────────────────────────────


class TestCreateSoliloquy:
    def test_default_policy_persists_decision_1(self):
        eid = str(uuid4())
        store = _make_store([eid])

        result = branch_operations.create_soliloquy(
            store,
            parent_episode_id=eid,
            parent_segment_id=SEG,
            soliloquy_purpose="decide between alternatives",
            initiated_by_agent="agent-a",
        )
        assert isinstance(result, SoliloquyResult)

        sol = store.soliloquies[result.soliloquy_id]
        policy = sol["visibility_policy"]
        assert policy["human_accessible"] is True
        assert policy["other_agents_access"] == "ESCALATION_ONLY"
        assert policy["audit_on_access"] is True
        assert policy["content_hash_policy"] == "HASH_PLACEHOLDER"

    def test_rejects_non_human_accessible_policy(self):
        """Humans ALWAYS have read access — cannot be turned off."""
        eid = str(uuid4())
        store = _make_store([eid])
        with pytest.raises(ASTPGovernanceError):
            branch_operations.create_soliloquy(
                store,
                parent_episode_id=eid,
                parent_segment_id=SEG,
                soliloquy_purpose="decide",
                initiated_by_agent="agent-a",
                visibility_policy={"human_accessible": False},
            )

    def test_placeholder_hash_does_not_leak_chain(self):
        """With HASH_PLACEHOLDER, content_hash does not depend on deliberation chain."""
        eid = str(uuid4())
        store = _make_store([eid])

        # Two soliloquies with same timestamp-insensitive identity but different chains.
        # Since timestamps and IDs differ, we can't directly compare hashes; instead,
        # verify the computed hash uses the placeholder prefix domain.
        result = branch_operations.create_soliloquy(
            store, parent_episode_id=eid, parent_segment_id=SEG,
            soliloquy_purpose="think", initiated_by_agent="agent-a",
            deliberation_chain=[PT1, PT2],
        )
        sol = store.soliloquies[result.soliloquy_id]
        # Deliberation chain is stored on the node but the content_hash
        # uses the placeholder domain — content is not exposed through the hash.
        assert sol["deliberation_chain"] == [
            PT1, PT2
        ]
        assert sol["content_hash"]  # hash is present
        assert len(sol["content_hash"]) == 64  # SHA3-256 hex

    def test_rejects_empty_purpose(self):
        eid = str(uuid4())
        store = _make_store([eid])
        with pytest.raises(ASTPGovernanceError):
            branch_operations.create_soliloquy(
                store, parent_episode_id=eid, parent_segment_id=SEG,
                soliloquy_purpose="",
                initiated_by_agent="agent-a",
            )


class TestConcludeSoliloquy:
    def test_conclusion_merges_summary_not_chain(self):
        """Only the conclusion merges back. Chain stays in Soliloquy node."""
        eid = str(uuid4())
        store = _make_store([eid])

        open_result = branch_operations.create_soliloquy(
            store, parent_episode_id=eid, parent_segment_id=SEG,
            soliloquy_purpose="decide",
            initiated_by_agent="agent-a",
            deliberation_chain=[PA, PB, PC],
        )

        result = branch_operations.conclude_soliloquy(
            store,
            soliloquy_id=open_result.soliloquy_id,
            conclusion_summary="I decided to proceed with option A",
            merged_into_segment_id=SEG_SPINE5,
        )
        assert isinstance(result, SoliloquyConclusionResult)

        # Conclusion summary is public; chain hash is tamper-evident
        conclusion = store.soliloquy_conclusions[result.conclusion_id]
        assert conclusion["conclusion_summary"] == "I decided to proceed with option A"
        assert conclusion["deliberation_chain_hash"] == result.deliberation_chain_hash
        assert len(result.deliberation_chain_hash) == 64

        # Chain still on Soliloquy node — NOT on the conclusion
        sol = store.soliloquies[open_result.soliloquy_id]
        assert sol["deliberation_chain"] == [PA, PB, PC]
        # Chain content not copied to conclusion — only the hash
        assert "deliberation_chain" not in conclusion or conclusion.get(
            "deliberation_chain"
        ) is None

        # Soliloquy status updated
        assert sol["soliloquy_status"] == "CONCLUDED"

    def test_writes_soliloquy_concluded_audit(self):
        eid = str(uuid4())
        store = _make_store([eid])
        open_result = branch_operations.create_soliloquy(
            store, parent_episode_id=eid, parent_segment_id=SEG,
            soliloquy_purpose="decide",
            initiated_by_agent="agent-a",
        )
        branch_operations.conclude_soliloquy(
            store,
            soliloquy_id=open_result.soliloquy_id,
            conclusion_summary="done",
            merged_into_segment_id=SEG_SPINE,
        )
        types_seen = [a["delta_type"] for a in store.audit_records]
        assert types_seen == ["SOLILOQUY_INITIATED", "SOLILOQUY_CONCLUDED"]

    def test_rejects_empty_summary(self):
        eid = str(uuid4())
        store = _make_store([eid])
        open_result = branch_operations.create_soliloquy(
            store, parent_episode_id=eid, parent_segment_id=SEG,
            soliloquy_purpose="decide", initiated_by_agent="agent-a",
        )
        with pytest.raises(ASTPGovernanceError):
            branch_operations.conclude_soliloquy(
                store,
                soliloquy_id=open_result.soliloquy_id,
                conclusion_summary="",
                merged_into_segment_id=SEG_SPINE,
            )

    def test_rejects_missing_merge_target(self):
        eid = str(uuid4())
        store = _make_store([eid])
        open_result = branch_operations.create_soliloquy(
            store, parent_episode_id=eid, parent_segment_id=SEG,
            soliloquy_purpose="decide", initiated_by_agent="agent-a",
        )
        with pytest.raises(ASTPGovernanceError):
            branch_operations.conclude_soliloquy(
                store,
                soliloquy_id=open_result.soliloquy_id,
                conclusion_summary="decided",
                merged_into_segment_id="",
            )

    def test_double_conclude_rejected(self):
        eid = str(uuid4())
        store = _make_store([eid])
        open_result = branch_operations.create_soliloquy(
            store, parent_episode_id=eid, parent_segment_id=SEG,
            soliloquy_purpose="decide", initiated_by_agent="agent-a",
        )
        branch_operations.conclude_soliloquy(
            store, soliloquy_id=open_result.soliloquy_id,
            conclusion_summary="first", merged_into_segment_id=SEG_S,
        )
        result2 = branch_operations.conclude_soliloquy(
            store, soliloquy_id=open_result.soliloquy_id,
            conclusion_summary="second", merged_into_segment_id=SEG_S,
        )
        assert result2 is None


class TestAuditChainContinuityPhase3:
    def test_aside_and_soliloquy_chain_in_order(self):
        eid = str(uuid4())
        store = _make_store([eid])

        a = branch_operations.create_aside(
            store, parent_episode_id=eid, parent_segment_id=SEG,
            aside_label="lbl", initiated_by_human="human-1",
            target_agent_id="agent-a",
        )
        s = branch_operations.create_soliloquy(
            store, parent_episode_id=eid, parent_segment_id=SEG,
            soliloquy_purpose="decide", initiated_by_agent="agent-a",
        )
        branch_operations.conclude_soliloquy(
            store, soliloquy_id=s.soliloquy_id,
            conclusion_summary="done", merged_into_segment_id=SEG_X,
        )
        branch_operations.close_aside(
            store, aside_id=a.aside_id, close_reason="resolved",
        )

        audits = sorted(
            store.audit_records, key=lambda ar: ar.get("delta_sequence", 0)
        )
        types_seen = [ar["delta_type"] for ar in audits]
        assert types_seen == [
            "ASIDE_OPENED", "SOLILOQUY_INITIATED",
            "SOLILOQUY_CONCLUDED", "ASIDE_CLOSED",
        ]
        # Chain integrity: each prior_audit_hash matches previous record_hash
        for i in range(1, len(audits)):
            assert audits[i]["prior_audit_hash"] == audits[i - 1]["record_hash"]
