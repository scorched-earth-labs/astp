# Ariadne State Tree Protocol Specification

**Version:** 3.2.0
**Status:** Stable. The Phase D departure-fork lifecycle (v3.2.0) is defined in-body at §19.3.5–19.3.6. v3.0 (cross-episode linking + grouping) and v3.1 (Layer 3 Workflow & Execution DAG) are normatively defined by their amendment documents until the SPEC integration pass folds them into this document's body. See [`AMENDMENT-v2.0-CROSS-EPISODE-LINKING.md`](./AMENDMENT-v2.0-CROSS-EPISODE-LINKING.md) and [`AMENDMENT-v3.0-WORKFLOW-EXECUTION-DAG.md`](./AMENDMENT-v3.0-WORKFLOW-EXECUTION-DAG.md). Amendment filenames retain their authoring numerals; under the canonical SPEC versioning policy ([`VERSIONING.md`](./VERSIONING.md)) they correspond to SPEC v3.0.0 and v3.1.0 respectively.
**Authors:** Scorched Earth Labs
**Date:** 2026-06-07
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
| **HITLEventNode** | A first-class node representing a human-in-the-loop decision gate. Two-phase lifecycle: INVOKED (gate raised) → RESOLVED/TIMED_OUT (decision recorded). Participates in the Merkle spine as a causal anchor. |
| **HITL Gate** | An edge from an Episode to an HITLEventNode. Typed as BLOCKS (approval required) or FOLLOWS (advisory review). |
| **Causal Anchor** | A Merkle spine leaf whose hash ancestry carries the authorization chain for subsequent segments. HITL nodes are causal anchors — post-approval segments cryptographically depend on the human decision. |
| **Adapter** | A database-specific implementation of persistence operations. |
| **ASI** | Adapter Service Interface. The abstract contract any conforming adapter must implement. |
| **Governance Rule** | A protocol invariant that any conforming implementation must enforce. |
| **Namespace Firewall** | The inviolable rule that the protocol layer (`ariadne.protocol.*`) never imports from node-type layers (`ariadne.nodes.*`). |
| **Protocol Surface** | The set of primitives, invariants, and interfaces where no differential is permitted across conforming implementations. |
| **Implementation Space** | Architectural choices where conforming implementations MAY differ (payload schemas, storage adapters, signing algorithms, etc.). |

### 2.5 Protocol vs. Implementation Boundary

Ariadne is a **protocol**, not an implementation. This distinction is load-bearing.

#### 2.5.1 The Differential Principle

A conforming Ariadne implementation may make architectural choices — about agent reasoning models, storage backends, key management infrastructure, payload schemas, and operational policies — that differ from other conforming implementations. These are **implementation differentials**: legitimate variation that the protocol explicitly accommodates.

The protocol surface is the set of primitives, invariants, and interfaces where no differential is permitted. Deviation from the protocol surface produces a non-conforming implementation that cannot interoperate with or be verified by other conforming implementations.

#### 2.5.2 Protocol Surface (Non-Negotiable)

| Element | Constraint |
|---------|-----------|
| `CognitiveNode` schema (core fields) | Fixed. Field names, types, and semantics are immutable within a major version. |
| `NodePayload` interface | `validate()` and `to_content_hash_input()` are the only protocol-layer calls. The protocol NEVER inspects payload internals. |
| Leaf hash construction | SHA3-256 with the position-binding preimage defined in Section 5.2. Concatenation order, length prefixing, and algorithm are fixed. |
| Spine Merkle algorithm | SHA3-256 binary Merkle tree with domain separation (LEAF:/NODE:) and deterministic leaf ordering by `sequence_index`. |
| `spine_root` semantics | The Merkle root of all domain-separated leaf hashes in `sequence_index` order. |
| `ContentDelta` / `StructuralDelta` structure | Core fields (`pre_root`, `post_root`, `delta_type`) are fixed. |
| Governance rules G-1 through G-16 | All conforming implementations enforce all protocol-mandatory governance rules. |
| Dual Index semantics | `sequence_index` is immutable and in the leaf hash. `tree_leaf_index` is mutable and NOT in the leaf hash. |
| Namespace Firewall | Protocol layer never imports from node-type layers. |

#### 2.5.3 Implementation Space (Differential-Permitted)

| Element | Permitted Variation |
|---------|-------------------|
| `NodePayload` schemas | Each node type defines its own payload schema. The protocol does not constrain payload content beyond the interface contract. |
| Storage adapter | Any conforming ASI implementation. |
| Key management infrastructure | HSM, KMS, software keystore, distributed threshold — implementation choice. |
| Signing algorithms | The protocol specifies the *data to be signed*; the signing algorithm is implementation-defined (subject to minimum security requirements). |
| Transparency log target | Abstract `TransparencyLogAdapter` interface. Implementations choose the log. |
| Counter-signature policy | `min_counter_signatures` is a workspace-level configuration, not a protocol invariant. |
| Logical clock implementation | The protocol requires monotonic logical timestamps; the clock mechanism is implementation-defined. |
| Agent identity representation | The protocol requires an `agent_id` string; the identity system behind it is implementation-defined. |
| Cognitive architecture | BDI, ReAct, chain-of-thought, SOAR, or any other model. The protocol records outcomes, not reasoning mechanics. |

#### 2.5.4 Cross-Architecture Interoperability Guarantee

Two conforming implementations from different AI architectures MUST be able to:

1. **Verify each other's proofs.** An `InclusionProof` generated by Implementation A is verifiable by Implementation B using only protocol surface primitives.
2. **Traverse cross-node chains.** A proof chain linking nodes across implementations is valid if each link satisfies the leaf hash and spine root constraints.
3. **Agree on node identity.** `node_id` is a stable, architecture-independent identifier.

Interoperability does NOT require that implementations can read each other's payload content — only that they can verify the integrity and provenance of the node structure.

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

### 3.4 The Persistence Layer Model

The protocol defines three **persistence layers** — distinct from the code-architecture layering of §3.1. Each persistence layer is a separate cryptographic surface, owned by a distinct authority, and isolated from the others' hash integrity:

| Layer | Contents | Owner | Hash Participation |
|-------|----------|-------|-------------------|
| **Layer 1 — Merkle Spine** | EpisodeNode, IntentionNode, BeliefNode, SignalNode, and other cognitive primitives | Protocol kernel | Hash-chained, witness-signable, authoritative cognitive record |
| **Layer 2 — Episode Content** | Segments, BranchPoints, HITLEventNodes; Adaptive Merkle Tree under the Spine | Protocol kernel | Anchored to Layer 1 via parent references |
| **Layer 3 — Workflow & Execution DAG** | WorkflowDeclaration, ExecutionNode, SkillInvocation | Cognitive Implementation Authority (per workspace, per node type — see Amendment v3.0 §3) | **Isolated**: Layer 3 nodes do NOT participate in Spine hash computation. Cross-layer references are by ID only. |

**Layer 3 was introduced by Amendment v3.0 — Workflow & Execution DAG Codification.** The full Layer 3 surface — node schemas, hash preimage rules, immutability invariants, state machine, sole-writer principle (Cognitive Implementation Authority), and audit event types (`WORKFLOW_DECLARED`, `EXECUTION_RECORDED`, `SKILL_INVOKED`, `WORKFLOW_CLOSED`) — is normatively specified in `AMENDMENT-v3.0-WORKFLOW-EXECUTION-DAG.md`. This section names Layer 3's existence and position in the persistence model; the amendment is the authoritative reference for its semantics.

