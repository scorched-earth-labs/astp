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
Wire constants that kept the ``ariadne`` prefix when the package became ``astp``.

The import package was renamed; these strings were not, and must not be.
The HKDF ``info`` strings are key-derivation inputs, so changing one changes
every derived key. The coordinator key prefixes and graph labels name data
that already exists in deployed stores. A future naming sweep that "fixes"
any of them is a breaking change, and this file is what should stop it.
"""

from cryptography.hazmat.primitives.hashes import SHA3_256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from astp.adapters.neo4j import writer
from astp.core import wil
from astp.protocol.keys import derive_node_key, derive_seal_key, derive_workspace_key

ROOT = bytes(range(32))
SPINE_ROOT = "a1" * 32


def _hkdf(ikm: bytes, salt: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=SHA3_256(), length=32, salt=salt, info=info).derive(ikm)


class TestHkdfInfoStrings:
    def test_workspace_key_info(self):
        assert derive_workspace_key(ROOT, "ws-1") == _hkdf(
            ROOT, b"ws-1", b"ariadne.workspace.v1"
        )

    def test_node_key_info_carries_node_type(self):
        assert derive_node_key(ROOT, "node-1", "episode") == _hkdf(
            ROOT, b"node-1", b"ariadne.node.v1:episode"
        )

    def test_seal_key_info(self):
        assert derive_seal_key(ROOT, SPINE_ROOT) == _hkdf(
            ROOT, bytes.fromhex(SPINE_ROOT), b"ariadne.seal.v1"
        )


class TestCoordinatorKeyPrefixes:
    def test_key_builders(self):
        assert wil.build_redis_episode_key("e") == "ariadne::episode::e"
        assert wil.build_redis_manifest_key("e") == "ariadne::manifest::e"
        assert wil.build_redis_wil_key("i") == "ariadne::wil::i"
        assert wil.build_redis_merkle_key("l") == "ariadne::merkle::l"

    def test_ttl_policy_is_keyed_on_the_same_prefix(self):
        assert all(k.startswith("ariadne::") for k in wil.REDIS_TTL_POLICY)


class TestGraphLabels:
    def test_schema_statements_keep_the_label_prefix(self):
        statements = [
            s
            for name in dir(writer)
            for s in (getattr(writer, name),)
            if isinstance(s, list) and s and all(isinstance(x, str) for x in s)
            for s in s
            if s.startswith("CREATE ")
        ]
        assert statements, "no schema statements found on the writer module"
        for label in ("AriadneEpisode", "AriadneSegment", "AriadneSignal", "AriadneWILEntry"):
            assert any(f":{label})" in s for s in statements), label
