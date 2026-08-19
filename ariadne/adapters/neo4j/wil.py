"""
Ariadne Neo4j+Redis WIL Adapter

Persistence operations for the Write Intent Log protocol.
Coordinates writes across Redis (ephemeral) and Neo4j (durable).
All operations are gated by ARIADNE_ENABLED feature flag.

Protocol-level models, invariants, and guards live in ariadne.core.wil.
This module handles only the database operations.
"""

import logging
import os
from datetime import datetime, timezone
from uuid import UUID

from ariadne.core.wil import (
    ARIADNE_ENABLED,
    StoreLayer,
    WILOperation,
    WILStatus,
    WriteIntentEntry,
    build_redis_episode_key,
    build_redis_manifest_key,
    build_redis_wil_key,
    enforce_provisional_state_guard,
    enforce_write_order,
    get_redis_ttl,
)

logger = logging.getLogger("ariadne.adapters.neo4j.wil")


# ── WIL Lifecycle ────────────────────────────────────────────────────────────

async def declare_write_intent(
    redis_client,
    operation: WILOperation,
    episode_id: UUID,
    stores_involved: list[StoreLayer],
    pre_state_hash: str,
    post_state_hash: str,
) -> WriteIntentEntry:
    """
    Phase 1: INTENT_DECLARED.
    Creates a WIL entry in Redis with completed_at=null.
    """
    if not ARIADNE_ENABLED:
        return WriteIntentEntry(
            operation=operation, episode_id=episode_id,
            stores_involved=stores_involved,
            pre_state_hash=pre_state_hash,
            post_state_hash=post_state_hash,
        )

    entry = WriteIntentEntry(
        operation=operation,
        episode_id=episode_id,
        stores_involved=enforce_write_order(stores_involved),
        pre_state_hash=pre_state_hash,
        post_state_hash=post_state_hash,
    )
    key = build_redis_wil_key(str(entry.intent_id))
    ttl = get_redis_ttl(key)
    await redis_client.setex(key, ttl, entry.model_dump_json())
    logger.debug(
        f"WIL: Intent declared -- {operation.value} "
        f"episode={episode_id} intent={entry.intent_id}"
    )
    return entry


async def record_store_completion(
    redis_client,
    intent_id: str,
    completed_store: StoreLayer,
) -> None:
    """
    Phase 2: Record successful store write.
    Updates last_completed_store for recovery resumption.
    """
    if not ARIADNE_ENABLED:
        return
    key = build_redis_wil_key(intent_id)
    raw = await redis_client.get(key)
    if not raw:
        logger.warning(f"WIL: Cannot record completion for {intent_id} -- entry not found")
        return
    entry = WriteIntentEntry.model_validate_json(raw)
    entry.last_completed_store = completed_store
    ttl = get_redis_ttl(key)
    await redis_client.setex(key, ttl, entry.model_dump_json())


async def complete_write_intent(
    redis_client,
    neo4j_driver,
    intent_id: str,
) -> None:
    """
    Phase 3: COMPLETION.
    Marks complete and graduates from Redis to Neo4j.
    """
    if not ARIADNE_ENABLED:
        return
    key = build_redis_wil_key(intent_id)
    raw = await redis_client.get(key)
    if not raw:
        logger.warning(f"WIL: Cannot complete {intent_id} -- entry not found")
        return

    entry = WriteIntentEntry.model_validate_json(raw)
    entry.completed_at = datetime.now(timezone.utc)
    entry.status = WILStatus.COMPLETE

    # Graduate to Neo4j
    params = {
        "intent_id": str(entry.intent_id),
        "operation": entry.operation.value,
        "episode_id": str(entry.episode_id),
        "stores_involved": [s.value for s in entry.stores_involved],
        "pre_state_hash": entry.pre_state_hash,
        "post_state_hash": entry.post_state_hash,
        "initiated_at": entry.initiated_at.isoformat(),
        "completed_at": entry.completed_at.isoformat(),
        "status": entry.status.value,
        "last_completed_store": entry.last_completed_store.value if entry.last_completed_store else None,
    }
    async with neo4j_driver.session() as session:
        await session.run("""
            MERGE (w:AriadneWILEntry {intent_id: $intent_id})
            ON CREATE SET
              w.operation             = $operation,
              w.episode_id            = $episode_id,
              w.stores_involved       = $stores_involved,
              w.pre_state_hash        = $pre_state_hash,
              w.post_state_hash       = $post_state_hash,
              w.initiated_at          = $initiated_at,
              w.completed_at          = $completed_at,
              w.status                = $status,
              w.last_completed_store  = $last_completed_store
        """, params)

    await redis_client.delete(key)
    logger.info(f"WIL: Intent {intent_id} completed and graduated to Neo4j")


