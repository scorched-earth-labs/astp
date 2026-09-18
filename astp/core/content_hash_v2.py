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
Content hashes for the §19 side-channel nodes and the cross-Episode link
(SPEC 5.0.0; pending ratification).

None of these is a seal input. Each is a node's own content hash: the claim
that node makes, bound so that the claim cannot be altered after the fact.
Every construction is new and versioned; 4.x values remain what the 4.x
functions computed.

What each binds, and what it deliberately does not:

* **Aside** — a channel opened by a human with one agent, from one Segment.
  The two parties are the channel, not provenance of an operation, so both are
  bound. The Segment it opened from is bound by identity *and* content hash;
  4.x reserved a ``parent_hash`` for this and never populated it, so 4.x asides
  bind an empty string where the parent's content should be. The label is
  commentary and is not bound.
* **Aside terminus** — how the channel closed: the content it produced (the
  content hashes of the Segments written inside it, in order), the close reason,
  the reference-scan outcome and the external Segments that were found holding
  references into it. Notification targets and duration are not bound.
* **Soliloquy** — a private deliberation opened by an agent from one Segment.
  One construction: the deliberation chain does not exist when the node is
  created, so it is not in the node's hash; 4.x's ``FULL_CONTENT`` policy bound
  whatever the chain was at open, usually nothing, and is retired.
* **Deliberation chain** — the content hashes of the deliberation Segments in
  order, hashed so a human auditor with access can verify the chain against the
  conclusion without the content being in the hash. 4.x hashed the Segments'
  identifiers, which binds nothing about what was thought.
* **Soliloquy conclusion** — the public conclusion: its summary, the chain hash,
  the spine Segment it merged into and how it terminated.
* **Episode link** — a relationship between two Episodes. It binds the two
  Episode identifiers, and for each end the Episode root at link creation when
  that end was sealed (NULL when it was not), the link's type, strength,
  inference provenance (each signal hashed on its own, listed in order) and
  whether it was retroactive. Health state and quarantine are lifecycle, and who
  asserted the link is provenance: both belong to the audit chain and are not
  bound. 4.x bound the health fields, so the hash of a 4.x link changes when its
  health does and commits to nothing stable.
