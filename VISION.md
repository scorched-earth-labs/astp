# ASTP — AI State Tree Protocol
## Unified Architecture Vision
**Version:** 0.1.0-draft synthesis  
**Date:** April 8, 2026  
**Prepared by:** Clotho, Suite Lead — product_ariadne  
**Contributors:** Daedalus, Aletheia, Chronos, Mnemosyne, Harmonia

---

## Executive Summary

ASTP (the AI State Tree Protocol, developed internally as Project Ariadne) is the persistence layer that gives agents continuous identity and verifiable state. It answers a deceptively simple question: *"Did this agent reason honestly, in this order, with these influences, and can we prove it?"*

The protocol achieves this through three interlocking primitives:
- **The Spine** — an ordered hash chain that makes reasoning sequence part of the integrity guarantee
- **The Seal** — a tripartite cryptographic commitment that freezes a bounded unit of work
- **Crystallization** — an immutable cross-episode checkpoint that anchors the historical record

Everything else in this document serves those three primitives.

---

## 1. Architectural Foundation

### 1.1 The Core Insight

Most persistence systems treat *what* was stored as the integrity concern. ASTP treats *when* and *in what order* as equally fundamental. An agent that reasons correctly but in a manipulated sequence has not reasoned authentically. The Spine is the mechanism that makes reordering a cryptographic violation, not just a policy violation.

### 1.2 The Three-Level Hash Architecture

```
Level 1: Segment Spine (ordered chain — position is integrity)
──────────────────────────────────────────────────────────────
S₀ = H(LEAF_PREFIX || null         || content₀ || meta₀ || position:0)
S₁ = H(LEAF_PREFIX || S₀          || content₁ || meta₁ || position:1)
S₂ = H(LEAF_PREFIX || S₁          || content₂ || meta₂ || position:2)
...
Sₙ = H(LEAF_PREFIX || Sₙ₋₁        || contentₙ || metaₙ || position:n)

Spine Root = MerkleRoot(S₀, S₁, ..., Sₙ)
  — using domain-separated branch hashing (BRANCH_PREFIX)
  — position index bound into each leaf (prevents reorder attacks)

Level 2: Episode Seal (tripartite commitment)
──────────────────────────────────────────────────────────────
Signal Manifest Root = MerkleRoot(all_signal_hashes)

Episode Root = H(
  version_tag           ||  # protocol version binding
  episode_id            ||  # prevents cross-episode transplant
  spine_root            ||
  signal_manifest_root  ||
  lifecycle_state       ||  # SEALED is part of the commitment
  sealed_at_timestamp
)

Seal = {
  episode_root_hash,
  spine_hash,
  signal_manifest_hash,
  sealed_by,
  sealed_at,
  nonce,                    # prevents replay
  signature                 # over all above fields
}

Level 3: Crystallization (cross-episode checkpoint)
──────────────────────────────────────────────────────────────
Chain Root = MerkleRoot(EpisodeSeal₀, EpisodeSeal₁, ..., EpisodeSealₙ)

Crystallization Record = {
  sequence_number,
  prior_crystal_hash,       # chains crystallizations — CRITICAL
  episode_set_root,
  episode_seal_hashes[],    # ordered
  crystallized_at,
  witness_signatures[]      # multi-party if required
}
```

**Why position-binding matters:** A flat Merkle tree proves a segment *exists* in an episode. The Spine proves it exists *at a specific position*. For cognitive integrity, these are different claims. Inserting a segment between positions 3 and 4 is a form of tampering even if no content changes.

**Why domain separation matters:** Without `LEAF_PREFIX` and `BRANCH_PREFIX` on hash inputs, an attacker can construct a valid "leaf" that is also a valid "branch" node — a well-documented Merkle vulnerability. Domain separation is mandatory, not optional.

### 1.3 Hash Algorithm Selection

