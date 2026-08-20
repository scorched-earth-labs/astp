"""
Ariadne Neo4j Crystallization Adapter

Neo4j-specific persistence operations for the crystallization protocol.
All operations are gated by ARIADNE_ENABLED feature flag.

Protocol-level models, hashes, and guards live in ariadne.core.crystallization.
This module handles only the database operations.
"""

import json
import logging
import os
from uuid import UUID

from ariadne.core.schema import AriadneGovernanceError, compute_spine_hash
from ariadne.core.crystallization import (
    CrystallizationDeltaNode,
    CrystallizationVerificationResult,
    EpisodeVersionVector,
    build_crystallization_delta,
    compute_crystallization_node_hash,
    compute_spine_hash_for_episode,
    verify_crystallization_hashes,
)

logger = logging.getLogger("ariadne.adapters.neo4j.crystallization")

ARIADNE_ENABLED = os.getenv("ARIADNE_ENABLED", "false").lower() == "true"
IMPLICIT_CRYSTALLIZATION_ON_ARCHIVE = os.getenv(
    "ARIADNE_IMPLICIT_CRYSTALLIZATION_ON_ARCHIVE", "true"
).lower() == "true"


# ── CRYSTALLIZATION_PENDING Lock ─────────────────────────────────────────────

async def acquire_crystallization_lock(driver, episode_id: str) -> bool:
    """
    Sets episode_status to CRYSTALLIZATION_PENDING.
    Returns True if lock acquired, False if episode not in ACTIVE state
    or if pending HITL events exist.
    """
    if not ARIADNE_ENABLED:
        return False
    async with driver.session() as session:
        # Check for pending HITL events before acquiring lock
        hitl_check = await session.run("""
            MATCH (e:AriadneEpisode {episode_id: $episode_id})-[:HITL_GATE]->(h:AriadneHITLEvent)
            WHERE h.status = 'invoked'
            RETURN count(h) AS pending_count
        """, {"episode_id": episode_id})
        hitl_record = await hitl_check.single()
        pending_hitl = hitl_record["pending_count"] if hitl_record else 0

        if pending_hitl > 0:
            logger.warning(
                f"Ariadne: Cannot acquire crystallization lock for episode {episode_id} "
                f"-- {pending_hitl} pending HITL event(s) must be resolved first."
            )
            return False

        result = await session.run("""
            MATCH (e:AriadneEpisode {episode_id: $episode_id})
            WHERE e.episode_status = 'ACTIVE'
            SET e.episode_status = 'CRYSTALLIZATION_PENDING',
                e.crystallization_pending_at = datetime()
            RETURN e.episode_id AS locked
        """, {"episode_id": episode_id})
        record = await result.single()
        locked = record is not None
        if locked:
            logger.info(f"Ariadne: CRYSTALLIZATION_PENDING lock acquired for episode {episode_id}")
        else:
            logger.warning(
                f"Ariadne: Could not acquire crystallization lock for episode {episode_id} "
                f"-- episode not in ACTIVE state or not found."
            )
        return locked


async def release_crystallization_lock(driver, episode_id: str, success: bool) -> None:
    """
    Releases the CRYSTALLIZATION_PENDING lock.
    On success: transitions to CRYSTALLIZED. On failure: reverts to ACTIVE.
    """
    if not ARIADNE_ENABLED:
        return
    new_status = "CRYSTALLIZED" if success else "ACTIVE"
    async with driver.session() as session:
        await session.run("""
            MATCH (e:AriadneEpisode {episode_id: $episode_id})
            WHERE e.episode_status = 'CRYSTALLIZATION_PENDING'
            SET e.episode_status = $new_status,
                e.crystallization_pending_at = null
        """, {"episode_id": episode_id, "new_status": new_status})
    logger.info(
        f"Ariadne: Released crystallization lock for episode {episode_id} -> {new_status}"
    )


# ── Neo4j Write ──────────────────────────────────────────────────────────────