async def fail_write_intent(
    redis_client,
    intent_id: str,
    reason: str,
) -> None:
    """Marks a WIL entry as FAILED. Remains in Redis for recovery scanner."""
    if not ARIADNE_ENABLED:
        return
    key = build_redis_wil_key(intent_id)
    raw = await redis_client.get(key)
    if not raw:
        return
    entry = WriteIntentEntry.model_validate_json(raw)
    entry.status = WILStatus.FAILED
    entry.failure_reason = reason
    ttl = get_redis_ttl(key)
    await redis_client.setex(key, ttl, entry.model_dump_json())
    logger.error(f"WIL: Intent {intent_id} failed -- {reason}")


# ── Recovery Scanner ─────────────────────────────────────────────────────────

async def find_incomplete_wil_entries(redis_client) -> list[WriteIntentEntry]:
    """
    Scans Redis for WIL entries with completed_at=null.
    Called on startup and periodically (recommended: every 5 minutes).
    """
    if not ARIADNE_ENABLED:
        return []
    incomplete = []
    async for key in redis_client.scan_iter("ariadne::wil::*"):
        raw = await redis_client.get(key)
        if not raw:
            continue
        try:
            entry = WriteIntentEntry.model_validate_json(raw)
            if entry.completed_at is None:
                incomplete.append(entry)
        except Exception as e:
            logger.warning(f"WIL recovery scan: Could not parse entry {key}: {e}")
    if incomplete:
        logger.warning(
            f"WIL: Found {len(incomplete)} incomplete write intent(s). "
            f"Recovery required for: {[str(e.intent_id) for e in incomplete]}"
        )
    return incomplete


async def replay_incomplete_write(
    redis_client,
    neo4j_driver,
    entry: WriteIntentEntry,
) -> None:
    """
    Marks entry as REPLAYING. Actual re-execution is delegated to
    operation-specific handlers based on entry.operation.
    """
    if not ARIADNE_ENABLED:
        return
    key = build_redis_wil_key(str(entry.intent_id))
    entry.status = WILStatus.REPLAYING
    ttl = get_redis_ttl(key)
    await redis_client.setex(key, ttl, entry.model_dump_json())
    logger.info(
        f"WIL: Replaying {entry.operation.value} intent={entry.intent_id} "
        f"episode={entry.episode_id} "
        f"resuming_after={entry.last_completed_store}"
    )


# ── Coordinated Write Sequences ─────────────────────────────────────────────

async def execute_episode_create(
    redis_client,
    neo4j_driver,
    episode,
    pre_state_hash: str = "",
    post_state_hash: str = "",
) -> str:
    """
    Coordinated write for EPISODE_CREATE (SPEC S12.4, Tier 1).

    Returns intent_id.

    Delegates the Neo4j write to `create_episode_node` rather than inlining the
    Cypher, for the same reason `execute_segment_commit` does: the writer owns
    the node's shape and its `_ariadne_guard`, and a second copy of that MERGE
    would drift from it.

    On the state hashes: `pre_state_hash` defaults to empty because an episode
    create is a genesis write — there is genuinely no prior state, so empty is
    the correct value here rather than a placeholder. The protocol defines no
    canonical hash for "episode exists, spine empty", so `post_state_hash` is
    left to the caller instead of inventing a preimage; preimages are governed
    and are not something a convenience wrapper should mint.

    Single-store, and still Tier 1: the three-phase form is what makes an
    interrupted episode create recognisable as `completed_at=null`, which a
    single completed entry could never express.
    """
    if not ARIADNE_ENABLED:
        return ""

    from ariadne.adapters.neo4j.writer import create_episode_node

    stores = [StoreLayer.NEO4J]
    intent = await declare_write_intent(
        redis_client, WILOperation.EPISODE_CREATE, episode.episode_id,
        stores, pre_state_hash, post_state_hash,
    )

    try:
        await create_episode_node(neo4j_driver, episode)
        await record_store_completion(
            redis_client, str(intent.intent_id), StoreLayer.NEO4J
        )
        await complete_write_intent(
            redis_client, neo4j_driver, str(intent.intent_id)
        )
    except Exception as e:
        await fail_write_intent(redis_client, str(intent.intent_id), str(e))
        raise

    return str(intent.intent_id)


