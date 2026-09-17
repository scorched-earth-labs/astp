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
Ariadne Segment Node Type — a point-in-time record within an episode.

Segments form the audit trail: each recorded action (a chat turn, tool call,
or annotation) is a segment linked to its episode via ``parent_node_id``.

Importing this package self-registers "segment" with the NodeTypeRegistry —
the idiomatic pattern for a node type living in its own package without
touching the protocol layer.
"""

from astp.nodes.factory import register_node_type
from astp.nodes.segment.payload import SegmentPayload
from astp.nodes.segment.factory import create_segment_node

# Self-register on import (idempotent — re-registration overwrites with the
# same definition). temporal_profile="point": a segment is an instantaneous
# record, unlike an episode which is "bounded".
register_node_type("segment", "Segment", temporal_profile="point")

__all__ = ["SegmentPayload", "create_segment_node"]
