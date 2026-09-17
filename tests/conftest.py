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
Shared pytest fixtures.

The Neo4j reference adapter gates every write and query on a module-level
``ARIADNE_ENABLED`` flag that each module reads from the environment once,
at import. The fixture below turns the flag on for the duration of each
test, in every module that holds its own copy, without touching
``os.environ`` or reloading modules, so a test file behaves the same alone,
in any order, and in the full run.
"""

from __future__ import annotations

import importlib

import pytest

# Every module that binds its own ``ARIADNE_ENABLED`` name. A
# ``from x import ARIADNE_ENABLED`` creates a separate binding, so modules
# that import the flag are listed alongside the ones that define it.
ARIADNE_ENABLED_MODULES = (
    "astp.core.wil",
    "astp.adapters.neo4j.writer",
    "astp.adapters.neo4j.queries",
    "astp.adapters.neo4j.crystallization",
    "astp.adapters.neo4j.rebalance",
    "astp.adapters.neo4j.retrieval_audit",
    "astp.adapters.neo4j.wil",
)


@pytest.fixture(autouse=True)
def ariadne_enabled(monkeypatch):
    """Enable the adapter feature flag in every module that holds a copy."""
    for name in ARIADNE_ENABLED_MODULES:
        module = importlib.import_module(name)
        monkeypatch.setattr(module, "ARIADNE_ENABLED", True)
