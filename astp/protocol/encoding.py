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
ASTP — Canonical Field Encoding (SPEC 5.0.0; pending ratification)

One encoding for every hash preimage that is built from named fields. A
construction is ``SHA3-256(prefix ‖ enc(f1) ‖ … ‖ enc(fn))``: a domain prefix
unique to the construction and its version, followed by the fields in a fixed
order, each encoded with a type tag. Because every field carries its type and
either a fixed width or a length, two different field tuples can never produce
the same byte string — which is the property the colon- and pipe-joined
preimages of 4.x lack.

    tag   type        payload
    0x00  NULL        (none) — an absent optional field
    0x01  BYTES       u32be(length) ‖ bytes
    0x02  STRING      u32be(length) ‖ UTF-8 of the NFC-normalized text
    0x03  UINT        8 bytes, big-endian, 0 ≤ n < 2^64
    0x04  UUID        16 bytes
    0x05  TIMESTAMP   8 bytes, big-endian: whole milliseconds since the Unix epoch, UTC
    0x06  HASH        32 bytes (a SHA3-256 value, raw — never its hex text)
    0x07  LIST        u32be(count) ‖ the items, each encoded as a field of one stated kind
    0x08  BOOL        one byte, 0x00 or 0x01
    0x09  FLOAT       8 bytes: IEEE 754 binary64, big-endian. NaN and ±inf are refused before
                      encoding; subnormals are encoded as-is; -0 -> +0 is the only normalization
"""

import struct
import unicodedata
from datetime import datetime, timezone
from typing import Iterable, Optional, Tuple, Union
from uuid import UUID

from astp.protocol.hashing import sha3_256

NULL, BYTES, STRING, UINT, UUID_, TIMESTAMP, HASH, LIST, BOOL, FLOAT = range(10)

Field = Tuple[object, object]   # (kind, value); a LIST kind is the tuple (LIST, item_kind)

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _u32(n: int) -> bytes:
    return n.to_bytes(4, "big")


def encode_field(kind: int, value: object) -> bytes:
    """Encode one field. ``None`` is permitted for any kind and encodes as NULL."""
    if value is None:
        return bytes([NULL])
    if kind == BYTES:
        if not isinstance(value, (bytes, bytearray)):
            raise TypeError("BYTES field requires bytes")
        return bytes([BYTES]) + _u32(len(value)) + bytes(value)
    if kind == STRING:
        if not isinstance(value, str):
            raise TypeError("STRING field requires str")
        data = unicodedata.normalize("NFC", value).encode("utf-8")
        return bytes([STRING]) + _u32(len(data)) + data
    if kind == UINT:
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 2**64:
            raise ValueError("UINT field requires an integer in [0, 2^64)")
        return bytes([UINT]) + value.to_bytes(8, "big")
    if kind == UUID_:
        if not isinstance(value, UUID):
            raise TypeError("UUID field requires uuid.UUID")
        return bytes([UUID_]) + value.bytes
    if kind == TIMESTAMP:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("TIMESTAMP field requires a timezone-aware datetime; naive datetimes are refused")
        delta = value.astimezone(timezone.utc) - _EPOCH
        millis = (delta.days * 86_400 + delta.seconds) * 1000 + delta.microseconds // 1000   # integer arithmetic only
        if not 0 <= millis < 2**64:
            raise ValueError("TIMESTAMP out of range")
        return bytes([TIMESTAMP]) + millis.to_bytes(8, "big")
    if kind == HASH:
        raw = bytes.fromhex(value) if isinstance(value, str) else bytes(value)
        if len(raw) != 32:
            raise ValueError("HASH field requires a 32-byte value")
        return bytes([HASH]) + raw
    if kind == BOOL:
        if not isinstance(value, bool):
            raise TypeError("BOOL field requires bool")
        return bytes([BOOL, 1 if value else 0])
    if kind == FLOAT:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("FLOAT field requires a real number")
        x = float(value)
        if x != x or x in (float("inf"), float("-inf")):
            raise ValueError("FLOAT field cannot be NaN or infinite")
        if x == 0.0:
            x = 0.0   # drops the sign of negative zero
        return bytes([FLOAT]) + struct.pack(">d", x)
    if isinstance(kind, tuple) and len(kind) == 2 and kind[0] == LIST:
        item_kind = kind[1]
        items = list(value)
        return bytes([LIST]) + _u32(len(items)) + b"".join(encode_field(item_kind, v) for v in items)
    raise ValueError(f"unknown field kind {kind!r}")


def encode_fields(fields: Iterable[Field]) -> bytes:
    return b"".join(encode_field(kind, value) for kind, value in fields)


def hash_fields(prefix: bytes, fields: Iterable[Field]) -> str:
    """``SHA3-256(prefix ‖ enc(fields))`` as lowercase hex."""
    return sha3_256(prefix + encode_fields(fields))


def hash_set(prefix: bytes, member_hashes: Iterable[Union[str, bytes]]) -> str:
    """Order-independent commitment to a set of hashes:
    ``SHA3-256(prefix ‖ u32be(n) ‖ h_1 ‖ … ‖ h_n)`` over the distinct members as
    32 raw bytes each, sorted ascending bytewise. The empty set is ``n = 0``."""
    members = sorted({bytes.fromhex(h) if isinstance(h, str) else bytes(h) for h in member_hashes})
    if any(len(m) != 32 for m in members):
        raise ValueError("set members must be 32-byte hashes")
    return sha3_256(prefix + _u32(len(members)) + b"".join(members))