The two three-layer models — code-architecture (§3.1) and persistence (§3.4) — are **orthogonal**. The code-architecture layering governs what can import what (Protocol → Instantiation → Node Type, never reverse). The persistence layering governs what participates in which cryptographic structure. A given node type (e.g., `WorkflowDeclaration`) sits in the Node Type code-architecture layer AND in Persistence Layer 3 simultaneously; the two memberships describe different properties.

#### 3.4.1 Segment parentage is upward (to the episode), never lateral (to a sibling)

A Segment is Layer 2 content anchored to its Layer 1 `EpisodeNode`: a segment's `parent_node_id` is the **episode's** `node_id`. Segments therefore fan out from their episode — one parent reference each — and their relative order is carried entirely by `sequence_index`, which is immutable, part of the leaf-hash preimage (§5.2), and the key the Merkle spine orders by (§5.4).

There is **no segment→segment parent edge**, and none is needed. A `parent_node_id` pointing at the *preceding* segment would (a) bind a sibling, not the node's origin, into the immutable leaf hash — making "ordering" a hash-committed claim that diverges from `sequence_index` after any out-of-order insert, repair, or rebalance; and (b) hard-code a single successor, which a branch or fork cannot honor (a segment may have more than one successor across branches). Ordering already lives, authoritatively and twice, in `sequence_index` (on the node, in the leaf hash) — a parent chain can only ever be a third, un-hashed copy that is redundant-when-right and wrong-when-divergent.

A conforming implementation materializes this as one ordered containment edge per segment — e.g. `(Episode)-[:CONTAINS {sequence_index}]->(Segment)` — i.e. an ordered fan-out, not a linked list. If an explicit next/prev adjacency is wanted (e.g. for a visualization), **derive it at read time** by ordering on `sequence_index`; do not persist it as authoritative state.

> **Do not confuse this with proof-chain parentage (§16.5.3).** The chain-verification rule `B.parent_node_id == A.node_id` links *distinct cognitive nodes* into a causal proof chain (e.g. episode→episode) and is a cross-node construct. It says nothing about how segments order *within* an episode. Within-episode order is `sequence_index`; cross-node causal order is parent/cross-reference. These are two different uses of `parent_node_id` — keep them separate.

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

### 4.5 Segment Metadata: signal_versions_read

Every segment carries an optional `signal_versions_read` field: a list of signal IDs that were visible in the Episode when the segment was written. This enables post-hoc stale-read detection — if a REASONING segment was written while referencing a signal that had already been superseded, the version mismatch is auditable after the fact.

`signal_versions_read` is **side-channel metadata**. It is NOT included in `content_hash` computation. The content hash covers only the segment's actual content; the signal version snapshot is recorded for audit purposes but does not affect integrity verification.

A conforming adapter SHOULD populate `signal_versions_read` at segment write time by querying current signal state for the Episode. Adapters MAY leave it empty if signal tracking is not supported.

### 4.6 HITLEventNode (Phase 4 — Human-in-the-Loop)

A first-class node type representing a human oversight decision within an episode. HITL events have a two-phase temporal structure — the gate is raised (INVOKED), a pending interval occurs, and the human resolves (RESOLVED/TIMED_OUT/ESCALATED).

```
HITLEventNode {
  hitl_event_id:          UUID         (unique, immutable)
  episode_id:             UUID
  hitl_request_id:        string       (FK to operational HITL store)
  schema_version:         string

  // Gate classification
  gate_type:              HITLGateType (APPROVAL_REQUIRED | REVIEW_ADVISORY | ESCALATION |
                                        COMPLIANCE_CHECKPOINT | MODIFICATION_REQUEST)
  status:                 HITLNodeStatus (INVOKED | RESOLVED | TIMED_OUT | ESCALATED)
  requesting_agent:       string

  // Phase 1 — Invocation (immutable after creation)
  invoked_at:             datetime (ms precision)
  timeout_at:             datetime?
  spine_snapshot_index:   int?         (spine state when gate was raised)

  // Phase 2 — Resolution (written on resolution)
  resolved_at:            datetime?
  decision:               HITLDecision (APPROVED | REJECTED | MODIFIED | DEFERRED | ESCALATED)
  resolved_by:            string?      (human principal identifier)
  rationale:              string?
  pending_duration_ms:    int?         (computed: resolved_at - invoked_at)

  // Integrity
  context_hash:           string       (SHA3-256 of invocation context)
  resolution_hash:        string?      (SHA3-256 of resolution payload)
  node_hash:              string?      (H(NODE: context_hash || resolution_hash))

  // Cryptographic attestation
  invocation_signature:   string?      (Ed25519 sig over context_hash, hex-encoded)
  invocation_key_fingerprint: string?  (SHA3-256 of agent public key)
  resolution_signature:   string?      (Ed25519 sig over resolution_hash, hex-encoded)
  resolution_key_fingerprint: string?  (SHA3-256 of human public key)
}
```

**Hash computation:**

- `context_hash = SHA3-256("HITL_CTX:" || request_id || episode_id || gate_type || agent || invoked_at || context_json)`
- `resolution_hash = SHA3-256("HITL_RES:" || event_id || decision || resolved_by || resolved_at || rationale)`
- `node_hash = SHA3-256("NODE:" || context_hash || resolution_hash)`

Domain separation prefixes (`HITL_CTX:`, `HITL_RES:`) prevent cross-type hash confusion.

**Two-layer signing model:**

1. **Agent invocation signature:** `Sign(agent_private_key, bytes.fromhex(context_hash))` — proves the agent created the gate.
2. **Human resolution signature:** `Sign(human_private_key, bytes.fromhex(resolution_hash))` — proves the human made the decision.

Both use the HKDF key hierarchy (§16.2) with `entity_type` parameter distinguishing agent from user key derivation paths.

**HITL_GATE edge:**

A directed edge from Episode to HITLEventNode with properties:
- `gate_type`: Classification of the HITL gate
- `blocking`: Boolean — whether the gate blocks episode progression
- `dependency`: `"BLOCKS"` (approval required) or `"FOLLOWS"` (advisory review)

**Spine participation:**

Resolved HITL `node_hash` values participate in the Merkle spine as causal anchor leaves with `importance=2` (high). The spine hash changes when a HITL event resolves — the human decision becomes part of the episode's integrity fingerprint.

**Crystallization guard:**

An episode in `PENDING_HITL` status (blocking HITL gate open) cannot be crystallized. `acquire_crystallization_lock()` queries for unresolved HITLEventNode nodes before acquiring the lock. This is a hard protocol invariant — an episode with an outstanding human decision is an open episode.

**Advisory gates and CONDITIONALLY_VALID:**

Segments written while a `REVIEW_ADVISORY` gate is pending are tagged with `pending_hitl_ref` (the HITLEventNode ID). These segments are `CONDITIONALLY_VALID` — included in the spine but with a governance caveat. The advisory gate does not block episode progression.

**HITLEventNode is the only node type that permits post-creation mutation** — but only during the INVOKED → RESOLVED transition. All other transitions are immutable. This exception is enforced by G-17.

**Timeout is a recorded event.** `TIMED_OUT` is a valid terminal status treated as implicit rejection. Orphaned pending decisions are not permitted — all HITL invocations must specify a timeout policy.

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

### G-11: Witness Threshold (Phase 3)

If a workspace declares `min_counter_signatures > 0` for a `node_type`, a node of that type MUST have at least that many valid `WitnessRecord` entries with distinct `witness_id` values before transitioning to SEALED state. The protocol does not mandate a default value — this is workspace-configured.

### G-12: Witness Commitment Integrity (Phase 3)

