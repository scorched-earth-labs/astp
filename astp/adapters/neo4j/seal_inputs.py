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
What a version 2 seal reads from the graph (SPEC §5.2, §5.6, §5.7.1).

One reader for the seal path and the verifier, so the two cannot disagree
about which stored fields a seal is a function of. It returns exactly what
``astp.core.seal_v2.compute_episode_seal_v2`` consumes: the six fields of each
non-ephemeral Segment, the excluded content hashes, the SPINE Signal content
hashes, and the ``:v2:`` member hash of every structural node of the Episode.

Rules the mapping applies, stated here because a verifier must apply the same:

* A Segment's ``node_type`` is ``"segment"``; its parent is the Episode
  (§3.4.1). A Segment stored without ``schema_version`` is schema ``1.2.0`` —
  the only Segment schema that ever existed without the field on the node.
* Timestamps are stored as ISO 8601 text; ``parent_hash`` stored as the 4.x text
  ``"GENESIS"`` is NULL.
* A HITL event is a member in a terminal state (``resolved``, ``timed_out``,
  ``escalated``). Its ``HITL_CONTEXT:v2:`` hash binds ``context_json``; a
  terminal event stored without that document **cannot be committed under
  version 2**, and the reader says so (``refusals``) rather than inventing one.
  The seal path then seals under version 1, which never bound it.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from astp.core import seal_v2 as S
from astp.core.seal_v2 import SegmentSealInput
from astp.protocol.errors import AdapterWriteError, AriadneProtocolError

DEFAULT_SEGMENT_SCHEMA_VERSION = "1.2.0"
SEGMENT_NODE_TYPE = "segment"


@dataclass
class SealInputsV2:
    episode_id: UUID
    segments: List[SegmentSealInput]          # non-ephemeral, any order
    excluded_content_hashes: List[str]
    signal_content_hashes: List[str]
    structural_member_hashes: List[str]
    refusals: List[str] = field(default_factory=list)   # why a version 2 seal is not possible, if it is not

    @property
    def sealable_under_v2(self) -> bool:
        return not self.refusals


_SEGMENTS = """
MATCH (e:AriadneEpisode {episode_id: $e})-[:CONTAINS]->(s:AriadneSegment)
WHERE s.content_hash IS NOT NULL
RETURN s.segment_id AS id, s.sequence_index AS seq, s.content_hash AS h, s.schema_version AS sv,
       COALESCE(s.retention_tier, 'PERSISTENT') = 'EPHEMERAL' AS ephemeral
"""
_SIGNALS = """
MATCH (e:AriadneEpisode {episode_id: $e})-[:RECEIVED]->(g:AriadneSignal)
WHERE g.placement = 'SPINE' AND g.content_hash IS NOT NULL
RETURN g.content_hash AS h
"""
_BRANCH_POINTS = """
MATCH (bp:AriadneBranchPoint {episode_id: $e})
RETURN bp.branch_point_id AS id, bp.episode_id AS episode_id, bp.branch_id AS branch_id, bp.source_segment_id AS seg,
       bp.spine_merkle_snapshot AS snap, bp.branch_type AS bt, bp.declaration_type AS dt, bp.timestamp_utc AS ts,
       bp.parent_hash AS parent
"""
_BRANCH_TERMINI = """
MATCH (bp:AriadneBranchPoint {episode_id: $e})-[:BRANCH_TERMINUS]->(t:AriadneBranchTerminus)
RETURN t.terminus_id AS id, t.branch_id AS branch_id, t.terminus_type AS tt, t.branch_point_hash AS bph,
       t.final_merkle_root AS fmr, t.timestamp_utc AS ts
"""
_FORK_POINTS = """
MATCH (fp:AriadneForkPoint {episode_id: $e})
RETURN fp.fork_point_id AS id, fp.fork_id AS fork_id, fp.episode_id AS episode_id, fp.origin_episode_id AS origin,
       fp.origin_segment_id AS seg, fp.fork_objective AS obj, fp.sibling_index AS si, fp.timestamp_utc AS ts,
       fp.parent_hash AS parent
"""
_DEPARTURE_FORK_POINTS = """
MATCH (fp:AriadneDepartureForkPoint {origin_episode_id: $e})
RETURN fp.fork_point_id AS id, fp.fork_id AS fork_id, fp.fork_episode_id AS fork_ep, fp.origin_episode_id AS origin,
       fp.origin_segment_id AS seg, fp.fork_objective AS obj, fp.fork_creation_trigger AS trig,
       fp.spine_tip_hash_at_departure AS tip, fp.timestamp_utc AS ts, fp.parent_hash AS parent
"""
_FORK_RETURNS = """
MATCH (fr:AriadneForkReturn {origin_episode_id: $e})
RETURN fr.fork_return_id AS id, fr.fork_id AS fork_id, fr.fork_episode_id AS fork_ep, fr.origin_episode_id AS origin,
       fr.return_type AS rt, fr.fork_final_spine_tip_hash AS tip, fr.timestamp_utc AS ts, fr.parent_hash AS parent
"""
_MERGE_POINTS = """
MATCH (mp:AriadneMergePoint {target_episode_id: $e})
RETURN mp.merge_point_id AS id, mp.merge_id AS merge_id, mp.source_episode_id AS src, mp.target_episode_id AS tgt,
       mp.source_merkle_root AS smr, mp.target_merkle_root_pre AS pre, mp.target_merkle_root_post AS post,
       mp.common_ancestor_id AS ca, mp.merge_type AS mt, mp.timestamp_utc AS ts, mp.parent_hash AS parent
"""
_HITL = """
MATCH (h:AriadneHITLEvent {episode_id: $e})
WHERE toLower(h.status) IN ['resolved', 'timed_out', 'escalated']
RETURN h.hitl_event_id AS id, h.hitl_request_id AS req, h.episode_id AS episode_id, h.gate_type AS gate,
       h.requesting_agent AS agent, h.invoked_at AS invoked_at, h.context_json AS context_json,
       h.decision AS decision, h.resolved_by AS resolved_by, h.resolved_at AS resolved_at, h.rationale AS rationale
"""