async def execute_codicil_append(
    redis_client,
    neo4j_driver,
    codicil,
    pre_state_hash: str = "",
    post_state_hash: str = "",
) -> str:
    """
    Coordinated write for CODICIL_APPEND (SPEC S12.4, Tier 1).

    Returns intent_id.

    Delegates to `create_codicil_node`, which until now did not exist — the
    adapter interface declared `create_codicil` abstract and no Neo4j
    implementation was ever written, so consumers hand-rolled both the node and
    its ledger entry. That is the gap this closes.

    `post_state_hash` defaults to the codicil's own content_hash: a codicil is
    appended rather than integrated, so the meaningful commitment is to the
    addendum's content. Callers with a broader notion of post-write state can
    override it.
    """
    if not ARIADNE_ENABLED:
        return ""

    from ariadne.adapters.neo4j.writer import create_codicil_node

    stores = [StoreLayer.NEO4J]
    intent = await declare_write_intent(
        redis_client, WILOperation.CODICIL_APPEND, codicil.episode_id,
        stores, pre_state_hash, post_state_hash or codicil.content_hash,
    )

    try:
        await create_codicil_node(neo4j_driver, codicil)
        await record_store_completion(
            redis_client, str(intent.intent_id), StoreLayer.NEO4J
        )
        await complete_write_intent(
            redis_client, neo4j_driver, str(intent.intent_id)
        )
    except Exception as e:
        await fail_write_intent(redis_client, str(intent.intent_id), str(e))
        raise

    return str(intent.intent_id)


async def execute_signal_commit(
    redis_client,
    neo4j_driver,
    episode_id: UUID,
    signal_node_data: dict,
    pre_state_hash: str,
    post_state_hash: str,
    is_provisional: bool = False,
) -> str:
    """
    Coordinated write for SIGNAL_COMMIT.
    Blob write must be done by caller BEFORE calling this function.
    Returns intent_id.
    """
    if not ARIADNE_ENABLED:
        return ""

    if is_provisional:
        enforce_provisional_state_guard(True, StoreLayer.NEO4J, "signal during provisional window")

    stores = [StoreLayer.NEO4J, StoreLayer.REDIS]
    intent = await declare_write_intent(
        redis_client, WILOperation.SIGNAL_COMMIT, episode_id,
        stores, pre_state_hash, post_state_hash,
    )

    try:
        async with neo4j_driver.session() as session:
            await session.run("""
                MERGE (sig:AriadneSignal {signal_id: $signal_id})
                ON CREATE SET sig += $props
            """, {"signal_id": signal_node_data["signal_id"], "props": signal_node_data})
        await record_store_completion(redis_client, str(intent.intent_id), StoreLayer.NEO4J)

        episode_key = build_redis_episode_key(str(episode_id))
        ttl = get_redis_ttl(episode_key)
        await redis_client.expire(episode_key, ttl)
        await record_store_completion(redis_client, str(intent.intent_id), StoreLayer.REDIS)

        await complete_write_intent(redis_client, neo4j_driver, str(intent.intent_id))

    except Exception as e:
        await fail_write_intent(redis_client, str(intent.intent_id), str(e))
        raise

    return str(intent.intent_id)