async def write_crystallization_delta(driver, delta: CrystallizationDeltaNode) -> None:
    """
    Persists a CrystallizationDeltaNode to Neo4j.
    PRECONDITION: CRYSTALLIZATION_PENDING lock must be held.
    POSTCONDITION: caller must call release_crystallization_lock(success=True).
    """
    if not ARIADNE_ENABLED:
        return

    content_json = json.dumps({
        "predecessor_hash": delta.content.predecessor_hash,
        "sealed_chain_root": delta.content.sealed_chain_root,
        "verification_timestamp": delta.content.verification_timestamp.isoformat(),
        "verification_authority": delta.content.verification_authority,
        "schema_version": delta.content.schema_version,
        "crystallization_scope": delta.content.crystallization_scope.value,
        "successor_episode_id": delta.content.successor_episode_id,
    }, sort_keys=True)

    params = {
        "delta_id": str(delta.delta_id),
        "episode_id": str(delta.episode_id),
        "chain_position": delta.chain_position,
        "content_json": content_json,
        "content_hash": delta.content_hash,
        "node_hash": delta.node_hash,
        "predecessor_hash": delta.content.predecessor_hash,
        "sealed_chain_root": delta.content.sealed_chain_root,
        "verification_timestamp": delta.content.verification_timestamp.isoformat(),
        "verification_authority": delta.content.verification_authority,
        "schema_version": delta.content.schema_version,
        "content_version": delta.version_vector.content_version,
        "lifecycle_version": delta.version_vector.lifecycle_version,
        "chain_version": delta.version_vector.chain_version,
        "created_at": delta.created_at.isoformat(),
    }

    async with driver.session() as session:
        await session.run("""
            CREATE (cd:AriadneCrystallizationDelta {
              delta_id:             $delta_id,
              episode_id:           $episode_id,
              delta_type:           'CRYSTALLIZATION',
              chain_position:       $chain_position,
              content_json:         $content_json,
              content_hash:         $content_hash,
              node_hash:            $node_hash,
              predecessor_hash:     $predecessor_hash,
              sealed_chain_root:    $sealed_chain_root,
              verification_timestamp: $verification_timestamp,
              verification_authority: $verification_authority,
              schema_version:       $schema_version,
              content_version:      $content_version,
              lifecycle_version:    $lifecycle_version,
              chain_version:        $chain_version,
              immutable:            true,
              created_at:           $created_at
            })
        """, params)

        await session.run("""
            MATCH (cd:AriadneCrystallizationDelta {delta_id: $delta_id})
            MATCH (e:AriadneEpisode {episode_id: $episode_id})
            CREATE (cd)-[:CRYSTALLIZES {
              crystallized_at:   $crystallized_at,
              chain_position:    $chain_position,
              sealed_chain_root: $sealed_chain_root
            }]->(e)
        """, {
            "delta_id": str(delta.delta_id),
            "episode_id": str(delta.episode_id),
            "crystallized_at": delta.content.verification_timestamp.isoformat(),
            "chain_position": delta.chain_position,
            "sealed_chain_root": delta.content.sealed_chain_root,
        })

        await session.run("""
            MATCH (e:AriadneEpisode {episode_id: $episode_id})
            SET e.crystallization_status = 'crystallized',
                e.last_crystallized_at   = $crystallized_at,
                e.last_crystallization_delta_id = $delta_id
        """, {
            "episode_id": str(delta.episode_id),
            "crystallized_at": delta.content.verification_timestamp.isoformat(),
            "delta_id": str(delta.delta_id),
        })

    logger.info(
        f"Ariadne: Crystallization delta {delta.delta_id} written for "
        f"episode {delta.episode_id} at chain_position={delta.chain_position}"
    )


# ── Two-Phase Verification ───────────────────────────────────────────────────

