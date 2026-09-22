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
Context-commitment operations over a ``StructuralStore`` (SPEC 6.0.0 §4.8,
§4.9, §5.7.3; G-41 … G-43).

Three operations and two seal-time readers:

* :func:`commit_context_entry` — write one context entry (``CONTEXT_COMMIT``,
  §12.4.1). G-42 is enforced here: an entry the implementation classified as
  low-entropy personal data and committed plain is refused. ``resolves`` must
  name a declared-incomplete entry of the same Episode.
* :func:`set_capture_posture` — record the posture the seal will bind (G-41).
* :func:`erase_context_entry` — the stored-node half of §4.9.2 after the
  deployment has destroyed the content and the salt: build the
  ``ErasureTombstone``, store it as a codicil (``CODICIL_APPEND``), null the
  pointers, touch nothing else (G-43).
* :func:`context_seal_inputs` — the posture and the entries a version 3 seal
  reads, with G-41 applied; :func:`episode_context_manifest_hash` composes
  the manifest from them.

The store never holds content or salts. What a deployment keeps behind
``content_ref`` and ``salt_ref``, and how it destroys it atomically, is its
own; this module records what the protocol records.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple
from uuid import UUID, uuid4

from pydantic import BaseModel

from astp.adapters.base import as_structural_store
from astp.core.context_v1 import (CAPTURE_POSTURES, G41Violation, G42Violation, G43Violation, PII_LOW_ENTROPY,
                                  ContextEntryNode, ErasureTombstone, apply_erasure, check_context_entries_sealable,
                                  compute_context_manifest_hash_v1, context_entry_hash, context_entry_hashes,
                                  tombstone_hash)
from astp.core.schema import ASTP_SCHEMA_VERSION, CodicilNode
from astp.core.wil import WILOperation
from astp.protocol.hashing import sha3_256

logger = logging.getLogger(__name__)

# An Episode in one of these states admits no further provision to an agent's
# context: its content is closed and its seal either made or pending.
NO_PROVISION_STATES = frozenset({"CLOSED", "CRYSTALLIZATION_PENDING", "CRYSTALLIZED", "SEALING", "SEALED", "ARCHIVED"})


class ContextOperationError(ValueError):
    """A context operation refused for a reason other than a governance rule."""


class ContextCommitResult(BaseModel):
    entry_id: UUID
    episode_id: UUID
    entry_hash: str
    wil_intent_id: UUID


class ErasureResult(BaseModel):
    entry_id: UUID
    episode_id: UUID
    entry_hash: str                 # unchanged by erasure
    tombstone: ErasureTombstone
    tombstone_hash: str
    codicil_id: UUID
    wil_intent_id: UUID


def _ledger(store, operation: WILOperation, episode_id: str, node_id: str) -> UUID:
    """One COMPLETE ledger entry for a write that has happened (G-39). A
    ledger entry that cannot be written fails the operation that needed it."""
    intent_id = uuid4()
    store.write_completed_wil_entry(intent_id=str(intent_id), operation=WILOperation(operation).value,
                                    episode_id=episode_id, node_id=node_id,
                                    timestamp=datetime.now(timezone.utc).isoformat())
    return intent_id


def _entry_from_stored(d: dict) -> ContextEntryNode:
    return ContextEntryNode(**d)


def _resolved_hash(store, entry: ContextEntryNode) -> Optional[str]:
    """The hash of the declared-incomplete entry ``entry.resolves`` names, or
    None. Refuses a target outside the Episode, a captured target, or a
    target that itself resolves (§4.8.5)."""
    if entry.resolves is None:
        return None
    target = store.context_entry(str(entry.resolves))
    if target is None or target["episode_id"] != str(entry.episode_id):
        raise ContextOperationError(f"entry resolves {entry.resolves}, which is not a context entry of Episode {entry.episode_id}")
    t = _entry_from_stored(target)
    if t.capture_state != "declared_incomplete" or t.resolves is not None:
        raise ContextOperationError("an entry resolves exactly one declared_incomplete entry that resolves nothing")
    return context_entry_hash(t)


def commit_context_entry(store: Any, entry: ContextEntryNode) -> ContextCommitResult:
    """Write a context entry and ledger it as ``CONTEXT_COMMIT``.

    Refuses: an Episode that does not exist or admits no further provision
    (:data:`NO_PROVISION_STATES`); a duplicate ``entry_id``; an entry whose
    fields do not hash (a captured entry without a content hash, a
    declared-incomplete one with content); a bad ``resolves``; and — G-42 —
    low-entropy personal data committed through the plain construction.
    """
    store = as_structural_store(store)
    episode_id = str(entry.episode_id)
    status = store.episode_status(episode_id)
    if status is None:
        raise ContextOperationError(f"Episode {episode_id} does not exist")
    if status in NO_PROVISION_STATES:
        raise ContextOperationError(f"Episode {episode_id} is {status}: no further content can be provided to an agent in it")
    if store.context_entry(str(entry.entry_id)) is not None:
        raise ContextOperationError(f"context entry {entry.entry_id} already exists: entries are append-only")
    if entry.erasure_state != "present":
        raise ContextOperationError("a new entry is written present; erasure is a later operation (§4.9)")
    if entry.pii_classification == PII_LOW_ENTROPY and entry.capture_state == "captured" and not entry.salted:
        raise G42Violation(f"entry {entry.entry_id}: low-entropy personal data committed through the plain construction")
    entry_hash = context_entry_hash(entry, _resolved_hash(store, entry))   # validates the field shape (§5.7.3)
    store.write_context_entry(entry)
    intent = _ledger(store, WILOperation.CONTEXT_COMMIT, episode_id, str(entry.entry_id))
    logger.info(f"context entry committed: {str(entry.entry_id)[:8]}… {entry.entry_type} for {entry.provided_to} in {episode_id[:8]}…")
    return ContextCommitResult(entry_id=entry.entry_id, episode_id=entry.episode_id, entry_hash=entry_hash, wil_intent_id=intent)


