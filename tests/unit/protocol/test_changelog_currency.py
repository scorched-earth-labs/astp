"""CHANGELOG.md must carry an entry for the current SPEC version.

VERSIONING.md's bump procedure ends with "Update CHANGELOG.md with the version
entry". Nothing enforced it, and three consecutive releases — 3.4.0, 3.5.0 and
3.5.1 — shipped without one. The changelog's latest entry was 3.3.0 while
SPEC.md was at 3.5.1.

Same failure as every other one this week: a documented step with no mechanism,
and a fact that lives in two places with nothing comparing them.
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
    """The three releases that slipped are present, so a gap is visible."""
    versions = _changelog_versions()
    for required in ("3.4.0", "3.5.0", "3.5.1"):
        assert required in versions, f"CHANGELOG.md is missing [{required}]"
