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
The in-memory reference store (``astp.adapters.memory.InMemoryStore``).

It is both adapter contracts with nothing behind them; these tests are the
rules the reference writer applies before a write (link endpoints and
mutual exclusivity, membership succession, declaration versions), the
operations that run end to end through it with an audit chain, and the
Phase 1 node interface's reads.
"""

import asyncio
from uuid import uuid4

import pytest

from astp.adapters.base import ASTPAdapter, StructuralStore
from astp.adapters.memory import InMemoryStore
from astp.core.cross_episode import EpisodeLink, LinkGovernanceError, LinkType, assert_episode_link
from astp.core.grouping import (
    Capability,
    ConformanceDeclaration,
    GroupingGovernanceError,
    MembershipRecord,
    MembershipRole,
    assert_membership_record,
    bump_conformance_declaration,
    register_conformance_declaration,
)
from astp.core.schema import EpisodeNode, EpisodeStatus, SegmentNode, SegmentType


def _episode(store, **fields):
    eid = str(uuid4())
    store.episodes[eid] = {"episode_id": eid, "episode_status": "ACTIVE", "spine_hash": f"spine-{eid[:8]}", **fields}
    return eid


def _link(src, tgt, link_type=LinkType.CONTINUES_FROM):
    return EpisodeLink(source_episode=src, target_episode=tgt, created_by="agent-a",
                       link_type=link_type, link_strength=0.8, is_inferred=False)


def _membership(eid, **overrides):
    base = dict(episode_id=eid, group_id="g", group_system="example:Collection",
                asserted_by="human-1", membership_role=MembershipRole.PRIMARY)
    base.update(overrides)
    return MembershipRecord(**base)


def _declaration(**overrides):
    base = dict(group_id="g", group_system="example:Collection", declared_by="agent-a",
                declaration_version="1.0.0", capabilities=[Capability(capability_id="supports_archival")])
    base.update(overrides)
    return ConformanceDeclaration(**base)


def test_is_both_contracts():
    store = InMemoryStore()
    assert isinstance(store, ASTPAdapter) and isinstance(store, StructuralStore)


# ── Links ──────────────────────────────────────────────────────────────────

class TestEpisodeLinks:
    def test_both_endpoints_must_exist(self):
        store = InMemoryStore()
        src = _episode(store)
        with pytest.raises(ValueError, match="endpoints not found"):
            store.write_episode_link(_link(src, uuid4()))
        assert store.links == {}

    def test_mutual_exclusivity_is_enforced_against_existing_links(self):
        store = InMemoryStore()
        src, tgt = _episode(store), _episode(store)
        store.write_episode_link(_link(src, tgt, LinkType.CONTINUES_FROM))
        with pytest.raises(LinkGovernanceError):
            store.write_episode_link(_link(src, tgt, LinkType.SUPERSEDES))
        assert len(store.links) == 1

    def test_sealed_endpoint_root_is_bound_and_hash_stamped(self):
        store = InMemoryStore()
        src = _episode(store, sealed_at="2026-09-21T00:00:00+00:00", episode_root_hash="ab" * 32)
        tgt = _episode(store)  # unsealed: root stays None
        link = _link(src, tgt)
        store.write_episode_link(link)
        assert link.source_episode_root == "ab" * 32
        assert link.target_episode_root is None
        assert link.content_hash and len(link.content_hash) == 64
        assert store.links[str(link.link_id)]["content_hash"] == link.content_hash

    def test_assert_episode_link_runs_end_to_end_with_an_audit_record(self):
        store = InMemoryStore()
        src, tgt = _episode(store), _episode(store)
        link = assert_episode_link(store, _link(src, tgt), session_id="s-1", explicit_reason="continues")
        assert str(link.link_id) in store.links
        chain = [a for a in store.audit_records if a["episode_id"] == src]
        assert [a["delta_type"] for a in chain] == ["LINK_ACCEPTED"]
        assert chain[0]["delta_sequence"] == 1 and chain[0]["prior_audit_hash"] == "GENESIS"


# ── Grouping ───────────────────────────────────────────────────────────────

class TestMembershipRecords:
    def test_episode_must_exist(self):
        store = InMemoryStore()
        with pytest.raises(ValueError, match="not found"):
            store.write_membership_record(_membership(uuid4()))

    def test_hash_is_stamped_and_succession_sets_the_forward_pointer(self):
        store = InMemoryStore()
        eid = _episode(store)
        first = _membership(eid)
        store.write_membership_record(first)
        assert first.content_hash and store.membership_records[str(first.record_id)]["superseded_by_record_id"] is None
        second = _membership(eid, membership_role=MembershipRole.SUPPORTING,
                             supersedes_record_id=first.record_id, succession_reason="role changed")
        store.write_membership_record(second)
        assert store.membership_records[str(first.record_id)]["superseded_by_record_id"] == str(second.record_id)
        assert store.membership_record_role(str(first.record_id)) == "PRIMARY"

    def test_succession_refuses_a_missing_superseded_or_mismatched_prior(self):
        store = InMemoryStore()
        eid, other = _episode(store), _episode(store)
        first = _membership(eid)
        store.write_membership_record(first)
        with pytest.raises(ValueError, match="not found"):
            store.write_membership_record(_membership(eid, supersedes_record_id=uuid4()))
        with pytest.raises(ValueError, match="does not match prior's episode"):
            store.write_membership_record(_membership(other, supersedes_record_id=first.record_id))
        with pytest.raises(ValueError, match="does not match prior's"):
            store.write_membership_record(_membership(eid, group_id="other-group", supersedes_record_id=first.record_id))
        store.write_membership_record(_membership(eid, supersedes_record_id=first.record_id))
        with pytest.raises(ValueError, match="already superseded"):
            store.write_membership_record(_membership(eid, supersedes_record_id=first.record_id))

    def test_assert_membership_record_emits_created_then_superseded(self):
        store = InMemoryStore()
        eid = _episode(store)
        first = assert_membership_record(store, _membership(eid))
        assert_membership_record(store, _membership(eid, membership_role=MembershipRole.ARCHIVED,
                                                    supersedes_record_id=first.record_id, succession_reason="archived"))
        types = [a["delta_type"] for a in sorted(store.audit_records, key=lambda a: a["delta_sequence"])]
        assert types == ["MEMBERSHIP_RECORD_CREATED", "MEMBERSHIP_RECORD_CREATED", "MEMBERSHIP_RECORD_SUPERSEDED"]


class TestConformanceDeclarations:
    def test_version_must_be_semver_and_hash_is_stamped(self):
        store = InMemoryStore()
        with pytest.raises(GroupingGovernanceError):
            store.write_conformance_declaration(_declaration(declaration_version="v1"))
        d = _declaration()
        store.write_conformance_declaration(d)
        assert d.declaration_hash and store.declarations[str(d.declaration_id)]["declaration_hash"] == d.declaration_hash

    def test_supersession_needs_both_declarations(self):
        store = InMemoryStore()
        d = _declaration()
        store.write_conformance_declaration(d)
        with pytest.raises(ValueError, match="not found"):
            store.supersede_conformance_declaration(str(d.declaration_id), str(uuid4()))

    def test_register_then_bump_records_the_bump_on_a_synthetic_chain(self):
        store = InMemoryStore()
        first = register_conformance_declaration(store, _declaration())
        assert store.audit_records == []  # registration itself is not audited (§11.4)
        new, kind = bump_conformance_declaration(
            store, _declaration(declaration_version="1.1.0"), str(first.declaration_id), prior_version="1.0.0",
        )
        assert kind == "minor"
        assert store.declarations[str(first.declaration_id)]["superseded_by"] == str(new.declaration_id)
        chain_keys = {a["episode_id"] for a in store.audit_records}
        assert chain_keys == {"declaration:example:Collection:g"}


# ── Phase 1 node interface ─────────────────────────────────────────────────

class TestPhaseOneInterface:
    def _seeded(self):
        store = InMemoryStore()
        ep = EpisodeNode(agent_id="agent-a", workspace_id="ws-1")

        async def seed():
            await store.create_episode(ep)
            for i, kind in enumerate([SegmentType.CONVERSATION, SegmentType.REASONING, SegmentType.CONVERSATION]):
                await store.create_segment(SegmentNode(
                    episode_id=ep.episode_id, segment_type=kind, sequence_index=i,
                    content_hash="00" * 32, content_ref=f"mem://{i}", author="agent-a" if i else "user",
                ), EpisodeStatus.ACTIVE)
        asyncio.run(seed())
        return store, ep

    def test_episode_and_segments_round_trip(self):
        store, ep = self._seeded()
        detail = asyncio.run(store.get_episode_detail(ep.episode_id))
        assert detail["segment_count"] == 3 and detail["signal_count"] == 0
        assert [e["episode_id"] for e in asyncio.run(store.list_episodes(workspace_id="ws-1"))] == [str(ep.episode_id)]
        assert asyncio.run(store.list_episodes(workspace_id="elsewhere")) == []

    def test_reads_are_ordered_filtered_and_episode_scoped(self):
        store, ep = self._seeded()
        spine = asyncio.run(store.get_episode_spine(ep.episode_id, limit=2))
        assert [s["sequence_index"] for s in spine] == [1, 2]
        before = asyncio.run(store.get_episode_spine(ep.episode_id, limit=5, before_index=2))
        assert [s["sequence_index"] for s in before] == [0, 1]
        rng = asyncio.run(store.get_segment_range(ep.episode_id, 0, 2, segment_types=["CONVERSATION"]))
        assert [s["sequence_index"] for s in rng] == [0, 2]
        by_author = asyncio.run(store.get_segment_range(ep.episode_id, 0, 2, authors=["user"]))
        assert [s["sequence_index"] for s in by_author] == [0]
        sid = spine[0]["segment_id"]
        assert asyncio.run(store.get_segment_by_id(ep.episode_id, sid))["segment_id"] == sid
        assert asyncio.run(store.get_segment_by_id(uuid4(), sid)) is None  # never across Episodes

    def test_status_update_and_references_feed_the_structural_contract(self):
        store, ep = self._seeded()
        asyncio.run(store.update_episode_status(ep.episode_id, EpisodeStatus.SEALED, episode_root_hash="cd" * 32))
        assert store.episode_status(str(ep.episode_id)) == "SEALED"
        segs = asyncio.run(store.list_segments(ep.episode_id))
        asyncio.run(store.create_segment_reference(segs[2]["segment_id"], segs[0]["segment_id"], "REFERENCES"))
        assert store.scan_aside_external_references("aside", [segs[0]["segment_id"]]) == [segs[2]["segment_id"]]
        assert store.segment_content_hashes([segs[0]["segment_id"]]) == {segs[0]["segment_id"]: (0, "00" * 32)}
