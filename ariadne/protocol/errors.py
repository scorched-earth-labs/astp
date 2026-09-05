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
Ariadne Protocol v2 — Exception Hierarchy

Base exceptions for all protocol-level errors. These are structural
errors indicating protocol non-conformance, not application errors.
"""


class AriadneProtocolError(Exception):
    """Base exception for all Ariadne v2 protocol violations."""
    pass


class GovernanceViolation(AriadneProtocolError):
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


class VerificationError(AriadneProtocolError):
    """Hash verification or integrity check failed."""
    pass


class StaleRootError(AriadneProtocolError):
    """Compare-and-swap failed on spine_root — concurrent writer detected."""
    pass


class MonotonicityViolation(GovernanceViolation):
    """A monotonically increasing value decreased (logical clock, sequence index)."""
    pass
