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
Namespace Firewall Test

Enforces the inviolable rule: ariadne.protocol.* must NEVER import
from ariadne.nodes.*. This is a structural test that scans the AST
of all protocol-layer Python files.
"""

import ast
import os
from pathlib import Path


PROTOCOL_DIR = Path(__file__).parent.parent.parent.parent / "ariadne" / "protocol"
FORBIDDEN_PREFIX = "ariadne.nodes"


def _collect_imports(filepath: Path) -> list[str]:
    """Extract all import module names from a Python file."""
    with open(filepath) as f:
        tree = ast.parse(f.read(), filename=str(filepath))

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


def test_protocol_never_imports_from_nodes():
    """The protocol layer must never import from the nodes layer."""
    violations = []

    for py_file in PROTOCOL_DIR.glob("*.py"):
        imports = _collect_imports(py_file)
        for imp in imports:
            if imp.startswith(FORBIDDEN_PREFIX):
                violations.append(
                    f"{py_file.name}: imports '{imp}' — "
                    f"protocol layer must not depend on node-type-specific code"
                )

    assert not violations, (
        f"Namespace firewall violated! {len(violations)} violation(s):\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


def test_protocol_directory_exists():
    """Sanity check: the protocol directory exists and has Python files."""
    assert PROTOCOL_DIR.exists(), f"Protocol directory not found: {PROTOCOL_DIR}"
    py_files = list(PROTOCOL_DIR.glob("*.py"))
    assert len(py_files) > 0, f"No Python files in {PROTOCOL_DIR}"
