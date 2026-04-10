# Ariadne State Tree Protocol Specification

**Version:** 2.1.0-draft
**Status:** Working Draft — Phase 1 Implemented, Coordination Protocol Added
**Authors:** Scorched Earth Labs
**Date:** 2026-04-10
**Supersedes:** SPEC-v1.md (0.1.0-draft)

## 1. Abstract

Ariadne is a cognitive persistence protocol for multi-agent AI systems. It provides a standardized, verifiable record of agent state transitions — what agents did, what state resulted, and cryptographic proof that the record hasn't been tampered with.

The protocol is agnostic to both cognitive architecture and node type. A system using BDI, ReAct, chain-of-thought, SOAR, or any other reasoning model can implement Ariadne without inheriting assumptions about how agents think. Ariadne records *that* agents reasoned and *what* resulted — not *how* they reasoned.

**v2 core change:** The protocol primitive is `CognitiveNode`, not `Episode`. Episodes are the first *parameterization* of the protocol, not a precondition of it. Future node types (signals, agents, artifacts) slot into the same framework with zero protocol-layer changes.

## 2. Terminology

| Term | Definition |
|------|-----------|
| **CognitiveNode** | The universal protocol primitive. All cognitive state is represented as CognitiveNodes with type-specific payloads. |
| **NodePayload** | Abstract interface for node-type-specific data. The protocol calls `validate()` and `to_content_hash_input()` — never inspects internals. |
| **Episode** | A bounded unit of agent work. The Phase 1 node type. Implemented as `CognitiveNode` with `node_type="episode"` and `EpisodePayload`. |
| **Segment** | An ordered, immutable content unit within an episode. |
| **Spine** | The ordered hash chain of leaf hashes within a cognitive node tree. The Merkle root of the spine is the node's integrity fingerprint. |
| **Seal** | A cryptographic commitment that freezes a cognitive node. |
| **Crystallization** | A protocol-level state transition that captures a point-in-time integrity snapshot. Immutable once written. |
| **WIL** | Write Intent Log. A coordination protocol for multi-store writes that guarantees ordering and recoverability. |
| **Dual Index** | The separation of `sequence_index` (immutable temporal position, in hash) from `tree_leaf_index` (mutable structural position, NOT in hash). The epistemological core of v2. |
| **Adapter** | A database-specific implementation of persistence operations. |
| **ASI** | Adapter Service Interface. The abstract contract any conforming adapter must implement. |
| **Governance Rule** | A protocol invariant that any conforming implementation must enforce. |
| **Namespace Firewall** | The inviolable rule that the protocol layer (`ariadne.protocol.*`) never imports from node-type layers (`ariadne.nodes.*`). |

## 3. Architecture

### 3.1 The Three-Layer Model

```
PROTOCOL LAYER — Node-Generic (ariadne.protocol.*)
  CognitiveNode, CognitiveEdge, NodePayload ABC
  Position-binding leaf hash, Merkle tree, delta records, audit chain
  Governance rules, verification, version vectors
  → No Episode symbols. No episode_id. No session_bounds.

INSTANTIATION LAYER — Node Type Registry
  NodeTypeDefinition, open enum registration
  "episode" ← Phase 1    "signal" ← Phase 2    "agent" ← Phase 2

NODE TYPE LAYER — Type-Specific Extensions (ariadne.nodes.*)
  EpisodePayload implements NodePayload
  Episode lifecycle state machine
  → Dependency: Node Type Layer → Protocol Layer only. Never reverse.
```

### 3.2 The Namespace Firewall

The protocol layer MUST NOT import from any node-type layer. This boundary is enforced by automated testing (AST scan of all protocol-layer imports). Violations are CI failures, not warnings.

### 3.3 The Dual-Index Invariant

| Index | Type | Mutability | Meaning | In Hash Preimage |
|-------|------|-----------|---------|-----------------|
| `sequence_index` | `int` | **Immutable** | Nth cognitive event in this context | Yes |
| `tree_leaf_index` | `int` | Mutable | Current physical position in Merkle tree | **No** |

