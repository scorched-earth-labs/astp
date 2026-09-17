> **HISTORICAL — retained for provenance. Superseded by [`SPEC.md`](../../SPEC.md); do not implement from this document.**
>
> This is the original specification, `0.1.0-draft` (2026-04-07), with an Episode-centric model. Superseded by the v2.x rewrite of `SPEC.md` (2.0.0-draft, 2026-04-09), which made `CognitiveNode` the protocol primitive, and by every version since.

# Ariadne Protocol Specification

**Version:** 0.1.0-draft
**Status:** Working Draft
**Authors:** Scorched Earth Labs
**Date:** 2026-04-07

## 1. Abstract

Ariadne is a cognitive persistence protocol for multi-agent AI systems. It provides a standardized, verifiable record of agent state transitions — what agents did, what state resulted, and cryptographic proof that the record hasn't been tampered with.

The protocol is agnostic to cognitive architecture. A system using BDI, ReAct, chain-of-thought, SOAR, or any other reasoning model can implement Ariadne without inheriting assumptions about how agents think. Ariadne records *that* agents reasoned and *what* resulted — not *how* they reasoned.

The core contribution is a hash-chained state tree with governance rules that guarantee auditability, integrity, and coordination across distributed writes. The protocol defines *what* invariants must hold; adapters define *how* to enforce them in specific databases.

## 2. Terminology

| Term | Definition |
|------|-----------|
| **Episode** | A bounded unit of agent work. Contains segments, signals, and metadata. Has a lifecycle: CREATED → ACTIVE → SEALED → ARCHIVED. |
| **Segment** | An ordered, immutable content unit within an episode. Types: CONVERSATION, REASONING, ARTIFACT, ANNOTATION, CONSULTATION, COLLABORATION. |
| **Signal** | An external event that influences an episode. Classified by retention (EPHEMERAL/PERSISTENT/STRUCTURAL) and causal role (causal/contextual/observational/ephemeral). |
| **Seal** | A cryptographic commitment that freezes an episode. Contains the spine hash, signal manifest hash, and episode root hash. |
| **Spine** | The ordered hash chain of segments and SPINE-placed signals within an episode. The Merkle root of the spine is the episode's integrity fingerprint. |
| **Crystallization** | A protocol-level state transition that captures a point-in-time integrity snapshot of the episode chain. Immutable once written. |
| **WIL** | Write Intent Log. A coordination protocol for multi-store writes that guarantees ordering and recoverability. |
| **Adapter** | A database-specific implementation of the persistence operations. The protocol defines the contract; the adapter fulfills it. |
| **ASI** | Adapter Service Interface. The abstract contract that any conforming adapter must implement. |
| **Governance Rule** | A protocol invariant (G-1 through G-9) that any conforming implementation must enforce. Violations are structural errors, not application errors. |

## 3. Data Model

### 3.1 Episode

The root container for a unit of agent work.

```
EpisodeNode {
  episode_id:              UUID        (unique, immutable after creation)
  schema_version:          string      (protocol version, e.g. "1.1.0")
  agent_id:                string      (FK to agent identity)
  opened_at:               datetime    (UTC)
  sealed_at:               datetime?   (null until sealed)
  archived_at:             datetime?   (null until archived)
  episode_status:          EpisodeStatus
  crystallization_status:  CrystallizationStatus?
  participants:            string[]    (agent_ids involved)
  spine_hash:              string?     (Merkle root; null until sealed)
  spine_fingerprint:       string?     (Adaptive Merkle fingerprint)
  spine_depth:             int?        (Merkle tree depth)
  signal_manifest_hash:    string?     (null until sealed)
  episode_root_hash:       string?     (null until sealed)
  parent_episode_id:       UUID?       (for branched episodes)
  workspace_id:            string?     (links to external workspace)
  title:                   string?     (human-readable)
  context_note:            string?     (cognitive anchor)
  episode_mode:            string      ("directed" | "collaborative")
}
```

**Episode Status Lifecycle:**

```
CREATED → ACTIVE → CLOSING → CLOSING_PENDING_SEAL → SEALED → ARCHIVED
                 ↘ CRYSTALLIZATION_PENDING → CRYSTALLIZED ↗
```

### 3.2 Segment

An ordered, immutable content unit within an episode.

