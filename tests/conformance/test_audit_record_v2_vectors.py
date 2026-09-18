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
Conformance: canonical JSON and the version 2 audit record (SPEC 5.0.0 DRAFT).

Every vector is checked twice — against the library, and against a reference
written from the draft text that imports nothing from ``astp``: ``hashlib``,
``json``, ``unicodedata`` and the standard library only. The canonical-JSON
reference is RFC 8785's own appendix example, whose expected output is the
RFC's, byte for byte.
"""

import hashlib
import json
import math
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from astp.protocol.audit_v2 import (
    AuditChainError, AuditRecordV2, compute_audit_record_hash_v2, make_audit_record, verify_audit_chain_v2,
)
from astp.protocol.canonical_json import canonical_json, es6_number

VECTORS = json.loads((Path(__file__).parents[2] / "vectors" / "5.0.0-draft" / "seal-constructions.json").read_text("utf-8"))
CJ = VECTORS["canonical_json"]
AR = VECTORS["audit_records_v2"]


# ── reference written from the draft text, no astp imports ───────────────────────

def _u32(n): return n.to_bytes(4, "big")
def _null(): return b"\x00"
def _bytes(b): return b"\x01" + _u32(len(b)) + b
def _string(s): d = unicodedata.normalize("NFC", s).encode("utf-8"); return b"\x02" + _u32(len(d)) + d
def _uint(n): return b"\x03" + n.to_bytes(8, "big")
def _uuid(u): return b"\x04" + UUID(u).bytes
def _timestamp(iso):
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    ms = (dt - datetime(1970, 1, 1, tzinfo=timezone.utc)) // __import__("datetime").timedelta(milliseconds=1)
    return b"\x05" + ms.to_bytes(8, "big")
def _hash(h): return b"\x06" + bytes.fromhex(h)
def _list_str(items): return b"\x07" + _u32(len(items)) + b"".join(_string(s) for s in items)
def _bool(b): return b"\x08" + (b"\x01" if b else b"\x00")


def ref_record_hash(r: dict) -> str:
    """The preimage as the draft lists it, field by field."""
    pre = (b"AUDIT_RECORD:v2:"
           + _uuid(r["audit_id"])
           + _string(r["chain_key"])
           + _uint(r["delta_sequence"])
           + _string(r["delta_type"])
           + _string(r["agent_id"])
           + _string(r["session_id"])
           + (_null() if r["human_actor"] is None else _string(r["human_actor"]))
           + _timestamp(r["wall_clock_time"])
           + _uint(r["episode_time"])
           + _bytes(r["forward_delta"].encode("utf-8"))
           + _bytes(r["reverse_delta"].encode("utf-8"))
           + _list_str(r["affected_nodes"])
           + _string(r["trigger_context"])
           + (_null() if r["explicit_reason"] is None else _string(r["explicit_reason"]))
           + _string(r["caught_by"])
           + _bool(r["detection_window_open"])
           + (_null() if r["prior_audit_hash"] is None else _hash(r["prior_audit_hash"])))
    return hashlib.sha3_256(pre).hexdigest()


# ── canonical JSON ───────────────────────────────────────────────────────────────

def test_rfc8785_appendix_example_byte_for_byte():
    # RFC 8785 §3.2.3 / Appendix: the expected serialization from the RFC itself.
    euro, si, nl, bs, q = chr(0x20AC), chr(0x0F), chr(0x0A), chr(0x5C), chr(0x22)
    doc = {"numbers": [333333333.33333329, 1E30, 4.50, 2e-3, 0.000000000000000000000000001],
           "string": euro + "$" + si + nl + "A'B" + q + bs + bs + "/",
           "literals": [None, True, False]}
    want = ('{"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],"string":"'
            + euro + "$" + bs + "u000f" + bs + "nA'B" + bs + q + bs + bs + bs + bs + '/"}').encode("utf-8")
    assert canonical_json(doc) == want
    assert CJ["rfc8785_appendix_example"]["canonical"].encode("utf-8") == want
    assert CJ["rfc8785_appendix_example"]["sha3_256"] == hashlib.sha3_256(want).hexdigest()


@pytest.mark.parametrize("x,want", [
    (1.0, "1"), (0.75, "0.75"), (1e21, "1e+21"), (1e-7, "1e-7"), (0.000001, "0.000001"),
    (-0.0, "0"), (5e-324, "5e-324"), (1.7976931348623157e308, "1.7976931348623157e+308"),
    (100.0, "100"), (1e20, "100000000000000000000"), (-1.5e-10, "-1.5e-10"),
    (9007199254740993.0, "9007199254740992"), (333333333.33333329, "333333333.3333333"),
])
def test_numbers_are_es6_number_tostring(x, want):
    assert es6_number(x) == want


def test_nan_and_infinity_are_refused():
    for x in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError):
            canonical_json({"x": x})


def test_keys_sort_by_utf16_code_units_not_code_points():
    # U+1F600 is a surrogate pair (D83D DE00) in UTF-16, so it sorts before U+FFFF.
    got = canonical_json({chr(0x1F600): 1, chr(0xFFFF): 2, "a": 3}).decode("utf-8")
    assert got == '{"a":3,"' + chr(0x1F600) + '":1,"' + chr(0xFFFF) + '":2}'
    assert CJ["nested_keys_sorted_by_utf16_code_units"]["canonical"] == '{"":5,"B":4,"a":3,"' + chr(0x1F600) + '":1,"' + chr(0xFFFF) + '":2}'


def test_strings_and_keys_are_nfc_and_colliding_keys_are_refused():
    composed = chr(0xE9)
    decomposed = "e" + chr(0x301)
    assert canonical_json({decomposed: decomposed}) == canonical_json({composed: composed})
    assert CJ["nfc_decomposed_key_and_value"]["canonical"] == '{"' + composed + '":"' + composed + '"}'
    with pytest.raises(ValueError):
        canonical_json({decomposed: 1, composed: 2})


@pytest.mark.parametrize("name", list(CJ))
def test_canonical_json_vectors(name):
    v = CJ[name]
    assert hashlib.sha3_256(v["canonical"].encode("utf-8")).hexdigest() == v["sha3_256"]
    # canonical form is a fixed point
    assert canonical_json(json.loads(v["canonical"])) == v["canonical"].encode("utf-8")


# ── audit record ─────────────────────────────────────────────────────────────────

def _records():
    return [AuditRecordV2(**r) for r in AR["chain"]]


@pytest.mark.parametrize("i", range(3))
def test_chain_record_hashes_match_the_independent_reference(i):
    r = AR["chain"][i]
    assert ref_record_hash(r) == r["record_hash"]
    assert compute_audit_record_hash_v2(**{k: (UUID(v) if k == "audit_id" else
                                                datetime.fromisoformat(v.replace("Z", "+00:00")) if k == "wall_clock_time" else v)
                                            for k, v in r.items() if k != "record_hash"}) == r["record_hash"]


def test_genesis_minimal_record():
    g = AR["genesis_minimal"]
    assert g["prior_audit_hash"] is None and g["delta_sequence"] == 1
    assert g["human_actor"] is None and g["explicit_reason"] is None and g["affected_nodes"] == []
    assert g["forward_delta"] == "{}" and g["reverse_delta"] == "{}"
    assert ref_record_hash(g) == g["record_hash"]
    verify_audit_chain_v2([AuditRecordV2(**g)])


def test_chain_verifies_and_is_linked():
    recs = _records()
    verify_audit_chain_v2(recs)
    assert recs[0].prior_audit_hash is None
    assert recs[1].prior_audit_hash == recs[0].record_hash
    assert recs[2].prior_audit_hash == recs[1].record_hash
    assert [r.delta_sequence for r in recs] == [1, 2, 3]
    verify_audit_chain_v2([])


def test_stored_delta_is_canonical_and_the_timestamp_is_at_millisecond_precision():
    r1, r2, _ = AR["chain"]
    assert r1["forward_delta"] == '{"branch_id":"00000000-0000-4000-8000-000000000014","depth":2.5,"label":"' + chr(0xE9) + 'tude"}'
    assert r2["wall_clock_time"].endswith("02.122000Z")   # built from …02.122999 — truncated, not rounded
    with pytest.raises(ValueError):
        AuditRecordV2(**{**r1, "forward_delta": '{"label":"' + chr(0xE9) + 'tude","branch_id":"00000000-0000-4000-8000-000000000014","depth":2.5}'})
    with pytest.raises(ValueError):
        make_audit_record(chain_key="k", delta_sequence=1, delta_type="X", agent_id="a", session_id="s",
                          trigger_context="t", forward_delta={}, reverse_delta={}, prior_audit_hash=None,
                          wall_clock_time=datetime(2026, 1, 1))   # naive


@pytest.mark.parametrize("field,value", [
    ("agent_id", "mallory"), ("delta_type", "BRANCH_CREATED"), ("human_actor", "devin"),
    ("episode_time", 9), ("forward_delta", '{"branch_id":"00000000-0000-4000-8000-000000000015"}'),
    ("affected_nodes", []), ("trigger_context", "human_explicit"), ("explicit_reason", "because"),
    ("caught_by", "HUMAN"), ("detection_window_open", True), ("chain_key", "other"),
    ("wall_clock_time", "2026-01-01T00:00:02.123000Z"), ("audit_id", "00000000-0000-4000-8000-000000000099"),
])
def test_every_field_is_bound(field, value):
    recs = _records()
    tampered = AuditRecordV2(**{**AR["chain"][1], field: value})
    recs[1] = tampered
    with pytest.raises(AuditChainError, match="record 1"):
        verify_audit_chain_v2(recs)


def test_deletion_insertion_and_reorder_are_detected():
    recs = _records()
    with pytest.raises(AuditChainError, match="record 1: delta_sequence 3"):
        verify_audit_chain_v2([recs[0], recs[2]])
    with pytest.raises(AuditChainError, match="record 0"):
        verify_audit_chain_v2([recs[1], recs[0], recs[2]])
    forged = make_audit_record(chain_key=recs[0].chain_key, delta_sequence=2, delta_type="X", agent_id="a", session_id="s",
                               trigger_context="t", forward_delta={}, reverse_delta={}, prior_audit_hash=recs[0].record_hash,
                               wall_clock_time=datetime(2026, 1, 1, tzinfo=timezone.utc))
    # a record inserted mid-chain: the next genuine record no longer links to it
    with pytest.raises(AuditChainError, match="record 2: prior_audit_hash"):
        verify_audit_chain_v2([recs[0], forged, recs[1].model_copy(update={"delta_sequence": 3})])


def test_genesis_is_null_not_text():
    r0 = AR["chain"][0]
    assert r0["prior_audit_hash"] is None
    with pytest.raises(ValueError):
        AuditRecordV2(**{**r0, "prior_audit_hash": "GENESIS"})


def test_null_and_empty_string_do_not_collide():
    base = dict(chain_key="k", delta_sequence=1, delta_type="X", agent_id="a", session_id="s", trigger_context="t",
                forward_delta={}, reverse_delta={}, prior_audit_hash=None,
                wall_clock_time=datetime(2026, 1, 1, tzinfo=timezone.utc), audit_id=UUID(int=1))
    assert make_audit_record(**base, human_actor=None).record_hash != make_audit_record(**base, human_actor="").record_hash


def test_vector_file_is_current():
    import subprocess, sys
    gen = Path(__file__).parents[2] / "vectors" / "5.0.0-draft" / "generate.py"
    assert subprocess.run([sys.executable, str(gen), "--check"]).returncode == 0
