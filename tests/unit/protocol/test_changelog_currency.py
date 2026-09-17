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
"""CHANGELOG.md must carry an entry for the current SPEC version.

VERSIONING.md's bump procedure ends with "Update CHANGELOG.md with the version
entry". SPEC.md's ``**Version:**`` and the CHANGELOG headings are the same fact
in two places; these tests compare them so a release cannot ship without its
entry.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC = ROOT / "SPEC.md"
CHANGELOG = ROOT / "CHANGELOG.md"


def _spec_version() -> str:
    match = re.search(r"^\*\*Version:\*\*\s*(\S+)", SPEC.read_text(encoding="utf-8"), re.M)
    assert match, "SPEC.md declares no **Version:**"
    return match.group(1)


def _changelog_versions() -> set[str]:
    return set(re.findall(r"^## \[([0-9][^\]]*)\]", CHANGELOG.read_text(encoding="utf-8"), re.M))


def test_current_spec_version_has_a_changelog_entry():
    version = _spec_version()
    versions = _changelog_versions()
    assert version in versions, (
        f"SPEC.md is at {version} but CHANGELOG.md has no [{version}] entry "
        f"(latest entries: {sorted(versions, reverse=True)[:3]})"
    )


def test_changelog_has_no_gaps_in_the_current_minor_line():
    """Every PATCH release of the current MAJOR.MINOR line, up to SPEC's, has an entry."""
    version = _spec_version()
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:-.+)?", version)
    assert match, f"unparseable SPEC version: {version!r}"
    major, minor, patch = (int(part) for part in match.groups())
    versions = _changelog_versions()
    for earlier_patch in range(patch):
        required = f"{major}.{minor}.{earlier_patch}"
        assert required in versions, f"CHANGELOG.md is missing [{required}]"