| Purpose | Algorithm | Rationale |
|---------|-----------|-----------|
| Spine segment hashing | BLAKE3 | Fast, parallelizable, streaming-capable for large artifacts |
| Merkle branch nodes | SHA3-256 (Keccak) | Well-analyzed, no length extension attacks |
| External seal signatures | SHA3-256 | Compatibility with external verification systems |
| **Avoid** | SHA-256 (naive) | Length extension vulnerability in custom constructions |

---

## 2. Node Schema

### 2.1 Episode Node

```typescript
interface EpisodeNode {
  // Identity
  id: EpisodeID;                        // UUID v7 (time-ordered, no coordination)
  version: SemanticVersion;             // Protocol version: "0.1.0"

  // Lifecycle
  status: EpisodeStatus;                // CREATED | ACTIVE | SEALING | SEALED | ARCHIVED
  created_at: Timestamp;
  activated_at: Timestamp | null;
  sealing_initiated_at: Timestamp | null;
  sealed_at: Timestamp | null;
  archived_at: Timestamp | null;

  // Participants
  primary_agent: AgentRef;
  collaborating_agents: AgentRef[];
  coordinator_agent: AgentRef | null;   // For COLLABORATION episodes

  // Content references (hash references only — content lives in storage)
  spine_root: SpineHash;
  segment_count: uint32;
  signal_manifest_hash: Hash;

  // Seal (null until SEALED)
  seal: EpisodeSeal | null;

  // Relationships
  parent_episode: EpisodeID | null;     // For branch episodes
  spine_predecessor: EpisodeID | null;  // Previous episode in chain
  crystallization_ref: CrystallizationID | null;
  branch_status: BranchStatus | null;   // null | ACTIVE | MERGED | DIVERGED

  // Temporal
  logical_clock: uint64;                // Lamport clock — authoritative ordering
  version_vector: Record<AgentID, uint64>; // For multi-agent coordination

  // Metadata
  context_tags: string[];
  cognitive_model: string;              // "ReAct" | "CoT" | "BDI" | etc.
  key_commitment: PublicKeyRef;         // Key that will seal this episode (set at CREATED)

  // Integrity
  node_hash: Hash;
}
```

> **Key design decisions:**
> - `SEALING` is a formal intermediate state (not implied) — required for seal race prevention
> - `key_commitment` is set at creation, not at sealing — enables historical verification even after key rotation
> - `logical_clock` is authoritative; wall-clock timestamps are advisory
> - `branch_status` tracks branch lifecycle explicitly

### 2.2 Segment Node

```typescript
interface SegmentNode {
  id: SegmentID;
  episode_id: EpisodeID;

  // Spine ordering
  sequence_index: uint32;               // Absolute position — immutable once written
  predecessor_hash: Hash | null;        // null only for sequence_index === 0

  // Type
  segment_type: SegmentType;
  // CONVERSATION | REASONING | ARTIFACT | ANNOTATION |
  // CONSULTATION | COLLABORATION

  // Content (indirection — content lives in storage)
  content_hash: Hash;
  content_ref: StorageRef;
  content_size_bytes: uint64;
  content_encoding: ContentEncoding;

  // Spine participation
  spine_hash: Hash;
  // = H(LEAF_PREFIX || predecessor_hash || content_hash || metadata_hash || sequence_index)

  // Authorship (for audit)
  author: AgentRef;
  faculty_id: FacultyID;
  written_at: Timestamp;
  logical_clock: uint64;

  // Causal context (for conflict reconstruction)
  signal_versions_read: Record<SignalID, SignalVersion>;

  // Type-specific metadata
  metadata: SegmentMetadata;            // Discriminated union (see below)

  node_hash: Hash;
}
```

> **Why `signal_versions_read` matters:** This field makes stale-read conflicts auditable after the fact. If a REASONING segment was written based on a signal that had already been updated, this field surfaces that — even if it couldn't be prevented in real time.

### 2.3 Signal Node