```
SegmentNode {
  segment_id:      UUID
  episode_id:      UUID        (FK to episode)
  segment_type:    SegmentType (CONVERSATION|REASONING|ARTIFACT|ANNOTATION|CONSULTATION|COLLABORATION)
  sequence_index:  int         (immutable after creation; defines spine order)
  content_hash:    string      (SHA3-256 of serialized content)
  content_ref:     string      (storage pointer URI)
  content_text:    string?     (durable content on node)
  authored_at:     datetime    (UTC)
  author:          string      (agent_id)
  retention_tier:  RetentionTier (PERSISTENT|EPHEMERAL)
}
```

**Retention semantics:** PERSISTENT segments are included in the spine hash. EPHEMERAL segments are excluded — they exist for operational context but are not part of the cryptographic record.

**Content storage model:** Segments have two content fields that serve distinct purposes:

- `content_ref` (required): A storage pointer URI that identifies where the full serialized content is stored. The blob at this URI is the source of truth for `content_hash` computation. A conforming implementation MUST be able to resolve a `content_ref` to retrieve the original content independently of the graph node.
- `content_text` (optional): A durable copy of the content stored directly on the graph node. When present, this enables graph-local reads without a blob store round-trip. When both are present, `content_hash` is always computed from the blob at `content_ref`, not from `content_text`. Adapters MAY populate `content_text` for query convenience but MUST NOT rely on it as the canonical content source.

The `content_ref` URI scheme is implementation-defined. The protocol requires only that the URI is resolvable by the adapter that created it and that the content at the URI produces the same `content_hash` recorded on the segment.

### 3.3 Signal

An external event that influences an episode.

```
SignalNode {
  signal_id:              UUID
  episode_id:             UUID
  signal_type:            SignalType    (EPHEMERAL|PERSISTENT|STRUCTURAL)
  signal_class:           SignalClass   (causal|contextual|observational|ephemeral)
  signal_source:          string
  received_at:            datetime
  signal_status:          SignalStatus  (RECEIVED|VALIDATED|COMMITTED|ATTESTED|EXCLUDED)
  content_hash:           string
  content_ref:            string?       (null for EPHEMERAL)
  placement:              SignalPlacement (SPINE|BRANCH_LEAF|EXCLUDED_MANIFEST)
  placement_rationale:    string?       (REQUIRED if EXCLUDED_MANIFEST)
  influenced_segments:    string[]      (segment UUIDs)
  persistence_confirmed:  bool
}
```

**Dual taxonomy:** Signals are classified on two independent axes:
- **Type** (retention): How long the signal persists
- **Class** (causal role): How the signal influences the episode

### 3.4 Seal

A cryptographic commitment that freezes an episode.

```
SealNode {
  seal_id:                       UUID
  episode_id:                    UUID
  sealed_at:                     datetime
  sealed_by:                     string (agent_id)
  spine_hash:                    string (SHA3-256 Merkle root)
  signal_manifest_hash:          string
  exclusion_hash:                string
  episode_root_hash:             string (H(spine || manifest || exclusion))
  write_intent_id:               UUID   (WIL entry that coordinated this seal)
  seal_status:                   SealStatus (PENDING|COMMITTED|VERIFIED|DISPUTED)
}
```

### 3.5 Consultation

A cross-agent exchange recorded as a first-class protocol node.

```
ConsultationNode {
  consultation_id:         UUID
  episode_id:              UUID        (initiating agent's episode)
  consultation_type:       ConsultationType (advisory|delegated|collaborative|escalation)
  initiating_agent:        string
  consulting_agent:        string
  initiated_at:            datetime
  resolved_at:             datetime?
  initiating_context_hash: string
  consultation_prompt:     string      (stored directly)
  consultation_prompt_hash: string
  resolution_hash:         string?
  consultation_node_hash:  string?     (H(initiation || resolution))
}
```

Consultations form a hash chain of ExchangeEntry nodes:

```
ExchangeEntry {
  entry_id:          UUID
  consultation_id:   UUID
  sequence:          int
  speaker:           string
  role:              ExchangeRole (initiator|consultant|participant)
  content:           string
  content_hash:      string
  previous_hash:     string     ("GENESIS" for entry 0)
}
```

### 3.6 Document, Codicil, Amendment

**DocumentNode:** Verifiable attachment with content hash integrity.

**CodicilNode:** Bounded addendum to a CLOSED episode. Appended, never integrated into the sealed record.

**AmendmentLink:** Links a new episode to a sealed source. The original remains sealed; the new episode inherits context.