This separation enables tree rebalancing without breaking integrity. Changing `sequence_index` is equivalent to rewriting history — it is a protocol violation. Changing `tree_leaf_index` is a structural optimization with no integrity impact.

## 4. Data Model

### 4.1 CognitiveNode

The universal protocol primitive.

```
CognitiveNode {
  node_id:          UUID         (unique, immutable)
  node_type:        string       (open enum, validated via registry)
  schema_version:   string       ("2.0.0")
  sequence_index:   int          (IMMUTABLE — cognitive timeline position)
  tree_leaf_index:  int          (mutable — physical Merkle position)
  content_hash:     string       (SHA3-256 of payload)
  authored_by:      string       (agent identity)
  created_at:       datetime     (UTC)
  sealed_at:        datetime?    (null = unsealed)
  parent_node_id:   UUID?        (graph position anchor, IMMUTABLE)
  payload:          dict         (serialized NodePayload)
  leaf_hash:        string?      (computed once at creation, cached)
}
```

### 4.2 CognitiveEdge

A typed, directed edge between cognitive nodes.

```
CognitiveEdge {
  edge_id:          UUID
  edge_type:        string
  source_node_id:   UUID
  target_node_id:   UUID
  source_type:      string
  target_type:      string
  weight:           float
  created_at:       datetime
}
```

### 4.3 NodePayload Interface

Protocol code interacts with payloads through three methods only:

- `validate() -> None` — check type-specific invariants
- `to_content_hash_input() -> bytes` — deterministic byte representation
- `to_dict() -> dict` — serialization for storage

The protocol MUST NOT inspect payload fields directly.

### 4.4 Episode (Phase 1 Node Type)

`EpisodePayload` implements `NodePayload` with fields: title, context_note, episode_type, episode_mode, workspace_id, participants, segment_count, signal_reads.

Episode lifecycle states: ACTIVE, REBALANCING, SEALING, SEALED, SEALING_FAILED, REBALANCE_FAILED, ARCHIVED, EXPIRED.

## 5. Hash Chain

### 5.1 Hash Algorithm

All hashing uses **SHA3-256** (Keccak). No exceptions. This is a protocol-level commitment: changing the hash algorithm requires a major version bump.

### 5.2 Position-Binding Leaf Hash

The leaf hash preimage binds identity, type, position, content, temporal state, and graph position into a single commitment:

```
leaf_hash = SHA3-256(
  node_id                              (16 bytes, UUID)
  len(node_type).to_bytes(4, "big")    (4 bytes, length prefix)
  node_type                            (variable, UTF-8)
  len(schema_version).to_bytes(4, "big")  (4 bytes, length prefix)
  schema_version                       (variable, UTF-8)
  sequence_index.to_bytes(8, "big")    (8 bytes, big-endian)
  content_hash                         (32 bytes, hex-decoded)
  sealed_at_ms.to_bytes(8, "big")      (8 bytes, Unix ms or 0)
  parent_node_id                       (16 bytes, UUID or 16 zero bytes)
)
```

**Design rationale:**
- **Length prefixing** on variable fields prevents collision attacks (e.g., `("ep","2.0")` vs `("e","p2.0")`)
- **Unix milliseconds** for `sealed_at` avoids timezone/format non-determinism of ISO strings
- **`node_type` in preimage** makes type confusion cryptographically detectable
- **`tree_leaf_index` excluded** — the dual-index invariant requires it

The leaf hash is computed once at node creation and never recomputed.

### 5.3 Domain Separation

To prevent second-preimage attacks across tree levels:
- Leaf level: `SHA3-256(b"LEAF:" + leaf_hash)`
- Internal nodes: `SHA3-256(b"NODE:" + left + right)`

### 5.4 Merkle Tree

A binary Merkle tree over domain-separated leaf hashes. Supports:
- Full construction from leaf set
- Incremental append (O(log n))
- Inclusion proof generation (P2 — position-binding)
- Inclusion proof verification

The tree is node-type-agnostic — it operates on hash strings only.

