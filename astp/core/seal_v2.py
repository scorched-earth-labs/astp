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
Episode seal constructions for SPEC 5.0.0 (DRAFT; not yet ratified).

Everything here is a *new versioned construction*. Nothing in this module
replaces a 4.x function: seals made under ``spine_algorithm_version`` 0 and 1
remain reproducible with the functions that made them (``reproduce_spine_root``).

What changes, and why (design Episode 4b9a779e-be46-4d61-872e-fd76545aa901):

* **Spine leaves are position-binding leaf hashes** (``hash_version`` 2), not bare
  content hashes. The 4.x spine root commits to content and order only; this one
  also commits to each Segment's identity, type, schema version, position and
  parent.
* **Raw bytes.** Hash values enter every construction as 32 bytes, never as hex
  text. Encoding is a property of the algorithm version: a verifier reads it off
  the tag, exactly as it reads the presence of the Episode-identifier leaf.
* **No Episode-identifier leaf.** Each leaf binds its parent — the Episode — so
  the leaf is redundant, and the Episode root binds ``episode_id`` explicitly.
  The leaf is dropped in this construction and not before: under content-hash
  leaves it is the only thing that stops a spine being transplanted.
* **A structural manifest.** Branch, fork, departure-fork and merge points, and
  resolved human-in-the-loop events, are committed into the Episode root as an
  order-independent set. They have no ``sequence_index``; as spine leaves they
  would need an ordering key they do not reliably have, which is the defect that
  left four 4.x seals reproducible only by search. As a set, removing one changes
  the Episode root and no ordering question arises.
