"""VERSIONING.md must not restate the protocol version.

VERSIONING.md declares `SPEC.md` the canonical version source and then, for
several releases, restated a version of its own — `2.5.0-draft`, long after
SPEC.md had moved to the 3.x line. Nothing could notice: the number existed in
two places with no relationship between them.

Same failure shape as the WIL operation register (see test_wil_operations.py):
a fact duplicated into a second location drifts, and drift is invisible until
something downstream trusts the wrong copy. The fix is to remove the duplicate,
and this test keeps it removed.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC = REPO_ROOT / "SPEC.md"
VERSIONING = REPO_ROOT / "VERSIONING.md"

SEMVER = re.compile(r"\b\d+\.\d+\.\d+(?:-[a-zA-Z0-9.]+)?\b")


def _current_version_section() -> str:
    text = VERSIONING.read_text(encoding="utf-8")
    start = text.index("## Current version")
    end = text.index("## ", start + 1)
    return text[start:end]


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
