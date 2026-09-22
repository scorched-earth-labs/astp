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
Context-commitment constructions for SPEC 6.0.0 (§4.8, §4.9, §5.7.3, §5.7,
§5.8, G-41 … G-43), ratified in Episode of Record 80e5a2dd-3d9f-45d0-abfb-6489c8caf1b8
(design Episode ec31d0c0-50eb-4a2a-9f95-32536c9e645e; the amendment text is
retained at ``docs/history/SPEC-6.0.0-DRAFT-context-commitment.md``).
Every construction is new and versioned; seals made under
``spine_algorithm_version`` 0, 1 and 2 stay defined by ``astp.core.schema`` and
``astp.core.seal_v2`` and stay reproducible.

What 6.0.0 adds:

* **A context entry** (§4.8): one stored node per provision of external content
  to one agent — an attachment, a retrieval, an external fetch, a Layer 3 tool
  result — or per attempted provision whose content was not captured. Kind is a
  property (``entry_type``), not a node type.
* **A content commitment with two constructions and one sealed bit** (§4.8.3):
  plain, or salted with a per-entry CSPRNG salt kept in a namespace separate
  from the content. ``salted`` is in the entry preimage; the salt's pointer is
  not, so erasure can destroy the salt without moving a sealed preimage.
* **A context manifest** (§5.7.3): the version 2 Merkle tree over entry hashes
  in ascending bytewise order — a function of the *set*, so membership binds and
  insertion order does not, and one entry can be proven present without the
  others — bound with the Episode's sealed ``capture_posture`` (G-41).
* **Episode root version 3** (§5.7): the version 2 root with
  ``context_manifest_hash`` appended as its sixth field, selected by
  ``spine_algorithm_version`` 3 in the single §5.8 identifier. The spine root
  under 3 is byte-identical to 2; nothing is re-sealed.
* **Content-plane erasure** (G-43, §4.9): destroy content and salt atomically,
  append an ``ErasureTombstone`` as a §12.4.1 codicil, null the pointers, touch
  nothing else. The Episode root verifies identically before and after.

The governing invariant: **the seal proves history, not retention.**
"""

from datetime import datetime
from typing import Iterable, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from astp.protocol.encoding import BOOL, BYTES, HASH, STRING, TIMESTAMP, UINT, UUID_, hash_fields
from astp.protocol.merkle import InclusionProofV2, compute_merkle_root_v2, generate_inclusion_proof_v2, verify_inclusion_proof_v2
from astp.core.seal_v2 import (SegmentSealInput, compute_episode_seal_v2, compute_exclusion_hash_v2,
                               compute_signal_manifest_hash_v2, compute_structural_manifest_hash)

SPINE_ALGORITHM_VERSION_3 = 3      # SPEC §5.8: selects the entire seal construction, Episode root version 3 included
EPISODE_ROOT_VERSION_3 = 3

# ── domain prefix registry (SPEC §5.1.3, 6.0.0; none is a prefix of another) ──
CONTEXT_ENTRY_V1 = b"CONTEXT_ENTRY:v1:"
CONTEXT_CONTENT_V1 = b"CONTEXT_CONTENT:v1:"
CONTEXT_CONTENT_SALTED_V1 = b"CONTEXT_CONTENT_SALTED:v1:"
CONTEXT_MANIFEST_V1 = b"CONTEXT_MANIFEST:v1:"
EPISODE_ROOT_V3 = b"EPISODE_ROOT:v3:"
ERASURE_TOMBSTONE_V1 = b"ERASURE_TOMBSTONE:v1:"

# ── enumerations (SPEC §4.8, §5.7.3, §4.9) ─────────────────────────────────────────
ENTRY_TYPES = frozenset({"attachment", "retrieval", "external", "tool_output"})
CAPTURE_STATES = frozenset({"captured", "declared_incomplete"})
VERIFIABILITY_STATES = frozenset({"verifiable", "attested"})
CAPTURE_POSTURES = frozenset({"all_external", "declared_only", "none"})
ERASURE_STATES = frozenset({"present", "tombstoned"})
SALT_LENGTH = 32                   # SPEC §4.8.3: 32 bytes from a CSPRNG at write time

# The implementation-side classification that selects the construction (SPEC
# §4.9.1). The protocol names the value that MUST be salted and nothing else.
PII_LOW_ENTROPY = "low_entropy_personal"


class G41Violation(ValueError):
    """An Episode sealed under version 3 without a capture posture, or over an
    entry whose write did not complete as ``captured`` or ``declared_incomplete``."""


class G42Violation(ValueError):
    """A context entry classified as low-entropy personal data committed through
    the plain construction."""


class G43Violation(ValueError):
    """An erasure that would move a sealed preimage or leave content and salt in
    different states."""


# ── content commitment (§4.8.3) ─────────────────────────────────────────────

def compute_context_content_hash_v1(content: bytes, salt: Optional[bytes] = None) -> str:
    """``CONTEXT_CONTENT:v1:`` over the bytes as provided, or
    ``CONTEXT_CONTENT_SALTED:v1:`` over the salt and then the bytes. Which one
    was used is recorded by the entry's ``salted`` bit, which is sealed."""
    if salt is None:
        return hash_fields(CONTEXT_CONTENT_V1, [(BYTES, bytes(content))])
    if len(salt) != SALT_LENGTH:
        raise ValueError(f"salt must be {SALT_LENGTH} bytes")
    return hash_fields(CONTEXT_CONTENT_SALTED_V1, [(BYTES, bytes(salt)), (BYTES, bytes(content))])