def set_capture_posture(store: Any, episode_id: str, posture: str) -> None:
    """Record the posture the seal binds (§5.7.3, G-41). Refused on a sealed
    Episode: the posture is in the manifest preimage and cannot change after."""
    store = as_structural_store(store)
    if posture not in CAPTURE_POSTURES:
        raise G41Violation(f"unknown capture_posture {posture!r}; one of {sorted(CAPTURE_POSTURES)}")
    status = store.episode_status(episode_id)
    if status is None:
        raise ContextOperationError(f"Episode {episode_id} does not exist")
    if status in ("CRYSTALLIZED", "SEALED", "ARCHIVED"):
        raise G41Violation(f"Episode {episode_id} is {status}: its posture is sealed and cannot change")
    store.set_capture_posture(episode_id, posture)


def context_seal_inputs(store: Any, episode_id: str) -> Tuple[str, List[ContextEntryNode]]:
    """The posture and the entries a version 3 seal reads, G-41 applied: a
    posture must have been set, and every entry must have completed as
    ``captured`` or ``declared_incomplete``. G-42 is re-checked at the seal
    (``check_context_entries_sealable``) so a plain low-entropy entry that
    reached the store by another path still blocks the seal."""
    store = as_structural_store(store)
    posture = store.capture_posture(episode_id)
    if posture is None:
        raise G41Violation(f"Episode {episode_id} has no capture_posture: a version 3 seal MUST carry one")
    entries = [_entry_from_stored(d) for d in store.context_entries_of(episode_id)]
    check_context_entries_sealable(entries)
    return posture, entries


def episode_context_manifest_hash(store: Any, episode_id: str) -> str:
    """The Episode's ``context_manifest_hash`` from stored state alone (§9.3)."""
    posture, entries = context_seal_inputs(store, episode_id)
    return compute_context_manifest_hash_v1(posture, context_entry_hashes(entries))


def erase_context_entry(
    store: Any,
    entry_id: str,
    *,
    erasure_authority: str,
    erasure_request_id: str,
    erased_by: str,
    content_and_salt_destroyed: bool,
    erased_at: Optional[datetime] = None,
    tombstone_id: Optional[UUID] = None,
    codicil_id: Optional[UUID] = None,
) -> ErasureResult:
    """The stored-node half of §4.9.2, after the deployment has destroyed the
    content at ``content_ref`` and the salt at ``salt_ref`` atomically.

    ``content_and_salt_destroyed`` is the caller's assertion that steps 1–2
    happened; the store cannot perform them and refuses to record an erasure
    nobody claims to have done. Builds the ``ErasureTombstone`` over the
    entry's unchanged hash, stores it as a ``CodicilNode`` (``CODICIL_APPEND``),
    nulls the two pointers and sets ``erasure_state``; every sealed value is
    untouched (G-43). Refused on an entry already tombstoned.
    """
    store = as_structural_store(store)
    if not content_and_salt_destroyed:
        raise G43Violation("erasure is recorded only after content and salt were destroyed together (§4.9.2 steps 1–2)")
    stored = store.context_entry(entry_id)
    if stored is None:
        raise ContextOperationError(f"context entry {entry_id} does not exist")
    entry = _entry_from_stored(stored)
    if entry.erasure_state == "tombstoned":
        raise G43Violation(f"context entry {entry_id} is already tombstoned")
    entry_hash = context_entry_hash(entry, _resolved_hash(store, entry))
    tomb = ErasureTombstone(tombstone_id=tombstone_id or uuid4(), episode_id=entry.episode_id, entry_id=entry.entry_id,
                            entry_hash=entry_hash, erased_at=erased_at or datetime.now(timezone.utc),
                            erasure_authority=erasure_authority, erasure_request_id=erasure_request_id, erased_by=erased_by)
    erased = apply_erasure(entry, tomb)                     # G-43: the only fields that move are the side-channel three
    assert context_entry_hash(erased, _resolved_hash(store, erased)) == entry_hash
    content = json.dumps({"erasure_tombstone": json.loads(tomb.model_dump_json()), "tombstone_hash": tombstone_hash(tomb)},
                         sort_keys=True, separators=(",", ":"))
    codicil = CodicilNode(codicil_id=codicil_id or uuid4(), episode_id=entry.episode_id, author=erased_by,
                          content=content, content_hash=sha3_256(content.encode("utf-8")), schema_version=ASTP_SCHEMA_VERSION)
    store.tombstone_context_entry(entry_id, tomb, codicil)
    intent = _ledger(store, WILOperation.CODICIL_APPEND, str(entry.episode_id), str(codicil.codicil_id))
    logger.info(f"context entry erased: {entry_id[:8]}… tombstone {str(tomb.tombstone_id)[:8]}… ({erasure_authority})")
    return ErasureResult(entry_id=entry.entry_id, episode_id=entry.episode_id, entry_hash=entry_hash, tombstone=tomb,
                         tombstone_hash=tombstone_hash(tomb), codicil_id=codicil.codicil_id, wil_intent_id=intent)