async def execute_segment_commit(
    redis_client,
    neo4j_driver,
    segment,
    episode_status,
    pre_state_hash: str,
    post_state_hash: str,
    is_provisional: bool = False,
) -> str:
    """
    Coordinated write for SEGMENT_COMMIT (SPEC S12.4, Tier 1).

    Blob write must be done by caller BEFORE calling this function.
    Returns intent_id.

    Unlike the other coordinated writes in this module, this one delegates the
    Neo4j write to `create_segment_node` rather than inlining the Cypher. That
    is deliberate: the segment writer enforces G-1 and the crystallization lock
    guard, and duplicating its MERGE here would silently bypass both. A
    coordinated write must not be a way around governance.

    Prior to this function, segment commits were the one core spine operation
    with no ledger coverage — callers wrote the segment directly, and the
    absence of a WIL entry was indistinguishable from a lost one.
    """
    if not ARIADNE_ENABLED:
        return ""

    from ariadne.adapters.neo4j.writer import create_segment_node

    if is_provisional:
        enforce_provisional_state_guard(
            True, StoreLayer.NEO4J, "segment during provisional window"
        )

    stores = [StoreLayer.NEO4J, StoreLayer.REDIS]
    intent = await declare_write_intent(
        redis_client, WILOperation.SEGMENT_COMMIT, segment.episode_id,
        stores, pre_state_hash, post_state_hash,
    )

    try:
        await create_segment_node(neo4j_driver, segment, episode_status)
        await record_store_completion(
            redis_client, str(intent.intent_id), StoreLayer.NEO4J
        )

        episode_key = build_redis_episode_key(str(segment.episode_id))
        ttl = get_redis_ttl(episode_key)
        await redis_client.expire(episode_key, ttl)
        await record_store_completion(
            redis_client, str(intent.intent_id), StoreLayer.REDIS
        )

        await complete_write_intent(
            redis_client, neo4j_driver, str(intent.intent_id)
        )

    except Exception as e:
        await fail_write_intent(redis_client, str(intent.intent_id), str(e))
        raise

    return str(intent.intent_id)


async def execute_episode_seal(
    redis_client,
    neo4j_driver,
    episode_id: UUID,
    seal_node_data: dict,
    pre_state_hash: str,
    post_state_hash: str,
) -> str:
    """
    Coordinated write for EPISODE_SEAL.
    Blob write must be done by caller BEFORE calling this function.
    Returns intent_id.
    """
    if not ARIADNE_ENABLED:
        return ""

    stores = [StoreLayer.BLOB, StoreLayer.NEO4J, StoreLayer.REDIS]
    intent = await declare_write_intent(
        redis_client, WILOperation.EPISODE_SEAL, episode_id,
        stores, pre_state_hash, post_state_hash,
    )

    try:
        await record_store_completion(redis_client, str(intent.intent_id), StoreLayer.BLOB)

        async with neo4j_driver.session() as session:
            await session.run("""
                MERGE (seal:AriadneSeal {seal_id: $seal_id})
                ON CREATE SET seal += $props
            """, {"seal_id": seal_node_data["seal_id"], "props": seal_node_data})
            await session.run("""
                MATCH (seal:AriadneSeal {seal_id: $seal_id})
                MATCH (e:AriadneEpisode {episode_id: $episode_id})
                MERGE (seal)-[:SEALS {sealed_at: $sealed_at}]->(e)
            """, {
                "seal_id": seal_node_data["seal_id"],
                "episode_id": str(episode_id),
                "sealed_at": seal_node_data.get("sealed_at", ""),
            })
            await session.run("""
                MATCH (e:AriadneEpisode {episode_id: $episode_id})
                SET e.episode_status   = 'SEALED',
                    e.sealed_at        = $sealed_at,
                    e.episode_root_hash = $root_hash
            """, {
                "episode_id": str(episode_id),
                "sealed_at": seal_node_data.get("sealed_at", ""),
                "root_hash": seal_node_data.get("episode_root_hash", ""),
            })
        await record_store_completion(redis_client, str(intent.intent_id), StoreLayer.NEO4J)

        episode_key = build_redis_episode_key(str(episode_id))
        await redis_client.delete(episode_key)
        manifest_key = build_redis_manifest_key(str(episode_id))
        await redis_client.delete(manifest_key)
        await record_store_completion(redis_client, str(intent.intent_id), StoreLayer.REDIS)

        await complete_write_intent(redis_client, neo4j_driver, str(intent.intent_id))

    except Exception as e:
        await fail_write_intent(redis_client, str(intent.intent_id), str(e))
        raise

    return str(intent.intent_id)