```typescript
interface SignalNode {
  id: SignalID;
  episode_id: EpisodeID;

  // Classification — these drive storage tier assignment
  retention: SignalRetention;           // EPHEMERAL | PERSISTENT | STRUCTURAL
  causal_role: SignalCausalRole;        // causal | contextual | observational | ephemeral

  // Spine placement
  spine_placement: SpinePlacement;      // SPINE | MANIFEST_ONLY
  spine_position: uint32 | null;        // Position if SPINE-placed

  // Versioning (PERSISTENT signals only)
  version: uint32;                      // Increments on update
  supersedes: SignalID | null;          // Previous version

  // Content
  signal_type: string;
  payload_hash: Hash;
  payload_ref: StorageRef | null;       // null for EPHEMERAL

  // Timing
  occurred_at: Timestamp;
  recorded_at: Timestamp;

  node_hash: Hash;
}
```

### 2.4 Episode Seal

```typescript
interface EpisodeSeal {
  episode_root_hash: Hash;
  spine_hash: Hash;
  signal_manifest_hash: Hash;

  sealed_by: AgentRef;
  sealed_at: Timestamp;
  protocol_version: SemanticVersion;
  nonce: bytes16;                       // Prevents replay

  signature: Signature;                 // Over all above fields
  signature_algorithm: string;          // "Ed25519" recommended

  seal_hash: Hash;
}
```

### 2.5 Crystallization Node

```typescript
interface CrystallizationNode {
  id: CrystallizationID;
  sequence_number: uint64;              // Global crystallization sequence
  prior_crystal_hash: Hash | null;      // null only for genesis crystallization

  // Scope
  episode_ids: EpisodeID[];
  episode_range: {
    first_episode: EpisodeID;
    last_episode: EpisodeID;
    episode_count: uint32;
  };

  // Commitment
  chain_root_hash: Hash;                // MerkleRoot over episode seals
  episode_seal_hashes: Hash[];          // Ordered

  // Finalization
  crystallized_at: Timestamp;
  witness_signatures: Signature[];      // N-of-M for enforcement
  external_anchor: ExternalAnchorRef | null; // Blockchain/RFC 3161 timestamp

  node_hash: Hash;
}
```

> **`prior_crystal_hash` is non-negotiable.** Without it, crystallizations are isolated snapshots. With it, they form a verifiable history chain. An auditor can prove not just that a crystallization exists, but that it existed in a specific sequence relative to all others.

---

## 3. Lifecycle State Machine

```
CREATED ──────────────────────────────────────────────────────►
    Mutable. Segments being appended. Local writes only.
    Clock: wall-time acceptable.
    Coordination: low — typically single writer.
    ↓

ACTIVE ────────────────────────────────────────────────────────►
    Spine being extended. Distributed writes possible.
    Clock: MUST use logical ordering (Lamport/vector clocks).
    Coordination: spine lock required per append.
    ↓

SEALING ───────────────────────────────────────────────────────►  ← NEW STATE
    Soft write lock. In-flight writes must complete or abort.
    Timeout: if writes don't complete within T, they're aborted.
    No new segments accepted.
    Clock: frozen at SEALING initiation.
    ↓

SEALED ────────────────────────────────────────────────────────►
    Episode frozen. Seal hash is the temporal commitment.
    Post-seal annotations possible via separate post-seal spine.
    (Original seal integrity preserved — annotations don't modify it.)
    ↓

ARCHIVED ──────────────────────────────────────────────────────►
    Historical. Read-only. Retention policy governs deletion eligibility.
    Cryptographic proof of compliant deletion required for regulated contexts.
```

### Open Questions for v0.2

1. **Can a SEALED episode receive ANNOTATION segments?** Recommended: yes, via a separate post-seal annotation spine that doesn't modify the original seal. The original seal's integrity is preserved; the post-seal spine has its own hash chain.

