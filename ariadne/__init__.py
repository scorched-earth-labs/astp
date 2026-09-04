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
Ariadne Protocol — Cognitive persistence for multi-agent systems.

Bring your own cognitive architecture. Ariadne handles the persistence,
integrity verification, and coordination of agent state transitions.

Core modules:
    ariadne.core.schema         — Episode/Segment/Signal models, governance rules G1-G9
    ariadne.core.merkle         — Adaptive Merkle tree (integrity verification)
    ariadne.core.crystallization — Crystallization delta state machine
    ariadne.core.wil            — Write Intent Log (cross-system write coordination)

Adapters:
    ariadne.adapters.neo4j      — Reference implementation (Neo4j graph database)
"""

__version__ = "0.1.0"