async def verify_crystallization_delta(
    driver,
    delta_id: str,
    segment_content_hashes: list[str],
    spine_signal_hashes: list[str],
) -> CrystallizationVerificationResult:
    """
    Fetches stored crystallization data from Neo4j and delegates
    to the protocol-level verification function.
    """
    if not ARIADNE_ENABLED:
        return CrystallizationVerificationResult(
            episode_id="", delta_id=delta_id,
            phase_1_passed=False, phase_2_passed=False, verified=False,
            failure_reason="ARIADNE_ENABLED is false"
        )

    async with driver.session() as session:
        result = await session.run("""
            MATCH (cd:AriadneCrystallizationDelta {delta_id: $delta_id})
            RETURN
              cd.episode_id         AS episode_id,
              cd.predecessor_hash   AS predecessor_hash,
              cd.sealed_chain_root  AS sealed_chain_root,
              cd.node_hash          AS node_hash,
              cd.content_hash       AS content_hash,
              cd.chain_position     AS chain_position
        """, {"delta_id": delta_id})
        record = await result.single()

    if not record:
        return CrystallizationVerificationResult(
            episode_id="", delta_id=delta_id,
            phase_1_passed=False, phase_2_passed=False, verified=False,
            failure_reason=f"CrystallizationDelta {delta_id} not found in Neo4j"
        )

    return verify_crystallization_hashes(
        stored_content_hash=record["content_hash"],
        stored_predecessor_hash=record["predecessor_hash"],
        stored_node_hash=record["node_hash"],
        stored_sealed_chain_root=record["sealed_chain_root"],
        segment_content_hashes=segment_content_hashes,
        spine_signal_hashes=spine_signal_hashes,
        episode_id=record["episode_id"],
        delta_id=delta_id,
    )


# ── Ordering Constraint ─────────────────────────────────────────────────────

async def get_next_valid_chain_position(driver, episode_id: str) -> int:
    """
    Returns the next valid chain_position for a crystallization delta.
    Raises if no new content since last crystallization.
    """
    if not ARIADNE_ENABLED:
        return 0
    async with driver.session() as session:
        result = await session.run("""
            MATCH (cd:AriadneCrystallizationDelta {episode_id: $episode_id})
            RETURN max(cd.chain_position) AS last_crystallization_position
        """, {"episode_id": episode_id})
        record = await result.single()
        last_crystallization_pos = record["last_crystallization_position"] if record else None

        result2 = await session.run("""
            MATCH (e:AriadneEpisode {episode_id: $episode_id})
            OPTIONAL MATCH (e)-[:CONTAINS]->(s:AriadneSegment)
            OPTIONAL MATCH (e)-[:RECEIVED]->(sig:AriadneSignal)
              WHERE sig.placement = 'SPINE'
            RETURN count(DISTINCT s) + count(DISTINCT sig) AS content_count
        """, {"episode_id": episode_id})
        record2 = await result2.single()
        content_count = record2["content_count"] if record2 else 0

    if last_crystallization_pos is not None and content_count <= last_crystallization_pos:
        raise AriadneGovernanceError(
            f"Ordering constraint violation: Cannot re-crystallize episode {episode_id}. "
            f"No new content deltas since last crystallization at position "
            f"{last_crystallization_pos}. Add content before re-crystallizing."
        )

    return content_count + 1


async def get_chain_crystallization_count(driver, episode_id: str) -> int:
    """Returns count of CRYSTALLIZATION_DELTA events in a chain."""
    if not ARIADNE_ENABLED:
        return 0
    async with driver.session() as session:
        result = await session.run("""
            MATCH (cd:AriadneCrystallizationDelta {episode_id: $episode_id})
            RETURN count(cd) AS count
        """, {"episode_id": episode_id})
        record = await result.single()
        return record["count"] if record else 0


