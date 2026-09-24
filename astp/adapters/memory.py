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
The in-memory reference store — both adapter contracts over plain dicts.

``InMemoryStore`` implements ``ASTPAdapter`` (the Phase 1 node interface) and
``StructuralStore`` (the operations contract) with nothing behind them but
Python dicts. It is the store the protocol's own tests run the operations
against, the simplest conforming implementation an implementer can read, and
a seed for one of their own: every method is the whole of what the contract
asks of it.

It is deliberately not durable, not concurrent and not indexed. Records are
kept as the JSON form of the node models (``model_dump(mode="json")``: UUIDs
as strings, datetimes as ISO-8601 text, enums as their values), in the
public dict attributes named below, so a test or a caller can read them back
directly. Where the protocol's reference writer applies a rule before a write —
a link's endpoints must exist and respect mutual exclusivity, a membership
record must supersede an unsuperseded prior of the same episode and group, a
declaration's version must be SemVer — this store applies the same rule and
raises the same error.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from astp.adapters.base import ASTPAdapter, StructuralStore
from astp.core.schema import (
    AmendmentLink,
    CodicilNode,
    ConsultationNode,
    ConsultationParticipantNode,
    DocumentNode,
    EpisodeClosureRecord,
    EpisodeNode,
    EpisodeStatus,
    ExchangeEntry,
    ExclusionRecord,
    SealNode,
    SegmentNode,
    SignalNode,
)