A `WitnessRecord` is invalid if `commitment_hash` does not match the computed `WitnessCommitment` over the record's fields. Invalid witness records MUST NOT count toward any threshold.

### G-13: Chain Root Integrity (Phase 3)

A `ProofChain` `chain_root` must equal `SHA3-256` of the concatenated `spine_root` values of all links in order. A chain with an incorrect `chain_root` is invalid regardless of individual link validity.

### G-14: Transparency Log Anchoring Timing (Phase 3)

Transparency log anchoring MUST occur at crystallization. Anchoring at other times is permitted but does not satisfy G-14.

### G-15: Key Version Monotonicity (Phase 3)

`NodeKeyRecord.key_version` MUST be monotonically non-decreasing for a given `node_id`. Key version rollback is a governance violation.

### G-16: Node Type in Key Derivation (Phase 3)

The HKDF `info` string for node key derivation MUST include `node_type`. Keys derived without `node_type` in the context are non-conforming. This prevents cross-type key confusion.

### G-17: HITL Invocation Before Resolution (Phase 4)

`resolution_hash` MUST NOT be set on an HITLEventNode in `INVOKED` status. Resolution data may only be written during the `INVOKED → RESOLVED/TIMED_OUT/ESCALATED` transition. An HITLEventNode is the only node type that permits post-creation mutation, and this mutation is constrained to the single-phase transition.

### G-18: HITL Crystallization Block (Phase 4)

An episode with any HITLEventNode in `INVOKED` status (for blocking gate types: `APPROVAL_REQUIRED`, `COMPLIANCE_CHECKPOINT`) MUST NOT transition to `CRYSTALLIZATION_PENDING`. The crystallization lock acquisition MUST query for pending HITL events and refuse if any exist. Advisory gates (`REVIEW_ADVISORY`) do not block crystallization.

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

> **Node-Type Scope Note:** The retrieval operations defined below are the Episode-parameterized retrieval contract — the Phase 1 instantiation for `node_type="episode"`. Future node types (signals, agents, artifacts) will define their own retrieval contracts appropriate to their structure and access patterns. The protocol-level invariants — snapshot isolation (10.4), tail write advisory (10.5), HITL re-validation (10.6), and the side-effect contract (Section 11) — apply to ALL node-type retrieval contracts, not just Episode retrieval.

A conforming adapter implementing Episode retrieval MUST provide three operations:

**get_segment_by_id** — single segment by ID, node-scoped. Node scoping MUST be enforced at the query level — a query against node A must never return content belonging to node B.

**get_segment_range** — contiguous range by sequence_index (inclusive). Supports filtering by segment_type and author. Returns ordered by sequence_index ASC.

**get_episode_spine** — most recent N segments from an Episode's spine. Supports before_index scoping, segment_type filter, retention_tier filter. Returns ordered by sequence_index ASC.

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

### 11.1 Retrieval Audit Records

Every retrieval tool call SHOULD produce a `RetrievalAuditRecord` — a side-channel record capturing what an agent read, when, and through which snapshot boundary.

```
RetrievalAuditRecord {
  record_id:       UUID
  node_id:         string       (the CognitiveNode being read from)
  actor:           string       (agent_id performing the retrieval)
  tool_name:       string       (which retrieval tool was called)
  parameters:      dict         (from_index, to_index, limit, filters, etc.)
  segment_count:   int          (number of segments returned)
  segment_ids:     list[string] (UUIDs of returned segments)
  snapshot_index:  int?         (spine snapshot boundary at retrieval time)
  wall_clock:      datetime
}
```

Retrieval audit records are stored on separate nodes (not on segment nodes), linked to the source CognitiveNode via dedicated edges. They are NOT included in any hash computation. A conforming adapter SHOULD persist retrieval audit records but MUST NOT fail a retrieval if audit persistence fails — retrieval availability takes precedence over audit completeness.

Retrieval audit records enable post-hoc analysis: which agents read what content, at what point in the node's spine, and whether their snapshot was current or stale. This is the read-path complement to the WIL's write-path observability.

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

## 13. Spine Tip Cache

Segment append and snapshot capture both need to know the current `max(sequence_index)` for an Episode. Without caching, every such operation requires a database traversal.

A conforming implementation SHOULD maintain a cached spine tip per Episode in the ephemeral coordinator (e.g., Redis). The cache lifecycle:

1. **Invalidate** before any segment write begins (ensures no stale reads during the write window)
2. **Update** after segment write commits (sets cache to the new max sequence_index)
3. **Read** during snapshot capture — cache hit avoids database traversal
4. **TTL** as safety bound — cached entries expire if not refreshed (handles crashed writes that never reach the update step)

**The spine tip cache is a performance optimization, not a source of truth.** The authoritative max_sequence_index is always in the structural store (e.g., Neo4j). If the cache is empty, unavailable, or suspected of being stale, the system falls back to querying the structural store directly.

A conforming adapter MUST implement `get_spine_snapshot_index()` which returns the authoritative max_sequence_index from the structural store. The cache layer sits above this function and is implementation-defined.

## 14. Rebalance Events

Tree rebalancing modifies `tree_leaf_index` values without changing content. Without an audit trail, a legitimate rebalance is indistinguishable from tampering. The `RebalanceEventNode` is the forensic record that proves a rebalance was legitimate.

### 14.1 Root-Preservation Invariant

A correct rebalance MUST NOT change the spine root hash. The root is computed from leaf hashes, and leaf hashes are computed from `sequence_index` (immutable) and `content_hash` (unchanged by rebalancing). Therefore, `pre_rebalance_root` MUST equal `post_rebalance_root`.

A `RebalanceEventNode` where these values differ indicates the rebalance modified content — this is a governance violation and MUST be rejected at creation time.

### 14.2 Rebalance Event Record

```
RebalanceEventNode {
  event_id:              UUID
  node_id:               UUID         (the CognitiveNode being rebalanced)
  rebalance_generation:  int          (increments on each rebalance)
  triggered_by:          string       ("SIZE_THRESHOLD" | "MANUAL" | "SEAL_OPTIMIZATION")
  pre_rebalance_root:    string       (spine root before — MUST equal post)
  post_rebalance_root:   string       (spine root after — MUST equal pre)
  leaf_index_delta:      dict?        (optional: {segment_id: {old: N, new: M}})
  affected_leaf_count:   int
  executed_at:           datetime
  executor_id:           string
}
```

A conforming adapter MUST persist rebalance events and link them to the rebalanced node. The `rebalance_generation` counter enables detection of stale `tree_leaf_index` values — any `tree_leaf_index` from a prior generation may be incorrect.

## 15. Adapter Requirements

A conforming adapter MUST:

1. Implement the `AriadneAdapter` interface
2. Enforce all governance rules
3. Preserve hash chain integrity — never modify leaf_hash, spine_root, or content_hash after creation
4. Enforce the dual-index invariant: `tree_leaf_index` never in any hash preimage
5. Respect write ordering invariants across stores
6. Support idempotent writes for WIL recovery
7. Fail loudly on errors — never silently swallow writes
8. Implement `get_spine_snapshot_index()` for authoritative spine tip queries
9. Persist rebalance events with root-preservation invariant enforcement
10. Implement `TransparencyLogAdapter` interface if transparency log anchoring is supported
11. Persist `WitnessRecord` entries and enforce workspace-level witness policies

## 16. Trust Infrastructure (Phase 3)

### 16.1 Overview

Phase 3 adds cryptographic trust infrastructure to the `CognitiveNode` primitive. All Phase 3 machinery operates at the protocol surface — designed against `CognitiveNode`, not against any specific node type.

