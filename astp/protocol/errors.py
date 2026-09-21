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
ASTP — Exception Hierarchy

Base exceptions for all protocol-level errors. These are structural
errors indicating protocol non-conformance, not application errors.
"""


class ASTPProtocolError(Exception):
    """Base exception for all ASTP protocol violations."""
    pass


AriadneProtocolError = ASTPProtocolError  # name retained for callers written before astp 0.6.0


class GovernanceViolation(ASTPProtocolError):
    """A governance rule has been violated."""
    pass


class ReparentingViolation(GovernanceViolation):
    """Attempted to change a node's parent_node_id after creation.

    Reparenting is a governance violation, not a valid operation.
    A node's parentage is a fact about its origin. To correct
    incorrect parentage: create a new node with correct parentage,
    issue a deprecation record on the original.
    """
    pass


class VerificationError(ASTPProtocolError):
    """Hash verification or integrity check failed."""
    pass


class StaleRootError(ASTPProtocolError):
    """Compare-and-swap failed on spine_root — concurrent writer detected."""
    pass


class MonotonicityViolation(GovernanceViolation):
    """A monotonically increasing value decreased (logical clock, sequence index)."""
    pass


class AdapterWriteError(ASTPProtocolError):
    """An adapter operation did not complete (SPEC §15 item 7: fail loudly).

    Raised, chained to the underlying driver or store error, by every reference
    adapter writer and reader when the store refuses or the operation fails part
    way. Never swallowed inside the package: the host decides whether to retry,
    queue, or surface it, and a ledger entry is never written as COMPLETE for a
    write that did not happen (G-39).
    """


class BranchOperationError(ASTPProtocolError):
    """A branch, fork, merge, aside or soliloquy operation failed after it began.

    Raised, chained, in place of the ``return None`` the 4.x operations used
    for any exception. A precondition *refusal* (source Episode not found or
    not ACTIVE, branch already terminated, …) is not an error: those still
    return ``None`` after logging, so a caller can tell "refused" from
    "failed". No WIL entry is written for an operation that raised.
    """
