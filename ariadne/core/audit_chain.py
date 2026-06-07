"""
Audit chain helpers — shared by every Ariadne operation that advances the
tamper-evident audit log.

Three modules currently emit AuditRecords (`branch_operations.py`,
`cross_episode.py`, `grouping.py`); before this lift, each held private
duplicates of these two helpers. They're now centralized here.

**Chain key semantics**

An audit chain is keyed by a string. The most common chain key is an
episode_id (e.g., `"a18748aa-12c2-495a-..."`) — every audit event for
that episode advances its own monotonic sequence and forms a hash-linked
chain. Some operations (notably ConformanceDeclaration version bumps in
the grouping module) anchor to a synthetic chain key — e.g.,
`"declaration:sel-thermyt:Collection:<group_id>"` — when the event has
no natural episode home.

The protocol places no constraint on the chain_key format. Implementations
choose what makes sense for their event type. The chain_key flows
through to `AriadneAuditRecord.episode_id` as the indexed lookup field.

**DI discipline**

Both helpers take the driver as an argument. They reach for no module-
level state and no globals. This matches the dependency-injection
pattern that runs through the rest of the protocol package.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("ariadne.core.audit_chain")


# Sentinel for the start of any chain. Every audit chain's first record
# has `prior_audit_hash="GENESIS"`. Defined here so call sites don't
# pass string literals around.
GENESIS_HASH = "GENESIS"


def next_delta_sequence(driver: Any, chain_key: str) -> int:
    """Return the next monotonic sequence number for a chain.

    Returns 1 for an empty chain. Sequences are scoped per chain_key
    and never reset within that chain.

    Failures fall through to returning 1 — under the protocol's "audit
    chain advance must not block operations" rule, a transient query
    error should not stop the calling operation from emitting its audit
    record. The returned sequence may collide with an existing record
    in that pathological case; integrity is still verifiable via the
    hash chain, and the duplicate sequence is itself an auditable
    anomaly.
    """
    try:
        with driver.session() as session:
            result = session.run(
                """
                MATCH (ar:AriadneAuditRecord {episode_id: $eid})
                RETURN max(ar.delta_sequence) AS max_seq
                """,
                # Cypher parameter is `$eid` for backward compatibility with
                # the test fakes in tests/unit/protocol/test_phase2_operations.py
                # and similar. The Python-level parameter is `chain_key`
                # because the value may be an episode_id OR a synthetic chain
                # key (e.g., "declaration:<system>:<group>"). Cypher parameter
                # name is implementation detail; the function contract is on
                # the Python signature.
                {"eid": chain_key},
            )
            record = result.single()
            current_max = record["max_seq"] if record and record["max_seq"] is not None else 0
            return current_max + 1
    except Exception as e:
        logger.warning(f"audit_chain.next_delta_sequence fallback: {e}")
        return 1


def prior_audit_hash(driver: Any, chain_key: str) -> str:
    """Return the hash of the most recent audit record on this chain.

    Returns `GENESIS_HASH` if the chain is empty. The caller uses this
    as the `prior_audit_hash` field on the new AuditRecord it's about
    to write, forming the hash chain.

    Same fallback semantics as `next_delta_sequence` — a transient
    query error returns GENESIS rather than blocking the operation.
    The integrity check that catches this is the chain-completeness
    proof (Amendment v2.0 §11.2.3); a spurious GENESIS in the middle
    of a chain shows up as a hash mismatch at the next record.
    """
    try:
        with driver.session() as session:
            result = session.run(
                """
                MATCH (ar:AriadneAuditRecord {episode_id: $eid})
                RETURN ar.record_hash AS hash
                ORDER BY ar.delta_sequence DESC
                LIMIT 1
                """,
                # See `next_delta_sequence` for the $eid vs chain_key rationale.
                {"eid": chain_key},
            )
            record = result.single()
            return record["hash"] if record and record["hash"] else GENESIS_HASH
    except Exception as e:
        logger.warning(f"audit_chain.prior_audit_hash fallback: {e}")
        return GENESIS_HASH