| Capability | Protocol-Mandatory | Implementation-Defined |
|-----------|-------------------|----------------------|
| Node Key Hierarchy | HKDF derivation path and context string format | Key material source, KMS integration |
| Transparency Log Anchoring | Anchor data structure, anchor timing (at crystallization) | Log target, submission mechanism |
| Node Witness Signatures | Witness record schema, what is signed | Signing algorithm, key management, threshold policy |
| Cross-Node Chain Proof | Proof chain data structure, verification algorithm | Chain traversal strategy, caching |

### 16.2 Node Key Hierarchy

#### 16.2.1 Derivation Path

All node keys are derived using HKDF-SHA3-256:

```
Root Key Material
    └── Workspace Key: HKDF(RKM, salt=workspace_id, info="ariadne.workspace.v1")
            └── Node Key: HKDF(WK, salt=node_id, info="ariadne.node.v1:{node_type}")
                    └── Seal Key: HKDF(NK, salt=spine_root_at_seal, info="ariadne.seal.v1")
```

The `node_type` participates in the HKDF `info` string at the Node Key level. Keys derived for `node_type="episode"` are cryptographically distinct from keys derived for `node_type="signal"` or `node_type="artifact"`. New node types automatically receive distinct key spaces without protocol changes.

#### 16.2.2 Two Cryptographic Identities

| Identity | Key | Derived From | Semantics |
|----------|-----|-------------|-----------|
| **Node Identity Key** | `NK` | `node_id` + `node_type` + `workspace_id` | "This is the node." Available from creation. |
| **Seal Commitment Key** | `SK` | `NK` + `spine_root_at_seal` | "This is the node at seal." Available only after sealing. |

The Seal Commitment Key binds the key to the sealed state. A signature under `SK` is a commitment to a specific `spine_root`, not just a node identity.

#### 16.2.3 Key Scope

Node keys support **signing only** at the protocol layer. Encryption (confidentiality of segment content) is implementation-defined and outside the protocol surface. This keeps the protocol surface minimal and avoids key escrow and rotation complexity at the protocol layer.

#### 16.2.4 Schema: NodeKeyRecord

```
NodeKeyRecord {
  node_id:                 string
  node_type:               string    (participates in HKDF context)
  workspace_id:            string
  key_version:             int       (monotonically increasing — G-15)
  public_key_fingerprint:  string    (SHA3-256 of public key bytes)
  derivation_path:         string    (human-readable: "workspace/{wid}/node/{nid}")
  created_at:              datetime
}
```

### 16.3 Transparency Log Anchoring

#### 16.3.1 Anchor Timing

Transparency log anchoring MUST occur at **crystallization boundaries** (G-14). Crystallization is already a protocol-level state transition producing an immutable snapshot — the natural anchor point. Anchoring provides external temporal proof that the crystallization existed at wall-clock time T and was not backdated.

#### 16.3.2 Anchor Data

```
AnchorCommitment {
  node_id:                   string
  node_type:                 string
  workspace_id:              string
  crystallization_root:      string    (spine_root at crystallization)
  crystallization_sequence:  int       (sequence_index of last segment)
  logical_clock:             int
  wall_clock:                datetime
  protocol_version:          string
}
```

The `AnchorCommitment` contains only protocol-surface data. No payload internals are anchored.

#### 16.3.3 TransparencyLogAdapter Interface

The protocol defines an abstract interface. Implementations provide a concrete adapter:

- `submit(commitment) -> AnchorReceipt` — submit an anchor commitment, receive a receipt with log proof
- `verify(receipt) -> bool` — verify a receipt is valid for its claimed log
- `retrieve(node_id, crystallization_root) -> AnchorReceipt?` — retrieve a previously submitted receipt

```
AnchorReceipt {
  log_id:             string    (identifies the transparency log)
  log_entry_id:       string    (log-specific entry identifier)
  commitment_hash:    string    (SHA3-256 of AnchorCommitment)
  log_timestamp:      datetime  (timestamp assigned by the log)
  inclusion_proof:    bytes?    (log's own inclusion proof)
  submitted_at:       datetime
}
```

#### 16.3.4 Hybrid Temporal Reasoning

The transparency log receipt's `log_timestamp` provides an **external monotonicity anchor** that the logical clock alone cannot provide. Conforming implementations SHOULD record the `log_timestamp` alongside the logical clock value, enabling: logical clock for intra-system ordering, log timestamp for cross-system and cross-architecture temporal proof.

### 16.4 Node Witness Signatures

#### 16.4.1 Purpose

A witness signature is a statement by an agent that it observed a specific `spine_root` for a specific `CognitiveNode` at a specific time. It is additive evidence — it does not alter the node's state or hash chain.

#### 16.4.2 Witness Commitment

```
WitnessCommitment = SHA3-256(
    node_id ‖ node_type ‖ spine_root ‖ sequence_index ‖ logical_clock ‖ role
)
```

Fields are UTF-8 encoded with `|` as separator, then hashed. The signature is over the commitment hash, not the raw fields.

#### 16.4.3 Schema: WitnessRecord

```
WitnessRecord {
  witness_id:              string    (agent_id of the witness)
  node_id:                 string
  node_type:               string
  spine_root:              string    (the specific root being witnessed)
  sequence_index:          int
  logical_clock:           int
  wall_clock:              datetime
  role:                    WitnessRole
  commitment_hash:         string    (SHA3-256 of WitnessCommitment)
  signature:               bytes
  public_key_fingerprint:  string
  protocol_version:        string
}
```

#### 16.4.4 Witness Roles