def _dump(model: Any) -> Dict[str, Any]:
    """The JSON form of a node model, or a dict as given."""
    if isinstance(model, dict):
        return dict(model)
    return model.model_dump(mode="json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class InMemoryStore(ASTPAdapter, StructuralStore):
    """Both adapter contracts, in memory. See the module docstring."""

    def __init__(self):
        # Phase 1 nodes
        self.episodes: Dict[str, Dict[str, Any]] = {}
        self.segments: Dict[str, Dict[str, Any]] = {}
        self.signals: Dict[str, Dict[str, Any]] = {}
        self.seals: Dict[str, Dict[str, Any]] = {}
        self.exclusions: Dict[str, Dict[str, Any]] = {}
        self.documents: Dict[str, Dict[str, Any]] = {}
        self.consultations: Dict[str, Dict[str, Any]] = {}
        self.exchange_entries: Dict[str, Dict[str, Any]] = {}
        self.consultation_participants: Dict[str, Dict[str, Any]] = {}
        self.closure_records: Dict[str, Dict[str, Any]] = {}
        self.codicils: Dict[str, Dict[str, Any]] = {}
        self.context_entries: Dict[str, Dict[str, Any]] = {}      # SPEC 6.0.0 §4.8; posture lives on the episode dict
        self.amendment_links: Dict[str, Dict[str, Any]] = {}
        self.segment_references: List[Dict[str, Any]] = []   # {source, target, reference_type}
        # Structural record
        self.branch_points: Dict[str, Dict[str, Any]] = {}
        self.branch_termini: Dict[str, Dict[str, Any]] = {}
        self.branch_returns: List[Dict[str, Any]] = []
        self.fork_points: Dict[str, Dict[str, Any]] = {}
        self.departure_fork_points: Dict[str, Dict[str, Any]] = {}
        self.fork_returns: Dict[str, Dict[str, Any]] = {}
        self.merge_points: Dict[str, Dict[str, Any]] = {}
        self.asides: Dict[str, Dict[str, Any]] = {}
        self.aside_termini: Dict[str, Dict[str, Any]] = {}
        self.soliloquies: Dict[str, Dict[str, Any]] = {}
        self.soliloquy_conclusions: Dict[str, Dict[str, Any]] = {}
        self.fingerprints: Dict[str, Dict[str, Any]] = {}
        self.links: Dict[str, Dict[str, Any]] = {}
        self.membership_records: Dict[str, Dict[str, Any]] = {}
        self.declarations: Dict[str, Dict[str, Any]] = {}
        self.audit_records: List[Dict[str, Any]] = []
        self.intents: Dict[str, Dict[str, Any]] = {}
        self.wil_entries: Dict[str, Dict[str, Any]] = {}

    # ══════════════════════════════════════════════════════════════════════
    # ASTPAdapter — Phase 1 nodes
    # ══════════════════════════════════════════════════════════════════════

    async def initialize_schema(self) -> None:
        """Nothing to create: the dicts are the schema."""

    async def create_episode(self, episode: EpisodeNode) -> None:
        self.episodes.setdefault(str(episode.episode_id), _dump(episode))

    async def update_episode_status(self, episode_id: UUID, status: EpisodeStatus, **fields: Any) -> None:
        ep = self.episodes.get(str(episode_id))
        if ep is None:
            return
        ep["episode_status"] = status.value if isinstance(status, EpisodeStatus) else status
        for k, v in fields.items():
            ep[k] = v.isoformat() if isinstance(v, datetime) else (str(v) if isinstance(v, UUID) else v)

    async def get_episode(self, episode_id: UUID) -> Optional[Dict[str, Any]]:
        ep = self.episodes.get(str(episode_id))
        return dict(ep) if ep is not None else None

    async def create_segment(self, segment: SegmentNode, episode_status: EpisodeStatus) -> None:
        self.segments.setdefault(str(segment.segment_id), _dump(segment))

    async def list_segments(self, episode_id: UUID, limit: int = 100) -> List[Dict[str, Any]]:
        return self._episode_segments(str(episode_id))[:limit]

    async def create_signal(self, signal: SignalNode, episode_status: EpisodeStatus) -> None:
        self.signals.setdefault(str(signal.signal_id), _dump(signal))

    async def list_signals(self, episode_id: UUID, limit: int = 100) -> List[Dict[str, Any]]:
        rows = [dict(s) for s in self.signals.values() if s["episode_id"] == str(episode_id)]
        rows.sort(key=lambda s: s["received_at"])
        return rows[:limit]

    async def create_seal(self, seal: SealNode) -> None:
        self.seals.setdefault(str(seal.seal_id), _dump(seal))

    async def create_exclusion(self, exclusion: ExclusionRecord) -> None:
        self.exclusions.setdefault(str(exclusion.exclusion_id), _dump(exclusion))

    async def create_document(self, document: DocumentNode) -> None:
        self.documents.setdefault(str(document.document_id), _dump(document))

    async def create_consultation(self, consultation: ConsultationNode) -> None:
        self.consultations.setdefault(str(consultation.consultation_id), _dump(consultation))

    async def create_exchange_entry(self, entry: ExchangeEntry) -> None:
        self.exchange_entries.setdefault(str(entry.entry_id), _dump(entry))

    async def create_consultation_participant(self, participant: ConsultationParticipantNode) -> None:
        self.consultation_participants.setdefault(str(participant.participant_id), _dump(participant))

    async def create_closure_record(self, closure: EpisodeClosureRecord) -> None:
        self.closure_records.setdefault(str(closure.closure_id), _dump(closure))

    async def create_codicil(self, codicil: CodicilNode) -> None:
        self.codicils.setdefault(str(codicil.codicil_id), _dump(codicil))

    async def create_amendment_link(self, amendment: AmendmentLink) -> None:
        self.amendment_links.setdefault(str(amendment.amendment_id), _dump(amendment))

    async def list_episodes(self, workspace_id: Optional[str] = None, agent_id: Optional[str] = None,
                            status: Optional[EpisodeStatus] = None, limit: int = 50) -> List[Dict[str, Any]]:
        want_status = status.value if isinstance(status, EpisodeStatus) else status
        rows = [
            dict(e) for e in self.episodes.values()
            if (workspace_id is None or e.get("workspace_id") == workspace_id)
            and (agent_id is None or e.get("agent_id") == agent_id)
            and (want_status is None or e.get("episode_status") == want_status)
        ]
        rows.sort(key=lambda e: e.get("opened_at") or "", reverse=True)
        return rows[:limit]

    async def get_episode_detail(self, episode_id: UUID) -> Optional[Dict[str, Any]]:
        ep = self.episodes.get(str(episode_id))
        if ep is None:
            return None
        detail = dict(ep)
        detail["segment_count"] = len(self._episode_segments(str(episode_id)))
        detail["signal_count"] = sum(1 for s in self.signals.values() if s["episode_id"] == str(episode_id))
        return detail

    async def get_segment_by_id(self, episode_id: UUID, segment_id: UUID) -> Optional[Dict[str, Any]]:
        seg = self.segments.get(str(segment_id))
        if seg is None or seg.get("episode_id") != str(episode_id):
            return None  # episode scoping is a security requirement (ASI)
        return dict(seg)

    async def get_segment_range(self, episode_id: UUID, from_index: int, to_index: int,
                                segment_types: Optional[List[str]] = None,
                                authors: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        return [
            s for s in self._episode_segments(str(episode_id))
            if from_index <= s["sequence_index"] <= to_index
            and (segment_types is None or s.get("segment_type") in segment_types)
            and (authors is None or s.get("author") in authors)
        ]

    async def get_episode_spine(self, episode_id: UUID, limit: int = 20, before_index: Optional[int] = None,
                                segment_types: Optional[List[str]] = None,
                                retention_tier: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = [
            s for s in self._episode_segments(str(episode_id))
            if (before_index is None or s["sequence_index"] < before_index)
            and (segment_types is None or s.get("segment_type") in segment_types)
            and (retention_tier is None or s.get("retention_tier") == retention_tier)
        ]
        return rows[-limit:] if limit else rows

    async def create_segment_reference(self, source_segment_id: UUID, target_segment_id: UUID,
                                       reference_type: str) -> None:
        self.segment_references.append({
            "source": str(source_segment_id), "target": str(target_segment_id), "reference_type": reference_type,
        })

    def _episode_segments(self, episode_id: str) -> List[Dict[str, Any]]:
        rows = [dict(s) for s in self.segments.values() if s.get("episode_id") == episode_id]
        rows.sort(key=lambda s: s["sequence_index"])
        return rows

    # ══════════════════════════════════════════════════════════════════════
    # StructuralStore — the operations contract
    # ══════════════════════════════════════════════════════════════════════

    # ── Episodes ───────────────────────────────────────────────────────────

    def episode_status(self, episode_id: str) -> Optional[str]:
        ep = self.episodes.get(str(episode_id))
        return ep.get("episode_status") if ep is not None else None

    def episode_spine_hash(self, episode_id: str) -> Optional[str]:
        ep = self.episodes.get(str(episode_id))
        return (ep.get("spine_hash") or None) if ep is not None else None

    def episode_status_and_spine_hash(self, episode_id: str) -> Optional[tuple]:
        ep = self.episodes.get(str(episode_id))
        return (ep.get("episode_status"), ep.get("spine_hash")) if ep is not None else None

    def departure_fork_episode(self, fork_episode_id: Optional[str] = None,
                               fork_id: Optional[str] = None) -> tuple:
        if fork_episode_id:
            ep = self.episodes.get(str(fork_episode_id))
            return (str(fork_episode_id), ep.get("fork_status")) if ep is not None else (None, None)
        for eid, ep in self.episodes.items():
            if ep.get("fork_id") is not None and str(ep["fork_id"]) == str(fork_id):
                return (eid, ep.get("fork_status"))
        return (None, None)

    def write_departure_fork_episode(self, episode: Any) -> None:
        self.episodes.setdefault(str(episode.episode_id), _dump(episode))

    def set_episode_fork_return_type(self, episode_id: str, return_type: str) -> None:
        ep = self.episodes.get(str(episode_id))
        if ep is not None:
            ep["fork_return_type"] = return_type

    def mark_departure_fork_status(self, fork_episode_id: str, status: str) -> None:
        ep = self.episodes.get(str(fork_episode_id))
        if ep is not None:
            ep["fork_status"] = status
            ep["fork_status_updated_at"] = _now()

    def set_departure_fork_anchor_index(self, fork_episode_id: str, anchor_index: int) -> None:
        ep = self.episodes.get(str(fork_episode_id))
        if ep is not None:
            ep["fork_anchor_index"] = anchor_index

    # ── Segments ───────────────────────────────────────────────────────────

    def segment_sequence_index(self, segment_id: str) -> Optional[int]:
        seg = self.segments.get(str(segment_id))
        return seg.get("sequence_index") if seg is not None else None

    def segment_content_hashes(self, segment_ids) -> Dict[str, tuple]:
        found = {}
        for sid in segment_ids:
            seg = self.segments.get(str(sid))
            if seg is not None and seg.get("content_hash"):
                found[str(sid)] = (seg.get("sequence_index"), seg["content_hash"])
        return found

    def spine_segments(self, episode_id: str) -> List[Any]:
        from astp.core.schema import ASTP_SCHEMA_VERSION
        from astp.core.seal_v2 import SegmentSealInput
        return [
            SegmentSealInput(
                node_id=UUID(str(s["segment_id"])), node_type="segment",
                schema_version=s.get("schema_version") or ASTP_SCHEMA_VERSION,
                sequence_index=int(s["sequence_index"]), content_hash=s["content_hash"],
                parent_node_id=UUID(str(episode_id)),
            )
            for s in self._episode_segments(str(episode_id))
            if s.get("content_hash") and s.get("retention_tier", "PERSISTENT") != "EPHEMERAL"
        ]

    # ── Branches ───────────────────────────────────────────────────────────

    def write_branch_point(self, branch_point: Any) -> None:
        self.branch_points.setdefault(str(branch_point.branch_point_id), _dump(branch_point))

    def branch_point_with_terminus(self, branch_id: str) -> Optional[tuple]:
        bp = next((b for b in self.branch_points.values() if str(b.get("branch_id")) == str(branch_id)), None)
        if bp is None:
            return None
        has_terminus = any(str(t.get("branch_id")) == str(branch_id) for t in self.branch_termini.values())
        return (dict(bp), has_terminus)

    def write_branch_terminus(self, terminus: Any) -> None:
        self.branch_termini.setdefault(str(terminus.terminus_id), _dump(terminus))

    def write_branch_return_edge(self, branch_return: Any) -> None:
        self.branch_returns.append(_dump(branch_return))

    def find_common_ancestor(self, branch_id: str, target_episode_id: str) -> Optional[dict]:
        bp = next((b for b in self.branch_points.values() if str(b.get("branch_id")) == str(branch_id)), None)
        if bp is None or str(bp.get("parent_episode_id")) != str(target_episode_id):
            return None
        return {
            "common_ancestor_node_id": bp.get("source_segment_id"),
            "branch_point_id": bp.get("branch_point_id"),
            "parent_episode_id": bp.get("parent_episode_id"),
            "anchor_merkle": bp.get("spine_merkle_snapshot"),
        }

    # ── Forks ──────────────────────────────────────────────────────────────

    def write_fork_point(self, fork_point: Any) -> None:
        row = _dump(fork_point)
        row.setdefault("fork_status", "ACTIVE")
        self.fork_points.setdefault(str(fork_point.fork_point_id), row)

    def fork_points_of(self, fork_id: str) -> List[dict]:
        return [
            {"fpid": fp["fork_point_id"], "eid": fp["episode_id"],
             "status": fp.get("fork_status", "ACTIVE"), "origin_id": fp.get("origin_episode_id")}
            for fp in self.fork_points.values() if str(fp.get("fork_id")) == str(fork_id)
        ]

    def mark_fork_point_status(self, fork_point_id: str, status: str) -> None:
        fp = self.fork_points.get(str(fork_point_id))
        if fp is not None:
            fp["fork_status"] = status
            fp["resolved_at"] = _now()

    def write_departure_fork_point(self, fork_point: Any) -> None:
        self.departure_fork_points.setdefault(str(fork_point.fork_point_id), _dump(fork_point))

    def departure_fork_point_by_fork(self, fork_id: str) -> Optional[dict]:
        for fp in self.departure_fork_points.values():
            if str(fp.get("fork_id")) == str(fork_id):
                return {"pid": fp.get("fork_point_id"), "eid": fp.get("fork_episode_id"),
                        "tip": fp.get("spine_tip_hash_at_departure")}
        return None

    def write_fork_return_node(self, fork_return: Any) -> None:
        self.fork_returns.setdefault(str(fork_return.fork_return_id), _dump(fork_return))

    def fork_return_exists(self, fork_id: str) -> bool:
        return any(str(fr.get("fork_id")) == str(fork_id) for fr in self.fork_returns.values())

    # ── Merges ─────────────────────────────────────────────────────────────

    def write_merge_point(self, merge_point: Any) -> None:
        self.merge_points.setdefault(str(merge_point.merge_point_id), _dump(merge_point))

    def merge_point(self, merge_id: str) -> Optional[dict]:
        mp = next((m for m in self.merge_points.values() if str(m.get("merge_id")) == str(merge_id)), None)
        return dict(mp) if mp is not None else None

    def merge_executed_forward_delta(self, merge_id: str) -> Optional[str]:
        for a in self.audit_records:
            if a.get("delta_type") == "MERGE_EXECUTED" and str(merge_id) in str(a.get("forward_delta", "")):
                return a.get("forward_delta") or None
        return None

    # ── Asides and soliloquies ─────────────────────────────────────────────

    def write_aside(self, aside: Any) -> None:
        row = _dump(aside)
        row.setdefault("aside_status", "OPEN")
        self.asides.setdefault(str(aside.aside_id), row)

    def write_aside_terminus(self, terminus: Any) -> None:
        self.aside_termini.setdefault(str(terminus.aside_terminus_id), _dump(terminus))
        aside = self.asides.get(str(terminus.aside_id))
        if aside is not None:
            aside["aside_status"] = "CLOSED"

    def load_aside(self, aside_id: str) -> Optional[dict]:
        aside = self.asides.get(str(aside_id))
        if aside is None:
            return None
        is_closed = any(str(t.get("aside_id")) == str(aside_id) for t in self.aside_termini.values())
        return {"aside": dict(aside), "is_closed": is_closed}

    def scan_aside_external_references(self, aside_id: str, content_refs: List[str]) -> List[str]:
        if not content_refs:
            return []
        internal = {str(r) for r in content_refs}
        offenders = []
        for ref in self.segment_references:
            if ref["target"] in internal and ref["source"] not in internal and ref["source"] not in offenders:
                offenders.append(ref["source"])
        return offenders

    def write_soliloquy(self, soliloquy: Any) -> None:
        row = _dump(soliloquy)
        row.setdefault("soliloquy_status", "ACTIVE")
        self.soliloquies.setdefault(str(soliloquy.soliloquy_id), row)

    def write_soliloquy_conclusion(self, conclusion: Any) -> None:
        self.soliloquy_conclusions.setdefault(str(conclusion.conclusion_id), _dump(conclusion))
        sol = self.soliloquies.get(str(conclusion.soliloquy_id))
        if sol is not None:
            sol["soliloquy_status"] = "CONCLUDED"

    def load_soliloquy(self, soliloquy_id: str) -> Optional[dict]:
        sol = self.soliloquies.get(str(soliloquy_id))
        if sol is None:
            return None
        is_concluded = any(str(c.get("soliloquy_id")) == str(soliloquy_id) for c in self.soliloquy_conclusions.values())
        return {"soliloquy": dict(sol), "is_concluded": is_concluded}

    # ── Coherence ──────────────────────────────────────────────────────────

    def write_coherence_fingerprint(self, fingerprint: Any) -> None:
        self.fingerprints.setdefault(str(fingerprint.fingerprint_id), _dump(fingerprint))

    def recent_fingerprints(self, episode_id: str, limit: int = 10) -> List[dict]:
        rows = [dict(f) for f in self.fingerprints.values() if str(f.get("episode_id")) == str(episode_id)]
        rows.sort(key=lambda f: f.get("sequence_index", 0), reverse=True)
        return rows[:limit]

    def last_fingerprint(self, episode_id: str) -> Optional[dict]:
        rows = self.recent_fingerprints(episode_id, limit=1)
        return rows[0] if rows else None

    def last_nominal_segment(self, episode_id: str) -> Optional[str]:
        rows = [f for f in self.recent_fingerprints(episode_id, limit=len(self.fingerprints) or 1)
                if f.get("detection_state") == "NOMINAL"]
        return rows[0]["segment_id"] if rows else None

    # ── Cross-episode links and grouping ───────────────────────────────────

    def write_episode_link(self, link: Any) -> None:
        from astp.core.cross_episode import (
            EpisodeLink, LinkType, compute_episode_link_content_hash, enforce_link_mutual_exclusivity,
        )
        if not isinstance(link, EpisodeLink):
            raise TypeError(f"expected EpisodeLink, got {type(link).__name__}")
        src_id, tgt_id = str(link.source_episode), str(link.target_episode)
        src, tgt = self.episodes.get(src_id), self.episodes.get(tgt_id)
        if src is None or tgt is None:
            raise ValueError(
                f"Cannot create EpisodeLink: one or both endpoints not found (source={src_id}, target={tgt_id})"
            )
        # SPEC §20 →2: bind each end's Episode root when that end was sealed at link creation.
        if link.source_episode_root is None and src.get("sealed_at") and src.get("episode_root_hash"):
            link.source_episode_root = src["episode_root_hash"]
        if link.target_episode_root is None and tgt.get("sealed_at") and tgt.get("episode_root_hash"):
            link.target_episode_root = tgt["episode_root_hash"]
        existing_types = [
            LinkType(l["link_type"]) for l in self.links.values()
            if l["source_episode"] == src_id and l["target_episode"] == tgt_id
        ]
        enforce_link_mutual_exclusivity(link.link_type, existing_types)
        link.content_hash = compute_episode_link_content_hash(link)
        self.links[str(link.link_id)] = _dump(link)

    def write_membership_record(self, record: Any) -> None:
        from astp.core.grouping import MembershipRecord, compute_membership_record_content_hash
        if not isinstance(record, MembershipRecord):
            raise TypeError(f"expected MembershipRecord, got {type(record).__name__}")
        episode_id = str(record.episode_id)
        if episode_id not in self.episodes:
            raise ValueError(f"Cannot create MembershipRecord: episode {episode_id} not found")
        if not record.content_hash:
            record.content_hash = compute_membership_record_content_hash(record)
        prior = None
        if record.supersedes_record_id is not None:
            prior_id = str(record.supersedes_record_id)
            prior = self.membership_records.get(prior_id)
            if prior is None:
                raise ValueError(f"Cannot create MembershipRecord: prior record {prior_id} not found")
            if prior.get("superseded_by_record_id"):
                raise ValueError(f"Cannot supersede {prior_id}: already superseded by {prior['superseded_by_record_id']}")
            if prior["episode_id"] != episode_id:
                raise ValueError("Succession chain mismatch: new record's episode does not match prior's episode")
            if prior["group_id"] != record.group_id or prior["group_system"] != record.group_system:
                raise ValueError("Succession chain mismatch: new record's (group_id, group_system) does not match prior's")
        row = _dump(record)
        row["superseded_by_record_id"] = None  # forward pointer: set by the next succession
        self.membership_records[str(record.record_id)] = row
        if prior is not None:
            prior["superseded_by_record_id"] = str(record.record_id)

    def membership_record_role(self, record_id: str) -> Optional[str]:
        rec = self.membership_records.get(str(record_id))
        return rec.get("membership_role") if rec is not None else None

    def write_conformance_declaration(self, declaration: Any) -> None:
        from astp.core.grouping import (
            ConformanceDeclaration, compute_conformance_declaration_hash, enforce_semver_format,
        )
        if not isinstance(declaration, ConformanceDeclaration):
            raise TypeError(f"expected ConformanceDeclaration, got {type(declaration).__name__}")
        enforce_semver_format(declaration.declaration_version)
        if not declaration.declaration_hash:
            declaration.declaration_hash = compute_conformance_declaration_hash(declaration)
        self.declarations[str(declaration.declaration_id)] = _dump(declaration)

    def supersede_conformance_declaration(self, old_declaration_id: str, new_declaration_id: str) -> None:
        old, new = self.declarations.get(str(old_declaration_id)), self.declarations.get(str(new_declaration_id))
        if old is None or new is None:
            raise ValueError(
                f"Cannot link supersession: one or both declarations not found "
                f"(old={old_declaration_id}, new={new_declaration_id})"
            )
        old["superseded_by"] = str(new_declaration_id)

    # ── Audit chain, intents, write-intent ledger ──────────────────────────

    def write_audit_record(self, audit: Any) -> None:
        row = _dump(audit)
        # Deltas are stored as JSON text (SPEC §8: canonical JSON, stored as hashed);
        # the operations read them back as text.
        for key in ("forward_delta", "reverse_delta"):
            if not isinstance(row.get(key), str):
                row[key] = json.dumps(row.get(key) or {}, default=str)
        self.audit_records.append(row)

    def _chain(self, chain_key: str) -> List[Dict[str, Any]]:
        return [a for a in self.audit_records if str(a.get("episode_id")) == str(chain_key)]

    def max_delta_sequence(self, chain_key: str) -> Optional[int]:
        seqs = [a["delta_sequence"] for a in self._chain(chain_key) if a.get("delta_sequence") is not None]
        return max(seqs) if seqs else None

    def latest_audit_record_hash(self, chain_key: str) -> Optional[str]:
        chain = sorted(self._chain(chain_key), key=lambda a: a.get("delta_sequence", 0), reverse=True)
        return (chain[0].get("record_hash") or None) if chain else None

    def acquire_intent(self, idempotency_key: str, intent_type: str, initiator_id: str) -> tuple:
        existing = self.intents.get(idempotency_key)
        if existing is not None and existing.get("status") in ("COMPLETE", "PENDING"):
            return dict(existing), False
        intent = {
            "intent_id": str(uuid4()), "idempotency_key": idempotency_key, "intent_type": intent_type,
            "initiator_id": initiator_id, "status": "PENDING", "created_at": _now(),
        }
        self.intents[idempotency_key] = intent
        return {"intent_id": intent["intent_id"], "idempotency_key": idempotency_key, "status": "PENDING"}, True

    def complete_intent(self, idempotency_key: str, result_node_id: str) -> None:
        intent = self.intents.get(idempotency_key)
        if intent is not None and intent.get("status") == "PENDING":
            intent["status"] = "COMPLETE"
            intent["completed_at"] = _now()
            intent["result_node_id"] = result_node_id

    # ── Context commitment (SPEC 6.0.0) ─────────────────────────────────────

    def write_context_entry(self, entry: Any) -> None:
        d = _dump(entry)
        if d["entry_id"] in self.context_entries:
            raise ValueError(f"context entry {d['entry_id']} already exists: entries are append-only")
        self.context_entries[d["entry_id"]] = d

    def context_entry(self, entry_id: str) -> Optional[dict]:
        d = self.context_entries.get(entry_id)
        return dict(d) if d else None

    def context_entries_of(self, episode_id: str) -> List[dict]:
        return [dict(d) for d in self.context_entries.values() if d["episode_id"] == episode_id]

    def set_capture_posture(self, episode_id: str, posture: str) -> None:
        ep = self.episodes.get(episode_id)
        if ep is None:
            raise ValueError(f"episode {episode_id} does not exist")
        ep["capture_posture"] = posture

    def capture_posture(self, episode_id: str) -> Optional[str]:
        ep = self.episodes.get(episode_id)
        return ep.get("capture_posture") if ep else None

    def tombstone_context_entry(self, entry_id: str, tombstone: Any, codicil: Any) -> None:
        d = self.context_entries.get(entry_id)
        if d is None:
            raise ValueError(f"context entry {entry_id} does not exist")
        c = _dump(codicil)
        self.codicils.setdefault(c["codicil_id"], c)
        d["content_ref"] = None
        d["salt_ref"] = None
        d["erasure_state"] = "tombstoned"

    def write_completed_wil_entry(self, intent_id: str, operation: str, episode_id: str,
                                  node_id: str, timestamp: str) -> None:
        self.wil_entries.setdefault(intent_id, {
            "intent_id": intent_id, "operation": operation, "episode_id": episode_id,
            "stores_involved": ["authoritative_structural"],
            "pre_state_hash": node_id, "post_state_hash": node_id,
            "initiated_at": timestamp, "completed_at": timestamp,
            "status": "COMPLETE", "last_completed_store": "authoritative_structural",
        })
