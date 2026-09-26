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
"""A SHA3-256 digest of SPEC.md, where one is published for its version, is of these bytes.

PATENTS.md §4.1 and PROTOCOL-CONFORMANCE.md §7 identify the text pledged and
conformed to by digest, not by version string. A version need not have a row —
listing one is a deliberate act — but a row for the version SPEC.md declares
must be of SPEC.md exactly as it stands. Any edit to SPEC.md therefore either
bumps its version or updates the digest; it cannot leave a stale one behind.
"""

import hashlib
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC = REPO_ROOT / "SPEC.md"
DIGEST_TABLES = ["PATENTS.md", "PROTOCOL-CONFORMANCE.md"]

ROW = re.compile(r"^\|\s*(\d+\.\d+\.\d+)\s*\|\s*`([0-9a-f]{64})`\s*\|", re.M)


def _spec_version() -> str:
    match = re.search(r"^\*\*Version:\*\*\s*(\S+)", SPEC.read_text(encoding="utf-8"), re.M)
    assert match, "SPEC.md declares no **Version:**"
    return match.group(1)


@pytest.mark.parametrize("document", DIGEST_TABLES)
def test_published_digest_of_current_spec_matches(document):
    rows = dict(ROW.findall((REPO_ROOT / document).read_text(encoding="utf-8")))
    version = _spec_version()
    if version not in rows:
        pytest.skip(f"{document} publishes no digest for SPEC.md {version}")
    actual = hashlib.sha3_256(SPEC.read_bytes()).hexdigest()
    assert rows[version] == actual, (
        f"{document} pins SPEC.md {version} as {rows[version]}, but SPEC.md hashes to {actual}"
    )


@pytest.mark.parametrize("document", DIGEST_TABLES)
def test_no_placeholder_digest(document):
    text = (REPO_ROOT / document).read_text(encoding="utf-8")
    assert "[FILL" not in text and "@SPEC_DIGEST@" not in text