- `REVIEWER` — reviewed node content and attests to accuracy
- `AUDITOR` — audited node for compliance or correctness
- `SEAL_WITNESS` — witnessed the sealing event
- `CHAIN_ANCHOR` — attests to cross-node chain integrity
- `CUSTOM` — implementation-defined role (the differential hook for architectures with witness semantics the protocol hasn't anticipated)

#### 16.4.5 Witness Policy

The `min_counter_signatures` threshold is workspace-level configuration, not a protocol governance rule. The protocol defines the witness record schema and verification semantics; the threshold policy is an implementation differential (G-11).

### 16.5 Cross-Node Chain Proof

#### 16.5.1 Purpose

A cross-node chain proof answers: "Prove that Node B's state at sequence index N was causally downstream of Node A's state at sequence index M." This is the protocol-level mechanism for verifying causal relationships across node boundaries, node types, and AI architectures.

#### 16.5.2 ProofChain Data Structure

```
ProofLink {
  node_id:           string
  node_type:         string
  spine_root:        string
  sequence_index:    int
  inclusion_proof:   InclusionProof    (from Section 9.2)
  parent_node_id:    string?           (graph anchor)
  anchor_receipt:    AnchorReceipt?    (transparency log receipt, if available)
  witness_records:   WitnessRecord[]   (witness signatures at this link)
}

ProofChain {
  chain_id:          string
  links:             ProofLink[]       (ordered: root cause → effect)
  chain_root:        string            (SHA3-256 of concatenated link spine_roots)
  created_at:        datetime
  protocol_version:  string
}
```

#### 16.5.3 Chain Verification Algorithm

A `ProofChain` is valid if and only if:

1. **Each link is internally valid:** `link.inclusion_proof` verifies against `link.spine_root` using the inclusion proof algorithm from Section 9.2.
2. **The chain is causally ordered:** For consecutive links (A, B), either `B.parent_node_id == A.node_id` (direct parentage) or a valid cross-reference exists. This causal-ordering rule links **distinct cognitive nodes** (e.g. episode→episode); it does **not** describe how segments order within an episode — a segment's `parent_node_id` is its episode, and segments order by `sequence_index`, not by a parent chain (§3.4.1).
3. **Logical clock monotonicity:** Ordering is consistent with causal direction. Where chains cross architecture boundaries with independent clocks, transparency log timestamps resolve ordering.
4. **Chain root integrity:** `chain_root == SHA3-256(links[0].spine_root ‖ links[1].spine_root ‖ ... ‖ links[n].spine_root)` (G-13).

#### 16.5.4 Cross-Architecture Chain Proof

When a `ProofChain` spans nodes from different conforming implementations, the chain is valid if all links satisfy the verification algorithm above, each link's `inclusion_proof` is verifiable using only protocol-surface primitives, and `anchor_receipt` entries provide temporal ordering where logical clocks are incommensurable.

This is the concrete expression of the cross-architecture interoperability guarantee in Section 2.5.4.

## 17. Conformance Testing

The `ariadne.protocol.verification` module provides the `DeltaVerifier` — the five-test gate that any conforming implementation must pass.

### 17.1 Phase 1-2 Conformance (Five-Test Gate)

| Layer | Verifies |
|-------|----------|
| **Structural** | Hash chain integrity, leaf hash correctness, Merkle root consistency |
| **Temporal** | Sequence monotonicity, logical clock monotonicity, position-binding |
| **Audit** | Tamper-evident chain integrity, delta record consistency |

The five specific test cases are defined in Section 9.1. A conforming implementation MUST detect all five tampering classes.

### 17.2 Phase 3 Conformance Test Vectors

Phase 3 adds the following prescriptive test vectors. Implementors claiming Phase 3 conformance MUST pass all of them:

**Key Derivation Tests:**

| # | Test | Expected |
|---|------|----------|
| K1 | Derive Node Key with `node_type="episode"` and again with `node_type="signal"` using same `node_id` | Keys MUST differ (G-16) |
| K2 | Derive Seal Key with two different `spine_root` values for same node | Keys MUST differ |
| K3 | Attempt to create `NodeKeyRecord` with `key_version` less than existing | MUST reject (G-15) |

**Witness Verification Tests:**

| # | Test | Expected |
|---|------|----------|
| W1 | Create `WitnessRecord` with correct `commitment_hash` | Verification passes |
| W2 | Create `WitnessRecord` with tampered `commitment_hash` | Verification MUST fail (G-12) |
| W3 | Set `min_counter_signatures=2`, attempt seal with 1 valid witness | MUST reject (G-11) |
| W4 | Set `min_counter_signatures=2`, attempt seal with 2 witnesses but same `witness_id` | MUST reject (G-11 requires distinct IDs) |

**Transparency Log Tests:**

| # | Test | Expected |
|---|------|----------|
| T1 | Submit `AnchorCommitment` at crystallization | Receipt returned with valid `commitment_hash` |
| T2 | Verify receipt against `AnchorCommitment` | Passes |
| T3 | Tamper with `AnchorCommitment` after receipt | Verification MUST fail (`commitment_hash` mismatch) |

**Chain Proof Tests:**

| # | Test | Expected |
|---|------|----------|
| C1 | Build 3-link `ProofChain` with valid links and parentage | `chain_root` verification passes |
| C2 | Tamper with one link's `spine_root` without updating `chain_root` | Verification MUST fail (G-13) |
| C3 | Reorder links in chain (break causal order) | Verification MUST fail (causality check) |
| C4 | Cross-architecture chain: two implementations, valid links | Verification passes using only protocol-surface primitives |

### 17.3 Cross-Architecture Interoperability Test

The definitive conformance test for two implementations claiming interoperability:

1. Implementation A creates a `CognitiveNode`, appends segments, seals, and generates an `InclusionProof`
2. Implementation B receives only the proof and the `spine_root` (no payload, no internal state)
3. Implementation B verifies the proof using protocol-surface primitives
4. Result: proof MUST verify. If it does not, at least one implementation is non-conforming.

This test should be run bidirectionally (A→B and B→A).

## 18. Version History

| Version | Date | Changes |
|---------|------|---------|
| 0.1.0-draft | 2026-04-07 | Initial extraction. Episode-centric. See SPEC-v1.md. |
| 2.0.0-draft | 2026-04-09 | CognitiveNode foundation. Dual-index. Position-binding leaf hash. Five-test gate. Namespace firewall. |
| 2.1.0-draft | 2026-04-10 | Retrieval coordination protocol: snapshot isolation (10.4), tail write advisory (10.5), HITL re-validation gate (10.6), side-effect contract (11). |
| 2.2.0-draft | 2026-04-12 | Phase 2 observability: signal_versions_read (4.5), retrieval audit records (11.1), spine tip cache (13), rebalance events (14). |
| 2.3.0-draft | 2026-04-12 | Phase 3 trust infrastructure: Protocol vs. Implementation Boundary (2.5), node key hierarchy (16.2), transparency log anchoring (16.3), witness signatures (16.4), cross-node chain proof (16.5), G-11 through G-16. |
| 2.4.0-draft | 2026-04-16 | Phase 4 HITL: HITLEventNode first-class node type (4.6), two-phase lifecycle (INVOKED→RESOLVED), HITL_GATE edges (BLOCKS/FOLLOWS), Merkle spine participation as causal anchors, PENDING_HITL crystallization guard, two-layer Ed25519 signing (agent invocation + human resolution), CONDITIONALLY_VALID advisory gates, pending_hitl_ref segment tagging, G-17 (invocation before resolution), G-18 (crystallization block). Schema version 1.2.0. |
| 2.5.0-draft | 2026-04-21 | Branch/Fork/Merge Taxonomy §19 covering BFM Phases 1–4: BranchPoint/BranchTerminus (§19.2), ForkPoint/MergePoint/BranchReturn with three-Merkle-root verification (§19.3), AsideSegment/SoliloquySegment with HASH_PLACEHOLDER content policy and Decision 1 visibility (§19.4), CoherenceFingerprint write-intercept state machine and ConfirmationCache (§19.5). New governance rules G-19 through G-29. New delta types BRANCH_CREATED/ABANDONED, FORK_CREATED/RESOLVED, MERGE_EXECUTED, ASIDE_OPENED/CLOSED, SOLILOQUY_INITIATED/CONCLUDED. AuditRecord chain integrity (`prior_audit_hash`), IntentRecord idempotency, derived lifecycle state (§19.2.4). |
| 3.0.0 | 2026-06-07 | **MAJOR** — Cross-episode linking + grouping. Source: [`AMENDMENT-v2.0-CROSS-EPISODE-LINKING.md`](./AMENDMENT-v2.0-CROSS-EPISODE-LINKING.md). Typed `EpisodeLink` with `LinkType`, `LinkHealthState`, `Signal`/`SignalType` machinery. `EpisodeGrouping` interface (`MembershipRecord` as protocol-owned artifact; `ConformanceDeclaration` for downstream conformance). Succession-chain governance for membership/conformance. Audit-the-decision pattern for behavioral-tier implementation choices (§12). Three-tier conformance taxonomy: wire / state / behavioral. **Breaking hash preimage changes on `EpisodeLink`, `MembershipRecord`, `ConformanceDeclaration`** — see amendment Appendix A for the full breaking-change reference. `LINK_*` audit events + `assert_episode_link` operation. Phase 2 discovery primitives (link proposals + calibration loop). Audit-chain + canonical-hash helpers lifted into shared core modules. |
| 3.1.0 | 2026-06-07 | **MINOR** — Layer 3 Workflow & Execution DAG. Source: [`AMENDMENT-v3.0-WORKFLOW-EXECUTION-DAG.md`](./AMENDMENT-v3.0-WORKFLOW-EXECUTION-DAG.md). New node types: `WorkflowDeclaration`, `ExecutionNode`, `SkillInvocation`. Three-Merkle-layer model formalized: Layer 1 Spine, Layer 2 episode content, Layer 3 Workflow & Execution DAG. **Layer 3 is cryptographically isolated from Spine integrity** — references Layers 1/2 by ID only; never hash-linked into the Spine; no future Layer-3 change can force a MAJOR bump on Spine grounds. Cognitive Implementation Authority (CIA) — sole-writer guarantee as wire-tier conformance principle. New `CognitiveDeltaType` variants. `ExecutionNode` and `SkillInvocationNode` immutable after creation; only mutable Layer 3 field is `WorkflowDeclaration.status` (and `status_updated_at`). Hash byte-form left open at protocol layer per amendment §3. |
| 3.2.0 | 2026-07-04 | **MINOR** — Phase D departure-fork lifecycle, defined in-body (§19.3.5–19.3.6). `create_departure_fork()`: a single directional departure into a new (continuing) Episode, distinct from the speculative `create_fork()`. New nodes `DepartureForkPointNode` (domain `DEPARTURE_FORK_POINT:`) and `ForkReturnNode` (domain `FORK_RETURN:`). Backdating integrity invariant (G-30): `spine_tip_hash_at_departure` == the fork Episode's `fork_origin_spine_tip_hash`. Lifecycle FSM `ACTIVE → COMPLETED \| ABANDONED` (`complete_departure_fork` / `abandon_departure_fork` / `declare_fork_return`); resumption is a non-event. **Declarative** return (`INCORPORATED`/`ACKNOWLEDGED`/`SUPERSEDED`), never the branch's structural merge. Immutable Episode fork provenance (§19.3.6). New `CognitiveDeltaType` variants `DEPARTURE_FORK_CREATED`/`_COMPLETED`/`_ABANDONED`/`_RETURNED`; new edges `FORK_RETURN`, `RETURNED_FROM`. Governance G-30 through G-35. **Additive — no breaking changes.** |

## 19. Branch/Fork/Merge Taxonomy

This section specifies the node types, governance rules, delta types, and
state transitions that model non-linear cognitive work: when an agent (or
human) diverges from a single coherent thread and later reconciles (or
terminates) the divergence. The taxonomy is orthogonal to §4–§16 — it
adds new node types on top of the `CognitiveNode` primitive.

**Governing principle.** Every state transition in this taxonomy
simultaneously produces (a) a structural node, (b) a cognitive delta, and
(c) an append-only audit record. If any of the three writes is absent or
fails, the transition is incomplete. A partial transition is worse than
no transition — it produces ghost state the system cannot reason about.

### 19.1 Foundation Layer

#### 19.1.1 AuditRecord

`AuditRecord` is the tamper-evident append-only log for the taxonomy.

| Field | Type | Purpose |
|-------|------|---------|
| `audit_id` | UUID | Record identity |
| `delta_sequence` | int (monotonic) | Global ordering; never resets |
| `agent_id`, `session_id`, `human_actor` | string | Who |
| `wall_clock_time`, `episode_time` | ISO8601, logical clock | When |
| `delta_type` | enum | What transition (see §19.1.2) |
| `forward_delta`, `reverse_delta` | payload | Forward + reverse written simultaneously |
| `prior_audit_hash` | SHA3-256 hex | Previous record's `record_hash` — chain link |
| `record_hash` | SHA3-256 hex | `sha3_256(b"AUDIT:" + …)` |
| `caught_by` | AGENT / HUMAN / SYSTEM / UNCAUGHT | Detection provenance |
| `detection_window_open` | bool | Was active detection running? |

**Chain integrity.** `prior_audit_hash` is the previous record's
`record_hash`, forming a hash chain scoped by `episode_id`. Any
insertion, deletion, or modification of a historical record breaks the
chain from that point forward.

**Invariant.** Rollback creates a new forward record. The log is never
edited in place — a reverse delta is written as a new audit record that
references the original.

#### 19.1.2 CognitiveDelta Registry — Taxonomy Types

| Delta Type | Phase | Writer |
|-----------|-------|--------|
| `BRANCH_CREATED` | 1 | `create_branch()` |
| `BRANCH_ABANDONED` | 1 | `abandon_branch()` |
| `FORK_CREATED` | 2 | `create_fork()` |
| `FORK_RESOLVED` | 2 | `resolve_fork()` |
| `MERGE_EXECUTED` | 2 | `execute_merge()` |
| `ASIDE_OPENED` | 3 | `create_aside()` |
| `ASIDE_CLOSED` | 3 | `close_aside()` |
| `SOLILOQUY_INITIATED` | 3 | `create_soliloquy()` |
| `SOLILOQUY_CONCLUDED` | 3 | `conclude_soliloquy()` |

All types register at protocol load time. Functions reference the
registry — the registry never references functions.

#### 19.1.3 AccessPolicy

Per-resource read/write policy. Default resource types: `BRANCH`, `FORK`,
`ASIDE`, `SOLILOQUY`. Defaults:

| Resource | `other_agents_read` | `audit_on_access` |
|----------|--------------------|--------------------|
| `BRANCH` / `FORK` / `ASIDE` | `OPEN` | false |
| `SOLILOQUY` | `ESCALATION_ONLY` | true |

**Enforcement rule:** fail-closed. If a policy cannot be evaluated,
access is denied and a denial is written to the audit chain.

#### 19.1.4 IntentRecord

Prevents concurrent duplicate creation (Harmonia Scenario A). Idempotency
key: `SHA3-256("INTENT:" + source_episode_id + source_segment_id + intent_hash)`.
An `acquire_intent_sync` lookup with a COMPLETE status returns the prior
result; a PENDING status short-circuits; a new intent is written
atomically.

### 19.2 Phase 1 — Branch Lifecycle

#### 19.2.1 BranchPointNode

Created by `create_branch()` at the exact divergence point on the spine.
Immutable after creation; lifecycle state is derived from the presence
or absence of a matching `BranchTerminusNode`.

Key fields: `branch_id` (stable UUID), `parent_episode_id`,
`source_segment_id`, `branch_type`, `branch_depth` (soft max 4),
`declaration_type` (`EXPLICIT` / `INFERRED` / `RETROACTIVE`),
`spine_merkle_snapshot` (immutable coherence anchor), `content_hash`
(domain prefix `BRANCH_POINT:`).

Retroactive declarations additionally carry
`pre_declaration_merkle_root`, `declared_retroactively_at`, `declared_by`.

#### 19.2.2 BranchTerminusNode

Created by `abandon_branch()` (type `ABANDONED`) or `execute_merge()`
(type `MERGED`). Terminal — the branch cannot be reopened.

Integrity link: `branch_point_hash` MUST equal the originating
`BranchPointNode.content_hash`. The terminus hash uses domain prefix
`BRANCH_TERMINUS:`.

#### 19.2.3 Dual Hash Chain

Branches create non-linear Episode graphs that must remain verifiable:

- **Spine chain.** `BranchPointNode.content_hash` is included in the
  spine chain. Branch *contents* are NOT — the spine is self-contained
  and verifiable without them.
- **Branch chain.** Starts at `BranchPointNode` and ends at
  `BranchTerminusNode`. Verifiable independently of the spine.
- **Merge verification (Phase 2).** Requires three Merkle roots — see §19.3.3.

**Depth constraint.** `branch_depth` maximum of 4 (soft). Exceeding it
raises `AriadneGovernanceError`; callers may catch and record an
override in the audit trail.

#### 19.2.4 Derived Lifecycle State

Lifecycle state is always recomputed from the log — never stored as a
mutable field:

```
IF BranchPointNode(branch_id) missing             → ERROR
IF BranchTerminusNode(branch_id, MERGED) exists   → MERGED
IF BranchTerminusNode(branch_id, ABANDONED) exists → ABANDONED
ELSE                                              → ACTIVE
```

### 19.3 Phase 2 — Resolution Primitives

#### 19.3.1 ForkPointNode

Forks differ from branches: a fork produces a new Episode with a
distinct objective. A single `create_fork()` call writes N ForkPointNodes
sharing the same `fork_id`; each ForkPoint anchors a new Episode.
Domain prefix: `FORK_POINT:`.

Governance:
- **G-19.** `fork_objective` non-empty. A fork without an objective is
  indistinguishable from a branch.
- **G-20.** At least 2 alternatives per fork. Single-path divergence is
  a branch.

`resolve_fork()` marks one sibling `PROMOTED` and all others `DISCARDED`,
writing `FORK_RESOLVED`. `resolution_rationale` is required (G-21).

#### 19.3.2 MergePointNode

Created by `execute_merge()` on the target spine. Carries three Merkle
roots: `source_merkle_root` (branch state at merge),
`target_merkle_root_pre` (spine before merge), `target_merkle_root_post`
(spine after merge — must match recompute). Domain prefix: `MERGE_POINT:`
binds all three roots into the content hash.

**G-22.** `merge_summary` non-empty. The synthesis is the audit trail.

**G-23 (Conflict Surface Invariant).** `execute_merge()` never resolves
conflicts silently. When conflicts exist without matching
`ConflictResolution` entries, or when `merge_strategy == AUTO` and any
conflicts exist, the function returns a `ConflictManifest` and writes
NO merge records. The manifest carries `source_merkle_root`,
`target_merkle_root_pre`, the common ancestor, and all conflict
segments; callers must re-invoke with resolutions.

**G-24.** The three integrity assertions in §5 Step 8 of the build spec
must pass before `MergePointNode` is written. On failure the merge is
aborted and a SYSTEM-caught failure audit record is written.

#### 19.3.3 Merge Integrity Verification

```
source_valid      := merge.source_merkle_root      == branch.merkle_root at merge time
target_pre_valid  := merge.target_merkle_root_pre  == spine.merkle_root before merge
target_post_valid := merge.target_merkle_root_post == recomputed spine root
integrity_holds   := all three
```

`verify_merge_integrity(merge_id)` returns a `MergeIntegrityResult`.
Any `false` in `integrity_holds` is a critical health metric
(`merge_integrity_failures`, target: 0).

#### 19.3.4 BranchReturnEdge

On merge, a `BRANCH_RETURN` edge connects `BranchTerminusNode(MERGED)`
to the `MergePointNode` on the target spine. Carries
`synthesis_summary` and `nodes_integrated`.

#### 19.3.5 DepartureForkPointNode (Phase D — Departure Fork Lifecycle)

A **departure fork** is distinct from the speculative fork of §19.3.1. It is a
single **directional departure**: one topic diverges into a new Episode while the
originating Episode *continues* uninterrupted. There are no siblings and no
resolve/promote/discard — a departure fork, if not abandoned, *is* an Episode
("fork is a verb, not a noun"). Created by `create_departure_fork()`.
Domain prefix: `DEPARTURE_FORK_POINT:`.

`create_departure_fork()` writes atomically: the new fork Episode (status ACTIVE,
carrying the immutable fork provenance of §19.3.6), a single
`DepartureForkPointNode` on the *originating* spine (`FORK_ORIGIN` edge), and a
`DEPARTURE_FORK_CREATED` audit record.

**G-30 (Backdating integrity invariant).**
`DepartureForkPointNode.spine_tip_hash_at_departure` == the fork Episode's
`fork_origin_spine_tip_hash`. Both are the originating spine tip at the departure
moment; a mismatch is a fatal integrity violation at creation. The branch point
records where divergence *began*, cross-verifiable across the two independent spines.

Governance:
- **G-31.** `fork_objective` non-empty (as G-19).
- **G-32.** `fork_creation_trigger ∈ {TOPIC_SHIFT, PARALLEL_THREAD, EXPLICIT_FORK,
  AGENT_ESCALATION}`. `EXPLORATORY_THREAD` routes to the speculative `create_fork()`,
  not here.
- **G-33.** `fork_trigger_segment_id` required when `fork_creation_trigger ==
  AGENT_ESCALATION`.

**Lifecycle FSM.** States `ACTIVE → COMPLETED | ABANDONED`, a distinct vocabulary
from the speculative fork's `PROMOTED | DISCARDED` (an abandoned departure is not a
discarded alternative). `ACTIVE` covers both in-progress and *parked*;
**resumption** — re-entering the origin while the fork stays ACTIVE — is a
non-event: no node, no declaration.

