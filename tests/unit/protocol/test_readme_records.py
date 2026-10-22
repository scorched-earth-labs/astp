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
"""README.md restates two facts that live elsewhere, and is held to both.

The Status section leads with the protocol version, whose source is the
``**Version:**`` field of SPEC.md. The Amendments table lists each Episode of
Record, whose id, seal date and ``spine_algorithm_version`` are in its exported
proof under docs/proofs/. A ratification or a re-export that changes one side
and not the other would publish a wrong record of the protocol's own history.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
README = (ROOT / "README.md").read_text(encoding="utf-8")
SPEC = (ROOT / "SPEC.md").read_text(encoding="utf-8")


def _find(obj, key):
    if isinstance(obj, dict):
        if key in obj and isinstance(obj[key], (str, int)):
            return obj[key]
        for v in obj.values():
            found = _find(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find(v, key)
            if found is not None:
                return found
    return None


def test_status_leads_with_the_spec_version():
    version = re.search(r"^\*\*Version:\*\* (\S+)", SPEC, re.M).group(1)
    status = README.split("## Status", 1)[1]
    first = re.search(r"^\*\*(\d+\.\d+\.\d+)\.\*\*", status, re.M).group(1)
    assert first == version


def test_every_proof_of_record_has_a_matching_row():
    rows = [l for l in README.splitlines() if l.startswith("| `") and "Episode" not in l]
    proofs = sorted((ROOT / "docs" / "proofs").glob("episode-of-record-*.json"))
    assert proofs
    for proof in proofs:
        record = json.loads(proof.read_text())
        episode_id = _find(record, "episode_id")
        sealed = _find(record, "sealed_at")[:10]
        version = _find(record, "spine_algorithm_version")
        matching = [r for r in rows if f"`{episode_id}`" in r]
        assert len(matching) == 1, f"{proof.name}: expected one README row for {episode_id}"
        assert f"| {sealed} ({version}) |" in matching[0], f"{proof.name}: row says otherwise"
