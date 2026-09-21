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
ASTP Neo4j Rebalance Adapter

Persistence for RebalanceEventNode — forensic audit trail for
tree rebalancing operations. Stored on AriadneRebalanceEvent nodes.

Every operation raises AdapterWriteError on failure; nothing is gated by a flag.
"""

import asyncio
import json
import logging
import os
from typing import Any

from astp.protocol.rebalance import RebalanceEventNode

logger = logging.getLogger("astp.adapters.neo4j.rebalance")



REBALANCE_SCHEMA = [
    "CREATE CONSTRAINT ariadne_rebalance_event_id IF NOT EXISTS "
    "FOR (re:AriadneRebalanceEvent) REQUIRE re.event_id IS UNIQUE",
    "CREATE INDEX ariadne_rebalance_node_id IF NOT EXISTS "
    "FOR (re:AriadneRebalanceEvent) ON (re.node_id)",
    "CREATE INDEX ariadne_rebalance_generation IF NOT EXISTS "
    "FOR (re:AriadneRebalanceEvent) ON (re.rebalance_generation)",
]


async def initialize_rebalance_schema(driver) -> None:
    """Create constraints and indexes for rebalance event nodes."""
    async with driver.session() as session:
        for stmt in REBALANCE_SCHEMA:
            await session.run(stmt)
    logger.info("ASTP rebalance event schema initialized")


async def write_rebalance_event(driver, event: RebalanceEventNode) -> None:
    """Persist a rebalance event to Neo4j."""
    def _write():
        with driver.session() as session:
            session.run("""
                CREATE (re:AriadneRebalanceEvent {
                    event_id:              $event_id,
                    node_id:               $node_id,
                    rebalance_generation:  $generation,
                    triggered_by:          $triggered_by,
                    pre_rebalance_root:    $pre_root,
                    post_rebalance_root:   $post_root,
                    leaf_index_delta:      $delta_json,
                    affected_leaf_count:   $affected,
                    executed_at:           $executed_at,
                    executor_id:           $executor_id
                })
            """, {
                "event_id": str(event.event_id),
                "node_id": str(event.node_id),
                "generation": event.rebalance_generation,
                "triggered_by": event.triggered_by,
                "pre_root": event.pre_rebalance_root,
                "post_root": event.post_rebalance_root,
                "delta_json": json.dumps(event.leaf_index_delta) if event.leaf_index_delta else "{}",
                "affected": event.affected_leaf_count,
                "executed_at": event.executed_at.isoformat(),
                "executor_id": event.executor_id,
            })

            # Link to episode/cognitive node
            session.run("""
                MATCH (re:AriadneRebalanceEvent {event_id: $event_id})
                MATCH (e:AriadneEpisode {episode_id: $node_id})
                CREATE (e)-[:REBALANCED {
                    generation: $generation,
                    executed_at: $executed_at
                }]->(re)
            """, {
                "event_id": str(event.event_id),
                "node_id": str(event.node_id),
                "generation": event.rebalance_generation,
                "executed_at": event.executed_at.isoformat(),
            })

    await asyncio.to_thread(_write)
    logger.info(
        f"Rebalance event recorded: node={str(event.node_id)[:12]}..., "
        f"generation={event.rebalance_generation}, "
        f"triggered_by={event.triggered_by}, "
        f"affected_leaves={event.affected_leaf_count}"
    )


async def list_rebalance_events(
    driver,
    node_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List rebalance events for a cognitive node, most recent first."""
    def _query():
        with driver.session() as session:
            result = session.run("""
                MATCH (re:AriadneRebalanceEvent {node_id: $node_id})
                RETURN re {.*} AS event
                ORDER BY re.rebalance_generation DESC
                LIMIT $limit
            """, {"node_id": node_id, "limit": limit})
            return [dict(r["event"]) for r in result]

    return await asyncio.to_thread(_query)
