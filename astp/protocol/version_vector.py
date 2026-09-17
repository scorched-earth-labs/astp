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
ASTP — Version Vector

Tracks both content and structural evolution independently.
spine_version increments on content changes; tree_version increments
on structural changes (rebalancing). This enables cache invalidation
strategies that distinguish content from reorganization.
"""

from typing import Dict

from pydantic import BaseModel, Field


class VersionVector(BaseModel):
    """Multi-dimensional version tracking for cognitive nodes.

    agent_clocks: per-agent logical clock for multi-agent coordination
    global_seq: total ordering at commit time
    spine_version: increments on content change (segment append/modify)
    tree_version: increments on structural change (rebalance)
    """
    agent_clocks: Dict[str, int] = Field(default_factory=dict)
    global_seq: int = 0
    spine_version: int = 0
    tree_version: int = 0

    def increment_spine(self) -> "VersionVector":
        """Return new vector with spine_version incremented (content change)."""
        return self.model_copy(update={
            "spine_version": self.spine_version + 1,
            "global_seq": self.global_seq + 1,
        })

    def increment_tree(self) -> "VersionVector":
        """Return new vector with tree_version incremented (structural change)."""
        return self.model_copy(update={
            "tree_version": self.tree_version + 1,
            "global_seq": self.global_seq + 1,
        })

    def increment_for_agent(self, agent_id: str) -> "VersionVector":
        """Return new vector with the specified agent's clock incremented."""
        new_clocks = dict(self.agent_clocks)
        new_clocks[agent_id] = new_clocks.get(agent_id, 0) + 1
        return self.model_copy(update={
            "agent_clocks": new_clocks,
            "global_seq": self.global_seq + 1,
        })
