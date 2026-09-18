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
Conformance: witness commitment, witness validity and the anchor commitment
(SPEC 5.0.0 DRAFT §14). The commitment reference is written from the draft text
with ``hashlib`` alone; signature verification uses ``cryptography``'s Ed25519
directly, importing nothing from ``astp``.
"""

import hashlib
import json
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from astp.protocol.anchor_v2 import compute_anchor_commitment_v2
from astp.protocol.errors import GovernanceViolation
from astp.protocol.witness_v2 import (
    WitnessInvalid, WitnessRecordV2, check_witness_record_v2, compute_witness_commitment_v2,
    count_distinct_valid_witnesses_v2, enforce_witness_threshold_v2, is_valid_witness_v2, sign_witness_record_v2,
)

VECTORS = json.loads((Path(__file__).parents[2] / "vectors" / "5.0.0-draft" / "seal-constructions.json").read_text("utf-8"))
V = VECTORS["witness_and_anchor_v2"]
SK1 = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"))
SK2 = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb"))
SK3 = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7"))


def _u32(n): return n.to_bytes(4, "big")
def _null(): return b"\x00"
def _string(s): d = unicodedata.normalize("NFC", s).encode("utf-8"); return b"\x02" + _u32(len(d)) + d
def _uint(n): return b"\x03" + n.to_bytes(8, "big")
def _uuid(u): return b"\x04" + UUID(u).bytes
def _ts(iso):
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    return b"\x05" + ((dt - datetime(1970, 1, 1, tzinfo=timezone.utc)) // timedelta(milliseconds=1)).to_bytes(8, "big")
def _hash(h): return b"\x06" + bytes.fromhex(h)
def H(pre): return hashlib.sha3_256(pre).hexdigest()


def _load(d: dict) -> WitnessRecordV2:
    return WitnessRecordV2(**{**d, "signature": bytes.fromhex(d["signature"]), "public_key": bytes.fromhex(d["public_key"])})


@pytest.mark.parametrize("i", [0, 1])
def test_witness_commitment_and_signature_match_the_independent_reference(i):
    r = V["witness_records"][i]
    pre = (b"WITNESS_COMMITMENT:v2:" + _string(r["witness_id"]) + _uuid(r["node_id"]) + _string(r["node_type"])
           + _hash(r["root"]) + _uint(r["root_version"]) + _uint(r["sequence_index"]) + _uint(r["logical_clock"])
           + _ts(r["witnessed_at"]) + _string(r["role"])
           + (_null() if r["role_detail"] is None else _string(r["role_detail"])))
    assert H(pre) == r["commitment_hash"]
    assert hashlib.sha3_256(bytes.fromhex(r["public_key"])).hexdigest() == r["public_key_fingerprint"]
    # the signature is over the raw 32 bytes of the commitment, under the RFC 8032 test key
    Ed25519PublicKey.from_public_bytes(bytes.fromhex(r["public_key"])).verify(
        bytes.fromhex(r["signature"]), bytes.fromhex(r["commitment_hash"]))
    assert r["public_key"] == ["d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
                               "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c"][i]
    # and the library agrees
    rec = _load(r)
    assert compute_witness_commitment_v2(**rec.commitment_fields()) == r["commitment_hash"]
    check_witness_record_v2(rec, node_author="author")


def test_every_g12_condition_is_checked():
    w1 = _load(V["witness_records"][0])
    with pytest.raises(WitnessInvalid, match="author"):
        check_witness_record_v2(w1, node_author="witness-1")
    with pytest.raises(WitnessInvalid, match="does not recompute"):
        check_witness_record_v2(w1.model_copy(update={"witness_id": "someone-else"}), "author")   # copied under a new name
    with pytest.raises(WitnessInvalid, match="does not recompute"):
        check_witness_record_v2(w1.model_copy(update={"witnessed_at": w1.witnessed_at + timedelta(seconds=1)}), "author")
    with pytest.raises(WitnessInvalid, match="signature does not verify"):
        check_witness_record_v2(w1.model_copy(update={"signature": b"\x00" * 64}), "author")
    with pytest.raises(WitnessInvalid, match="signature does not verify"):
        check_witness_record_v2(w1.model_copy(update={"signature": b""}), "author")               # 4.x let this count
    other = SK2.public_key().public_bytes_raw()
    with pytest.raises(WitnessInvalid, match="fingerprint"):
        check_witness_record_v2(w1.model_copy(update={"public_key": other}), "author")
    with pytest.raises(WitnessInvalid, match="signature does not verify"):
        check_witness_record_v2(w1.model_copy(update={"public_key": other, "public_key_fingerprint": hashlib.sha3_256(other).hexdigest()}), "author")
    with pytest.raises(WitnessInvalid, match="scheme"):
        check_witness_record_v2(w1.model_copy(update={"signature_scheme": "none"}), "author")


def test_threshold_counts_distinct_names_and_distinct_keys():
    f = dict(node_id=UUID(V["witness_records"][0]["node_id"]), node_type="episode", root=V["witness_records"][0]["root"],
             root_version=2, sequence_index=7, logical_clock=9,
             witnessed_at=datetime(2026, 1, 1, tzinfo=timezone.utc), role="SEAL_WITNESS")
    a1 = sign_witness_record_v2(SK1, witness_id="A", **f)
    a2 = sign_witness_record_v2(SK2, witness_id="A", **f)
    b1 = sign_witness_record_v2(SK1, witness_id="B", **f)
    c3 = sign_witness_record_v2(SK3, witness_id="C", **f)
    assert count_distinct_valid_witnesses_v2([a1, a1], "author") == 1          # same record twice
    assert count_distinct_valid_witnesses_v2([a1, a2], "author") == 1          # one name, two keys
    assert count_distinct_valid_witnesses_v2([a1, b1], "author") == 1          # one key, two names
    assert count_distinct_valid_witnesses_v2([a1, a2, b1], "author") == 2      # A/k2 + B/k1 — a greedy pass would say 1
    assert count_distinct_valid_witnesses_v2([a1, b1, c3], "author") == 2
    assert count_distinct_valid_witnesses_v2([a1, c3], "C") == 1               # C is the author
    enforce_witness_threshold_v2([a1, a2, b1], "author", 2)
    with pytest.raises(GovernanceViolation):
        enforce_witness_threshold_v2([a1, a2, b1], "author", 3)
    unsigned = a1.model_copy(update={"signature": b""})
    with pytest.raises(GovernanceViolation):
        enforce_witness_threshold_v2([unsigned, unsigned.model_copy(update={"witness_id": "Z"})], "author", 1)


def test_anchor_commitment_matches_the_independent_reference():
    a = V["anchor_inputs"]
    pre = (b"ANCHOR_COMMITMENT:v2:" + _uuid(a["node_id"]) + _string(a["node_type"]) + _string(a["workspace_id"])
           + _hash(a["root"]) + _uint(a["root_version"]) + _uint(a["crystallization_sequence"]) + _uint(a["logical_clock"])
           + _ts(a["anchored_at"]))
    assert H(pre) == V["anchor_commitment_v2"]
    assert compute_anchor_commitment_v2(**{**a, "node_id": UUID(a["node_id"]),
                                           "anchored_at": datetime.fromisoformat(a["anchored_at"])}) == V["anchor_commitment_v2"]
    # a different workspace, root or root version is a different anchor
    for k, v in (("workspace_id", "ws-2"), ("root", "00" * 32), ("root_version", 1)):
        assert compute_anchor_commitment_v2(**{**a, k: v, "node_id": UUID(a["node_id"]),
                                               "anchored_at": datetime.fromisoformat(a["anchored_at"])}) != V["anchor_commitment_v2"]


def test_vector_file_is_current():
    import subprocess, sys
    gen = Path(__file__).parents[2] / "vectors" / "5.0.0-draft" / "generate.py"
    assert subprocess.run([sys.executable, str(gen), "--check"]).returncode == 0