## 4. Hash Chain

### 4.1 Hash Algorithm

All hashing uses **SHA3-256** (Keccak). This is a protocol-level commitment: changing the hash algorithm requires a schema version bump.

### 4.2 Domain Separation

To prevent second-preimage attacks across tree levels:
- Leaf nodes: `SHA3-256(b"LEAF:" + content)`
- Internal nodes: `SHA3-256(b"NODE:" + left + right)`

### 4.3 Spine Hash (Merkle Root)

The spine hash is the Merkle root over ordered segments and SPINE-placed signals:

1. Collect segment content hashes, ordered by `sequence_index` ASC
2. Collect SPINE signal content hashes, ordered by `received_at` ASC
3. Construct a binary Merkle tree with domain-separated leaf and node hashing
4. The root of this tree is the `spine_hash`

### 4.4 Adaptive Merkle Tree

The protocol includes an adaptive Merkle tree that extends the standard static construction with:

1. **Ordering function** — Leaves sorted by configurable criteria (chronological, importance) before tree construction
2. **Selective recalculation** — O(log n) updates when data is appended or changed; only the affected branch path is recomputed
3. **Compact fingerprint** — Leftmost branch array extracted as a fixed-format hexadecimal string for efficient external verification
4. **Threshold significance detection** — Comparing two fingerprints reveals the importance of changes: earlier differences indicate more significant structural changes

The adaptive tree produces an identical root hash to the standard static construction but supports incremental operations and compact comparison.

### 4.5 Episode Root Hash

```
episode_root_hash = SHA3-256(
  b"NODE:" + spine_hash + signal_manifest_hash + exclusion_hash
)
```

This three-component root captures the complete integrity state of a sealed episode.

### 4.6 Consultation Hash Chain

Exchange entries form a hash chain: each entry's `previous_hash` references the prior entry's `content_hash`. Entry 0 uses `"GENESIS"` as its `previous_hash`.

```
consultation_node_hash = SHA3-256(
  b"NODE:" + initiation_hash + resolution_hash
)
```

## 5. Governance Rules

These invariants MUST be enforced by any conforming implementation. Violations are structural errors that indicate protocol non-conformance.

### G-1: Write Guard

No segment or signal may be written to an episode in SEALING, SEALED, or ARCHIVED status.

### G-2: Crystallization Lock Guard

No segment or signal may be written to an episode in CRYSTALLIZATION_PENDING status. The episode is frozen for integrity verification during this window. Writes are rejected until crystallization completes (transitions to CRYSTALLIZED) or is rolled back (reverts to ACTIVE).

### G-3: Crystallization Immutability

Crystallization delta nodes are immutable after creation. No field on a `CrystallizationDeltaNode` may be modified after it is persisted. Erroneous crystallizations are corrected via successor episodes, not in-place amendment. The original record is preserved in the historical chain.

### G-4: Signal Classification Constraints

The dual taxonomy (type x class) has composition rules that prevent semantically incoherent combinations:

- STRUCTURAL signals MUST have `signal_class=causal` (structural signals are by definition causal)
- EPHEMERAL/causal signals MUST use BRANCH_LEAF placement, not SPINE (ephemeral causal influence is recorded but not included in the integrity chain)

### G-5: Exclusion Rationale

`placement_rationale` is REQUIRED when a signal's placement is EXCLUDED_MANIFEST. The protocol demands an auditable reason for every exclusion.

### G-6: Hash Chain Integrity

Once a `content_hash`, `spine_hash`, or `episode_root_hash` is persisted, it MUST NOT be modified. These hashes are cryptographic commitments. If the underlying content changes (which itself may be a governance violation), the hash must not be retroactively updated. Integrity verification relies on the immutability of these fields.

### G-7: Causal Edge Requirement

Signals with `signal_class=causal` REQUIRE a TRIGGERED edge to at least one segment. Causal signals without demonstrated influence are a protocol violation.

### G-8: Initiation Before Exchange

Exchange entries may not exist without a prior `initiation_hash` on the consultation node. The branch point must be recorded before any exchange occurs.

### G-9: Resolution Requires Entries

A consultation cannot be resolved (have a `resolution_hash`) without at least one exchange entry. Empty resolutions are meaningless and prohibited.

## 6. Crystallization Protocol

Crystallization is a state transition IN the episode chain, not a receipt ABOUT it. Each crystallization produces a `CrystallizationDeltaNode` — structurally analogous to a blockchain block header.