# ── the entry and its hash (§4.8, §5.7.3) ───────────────────────────────────

class ContextEntryNode(BaseModel):
    """One provision of external content to one agent — or one attempted
    provision whose content was not captured (§4.8).

    The fields above the side-channel line are the entry's claims and are in
    its preimage (§6.1). ``source_ref``, ``content_ref``, ``salt_ref`` and
    ``erasure_state`` are provenance and content plane (§5.6): outside the
    preimage and outside every root, nulled or changed by erasure without
    moving a sealed claim. ``pii_classification`` is the implementation's
    write-time classification (§8.1); it selects the construction and is not
    a protocol field."""
    entry_id: UUID
    episode_id: UUID
    entry_type: str
    provided_to: str
    provided_at: datetime
    provided_before_sequence_index: Optional[int] = None
    capture_state: str = "captured"
    content_hash: Optional[str] = None
    salted: bool = False
    verifiability_at_seal: Optional[str] = None
    media_type: Optional[str] = None
    source_version_hash: Optional[str] = None
    resolves: Optional[UUID] = None
    schema_version: str = "6.0.0"

    # provenance and content plane — outside the preimage; §4.8.6
    source_ref: Optional[str] = None
    content_ref: Optional[str] = None
    salt_ref: Optional[str] = None
    erasure_state: str = "present"
    pii_classification: Optional[str] = None


def compute_context_entry_hash_v1(
    entry_id: UUID, episode_id: UUID, entry_type: str, provided_to: str, provided_at: datetime,
    provided_before_sequence_index: Optional[int], capture_state: str, content_hash: Optional[str], salted: bool,
    verifiability_at_seal: Optional[str], media_type: Optional[str], source_version_hash: Optional[str],
    resolves_entry_hash: Optional[str],
) -> str:
    """SPEC §5.7.3. Every field is recomputable from the stored node alone;
    ``resolves_entry_hash`` is the entry hash of the entry named by ``resolves``,
    or NULL. A declared-incomplete entry carries NULL content, ``salted`` false,
    NULL verifiability."""
    if entry_type not in ENTRY_TYPES:
        raise ValueError(f"unknown entry_type {entry_type!r}")
    if capture_state not in CAPTURE_STATES:
        raise ValueError(f"unknown capture_state {capture_state!r}")
    if capture_state == "declared_incomplete":
        if content_hash is not None or salted or verifiability_at_seal is not None:
            raise ValueError("a declared_incomplete entry has NULL content_hash, salted false and NULL verifiability_at_seal")
    else:
        if content_hash is None or verifiability_at_seal not in VERIFIABILITY_STATES:
            raise ValueError("a captured entry has a content_hash and a verifiability_at_seal of verifiable or attested")
    return hash_fields(CONTEXT_ENTRY_V1, [
        (UUID_, entry_id), (UUID_, episode_id), (STRING, entry_type),
        (STRING, provided_to), (TIMESTAMP, provided_at), (UINT, provided_before_sequence_index),
        (STRING, capture_state), (HASH, content_hash), (BOOL, salted),
        (STRING, verifiability_at_seal), (STRING, media_type),
        (HASH, source_version_hash), (HASH, resolves_entry_hash),
    ])


