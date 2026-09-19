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
Audit chain helpers — shared by every Ariadne operation that advances the
tamper-evident audit log.

Three modules emit AuditRecords (`branch_operations.py`,
`cross_episode.py`, `grouping.py`); they share the two helpers defined here.

**Chain key semantics**

An audit chain is keyed by a string. The most common chain key is an
episode_id (a UUID string) — every audit event for
that episode advances its own monotonic sequence and forms a hash-linked
chain. Some operations (notably ConformanceDeclaration version bumps in
the grouping module) anchor to a synthetic chain key — e.g.,
`"declaration:<group_system>:<group_id>"` — when the event has
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

from astp.protocol.errors import AdapterWriteError, AriadneProtocolError

logger = logging.getLogger("astp.core.audit_chain")


# Sentinel for the start of any chain. Every audit chain's first record
# has `prior_audit_hash="GENESIS"`. Defined here so call sites don't
# pass string literals around.
GENESIS_HASH = "GENESIS"


def next_delta_sequence(driver: Any, chain_key: str) -> int:
    """Return the next monotonic sequence number for a chain.

    Returns 1 for an empty chain. Sequences are scoped per chain_key
    and never reset within that chain.

    A failure to read the chain head raises ``AdapterWriteError``: a writer
    that cannot read the head MUST NOT guess a sequence (SPEC §8.2). Until
    5.1.0 this fell through to 1, which manufactured a second genesis
    mid-chain on any transient error.
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
    except AriadneProtocolError:
        raise
    except Exception as e:
        logger.error(f"audit_chain.next_delta_sequence: cannot read chain head: {e}")
        raise AdapterWriteError(f"next_delta_sequence: {e}") from e


def prior_audit_hash(driver: Any, chain_key: str) -> str:
    """Return the hash of the most recent audit record on this chain.

    Returns `GENESIS_HASH` if the chain is empty. The caller uses this
    as the `prior_audit_hash` field on the new AuditRecord it's about
    to write, forming the hash chain.

    A failure to read the chain head raises ``AdapterWriteError`` (see
    ``next_delta_sequence``): returning GENESIS on a transient error, as
    this did until 5.1.0, forged a chain restart.
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
    except AriadneProtocolError:
        raise
    except Exception as e:
        logger.error(f"audit_chain.prior_audit_hash: cannot read chain head: {e}")
        raise AdapterWriteError(f"prior_audit_hash: {e}") from e
