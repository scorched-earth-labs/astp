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
Conformance: §19 side-channel content hashes and the Episode link
(SPEC 5.0.0 DRAFT §13). Each vector is checked against the library and
against a reference written from the draft text with ``hashlib`` and
``struct`` alone, importing nothing from ``astp``.
"""

import hashlib
import json
import struct
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from astp.core import content_hash_v2 as C
from astp.protocol.encoding import FLOAT, encode_field

VECTORS = json.loads((Path(__file__).parents[2] / "vectors" / "5.0.0-draft" / "seal-constructions.json").read_text("utf-8"))
V = VECTORS["content_hashes_v2"]
EP = UUID(VECTORS["episode_id"])
EP2 = UUID(V["target_episode_id"])
T = datetime(2026, 1, 1, 0, 0, 0, 123000, tzinfo=timezone.utc)
C_ = [s["content_hash"] for s in VECTORS["segments"]]


def nid(i: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{i:012x}")


# ── reference written from the draft text, no astp imports ───────────────────────

def _u32(n): return n.to_bytes(4, "big")
def _null(): return b"\x00"
def _string(s): d = unicodedata.normalize("NFC", s).encode("utf-8"); return b"\x02" + _u32(len(d)) + d
def _uuid(u): return b"\x04" + u.bytes
def _ts(dt): return b"\x05" + ((dt.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)) // timedelta(milliseconds=1)).to_bytes(8, "big")
def _hash(h): return b"\x06" + bytes.fromhex(h)
def _list(items, enc): return b"\x07" + _u32(len(items)) + b"".join(enc(i) for i in items)
def _bool(b): return b"\x08" + (b"\x01" if b else b"\x00")
def _float(x): return b"\x09" + struct.pack(">d", 0.0 if x == 0 else float(x))
def _opt(v, enc): return _null() if v is None else enc(v)
def H(pre: bytes) -> str: return hashlib.sha3_256(pre).hexdigest()


def test_float_encoding_is_ieee754_big_endian_and_negative_zero_is_zero():
    fe = VECTORS["field_encoding"]
    assert fe["FLOAT_0.75"] == "09" + struct.pack(">d", 0.75).hex()
    assert fe["FLOAT_negative_zero_is_positive_zero"][0] == fe["FLOAT_negative_zero_is_positive_zero"][1] == "09" + "00" * 8
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            encode_field(FLOAT, bad)
    with pytest.raises(TypeError):
        encode_field(FLOAT, True)
    # subnormals are admitted bit-faithfully; -0 -> +0 is the only normalization
    assert encode_field(FLOAT, 5e-324) == b"\x09" + struct.pack(">d", 5e-324)
    assert encode_field(FLOAT, -5e-324) == b"\x09" + struct.pack(">d", -5e-324)


def test_aside():
    lib = C.compute_aside_hash_v2(nid(40), EP, nid(2), C_[2], "devin", "agent-α", T)
    ref = H(b"ASIDE:v2:" + _uuid(nid(40)) + _uuid(EP) + _uuid(nid(2)) + _hash(C_[2]) + _string("devin")
            + _string("agent-α") + _ts(T))
    assert lib == ref == V["aside_v2"]


def test_aside_terminus():
    lib = C.compute_aside_terminus_hash_v2(nid(41), nid(40), EP, V["aside_v2"], [C_[3], C_[4]], "done",
                                           False, [nid(5)], "CLOSED", T + timedelta(minutes=5))
    ref = H(b"ASIDE_TERMINUS:v2:" + _uuid(nid(41)) + _uuid(nid(40)) + _uuid(EP) + _hash(V["aside_v2"])
            + _list([C_[3], C_[4]], _hash) + _string("done") + _bool(False) + _list([nid(5)], _uuid)
            + _string("CLOSED") + _ts(T + timedelta(minutes=5)))
    assert lib == ref == V["aside_terminus_v2"]
    # the produced content is bound in order; the scan outcome is bound
    assert C.compute_aside_terminus_hash_v2(nid(41), nid(40), EP, V["aside_v2"], [C_[4], C_[3]], "done",
                                            False, [nid(5)], "CLOSED", T + timedelta(minutes=5)) != lib
    assert C.compute_aside_terminus_hash_v2(nid(41), nid(40), EP, V["aside_v2"], [C_[3], C_[4]], "done",
                                            True, [], "CLOSED", T + timedelta(minutes=5)) != lib


def test_soliloquy_and_deliberation_chain_and_conclusion():
    sol = C.compute_soliloquy_hash_v2(nid(42), EP, nid(2), C_[2], "agent-α", T)
    assert sol == H(b"SOLILOQUY:v2:" + _uuid(nid(42)) + _uuid(EP) + _uuid(nid(2)) + _hash(C_[2]) + _string("agent-α") + _ts(T))
    assert sol == V["soliloquy_v2"]

    chain = C.compute_deliberation_chain_hash_v2(nid(42), [C_[3], C_[4], C_[5]])
    assert chain == H(b"DELIBERATION_CHAIN:v2:" + _uuid(nid(42)) + _list([C_[3], C_[4], C_[5]], _hash)) == V["deliberation_chain_v2"]
    assert C.compute_deliberation_chain_hash_v2(nid(42), []) == H(b"DELIBERATION_CHAIN:v2:" + _uuid(nid(42)) + _list([], _hash)) == V["deliberation_chain_v2_empty"]
    assert C.compute_deliberation_chain_hash_v2(nid(42), [C_[4], C_[3], C_[5]]) != chain   # order is meaning

    concl = C.compute_soliloquy_conclusion_hash_v2(nid(43), nid(42), EP, chain, "take the second reading",
                                                   nid(6), "ABSORBED", T + timedelta(minutes=5))
    ref = H(b"SOLILOQUY_CONCLUSION:v2:" + _uuid(nid(43)) + _uuid(nid(42)) + _uuid(EP) + _hash(chain)
            + _string("take the second reading") + _uuid(nid(6)) + _string("ABSORBED") + _ts(T + timedelta(minutes=5)))
    assert concl == ref == V["soliloquy_conclusion_v2"]


def test_link_signals_and_episode_link():
    sig1 = C.compute_link_signal_hash_v2("SEMANTIC_SIMILARITY", 0.6, 0.91, T)
    sig2 = C.compute_link_signal_hash_v2("PARTICIPANT_OVERLAP", 0.4, 0.5, T)
    assert sig1 == H(b"LINK_SIGNAL:v2:" + _string("SEMANTIC_SIMILARITY") + _float(0.6) + _float(0.91) + _ts(T))
    assert [sig1, sig2] == V["link_signal_v2"]

    root = V["source_episode_root_used"]
    inferred = C.compute_episode_link_hash_v2(nid(44), EP, EP2, root, None, T, "RELATES_TO", 0.736, True,
                                              [sig1, sig2], 0.7, True, "1.0.0", None)
    ref = H(b"EPISODE_LINK:v2:" + _uuid(nid(44)) + _uuid(EP) + _uuid(EP2) + _hash(root) + _null() + _ts(T)
            + _string("RELATES_TO") + _float(0.736) + _bool(True) + _list([sig1, sig2], _hash) + _float(0.7)
            + _bool(True) + _string("1.0.0") + _null())
    assert inferred == ref == V["episode_link_v2_inferred_source_sealed"]

    asserted = C.compute_episode_link_hash_v2(nid(45), EP, EP2, None, None, T, "CONTINUES_FROM", 1.0, False,
                                              [], None, False, None, None)
    ref = H(b"EPISODE_LINK:v2:" + _uuid(nid(45)) + _uuid(EP) + _uuid(EP2) + _null() + _null() + _ts(T)
            + _string("CONTINUES_FROM") + _float(1.0) + _bool(False) + _list([], _hash) + _null()
            + _bool(False) + _null() + _null())
    assert asserted == ref == V["episode_link_v2_asserted_neither_sealed"]


def test_episode_link_binds_the_ends_and_the_claim_but_not_lifecycle():
    base = dict(link_id=nid(44), source_episode=EP, target_episode=EP2, source_episode_root=None,
                target_episode_root=None, created_at=T, link_type="RELATES_TO", link_strength=0.5, is_inferred=False,
                inference_signal_hashes=[], inference_threshold=None, retroactive=False,
                source_version=None, target_version=None)
    h = C.compute_episode_link_hash_v2(**base)
    # the direction of the relationship is bound
    assert C.compute_episode_link_hash_v2(**{**base, "source_episode": EP2, "target_episode": EP}) != h
    # binding the source's root is a different claim from leaving it unbound
    assert C.compute_episode_link_hash_v2(**{**base, "source_episode_root": V["source_episode_root_used"]}) != h
    # strength is a real number, bound exactly
    assert C.compute_episode_link_hash_v2(**{**base, "link_strength": 0.5000000000000001}) != h
    # there is no parameter for health, quarantine or the asserting agent: lifecycle and provenance are the audit chain's
    import inspect
    params = set(inspect.signature(C.compute_episode_link_hash_v2).parameters)
    assert not params & {"health_state", "health_checked_at", "quarantine_reason", "quarantined_at", "created_by"}


def test_vector_file_is_current():
    import subprocess, sys
    gen = Path(__file__).parents[2] / "vectors" / "5.0.0-draft" / "generate.py"
    assert subprocess.run([sys.executable, str(gen), "--check"]).returncode == 0