def context_entry_hash(entry: ContextEntryNode, resolves_entry_hash: Optional[str] = None) -> str:
    """The §6.1 hash of a stored entry. The caller supplies the hash of the
    entry it resolves (looked up by ``entry.resolves``), or nothing."""
    if (entry.resolves is None) != (resolves_entry_hash is None):
        raise ValueError("resolves and resolves_entry_hash are given together or not at all")
    return compute_context_entry_hash_v1(
        entry.entry_id, entry.episode_id, entry.entry_type, entry.provided_to, entry.provided_at,
        entry.provided_before_sequence_index, entry.capture_state, entry.content_hash, entry.salted,
        entry.verifiability_at_seal, entry.media_type, entry.source_version_hash, resolves_entry_hash,
    )


def context_entry_hashes(entries: Iterable[ContextEntryNode]) -> List[str]:
    """Entry hashes for a set of stored entries, resolving ``resolves`` within
    the set. Refuses a ``resolves`` that names an entry not in the set, or a
    resolving chain (an entry resolving an entry that itself resolves)."""
    by_id = {e.entry_id: e for e in entries}
    out = []
    for e in by_id.values():
        target_hash = None
        if e.resolves is not None:
            target = by_id.get(e.resolves)
            if target is None:
                raise ValueError(f"entry {e.entry_id} resolves {e.resolves}, which is not among the Episode's entries")
            if target.capture_state != "declared_incomplete" or target.resolves is not None:
                raise ValueError("an entry resolves exactly one declared_incomplete entry that resolves nothing")
            target_hash = context_entry_hash(target)
        out.append(context_entry_hash(e, target_hash))
    return out


# ── the manifest (§5.7.3) ─────────────────────────────────────────────

def sort_entry_hashes(entry_hashes: Iterable[str]) -> List[str]:
    """Canonical leaf order: ascending bytewise over the raw 32-byte values."""
    return [h.hex() for h in sorted(bytes.fromhex(x) for x in entry_hashes)]


def compute_context_tree_root_v1(entry_hashes: Iterable[str]) -> str:
    """The §5.4 version 2 tree over the entry hashes in canonical order.
    Undefined for zero entries (the manifest carries NULL there)."""
    leaves = sort_entry_hashes(entry_hashes)
    if not leaves:
        raise ValueError("the context tree is undefined for zero entries; the manifest carries NULL")
    return compute_merkle_root_v2(leaves)


def compute_context_manifest_hash_v1(capture_posture: str, entry_hashes: Iterable[str]) -> str:
    """``CONTEXT_MANIFEST:v1:`` ‖ STRING(posture) ‖ UINT(n) ‖ HASH|NULL(root).
    The posture is in the preimage so the field that governs how absence is
    read is sealed with the entries it governs."""
    if capture_posture not in CAPTURE_POSTURES:
        raise G41Violation(f"unknown capture_posture {capture_posture!r}")
    hashes = list(entry_hashes)
    root = compute_context_tree_root_v1(hashes) if hashes else None
    return hash_fields(CONTEXT_MANIFEST_V1, [(STRING, capture_posture), (UINT, len(hashes)), (HASH, root)])


# ── inclusion proofs over the manifest (§9.2) ──────────────────────────────

class ContextInclusionProofV1(BaseModel):
    """The §9.2 proof over the context tree. ``leaf_index`` is the entry's
    position in the sorted leaf list and carries no meaning beyond the proof.
    From ``context_tree_root``, the manifest hash follows from the posture and
    the count, and the Episode root from the manifest hash."""
    leaf_index: int
    leaf_count: int
    entry_hash: str
    siblings: List[str]
    context_tree_root: str


