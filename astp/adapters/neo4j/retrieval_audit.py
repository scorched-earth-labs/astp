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
Ariadne Neo4j Retrieval Audit Adapter

Persistence for RetrievalAuditRecord — side-channel storage of
agent retrieval operations. Stored on AriadneRetrievalAudit nodes,
linked to episodes via RETRIEVAL_AUDIT edges.

Every operation raises AdapterWriteError on failure; nothing is gated by a flag.
"""

import asyncio
import json
import logging
import os
from typing import Any

from astp.protocol.retrieval_audit import RetrievalAuditRecord

from astp.protocol.errors import AdapterWriteError, AriadneProtocolError

logger = logging.getLogger("astp.adapters.neo4j.retrieval_audit")



RETRIEVAL_AUDIT_SCHEMA = [
    "CREATE CONSTRAINT ariadne_retrieval_audit_id IF NOT EXISTS "
    "FOR (ra:AriadneRetrievalAudit) REQUIRE ra.record_id IS UNIQUE",
    "CREATE INDEX ariadne_retrieval_audit_episode IF NOT EXISTS "
    "FOR (ra:AriadneRetrievalAudit) ON (ra.episode_id)",
    "CREATE INDEX ariadne_retrieval_audit_actor IF NOT EXISTS "
    "FOR (ra:AriadneRetrievalAudit) ON (ra.actor)",
    "CREATE INDEX ariadne_retrieval_audit_wall_clock IF NOT EXISTS "
    "FOR (ra:AriadneRetrievalAudit) ON (ra.wall_clock)",
]


async def initialize_retrieval_audit_schema(driver) -> None:
    """Create constraints and indexes for retrieval audit nodes."""
    async with driver.session() as session:
        for stmt in RETRIEVAL_AUDIT_SCHEMA:
            await session.run(stmt)
    logger.info("Ariadne retrieval audit schema initialized")


async def write_retrieval_audit(driver, record: RetrievalAuditRecord) -> None:
    """Persist a retrieval audit record to Neo4j.

    Non-fatal: failures are logged but do not propagate.
    Retrieval must never fail because audit logging failed.
    """
    def _write():
        try:
            with driver.session() as session:
                session.run("""
                    CREATE (ra:AriadneRetrievalAudit {
                        record_id:      $record_id,
                        episode_id:     $episode_id,
                        actor:          $actor,
                        tool_name:      $tool_name,
                        parameters:     $parameters,
                        segment_count:  $segment_count,
                        segment_ids:    $segment_ids,
                        snapshot_index: $snapshot_index,
                        wall_clock:     $wall_clock
                    })
                """, {
                    "record_id": str(record.record_id),
                    "episode_id": record.episode_id,
                    "actor": record.actor,
                    "tool_name": record.tool_name,
                    "parameters": json.dumps(record.parameters),
                    "segment_count": record.segment_count,
                    "segment_ids": record.segment_ids,
                    "snapshot_index": record.snapshot_index,
                    "wall_clock": record.wall_clock.isoformat(),
                })

                # Link to episode
                session.run("""
                    MATCH (ra:AriadneRetrievalAudit {record_id: $record_id})
                    MATCH (e:AriadneEpisode {episode_id: $episode_id})
                    CREATE (e)-[:RETRIEVAL_AUDIT {wall_clock: $wall_clock}]->(ra)
                """, {
                    "record_id": str(record.record_id),
                    "episode_id": record.episode_id,
                    "wall_clock": record.wall_clock.isoformat(),
                })
        except AriadneProtocolError:
            raise
        except Exception as e:
            logger.error(f"Retrieval audit write failed (non-fatal): {e}")
            raise AdapterWriteError(f"_write: {e}") from e

    await asyncio.to_thread(_write)


async def list_retrieval_audits_for_episode(
    driver,
    episode_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List retrieval audit records for an episode, most recent first."""
    def _query():
        with driver.session() as session:
            result = session.run("""
                MATCH (e:AriadneEpisode {episode_id: $episode_id})
                      -[:RETRIEVAL_AUDIT]->(ra:AriadneRetrievalAudit)
                RETURN ra {.*} AS record
                ORDER BY ra.wall_clock DESC
                LIMIT $limit
            """, {"episode_id": episode_id, "limit": limit})
            return [dict(r["record"]) for r in result]

    return await asyncio.to_thread(_query)
