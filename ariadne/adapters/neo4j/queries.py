"""
Ariadne read-only Neo4j queries for Thermyt-Lite UI.

All queries use asyncio.to_thread() to wrap the sync Neo4j driver,
matching the pattern established in server.py.

IMPORTANT: Neo4j session.run() signature is run(query, parameters=None, **kwargs).
All parameters are passed as an explicit dict (positional arg) to avoid collisions.
"""

import asyncio
import logging
import os
from typing import Any, Optional

logger = logging.getLogger("ariadne.adapters.neo4j.queries")

ARIADNE_ENABLED = os.getenv("ARIADNE_ENABLED", "false").lower() == "true"


def _empty_if_disabled(default=None):
    """Return default value when Ariadne is not enabled."""
    if default is None:
        return []
    return default


# ── Episode Queries ──────────────────────────────────────────────────────────


async def list_episodes_for_workspace(
    driver,
    workspace_id: str,
    status: Optional[str] = None,
    limit: int = 50,
    user_name: Optional[str] = None,
) -> list[dict[str, Any]]:
    """List episodes linked to a workspace, ordered by most recent activity.

    If user_name is provided, only returns episodes where that user is a participant.
    """
    if not ARIADNE_ENABLED:
        return []

    def _query():
        with driver.session() as session:
            # Build WHERE clauses
            where_clauses = []
            params: dict[str, Any] = {"workspace_id": workspace_id, "limit": limit}
            if status:
                where_clauses.append("e.episode_status = $status")
                params["status"] = status
            if user_name:
                where_clauses.append("$user_name IN e.participants")
                params["user_name"] = user_name

            where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

            result = session.run(f"""
                MATCH (e:AriadneEpisode {{workspace_id: $workspace_id}})
                {where_sql}
                RETURN e {{.*}} AS episode
                ORDER BY e.opened_at DESC
                LIMIT $limit
            """, params)
            return [record["episode"] for record in result]

    return await asyncio.to_thread(_query)