### 6.1 Version Vector

Three-layer versioning tracks episode evolution:

| Layer | Increments on | Purpose |
|-------|--------------|---------|
| `content_version` | APPEND, MODIFY, BRANCH, MERGE | Content changes |
| `lifecycle_version` | CRYSTALLIZATION, ARCHIVE, EXPIRY | Lifecycle transitions |
| `chain_version` | All deltas | Spine position |

Crystallization increments `lifecycle_version` and `chain_version` but NOT `content_version` — episode content is unchanged by crystallization.

### 6.2 Delta Construction

```
content_hash = SHA3-256(canonical_json(CrystallizationContent))
node_hash    = SHA3-256(b"LEAF:" + content_hash + predecessor_hash)
```

The `predecessor_hash` is a causal link (what came before). The `sealed_chain_root` is an integrity assertion (what the chain looks like). In re-crystallization scenarios these diverge; that divergence is meaningful audit data.

### 6.3 Two-Phase Verification

**Phase 1:** Verify `node_hash` consistency — recompute from `content_hash` and `predecessor_hash` and compare to stored `node_hash`.

**Phase 2:** Verify `sealed_chain_root` — reconstruct the Merkle root from current segment and signal hashes and compare to the stored root.

Both phases must pass for the crystallization to be verified.

### 6.4 Ordering Constraint

A new crystallization delta's `chain_position` must be strictly greater than any prior delta. New content must exist since the last crystallization — re-crystallizing without new content is a governance error.

## 7. Write Intent Log (WIL)

The WIL is a coordination protocol for multi-store writes. It guarantees ordering, recoverability, and the provisional state invariant.

### 7.1 Three Storage Invariants

1. **The ephemeral coordinator is not a persistent store.** The WIL coordinator (e.g., Redis in the reference implementation) manages in-flight write state but is not durable. Loss of coordinator state is recoverable from the authoritative store.
2. **Write ordering is a formal invariant.** Writes proceed in strict durability order: durable content store → authoritative structural store → ephemeral coordinator → semantic search index. This ordering guarantees that the most durable store is always written first. Degradation of lower-priority stores (e.g., semantic search) is always recoverable from higher-priority stores. In the reference implementation: Blob → Neo4j → Redis → QDrant.
3. **Provisional state never enters persistent storage.** Data in the provisional window may only exist in the ephemeral coordinator. It must be crystallized before writing to any durable store.

### 7.2 Three-Phase Write Protocol

**Phase 1 — INTENT_DECLARED:** Create a WIL entry with `completed_at=null`. This declares the write intent before any mutation occurs.

**Phase 2 — WRITE_EXECUTION:** Execute writes in mandatory order, recording each store completion. If a write fails mid-sequence, the WIL entry records the last completed store for recovery.

**Phase 3 — COMPLETION:** Mark the WIL entry complete and graduate it from the ephemeral coordinator (Redis) to the durable store (Neo4j). Delete the ephemeral entry.

### 7.3 Recovery

On startup and periodically, scan for WIL entries with `completed_at=null`. These represent interrupted writes. The `last_completed_store` field indicates where to resume. All writes are idempotent — re-execution is safe.

### 7.4 Ephemeral Coordinator TTL Policy

Every key written to the ephemeral coordinator MUST carry an explicit TTL. Keys without a TTL policy entry are a governance violation. This prevents coordinator state from accumulating unboundedly and ensures that interrupted writes are eventually visible to recovery scanners.

The reference implementation uses Redis with the following key patterns and TTLs:

| Pattern | TTL | Rationale |
|---------|-----|-----------|
| `ariadne::episode::{id}` | 4 hours | Session lifetime max |
| `ariadne::branch::{id}` | 2 hours | Branch lifetime max |
| `ariadne::merkle::{id}` | 15 minutes | Renewed on verification |
| `ariadne::manifest::{id}` | Provisional window | Configurable (default 4h) |
| `ariadne::wil::{id}` | 24 hours | Before graduation to durable store |
| `ariadne::consultation::{id}` | 4 hours | Same as episode |

Alternative coordinator implementations MUST define equivalent TTL policies appropriate to their storage mechanism.

## 8. Adapter Requirements

A conforming adapter MUST:

