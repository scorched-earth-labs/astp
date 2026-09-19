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
ASTP — Audit record, version 2 (SPEC 5.0.0)

One audit record schema and one fully specified preimage. Under 4.x there are
two ``AuditRecord`` models with two hash constructions and two ``"GENESIS"``
sentinels, one of which hashes sorted JSON while storing it unsorted. This
module replaces neither in place: 4.x chains remain verifiable by the code that
wrote them. New chains are written under this construction.

    record_hash = SHA3-256("AUDIT_RECORD:v2:" ‖ enc(fields in the order below))

    UUID         audit_id
    STRING       chain_key             the chain this record belongs to — an Episode UUID as text (hashed as text,
                                       never as a UUID), or a synthetic key such as declaration:<system>:<group>
    UINT         delta_sequence        1 for the first record; +1 per record; never reset
    STRING       delta_type
    STRING       agent_id
    STRING       session_id
    STRING|NULL  human_actor
    TIMESTAMP    wall_clock_time       UTC, whole milliseconds
    UINT         episode_time          logical clock
    BYTES        forward_delta         canonical JSON (RFC 8785 + NFC), UTF-8
    BYTES        reverse_delta         canonical JSON (RFC 8785 + NFC), UTF-8
    LIST(STRING) affected_nodes        identifiers as canonical text, in the order written
    STRING       trigger_context
    STRING|NULL  explicit_reason
    STRING       caught_by
    BOOL         detection_window_open
    HASH|NULL    prior_audit_hash      NULL for the first record — there is no text sentinel

The record stores exactly what it hashes: the deltas are stored in their
canonical form, the timestamp at millisecond precision. A reader that hashes
what it reads gets the writer's digest.

A chain is verified from its first record: ``delta_sequence`` runs 1, 2, 3, …
without gap, the first record's ``prior_audit_hash`` is NULL, every later
record's is the previous record's ``record_hash``, and every ``record_hash``
recomputes from its fields.
"""

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator

from astp.protocol.canonical_json import canonical_json
from astp.protocol.encoding import BOOL, BYTES, HASH, LIST, NULL, STRING, TIMESTAMP, UINT, UUID_, hash_fields

AUDIT_RECORD_V2 = b"AUDIT_RECORD:v2:"


class AuditChainError(ValueError):
    """A version 2 audit chain does not verify; the message says where and why."""


def _text(value: Union[str, Enum]) -> str:
    return value.value if isinstance(value, Enum) else value


def _canonical_text(doc: Union[Dict[str, Any], str, bytes]) -> str:
    """The canonical JSON of ``doc`` as text. A string or bytes argument must
    already be canonical; anything else is refused rather than re-canonicalized,
    because the writer's text is what the record stores."""
    if isinstance(doc, (str, bytes)):
        raw = doc.encode("utf-8") if isinstance(doc, str) else bytes(doc)
        if canonical_json(json.loads(raw)) != raw:
            raise ValueError("delta text is not canonical JSON (RFC 8785 + NFC)")
        return raw.decode("utf-8")
    return canonical_json(doc).decode("utf-8")