- `complete_departure_fork()` — `ACTIVE → COMPLETED`. A first-person declaration by
  the fork Episode's own agent. Writes `DEPARTURE_FORK_COMPLETED`.
- `abandon_departure_fork()` — `ACTIVE → ABANDONED` (terminal). By the originating
  agent, or system cleanup of a never-entered stub. A COMPLETED fork returns; it is
  not abandoned. Writes `DEPARTURE_FORK_ABANDONED`.

**Formal return.** `declare_fork_return()` (authority: the originating agent) writes
a `ForkReturnNode` to the *originating* spine (`FORK_RETURN` edge) plus a
`RETURNED_FROM` edge to the fork Episode, and a `DEPARTURE_FORK_RETURNED` audit.
Domain prefix: `FORK_RETURN:`. A fork return is **declarative** — the origin asserts
incorporation across two independent spines — never the branch's *structural*
merge; integration content is written as subsequent origin-spine segments.
`return_type ∈ {INCORPORATED, ACKNOWLEDGED, SUPERSEDED}`.
- **G-34.** The fork must be `COMPLETED` before a return may be declared.
- **G-35.** At most one return declaration per `fork_id`.

Resumption requires no node; only a formal return writes to the spine.

#### 19.3.6 Departure-fork Episode provenance

An Episode created via `create_departure_fork()` carries immutable provenance
fields, set once at creation and never mutated: `fork_origin_episode_id`,
`fork_anchor_index`, `fork_id`, `fork_created_at`, `fork_creation_trigger`,
`fork_trigger_confidence`, `fork_trigger_segment_id`, `fork_origin_spine_tip_hash`,
`fork_origin_active_branch_ids`, `fork_status`, `fork_return_type`. This is
provenance — "how did this Episode come to exist" — not identity, analogous to
`continuation_of`. Null on non-fork Episodes.

