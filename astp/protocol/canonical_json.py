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
ASTP — Canonical JSON (DRAFT for SPEC 5.0.0; not yet ratified)

Where a hash preimage contains a JSON document — an audit record's deltas, a
Layer 3 node's state — the bytes hashed are the document's canonical form:
RFC 8785 (JSON Canonicalization Scheme), with every string (object keys and
values alike) first normalized to Unicode NFC. Concretely:

* objects: members sorted by key, keys compared as UTF-16 code units (RFC 8785
  section 3.2.3); no whitespace anywhere
* strings: UTF-8; only the quotation mark, the backslash and control characters
  below U+0020 are escaped, the latter as the two-character escapes for
  backspace, form feed, newline, carriage return and tab, or else as a
  lowercase ``\\u00xx`` escape
* numbers: integers as digits; other numbers in the shortest form that round
  trips, formatted as ECMAScript's Number::toString (RFC 8785 section
  3.2.2.3); negative zero is ``0``; NaN and infinities are refused
* literals: ``true``, ``false``, ``null``

The canonical form is what is hashed **and what is stored**: a reader that
hashes what it reads gets the writer's digest.
"""

import json
import math
import unicodedata
from typing import Any


def _nfc(obj: Any) -> Any:
    if isinstance(obj, str):
        return unicodedata.normalize("NFC", obj)
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            nk = _nfc(k)
            if nk in out:
                raise ValueError(f"object keys are not distinct after NFC normalization: {k!r}")
            out[nk] = _nfc(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [_nfc(v) for v in obj]
    return obj


def es6_number(x: float) -> str:
    """ECMAScript Number::toString for a finite float. Python's ``repr`` already
    yields the shortest digit string that round-trips; only the placement of the
    decimal point and the exponent syntax differ, and this fixes those."""
    if x == 0:
        return "0"
    r = repr(float(x))
    sign = "-" if r.startswith("-") else ""
    r = r.lstrip("-")
    if "e" in r:
        mant, exp_s = r.split("e")
        exp = int(exp_s)
    else:
        mant, exp = r, 0
    ip, _, fp = mant.partition(".")
    # value = 0.<digits> * 10**n, where digits has no leading zeros
    if ip.strip("0"):
        n = len(ip.lstrip("0")) + exp
        digits = ip.lstrip("0") + fp
    else:
        stripped = fp.lstrip("0")
        n = exp - (len(fp) - len(stripped))
        digits = stripped
    digits = digits.rstrip("0") or "0"
    k = len(digits)
    if k <= n <= 21:
        s = digits + "0" * (n - k)
    elif 0 < n <= 21:
        s = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        s = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        s = digits[0] + ("." + digits[1:] if k > 1 else "") + "e" + ("+" if e >= 0 else "-") + str(abs(e))
    return sign + s


def _encode(obj: Any, out: list) -> None:
    if obj is None:
        out.append("null")
    elif obj is True:
        out.append("true")
    elif obj is False:
        out.append("false")
    elif isinstance(obj, int):
        out.append(str(obj))
    elif isinstance(obj, float):
        if not math.isfinite(obj):
            raise ValueError("canonical JSON cannot represent NaN or infinity")
        out.append(es6_number(obj))
    elif isinstance(obj, str):
        out.append(json.dumps(obj, ensure_ascii=False))
    elif isinstance(obj, (list, tuple)):
        out.append("[")
        for i, v in enumerate(obj):
            if i:
                out.append(",")
            _encode(v, out)
        out.append("]")
    elif isinstance(obj, dict):
        keys = list(obj)
        if any(not isinstance(k, str) for k in keys):
            raise TypeError("canonical JSON object keys must be strings")
        out.append("{")
        for i, k in enumerate(sorted(keys, key=lambda s: s.encode("utf-16-be"))):
            if i:
                out.append(",")
            out.append(json.dumps(k, ensure_ascii=False))
            out.append(":")
            _encode(obj[k], out)
        out.append("}")
    else:
        raise TypeError(f"canonical JSON cannot represent {type(obj).__name__}")


def canonical_json(obj: Any) -> bytes:
    """The RFC 8785 canonical form of ``obj``, after NFC normalization, as UTF-8."""
    out: list = []
    _encode(_nfc(obj), out)
    return "".join(out).encode("utf-8")
