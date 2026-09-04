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
Ariadne Protocol v2 — Position-Binding Leaf Hash

The authoritative leaf hash computation per Node-Generic Architecture
Revised Section 3.1. This is the cryptographic foundation of the
entire protocol.

The preimage includes:
  - node_id: identity
  - node_type: type tag (prevents type confusion attacks)
  - schema_version: version-aware verification
  - sequence_index: cognitive timeline position (IMMUTABLE)
  - content_hash: payload integrity
  - sealed_at: temporal seal
  - parent_node_id: graph position anchor

Explicitly EXCLUDED:
  - tree_leaf_index: mutable structural fact, changes during rebalancing

Variable-length fields (node_type, schema_version) are length-prefixed
to prevent collision attacks (e.g., ("ep","2.0") vs ("e","p2.0")).

sealed_at uses Unix milliseconds (8 bytes big-endian) for deterministic
encoding — avoids timezone/format non-determinism of ISO strings.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from ariadne.core.schema import sha3_256


def compute_leaf_hash(
    node_id: UUID,
    node_type: str,
    schema_version: str,
    sequence_index: int,
    content_hash: str,
    sealed_at: Optional[datetime] = None,
    parent_node_id: Optional[UUID] = None,
) -> str:
    """Compute the position-binding leaf hash for a CognitiveNode.

    This function is the canonical implementation. Any deviation
    from this preimage construction is a protocol error.

    Returns:
        SHA3-256 hex string
    """
    node_type_bytes = node_type.encode("utf-8")
    schema_version_bytes = schema_version.encode("utf-8")

    # Convert sealed_at to Unix milliseconds for deterministic encoding
    if sealed_at is not None:
        sealed_at_ms = int(sealed_at.timestamp() * 1000)
    else:
        sealed_at_ms = 0

    preimage = (
        node_id.bytes                                           # 16 bytes (UUID)
        + len(node_type_bytes).to_bytes(4, "big")               # 4 bytes length prefix
        + node_type_bytes                                        # variable
        + len(schema_version_bytes).to_bytes(4, "big")           # 4 bytes length prefix
        + schema_version_bytes                                   # variable
        + sequence_index.to_bytes(8, "big")                      # 8 bytes big-endian
        + bytes.fromhex(content_hash)                            # 32 bytes
        + sealed_at_ms.to_bytes(8, "big")                        # 8 bytes
        + (parent_node_id.bytes if parent_node_id else b"\x00" * 16)  # 16 bytes
    )

    return sha3_256(preimage)


def compute_leaf_hash_from_node(node) -> str:
    """Convenience wrapper that extracts fields from a CognitiveNode."""
    return compute_leaf_hash(
        node_id=node.node_id,
        node_type=node.node_type,
        schema_version=node.schema_version,
        sequence_index=node.sequence_index,
        content_hash=node.content_hash,
        sealed_at=node.sealed_at,
        parent_node_id=node.parent_node_id,
    )