### 19.4 Phase 3 — Social/Internal Primitives

#### 19.4.1 AsideSegmentNode

Human-initiated side channel with a target agent. Domain prefix `ASIDE:`.

**G-25 (Aside Human-Initiation Invariant).** Asides are ALWAYS
human-initiated. `initiated_by_human` is required; an attempt to create
an aside without a human actor raises `AriadneGovernanceError`.
Agent-initiated internal branches are soliloquies (§19.4.2).

**G-26 (Aside Return Obligation).** An aside that remains OPEN at
episode seal is an audit violation. `check_aside_return_obligation()`
enforces this at seal time.

**Asymmetric merge on close.** `close_aside()` runs a reference scan:
external segments that hold references to aside-internal segments are
recorded in the `AsideTerminusNode` and `ASIDE_CLOSED` audit record as
`external_references_found`. The close proceeds — the scan is a
disclosure mechanism, not a block — but the leak is part of the
permanent audit trail.

#### 19.4.2 SoliloquySegmentNode

Agent-initiated private deliberation. Domain prefix
`SOLILOQUY_PLACEHOLDER:` or `SOLILOQUY_FULL:` depending on the
`content_hash_policy` field (see §19.4.3).

**G-27 (Soliloquy Human Accessibility Invariant — Decision 1).** Humans
ALWAYS have read access. `SoliloquyVisibilityPolicy.human_accessible`
defaulting or being set to `false` raises `AriadneGovernanceError`.
Deliberation content can be private to other agents, never private to
humans.

