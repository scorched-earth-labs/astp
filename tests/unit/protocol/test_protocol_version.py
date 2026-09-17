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
"""``astp.PROTOCOL_VERSION`` must name the SPEC.md version the package implements.

Compared on MAJOR.MINOR only: by VERSIONING.md a PATCH release is errata with
no change to normative surface, so the package does not need a new constant
for it.
"""

import re
from pathlib import Path

import astp

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC = REPO_ROOT / "SPEC.md"

SEMVER = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:-[a-zA-Z0-9.]+)?")


def _spec_version() -> str:
    match = re.search(r"^\*\*Version:\*\*\s*(\S+)", SPEC.read_text(encoding="utf-8"), re.M)
    assert match, "SPEC.md declares no **Version:**"
    return match.group(1)


def test_protocol_version_is_exported_semver():
    assert SEMVER.fullmatch(astp.PROTOCOL_VERSION), astp.PROTOCOL_VERSION


def test_protocol_version_matches_spec_major_minor():
    spec = SEMVER.fullmatch(_spec_version())
    assert spec, f"unparseable SPEC version: {_spec_version()!r}"
    package = SEMVER.fullmatch(astp.PROTOCOL_VERSION)
    assert package.group(1, 2) == spec.group(1, 2), (
        f"astp.PROTOCOL_VERSION is {astp.PROTOCOL_VERSION} but SPEC.md is at "
        f"{_spec_version()} — MAJOR.MINOR must agree"
    )