### 5.5 Type Isolation Property

A CognitiveNode with `node_type="episode"` and one with `node_type="signal"` at the same `sequence_index` produce **different leaf hashes** because `node_type` is in the preimage.

## 6. Governance Rules

These invariants MUST be enforced by any conforming implementation.

### G-1: Write Guard

No modifications to sealed nodes. A node with non-null `sealed_at` is frozen.

### G-2: Reparenting Prohibition

`parent_node_id` is immutable after creation. Reparenting is a governance violation, not a valid operation. A node's parentage is a fact about its origin.

**Correction path:** Create a new node with correct parentage. Issue a deprecation record on the original. The original's hash and position remain permanently in the audit trail.

### G-3: Sequence Monotonicity

New `sequence_index` values must be strictly greater than the current maximum. Non-monotonic sequence indices indicate either a bug or an insertion attack.

### G-4: Logical Clock Monotonicity

Logical clock values must be strictly monotonically increasing across audit records. A decreasing clock indicates backdating — either tampering or out-of-order insertion.

### G-5: Node Type Registration

`node_type` must be registered in the `NodeTypeRegistry` before a node can be created. Unregistered types are rejected.

### G-6: Namespace Firewall

The protocol layer (`ariadne.protocol.*`) MUST NOT import from any node-type layer (`ariadne.nodes.*`). This is enforced by automated testing.

### G-7 through G-9: Signal Governance (inherited from v1)

- **G-7:** Causal signals require a TRIGGERED edge to at least one segment
- **G-8:** Exchange entries require a prior initiation_hash on the consultation node
- **G-9:** Consultation resolution requires at least one exchange entry

### G-10: Structural Delta Content Invariant

A structural delta (rebalancing) that sets `sequence_indices_unchanged: false` is an integrity violation. Rebalancing must never alter logical ordering.

## 7. Delta Records

Every state transition is recorded as a delta.

### 7.1 Content Delta

Records content mutations (segment appends, updates):
```
ContentDelta {
  delta_id, node_id, segment_id,
  sequence_index,                    (for verification)
  previous_content_hash, new_content_hash,
  pre_root, post_root,              (the CAS condition and result)
  wall_clock, logical_clock, author
}
```

### 7.2 Structural Delta

Records structural mutations (rebalancing):
```
StructuralDelta {
  delta_id, node_id, delta_type,
  sequence_indices_unchanged: bool,  (INVARIANT — must be true)
  pre_rebalance_root, post_rebalance_root,
  wall_clock, logical_clock, author
}
```

## 8. Tamper-Evident Audit Chain

The audit trail is a first-class data structure. Each `AuditRecord` includes `prev_audit_hash` — a chain link that makes the trail tamper-evident independently of the delta chain.

```
AuditRecord {
  record_id, node_id, delta_id, delta_type,
  actor, actor_role,
  wall_clock, logical_clock,
  pre_state_hash, post_state_hash,
  delta_hash,
  prev_audit_hash,                   ("GENESIS" for first record)
  reason
}
```

Tampering with any record breaks the chain at that point, detectable by any verifier replaying from genesis.

## 9. Verification

### 9.1 The Five-Test Gate

Any conforming implementation MUST detect all five classes of tampering:

| # | Attack | Detection Mechanism |
|---|--------|-------------------|
| 1 | Content tampering | `content_hash` changes → `leaf_hash` mismatch → root mismatch |
| 2 | Sequence index modification | `sequence_index` in leaf hash preimage → `leaf_hash` changes |
| 3 | Segment insertion/deletion | Leaf count changes → root mismatch; position gaps detected |
| 4 | Audit chain tampering | `prev_audit_hash` chain breaks at tampered record |
| 5 | Backdated wall_clock | Logical clock monotonicity violation |

A verifier catching only test 1 is a *content* integrity verifier. Tests 2-5 are required for *temporal* integrity. All five must pass.

### 9.2 Inclusion Proof (P2)

A position-binding Merkle inclusion proof proves a node exists at a specific position:

```
InclusionProof {
  sequence_index,           (the position claim)
  leaf_hash,                (content commitment — not content)
  merkle_path: Hash[],      (sibling hashes to root)
  path_directions: str[],   (left/right for each sibling)
  spine_root                (root being proven against)
}
```

Verifier recomputes domain-separated leaf hash, walks the Merkle path, confirms it reaches `spine_root`. Segment content is never revealed.

## 10. Agent-Directed Retrieval

A conforming adapter MUST implement three retrieval operations:

**get_segment_by_id** — single segment by ID, episode-scoped. Episode scoping MUST be enforced at the query level.

**get_segment_range** — contiguous range by sequence_index (inclusive). Supports filtering by segment_type and author. Returns ordered by sequence_index ASC.

**get_episode_spine** — most recent N segments. Supports before_index scoping, segment_type filter, retention_tier filter. Returns ordered by sequence_index ASC.

`content_text` MUST be returned verbatim — no truncation, summarization, or modification. The retrieval layer does not decide what content is relevant.

### 10.4 Snapshot Isolation

All retrieval operations within a single agent turn MUST read against a consistent spine snapshot, not live database state. This prevents parallel branches from observing divergent Episode content due to concurrent writes by other agents.

**Snapshot capture:** At the start of each agent turn, the system queries the current `max(sequence_index)` for the active Episode and pins all retrieval to that boundary. Segments written after the snapshot are invisible to that turn's retrieval calls.

**Snapshot lifecycle:**
1. Turn begins → capture `max_sequence_index` from the authoritative store
2. All retrieval tool calls within the turn pass `max_sequence_index` to the query layer
3. Query layer filters: only segments at or below the snapshot index are returned
4. Turn ends → snapshot is cleared; next turn captures a fresh snapshot

**Parallel branch guarantee:** If multiple agents or specialists execute in parallel (e.g., fan-out patterns), and all share the same snapshot boundary, they are guaranteed to reason from identical Episode context. Divergence between branches is task-driven, not memory-driven.

A conforming adapter MUST support `max_sequence_index` as an optional parameter on all three retrieval operations (`get_segment_by_id`, `get_segment_range`, `get_episode_spine`). When provided, results MUST be filtered to segments at or below that index.

**Snapshot capture function:** A conforming adapter MUST implement `get_spine_snapshot_index(episode_id) -> Optional[int]` which returns the current maximum `sequence_index` for an Episode, or None if no segments exist.

### 10.5 Tail Write Advisory

When an agent is actively writing segments to the Episode spine, other agents capturing snapshots during that write window may observe a partially-committed state. The tail write advisory is a coordination signal that protects snapshot capture.

**Protocol:**
1. Before writing segments to the authoritative store, the writing agent sets a tail write advisory for the Episode
2. Any agent capturing a spine snapshot checks the advisory; if active, the snapshot index is reduced by one (excluding the in-progress tail)
3. After the write completes (success or failure), the advisory is cleared

**Scope:** The advisory is a soft coordination signal, not a hard lock. It does not prevent writes or reads — it adjusts snapshot boundaries to avoid phantom reads of uncommitted segments.

**Implementation note:** The advisory is in-process state (not persisted to the ephemeral coordinator) when all agents run in the same process. Distributed deployments require the advisory to be stored in the ephemeral coordinator (e.g., Redis) with a short TTL as a safety bound.

### 10.6 HITL Re-Validation Gate

Write operations that require human-in-the-loop (HITL) approval introduce a temporal gap between when the action is requested and when it is executed. During this gap, the Episode spine may advance, making the approval context stale.

**Protocol:**
1. When a write capability requests HITL approval, the current `spine_snapshot_index` is stored in the approval request context
2. When the approved action is executed, the system queries the current `max(sequence_index)` for the Episode
3. If the spine has advanced beyond the stored snapshot index, the execution is rejected with a `stale_approval` error
4. The requesting agent must re-evaluate the action against current Episode state and re-request if still appropriate

