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

Nothing in the reference adapter is gated by a feature flag, and nothing
swallows a failure: every writer and reader raises ``AdapterWriteError``
(chained) when the store refuses or the operation fails part way, governance
violations pass through untouched, and the audit-chain helpers refuse to guess
a chain head. The first two tests are structural guards over the source; the
rest exercise representative functions against a driver that fails.
"""

import ast
from pathlib import Path
from uuid import uuid4

import pytest

from astp.protocol.errors import AdapterWriteError, ASTPProtocolError, BranchOperationError

PKG = Path(__file__).resolve().parents[3] / "astp"
ADAPTER_MODULES = [
    PKG / "adapters" / "neo4j" / p for p in ("writer.py", "wil.py", "crystallization.py", "queries.py", "rebalance.py", "retrieval_audit.py")
] + [PKG / "core" / "audit_chain.py", PKG / "core" / "branch_operations.py", PKG / "core" / "wil.py"]


def test_no_feature_flag_anywhere_in_the_package():
    hits = [str(p.relative_to(PKG)) for p in PKG.rglob("*.py") if "ARIADNE_ENABLED" in p.read_text() or "_ariadne_guard" in p.read_text()]
    assert hits == [], f"feature flag remnants: {hits}"


def test_no_adapter_handler_swallows_an_exception():
    """Every `except Exception` / bare `except` in the adapter and operation
    modules re-raises (any `raise` in its body)."""
    offenders = []
    for path in ADAPTER_MODULES:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for h in node.handlers:
                    broad = h.type is None or (isinstance(h.type, ast.Name) and h.type.id == "Exception")
                    if broad and not any(isinstance(n, ast.Raise) for n in ast.walk(ast.Module(body=h.body, type_ignores=[]))):
                        offenders.append(f"{path.name}:{h.lineno}")
    assert offenders == [], f"handlers that swallow: {offenders}"


class _BrokenSession:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def run(self, *a, **k): raise RuntimeError("store down")
    def single(self): raise RuntimeError("store down")


class _BrokenDriver:
    def session(self, *a, **k): return _BrokenSession()


def test_audit_chain_helpers_refuse_to_guess():
    from astp.core.audit_chain import next_delta_sequence, prior_audit_hash
    with pytest.raises(AdapterWriteError, match="next_delta_sequence"):
        next_delta_sequence(_BrokenDriver(), "chain")
    with pytest.raises(AdapterWriteError, match="prior_audit_hash"):
        prior_audit_hash(_BrokenDriver(), "chain")


def test_sync_writers_raise_chained():
    from astp.adapters.neo4j.writer import write_audit_record_sync, write_branch_point_sync
    from astp.core.branching import AuditRecord, BranchDeclarationType, BranchPointNode, BranchType, CognitiveDeltaType, TriggerType
    ep = uuid4()
    bp = BranchPointNode(episode_id=ep, parent_episode_id=ep, branch_label="x", source_segment_id="seg",
                         branch_type=BranchType.EXPLORATORY, declaration_type=BranchDeclarationType.EXPLICIT,
                         trigger_context=TriggerType.HUMAN_EXPLICIT, initiated_by="devin", spine_merkle_snapshot="ab" * 32)
    with pytest.raises(AdapterWriteError, match="write_branch_point_sync") as ei:
        write_branch_point_sync(_BrokenDriver(), bp)
    assert isinstance(ei.value.__cause__, RuntimeError)
    ar = AuditRecord(delta_sequence=1, agent_id="a", session_id="s", delta_type=CognitiveDeltaType.BRANCH_CREATED,
                     trigger_context=TriggerType.HUMAN_EXPLICIT, episode_id="ep")
    with pytest.raises(AdapterWriteError, match="write_audit_record_sync"):
        write_audit_record_sync(_BrokenDriver(), ar)


def test_readers_raise_rather_than_return_empty():
    from astp.adapters.neo4j.writer import load_aside_sync, query_recent_fingerprints_sync, scan_aside_external_references_sync
    with pytest.raises(AdapterWriteError):
        load_aside_sync(_BrokenDriver(), str(uuid4()))
    with pytest.raises(AdapterWriteError):
        query_recent_fingerprints_sync(_BrokenDriver(), str(uuid4()), 5)
    with pytest.raises(AdapterWriteError):
        scan_aside_external_references_sync(_BrokenDriver(), str(uuid4()), ["seg-1"])


def test_governance_violations_pass_through_unwrapped():
    """A G-rule raised inside a writer is not re-wrapped as a store failure."""
    from astp.adapters.neo4j.writer import write_branch_point_sync

    class _GovSession(_BrokenSession):
        def run(self, *a, **k): raise ASTPProtocolError("G-1")

    class _GovDriver:
        def session(self, *a, **k): return _GovSession()

    from astp.core.branching import BranchDeclarationType, BranchPointNode, BranchType, TriggerType
    ep = uuid4()
    bp = BranchPointNode(episode_id=ep, parent_episode_id=ep, branch_label="x", source_segment_id="seg",
                         branch_type=BranchType.EXPLORATORY, declaration_type=BranchDeclarationType.EXPLICIT,
                         trigger_context=TriggerType.HUMAN_EXPLICIT, initiated_by="devin", spine_merkle_snapshot="ab" * 32)
    with pytest.raises(ASTPProtocolError, match="G-1") as ei:
        write_branch_point_sync(_GovDriver(), bp)
    assert not isinstance(ei.value, AdapterWriteError)


def test_branch_operation_failure_is_typed():
    from astp.core.branch_operations import create_branch
    from astp.core.branching import BranchType
    with pytest.raises(BranchOperationError, match="create_branch failed"):
        create_branch(_BrokenDriver(), source_episode_id=str(uuid4()), source_segment_id="seg", branch_intent="x")