"""

from datetime import datetime
from typing import Iterable, List, Optional
from uuid import UUID

from astp.protocol.encoding import BOOL, FLOAT, HASH, LIST, NULL, STRING, TIMESTAMP, UUID_, hash_fields

# ── domain prefix registry (one per construction and version) ───────────────────
ASIDE_V2 = b"ASIDE:v2:"
ASIDE_TERMINUS_V2 = b"ASIDE_TERMINUS:v2:"
SOLILOQUY_V2 = b"SOLILOQUY:v2:"
DELIBERATION_CHAIN_V2 = b"DELIBERATION_CHAIN:v2:"
SOLILOQUY_CONCLUSION_V2 = b"SOLILOQUY_CONCLUSION:v2:"
EPISODE_LINK_V2 = b"EPISODE_LINK:v2:"
LINK_SIGNAL_V2 = b"LINK_SIGNAL:v2:"


def _opt(kind, value):
    return (NULL, None) if value is None else (kind, value)


def compute_aside_hash_v2(aside_id: UUID, parent_episode_id: UUID, parent_segment_id: UUID,
                          parent_segment_content_hash: str, initiated_by_human: str, target_agent_id: str,
                          opened_at: datetime) -> str:
    return hash_fields(ASIDE_V2, [
        (UUID_, aside_id), (UUID_, parent_episode_id), (UUID_, parent_segment_id),
        (HASH, parent_segment_content_hash), (STRING, initiated_by_human), (STRING, target_agent_id),
        (TIMESTAMP, opened_at),
    ])


def compute_aside_terminus_hash_v2(aside_terminus_id: UUID, aside_id: UUID, parent_episode_id: UUID,
                                   aside_content_hash: str, produced_content_hashes: Iterable[str],
                                   close_reason: str, reference_scan_passed: bool,
                                   external_references_found: Iterable[UUID], termination_status: str,
                                   closed_at: datetime) -> str:
    """``produced_content_hashes`` are the content hashes of the Segments written
    inside the aside, in the order written; ``external_references_found`` are the
    identifiers of Segments outside the aside that were found holding references
    into it, in the order found."""
    return hash_fields(ASIDE_TERMINUS_V2, [
        (UUID_, aside_terminus_id), (UUID_, aside_id), (UUID_, parent_episode_id), (HASH, aside_content_hash),
        ((LIST, HASH), list(produced_content_hashes)), (STRING, close_reason), (BOOL, reference_scan_passed),
        ((LIST, UUID_), list(external_references_found)), (STRING, termination_status), (TIMESTAMP, closed_at),
    ])


def compute_soliloquy_hash_v2(soliloquy_id: UUID, parent_episode_id: UUID, parent_segment_id: UUID,
                              parent_segment_content_hash: str, initiated_by_agent: str,
                              opened_at: datetime) -> str:
    return hash_fields(SOLILOQUY_V2, [
        (UUID_, soliloquy_id), (UUID_, parent_episode_id), (UUID_, parent_segment_id),
        (HASH, parent_segment_content_hash), (STRING, initiated_by_agent), (TIMESTAMP, opened_at),
    ])


def compute_deliberation_chain_hash_v2(soliloquy_id: UUID, deliberation_content_hashes: Iterable[str]) -> str:
    """Over the content hashes of the deliberation Segments in order. An empty
    chain is a valid chain (a soliloquy concluded without deliberating)."""
    return hash_fields(DELIBERATION_CHAIN_V2, [
        (UUID_, soliloquy_id), ((LIST, HASH), list(deliberation_content_hashes)),
    ])


def compute_soliloquy_conclusion_hash_v2(conclusion_id: UUID, soliloquy_id: UUID, parent_episode_id: UUID,
                                         deliberation_chain_hash: str, conclusion_summary: str,
                                         merged_into_segment_id: UUID, termination_status: str,
                                         concluded_at: datetime) -> str:
    return hash_fields(SOLILOQUY_CONCLUSION_V2, [
        (UUID_, conclusion_id), (UUID_, soliloquy_id), (UUID_, parent_episode_id), (HASH, deliberation_chain_hash),
        (STRING, conclusion_summary), (UUID_, merged_into_segment_id), (STRING, termination_status),
        (TIMESTAMP, concluded_at),
    ])


def compute_link_signal_hash_v2(signal_type: str, signal_weight: float, signal_value: float,
                                computed_at: datetime) -> str:
    return hash_fields(LINK_SIGNAL_V2, [
        (STRING, signal_type), (FLOAT, signal_weight), (FLOAT, signal_value), (TIMESTAMP, computed_at),
    ])


def compute_episode_link_hash_v2(link_id: UUID, source_episode: UUID, target_episode: UUID,
                                 source_episode_root: Optional[str], target_episode_root: Optional[str],
                                 created_at: datetime, link_type: str, link_strength: float, is_inferred: bool,
                                 inference_signal_hashes: Iterable[str], inference_threshold: Optional[float],
                                 retroactive: bool, source_version: Optional[str],
                                 target_version: Optional[str]) -> str:
    """``source_episode_root`` / ``target_episode_root`` are the Episode roots of
    the two ends at link creation, NULL for an end that was not sealed then. A
    sealed end with a NULL root is nonconformant: the link had the root available
    and declined to bind it. ``inference_signal_hashes`` are
    :func:`compute_link_signal_hash_v2` values in the order the signals were
    recorded (empty for a human-asserted link)."""
    return hash_fields(EPISODE_LINK_V2, [
        (UUID_, link_id), (UUID_, source_episode), (UUID_, target_episode),
        _opt(HASH, source_episode_root), _opt(HASH, target_episode_root),
        (TIMESTAMP, created_at), (STRING, link_type), (FLOAT, link_strength), (BOOL, is_inferred),
        ((LIST, HASH), list(inference_signal_hashes)), _opt(FLOAT, inference_threshold), (BOOL, retroactive),
        _opt(STRING, source_version), _opt(STRING, target_version),
    ])