2. **What triggers ARCHIVED?** Must be explicit — time-based policy, governance action, or crystallization inclusion. "Archived" cannot be ambiguous in an audit context.

3. **Episode expiration in regulated contexts** — healthcare AI, financial AI will need explicit retention policies with cryptographic proof of compliant deletion.

---

## 4. Storage Architecture

ASTP's storage layer is **inherently polyglot** — not as a preference, but as a structural requirement. The cryptographic integrity and cognitive persistence roles have partially conflicting storage needs. No single store handles both.

### 4.1 Storage Tier Mapping

| Store | Role | What It Owns |
|-------|------|--------------|
| **Neo4j** | Structural memory | Spine graph, episode relationships, crystallization anchors, branch lineage |
| **QDrant** | Semantic memory | Segment embeddings, episode summaries — found by meaning, not ID |
| **Redis** | Working memory | Active session state, spine tip cache, ephemeral signals, write locks |
| **Blob** | Archival memory | Content blobs (CAS), seals, crystallization records — immutable |

### 4.2 Signal Retention → Storage Tier (Direct Mapping)

```
EPHEMERAL  → Redis only (TTL-managed, never touches Neo4j or QDrant)
PERSISTENT → Blob + QDrant (durable, semantically searchable)
STRUCTURAL → Neo4j + Blob (graph relationship + archived record)
```

This is not a design choice — the spec's retention classification *is* the storage routing rule. EPHEMERAL signals must never enter QDrant. Indexing them creates semantic noise that degrades search quality permanently.

### 4.3 Critical Hot Path: Segment Append

```
1. Redis:  Acquire spine lock (SET NX EX 30s)
2. Redis:  Read spine tip → (last_hash, sequence_number)  ← O(1), cache is critical
3. Compute: new_spine_hash = H(LEAF_PREFIX || last_hash || content_hash || meta_hash || seq)
4. Blob:   Write content → segments/{episode_id}/{seq:08d}/{content_hash}.jsonl.gz
5. Neo4j:  CREATE segment node, CREATE PRECEDES relationship
6. QDrant: Upsert segment embedding (ASYNC — can lag)
7. Redis:  Update spine tip cache, release lock
```

> **The spine tip cache is not optional.** Without it, every segment append requires a Neo4j traversal to find the last segment hash. At any meaningful write volume, this becomes the bottleneck. Implement from day one.

### 4.4 Write Ordering Protocol

For every multi-store write:

```
1. Redis  (acquire lock)
2. Blob   (content is immutable — safe to write first, idempotent on retry)
3. Neo4j  (source of truth for structure — "committed" once this succeeds)
4. QDrant (async, eventually consistent — semantic search can lag briefly)
5. Redis  (release lock, update cache — reflects committed state)
```

### 4.5 Blob Key Determinism

Blob keys must be deterministic from content hashes, not UUIDs:

```python
def segment_blob_key(episode_id: str, seq: int, content_hash: str) -> str:
    return f"segments/{episode_id}/{seq:08d}/{content_hash}.jsonl.gz"
```

This gives free deduplication, integrity verification from the key itself, and idempotent retry on failure.

### 4.6 Crystallization Immutability Enforcement

"Immutable" must be a cryptographic guarantee, not a policy claim:

1. **Append-only storage:** Crystallization records stored in write-once infrastructure
2. **Witness requirement:** N-of-M signatures required before finalization
3. **External anchoring:** Hash published externally (blockchain or RFC 3161 timestamp) before internal finalization

Without all three, an attacker with storage access can rewrite history.

---

## 5. Coordination & Conflict Resolution

### 5.1 The Spine as Serialization Point

The hash chain's most important coordination property: **it cannot be written concurrently without conflict**. Every segment append must know the previous hash. This surfaces concurrency conflicts rather than hiding them — which is correct behavior for a cognitive integrity protocol.

### 5.2 Conflict Scenarios & Resolutions