async def list_episodes_for_user(
    driver,
    user_name: str,
    status: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List all episodes where the user is a participant, across every workspace.

    This is the workspace-agnostic read path — episodes are surfaced by participation,
    not by workspace membership. Optional status filter matches the workspace-scoped
    variant's semantics.
    """
    if not ARIADNE_ENABLED:
        return []

    def _query():
        with driver.session() as session:
            where_clauses = ["$user_name IN e.participants"]
            params: dict[str, Any] = {"user_name": user_name, "limit": limit}
            if status:
                where_clauses.append("e.episode_status = $status")
                params["status"] = status

            where_sql = " AND ".join(where_clauses)
            result = session.run(f"""
                MATCH (e:AriadneEpisode)
                WHERE {where_sql}
                RETURN e {{.*}} AS episode
                ORDER BY e.opened_at DESC
                LIMIT $limit
            """, params)
            return [record["episode"] for record in result]

    return await asyncio.to_thread(_query)


async def list_shared_episodes_for_user(
    driver,
    user_name: str,
    exclude_workspace_id: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List episodes from OTHER workspaces where the user is a participant.

    Used to surface episodes shared with the user across workspace boundaries.
    """
    if not ARIADNE_ENABLED:
        return []

    def _query():
        with driver.session() as session:
            params: dict[str, Any] = {"user_name": user_name, "limit": limit}
            exclude_clause = ""
            if exclude_workspace_id:
                exclude_clause = "AND (e.workspace_id IS NULL OR e.workspace_id <> $exclude_ws)"
                params["exclude_ws"] = exclude_workspace_id

            result = session.run(f"""
                MATCH (e:AriadneEpisode)
                WHERE $user_name IN e.participants {exclude_clause}
                RETURN e {{.*}} AS episode
                ORDER BY e.opened_at DESC
                LIMIT $limit
            """, params)
            return [record["episode"] for record in result]

    return await asyncio.to_thread(_query)


async def list_all_episodes(
    driver,
    status: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List all episodes across workspaces, ordered by most recent activity."""
    if not ARIADNE_ENABLED:
        return []

    def _query():
        with driver.session() as session:
            if status:
                result = session.run("""
                    MATCH (e:AriadneEpisode)
                    WHERE e.episode_status = $status
                    RETURN e {.*} AS episode
                    ORDER BY e.opened_at DESC
                    LIMIT $limit
                """, {"status": status, "limit": limit})
            else:
                result = session.run("""
                    MATCH (e:AriadneEpisode)
                    RETURN e {.*} AS episode
                    ORDER BY e.opened_at DESC
                    LIMIT $limit
                """, {"limit": limit})
            return [record["episode"] for record in result]

    return await asyncio.to_thread(_query)


async def get_episode_detail(driver, episode_id: str) -> Optional[dict[str, Any]]:
    """Get full episode detail including segment/signal/intention counts."""
    if not ARIADNE_ENABLED:
        return None

    def _query():
        with driver.session() as session:
            result = session.run("""
                MATCH (e:AriadneEpisode {episode_id: $episode_id})
                OPTIONAL MATCH (e)-[:CONTAINS]->(seg:AriadneSegment)
                OPTIONAL MATCH (e)-[:RECEIVED]->(sig:AriadneSignal)
                OPTIONAL MATCH (i:Intention)-[ad:ACTIVE_DURING]->(e)
                RETURN e {.*} AS episode,
                       count(DISTINCT seg) AS segment_count,
                       count(DISTINCT sig) AS signal_count,
                       count(DISTINCT i) AS intention_count
            """, {"episode_id": episode_id})
            record = result.single()
            if not record:
                return None
            episode = dict(record["episode"])
            episode["segment_count"] = record["segment_count"]
            episode["signal_count"] = record["signal_count"]
            episode["intention_count"] = record["intention_count"]
            return episode

    return await asyncio.to_thread(_query)


# ── Layer 3 Execution DAG Queries ────────────────────────────────────────────


async def get_execution_dag_for_episode(driver, episode_id: str) -> dict[str, Any]:
    """Get the Layer 3 Execution DAG for an episode.

    Returns the workflow declarations anchored to the episode, their execution
    steps, and the PRECEDES edges between steps — the raw material for a DAG
    visualization. The DAG is written exclusively by the ignis-mcp-server, so
    most episodes have none; in that case workflows/steps/edges come back empty.

    Shape::

        {
          "workflows": [{node_id, workflow_name, workflow_version, status,
                         declared_by, declared_at}],
          "steps":     [{node_id, workflow_id, step_name, sequence_index,
                         status, agent_id, executed_at, duration_ms}],
          "edges":     [{source, target, edge_type, sequence_gap}],  # PRECEDES
        }
    """
    if not ARIADNE_ENABLED:
        return {"workflows": [], "steps": [], "edges": []}

    def _query():
        with driver.session() as session:
            workflows = [
                record["workflow"]
                for record in session.run("""
                    MATCH (w:WorkflowDeclaration {episode_id: $episode_id})
                          -[:DECLARED_WITHIN]->(:AriadneEpisode {episode_id: $episode_id})
                    RETURN w {
                        .node_id, .workflow_name, .workflow_version,
                        .status, .declared_by, .declared_at
                    } AS workflow
                    ORDER BY w.declared_at ASC
                """, {"episode_id": episode_id})
            ]
            steps = [
                record["step"]
                for record in session.run("""
                    MATCH (x:ExecutionNode {episode_id: $episode_id})
                          -[:EXECUTES_WITHIN]->(:WorkflowDeclaration {episode_id: $episode_id})
                    RETURN x {
                        .node_id, .workflow_id, .step_name, .sequence_index,
                        .status, .agent_id, .executed_at, .duration_ms
                    } AS step
                    ORDER BY x.sequence_index ASC
                """, {"episode_id": episode_id})
            ]
            edges = [
                {
                    "source": record["source"],
                    "target": record["target"],
                    "edge_type": record["edge_type"],
                    "sequence_gap": record["sequence_gap"],
                }
                for record in session.run("""
                    MATCH (a:ExecutionNode {episode_id: $episode_id})
                          -[r:PRECEDES]->(b:ExecutionNode {episode_id: $episode_id})
                    RETURN a.node_id AS source, b.node_id AS target,
                           r.edge_type AS edge_type, r.sequence_gap AS sequence_gap
                """, {"episode_id": episode_id})
            ]
            return {"workflows": workflows, "steps": steps, "edges": edges}

    return await asyncio.to_thread(_query)


# ── Segment Queries ──────────────────────────────────────────────────────────


async def list_segments_for_episode(
    driver,
    episode_id: str,
) -> list[dict[str, Any]]:
    """List segments for an episode, ordered by sequence index."""
    if not ARIADNE_ENABLED:
        return []

    def _query():
        with driver.session() as session:
            result = session.run("""
                MATCH (e:AriadneEpisode {episode_id: $episode_id})-[:CONTAINS]->(s:AriadneSegment)
                RETURN s {.*} AS segment
                ORDER BY s.sequence_index ASC
            """, {"episode_id": episode_id})
            return [record["segment"] for record in result]

    return await asyncio.to_thread(_query)


# ── Signal Queries ───────────────────────────────────────────────────────────


async def list_signals_for_episode(
    driver,
    episode_id: str,
) -> list[dict[str, Any]]:
    """List signals for an episode, ordered by received time."""
    if not ARIADNE_ENABLED:
        return []

    def _query():
        with driver.session() as session:
            result = session.run("""
                MATCH (e:AriadneEpisode {episode_id: $episode_id})-[:RECEIVED]->(sig:AriadneSignal)
                RETURN sig {.*} AS signal
                ORDER BY sig.received_at ASC
            """, {"episode_id": episode_id})
            return [record["signal"] for record in result]

    return await asyncio.to_thread(_query)


# ── Intention Queries ────────────────────────────────────────────────────────


async def list_intentions_for_episode(
    driver,
    episode_id: str,
) -> list[dict[str, Any]]:
    """List intentions linked to an episode via ACTIVE_DURING edges."""
    if not ARIADNE_ENABLED:
        return []

    def _query():
        with driver.session() as session:
            result = session.run("""
                MATCH (i:Intention)-[ad:ACTIVE_DURING]->(e:AriadneEpisode {episode_id: $episode_id})
                OPTIONAL MATCH (i)-[:FORMED_FROM]->(d:Desire)
                RETURN i {.*} AS intention,
                       ad.start_ts AS formed_at,
                       ad.end_state AS end_state,
                       d.goal AS desire_description
                ORDER BY ad.start_ts ASC
            """, {"episode_id": episode_id})
            records = []
            for record in result:
                intention = dict(record["intention"])
                intention["formed_at"] = record["formed_at"]
                intention["end_state"] = record["end_state"]
                # Use desire goal, or fall back to intention's reasoning field
                intention["desire_description"] = (
                    record["desire_description"]
                    or intention.get("reasoning")
                    or intention.get("action")
                )
                records.append(intention)
            return records

    return await asyncio.to_thread(_query)


# ── WIL Queries ──────────────────────────────────────────────────────────────


async def list_wil_entries_for_episode(
    driver,
    episode_id: str,
) -> list[dict[str, Any]]:
    """List WIL entries for an episode (from Neo4j — completed entries only)."""
    if not ARIADNE_ENABLED:
        return []

    def _query():
        with driver.session() as session:
            result = session.run("""
                MATCH (w:AriadneWILEntry {episode_id: $episode_id})
                RETURN w {.*} AS wil_entry
                ORDER BY w.initiated_at ASC
            """, {"episode_id": episode_id})
            return [record["wil_entry"] for record in result]

    return await asyncio.to_thread(_query)


async def list_recent_wil_entries_for_workspace(
    driver,
    workspace_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List recent WIL entries across episodes in a workspace."""
    if not ARIADNE_ENABLED:
        return []

    def _query():
        with driver.session() as session:
            result = session.run("""
                MATCH (e:AriadneEpisode {workspace_id: $workspace_id})
                MATCH (w:AriadneWILEntry {episode_id: e.episode_id})
                RETURN w {.*, workspace_id: e.workspace_id} AS wil_entry
                ORDER BY w.initiated_at DESC
                LIMIT $limit
            """, {"workspace_id": workspace_id, "limit": limit})
            return [record["wil_entry"] for record in result]

    return await asyncio.to_thread(_query)


async def get_wil_entries_with_episode_context(
    driver,
    workspace_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """WIL entries enriched with episode title and status."""
    if not ARIADNE_ENABLED:
        return []

    def _query():
        with driver.session() as session:
            result = session.run("""
                MATCH (e:AriadneEpisode {workspace_id: $workspace_id})
                MATCH (w:AriadneWILEntry {episode_id: e.episode_id})
                RETURN w {.*} AS wil_entry,
                       e.title AS episode_title,
                       e.episode_status AS episode_status,
                       e.agent_id AS agent_id
                ORDER BY w.initiated_at DESC
                LIMIT $limit
            """, {"workspace_id": workspace_id, "limit": limit})
            entries = []
            for record in result:
                entry = dict(record["wil_entry"])
                entry["episode_title"] = record["episode_title"]
                entry["episode_status"] = record["episode_status"]
                entry["agent_id"] = record["agent_id"]
                entries.append(entry)
            return entries

    return await asyncio.to_thread(_query)


# ── Workspace State Query ────────────────────────────────────────────────────


async def get_workspace_state(
    driver,
    workspace_id: str,
) -> dict[str, Any]:
    """Get workspace state: active episodes + recent activity signals."""
    if not ARIADNE_ENABLED:
        return {"active_episodes": [], "recent_activity": []}

    def _query():
        with driver.session() as session:
            # Active episodes
            ep_result = session.run("""
                MATCH (e:AriadneEpisode {workspace_id: $workspace_id})
                WHERE e.episode_status IN ['CREATED', 'ACTIVE', 'CRYSTALLIZATION_PENDING']
                RETURN e {.*} AS episode
                ORDER BY e.opened_at DESC
            """, {"workspace_id": workspace_id})
            active_episodes = [record["episode"] for record in ep_result]

            # Recent signals across workspace episodes
            sig_result = session.run("""
                MATCH (e:AriadneEpisode {workspace_id: $workspace_id})
                MATCH (e)-[:RECEIVED]->(sig:AriadneSignal)
                RETURN sig {.*, episode_title: e.title} AS signal
                ORDER BY sig.received_at DESC
                LIMIT 20
            """, {"workspace_id": workspace_id})
            recent_activity = [record["signal"] for record in sig_result]

            return {
                "active_episodes": active_episodes,
                "recent_activity": recent_activity,
            }

    return await asyncio.to_thread(_query)


# ── Crystallization Queries ──────────────────────────────────────────────────


async def get_crystallization_progress(
    driver,
    episode_id: str,
) -> dict[str, Any]:
    """Get crystallization status and chain position for an episode."""
    if not ARIADNE_ENABLED:
        return {"status": "disabled", "chain_position": 0, "version_vector": None}

    def _query():
        with driver.session() as session:
            # Episode crystallization status
            ep_result = session.run("""
                MATCH (e:AriadneEpisode {episode_id: $episode_id})
                RETURN e.episode_status AS status,
                       e.crystallization_status AS crystallization_status,
                       e.last_crystallized_at AS last_crystallized_at,
                       e.last_crystallization_delta_id AS last_delta_id
            """, {"episode_id": episode_id})
            ep_record = ep_result.single()
            if not ep_record:
                return {"status": "not_found", "chain_position": 0, "version_vector": None}

            # Latest crystallization delta for chain position + version vector
            delta_result = session.run("""
                MATCH (cd:AriadneCrystallizationDelta {episode_id: $episode_id})
                RETURN cd.chain_position AS chain_position,
                       cd.content_version AS content_version,
                       cd.lifecycle_version AS lifecycle_version,
                       cd.chain_version AS chain_version,
                       cd.sealed_chain_root AS sealed_chain_root
                ORDER BY cd.chain_position DESC
                LIMIT 1
            """, {"episode_id": episode_id})
            delta_record = delta_result.single()

            result = {
                "status": ep_record["crystallization_status"] or ep_record["status"],
                "episode_status": ep_record["status"],
                "last_crystallized_at": ep_record["last_crystallized_at"],
                "last_delta_id": ep_record["last_delta_id"],
            }

            if delta_record:
                result["chain_position"] = delta_record["chain_position"]
                result["version_vector"] = {
                    "content_version": delta_record["content_version"],
                    "lifecycle_version": delta_record["lifecycle_version"],
                    "chain_version": delta_record["chain_version"],
                }
                result["sealed_chain_root"] = delta_record["sealed_chain_root"]
            else:
                result["chain_position"] = 0
                result["version_vector"] = None

            return result

    return await asyncio.to_thread(_query)


# ── Codicil & Closure Queries ────────────────────────────────────────────────


async def list_codicils_for_episode(
    driver,
    episode_id: str,
) -> list[dict[str, Any]]:
    """List codicils for a sealed episode, ordered by creation time."""
    if not ARIADNE_ENABLED:
        return []

    def _query():
        with driver.session() as session:
            result = session.run("""
                MATCH (e:AriadneEpisode {episode_id: $episode_id})-[:HAS_CODICIL]->(cod:AriadneCodicil)
                RETURN cod {.*} AS codicil
                ORDER BY cod.created_at ASC
            """, {"episode_id": episode_id})
            return [record["codicil"] for record in result]

    return await asyncio.to_thread(_query)


async def get_closure_record(
    driver,
    episode_id: str,
) -> Optional[dict[str, Any]]:
    """Get the closure record for a sealed episode."""
    if not ARIADNE_ENABLED:
        return None

    def _query():
        with driver.session() as session:
            result = session.run("""
                MATCH (cl:AriadneClosureRecord {episode_id: $episode_id})
                RETURN cl {.*} AS closure
            """, {"episode_id": episode_id})
            record = result.single()
            return dict(record["closure"]) if record else None

    return await asyncio.to_thread(_query)


# ── Agent Retrieval Queries ──────────────────────────────────────────────────


async def get_spine_snapshot_index(
    driver,
    episode_id: str,
) -> Optional[int]:
    """
    Get the current max sequence_index for an episode.
    Used to capture a spine snapshot — all segments at or below
    this index are guaranteed stable (segments are append-only).

    Returns None if no segments exist or ARIADNE_ENABLED is false.
    """
    if not ARIADNE_ENABLED:
        return None

    def _query():
        with driver.session() as session:
            result = session.run("""
                MATCH (e:AriadneEpisode {episode_id: $episode_id})
                      -[:CONTAINS]->(s:AriadneSegment)
                RETURN max(s.sequence_index) AS max_index
            """, {"episode_id": episode_id})
            record = result.single()
            return record["max_index"] if record and record["max_index"] is not None else None

    return await asyncio.to_thread(_query)


async def get_segment_by_id(
    driver,
    episode_id: str,
    segment_id: str,
    max_sequence_index: Optional[int] = None,
) -> Optional[dict[str, Any]]:
    """
    Retrieve a single segment by ID, scoped to episode_id.
    Episode scoping is enforced in the Cypher query — never relaxed.

    max_sequence_index: if provided, rejects segments above this index
    (snapshot isolation — only return segments visible at snapshot time).
    """
    if not ARIADNE_ENABLED:
        return None

    def _query():
        with driver.session() as session:
            params = {"episode_id": episode_id, "segment_id": segment_id}
            snapshot_clause = ""
            if max_sequence_index is not None:
                snapshot_clause = "WHERE s.sequence_index <= $max_index"
                params["max_index"] = max_sequence_index

            result = session.run(f"""
                MATCH (e:AriadneEpisode {{episode_id: $episode_id}})
                      -[:CONTAINS]->
                      (s:AriadneSegment {{segment_id: $segment_id}})
                {snapshot_clause}
                RETURN s {{
                    .segment_id,
                    .episode_id,
                    .sequence_index,
                    .segment_type,
                    .author,
                    .authored_at,
                    .content_ref,
                    .content_text,
                    .retention_tier
                }} AS segment
            """, params)
            record = result.single()
            return dict(record["segment"]) if record else None

    return await asyncio.to_thread(_query)


async def get_segment_range(
    driver,
    episode_id: str,
    from_index: int,
    to_index: int,
    segment_types: Optional[list[str]] = None,
    authors: Optional[list[str]] = None,
    max_sequence_index: Optional[int] = None,
) -> list[dict[str, Any]]:
    """
    Retrieve segments between from_index and to_index (inclusive).
    Optional filters: segment_types, authors.
    max_sequence_index: snapshot isolation cap (only return segments at or below).
    Returns ordered by sequence_index ASC.
    """
    if not ARIADNE_ENABLED:
        return []

    # Snapshot isolation: cap to_index at snapshot boundary
    effective_to = to_index
    if max_sequence_index is not None:
        effective_to = min(to_index, max_sequence_index)

    def _query():
        with driver.session() as session:
            params: dict[str, Any] = {
                "episode_id": episode_id,
                "from_index": from_index,
                "to_index": effective_to,
            }
            type_clause = ""
            if segment_types:
                type_clause = "AND s.segment_type IN $segment_types"
                params["segment_types"] = segment_types

            author_clause = ""
            if authors:
                author_clause = "AND s.author IN $authors"
                params["authors"] = authors

            result = session.run(f"""
                MATCH (e:AriadneEpisode {{episode_id: $episode_id}})
                      -[:CONTAINS]->
                      (s:AriadneSegment)
                WHERE s.sequence_index >= $from_index
                  AND s.sequence_index <= $to_index
                  {type_clause}
                  {author_clause}
                RETURN s {{
                    .segment_id,
                    .episode_id,
                    .sequence_index,
                    .segment_type,
                    .author,
                    .authored_at,
                    .content_ref,
                    .content_text,
                    .retention_tier
                }} AS segment
                ORDER BY s.sequence_index ASC
            """, params)
            return [dict(record["segment"]) for record in result]

    return await asyncio.to_thread(_query)


async def get_episode_spine(
    driver,
    episode_id: str,
    limit: int = 20,
    before_index: Optional[int] = None,
    segment_types: Optional[list[str]] = None,
    retention_tier: Optional[str] = None,
    max_sequence_index: Optional[int] = None,
) -> list[dict[str, Any]]:
    """
    Retrieve the most recent N segments from the Episode spine.
    before_index scopes the query to segments before a given position.
    max_sequence_index: snapshot isolation cap (only return segments at or below).
    Returns ordered by sequence_index ASC.
    """
    if not ARIADNE_ENABLED:
        return []

    def _query():
        with driver.session() as session:
            params: dict[str, Any] = {
                "episode_id": episode_id,
                "limit": limit,
            }
            before_clause = ""
            # Snapshot isolation: use the tighter of before_index and max_sequence_index
            effective_before = before_index
            if max_sequence_index is not None:
                snapshot_before = max_sequence_index + 1  # inclusive → exclusive
                if effective_before is None or snapshot_before < effective_before:
                    effective_before = snapshot_before
            if effective_before is not None:
                before_clause = "AND s.sequence_index < $before_index"
                params["before_index"] = effective_before

            type_clause = ""
            if segment_types:
                type_clause = "AND s.segment_type IN $segment_types"
                params["segment_types"] = segment_types

            tier_clause = ""
            if retention_tier:
                tier_clause = "AND s.retention_tier = $retention_tier"
                params["retention_tier"] = retention_tier

            # DESC for LIMIT efficiency, reversed to ASC for agent consumption
            result = session.run(f"""
                MATCH (e:AriadneEpisode {{episode_id: $episode_id}})
                      -[:CONTAINS]->
                      (s:AriadneSegment)
                WHERE 1=1
                  {before_clause}
                  {type_clause}
                  {tier_clause}
                RETURN s {{
                    .segment_id,
                    .episode_id,
                    .sequence_index,
                    .segment_type,
                    .author,
                    .authored_at,
                    .content_ref,
                    .content_text,
                    .retention_tier
                }} AS segment
                ORDER BY s.sequence_index DESC
                LIMIT $limit
            """, params)
            rows = [dict(record["segment"]) for record in result]
            return list(reversed(rows))

    return await asyncio.to_thread(_query)


# ── Branch Queries (Phase 1) ────────────────────────────────────────────────


async def list_active_branches(
    driver,
    episode_id: str,
) -> list[dict[str, Any]]:
    """List all active branches for an episode.

    Active = BranchPointNode exists with no matching BranchTerminusNode.
    """
    if not ARIADNE_ENABLED:
        return []

    def _query():
        with driver.session() as session:
            result = session.run("""
                MATCH (bp:AriadneBranchPoint)
                WHERE bp.episode_id = $episode_id OR bp.parent_episode_id = $episode_id
                OPTIONAL MATCH (bp)-[:BRANCH_TERMINUS]->(bt:AriadneBranchTerminus)
                WITH bp, bt
                WHERE bt IS NULL
                RETURN bp {.*} AS branch_point
                ORDER BY bp.timestamp_utc DESC
            """, {"episode_id": episode_id})
            return [dict(record["branch_point"]) for record in result]

    return await asyncio.to_thread(_query)


async def get_branch_history(
    driver,
    branch_id: str,
) -> list[dict[str, Any]]:
    """Get audit records related to a specific branch."""
    if not ARIADNE_ENABLED:
        return []

    def _query():
        with driver.session() as session:
            # Find audit records that reference this branch
            result = session.run("""
                MATCH (ar:AriadneAuditRecord)
                WHERE ar.forward_delta CONTAINS $branch_id
                   OR any(n IN ar.affected_nodes WHERE n CONTAINS $branch_id)
                RETURN ar {.*} AS audit_record
                ORDER BY ar.delta_sequence ASC
            """, {"branch_id": branch_id})
            return [dict(record["audit_record"]) for record in result]

    return await asyncio.to_thread(_query)


async def derive_branch_lifecycle_state(
    driver,
    branch_id: str,
) -> str:
    """Derive branch lifecycle state from the append-only log.

    ACTIVE: BranchPointNode exists, no BranchTerminusNode
    MERGED: BranchTerminusNode with terminus_type=merged
    ABANDONED: BranchTerminusNode with terminus_type=abandoned
    NOT_FOUND: No BranchPointNode exists
    """
    if not ARIADNE_ENABLED:
        return "NOT_FOUND"

    def _query():
        with driver.session() as session:
            result = session.run("""
                MATCH (bp:AriadneBranchPoint {branch_id: $branch_id})
                OPTIONAL MATCH (bp)-[:BRANCH_TERMINUS]->(bt:AriadneBranchTerminus)
                RETURN bp.branch_point_id AS bp_id,
                       bt.terminus_type AS terminus_type
            """, {"branch_id": branch_id})
            record = result.single()

            if not record or not record["bp_id"]:
                return "NOT_FOUND"

            terminus_type = record["terminus_type"]
            if terminus_type == "merged":
                return "MERGED"
            elif terminus_type == "abandoned":
                return "ABANDONED"
            return "ACTIVE"

    return await asyncio.to_thread(_query)


async def get_audit_trail(
    driver,
    episode_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Get the full audit trail for an episode."""
    if not ARIADNE_ENABLED:
        return []

    def _query():
        with driver.session() as session:
            result = session.run("""
                MATCH (ar:AriadneAuditRecord {episode_id: $episode_id})
                RETURN ar {.*} AS audit_record
                ORDER BY ar.delta_sequence ASC
                LIMIT $limit
            """, {"episode_id": episode_id, "limit": limit})
            return [dict(record["audit_record"]) for record in result]

    return await asyncio.to_thread(_query)


# ── Cross-Episode Linking (Amendment v2.0) ──────────────────────────────────


async def list_links_for_episode(
    driver,
    episode_id: str,
    direction: str = "outbound",
    health_filter: Optional[list[str]] = None,
    link_type_filter: Optional[list[str]] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return cross-episode links for an episode — Amendment v2.0 §11.1.6 Pattern.

    Args:
        episode_id: Episode whose links to fetch.
        direction: 'outbound' (this episode → others), 'inbound' (others →
            this episode), or 'both'. Default 'outbound' — matches
            resumption-loader's primary use case.
        health_filter: Optional list of LinkHealthState values to include.
            None = all states. Common values: ['VALID','STALE','FROZEN'] to
            exclude BROKEN/QUARANTINED from active traversal.
        link_type_filter: Optional list of LinkType values to include.
            None = all types. For resumption-loader, callers typically pass
            ['CONTINUES_FROM','SUPERSEDES','INFORMED_BY'] per §3 isolation
            rule (REFERENCES is non-loading and excluded).
        limit: Cap results to prevent unbounded loads.

    Returns: list of dicts with link fields + `direction` ('out'/'in') +
    `other_episode_id` (the non-self endpoint). Empty list if Ariadne
    disabled or no matching links.
    """
    if not ARIADNE_ENABLED:
        return []

    def _query():
        params: dict[str, Any] = {"episode_id": episode_id, "limit": limit}
        where_clauses = []
        if health_filter:
            where_clauses.append("l.health_state IN $health_filter")
            params["health_filter"] = health_filter
        if link_type_filter:
            where_clauses.append("l.link_type IN $link_type_filter")
            params["link_type_filter"] = link_type_filter
        where_sql = ("AND " + " AND ".join(where_clauses)) if where_clauses else ""

        if direction == "outbound":
            cypher = f"""
                MATCH (s:AriadneEpisode {{episode_id: $episode_id}})-[r:LINKED_TO]->(t:AriadneEpisode)
                MATCH (l:AriadneEpisodeLink {{link_id: r.via}})
                WHERE 1=1 {where_sql}
                RETURN l {{.*}} AS link, 'out' AS direction, t.episode_id AS other_episode_id
                ORDER BY l.created_at DESC
                LIMIT $limit
            """
        elif direction == "inbound":
            cypher = f"""
                MATCH (s:AriadneEpisode)-[r:LINKED_TO]->(t:AriadneEpisode {{episode_id: $episode_id}})
                MATCH (l:AriadneEpisodeLink {{link_id: r.via}})
                WHERE 1=1 {where_sql}
                RETURN l {{.*}} AS link, 'in' AS direction, s.episode_id AS other_episode_id
                ORDER BY l.created_at DESC
                LIMIT $limit
            """
        elif direction == "both":
            cypher = f"""
                MATCH (self:AriadneEpisode {{episode_id: $episode_id}})
                MATCH (self)-[r:LINKED_TO]-(other:AriadneEpisode)
                MATCH (l:AriadneEpisodeLink {{link_id: r.via}})
                WHERE 1=1 {where_sql}
                RETURN l {{.*}} AS link,
                    CASE WHEN l.source_episode = $episode_id THEN 'out' ELSE 'in' END AS direction,
                    other.episode_id AS other_episode_id
                ORDER BY l.created_at DESC
                LIMIT $limit
            """
        else:
            raise ValueError(
                f"direction must be 'outbound', 'inbound', or 'both' — got {direction!r}"
            )

        with driver.session() as session:
            result = session.run(cypher, params)
            out: list[dict[str, Any]] = []
            for record in result:
                row = dict(record["link"])
                row["direction"] = record["direction"]
                row["other_episode_id"] = record["other_episode_id"]
                out.append(row)
            return out

    return await asyncio.to_thread(_query)


async def get_episode_link(driver, link_id: str) -> Optional[dict[str, Any]]:
    """Fetch a single EpisodeLink by id. Returns None when not found or
    when Ariadne is disabled."""
    if not ARIADNE_ENABLED:
        return None

    def _query():
        with driver.session() as session:
            result = session.run(
                """
                MATCH (l:AriadneEpisodeLink {link_id: $link_id})
                RETURN l {.*} AS link
                """,
                {"link_id": link_id},
            )
            record = result.single()
            return dict(record["link"]) if record else None

    return await asyncio.to_thread(_query)


async def list_pending_link_candidates(
    driver,
    episode_id: str,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return outstanding `LINK_PROPOSED` candidates for human review.

    A candidate is "pending" when its `LINK_PROPOSED` audit record has
    NOT been resolved by either:
      - a `LINK_REJECTED` audit event whose `proposed_audit_event_id`
        matches the proposal's audit_id, or
      - a `LINK_ACCEPTED` audit event that asserts the same
        (source_episode, target_episode, link_type) triple (the
        proposal was elevated into an actual link by the user).

    The query keys off the source_episode's audit chain — proposals
    anchor their audit records there (Amendment v2.0 §5).

    Returns: list of dicts with proposal_audit_id, source_episode,
    target_episode, proposed_link_type, composite_score,
    inference_signals, threshold values, wall_clock_time, agent_id.
    Sorted by composite_score DESC so the highest-confidence
    pending candidates surface first.

    Empty list if Ariadne disabled. forward_delta JSON is decoded in
    Python (rather than via APOC) to keep the query dependency-free.
    """
    if not ARIADNE_ENABLED:
        return []

    def _query():
        import json as _json

        with driver.session() as session:
            result = session.run(
                """
                MATCH (ar:AriadneAuditRecord {episode_id: $episode_id})
                WHERE ar.delta_type IN ['LINK_PROPOSED', 'LINK_REJECTED', 'LINK_ACCEPTED']
                RETURN ar.audit_id AS audit_id,
                       ar.delta_type AS delta_type,
                       ar.forward_delta AS forward_delta,
                       ar.agent_id AS agent_id,
                       ar.wall_clock_time AS wall_clock_time
                """,
                {"episode_id": episode_id},
            )

            proposals: list[dict[str, Any]] = []
            rejected_proposal_ids: set[str] = set()
            accepted_triples: set[tuple[str, str, str]] = set()

            for record in result:
                delta_type = record["delta_type"]
                try:
                    forward = _json.loads(record["forward_delta"]) if record["forward_delta"] else {}
                except (TypeError, ValueError):
                    forward = {}

                if delta_type == "LINK_PROPOSED":
                    proposals.append({
                        "proposal_audit_id": record["audit_id"],
                        "source_episode": forward.get("source_episode"),
                        "target_episode": forward.get("target_episode"),
                        "proposed_link_type": forward.get("proposed_link_type"),
                        "composite_score": forward.get("composite_score"),
                        "inference_signals": forward.get("inference_signals", []),
                        "discovery_threshold_at_creation": forward.get(
                            "discovery_threshold_at_creation"
                        ),
                        "auto_accept_threshold_at_creation": forward.get(
                            "auto_accept_threshold_at_creation"
                        ),
                        "agent_id": record["agent_id"],
                        "wall_clock_time": record["wall_clock_time"],
                    })
                elif delta_type == "LINK_REJECTED":
                    proposed_id = forward.get("proposed_audit_event_id")
                    if proposed_id:
                        rejected_proposal_ids.add(proposed_id)
                elif delta_type == "LINK_ACCEPTED":
                    accepted_triples.add((
                        forward.get("source_episode"),
                        forward.get("target_episode"),
                        forward.get("link_type"),
                    ))

            pending = [
                p for p in proposals
                if p["proposal_audit_id"] not in rejected_proposal_ids
                and (
                    p["source_episode"],
                    p["target_episode"],
                    p["proposed_link_type"],
                ) not in accepted_triples
            ]

            pending.sort(
                key=lambda p: (p["composite_score"] or 0.0),
                reverse=True,
            )
            return pending[:limit]

    return await asyncio.to_thread(_query)


# ── Episode Grouping (Amendment v2.0 §7-§8) ─────────────────────────────────


async def list_memberships_for_episode(
    driver,
    episode_id: str,
    *,
    include_superseded: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List MembershipRecords for an episode.

    By default returns ACTIVE memberships only (records with no
    superseded_by_record_id). Set `include_superseded=True` to walk the
    full history including prior records.
    """
    if not ARIADNE_ENABLED:
        return []

    def _query():
        where_extra = "" if include_superseded else "AND m.superseded_by_record_id IS NULL"
        cypher = f"""
            MATCH (m:AriadneMembershipRecord {{episode_id: $episode_id}})
            WHERE 1=1 {where_extra}
            RETURN m {{.*}} AS record
            ORDER BY m.asserted_at DESC
            LIMIT $limit
        """
        with driver.session() as session:
            result = session.run(cypher, {"episode_id": episode_id, "limit": limit})
            return [dict(r["record"]) for r in result]

    return await asyncio.to_thread(_query)


async def list_memberships_for_group(
    driver,
    group_id: str,
    group_system: str,
    *,
    membership_roles: Optional[list[str]] = None,
    include_superseded: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List MembershipRecords for a (group_id, group_system) tuple.

    By default returns ACTIVE memberships only. Optional role filter.
    """
    if not ARIADNE_ENABLED:
        return []

    def _query():
        params: dict[str, Any] = {
            "group_id": group_id,
            "group_system": group_system,
            "limit": limit,
        }
        where_clauses = []
        if not include_superseded:
            where_clauses.append("m.superseded_by_record_id IS NULL")
        if membership_roles:
            where_clauses.append("m.membership_role IN $membership_roles")
            params["membership_roles"] = membership_roles
        where_sql = ("AND " + " AND ".join(where_clauses)) if where_clauses else ""
        cypher = f"""
            MATCH (m:AriadneMembershipRecord {{group_id: $group_id, group_system: $group_system}})
            WHERE 1=1 {where_sql}
            RETURN m {{.*}} AS record
            ORDER BY m.asserted_at ASC
            LIMIT $limit
        """
        with driver.session() as session:
            result = session.run(cypher, params)
            return [dict(r["record"]) for r in result]

    return await asyncio.to_thread(_query)


async def get_active_membership(
    driver,
    episode_id: str,
    group_id: str,
    group_system: str,
) -> Optional[dict[str, Any]]:
    """Get the active (unsuperseded) MembershipRecord for a specific
    (episode, group_id, group_system) tuple. Returns None if no membership
    exists or all are superseded (should not happen — succession always
    creates a new active record)."""
    if not ARIADNE_ENABLED:
        return None

    def _query():
        with driver.session() as session:
            result = session.run(
                """
                MATCH (m:AriadneMembershipRecord {
                    episode_id: $episode_id,
                    group_id: $group_id,
                    group_system: $group_system
                })
                WHERE m.superseded_by_record_id IS NULL
                RETURN m {.*} AS record
                """,
                {
                    "episode_id": episode_id,
                    "group_id": group_id,
                    "group_system": group_system,
                },
            )
            record = result.single()
            return dict(record["record"]) if record else None

    return await asyncio.to_thread(_query)


async def list_membership_history(
    driver,
    episode_id: str,
    group_id: str,
    group_system: str,
) -> list[dict[str, Any]]:
    """Return the full succession chain for an (episode, group) tuple,
    ordered oldest → newest. Used when reconstructing membership role
    history for audit / display.
    """
    if not ARIADNE_ENABLED:
        return []

    def _query():
        with driver.session() as session:
            result = session.run(
                """
                MATCH (m:AriadneMembershipRecord {
                    episode_id: $episode_id,
                    group_id: $group_id,
                    group_system: $group_system
                })
                RETURN m {.*} AS record
                ORDER BY m.asserted_at ASC
                """,
                {
                    "episode_id": episode_id,
                    "group_id": group_id,
                    "group_system": group_system,
                },
            )
            return [dict(r["record"]) for r in result]

    return await asyncio.to_thread(_query)


async def get_active_conformance_declaration(
    driver,
    group_system: str,
    group_id: str,
) -> Optional[dict[str, Any]]:
    """Return the active (unsuperseded) ConformanceDeclaration for a
    (group_system, group_id) pair. Returns None if no declaration is
    registered or all are superseded."""
    if not ARIADNE_ENABLED:
        return None

    def _query():
        with driver.session() as session:
            result = session.run(
                """
                MATCH (cd:AriadneConformanceDeclaration {
                    group_system: $group_system,
                    group_id: $group_id
                })
                WHERE cd.superseded_by IS NULL
                RETURN cd {.*} AS declaration
                ORDER BY cd.declared_at DESC
                LIMIT 1
                """,
                {"group_system": group_system, "group_id": group_id},
            )
            record = result.single()
            return dict(record["declaration"]) if record else None

    return await asyncio.to_thread(_query)


async def list_conformance_declarations(
    driver,
    group_system: Optional[str] = None,
    *,
    include_superseded: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List ConformanceDeclarations, optionally filtered by group_system.
    Returns active only by default."""
    if not ARIADNE_ENABLED:
        return []

    def _query():
        params: dict[str, Any] = {"limit": limit}
        where_clauses = []
        if group_system:
            where_clauses.append("cd.group_system = $group_system")
            params["group_system"] = group_system
        if not include_superseded:
            where_clauses.append("cd.superseded_by IS NULL")
        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        cypher = f"""
            MATCH (cd:AriadneConformanceDeclaration)
            {where_sql}
            RETURN cd {{.*}} AS declaration
            ORDER BY cd.declared_at DESC
            LIMIT $limit
        """
        with driver.session() as session:
            result = session.run(cypher, params)
            return [dict(r["declaration"]) for r in result]

    return await asyncio.to_thread(_query)
