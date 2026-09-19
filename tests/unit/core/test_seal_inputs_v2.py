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
"""fetch_seal_inputs_v2: graph properties → the inputs of a version 2 seal,
checked against the ratified vector fixture through a fake session."""

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from astp.adapters.neo4j import seal_inputs as SI
from astp.core.seal_v2 import compute_episode_seal_v2
from astp.protocol.errors import AdapterWriteError

V = json.loads((Path(__file__).parents[3] / "vectors" / "5.0.0" / "seal-constructions.json").read_text("utf-8"))
EP = V["episode_id"]
T = datetime(2026, 1, 1, 0, 0, 0, 123000, tzinfo=timezone.utc)
SIGNALS = V["signals"] if isinstance(V["signals"], list) else list(V["signals"].values())


def nid(i): return f"00000000-0000-4000-8000-{i:012x}"


class _Session:
    """Answers each query from a table keyed by a distinctive fragment of its text."""
    def __init__(self, rows): self.rows = rows
    def run(self, q, params=None):
        for key, val in self.rows.items():
            if key in q:
                return list(val)
        return []


def _rows(hitl_context="{}"):
    segs = [dict(id=s["node_id"], seq=s["sequence_index"], h=s["content_hash"], sv=s["schema_version"], ephemeral=False)
            for s in V["segments"]]
    return {
        "AriadneSegment": segs,
        "AriadneSignal": [dict(h=h) for h in SIGNALS],
        "AriadneBranchPoint {episode_id: $e})\nRETURN": [dict(id=nid(10), episode_id=EP, branch_id=nid(11), seg=nid(2), snap="ab" * 32,
                                                      bt="EXPLORATORY", dt="EXPLICIT", ts=T.isoformat(), parent="GENESIS")],
        "AriadneBranchTerminus": [], "AriadneForkPoint": [], "AriadneDepartureForkPoint": [], "AriadneForkReturn": [], "AriadneMergePoint": [],
        "AriadneHITLEvent": [dict(id=nid(20), req="req-1", episode_id=EP, gate="APPROVAL", agent="agent-α", invoked_at=T.isoformat(),
                                  context_json=hitl_context, decision="approved", resolved_by="devin", resolved_at=T.isoformat(), rationale=None)],
    }


def test_reads_the_six_segment_fields_and_seals_to_the_vector_roots_when_structure_is_empty():
    rows = _rows(); rows["AriadneBranchPoint {episode_id: $e})\nRETURN"] = []; rows["AriadneHITLEvent"] = []
    inp = SI.fetch_seal_inputs_v2(_Session(rows), EP)
    assert inp.sealable_under_v2 and len(inp.segments) == 7 and inp.structural_member_hashes == []
    seal = compute_episode_seal_v2(inp.episode_id, inp.segments, signal_content_hashes=inp.signal_content_hashes,
                                   excluded_content_hashes=inp.excluded_content_hashes, structural_member_hashes=inp.structural_member_hashes)
    assert seal.spine_root == V["spine_root_sav2"]["7"]
    assert seal.episode_root_hash == V["episode_root_v2"]["with_empty_structural_manifest"]


def test_structural_members_are_computed_from_stored_fields_with_genesis_as_null():
    from astp.core.seal_v2 import compute_branch_point_hash_v2, compute_hitl_context_hash_v2, compute_hitl_node_hash_v2, compute_hitl_resolution_hash_v2
    inp = SI.fetch_seal_inputs_v2(_Session(_rows()), EP)
    bp = compute_branch_point_hash_v2(UUID(nid(10)), UUID(EP), UUID(nid(11)), UUID(nid(2)), "ab" * 32, "EXPLORATORY", "EXPLICIT", T, None)
    ctx = compute_hitl_context_hash_v2("req-1", UUID(EP), "APPROVAL", "agent-α", T, "{}")
    res = compute_hitl_resolution_hash_v2(UUID(nid(20)), "approved", "devin", T, None)
    assert sorted(inp.structural_member_hashes) == sorted([bp, compute_hitl_node_hash_v2(ctx, res)])
    assert inp.sealable_under_v2


def test_a_segment_without_schema_version_is_schema_1_2_0():
    rows = _rows(); rows["AriadneSegment"][0]["sv"] = None
    inp = SI.fetch_seal_inputs_v2(_Session(rows), EP)
    assert next(s for s in inp.segments if s.sequence_index == 0).schema_version == "1.2.0"


def test_terminal_hitl_without_context_json_refuses_version_2_rather_than_inventing_one():
    inp = SI.fetch_seal_inputs_v2(_Session(_rows(hitl_context=None)), EP)
    assert not inp.sealable_under_v2 and "context_json" in inp.refusals[0]


def test_non_uuid_episode_refuses_version_2():
    inp = SI.fetch_seal_inputs_v2(_Session(_rows()), "phase-a-doc-campaign")
    assert not inp.sealable_under_v2 and "not a UUID" in inp.refusals[0]


def test_store_failure_raises():
    class _Broken:
        def run(self, *a, **k): raise RuntimeError("down")
    with pytest.raises(AdapterWriteError):
        SI.fetch_seal_inputs_v2(_Broken(), EP)
