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
"""The 5.1.0 adapter failure contract (SPEC §15 item 7, G-39).

Nothing in the operations layer is gated by a feature flag, and nothing
swallows a failure: an operation raises ``AdapterWriteError`` or
``BranchOperationError`` (chained) when the store refuses or the operation
fails part way, governance violations pass through untouched, and the
audit-chain helpers refuse to guess a chain head. The first two tests are
structural guards over the source; the rest exercise representative functions
against a store that fails. (The reference deployment's adapter carries the
same contract and its own guards, where it lives.)
"""

import ast
from pathlib import Path
from uuid import uuid4

import pytest

from astp.adapters.memory import InMemoryStore
from astp.protocol.errors import AdapterWriteError, ASTPProtocolError, BranchOperationError

PKG = Path(__file__).resolve().parents[3] / "astp"
OPERATION_MODULES = [
    PKG / "core" / p for p in ("audit_chain.py", "branch_operations.py", "cross_episode.py", "grouping.py", "coherence.py", "wil.py")
] + [PKG / "adapters" / "memory.py"]


def test_no_feature_flag_anywhere_in_the_package():
    hits = [str(p.relative_to(PKG)) for p in PKG.rglob("*.py") if "ARIADNE_ENABLED" in p.read_text() or "_ariadne_guard" in p.read_text()]
    assert hits == [], f"feature flag remnants: {hits}"


def test_no_operation_handler_swallows_an_exception():
    """Every `except Exception` / bare `except` in the operations modules and
    the reference store re-raises (any `raise` in its body)."""
    offenders = []
    for path in OPERATION_MODULES:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for h in node.handlers:
                    broad = h.type is None or (isinstance(h.type, ast.Name) and h.type.id == "Exception")
                    if broad and not any(isinstance(n, ast.Raise) for n in ast.walk(ast.Module(body=h.body, type_ignores=[]))):
                        offenders.append(f"{path.name}:{h.lineno}")
    assert offenders == [], f"handlers that swallow: {offenders}"


class _BrokenStore(InMemoryStore):
    """Every read and write fails the way a store that is down fails."""

    def __getattribute__(self, name):
        attr = object.__getattribute__(self, name)
        if callable(attr) and not name.startswith("_"):
            def _down(*a, **k): raise RuntimeError("store down")
            return _down
        return attr


def test_audit_chain_helpers_refuse_to_guess():
    from astp.core.audit_chain import next_delta_sequence, prior_audit_hash
    with pytest.raises(AdapterWriteError, match="next_delta_sequence"):
        next_delta_sequence(_BrokenStore(), "chain")
    with pytest.raises(AdapterWriteError, match="prior_audit_hash"):
        prior_audit_hash(_BrokenStore(), "chain")


def test_branch_operation_failure_is_typed():
    from astp.core.branch_operations import create_branch
    from astp.core.branching import BranchType
    with pytest.raises(BranchOperationError, match="create_branch failed"):
        create_branch(_BrokenStore(), source_episode_id=str(uuid4()), source_segment_id="seg", branch_intent="x")