* **One field encoding, one prefix per construction** (``astp.protocol.encoding``).
"""

from datetime import datetime
from typing import Iterable, List, Optional
from uuid import UUID

from astp.protocol.encoding import HASH, STRING, TIMESTAMP, UINT, UUID_, hash_fields, hash_set
from astp.protocol.leaf_hash import compute_leaf_hash_v2
from astp.protocol.merkle import compute_merkle_root_v2

SPINE_ALGORITHM_VERSION_DRAFT = 2
EPISODE_ROOT_VERSION_DRAFT = 2

# ── domain prefix registry (one per construction and version) ───────────────────
SIGNAL_MANIFEST_V2 = b"SIGNAL_MANIFEST:v2:"
EXCLUSION_V2 = b"EXCLUSION:v2:"
STRUCTURAL_MANIFEST_V1 = b"STRUCTURAL_MANIFEST:v1:"
EPISODE_ROOT_V2 = b"EPISODE_ROOT:v2:"
BRANCH_POINT_V2 = b"BRANCH_POINT:v2:"
BRANCH_TERMINUS_V2 = b"BRANCH_TERMINUS:v2:"
FORK_POINT_V2 = b"FORK_POINT:v2:"
FORK_RETURN_V2 = b"FORK_RETURN:v2:"
DEPARTURE_FORK_POINT_V2 = b"DEPARTURE_FORK_POINT:v2:"
MERGE_POINT_V2 = b"MERGE_POINT:v2:"
HITL_CONTEXT_V2 = b"HITL_CONTEXT:v2:"
HITL_RESOLUTION_V2 = b"HITL_RESOLUTION:v2:"
HITL_NODE_V2 = b"HITL_NODE:v2:"


# ── spine ───────────────────────────────────────────────────────────────────────

def compute_spine_root_sav2(segment_leaf_hashes_in_sequence_order: List[str]) -> str:
    """``spine_algorithm_version`` 2, ``ordering_version`` 2: the raw-bytes Merkle
    root over the ``hash_version`` 2 leaf hashes of the Episode's non-ephemeral
    Segments in ``sequence_index`` order. No other leaf."""
    return compute_merkle_root_v2(segment_leaf_hashes_in_sequence_order)


# ── sets ────────────────────────────────────────────────────────────────────────

def compute_signal_manifest_hash_v2(signal_content_hashes: Iterable[str]) -> str:
    return hash_set(SIGNAL_MANIFEST_V2, signal_content_hashes)


def compute_exclusion_hash_v2(excluded_content_hashes: Iterable[str]) -> str:
    return hash_set(EXCLUSION_V2, excluded_content_hashes)


# A human-in-the-loop event is a manifest member once it is in one of these states.
HITL_TERMINAL_STATES = frozenset({"resolved", "timed_out", "escalated"})


def compute_structural_manifest_hash(member_hashes: Iterable[str]) -> str:
    """Commitment to the Episode's structural nodes.

    Membership rule: a structural node is a member if and only if removing it would
    let a verifier be deceived about the Episode's branch, fork, merge or
    termination structure. Members are the ``:v2:`` content hash of every
    BranchPoint, BranchTerminus, ForkPoint, DepartureForkPoint, ForkReturn and
    MergePoint that sits on this Episode, and the ``HITL_NODE:v2:`` hash of every
    human-in-the-loop event of this Episode in a terminal state
    (``HITL_TERMINAL_STATES``). A ForkOrphanMarker is a diagnostic satellite and is
    not a member. Each member hash is domain-separated by its own prefix, so the
    set needs no per-member type tag.

    The same rule decides fields: a field that makes a structural claim is in a
    member's preimage (``spine_merkle_snapshot``, ``merge_type``); commentary is
    not (a label, a free-text summary).

    A seal is immutable, so a structural node created after a seal is not a
    member of that seal's manifest. It is committed by the Episode's *next*
    crystallization, and references the earlier seal without belonging to it."""
    return hash_set(STRUCTURAL_MANIFEST_V1, member_hashes)


# ── Episode root ────────────────────────────────────────────────────────────────

def compute_episode_root_hash_v2(
    episode_id: UUID,
    spine_root: str,
    signal_manifest_hash: str,
    structural_manifest_hash: str,
    exclusion_hash: str,
) -> str:
    return hash_fields(EPISODE_ROOT_V2, [
        (UUID_, episode_id),
        (HASH, spine_root),
        (HASH, signal_manifest_hash),
        (HASH, structural_manifest_hash),
        (HASH, exclusion_hash),
    ])


# ── structural manifest members ─────────────────────────────────────────────────
# A member's preimage holds its structural claims and nothing else. Relative to
# 4.x that adds two fields 4.x omitted (``spine_merkle_snapshot``, ``merge_type``)
# and drops the provenance and commentary 4.x bound on some nodes and not others
# (``initiated_by``, ``initiator``, ``returned_by``, ``synthesis_summary``): who
# acted is the audit chain's to bind, and free text proves nothing structural.
# 4.x seals that bound those fields stay reproducible under 4.x. ``parent_hash``
# is NULL at the start of a chain (4.x used the text "GENESIS").

def compute_branch_point_hash_v2(branch_point_id: UUID, episode_id: UUID, branch_id: UUID, source_segment_id: UUID,
                                 spine_merkle_snapshot: str, branch_type: str, declaration_type: str,
                                 created_at: datetime, parent_hash: Optional[str]) -> str:
    """``spine_merkle_snapshot`` binds the divergence to the spine state it left
    from; without it a BranchPoint could be re-pointed at a different history."""
    return hash_fields(BRANCH_POINT_V2, [
        (UUID_, branch_point_id), (UUID_, episode_id), (UUID_, branch_id), (UUID_, source_segment_id),
        (HASH, spine_merkle_snapshot), (STRING, branch_type), (STRING, declaration_type),
        (TIMESTAMP, created_at), (HASH, parent_hash),
    ])


def compute_branch_terminus_hash_v2(terminus_id: UUID, branch_id: UUID, terminus_type: str, branch_point_hash: str,
                                    final_merkle_root: Optional[str], created_at: datetime) -> str:
    """A member because removing it would make a closed branch look open."""
    return hash_fields(BRANCH_TERMINUS_V2, [
        (UUID_, terminus_id), (UUID_, branch_id), (STRING, terminus_type), (HASH, branch_point_hash),
        (HASH, final_merkle_root), (TIMESTAMP, created_at),
    ])


def compute_fork_return_hash_v2(fork_return_id: UUID, fork_id: UUID, fork_episode_id: UUID, origin_episode_id: UUID,
                                return_type: str, fork_final_spine_tip_hash: str,
                                created_at: datetime, parent_hash: Optional[str]) -> str:
    """A member because removing it would falsify whether a fork rejoined. Its
    fields are the join fact: which fork, returning to which Episode, how, and
    from what state."""
    return hash_fields(FORK_RETURN_V2, [
        (UUID_, fork_return_id), (UUID_, fork_id), (UUID_, fork_episode_id), (UUID_, origin_episode_id),
        (STRING, return_type), (HASH, fork_final_spine_tip_hash),
        (TIMESTAMP, created_at), (HASH, parent_hash),
    ])


def compute_fork_point_hash_v2(fork_point_id: UUID, fork_id: UUID, episode_id: UUID, origin_episode_id: UUID,
                               origin_segment_id: UUID, fork_objective: str, sibling_index: int,
                               created_at: datetime, parent_hash: Optional[str]) -> str:
    return hash_fields(FORK_POINT_V2, [
        (UUID_, fork_point_id), (UUID_, fork_id), (UUID_, episode_id), (UUID_, origin_episode_id),
        (UUID_, origin_segment_id), (STRING, fork_objective), (UINT, sibling_index),
        (TIMESTAMP, created_at), (HASH, parent_hash),
    ])


def compute_departure_fork_point_hash_v2(fork_point_id: UUID, fork_id: UUID, fork_episode_id: UUID,
                                         origin_episode_id: UUID, origin_segment_id: UUID, fork_objective: str,
                                         fork_creation_trigger: str, spine_tip_hash_at_departure: str,
                                         created_at: datetime, parent_hash: Optional[str]) -> str:
    return hash_fields(DEPARTURE_FORK_POINT_V2, [
        (UUID_, fork_point_id), (UUID_, fork_id), (UUID_, fork_episode_id), (UUID_, origin_episode_id),
        (UUID_, origin_segment_id), (STRING, fork_objective), (STRING, fork_creation_trigger),
        (HASH, spine_tip_hash_at_departure), (TIMESTAMP, created_at), (HASH, parent_hash),
    ])


def compute_merge_point_hash_v2(merge_point_id: UUID, merge_id: UUID, source_episode_id: UUID,
                                target_episode_id: UUID, source_merkle_root: str, target_merkle_root_pre: str,
                                target_merkle_root_post: str, common_ancestor_id: Optional[UUID],
                                merge_type: str, created_at: datetime, parent_hash: Optional[str]) -> str:
    """``merge_type`` is a structural claim: how the two histories combined."""
    return hash_fields(MERGE_POINT_V2, [
        (UUID_, merge_point_id), (UUID_, merge_id), (UUID_, source_episode_id), (UUID_, target_episode_id),
        (HASH, source_merkle_root), (HASH, target_merkle_root_pre), (HASH, target_merkle_root_post),
        (UUID_, common_ancestor_id), (STRING, merge_type), (TIMESTAMP, created_at), (HASH, parent_hash),
    ])


def compute_hitl_context_hash_v2(hitl_request_id: str, episode_id: UUID, gate_type: str, requesting_agent: str,
                                 invoked_at: datetime, context_json: str) -> str:
    return hash_fields(HITL_CONTEXT_V2, [
        (STRING, hitl_request_id), (UUID_, episode_id), (STRING, gate_type), (STRING, requesting_agent),
        (TIMESTAMP, invoked_at), (STRING, context_json),
    ])


def compute_hitl_resolution_hash_v2(hitl_event_id: UUID, decision: str, resolved_by: str,
                                    resolved_at: datetime, rationale: Optional[str]) -> str:
    return hash_fields(HITL_RESOLUTION_V2, [
        (UUID_, hitl_event_id), (STRING, decision), (STRING, resolved_by),
        (TIMESTAMP, resolved_at), (STRING, rationale),
    ])


def compute_hitl_node_hash_v2(context_hash: str, resolution_hash: str) -> str:
    """The structural-manifest member for a human-in-the-loop event. Under 4.x this
    hash shared the ``NODE:`` prefix with Merkle interior nodes; it has its own."""
    return hash_fields(HITL_NODE_V2, [(HASH, context_hash), (HASH, resolution_hash)])
