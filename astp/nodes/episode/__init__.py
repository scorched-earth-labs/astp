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
ASTP Episode Node Type — the Phase 1 instantiation.

Episodes are bounded units of agent work with a formal lifecycle.
This is the first parameterization of CognitiveNode; the protocol
layer operates identically regardless of node type.
"""

from astp.nodes.episode.payload import EpisodePayload
from astp.nodes.episode.lifecycle import EpisodeState, VALID_TRANSITIONS
from astp.nodes.episode.factory import create_episode_node

__all__ = [
    "EpisodePayload",
    "EpisodeState",
    "VALID_TRANSITIONS",
    "create_episode_node",
]