| Scenario | Risk Level | Resolution |
|----------|-----------|------------|
| Concurrent spine appends | **Critical** | Rebase model — spine is a rebase target, not a merge target |
| Stale signal reads | Subtle | Causal versioning — `signal_versions_read` in segment metadata |
| Seal race (write during sealing) | **Critical** | SEALING intermediate state + soft write lock |
| Collaboration divergence | Semantic | Designated coordinator Faculty per COLLABORATION segment |
| Branch/crystallization conflict | Complex | Branch expiry on crystallization (grace period → DIVERGED) |

### 5.3 The Rebase Model

```
Faculty_A appends Segment_8a on top of Segment_7
Faculty_B appends Segment_8b on top of Segment_7 (conflict)

Resolution:
1. Detect conflict (hash mismatch at append time)
2. Serialize: one Faculty's segment wins position 8
3. Losing Faculty rebases: re-appends on top of winning segment (position 9)
4. Original attempt is logged, not discarded — audit trail preserved
```

The Spine is a **rebase target, not a merge target.** This is closer to Git's rebase model than its merge model, and for the same reason: linear history is the integrity guarantee.

### 5.4 The Two-Phase Seal Protocol

```
Phase 1 — ACTIVE → SEALING:
  - No new writes accepted
  - In-flight writes complete or abort (timeout: configurable, default 30s)
  - Aborted writes become candidates for post-seal annotation

Phase 2 — SEALING → SEALED:
  - Compute spine root, signal manifest root, episode root
  - Write seal to Blob
  - Update Neo4j status to SEALED
  - Invalidate Redis draft and spine tip cache
```

### 5.5 The CONSULTATION Pattern

For cross-Faculty coordination, CONSULTATION is the safest primitive:

```
Faculty_A writes: CONSULTATION segment (request)
Faculty_B reads:  CONSULTATION segment
Faculty_B writes: ANNOTATION or ARTIFACT (response)
Faculty_A reads:  response

No concurrent writes. Clear causal ordering. Fully auditable.
```

Design Faculty interactions as CONSULTATION chains wherever possible. Reserve COLLABORATION for cases where true concurrent contribution is genuinely necessary.

---

## 6. Verification & Selective Disclosure

### 6.1 Verification Surfaces

| Surface | Question Answered | Mechanism |
|---------|------------------|-----------|
| Segment-level | "Was this reasoning tampered with?" | Spine hash chain |
| Episode-level | "Was this work completed honestly?" | Tripartite Seal |
| Chain-level | "Is the history unbroken?" | Crystallization chain |

### 6.2 Selective Disclosure

The Spine enables graduated disclosure without revealing full episode content:

| Disclosure Level | Reveals | Proof Type |
|-----------------|---------|------------|
| Existence | Episode ID was sealed | Membership proof |
| Lifecycle | Reached SEALED at time T | Seal signature + timestamp |
| Signal influence | Specific signals affected episode | Manifest inclusion proof |
| Segment presence | Segment S exists at position N | Spine inclusion proof |
| Segment content | Full content of segment S | Direct disclosure + proof |
| Full episode | All segments, all signals | Complete tree revelation |

REASONING segments deserve special protection. An agent's internal chain-of-thought may contain exploratory hypotheses, rejected conclusions, or proprietary reasoning strategies. The Spine allows proving a reasoning segment exists at position N with hash H — without revealing its content.

### 6.3 Agent Identity & Key Management

```
Root Identity Key (offline, rarely used)
    └── Episode Signing Key (rotatable, per-session or per-period)
            └── Segment Attestation Key (can be ephemeral)
```

**Key rotation must not break historical verification.** The `key_commitment` field on EpisodeNode commits to the public key that will seal the episode at creation time. Even if that key is later rotated or revoked, historical seals remain verifiable.

### 6.4 Multi-Agent Attestation

COLLABORATION segments require counter-signatures:

```
collaboration_segment = {
  content: ...,
  primary_signature:  AgentA.sign(content),
  counter_signature:  AgentB.sign(content || primary_signature)
}
```

