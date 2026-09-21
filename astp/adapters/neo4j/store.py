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
The reference ``StructuralStore`` — a Neo4j driver behind the operations contract.

Every method either delegates to the writer/query module of this adapter or runs
the read the operations layer used to run itself, unchanged. The operations
layer (``astp.core.branch_operations`` and its siblings) no longer names a
store; this class is where the graph is named.
"""

from typing import Any, Dict, List, Optional

from astp.adapters.base import StructuralStore
from astp.adapters.neo4j import queries as Q
from astp.adapters.neo4j import writer as W


class Neo4jStructuralStore(StructuralStore):
    """``StructuralStore`` over a synchronous Neo4j driver."""

    def __init__(self, driver: Any):
        self.driver = driver

    def _single(self, query: str, params: dict):
        with self.driver.session() as session:
            return session.run(query, params).single()

    # ── Episodes ───────────────────────────────────────────────────────────

    def episode_status(self, episode_id: str) -> Optional[str]:
        rec = self._single("""
                MATCH (e:AriadneEpisode {episode_id: $eid})
                RETURN e.episode_status AS status
            """, {"eid": episode_id})
        return rec["status"] if rec else None

    def episode_spine_hash(self, episode_id: str) -> Optional[str]:
        rec = self._single("""
                MATCH (e:AriadneEpisode {episode_id: $eid})
                RETURN e.spine_hash AS spine_hash
            """, {"eid": episode_id})
        return rec["spine_hash"] if rec and rec["spine_hash"] else None

    def episode_status_and_spine_hash(self, episode_id: str) -> Optional[tuple]:
        rec = self._single("""
                MATCH (e:AriadneEpisode {episode_id: $eid})
                RETURN e.episode_status AS status, e.spine_hash AS spine_hash
            """, {"eid": episode_id})
        return (rec["status"], rec["spine_hash"]) if rec else None

    def departure_fork_episode(self, fork_episode_id: Optional[str] = None,
                               fork_id: Optional[str] = None) -> tuple:
        if fork_episode_id:
            r = self._single(
                "MATCH (e:AriadneEpisode {episode_id: $eid}) "
                "RETURN e.episode_id AS eid, e.fork_status AS st",
                {"eid": str(fork_episode_id)},
            )
        else:
            r = self._single(
                "MATCH (e:AriadneEpisode {fork_id: $fid}) "
                "RETURN e.episode_id AS eid, e.fork_status AS st",
                {"fid": str(fork_id)},
            )
        if not r:
            return (None, None)
        return (r["eid"], r["st"])

    def write_departure_fork_episode(self, episode: Any) -> None:
        W.write_departure_fork_episode_sync(self.driver, episode)

    def set_episode_fork_return_type(self, episode_id: str, return_type: str) -> None:
        with self.driver.session() as session:
            session.run(
                "MATCH (e:AriadneEpisode {episode_id: $eid}) SET e.fork_return_type = $rt",
                {"eid": str(episode_id), "rt": return_type},
            )

    def mark_departure_fork_status(self, fork_episode_id: str, status: str) -> None:
        W.mark_departure_fork_status_sync(self.driver, fork_episode_id, status)

    def set_departure_fork_anchor_index(self, fork_episode_id: str, anchor_index: int) -> None:
        W.set_departure_fork_anchor_index_sync(self.driver, fork_episode_id, anchor_index)

    # ── Segments ───────────────────────────────────────────────────────────

    def segment_sequence_index(self, segment_id: str) -> Optional[int]:
        r = self._single(
            "MATCH (s:AriadneSegment {segment_id: $sid}) RETURN s.sequence_index AS idx",
            {"sid": segment_id},
        )
        return r["idx"] if r is not None else None

    def segment_content_hashes(self, segment_ids) -> Dict[str, tuple]:
        return Q.segment_content_hashes_sync(self.driver, segment_ids)

    # ── Branches ───────────────────────────────────────────────────────────

    def write_branch_point(self, branch_point: Any) -> None:
        W.write_branch_point_sync(self.driver, branch_point)

    def branch_point_with_terminus(self, branch_id: str) -> Optional[tuple]:
        rec = self._single("""
                MATCH (bp:AriadneBranchPoint {branch_id: $bid})
                OPTIONAL MATCH (bp)-[:BRANCH_TERMINUS]->(bt:AriadneBranchTerminus)
                RETURN bp {.*} AS branch_point, bt IS NOT NULL AS has_terminus
            """, {"bid": branch_id})
        if not rec or not rec["branch_point"]:
            return None
        return (dict(rec["branch_point"]), bool(rec["has_terminus"]))

    def write_branch_terminus(self, terminus: Any) -> None:
        W.write_branch_terminus_sync(self.driver, terminus)

    def write_branch_return_edge(self, branch_return: Any) -> None:
        W.write_branch_return_edge_sync(self.driver, branch_return)

    def find_common_ancestor(self, branch_id: str, target_episode_id: str) -> Optional[dict]:
        return W.find_common_ancestor_sync(self.driver, branch_id, target_episode_id)

    # ── Forks ──────────────────────────────────────────────────────────────

    def write_fork_point(self, fork_point: Any) -> None:
        W.write_fork_point_sync(self.driver, fork_point)

    def fork_points(self, fork_id: str) -> List[dict]:
        with self.driver.session() as session:
            result = session.run("""
                MATCH (fp:AriadneForkPoint {fork_id: $fork_id})
                RETURN fp.fork_point_id AS fpid,
                       fp.episode_id    AS eid,
                       fp.fork_status   AS status,
                       fp.origin_episode_id AS origin_id
            """, {"fork_id": fork_id})
            return [dict(r) for r in result]

    def mark_fork_point_status(self, fork_point_id: str, status: str) -> None:
        W.mark_fork_point_status_sync(self.driver, fork_point_id, status)

    def write_departure_fork_point(self, fork_point: Any) -> None:
        W.write_departure_fork_point_sync(self.driver, fork_point)

    def departure_fork_point_by_fork(self, fork_id: str) -> Optional[dict]:
        r = self._single(
            """
                    MATCH (fp:AriadneDepartureForkPoint {fork_id: $fid})
                    RETURN fp.fork_point_id AS pid, fp.fork_episode_id AS eid,
                           fp.spine_tip_hash_at_departure AS tip
                    """,
            {"fid": str(fork_id)},
        )
        return dict(r) if r is not None else None

    def write_fork_return_node(self, fork_return: Any) -> None:
        W.write_fork_return_node_sync(self.driver, fork_return)

    def fork_return_exists(self, fork_id: str) -> bool:
        r = self._single(
            "MATCH (fr:AriadneForkReturn {fork_id: $fid}) "
            "RETURN fr.fork_return_id AS id LIMIT 1",
            {"fid": str(fork_id)},
        )
        return bool(r)

    # ── Merges ─────────────────────────────────────────────────────────────

    def write_merge_point(self, merge_point: Any) -> None:
        W.write_merge_point_sync(self.driver, merge_point)

    def merge_point(self, merge_id: str) -> Optional[dict]:
        rec = self._single("""
                MATCH (mp:AriadneMergePoint {merge_id: $mid})
                RETURN mp {.*} AS merge_point
            """, {"mid": merge_id})
        if not rec or not rec["merge_point"]:
            return None
        return dict(rec["merge_point"])

    def merge_executed_forward_delta(self, merge_id: str) -> Optional[str]:
        rec = self._single("""
                MATCH (ar:AriadneAuditRecord {delta_type: 'MERGE_EXECUTED'})
                WHERE ar.forward_delta CONTAINS $mid
                RETURN ar.forward_delta AS fd
                LIMIT 1
            """, {"mid": merge_id})
        return rec["fd"] if rec and rec["fd"] else None

    # ── Asides and soliloquies ─────────────────────────────────────────────

    def write_aside(self, aside: Any) -> None:
        W.write_aside_sync(self.driver, aside)

    def write_aside_terminus(self, terminus: Any) -> None:
        W.write_aside_terminus_sync(self.driver, terminus)

    def load_aside(self, aside_id: str) -> Optional[dict]:
        return W.load_aside_sync(self.driver, aside_id)

    def scan_aside_external_references(self, aside_id: str, content_refs: List[str]) -> List[str]:
        return W.scan_aside_external_references_sync(self.driver, aside_id, content_refs)

    def write_soliloquy(self, soliloquy: Any) -> None:
        W.write_soliloquy_sync(self.driver, soliloquy)

    def write_soliloquy_conclusion(self, conclusion: Any) -> None:
        W.write_soliloquy_conclusion_sync(self.driver, conclusion)

    def load_soliloquy(self, soliloquy_id: str) -> Optional[dict]:
        return W.load_soliloquy_sync(self.driver, soliloquy_id)

    # ── Coherence ──────────────────────────────────────────────────────────

    def write_coherence_fingerprint(self, fingerprint: Any) -> None:
        W.write_coherence_fingerprint_sync(self.driver, fingerprint)

    def recent_fingerprints(self, episode_id: str, limit: int = 10) -> List[dict]:
        return W.query_recent_fingerprints_sync(self.driver, episode_id, limit)

    def last_fingerprint(self, episode_id: str) -> Optional[dict]:
        return W.get_last_fingerprint_sync(self.driver, episode_id)

    def last_nominal_segment(self, episode_id: str) -> Optional[str]:
        return W.get_last_nominal_segment_sync(self.driver, episode_id)

    # ── Cross-episode links and grouping ───────────────────────────────────

    def write_episode_link(self, link: Any) -> None:
        W.write_episode_link_sync(self.driver, link)

    def write_membership_record(self, record: Any) -> None:
        W.write_membership_record_sync(self.driver, record)

    def membership_record_role(self, record_id: str) -> Optional[str]:
        r = self._single(
            "MATCH (m:AriadneMembershipRecord {record_id: $rid}) "
            "RETURN m.membership_role AS role",
            {"rid": str(record_id)},
        )
        return r["role"] if r else None

    def write_conformance_declaration(self, declaration: Any) -> None:
        W.write_conformance_declaration_sync(self.driver, declaration)

    def supersede_conformance_declaration(self, old_declaration_id: str, new_declaration_id: str) -> None:
        W.supersede_conformance_declaration_sync(self.driver, old_declaration_id, new_declaration_id)

    # ── Audit chain, intents, write-intent ledger ──────────────────────────

    def write_audit_record(self, audit: Any) -> None:
        W.write_audit_record_sync(self.driver, audit)

    def max_delta_sequence(self, chain_key: str) -> Optional[int]:
        # The graph parameter is `$eid` although the value may be a synthetic chain
        # key ("declaration:<system>:<group>"): the parameter name is storage detail.
        rec = self._single(
            """
                MATCH (ar:AriadneAuditRecord {episode_id: $eid})
                RETURN max(ar.delta_sequence) AS max_seq
                """,
            {"eid": chain_key},
        )
        return rec["max_seq"] if rec and rec["max_seq"] is not None else None

    def latest_audit_record_hash(self, chain_key: str) -> Optional[str]:
        rec = self._single(
            """
                MATCH (ar:AriadneAuditRecord {episode_id: $eid})
                RETURN ar.record_hash AS hash
                ORDER BY ar.delta_sequence DESC
                LIMIT 1
                """,
            {"eid": chain_key},
        )
        return rec["hash"] if rec and rec["hash"] else None

    def acquire_intent(self, idempotency_key: str, intent_type: str, initiator_id: str) -> tuple:
        return W.acquire_intent_sync(self.driver, idempotency_key, intent_type, initiator_id)

    def complete_intent(self, idempotency_key: str, result_node_id: str) -> None:
        W.complete_intent_sync(self.driver, idempotency_key, result_node_id)

    def write_completed_wil_entry(self, intent_id: str, operation: str, episode_id: str,
                                  node_id: str, timestamp: str) -> None:
        with self.driver.session() as session:
            session.run("""
                MERGE (w:AriadneWILEntry {intent_id: $intent_id})
                ON CREATE SET
                  w.operation              = $operation,
                  w.episode_id             = $episode_id,
                  w.stores_involved        = ['neo4j'],
                  w.pre_state_hash         = $pre_hash,
                  w.post_state_hash        = $post_hash,
                  w.initiated_at           = $ts,
                  w.completed_at           = $ts,
                  w.status                 = 'COMPLETE',
                  w.last_completed_store   = 'neo4j'
            """, {
                "intent_id": intent_id,
                "operation": operation,
                "episode_id": episode_id,
                "pre_hash": node_id,
                "post_hash": node_id,
                "ts": timestamp,
            })
