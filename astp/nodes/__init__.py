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
ASTP Node Types — domain-specific extensions of CognitiveNode.

Each node type implements NodePayload and registers with the
NodeTypeRegistry. The protocol layer never imports from here.

``create_node`` is the generic, governed factory for every registered type;
``register_node_type`` is the extensibility hook for adopter-defined types.
"""

from astp.nodes.factory import create_node, register_node_type

# Imported for its side effect: the package registers "segment" with the
# NodeTypeRegistry ("episode" is pre-registered by astp.protocol.registry),
# so ``import astp.nodes`` makes every built-in type creatable.
from astp.nodes import segment as _segment  # noqa: F401

__all__ = ["create_node", "register_node_type"]
