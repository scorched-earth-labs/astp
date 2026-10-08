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
"""README.md links must be absolute.

README.md is the package's long description, so PyPI renders it too. PyPI
resolves a relative link against pypi.org/project/astp/, where no repository
file exists: every ``./SPEC.md`` there is a dead link. Links into this
repository are absolute GitHub URLs, and each one names a file that exists.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
README = (ROOT / "README.md").read_text(encoding="utf-8")
REPO = "https://github.com/scorched-earth-labs/astp/"
LINK = re.compile(r"\]\(([^)\s]+)\)|href=\"([^\"]+)\"|src=\"([^\"]+)\"")


def _links():
    return [next(g for g in m.groups() if g) for m in LINK.finditer(README)]


def test_readme_has_no_relative_links():
    relative = [l for l in _links() if not re.match(r"(https?:|mailto:|#)", l)]
    assert relative == [], f"relative links render as 404s on PyPI: {relative}"


def test_readme_repository_links_name_existing_files():
    missing = []
    for link in _links():
        if not link.startswith(REPO):
            continue
        rest = link[len(REPO):].split("#")[0]
        kind, _, path = rest.partition("/main/")
        if kind not in ("blob", "tree") or not path:
            continue
        target = ROOT / path.rstrip("/")
        if not (target.is_dir() if kind == "tree" else target.is_file()):
            missing.append(link)
    assert missing == [], f"README links to paths that do not exist: {missing}"
