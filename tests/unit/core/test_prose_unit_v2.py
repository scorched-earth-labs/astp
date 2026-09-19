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
"""SPEC 5.0.0 §12.1 (role-named store values) and G-40 (sealed requires a record)."""

from datetime import datetime, timedelta, timezone

import pytest

from astp.core.seal_v2 import SealWithoutRecord, check_seal_record
from astp.core.wil import StoreLayer, StoreRole, store_role_of


def test_store_roles_are_named_by_role_and_legacy_provider_values_map_to_them():
    assert [r.value for r in StoreRole] == ["durable_content", "authoritative_structural", "ephemeral_coordinator", "semantic_index"]
    assert store_role_of("durable_content") is StoreRole.DURABLE_CONTENT
    # a 4.x ledger entry stays readable
    for layer, role in zip(StoreLayer, StoreRole):
        assert store_role_of(layer.value) is role
    with pytest.raises(ValueError):
        store_role_of("mongodb")


def test_sealed_requires_a_record_and_late_seal_is_ordinary():
    t0 = datetime(2026, 3, 1, tzinfo=timezone.utc)
    check_seal_record(sealed_at=None, closed_at=None, has_crystallization_record=False)          # unsealed passes
    check_seal_record(sealed_at=t0, closed_at=t0, has_crystallization_record=True)
    check_seal_record(sealed_at=t0 + timedelta(days=200), closed_at=t0, has_crystallization_record=True)   # late seal: valid
    with pytest.raises(SealWithoutRecord, match="no crystallization record"):
        check_seal_record(sealed_at=t0, closed_at=t0, has_crystallization_record=False)
    with pytest.raises(SealWithoutRecord, match="precedes"):
        check_seal_record(sealed_at=t0 - timedelta(seconds=1), closed_at=t0, has_crystallization_record=True)
