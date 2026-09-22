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
The HKDF ``info`` strings of both key-derivation versions (SPEC §16.2.1).

A string is a key-derivation input, so changing one changes every key it
derives; a string is never edited, a version is added. Version 1 (the
``ariadne.`` strings) is retained as the definition of every key derived
before 5.2.0 and must reproduce them; version 2 (the ``astp.`` strings) is
current. A naming sweep that "fixes" the retained strings would orphan every
version 1 key, and this file is what should stop it.
"""

from cryptography.hazmat.primitives.hashes import SHA3_256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from astp.protocol.keys import (
    KEY_DERIVATION_VERSION_CURRENT, derivation_info, derive_node_key, derive_seal_key, derive_workspace_key,
)

ROOT = bytes(range(32))
SPINE_ROOT = "a1" * 32


def _hkdf(ikm: bytes, salt: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=SHA3_256(), length=32, salt=salt, info=info).derive(ikm)


class TestVersionTwoIsCurrent:
    def test_current_version(self):
        assert KEY_DERIVATION_VERSION_CURRENT == 2

    def test_workspace_key_info(self):
        assert derive_workspace_key(ROOT, "ws-1") == _hkdf(ROOT, b"ws-1", b"astp.workspace.v2")

    def test_node_key_info_carries_node_type(self):
        assert derive_node_key(ROOT, "node-1", "episode") == _hkdf(ROOT, b"node-1", b"astp.node.v2:episode")

    def test_seal_key_info(self):
        assert derive_seal_key(ROOT, SPINE_ROOT) == _hkdf(ROOT, bytes.fromhex(SPINE_ROOT), b"astp.seal.v2")


class TestVersionOneIsRetained:
    """Every key derived before 5.2.0 must still be reproducible."""

    def test_workspace_key_info(self):
        assert derive_workspace_key(ROOT, "ws-1", derivation_version=1) == _hkdf(
            ROOT, b"ws-1", b"ariadne.workspace.v1"
        )

    def test_node_key_info_carries_node_type(self):
        assert derive_node_key(ROOT, "node-1", "episode", derivation_version=1) == _hkdf(
            ROOT, b"node-1", b"ariadne.node.v1:episode"
        )

    def test_seal_key_info(self):
        assert derive_seal_key(ROOT, SPINE_ROOT, derivation_version=1) == _hkdf(
            ROOT, bytes.fromhex(SPINE_ROOT), b"ariadne.seal.v1"
        )

    def test_the_two_versions_differ_and_nothing_else_is_known(self):
        assert derive_workspace_key(ROOT, "ws-1") != derive_workspace_key(ROOT, "ws-1", derivation_version=1)
        assert derivation_info("node", 1, node_type="agent") == b"ariadne.node.v1:agent"
        assert derivation_info("node", 2, node_type="agent") == b"astp.node.v2:agent"
        import pytest
        with pytest.raises(ValueError, match="unknown key derivation version"):
            derive_workspace_key(ROOT, "ws-1", derivation_version=3)
