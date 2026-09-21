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
Names retained as aliases when the public API took the protocol's name (astp 0.6.0).

A caller written against the ``Ariadne*`` names keeps working: each old name
IS the new object, not a copy, so ``except`` clauses and ``isinstance`` checks
written against either name agree.
"""

import os
from importlib import reload

from astp.adapters import base as adapters_base
from astp.adapters.neo4j import writer
from astp.core import grouping, schema
from astp.protocol import errors


def test_error_and_adapter_aliases_are_the_same_objects():
    assert errors.AriadneProtocolError is errors.ASTPProtocolError
    assert schema.AriadneGovernanceError is schema.ASTPGovernanceError
    assert adapters_base.AriadneAdapter is adapters_base.ASTPAdapter
    assert schema.ARIADNE_SCHEMA_VERSION == schema.ASTP_SCHEMA_VERSION
    assert writer.initialize_ariadne_schema is writer.initialize_astp_schema


def test_old_exception_names_catch_new_raises():
    try:
        raise schema.ASTPGovernanceError("G-1")
    except schema.AriadneGovernanceError:
        pass
    try:
        raise errors.ASTPProtocolError("p")
    except errors.AriadneProtocolError:
        pass


def test_grouping_system_keeps_the_retained_value():
    assert grouping.GroupingSystem.ASTP_NATIVE.value == "astp_native"
    assert grouping.GroupingSystem.ARIADNE_NATIVE.value == "ariadne_native"
    assert grouping.GroupingSystem("ariadne_native") is grouping.GroupingSystem.ARIADNE_NATIVE


def test_old_env_names_are_honoured(monkeypatch):
    from astp.core import wil
    from astp.adapters.neo4j import crystallization
    monkeypatch.delenv("ASTP_PROVISIONAL_WINDOW_HOURS", raising=False)
    monkeypatch.setenv("ARIADNE_PROVISIONAL_WINDOW_HOURS", "2.5")
    monkeypatch.delenv("ASTP_IMPLICIT_CRYSTALLIZATION_ON_ARCHIVE", raising=False)
    monkeypatch.setenv("ARIADNE_IMPLICIT_CRYSTALLIZATION_ON_ARCHIVE", "false")
    try:
        assert reload(wil).PROVISIONAL_WINDOW_HOURS == 2.5
        assert reload(crystallization).IMPLICIT_CRYSTALLIZATION_ON_ARCHIVE is False
        monkeypatch.setenv("ASTP_PROVISIONAL_WINDOW_HOURS", "1.0")
        assert reload(wil).PROVISIONAL_WINDOW_HOURS == 1.0  # the new name wins when both are set
    finally:
        monkeypatch.delenv("ARIADNE_PROVISIONAL_WINDOW_HOURS", raising=False)
        monkeypatch.delenv("ARIADNE_IMPLICIT_CRYSTALLIZATION_ON_ARCHIVE", raising=False)
        monkeypatch.delenv("ASTP_PROVISIONAL_WINDOW_HOURS", raising=False)
        reload(wil); reload(crystallization)
