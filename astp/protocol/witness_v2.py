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
ASTP — Witness commitment and witness validity, version 2
(SPEC 5.0.0)

A witness record is a claim by one party about what it saw: *this* witness saw
*this* root for *this* node at *this* time, in *this* role. Version 2 binds all
of that. 4.x bound the node, the root and the role but not the witness or the
time — so every witness of a root shared one commitment, and a record could be
copied under a second ``witness_id`` and count again toward G-11 — and it let a
record with an empty signature count as valid.

    commitment = SHA3-256("WITNESS_COMMITMENT:v2:" ‖
        STRING(witness_id) ‖ UUID(node_id) ‖ STRING(node_type)
        ‖ HASH(root) ‖ UINT(root_version)
        ‖ UINT(sequence_index) ‖ UINT(logical_clock) ‖ TIMESTAMP(witnessed_at)
        ‖ STRING(role) ‖ STRING(role_detail)|NULL )

``root`` is the node's outermost sealed commitment — the Episode root for an
Episode, the spine root for a node type that has no manifests — and
``root_version`` is the version of the construction that produced it.

The signature is Ed25519 over the 32 raw bytes of the commitment (the same
form as the HITL signatures of SPEC §4.6). ``public_key`` is the 32-byte
Ed25519 public key; ``public_key_fingerprint`` is its SHA3-256.

**Witness validity (G-12, version 2).** A record is valid if and only if:
its commitment recomputes from its fields; its signature verifies under its
public key over the raw commitment; its fingerprint is the SHA3-256 of that
key; and its ``witness_id`` is not the node's author. A record failing any of
these is recorded but never valid, and never counts toward a threshold.
Whether the named key belongs to the named witness is the workspace's key
registry to answer; the protocol verifies that the record was signed by the
key it names.

**Witness threshold (G-11, version 2).** A node meets a threshold *n* when at
least *n* valid records have pairwise-distinct ``witness_id`` **and**
pairwise-distinct ``public_key_fingerprint``: one key cannot count twice
under two names, and one name cannot count twice under two keys.
"""

from datetime import datetime
from typing import Optional, Sequence
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import BaseModel, Field

from astp.protocol.encoding import HASH, NULL, STRING, TIMESTAMP, UINT, UUID_, hash_fields
from astp.protocol.errors import GovernanceViolation
from astp.protocol.hashing import sha3_256

WITNESS_COMMITMENT_V2 = b"WITNESS_COMMITMENT:v2:"
SIGNATURE_SCHEME_ED25519 = "ed25519"


def compute_witness_commitment_v2(*, witness_id: str, node_id: UUID, node_type: str, root: str, root_version: int,
                                  sequence_index: int, logical_clock: int, witnessed_at: datetime, role: str,
                                  role_detail: Optional[str]) -> str:
    return hash_fields(WITNESS_COMMITMENT_V2, [
        (STRING, witness_id), (UUID_, node_id), (STRING, node_type), (HASH, root), (UINT, root_version),
        (UINT, sequence_index), (UINT, logical_clock), (TIMESTAMP, witnessed_at), (STRING, role),
        (NULL, None) if role_detail is None else (STRING, role_detail),
    ])


class WitnessRecordV2(BaseModel):
    witness_id: str
    node_id: UUID
    node_type: str
    root: str
    root_version: int = Field(ge=0)
    sequence_index: int = Field(ge=0)
    logical_clock: int = Field(ge=0)
    witnessed_at: datetime
    role: str
    role_detail: Optional[str] = None
    commitment_hash: str
    signature_scheme: str = SIGNATURE_SCHEME_ED25519
    signature: bytes                 # 64 bytes, over bytes.fromhex(commitment_hash)
    public_key: bytes                # 32 raw bytes
    public_key_fingerprint: str      # SHA3-256 hex of public_key

    def commitment_fields(self) -> dict:
        return self.model_dump(include={"witness_id", "node_id", "node_type", "root", "root_version",
                                        "sequence_index", "logical_clock", "witnessed_at", "role", "role_detail"})


def sign_witness_record_v2(private_key: Ed25519PrivateKey, **fields) -> WitnessRecordV2:
    """Build and sign a record. ``fields`` are the commitment fields; the
    timestamp is truncated to the millisecond it is hashed at."""
    fields.setdefault("role_detail", None)
    ts = fields["witnessed_at"]
    fields["witnessed_at"] = ts.replace(microsecond=(ts.microsecond // 1000) * 1000)
    commitment = compute_witness_commitment_v2(**fields)
    public_key = private_key.public_key().public_bytes_raw()
    return WitnessRecordV2(
        **fields,
        commitment_hash=commitment,
        signature=private_key.sign(bytes.fromhex(commitment)),
        public_key=public_key,
        public_key_fingerprint=sha3_256(public_key),
    )


class WitnessInvalid(ValueError):
    """The record is not a valid witness; the message says which condition failed."""


def check_witness_record_v2(record: WitnessRecordV2, node_author: str) -> None:
    """Raise :class:`WitnessInvalid` naming the first failed condition of G-12
    (version 2); return ``None`` for a valid record."""
    expected = compute_witness_commitment_v2(**record.commitment_fields())
    if record.commitment_hash != expected:
        raise WitnessInvalid("commitment does not recompute from the record's fields")
    if record.signature_scheme != SIGNATURE_SCHEME_ED25519:
        raise WitnessInvalid(f"unknown signature scheme {record.signature_scheme!r}")
    if len(record.public_key) != 32:
        raise WitnessInvalid("public key is not 32 bytes")
    if record.public_key_fingerprint != sha3_256(record.public_key):
        raise WitnessInvalid("public_key_fingerprint is not the SHA3-256 of public_key")
    try:
        Ed25519PublicKey.from_public_bytes(record.public_key).verify(record.signature, bytes.fromhex(record.commitment_hash))
    except (InvalidSignature, ValueError):
        raise WitnessInvalid("signature does not verify under public_key over the commitment")
    if record.witness_id == node_author:
        raise WitnessInvalid("a node's author cannot witness it")


def is_valid_witness_v2(record: WitnessRecordV2, node_author: str) -> bool:
    try:
        check_witness_record_v2(record, node_author)
    except WitnessInvalid:
        return False
    return True


def count_distinct_valid_witnesses_v2(records: Sequence[WitnessRecordV2], node_author: str) -> int:
    """The number of valid records with pairwise-distinct witness_id and
    pairwise-distinct public key: the size of the largest such set. Each valid
    record is an edge between a name and a key, so this is a maximum bipartite
    matching (a greedy pass is not exact: A/k1, A/k2, B/k1 admits two)."""
    edges = {}
    for r in records:
        if is_valid_witness_v2(r, node_author):
            edges.setdefault(r.witness_id, set()).add(r.public_key_fingerprint)
    match_of_key: dict = {}

    def augment(name: str, seen: set) -> bool:
        for key in edges[name]:
            if key in seen:
                continue
            seen.add(key)
            if key not in match_of_key or augment(match_of_key[key], seen):
                match_of_key[key] = name
                return True
        return False

    return sum(1 for name in edges if augment(name, set()))


def enforce_witness_threshold_v2(records: Sequence[WitnessRecordV2], node_author: str, min_counter_signatures: int) -> None:
    """G-11, version 2. Raises :class:`GovernanceViolation` when the threshold is not met."""
    n = count_distinct_valid_witnesses_v2(records, node_author)
    if n < min_counter_signatures:
        raise GovernanceViolation(
            f"Witness threshold not met (G-11): {n} distinct valid witnesses, threshold requires {min_counter_signatures}.")
