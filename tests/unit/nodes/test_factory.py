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
"""Unit tests for the generic cognitive node factory (astp.nodes.factory).

Covers the one governed creation path shared by every node type: governance
(node-type registration), payload validation, deterministic content hashing,
the position-binding leaf hash, episode delegation, and the adopter-facing
register_node_type extensibility hook.
"""
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from astp.core.schema import sha3_256
from astp.nodes import create_node, register_node_type
from astp.nodes.episode import EpisodePayload, create_episode_node
from astp.protocol.errors import GovernanceViolation
from astp.protocol.node import CognitiveNode
from astp.protocol.registry import REGISTRY


def _episode_payload():
    return EpisodePayload(title="T", context_note="C", participants=["agent-1"])


def test_create_node_builds_complete_node():
    n = create_node("episode", agent_id="agent-1", sequence_index=0, payload=_episode_payload())
    assert isinstance(n, CognitiveNode)
    assert n.node_type == "episode"
    assert n.authored_by == "agent-1"
    assert n.sequence_index == 0 and n.tree_leaf_index == 0  # equal until rebalance
    assert n.content_hash and n.leaf_hash  # both computed by the factory


def test_content_hash_deterministic_leaf_hash_unique():
    a = create_node("episode", agent_id="x", sequence_index=0, payload=_episode_payload())
    b = create_node("episode", agent_id="x", sequence_index=0, payload=_episode_payload())
    assert a.content_hash == b.content_hash   # same payload → same content hash
    assert a.leaf_hash != b.leaf_hash         # distinct node_id → distinct identity


def test_episode_convenience_matches_generic_path():
    """create_episode_node now delegates to create_node — identical hashing."""
    ep = create_episode_node("agent-1", 0, title="T", context_note="C")
    gen = create_node("episode", agent_id="agent-1", sequence_index=0, payload=_episode_payload())
    assert ep.node_type == gen.node_type == "episode"
    assert ep.content_hash == gen.content_hash


def test_unregistered_type_rejected_by_governance():
    with pytest.raises(GovernanceViolation):
        create_node(
            "definitely_not_registered_xyz",
            agent_id="a", sequence_index=1, payload=_episode_payload(),
        )


@pytest.fixture
def custom_type_id():
    """A type id unique to this test run, removed from the global registry afterwards.

    REGISTRY is a process-wide singleton with no public unregister, so the
    test must not depend on (or leave behind) a fixed name.
    """
    type_id = f"unit_test_custom_type_{uuid4().hex}"
    yield type_id
    REGISTRY._registry.pop(type_id, None)


def test_register_node_type_enables_creation(custom_type_id):
    assert not REGISTRY.is_registered(custom_type_id)
    defn = register_node_type(custom_type_id, "Unit Test Custom")
    assert defn.type_id == custom_type_id
    assert REGISTRY.is_registered(custom_type_id)
    n = create_node(custom_type_id, agent_id="a", sequence_index=2, payload=_episode_payload())
    assert n.node_type == custom_type_id and n.leaf_hash


def test_importing_astp_nodes_registers_builtin_types():
    """``import astp.nodes`` alone must make every built-in node type creatable."""
    code = (
        "import astp.nodes\n"
        "from astp.protocol.registry import REGISTRY\n"
        "print(sorted(REGISTRY.list_types()))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True,
        cwd=Path(__file__).resolve().parents[3],
    )
    assert out.stdout.strip() == "['episode', 'segment']"


def test_payload_validate_is_enforced():
    bad = EpisodePayload(title="T", episode_mode="not_a_valid_mode")
    with pytest.raises(ValueError):
        create_node("episode", agent_id="a", sequence_index=3, payload=bad)


def test_nodepayload_abc_compute_content_hash_default():
    """The ABC default equals sha3_256(to_content_hash_input()) — hash unchanged."""
    p = _episode_payload()
    assert p.compute_content_hash() == sha3_256(p.to_content_hash_input())