async def is_episode_crystallized(driver, episode_id: str) -> bool:
    """Fast path query: 'Is this episode crystallized?' O(1) via index."""
    if not ARIADNE_ENABLED:
        return False
    async with driver.session() as session:
        result = await session.run("""
            MATCH (cd:AriadneCrystallizationDelta {episode_id: $episode_id})
            RETURN count(cd) > 0 AS is_crystallized
        """, {"episode_id": episode_id})
        record = await result.single()
        return bool(record["is_crystallized"]) if record else False


# ── Implicit Crystallization on Archive ──────────────────────────────────────

async def archive_episode(
    driver,
    episode_id: str,
    archiving_agent: str,
    version_vector: EpisodeVersionVector,
    segment_content_hashes: list[str],
    spine_signal_hashes: list[str],
    predecessor_hash: str,
    redis_client=None,
) -> None:
    """
    Archives an episode. If ARIADNE_IMPLICIT_CRYSTALLIZATION_ON_ARCHIVE=true
    and the episode is not yet crystallized, auto-crystallizes before archiving.

    `redis_client` is optional and additive. When supplied, the implicit
    pre-archive crystallization runs through the coordinated write path and
    emits its own CRYSTALLIZATION ledger entry — a crystallization genuinely
    happened, so the ledger should say so rather than leaving it implied by an
    archive entry. When omitted, behaviour is exactly as before: the
    crystallization happens unledgered.
    """
    if not ARIADNE_ENABLED:
        return

    is_cryst = await is_episode_crystallized(driver, episode_id)

    if not is_cryst:
        if IMPLICIT_CRYSTALLIZATION_ON_ARCHIVE:
            logger.info(
                f"Ariadne: Auto-crystallizing episode {episode_id} before archive"
            )
            async def _build_delta():
                sealed_chain_root = compute_spine_hash_for_episode(
                    segment_content_hashes, spine_signal_hashes
                )
                chain_position = await get_next_valid_chain_position(driver, episode_id)
                return build_crystallization_delta(
                    episode_id=UUID(episode_id),
                    predecessor_hash=predecessor_hash,
                    sealed_chain_root=sealed_chain_root,
                    verification_authority=archiving_agent,
                    chain_position=chain_position,
                    version_vector=version_vector,
                )

            if redis_client is not None:
                # Ledgered path: the implicit crystallization gets its own
                # CRYSTALLIZATION entry, and the lock sequence is owned by the
                # coordinated helper rather than duplicated here.
                from ariadne.adapters.neo4j.wil import execute_crystallization

                intent_id = await execute_crystallization(
                    redis_client, driver, episode_id, _build_delta
                )
                if not intent_id:
                    raise AriadneGovernanceError(
                        f"Cannot archive episode {episode_id}: failed to acquire "
                        f"crystallization lock for implicit pre-archive crystallization."
                    )
            else:
                locked = await acquire_crystallization_lock(driver, episode_id)
                if not locked:
                    raise AriadneGovernanceError(
                        f"Cannot archive episode {episode_id}: failed to acquire "
                        f"crystallization lock for implicit pre-archive crystallization."
                    )
                try:
                    await write_crystallization_delta(driver, await _build_delta())
                    await release_crystallization_lock(driver, episode_id, success=True)
                except Exception:
                    await release_crystallization_lock(driver, episode_id, success=False)
                    raise
        else:
            raise AriadneGovernanceError(
                f"Archive rejected: Episode {episode_id} is not crystallized and "
                f"ARIADNE_IMPLICIT_CRYSTALLIZATION_ON_ARCHIVE=false. "
                f"Either crystallize the episode explicitly before archiving, or "
                f"set ARIADNE_IMPLICIT_CRYSTALLIZATION_ON_ARCHIVE=true."
            )

    async with driver.session() as session:
        await session.run("""
            MATCH (e:AriadneEpisode {episode_id: $episode_id})
            SET e.episode_status = 'ARCHIVED',
                e.archived_at    = datetime()
        """, {"episode_id": episode_id})
    logger.info(f"Ariadne: Episode {episode_id} archived.")
