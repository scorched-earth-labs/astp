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
Ariadne Protocol v2 — Key Hierarchy

HKDF-SHA3-256 key derivation for the three-level key hierarchy:
  Root Key Material → Workspace Key → Node Key → Seal Key

The node_type participates in the HKDF info string at the Node Key
level (G-16), creating cryptographic domain separation between node
types. Keys derived for "episode" are distinct from "signal" or
"artifact" even with identical node_id and workspace_id.

Node keys support signing only at the protocol layer. Encryption
is implementation-defined and outside the protocol surface.

Per IMPLEMENTATION-PHASE3.md Section 3.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.hashes import SHA3_256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from pydantic import BaseModel, Field

from ariadne.core.schema import sha3_256
from ariadne.protocol.errors import GovernanceViolation, MonotonicityViolation


# ── HKDF Derivation ─────────────────────────────────────────────────────────

def derive_workspace_key(
    root_key_material: bytes,
    workspace_id: str,
) -> bytes:
    """Derive a workspace key from root key material.

    HKDF(ikm=root_key_material, salt=workspace_id, info="ariadne.workspace.v1")

    Args:
        root_key_material: 32 bytes from KMS/HSM (implementation-defined source)
        workspace_id: Workspace identifier string

    Returns:
        32-byte workspace key
    """
    hkdf = HKDF(
        algorithm=SHA3_256(),
        length=32,
        salt=workspace_id.encode("utf-8"),
        info=b"ariadne.workspace.v1",
    )
    return hkdf.derive(root_key_material)


def derive_node_key(
    workspace_key: bytes,
    node_id: str,
    node_type: str,
) -> bytes:
    """Derive a node key from a workspace key.

    HKDF(ikm=workspace_key, salt=node_id, info="ariadne.node.v1:{node_type}")

    The node_type MUST appear in the info string (G-16). This creates
    cryptographic domain separation between node types.

    Args:
        workspace_key: 32-byte workspace key
        node_id: CognitiveNode identifier (UUID string)
        node_type: Node type string (e.g., "episode", "signal", "artifact")

    Returns:
        32-byte node key
    """
    info = f"ariadne.node.v1:{node_type}".encode("utf-8")
    hkdf = HKDF(
        algorithm=SHA3_256(),
        length=32,
        salt=node_id.encode("utf-8"),
        info=info,
    )
    return hkdf.derive(workspace_key)


def derive_seal_key(
    node_key: bytes,
    spine_root_at_seal: str,
) -> bytes:
    """Derive a seal key from a node key.

    HKDF(ikm=node_key, salt=spine_root_at_seal_bytes, info="ariadne.seal.v1")

    The spine_root is used as RAW BYTES (hex-decoded), not as a UTF-8
    string. This binds the seal key to a specific node state — a seal
    key derived from spine_root_1 is different from one derived from
    spine_root_2, even for the same node.

    Args:
        node_key: 32-byte node key
        spine_root_at_seal: Hex-encoded spine root hash at seal time

    Returns:
        32-byte seal key
    """
    hkdf = HKDF(
        algorithm=SHA3_256(),
        length=32,
        salt=bytes.fromhex(spine_root_at_seal),
        info=b"ariadne.seal.v1",
    )
    return hkdf.derive(node_key)


# ── Key Identity ─────────────────────────────────────────────────────────────

def compute_public_key_fingerprint(public_key_bytes: bytes) -> str:
    """SHA3-256 fingerprint of a public key for identification."""
    return sha3_256(public_key_bytes)


# ── NodeKeyRecord ────────────────────────────────────────────────────────────

class NodeKeyRecord(BaseModel):
    """Record of a key associated with a CognitiveNode.

    key_version is monotonically increasing (G-15). The protocol
    does not specify when to rotate — only that version numbers
    never go backward.
    """
    record_id: UUID = Field(default_factory=uuid4)
    node_id: str
    node_type: str
    workspace_id: str
    key_version: int
    public_key_fingerprint: str  # SHA3-256 of public key bytes
    derivation_path: str = ""  # Human-readable: "workspace/{wid}/node/{nid}"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def enforce_key_version_monotonicity(
    current_max_version: Optional[int],
    proposed_version: int,
) -> None:
    """Enforce G-15: key_version must be strictly increasing.

    Args:
        current_max_version: Current highest key_version for this node_id (None if first)
        proposed_version: The version being proposed

    Raises:
        MonotonicityViolation: If proposed version is not strictly greater
    """
    if current_max_version is not None and proposed_version <= current_max_version:
        raise MonotonicityViolation(
            f"Key version monotonicity violation (G-15): proposed version "
            f"{proposed_version} is not greater than current max {current_max_version}."
        )