def generate_context_inclusion_proof_v1(entry_hashes: Iterable[str], entry_hash: str) -> ContextInclusionProofV1:
    leaves = sort_entry_hashes(entry_hashes)
    if entry_hash not in leaves:
        raise ValueError("entry_hash is not a member of the manifest")
    p = generate_inclusion_proof_v2(leaves, leaves.index(entry_hash))
    return ContextInclusionProofV1(leaf_index=p.leaf_index, leaf_count=p.leaf_count, entry_hash=p.leaf_hash,
                                   siblings=p.siblings, context_tree_root=p.spine_root)


def verify_context_inclusion_proof_v1(proof: ContextInclusionProofV1, capture_posture: str, entry_count: int,
                                      context_manifest_hash: str) -> bool:
    """True when the proof reproduces ``context_tree_root`` and that root, with
    the stated posture and count, reproduces ``context_manifest_hash``."""
    inner = InclusionProofV2(leaf_index=proof.leaf_index, leaf_count=proof.leaf_count, leaf_hash=proof.entry_hash,
                             siblings=proof.siblings, spine_root=proof.context_tree_root)
    if not verify_inclusion_proof_v2(inner) or entry_count < 1:
        return False
    want = hash_fields(CONTEXT_MANIFEST_V1, [(STRING, capture_posture), (UINT, entry_count), (HASH, proof.context_tree_root)])
    return want == context_manifest_hash


# ── Episode root version 3 (§5.7) ───────────────────────────────────────────

def compute_episode_root_hash_v3(episode_id: UUID, spine_root: str, signal_manifest_hash: str,
                                 structural_manifest_hash: str, exclusion_hash: str, context_manifest_hash: str) -> str:
    """The version 2 root's five fields unchanged, then ``context_manifest_hash``."""
    return hash_fields(EPISODE_ROOT_V3, [
        (UUID_, episode_id), (HASH, spine_root), (HASH, signal_manifest_hash),
        (HASH, structural_manifest_hash), (HASH, exclusion_hash), (HASH, context_manifest_hash),
    ])


class SealV3(BaseModel):
    """A version 3 seal and the identifiers that name its construction. The
    first five roots are exactly what a version 2 seal of the same Episode
    would carry (§5.7; CM-010)."""
    episode_id: UUID
    spine_root: str
    signal_manifest_hash: str
    structural_manifest_hash: str
    exclusion_hash: str
    context_manifest_hash: str
    capture_posture: str
    context_entry_count: int
    episode_root_hash: str
    leaf_count: int
    spine_algorithm_version: int = SPINE_ALGORITHM_VERSION_3
    ordering_version: int = 2
    hash_version: int = 2


def check_context_entries_sealable(entries: Iterable[ContextEntryNode]) -> None:
    """G-41 and G-42 at the seal: every entry completed as ``captured`` or
    ``declared_incomplete`` (an undeclared gap blocks the seal), and no entry
    classified low-entropy personal data committed plain."""
    for e in entries:
        if e.capture_state not in CAPTURE_STATES:
            raise G41Violation(f"entry {e.entry_id}: write did not complete ({e.capture_state!r}); the seal is blocked")
        if e.pii_classification == PII_LOW_ENTROPY and e.capture_state == "captured" and not e.salted:
            raise G42Violation(f"entry {e.entry_id}: low-entropy personal data committed through the plain construction")


