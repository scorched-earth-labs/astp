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
Canonical serialization for protocol content hashes.

Defines the canonicalizer used by every content-hash computation in the
protocol package. Centralized here so that:

1. Hash determinism is shared across all node types — datetimes
   normalize to UTC ISO 8601, UUIDs to str, enums to .value, floats
   to repr (no platform precision drift), Pydantic models to dict.
2. Adding a new node type with a content hash is a one-call boilerplate
   via `hash_preimage(model, ordered_fields)` rather than re-implementing
   the canonicalizer.
3. Cross-implementation interop: any conforming Ariadne implementation
   that uses the same canonicalization rules produces the same hash
   for the same input. This is wire-tier conformance per Amendment
   v2.0 §12.1.

**Field-order discipline**

`hash_preimage` takes an `ordered_fields` tuple so the call site fully
controls the canonical ordering of fields in the preimage. JSON
serialization uses `sort_keys=False` — we want the tuple's order, not
alphabetical. Adding a new field to a node's hash preimage is therefore
an explicit decision recorded at the call site.

**Exclusion discipline**

Fields NOT in `ordered_fields` are NOT in the hash. This is the
mechanism that implements the §10 forward-pointer-exclusion rule:
mutable forward pointers like `superseded_by_record_id` simply aren't
listed in their owner's `_HASH_PREIMAGE_FIELDS` tuple.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Sequence
from uuid import UUID

from pydantic import BaseModel

from astp.core.schema import sha3_256


def canonical_value(value: Any) -> Any:
    """Recursive canonical-form serialization helper.

    Datetimes → UTC ISO 8601. UUIDs → hex string. Enums → .value.
    Floats → repr (round-trippable, platform-stable). Lists → recurse.
    Pydantic models → dict via model_dump, then recurse. Dicts → recurse.

    Raises TypeError for unsupported types — fail loudly rather than
    let a silent stringification produce hashes that don't match across
    implementations. New types need an explicit branch.
    """
    if value is None:
        return None
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        # Always normalize to UTC for hash stability across timezones.
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Enum):
        return value.value
    # bool is a subclass of int — check first so it doesn't fall into
    # the int branch and lose its True/False JSON representation.
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        # repr() produces a round-trippable representation. Avoids
        # platform float→string differences that would break hash stability.
        return repr(value)
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return [canonical_value(v) for v in value]
    if isinstance(value, BaseModel):
        return {k: canonical_value(v) for k, v in value.model_dump().items()}
    if isinstance(value, dict):
        return {k: canonical_value(v) for k, v in value.items()}
    raise TypeError(f"Unhashable value type {type(value).__name__}: {value!r}")


def hash_preimage(model: BaseModel, ordered_fields: Sequence[str]) -> str:
    """SHA3-256 of a model's canonical preimage over the named fields.

    The standard pattern for any content-hash function in the protocol:

        _MY_HASH_PREIMAGE_FIELDS = ("field_a", "field_b", "field_c")

        def compute_my_node_hash(node: MyNode) -> str:
            return hash_preimage(node, _MY_HASH_PREIMAGE_FIELDS)

    Field order is the order in `ordered_fields`. JSON serialization
    uses `sort_keys=False`; the caller's tuple order is the preimage
    order. Excluding a field is as simple as not listing it.
    """
    preimage: dict[str, Any] = {}
    for field_name in ordered_fields:
        preimage[field_name] = canonical_value(getattr(model, field_name))
    serialized = json.dumps(
        preimage, sort_keys=False, separators=(",", ":"), ensure_ascii=False
    )
    return sha3_256(serialized.encode("utf-8"))
