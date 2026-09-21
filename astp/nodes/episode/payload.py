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
ASTP Episode Payload — Episode-specific extension of NodePayload.

EpisodePayload carries episode metadata (title, participants, mode, etc.)
that the protocol layer never inspects. The protocol calls only
validate() and to_content_hash_input().
"""

import json
from typing import Any, Dict, List, Optional

from astp.core.schema import sha3_256
from astp.protocol.node import NodePayload


class EpisodePayload(NodePayload):
    """Episode-specific payload data.

    Contains all fields that are meaningful only for episodes —
    not for signals, agents, artifacts, or other future node types.
    """

    def __init__(
        self,
        title: str = "",
        context_note: str = "",
        episode_type: str = "",
        episode_mode: str = "directed",
        workspace_id: str = "",
        participants: Optional[List[str]] = None,
        segment_count: int = 0,
        signal_reads: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.title = title
        self.context_note = context_note
        self.episode_type = episode_type
        self.episode_mode = episode_mode
        self.workspace_id = workspace_id
        self.participants = participants or []
        self.segment_count = segment_count
        self.signal_reads = signal_reads or {}
        self.metadata = metadata or {}

    def validate(self) -> None:
        """Validate episode-specific invariants."""
        if self.episode_mode not in ("directed", "collaborative"):
            raise ValueError(
                f"Invalid episode_mode: '{self.episode_mode}'. "
                f"Must be 'directed' or 'collaborative'."
            )
        if self.segment_count < 0:
            raise ValueError(f"segment_count cannot be negative: {self.segment_count}")

    def to_content_hash_input(self) -> bytes:
        """Canonical byte representation for content_hash computation.

        Uses sorted-key JSON for deterministic serialization.
        """
        canonical = {
            "title": self.title,
            "context_note": self.context_note,
            "episode_type": self.episode_type,
            "episode_mode": self.episode_mode,
            "workspace_id": self.workspace_id,
            "participants": sorted(self.participants),
            "segment_count": self.segment_count,
        }
        return json.dumps(canonical, sort_keys=True).encode("utf-8")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage."""
        return {
            "title": self.title,
            "context_note": self.context_note,
            "episode_type": self.episode_type,
            "episode_mode": self.episode_mode,
            "workspace_id": self.workspace_id,
            "participants": self.participants,
            "segment_count": self.segment_count,
            "signal_reads": self.signal_reads,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EpisodePayload":
        """Deserialize from storage."""
        return cls(
            title=d.get("title", ""),
            context_note=d.get("context_note", ""),
            episode_type=d.get("episode_type", ""),
            episode_mode=d.get("episode_mode", "directed"),
            workspace_id=d.get("workspace_id", ""),
            participants=d.get("participants", []),
            segment_count=d.get("segment_count", 0),
            signal_reads=d.get("signal_reads", {}),
            metadata=d.get("metadata", {}),
        )

    def compute_content_hash(self) -> str:
        """Compute SHA3-256 of the canonical payload representation."""
        return sha3_256(self.to_content_hash_input())