**G-28 (Soliloquy Return Obligation).** Soliloquies left ACTIVE at
episode seal are audit violations. Coherence monitoring continues
inside the soliloquy — the agent cannot use soliloquy to escape the
framework.

**Conclusion merges, chain stays.** `conclude_soliloquy()` writes a
`SoliloquyConclusionNode` carrying `conclusion_content_hash` (public)
and `deliberation_chain_hash` (tamper-evident hash of the private
chain). Only the conclusion is absorbed into the spine; the
deliberation chain remains sealed inside the `SoliloquySegmentNode`.

#### 19.4.3 Soliloquy Content Hash Policy

| Policy | Preimage | Use Case |
|--------|---------|----------|
| `HASH_PLACEHOLDER` | `SOLILOQUY_PLACEHOLDER:{id}:{ep}:{seg}:{agent}:{ts}` | Preserves Merkle chain integrity without exposing content. Default. |
| `FULL_CONTENT` | `SOLILOQUY_FULL:{id}:{ep}:{seg}:{agent}:{ts}:{chain}` | Chain content bound into the hash. Use when privacy is not required. |

The placeholder variant is the key protocol innovation for private
deliberation — the spine verifies that a node exists at a given
position without the content being recoverable from the hash.

### 19.5 Phase 4 — Prescriptive Enforcement

Detection moves from descriptive (retroactive analysis) to prescriptive
(active, at segment write time).

#### 19.5.1 CoherenceFingerprint

Embedded per segment at write time:

| Field | Purpose |
|-------|---------|
| `topic_vector` | Caller-supplied embedding |
| `intent_class` | CONTINUE / EXPAND / SHIFT / RESOLVE / INTRODUCE |
| `objective_hash` | `sha3_256("OBJECTIVE:" + canonicalized objective)` |
| `drift_from_spine` | 0.0–1.0 cosine distance |
| `consecutive_drift_count` | Persisted across turns |
| `detection_state` | NOMINAL / WATCHING / CANDIDATE / MATERIALIZED |

**G-29 (Write-Time Fingerprint Invariant).** Fingerprints must be
computed at segment write time. `enforce_write_time_fingerprint(None)`
raises — retroactive fingerprinting defeats the detection window.

#### 19.5.2 Detection State Machine

`advance_detection_state(prior_state, prior_count, drift, obj_changed, intent, thresholds)`
is a pure function. Default thresholds match the spec:

| Target state | Drift ≥ | Consecutive turns ≥ |
|--------------|--------|---------------------|
| WATCHING | 0.3 | 1 |
| CANDIDATE | 0.3 | 3 |
| MATERIALIZED | 0.5 | 5 |

Two overrides force immediate CANDIDATE regardless of drift:
- `objective_hash` changed between consecutive observations
- `intent_class == INTRODUCE`

Drift below `watching_drift` resets the count to 0 and returns state to
NOMINAL. Thresholds are tunable per-episode-type via
`DetectionThresholds`.

#### 19.5.3 Write Intercept Protocol

`intercept_segment_write()` is the application hook. Sequence:

1. Compute `objective_hash` from the current episode objective.
2. Call `detect_branch_candidate()` — reads last fingerprint, advances
   state, computes `materialized_recommendation` if the state
   transitions to MATERIALIZED for the first time.
3. Persist the new fingerprint via the registry.
4. Return `DetectionResult`. If the result carries a
   `materialized_recommendation`, the caller SHOULD invoke
   `create_branch(declaration_type=RETROACTIVE, source_segment_id=rec.source_segment_id)`.
   The recommendation anchors at the last NOMINAL segment — the point
   before drift began.

`detect_branch_candidate()` is pure-read; only
`intercept_segment_write()` persists.

#### 19.5.4 ConfirmationCache

Prevents the confirmation loop when a detected candidate is confirmed
as a legitimate branch. TTL is measured in episode turns:

```
confirmation_valid_until = confirmed_at_turn + valid_for_turns
```

Lookup is case- and whitespace-insensitive on the action description.
Expiry is checked at read time; expired entries are discarded.

### 19.6 Edge and Relationship Summary

| Edge | From → To | Phase |
|------|-----------|-------|
| `BRANCH_ORIGIN` | Episode → BranchPoint | 1 |
| `BRANCH_TERMINUS` | BranchPoint → BranchTerminus | 1 |
| `AUDIT_TRAIL` | Episode → AuditRecord | 1 |
| `FORK_ORIGIN` | Episode → ForkPoint | 2 |
| `MERGE_INTO` | Source Episode → MergePoint | 2 |
| `MERGE_TARGET` | MergePoint → Target Episode | 2 |
| `BRANCH_RETURN` | BranchTerminus(MERGED) → MergePoint | 2 |
| `ASIDE_OPEN` | Episode → Aside | 3 |
| `ASIDE_CLOSED` | Aside → AsideTerminus | 3 |
| `SOLILOQUY_OPEN` | Episode → Soliloquy | 3 |
| `SOLILOQUY_CONCLUDED` | Soliloquy → SoliloquyConclusion | 3 |
| `FINGERPRINTS` | Episode → CoherenceFingerprint | 4 |
| `FORK_ORIGIN` (departure) | Origin Episode → DepartureForkPoint | D |
| `FORK_RETURN` | Origin Episode → ForkReturn | D |
| `RETURNED_FROM` | ForkReturn → Fork Episode | D |

### 19.7 Implementation Status

All four BFM phases **plus the Phase D departure-fork lifecycle** are implemented
and covered by unit tests against the Neo4j adapter (mocked driver). See
`tests/unit/protocol/test_phase2_*.py`, `test_phase3_*.py`, `test_phase4_*.py`, and
the departure-fork suites in `test_phase2_operations.py` (`TestCreateDepartureFork`,
`TestDepartureForkFSM`).

The following are **known limitations / forward-compatible extensions** —
deliberately scoped out of this version, non-breaking to add later, and safe to
build on:

1. **`target_merkle_root_post`** in `execute_merge()` is computed
   deterministically from pre-merge roots and resolutions rather than
   from full spine recomputation. Full recomputation requires a
   branch-aware segment model (segments tagged with `branch_id`), which
   is a forward-compatible extension.
2. **`find_common_ancestor()`** walks one level — from the branch's
   originating BranchPoint to the target spine. Multi-level nested
   merges require iterative traversal (forward-compatible).
3. **Return-obligation checks** (`check_aside_return_obligation`,
   `check_soliloquy_return_obligation`) are available as callable
   guards but are not yet invoked from the episode-seal path; the
   integration is owned by the seal implementation.
4. **Access-policy runtime enforcement** (audit on ESCALATION_ONLY reads)
   is spec'd at the coordination layer and left to the application.

## 20. References

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