def compute_episode_seal_v3(
    episode_id: UUID,
    segments: Iterable[SegmentSealInput],
    *,
    capture_posture: str,
    context_entries: Iterable[ContextEntryNode] = (),
    signal_content_hashes: Iterable[str] = (),
    excluded_content_hashes: Iterable[str] = (),
    structural_member_hashes: Iterable[str] = (),
) -> SealV3:
    """Seal an Episode under ``spine_algorithm_version`` 3 from stored fields.
    The spine, signal manifest, structural manifest and exclusion set are the
    version 2 computations; the context manifest is added and the root is
    version 3. ``capture_posture`` is required (G-41)."""
    if capture_posture not in CAPTURE_POSTURES:
        raise G41Violation("an Episode sealed under version 3 MUST carry a capture_posture")
    entries = list(context_entries)
    check_context_entries_sealable(entries)
    v2 = compute_episode_seal_v2(episode_id, segments, signal_content_hashes=signal_content_hashes,
                                 excluded_content_hashes=excluded_content_hashes,
                                 structural_member_hashes=structural_member_hashes)
    hashes = context_entry_hashes(entries)
    cm = compute_context_manifest_hash_v1(capture_posture, hashes)
    return SealV3(
        episode_id=episode_id, spine_root=v2.spine_root, signal_manifest_hash=v2.signal_manifest_hash,
        structural_manifest_hash=v2.structural_manifest_hash, exclusion_hash=v2.exclusion_hash,
        context_manifest_hash=cm, capture_posture=capture_posture, context_entry_count=len(hashes),
        episode_root_hash=compute_episode_root_hash_v3(episode_id, v2.spine_root, v2.signal_manifest_hash,
                                                       v2.structural_manifest_hash, v2.exclusion_hash, cm),
        leaf_count=v2.leaf_count,
    )


def reproduce_episode_root_v3(*, episode_id: UUID, spine_root: str, signal_content_hashes: Iterable[str],
                              excluded_content_hashes: Iterable[str], structural_member_hashes: Iterable[str],
                              capture_posture: str, context_entry_hashes: Iterable[str]) -> str:
    """Recompute a version 3 Episode root from stored state alone (§9.3
    extended to the sixth field)."""
    return compute_episode_root_hash_v3(
        episode_id, spine_root, compute_signal_manifest_hash_v2(signal_content_hashes),
        compute_structural_manifest_hash(structural_member_hashes), compute_exclusion_hash_v2(excluded_content_hashes),
        compute_context_manifest_hash_v1(capture_posture, context_entry_hashes))


# ── erasure (§4.9.2, §4.9.3; G-43) ────────────────────────────────────────────

class ErasureTombstone(BaseModel):
    """The content of a ``CodicilNode`` appended by ``CODICIL_APPEND`` to witness
    the erasure of a context entry's content. ``entry_hash`` is the erased
    entry's §6.1 hash, which erasure does not change."""
    tombstone_id: UUID
    episode_id: UUID
    entry_id: UUID
    entry_hash: str
    erased_at: datetime
    erasure_authority: str
    erasure_request_id: str
    erased_by: str


def compute_erasure_tombstone_hash_v1(tombstone_id: UUID, episode_id: UUID, entry_id: UUID, entry_hash: str,
                                      erased_at: datetime, erasure_authority: str, erasure_request_id: str,
                                      erased_by: str) -> str:
    return hash_fields(ERASURE_TOMBSTONE_V1, [
        (UUID_, tombstone_id), (UUID_, episode_id), (UUID_, entry_id), (HASH, entry_hash),
        (TIMESTAMP, erased_at), (STRING, erasure_authority), (STRING, erasure_request_id), (STRING, erased_by),
    ])


def tombstone_hash(t: ErasureTombstone) -> str:
    return compute_erasure_tombstone_hash_v1(t.tombstone_id, t.episode_id, t.entry_id, t.entry_hash, t.erased_at,
                                             t.erasure_authority, t.erasure_request_id, t.erased_by)


def apply_erasure(entry: ContextEntryNode, tombstone: ErasureTombstone) -> ContextEntryNode:
    """The stored-node half of the §8.2 operation, after the content at
    ``content_ref`` and the salt at ``salt_ref`` have been destroyed together:
    null both pointers, set ``erasure_state``, touch nothing else. The tombstone
    MUST name this entry by identity and by its unchanged hash. The destruction
    itself is the deployment's, outside this package."""
    if tombstone.entry_id != entry.entry_id or tombstone.episode_id != entry.episode_id:
        raise G43Violation("the tombstone does not name this entry")
    if entry.erasure_state == "tombstoned":
        raise G43Violation("the entry is already tombstoned")
    erased = entry.model_copy(update={"content_ref": None, "salt_ref": None, "erasure_state": "tombstoned"})
    for f in ("content_hash", "salted", "verifiability_at_seal"):
        if getattr(erased, f) != getattr(entry, f):
            raise G43Violation(f"erasure would change {f}")
    return erased
