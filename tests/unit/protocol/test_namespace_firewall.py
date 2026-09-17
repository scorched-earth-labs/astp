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

Enforces the layering rules of the package by static analysis of every
Python file under ``astp/protocol/`` plus a runtime ``sys.modules`` check:

  1. ``astp.protocol.*`` must NEVER import from ``astp.nodes.*``.
  2. ``astp.protocol.*`` must not import from ``astp.core.*`` or
     ``astp.adapters.*`` — the protocol layer is the bottom of the stack.

The detector resolves relative imports, inspects the names imported by
``from X import name`` (so ``from astp import nodes`` is caught), and flags
string-literal arguments to ``importlib.import_module`` / ``__import__``.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = REPO_ROOT / "astp"
PROTOCOL_DIR = PACKAGE_ROOT / "protocol"
FORBIDDEN_PREFIX = "astp.nodes"
LOWER_LAYER_FORBIDDEN_PREFIXES = ("astp.core", "astp.adapters")

_DYNAMIC_IMPORT_FUNCTIONS = {"import_module", "__import__"}


def _module_name(filepath: Path) -> tuple[str, bool]:
    """Dotted module name of a file under the repo root, and whether it is a package."""
    parts = list(filepath.resolve().relative_to(REPO_ROOT).with_suffix("").parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts.pop()
    return ".".join(parts), is_package


def _resolve_relative(name: str | None, level: int, module_name: str, is_package: bool) -> str:
    """Absolute dotted name for ``from <level dots><name> import ...`` inside ``module_name``."""
    if level == 0:
        return name or ""
    package = module_name.split(".") if is_package else module_name.split(".")[:-1]
    keep = len(package) - (level - 1)
    base = package[:keep] if keep > 0 else []
    if name:
        base = base + name.split(".")
    return ".".join(base)


def _imported_names(source: str, module_name: str, is_package: bool = False) -> list[str]:
    """Every absolute dotted name a module's source imports, statically or dynamically.

    For ``from X import a, b`` this yields ``X``, ``X.a`` and ``X.b``: any of
    the imported names may itself be a submodule.
    """
    tree = ast.parse(source, filename=module_name)
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_relative(node.module, node.level, module_name, is_package)
            if base:
                names.append(base)
            for alias in node.names:
                if alias.name != "*":
                    names.append(f"{base}.{alias.name}" if base else alias.name)
        elif isinstance(node, ast.Call):
            func = node.func
            func_name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if func_name in _DYNAMIC_IMPORT_FUNCTIONS and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    target = arg.value
                    if target.startswith("."):
                        level = len(target) - len(target.lstrip("."))
                        target = _resolve_relative(
                            target.lstrip(".") or None, level, module_name, is_package
                        )
                    names.append(target)
    return names


def _is_under(name: str, prefix: str) -> bool:
    """True for ``prefix`` itself or a dotted descendant — not for ``prefix_other``."""
    return name == prefix or name.startswith(prefix + ".")


def _violations(source: str, module_name: str, prefixes, is_package: bool = False) -> list[str]:
    return sorted({
        name
        for name in _imported_names(source, module_name, is_package)
        if any(_is_under(name, prefix) for prefix in prefixes)
    })


def _protocol_files() -> list[Path]:
    return sorted(PROTOCOL_DIR.rglob("*.py"))


def _scan_protocol_layer(prefixes) -> list[str]:
    found = []
    for py_file in _protocol_files():
        with open(py_file, encoding="utf-8") as f:
            source = f.read()
        module_name, is_package = _module_name(py_file)
        for name in _violations(source, module_name, prefixes, is_package):
            found.append(f"{py_file.relative_to(REPO_ROOT)}: imports '{name}'")
    return found


# ── The detector itself ─────────────────────────────────────────────────────


@pytest.mark.parametrize("source", [
    "import astp.nodes",
    "import astp.nodes.episode as ep",
    "import os, astp.nodes.segment",
    "from astp.nodes import factory",
    "from astp.nodes.episode import EpisodePayload",
    "from astp import nodes",
    "from astp import nodes as n",
    "from .. import nodes",
    "from ..nodes import factory",
    "from ..nodes.episode import EpisodePayload",
    "def f():\n    from astp.nodes import factory\n",
    "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from astp.nodes import factory\n",
    "import importlib\nimportlib.import_module('astp.nodes.episode')",
    "from importlib import import_module\nimport_module('astp.nodes')",
    "__import__('astp.nodes.segment')",
    "import importlib\nimportlib.import_module('..nodes', package='astp.protocol')",
])
def test_detector_flags_every_import_form(source):
    assert _violations(source, "astp.protocol.example", [FORBIDDEN_PREFIX])


def test_detector_resolves_relative_imports_from_package_init_and_subpackage():
    assert _violations("from ..nodes import factory", "astp.protocol", [FORBIDDEN_PREFIX], is_package=True)
    assert _violations("from ...nodes import factory", "astp.protocol.sub.mod", [FORBIDDEN_PREFIX])
    # One dot fewer stays inside the protocol package.
    assert not _violations("from ..nodes import factory", "astp.protocol.sub.mod", [FORBIDDEN_PREFIX])


@pytest.mark.parametrize("source", [
    "import astp.nodes_helper",
    "from astp import nodes_helper",
    "from astp.nodes_helper import x",
    "from . import node",
    "from .node import CognitiveNode",
    "from astp.protocol.node import CognitiveNode",
    "import importlib\nimportlib.import_module('astp.nodes_helper')",
    "print('astp.nodes')",
    "NAME = 'astp.nodes.episode'",
])
def test_detector_has_no_false_positives(source):
    assert not _violations(source, "astp.protocol.example", [FORBIDDEN_PREFIX])


def test_detector_flags_lower_layer_imports():
    for source in (
        "from astp.core.schema import sha3_256",
        "from astp import core",
        "from ..core import schema",
        "from ..adapters.neo4j import writer",
        "import astp.adapters",
    ):
        assert _violations(source, "astp.protocol.example", LOWER_LAYER_FORBIDDEN_PREFIXES), source
    assert not _violations(
        "from astp.protocol.hashing import sha3_256",
        "astp.protocol.example",
        LOWER_LAYER_FORBIDDEN_PREFIXES,
    )


# ── The layering rules ──────────────────────────────────────────────────────


def test_protocol_never_imports_from_nodes():
    """The protocol layer must never import from the nodes layer."""
    violations = _scan_protocol_layer([FORBIDDEN_PREFIX])
    assert not violations, (
        f"Namespace firewall violated! {len(violations)} violation(s) — "
        f"protocol layer must not depend on node-type-specific code:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


def test_protocol_never_imports_from_core_or_adapters():
    """The protocol layer is the bottom of the stack: no core or adapter imports."""
    violations = _scan_protocol_layer(LOWER_LAYER_FORBIDDEN_PREFIXES)
    assert not violations, (
        f"{len(violations)} protocol-layer import(s) reach into a higher layer:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


def test_importing_protocol_loads_no_other_layer():
    """Runtime check: ``import astp.protocol`` must not pull in nodes, core or adapters."""
    code = (
        "import astp.protocol, sys\n"
        "print([m for m in sys.modules if m == 'astp.nodes' or m.startswith("
        "('astp.nodes.', 'astp.core', 'astp.adapters'))])\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True,
        cwd=REPO_ROOT,
    )
    assert out.stdout.strip() == "[]"


def test_protocol_directory_exists():
    """Sanity check: the protocol directory exists and has Python files."""
    assert PROTOCOL_DIR.exists(), f"Protocol directory not found: {PROTOCOL_DIR}"
    assert _protocol_files(), f"No Python files in {PROTOCOL_DIR}"
