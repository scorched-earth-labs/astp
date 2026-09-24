"""live_spine_root: the version 2 spine root of a live Episode (SPEC §5.7.1).

A BranchPoint binds ``spine_merkle_snapshot`` — "the history it left from" —
as a non-nullable HASH in its version 2 member. Before 2.2.0 it was read from
the Episode's stored spine hash, which does not exist until the seal, so every
branch of a live Episode stored "" and the Episode could not seal under
version 2 or 3 ("HASH field requires a 32-byte value"). The snapshot is now the
root the seal would compute over the same Segments.
"""

import hashlib
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from astp.adapters.memory import InMemoryStore
from astp.core import branch_operations
from astp.core.branch_operations import live_spine_root
from astp.core.branching import BranchDeclarationType, BranchType, TriggerType
from astp.core.seal_v2 import (
    compute_branch_point_hash_v2,
    compute_episode_seal_v2,
    spine_leaf_hashes_v2,
)


def _store(n_segments=5, ephemeral=()):
    store = InMemoryStore()
    eid = str(uuid4())
    store.episodes[eid] = {"episode_id": eid, "episode_status": "ACTIVE"}
    seg_ids = []
    for i in range(n_segments):
        sid = str(uuid4())
        store.segments[sid] = {
            "segment_id": sid, "episode_id": eid, "sequence_index": i,
            "content_hash": hashlib.sha3_256(f"{eid}:{i}".encode()).hexdigest(),
            "retention_tier": "EPHEMERAL" if i in ephemeral else "PERSISTENT",
        }
        seg_ids.append(sid)
    return store, eid, seg_ids


def test_whole_episode_root_is_the_seal_spine_root():
    """The invariant the snapshot rests on: taken now, it is what the seal computes."""
    store, eid, _ = _store(7, ephemeral={3})
    seal = compute_episode_seal_v2(UUID(eid), store.spine_segments(eid))
    assert live_spine_root(store, eid) == seal.spine_root


def test_through_segment_is_the_root_of_the_prefix():
    store, eid, seg_ids = _store(6)
    k = 3
    prefix = [s for s in store.spine_segments(eid) if s.sequence_index <= k]
    expected = compute_episode_seal_v2(UUID(eid), prefix).spine_root
    assert live_spine_root(store, eid, seg_ids[k]) == expected
    assert live_spine_root(store, eid, seg_ids[k]) != live_spine_root(store, eid)


def test_ephemeral_segments_are_not_leaves():
    store, eid, _ = _store(4, ephemeral={1})
    assert [s.sequence_index for s in store.spine_segments(eid)] == [0, 2, 3]
    assert len(spine_leaf_hashes_v2(store.spine_segments(eid))) == 3


def test_no_leaf_or_unknown_segment_is_none():
    store, eid, _ = _store(0)
    assert live_spine_root(store, eid) is None
    store2, eid2, _ = _store(2)
    assert live_spine_root(store2, eid2, str(uuid4())) is None


def test_spine_segments_parent_is_the_episode():
    store, eid, _ = _store(2)
    assert all(s.parent_node_id == UUID(eid) for s in store.spine_segments(eid))


def test_create_branch_binds_a_real_snapshot_and_its_v2_member_hashes():
    """End to end: the v2 member hash raised on the "" snapshot before 2.2.0."""
    store, eid, seg_ids = _store(5)
    source = seg_ids[2]
    result = branch_operations.create_branch(
        store, eid, source, "Topic shift detected",
        declaration_type=BranchDeclarationType.INFERRED,
        branch_type=BranchType.TOPIC_SHIFT,
        trigger=TriggerType.AGENT_DETECTED,
        initiator="ignis",
    )
    assert result is not None
    bp = next(iter(store.branch_points.values()))
    snap = bp["spine_merkle_snapshot"]
    assert len(snap) == 64 and snap == live_spine_root(store, eid, source)

    member = compute_branch_point_hash_v2(
        UUID(bp["branch_point_id"]), UUID(bp["episode_id"]), UUID(bp["branch_id"]), UUID(bp["source_segment_id"]),
        snap, bp["branch_type"], bp["declaration_type"],
        datetime.fromisoformat(bp["timestamp_utc"]).astimezone(timezone.utc), None,
    )
    assert len(member) == 64


def test_empty_snapshot_is_what_the_v2_member_refuses():
    """Pins the failure this release removes, so the reason stays documented."""
    with pytest.raises(ValueError, match="32-byte"):
        compute_branch_point_hash_v2(uuid4(), uuid4(), uuid4(), uuid4(), "", "topic_shift", "inferred",
                                     datetime.now(timezone.utc), None)