async def execute_manifest_finalize(
    redis_client,
    neo4j_driver,
    episode_id: UUID,
    manifest_data: dict,
    pre_state_hash: str,
    post_state_hash: str,
) -> str:
    """Coordinated write for MANIFEST_FINALIZE. Returns intent_id."""
    if not ARIADNE_ENABLED:
        return ""

    stores = [StoreLayer.NEO4J, StoreLayer.REDIS]
    intent = await declare_write_intent(
        redis_client, WILOperation.MANIFEST_FINALIZE, episode_id,
        stores, pre_state_hash, post_state_hash,
    )

    try:
        async with neo4j_driver.session() as session:
            await session.run("""
                MERGE (m:AriadneSignalManifest {episode_id: $episode_id})
                ON CREATE SET m += $props
                ON MATCH SET  m += $props
            """, {
                "episode_id": str(episode_id),
                "props": {
                    "episode_id": str(episode_id),
                    "manifest_hash": manifest_data.get("manifest_hash", ""),
                    "entry_count": manifest_data.get("entry_count", 0),
                    "finalized_at": manifest_data.get("finalized_at", ""),
                    "schema_version": manifest_data.get("schema_version", "1.0.0"),
                },
            })
        await record_store_completion(redis_client, str(intent.intent_id), StoreLayer.NEO4J)

        manifest_key = build_redis_manifest_key(str(episode_id))
        await redis_client.delete(manifest_key)
        await record_store_completion(redis_client, str(intent.intent_id), StoreLayer.REDIS)

        await complete_write_intent(redis_client, neo4j_driver, str(intent.intent_id))

    except Exception as e:
        await fail_write_intent(redis_client, str(intent.intent_id), str(e))
        raise

    return str(intent.intent_id)


# ── Redis Failure Recovery Contract ──────────────────────────────────────────

async def handle_redis_failure_recovery(
    neo4j_driver,
    episode_id: str,
) -> dict:
    """
    Called when Redis is unavailable and provisional state may have been lost.
    Returns recovery summary — does NOT automatically re-execute writes.
    """
    if not ARIADNE_ENABLED:
        return {}

    async with neo4j_driver.session() as session:
        ep_result = await session.run("""
            MATCH (e:AriadneEpisode {episode_id: $episode_id})
            RETURN e.episode_status         AS status,
                   e.crystallization_status AS crystallization_status,
                   e.episode_root_hash      AS root_hash,
                   e.sealed_at              AS sealed_at
        """, {"episode_id": episode_id})
        episode_record = await ep_result.single()

        wil_result = await session.run("""
            MATCH (w:AriadneWILEntry {episode_id: $episode_id})
            WHERE w.status = 'COMPLETE'
            RETURN w.intent_id AS intent_id,
                   w.operation AS operation,
                   w.completed_at AS completed_at
            ORDER BY w.completed_at DESC
            LIMIT 10
        """, {"episode_id": episode_id})
        completed_wil = await wil_result.data()

    logger.warning(
        f"WIL: Redis failure recovery for episode {episode_id}. "
        f"Episode status: {episode_record['status'] if episode_record else 'UNKNOWN'}. "
        f"Last {len(completed_wil)} completed WIL entries available for replay guidance."
    )

    return {
        "episode_id": episode_id,
        "last_durable_status": episode_record["status"] if episode_record else None,
        "crystallization_status": episode_record["crystallization_status"] if episode_record else None,
        "episode_root_hash": episode_record["root_hash"] if episode_record else None,
        "completed_wil_entries": completed_wil,
        "recovery_action": (
            "REPLAY_INCOMPLETE_WRITES"
            if completed_wil else
            "EPISODE_STATE_LOST_REINITIALIZE"
        ),
    }
