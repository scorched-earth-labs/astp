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
"""VERSIONING.md must not restate the protocol version.

VERSIONING.md declares `SPEC.md` the canonical version source. A version
number restated in VERSIONING.md is a second copy of that fact with nothing
keeping it in step, so the "Current version" section must point at SPEC.md
and name no version of its own.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC = REPO_ROOT / "SPEC.md"
VERSIONING = REPO_ROOT / "VERSIONING.md"

SEMVER = re.compile(r"\b\d+\.\d+\.\d+(?:-[a-zA-Z0-9.]+)?\b")


def _current_version_section() -> str:
    """Text of the level-2 "Current version" section, up to the next level-2 heading."""
    text = VERSIONING.read_text(encoding="utf-8")
    heading = re.search(r"^## Current version[^\n]*$", text, re.M)
    assert heading, "VERSIONING.md has no '## Current version' section"
    following = re.search(r"^## ", text[heading.end():], re.M)
    end = heading.end() + following.start() if following else len(text)
    return text[heading.start():end]


def test_spec_declares_a_version():
    match = re.search(r"^\*\*Version:\*\*\s*(\S+)", SPEC.read_text(encoding="utf-8"), re.M)
    assert match, "SPEC.md must declare a **Version:** field — it is the canonical source"
    assert SEMVER.fullmatch(match.group(1)), f"unparseable SPEC version: {match.group(1)!r}"


def test_current_version_section_states_no_version():
    """The section must point at SPEC.md, never name a version itself."""
    section = _current_version_section()
    # The historical example of the bug is quoted in the prose on purpose; it
    # is the one permitted occurrence, and it is explicitly described as stale.
    quoted_history = "`2.5.0-draft`"
    found = [v for v in SEMVER.findall(section.replace(quoted_history, ""))]
    assert found == [], (
        "VERSIONING.md's 'Current version' section names a version "
        f"({found}). SPEC.md is the canonical source — point at it instead, "
        "or this number will drift the way 2.5.0-draft did."
    )


def test_current_version_section_points_at_spec():
    assert "SPEC.md" in _current_version_section()