This prevents one agent from falsely claiming another participated.

---

## 7. Protocol Versioning

### 7.1 Protocol-Level Versioning

```
0.1.0-draft    — Working draft, breaking changes expected
0.x.x-draft    — Stabilization, core concepts locked
1.0.0-rc       — Release candidate, adapter implementations begin
1.0.0          — Stable, backward compatibility guaranteed
```

The jump to 1.0.0 is gated on at least one complete adapter implementation stress-tested against real workloads.

### 7.2 Instance-Level Versioning

```
Episode Version:   [episode_id].[seal_sequence]
Segment Version:   [episode_version].[segment_ordinal]
Artifact Version:  [segment_version].[artifact_hash_prefix]
```

### 7.3 Schema Evolution Rules

```
MINOR version bumps: additive fields only (new optional fields)
MAJOR version bumps: require migration adapter
  - Old episodes retain their original schema version
  - Verifiers must support N-2 versions minimum
  - Crystallizations lock in the schema version at commit time
```

---

## 8. Open Questions for v0.2.0

The following require explicit resolution before the protocol can be considered stable:

| # | Question | Impact |
|---|----------|--------|
| 1 | **Crystallization semantics for active episodes** — Does crystallization force a seal? Allow partial capture? | High — affects all multi-episode workflows |
| 2 | **Distributed clock model** — Logical vs. wall-clock needs an explicit protocol position | High — affects all multi-agent coordination |
| 3 | **Post-seal annotation model** — How is history amended without being rewritten? | Medium — affects audit and correction workflows |
| 4 | **Branch creation semantics** — From any segment? Only from spine tips? | High — affects all branching workflows |
| 5 | **Branch expiry on crystallization** — Grace period duration? DIVERGED branch semantics? | Medium — affects long-running branch workflows |
| 6 | **Signal versioning** — Do PERSISTENT signals have version history or just current value? | Medium — affects causal audit fidelity |
| 7 | **Collaboration coordinator role** — In-protocol or implementation-defined? | Medium — affects multi-agent authorship |
| 8 | **External anchoring strategy** — Blockchain? RFC 3161? Implementation-defined? | High — affects external auditability claims |
| 9 | **Regulated context retention** — Cryptographic proof of compliant deletion | High for regulated deployments |
| 10 | **Audit chain integrity** — The audit log itself needs hash-chaining | High — without it, audit records can be modified |

---

## 9. Design Principles Summary

These principles should guide every implementation decision:

1. **Ordering is integrity.** Position in the Spine is not metadata — it is part of the cryptographic commitment. Any operation that could reorder segments without detection is a protocol violation.

2. **The Spine surfaces conflicts; it does not hide them.** Concurrent write conflicts are detectable by design. Implementations should surface them loudly, not resolve them silently.

3. **Immutability is enforced, not promised.** "Immutable" is a cryptographic guarantee backed by write-once storage, witness signatures, and external anchoring — not a policy claim.

4. **History is amended, not rewritten.** Errors are corrected by appending annotations, not by modifying past segments. The audit trail of the error is itself valuable.

5. **The query index is derived, not authoritative.** QDrant and Redis caches can be rebuilt from Neo4j and Blob at any time. Neo4j is authoritative for structure; Blob is authoritative for content. Index corruption affects availability, not integrity.

6. **CONSULTATION before COLLABORATION.** Cross-Faculty interactions should default to the CONSULTATION pattern (clear handoff, no concurrent writes) and escalate to COLLABORATION only when genuinely necessary.

7. **External anchoring closes the self-attestation gap.** Without external anchoring of crystallization records, ASTP provides integrity guarantees *within* the system but cannot prove to an external auditor that records weren't retroactively constructed.

---

*Project Ariadne gives agents the thread that leads back through the labyrinth of their own reasoning — verifiable, ordered, and true.*