1. Implement the `AriadneAdapter` interface (see `ariadne/adapters/base.py`)
2. Enforce all governance rules (G-1 through G-9, classification constraints, lock guards)
3. Preserve hash chain integrity — never modify `content_hash`, `spine_hash`, or `episode_root_hash` after creation
4. Respect write ordering invariants when spanning multiple stores
5. Support idempotent writes for WIL recovery
6. Fail loudly on errors — never silently swallow writes

A conforming adapter SHOULD:

1. Provide schema initialization (constraints, indexes) appropriate to the database
2. Support both async and sync operation modes
3. Log when operations are skipped due to feature flags

A conforming adapter MAY:

1. Implement additional query operations beyond the ASI minimum
2. Add database-specific optimizations (e.g., batch operations, connection pooling)
3. Support additional storage backends for the WIL coordinator role (not just Redis)

## 9. Schema Version

The current schema version is `1.1.0`. The hash algorithm (SHA3-256) is locked for the current schema version. Changing the hash algorithm requires a schema version bump.

Schema version is recorded on:
- Episode nodes (`schema_version` field)
- Consultation nodes (`schema_version` field)
- Crystallization delta nodes (via `CrystallizationContent.schema_version`)
- The schema version seed node in the database

## 10. Agent-Directed Retrieval

Ariadne defines a read-path interface that is the complement of the WIL write-path. Where WIL governs how state is written into the Episode, the agent retrieval interface governs how agents pull content back out.

Agent-directed retrieval replaces prompt injection as the mechanism for providing agents with Episode context. Rather than pushing pre-truncated history into the prompt before an agent evaluates the turn, agents issue tool calls to retrieve exactly what the current turn requires.

### 10.1 Retrieval Interface

A conforming adapter MUST implement three retrieval operations:

**get_segment_by_id** — retrieve a single segment by ID, scoped to episode. Episode scoping MUST be enforced: a segment query against episode A must never return a segment belonging to episode B.

**get_segment_range** — retrieve a contiguous range of segments by sequence_index (inclusive). Supports optional filtering by segment_type and author. Returns ordered by sequence_index ASC.

**get_episode_spine** — retrieve the most recent N segments. Supports before_index scoping (return segments before a given spine position), optional segment_type filter, and optional retention_tier filter. Returns ordered by sequence_index ASC.

### 10.2 Return Contract

All retrieval operations return segment records containing: segment_id, episode_id, sequence_index, segment_type, author, authored_at, content_ref, content_text, retention_tier.

`content_text` MUST be returned verbatim — no truncation, summarization, or modification. The retrieval layer is not permitted to make decisions about what content is relevant. That determination belongs to the agent.

### 10.3 Episode Scoping

All retrieval operations are scoped to a single episode_id. Cross-episode retrieval is not part of the core retrieval interface. Adapters MUST enforce episode scoping at the query level, not in application code.

## 11. Conformance Testing

The `ariadne.core.contracts` module provides a three-layer coherence measurement framework for verifying adapter conformance:

| Layer | What it verifies |
|-------|-----------------|
| **Structural** | Hash chain integrity, governance rule enforcement, Merkle root consistency |
| **Contextual** | Segment ordering, signal placement, consultation hash chains |
| **Experiential** | End-to-end episode lifecycle (create → populate → seal → verify → archive) |

A conforming adapter MUST pass all structural layer checks. Contextual and experiential layers provide additional confidence but are not strict conformance requirements.

To verify a new adapter implementation:

1. Run structural checks: governance rules G-1 through G-9 produce correct errors on violation
2. Run hash integrity checks: `spine_hash` and `episode_root_hash` match reconstructed values
3. Run lifecycle checks: episode transitions follow the status lifecycle without state corruption
4. Run WIL recovery checks: interrupted writes are correctly identified and idempotently resumable

## 12. References

The following references are internal Scorched Earth Labs design documents that informed the protocol design. The protocol specification in this document is self-contained; these references provide historical context for architectural decisions.

| Reference | Decision |
|-----------|----------|
| CLO-CONSOLIDATED-1.1 | Phase 1 architecture synthesis — episode/segment schema, hash chain design |
| OQ-D01 | Write ordering and provisional state invariants |
| OQ-D02 | Crystallization as state transition (not receipt) |
| CLO-03 S3.1 | Dual taxonomy composition rules for signals |
| CLO-06 S6 | Write Intent Log three-phase protocol |
| CLO-08 S8.3 | Redis TTL policy for ephemeral coordinator keys |

---

*Ariadne Protocol is developed by Scorched Earth Labs.*
