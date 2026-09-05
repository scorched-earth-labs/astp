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
Ariadne Protocol v2 — Node Type Registry

Open enum registration for cognitive node types. "episode" is
pre-registered as the Phase 1 instantiation. New types (signal,
agent, artifact) register in Phase 2 without protocol layer changes.
"""

from typing import Dict, List, Optional

from pydantic import BaseModel


class NodeTypeDefinition(BaseModel):
    """Definition of a cognitive node type."""
    type_id: str
    type_name: str
    schema_extension: Optional[str] = None
    valid_proof_types: List[str] = []
    temporal_profile: str = "bounded"  # "bounded" | "unbounded" | "point"


class NodeTypeRegistry:
    """Registry of known cognitive node types.

    New node types require both coordination and schema sign-off.
    The registry validates node_type strings at creation time.
    """

    def __init__(self):
        self._registry: Dict[str, NodeTypeDefinition] = {}

    def register(self, defn: NodeTypeDefinition) -> None:
        """Register a node type definition."""
        self._registry[defn.type_id] = defn

    def get(self, type_id: str) -> Optional[NodeTypeDefinition]:
        """Get a node type definition by ID. Returns None if not registered."""
        return self._registry.get(type_id)

    def is_registered(self, type_id: str) -> bool:
        """Check if a node type is registered."""
        return type_id in self._registry

    def list_types(self) -> List[str]:
        """List all registered type IDs."""
        return list(self._registry.keys())


# Module-level singleton with Phase 1 type pre-registered
REGISTRY = NodeTypeRegistry()
REGISTRY.register(NodeTypeDefinition(
    type_id="episode",
    type_name="Episode",
    schema_extension="ariadne.nodes.episode",
    valid_proof_types=["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9"],
    temporal_profile="bounded",
))
