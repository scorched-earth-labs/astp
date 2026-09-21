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
The operations layer names no store.

``astp.core`` and ``astp.protocol`` reach storage only through the
``StructuralStore`` contract (SPEC §15). These are structural guards over the
source — the same discipline as the namespace firewall — plus the contract's
own behaviour: the reference implementation is complete, coercion is
idempotent, and an operation runs against any ``StructuralStore`` with no
driver in sight.
"""

import ast
import inspect
from pathlib import Path

import pytest

from astp.adapters.base import StructuralStore, as_structural_store

PKG = Path(__file__).resolve().parents[3] / "astp"
OPERATIONS_LAYER = [p for d in ("core", "protocol", "nodes") for p in (PKG / d).rglob("*.py")]
VENDOR_WORDS = ("neo4j", "cypher", "redis")


def _imports(path: Path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
        elif isinstance(node, ast.Import):
            for a in node.names:
                yield a.name


def test_operations_layer_never_imports_the_reference_adapter():
    offenders = sorted(
        f"{p.relative_to(PKG)}: {m}"
        for p in OPERATIONS_LAYER
        for m in _imports(p)
        if m.startswith("astp.adapters.neo4j")
    )
    assert offenders == [], f"the operations layer imports the reference adapter: {offenders}"


def test_operations_layer_never_opens_a_store_session():
    """No ``driver.session()`` and no ``session.run`` outside the adapter package."""
    offenders = []
    for p in OPERATIONS_LAYER:
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if ".session(" in line or "session.run(" in line:
                offenders.append(f"{p.relative_to(PKG)}:{i}")
    assert offenders == [], f"raw store access in the operations layer: {offenders}"


def test_reference_store_implements_the_whole_contract():
    from astp.adapters.neo4j.store import Neo4jStructuralStore
    abstract = {n for n, m in inspect.getmembers(StructuralStore) if getattr(m, "__isabstractmethod__", False)}
    assert abstract, "the contract declares nothing"
    store = Neo4jStructuralStore(object())  # instantiation fails if any abstract method is missing
    assert isinstance(store, StructuralStore)
    for name in abstract:
        assert not getattr(getattr(store, name), "__isabstractmethod__", False)


class _NoSuchEpisodeStore(StructuralStore):
    """A store in which nothing exists. Every abstract method is present; only
    the ones an early-refused operation reaches are meaningful."""

    def __init__(self):
        self.calls = []

    def __getattribute__(self, name):
        attr = super().__getattribute__(name)
        if callable(attr) and not name.startswith("_") and name != "calls":
            def _rec(*a, **k):
                object.__getattribute__(self, "calls").append(name)
                return attr(*a, **k)
            return _rec
        return attr


# Fill the contract with refusals so the class is concrete.
for _name, _m in inspect.getmembers(StructuralStore):
    if getattr(_m, "__isabstractmethod__", False):
        setattr(_NoSuchEpisodeStore, _name, (lambda self, *a, **k: None) if _name != "departure_fork_episode" else (lambda self, *a, **k: (None, None)))
_NoSuchEpisodeStore.__abstractmethods__ = frozenset()


def test_coercion_returns_a_structural_store_unchanged():
    store = _NoSuchEpisodeStore()
    assert as_structural_store(store) is store


def test_coercion_wraps_a_raw_driver_in_the_reference_store():
    from astp.adapters.neo4j.store import Neo4jStructuralStore
    driver = object()
    wrapped = as_structural_store(driver)
    assert isinstance(wrapped, Neo4jStructuralStore) and wrapped.driver is driver


def test_an_operation_runs_against_any_structural_store():
    """``create_branch`` refuses (returns None) when the source Episode does not
    exist — reached through the contract alone, no driver anywhere."""
    from astp.core.branch_operations import create_branch
    store = _NoSuchEpisodeStore()
    assert create_branch(store, "ep-1", "seg-1", "explore") is None
    assert store.calls == ["episode_status"]


def test_audit_chain_helpers_read_through_the_contract():
    from astp.core.audit_chain import GENESIS_HASH, next_delta_sequence, prior_audit_hash
    store = _NoSuchEpisodeStore()
    assert next_delta_sequence(store, "chain") == 1
    assert prior_audit_hash(store, "chain") == GENESIS_HASH
    assert store.calls == ["max_delta_sequence", "latest_audit_record_hash"]