**Rationale:** A stale approval is worse than a rejected one. An action approved based on Episode state at index 42 may be semantically incorrect at index 47 — five new segments may have introduced context that contradicts the action's premise. The re-validation gate surfaces this conflict rather than silently executing.

**Failure mode:** If the re-validation check itself fails (e.g., database unavailable), the system SHOULD log a warning and proceed with execution. The re-validation gate is a safety mechanism, not a hard blocker — availability takes precedence over stale-detection in degraded conditions.

## 11. Retrieval Side-Effect Contract

Retrieval operations MUST NOT modify the Episode spine. Retrieval is a read-only operation — no segment creation, no hash updates, no state transitions.

If an implementation adds access logging (e.g., `last_retrieved_at`, `retrieval_count` on segments), these fields MUST be stored as **side-channel data** explicitly excluded from `content_hash` and `leaf_hash` computation. A retrieval that updates an access counter must not invalidate the Merkle tree.

**The invariant:** A retrieval tool call, followed by a full Merkle verification, MUST produce the same result as the verification without the retrieval. Retrieval is observationally transparent to the integrity layer.

## 12. Write Intent Log (WIL)

### 12.1 Three Storage Invariants

1. **The ephemeral coordinator is not a persistent store.** Loss of coordinator state is recoverable from the authoritative store.
2. **Write ordering is a formal invariant.** Durable content store → authoritative structural store → ephemeral coordinator → semantic search index.
3. **Provisional state never enters persistent storage.**

### 12.2 Three-Phase Write Protocol

**Phase 1 — INTENT_DECLARED:** Create WIL entry with `completed_at=null`.
**Phase 2 — WRITE_EXECUTION:** Execute writes in mandatory order, recording each store completion.
**Phase 3 — COMPLETION:** Mark complete, graduate from ephemeral coordinator to durable store.

### 12.3 Ephemeral Coordinator TTL Policy

Every coordinator key MUST carry an explicit TTL. Keys without a TTL policy entry are a governance violation. Alternative coordinator implementations MUST define equivalent TTL policies.

## 13. Adapter Requirements

A conforming adapter MUST:

1. Implement the `AriadneAdapter` interface
2. Enforce all governance rules
3. Preserve hash chain integrity — never modify leaf_hash, spine_root, or content_hash after creation
4. Enforce the dual-index invariant: `tree_leaf_index` never in any hash preimage
5. Respect write ordering invariants across stores
6. Support idempotent writes for WIL recovery
7. Fail loudly on errors — never silently swallow writes

## 14. Conformance Testing

The `ariadne.protocol.verification` module provides the `DeltaVerifier` — the five-test gate that any conforming implementation must pass.

| Layer | Verifies |
|-------|----------|
| **Structural** | Hash chain integrity, leaf hash correctness, Merkle root consistency |
| **Temporal** | Sequence monotonicity, logical clock monotonicity, position-binding |
| **Audit** | Tamper-evident chain integrity, delta record consistency |

## 15. Version History

| Version | Date | Changes |
|---------|------|---------|
| 0.1.0-draft | 2026-04-07 | Initial extraction. Episode-centric. See SPEC-v1.md. |
| 2.0.0-draft | 2026-04-09 | CognitiveNode foundation. Dual-index. Position-binding leaf hash. Five-test gate. Namespace firewall. |
| 2.1.0-draft | 2026-04-10 | Retrieval coordination protocol: snapshot isolation (10.4), tail write advisory (10.5), HITL re-validation gate (10.6), side-effect contract (11). |

## 16. References

Internal Scorched Earth Labs design documents that informed the protocol:

| Reference | Decision |
|-----------|----------|
| v2 Synthesis | Position-binding, dual-index, delta records, proof system P1-P13 |
| Node-Generic Architecture (Revised) | CognitiveNode as primitive, namespace firewall, reparenting prohibition |
| CLO-CONSOLIDATED-1.1 | Phase 1 architecture synthesis |
| OQ-D01 | Write ordering and provisional state invariants |
| OQ-D02 | Crystallization as state transition |

---

*Ariadne Protocol is developed by Scorched Earth Labs.*