def _ts(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if hasattr(value, "to_native"):          # neo4j.time.DateTime
        return value.to_native()
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _parent(value) -> Optional[str]:
    return None if value in (None, "", "GENESIS") else value


def _opt_uuid(value) -> Optional[UUID]:
    return None if value in (None, "") else UUID(str(value))


def fetch_seal_inputs_v2(session, episode_id) -> SealInputsV2:
    """Read everything a version 2 seal of ``episode_id`` is a function of.
    Raises ``AdapterWriteError`` if the store fails; records, rather than
    raises, the reasons a version 2 seal is not possible for this Episode."""
    eid = str(episode_id)
    try:
        ep = UUID(eid)
    except ValueError:
        return SealInputsV2(episode_id=UUID(int=0), segments=[], excluded_content_hashes=[], signal_content_hashes=[],
                            structural_member_hashes=[], refusals=[f"episode identifier {eid!r} is not a UUID (§5.7)"])
    try:
        segments: List[SegmentSealInput] = []; excluded: List[str] = []; refusals: List[str] = []
        for r in session.run(_SEGMENTS, {"e": eid}):
            if r["ephemeral"]:
                excluded.append(r["h"]); continue
            try:
                segments.append(SegmentSealInput(
                    node_id=UUID(str(r["id"])), node_type=SEGMENT_NODE_TYPE,
                    schema_version=r["sv"] or DEFAULT_SEGMENT_SCHEMA_VERSION, sequence_index=int(r["seq"]),
                    content_hash=r["h"], parent_node_id=ep))
            except (ValueError, TypeError) as e:
                refusals.append(f"segment {r['id']!r}: {e}")
        signals = [r["h"] for r in session.run(_SIGNALS, {"e": eid})]
        members: List[str] = []
        for r in session.run(_BRANCH_POINTS, {"e": eid}):
            members.append(S.compute_branch_point_hash_v2(
                UUID(r["id"]), UUID(r["episode_id"]), UUID(r["branch_id"]), UUID(r["seg"]), r["snap"], r["bt"], r["dt"],
                _ts(r["ts"]), _parent(r["parent"])))
        for r in session.run(_BRANCH_TERMINI, {"e": eid}):
            members.append(S.compute_branch_terminus_hash_v2(
                UUID(r["id"]), UUID(r["branch_id"]), r["tt"], r["bph"], r["fmr"] or None, _ts(r["ts"])))
        for r in session.run(_FORK_POINTS, {"e": eid}):
            members.append(S.compute_fork_point_hash_v2(
                UUID(r["id"]), UUID(r["fork_id"]), UUID(r["episode_id"]), UUID(r["origin"]), UUID(r["seg"]), r["obj"],
                int(r["si"] or 0), _ts(r["ts"]), _parent(r["parent"])))
        for r in session.run(_DEPARTURE_FORK_POINTS, {"e": eid}):
            members.append(S.compute_departure_fork_point_hash_v2(
                UUID(r["id"]), UUID(r["fork_id"]), UUID(r["fork_ep"]), UUID(r["origin"]), UUID(r["seg"]), r["obj"],
                r["trig"], r["tip"], _ts(r["ts"]), _parent(r["parent"])))
        for r in session.run(_FORK_RETURNS, {"e": eid}):
            members.append(S.compute_fork_return_hash_v2(
                UUID(r["id"]), UUID(r["fork_id"]), UUID(r["fork_ep"]), UUID(r["origin"]), r["rt"], r["tip"],
                _ts(r["ts"]), _parent(r["parent"])))
        for r in session.run(_MERGE_POINTS, {"e": eid}):
            members.append(S.compute_merge_point_hash_v2(
                UUID(r["id"]), UUID(r["merge_id"]), UUID(r["src"]), UUID(r["tgt"]), r["smr"], r["pre"], r["post"],
                _opt_uuid(r["ca"]), r["mt"], _ts(r["ts"]), _parent(r["parent"])))
        for r in session.run(_HITL, {"e": eid}):
            if r["context_json"] is None:
                refusals.append(f"HITL event {r['id']} is terminal but stores no context_json; it cannot be a version 2 member")
                continue
            ctx = S.compute_hitl_context_hash_v2(r["req"], UUID(r["episode_id"]), r["gate"], r["agent"], _ts(r["invoked_at"]), r["context_json"])
            res = S.compute_hitl_resolution_hash_v2(UUID(r["id"]), r["decision"], r["resolved_by"], _ts(r["resolved_at"]), r["rationale"])
            members.append(S.compute_hitl_node_hash_v2(ctx, res))
    except AriadneProtocolError:
        raise
    except Exception as e:
        raise AdapterWriteError(f"fetch_seal_inputs_v2: {e}") from e
    return SealInputsV2(episode_id=ep, segments=segments, excluded_content_hashes=excluded, signal_content_hashes=signals,
                        structural_member_hashes=members, refusals=refusals)
