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
ASTP — Anchor commitment, version 2 (DRAFT for SPEC 5.0.0; not yet ratified)

What is submitted to a transparency log at crystallization (G-14): a claim
that *this* node, in *this* workspace, had *this* root at *this* sequence and
clock, at *this* time. No payload internals.

    commitment = SHA3-256("ANCHOR_COMMITMENT:v2:" ‖
        UUID(node_id) ‖ STRING(node_type) ‖ STRING(workspace_id)
        ‖ HASH(root) ‖ UINT(root_version)
        ‖ UINT(crystallization_sequence) ‖ UINT(logical_clock) ‖ TIMESTAMP(anchored_at) )

``root`` and ``root_version`` are as for the witness commitment: the node's
outermost sealed commitment and the version of the construction that produced
it. 4.x hashed a sorted-JSON document that carried a ``protocol_version``
string defaulting to the literal ``"2.3.0"`` and a timestamp truncated to the
second; neither is a claim about the node, and both are gone.
"""

from datetime import datetime
from uuid import UUID

from astp.protocol.encoding import HASH, STRING, TIMESTAMP, UINT, UUID_, hash_fields

ANCHOR_COMMITMENT_V2 = b"ANCHOR_COMMITMENT:v2:"


def compute_anchor_commitment_v2(*, node_id: UUID, node_type: str, workspace_id: str, root: str, root_version: int,
                                 crystallization_sequence: int, logical_clock: int, anchored_at: datetime) -> str:
    return hash_fields(ANCHOR_COMMITMENT_V2, [
        (UUID_, node_id), (STRING, node_type), (STRING, workspace_id), (HASH, root), (UINT, root_version),
        (UINT, crystallization_sequence), (UINT, logical_clock), (TIMESTAMP, anchored_at),
    ])