def _to_ms(instant: datetime) -> datetime:
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("wall_clock_time must be timezone-aware")
    instant = instant.astimezone(timezone.utc)
    return instant.replace(microsecond=(instant.microsecond // 1000) * 1000)


class AuditRecordV2(BaseModel):
    """A version 2 audit record. Build one with :func:`make_audit_record`, which
    canonicalizes the deltas, truncates the timestamp and computes the hash;
    construct directly only when re-reading a stored record."""

    audit_id: UUID
    chain_key: str
    delta_sequence: int = Field(ge=1)
    delta_type: str
    agent_id: str
    session_id: str
    human_actor: Optional[str] = None
    wall_clock_time: datetime
    episode_time: int = Field(ge=0)
    forward_delta: str            # canonical JSON text — stored as hashed
    reverse_delta: str            # canonical JSON text — stored as hashed
    affected_nodes: List[str] = Field(default_factory=list)
    trigger_context: str
    explicit_reason: Optional[str] = None
    caught_by: str
    detection_window_open: bool
    prior_audit_hash: Optional[str] = None   # hex of the prior record_hash; None at genesis
    record_hash: str

    @field_validator("chain_key")
    @classmethod
    def _chain_key_nonempty(cls, v: str) -> str:
        if not v:
            raise ValueError("chain_key must not be empty")
        return v

    @field_validator("wall_clock_time")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("wall_clock_time must be timezone-aware")
        return v

    @field_validator("forward_delta", "reverse_delta")
    @classmethod
    def _canonical(cls, v: str) -> str:
        return _canonical_text(v)

    @field_validator("prior_audit_hash", "record_hash")
    @classmethod
    def _hex32(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        try:
            ok = len(bytes.fromhex(v)) == 32
        except ValueError:
            ok = False
        if not ok:
            raise ValueError("hash fields are 64 hex characters")
        return v.lower()


def compute_audit_record_hash_v2(
    *,
    audit_id: UUID,
    chain_key: str,
    delta_sequence: int,
    delta_type: str,
    agent_id: str,
    session_id: str,
    human_actor: Optional[str],
    wall_clock_time: datetime,
    episode_time: int,
    forward_delta: str,
    reverse_delta: str,
    affected_nodes: Sequence[str],
    trigger_context: str,
    explicit_reason: Optional[str],
    caught_by: str,
    detection_window_open: bool,
    prior_audit_hash: Optional[str],
) -> str:
    """The record hash over the fields exactly as the module docstring lists them.
    ``forward_delta`` and ``reverse_delta`` are canonical JSON text."""
    return hash_fields(AUDIT_RECORD_V2, [
        (UUID_, audit_id),
        (STRING, chain_key),
        (UINT, delta_sequence),
        (STRING, delta_type),
        (STRING, agent_id),
        (STRING, session_id),
        (NULL, None) if human_actor is None else (STRING, human_actor),
        (TIMESTAMP, wall_clock_time),
        (UINT, episode_time),
        (BYTES, forward_delta.encode("utf-8")),
        (BYTES, reverse_delta.encode("utf-8")),
        ((LIST, STRING), list(affected_nodes)),
        (STRING, trigger_context),
        (NULL, None) if explicit_reason is None else (STRING, explicit_reason),
        (STRING, caught_by),
        (BOOL, detection_window_open),
        (NULL, None) if prior_audit_hash is None else (HASH, prior_audit_hash),
    ])


def make_audit_record(
    *,
    chain_key: str,
    delta_sequence: int,
    delta_type: Union[str, Enum],
    agent_id: str,
    session_id: str,
    trigger_context: Union[str, Enum],
    forward_delta: Union[Dict[str, Any], str, bytes],
    reverse_delta: Union[Dict[str, Any], str, bytes],
    prior_audit_hash: Optional[str],
    affected_nodes: Sequence[str] = (),
    human_actor: Optional[str] = None,
    explicit_reason: Optional[str] = None,
    caught_by: str = "SYSTEM",
    detection_window_open: bool = False,
    wall_clock_time: Optional[datetime] = None,
    episode_time: int = 0,
    audit_id: Optional[UUID] = None,
) -> AuditRecordV2:
    """Build a record: canonicalize the deltas, normalize the timestamp to UTC
    milliseconds, compute ``record_hash``. What comes back is what is stored."""
    fields = dict(
        audit_id=audit_id or uuid4(),
        chain_key=chain_key,
        delta_sequence=delta_sequence,
        delta_type=_text(delta_type),
        agent_id=agent_id,
        session_id=session_id,
        human_actor=human_actor,
        wall_clock_time=_to_ms(wall_clock_time or datetime.now(timezone.utc)),
        episode_time=episode_time,
        forward_delta=_canonical_text(forward_delta),
        reverse_delta=_canonical_text(reverse_delta),
        affected_nodes=list(affected_nodes),
        trigger_context=_text(trigger_context),
        explicit_reason=explicit_reason,
        caught_by=caught_by,
        detection_window_open=detection_window_open,
        prior_audit_hash=prior_audit_hash,
    )
    return AuditRecordV2(record_hash=compute_audit_record_hash_v2(**fields), **fields)


def recompute_record_hash(record: AuditRecordV2) -> str:
    return compute_audit_record_hash_v2(**record.model_dump(exclude={"record_hash"}))


def verify_audit_chain_v2(records: Sequence[AuditRecordV2]) -> None:
    """Verify a whole chain, given its records in ``delta_sequence`` order.
    Raises :class:`AuditChainError` at the first record that fails; returns
    ``None`` when every record verifies. An empty chain verifies."""
    prior_hash: Optional[str] = None
    chain_key: Optional[str] = None
    for i, r in enumerate(records):
        expected_seq = i + 1
        if r.delta_sequence != expected_seq:
            raise AuditChainError(
                f"record {i}: delta_sequence {r.delta_sequence} != {expected_seq}")
        if chain_key is None:
            chain_key = r.chain_key
        elif r.chain_key != chain_key:
            raise AuditChainError(f"record {i}: chain_key {r.chain_key!r} != {chain_key!r}")
        if r.prior_audit_hash != prior_hash:
            raise AuditChainError(
                f"record {i}: prior_audit_hash {r.prior_audit_hash} != {prior_hash}")
        actual = recompute_record_hash(r)
        if actual != r.record_hash:
            raise AuditChainError(
                f"record {i}: record_hash {r.record_hash} does not recompute ({actual})")
        prior_hash = r.record_hash
