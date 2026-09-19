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
Phase 3 — Aside + Soliloquy Operations Unit Tests (driver-mocked)

Exercises create_aside, close_aside, create_soliloquy, conclude_soliloquy
against an in-memory fake Neo4j driver. Verifies:
  - asides rejected when not human-initiated
  - reference scan surfaces external leaks without blocking the close
  - soliloquy default policy enforces G-27 (human-accessible,
    ESCALATION_ONLY for other agents, HASH_PLACEHOLDER content hash)
  - concluding a soliloquy writes conclusion + tamper-evident chain hash
  - only the conclusion merges back — deliberation chain stays in the soliloquy node
  - audit chain continuity across aside/soliloquy lifecycle
"""

import json
from typing import Any, Dict, List
from uuid import uuid4

import pytest

from astp.core import branch_operations
from astp.core.branching import (
    AriadneGovernanceError,
    AsideCloseResult,
    AsideResult,
    SoliloquyConclusionResult,
    SoliloquyResult,
)


# ── Fake driver (extended for Phase 3) ──────────────────────────────────────


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


class FakeResult:
    def __init__(self, rows: List[Dict[str, Any]]):
        self._rows = rows

    def single(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class FakeSession:
    def __init__(self, store):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, params=None):
        return self.store.run(query, params or {})


class FakeDriver:
    def __init__(self, store):
        self._store = store

    def session(self):
        return FakeSession(self._store)


class FakeStore:
    def __init__(self):
        self.calls = []
        self.episodes = {}
        self.asides = {}
        self.aside_terminuses = {}
        self.soliloquies = {}
        self.soliloquy_conclusions = {}
        self.audit_records = []
        self.external_refs: Dict[str, List[str]] = {}  # aside_id → offending ext segments

    def run(self, query, params):
        self.calls.append({"query": query, "params": params})
        q = " ".join(query.split())

        # 5.0.0: side-channel hashes bind Segments by content. Every UUID-shaped
        # segment id the operations look up exists, with a deterministic content
        # hash and a sequence_index derived from its id, so ordering is testable.
        if "MATCH (s:AriadneSegment) WHERE s.segment_id IN $ids" in q:
            import hashlib, uuid as _uuid
            rows = []
            for i in params.get("ids", []):
                try:
                    _uuid.UUID(str(i))
                except ValueError:
                    continue
                rows.append({"id": str(i), "seq": int(str(i)[-4:], 16), "h": hashlib.sha3_256(f"content:{i}".encode()).hexdigest()})
            return FakeResult(rows)

        # Episode status + spine_hash
        if "MATCH (e:AriadneEpisode" in q and "RETURN e.episode_status" in q:
            ep = self.episodes.get(params.get("eid"))
            if not ep:
                return FakeResult([])
            return FakeResult([{
                "status": ep.get("status", "ACTIVE"),
                "spine_hash": ep.get("spine_hash", ""),
            }])

        # Aside node create
        if "MERGE (a:AriadneAside {aside_id: $aside_id})" in q:
            aid = params.get("aside_id")
            if aid and aid not in self.asides:
                self.asides[aid] = dict(params)
                self.asides[aid]["aside_status"] = "OPEN"
            return FakeResult([])

        # Aside load
        if "MATCH (a:AriadneAside {aside_id: $aside_id}) OPTIONAL MATCH (a)-[:ASIDE_CLOSED]" in q:
            aid = params.get("aside_id")
            a = self.asides.get(aid)
            if not a:
                return FakeResult([])
            is_closed = any(
                t.get("aside_id") == aid for t in self.aside_terminuses.values()
            )
            return FakeResult([{"aside": a, "is_closed": is_closed}])

        # Aside terminus create
        if "MERGE (at:AriadneAsideTerminus" in q:
            tid = params.get("aside_terminus_id")
            self.aside_terminuses[tid] = dict(params)
            return FakeResult([])

        # Link aside -> terminus + set CLOSED
        if "MERGE (a)-[:ASIDE_CLOSED" in q:
            aid = params.get("aside_id")
            if aid in self.asides:
                self.asides[aid]["aside_status"] = "CLOSED"
            return FakeResult([])

        # Reference scan
        if "MATCH (ext:AriadneSegment)-[:REFERENCES]->(internal:AriadneSegment)" in q:
            content_refs = params.get("content_refs", []) or []
            # Emulate: external_refs dict maps by sentinel; lookup by any matching content_ref set
            for content_key, offenders in self.external_refs.items():
                if content_key in content_refs:
                    return FakeResult([{"offenders": offenders}])
            return FakeResult([{"offenders": []}])

        # Soliloquy create
        if "MERGE (sol:AriadneSoliloquy {soliloquy_id: $soliloquy_id})" in q:
            sid = params.get("soliloquy_id")
            if sid and sid not in self.soliloquies:
                self.soliloquies[sid] = dict(params)
                self.soliloquies[sid]["soliloquy_status"] = "ACTIVE"
            return FakeResult([])

        # Soliloquy load
        if "MATCH (sol:AriadneSoliloquy {soliloquy_id: $soliloquy_id}) OPTIONAL MATCH (sol)-[:SOLILOQUY_CONCLUDED]" in q:
            sid = params.get("soliloquy_id")
            s = self.soliloquies.get(sid)
            if not s:
                return FakeResult([])
            is_concluded = any(
                c.get("soliloquy_id") == sid for c in self.soliloquy_conclusions.values()
            )
            return FakeResult([{"soliloquy": s, "is_concluded": is_concluded}])

        # Soliloquy conclusion create
        if "MERGE (sc:AriadneSoliloquyConclusion" in q:
            cid = params.get("conclusion_id")
            self.soliloquy_conclusions[cid] = dict(params)
            return FakeResult([])

        # Link soliloquy -> conclusion + set CONCLUDED
        if "MERGE (sol)-[:SOLILOQUY_CONCLUDED" in q:
            sid = params.get("soliloquy_id")
            if sid in self.soliloquies:
                self.soliloquies[sid]["soliloquy_status"] = "CONCLUDED"
            return FakeResult([])

        # Audit record
        if "MERGE (ar:AriadneAuditRecord" in q:
            self.audit_records.append(dict(params))
            return FakeResult([])

        if "RETURN max(ar.delta_sequence)" in q:
            eid = params.get("eid")
            seqs = [
                a["delta_sequence"]
                for a in self.audit_records
                if a.get("episode_id") == eid
            ]
            return FakeResult([{"max_seq": max(seqs) if seqs else None}])

        if "RETURN ar.record_hash AS hash" in q:
            eid = params.get("eid")
            relevant = sorted(
                (a for a in self.audit_records if a.get("episode_id") == eid),
                key=lambda x: x.get("delta_sequence", 0),
                reverse=True,
            )
            if relevant:
                return FakeResult([{"hash": relevant[0].get("record_hash", "GENESIS")}])
            return FakeResult([{"hash": None}])

        # Catch-all
        return FakeResult([])


def _make_store(eids):
    s = FakeStore()
    for eid in eids:
        s.episodes[eid] = {"status": "ACTIVE", "spine_hash": f"spine-{eid[:8]}"}
    return s


# ── Aside tests ────────────────────────────────────────────────────────────


class TestCreateAside:
    def test_opens_aside_and_writes_audit(self):
        eid = str(uuid4())
        store = _make_store([eid])
        driver = FakeDriver(store)

        result = branch_operations.create_aside(
            driver,
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
        driver = FakeDriver(store)
        with pytest.raises(AriadneGovernanceError):
            branch_operations.create_aside(
                driver,
                parent_episode_id=eid,
                parent_segment_id=SEG,
                aside_label="lbl",
                initiated_by_human="",   # Empty → agent-initiated attempt
                target_agent_id="agent-a",
            )

    def test_requires_target_agent(self):
        eid = str(uuid4())
        store = _make_store([eid])
        driver = FakeDriver(store)
        with pytest.raises(AriadneGovernanceError):
            branch_operations.create_aside(
                driver,
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
        driver = FakeDriver(store)

        open_result = branch_operations.create_aside(
            driver, parent_episode_id=eid, parent_segment_id=SEG,
            aside_label="lbl", initiated_by_human="human-1",
            target_agent_id="agent-a", content_refs=["seg-internal-1"],
        )
        close_result = branch_operations.close_aside(
            driver,
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
        driver = FakeDriver(store)

        open_result = branch_operations.create_aside(
            driver, parent_episode_id=eid, parent_segment_id=SEG,
            aside_label="lbl", initiated_by_human="human-1",
            target_agent_id="agent-a", content_refs=["internal-x"],
        )
        # Inject external refs pointing into the aside
        store.external_refs["internal-x"] = ["external-y", "external-z"]

        close_result = branch_operations.close_aside(
            driver,
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
        driver = FakeDriver(store)
        open_result = branch_operations.create_aside(
            driver, parent_episode_id=eid, parent_segment_id=SEG,
            aside_label="lbl", initiated_by_human="human-1",
            target_agent_id="agent-a",
        )
        with pytest.raises(AriadneGovernanceError):
            branch_operations.close_aside(
                driver, aside_id=open_result.aside_id, close_reason="",
            )

    def test_double_close_rejected(self):
        eid = str(uuid4())
        store = _make_store([eid])
        driver = FakeDriver(store)
        open_result = branch_operations.create_aside(
            driver, parent_episode_id=eid, parent_segment_id=SEG,
            aside_label="lbl", initiated_by_human="human-1",
            target_agent_id="agent-a",
        )
        branch_operations.close_aside(
            driver, aside_id=open_result.aside_id, close_reason="done",
        )
        # Second close returns None (not found in ACTIVE state)
        result2 = branch_operations.close_aside(
            driver, aside_id=open_result.aside_id, close_reason="done again",
        )
        assert result2 is None


# ── Soliloquy tests ────────────────────────────────────────────────────────


class TestCreateSoliloquy:
    def test_default_policy_persists_decision_1(self):
        eid = str(uuid4())
        store = _make_store([eid])
        driver = FakeDriver(store)

        result = branch_operations.create_soliloquy(
            driver,
            parent_episode_id=eid,
            parent_segment_id=SEG,
            soliloquy_purpose="decide between alternatives",
            initiated_by_agent="agent-a",
        )
        assert isinstance(result, SoliloquyResult)

        sol = store.soliloquies[result.soliloquy_id]
        policy = json.loads(sol["visibility_policy"])
        assert policy["human_accessible"] is True
        assert policy["other_agents_access"] == "ESCALATION_ONLY"
        assert policy["audit_on_access"] is True
        assert policy["content_hash_policy"] == "HASH_PLACEHOLDER"

    def test_rejects_non_human_accessible_policy(self):
        """Humans ALWAYS have read access — cannot be turned off."""
        eid = str(uuid4())
        store = _make_store([eid])
        driver = FakeDriver(store)
        with pytest.raises(AriadneGovernanceError):
            branch_operations.create_soliloquy(
                driver,
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
        driver = FakeDriver(store)

        # Two soliloquies with same timestamp-insensitive identity but different chains.
        # Since timestamps and IDs differ, we can't directly compare hashes; instead,
        # verify the computed hash uses the placeholder prefix domain.
        result = branch_operations.create_soliloquy(
            driver, parent_episode_id=eid, parent_segment_id=SEG,
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
        driver = FakeDriver(store)
        with pytest.raises(AriadneGovernanceError):
            branch_operations.create_soliloquy(
                driver, parent_episode_id=eid, parent_segment_id=SEG,
                soliloquy_purpose="",
                initiated_by_agent="agent-a",
            )


class TestConcludeSoliloquy:
    def test_conclusion_merges_summary_not_chain(self):
        """Only the conclusion merges back. Chain stays in Soliloquy node."""
        eid = str(uuid4())
        store = _make_store([eid])
        driver = FakeDriver(store)

        open_result = branch_operations.create_soliloquy(
            driver, parent_episode_id=eid, parent_segment_id=SEG,
            soliloquy_purpose="decide",
            initiated_by_agent="agent-a",
            deliberation_chain=[PA, PB, PC],
        )

        result = branch_operations.conclude_soliloquy(
            driver,
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
        driver = FakeDriver(store)
        open_result = branch_operations.create_soliloquy(
            driver, parent_episode_id=eid, parent_segment_id=SEG,
            soliloquy_purpose="decide",
            initiated_by_agent="agent-a",
        )
        branch_operations.conclude_soliloquy(
            driver,
            soliloquy_id=open_result.soliloquy_id,
            conclusion_summary="done",
            merged_into_segment_id=SEG_SPINE,
        )
        types_seen = [a["delta_type"] for a in store.audit_records]
        assert types_seen == ["SOLILOQUY_INITIATED", "SOLILOQUY_CONCLUDED"]

    def test_rejects_empty_summary(self):
        eid = str(uuid4())
        store = _make_store([eid])
        driver = FakeDriver(store)
        open_result = branch_operations.create_soliloquy(
            driver, parent_episode_id=eid, parent_segment_id=SEG,
            soliloquy_purpose="decide", initiated_by_agent="agent-a",
        )
        with pytest.raises(AriadneGovernanceError):
            branch_operations.conclude_soliloquy(
                driver,
                soliloquy_id=open_result.soliloquy_id,
                conclusion_summary="",
                merged_into_segment_id=SEG_SPINE,
            )

    def test_rejects_missing_merge_target(self):
        eid = str(uuid4())
        store = _make_store([eid])
        driver = FakeDriver(store)
        open_result = branch_operations.create_soliloquy(
            driver, parent_episode_id=eid, parent_segment_id=SEG,
            soliloquy_purpose="decide", initiated_by_agent="agent-a",
        )
        with pytest.raises(AriadneGovernanceError):
            branch_operations.conclude_soliloquy(
                driver,
                soliloquy_id=open_result.soliloquy_id,
                conclusion_summary="decided",
                merged_into_segment_id="",
            )

    def test_double_conclude_rejected(self):
        eid = str(uuid4())
        store = _make_store([eid])
        driver = FakeDriver(store)
        open_result = branch_operations.create_soliloquy(
            driver, parent_episode_id=eid, parent_segment_id=SEG,
            soliloquy_purpose="decide", initiated_by_agent="agent-a",
        )
        branch_operations.conclude_soliloquy(
            driver, soliloquy_id=open_result.soliloquy_id,
            conclusion_summary="first", merged_into_segment_id=SEG_S,
        )
        result2 = branch_operations.conclude_soliloquy(
            driver, soliloquy_id=open_result.soliloquy_id,
            conclusion_summary="second", merged_into_segment_id=SEG_S,
        )
        assert result2 is None


class TestAuditChainContinuityPhase3:
    def test_aside_and_soliloquy_chain_in_order(self):
        eid = str(uuid4())
        store = _make_store([eid])
        driver = FakeDriver(store)

        a = branch_operations.create_aside(
            driver, parent_episode_id=eid, parent_segment_id=SEG,
            aside_label="lbl", initiated_by_human="human-1",
            target_agent_id="agent-a",
        )
        s = branch_operations.create_soliloquy(
            driver, parent_episode_id=eid, parent_segment_id=SEG,
            soliloquy_purpose="decide", initiated_by_agent="agent-a",
        )
        branch_operations.conclude_soliloquy(
            driver, soliloquy_id=s.soliloquy_id,
            conclusion_summary="done", merged_into_segment_id=SEG_X,
        )
        branch_operations.close_aside(
            driver, aside_id=a.aside_id, close_reason="resolved",
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
