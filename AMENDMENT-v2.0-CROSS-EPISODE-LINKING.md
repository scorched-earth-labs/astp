# Cross-Episode Linking & Grouping Interface
## Protocol Amendment — Schema Version 2.0.0

**Supersedes:** Schema v1.x.x  
**Status:** Ratified  
**Episode of Record:** Amendment: Cross-Episode Linking  
**Breaking Changes:** `EpisodeLink`, `MembershipRecord`, `ConformanceDeclaration` hash preimages  
**Compatible Changes:** `LinkHealthState` enum (new value), `AuditEventType` enum (new events)

---

## Amendment Summary

This document records eight gap resolutions identified during structured review of the Cross-Episode Linking Architecture and Episode Grouping Interface artifacts, plus one Chronos addition (§11.3.3 `QUARANTINE_ESCALATED`) and one architectural section (§12 Protocol Scope and Conformance Boundaries). It supersedes the prior schema definitions in both documents. All phase labels are scoped per document (§9).

| Gap | Topic | Schema Impact |
|-----|-------|--------------|
| 1 | `link_strength` / `is_inferred` separation | `EpisodeLink` — two new fields |
| 2 | Named constants for inference thresholds | New Protocol Constants section |
| 3 | Signal combination specification | Implementation-side; no schema change |
| 4 | Orphan link quarantine | `LinkHealthState` — new `QUARANTINED` value; `EpisodeLink` — quarantine fields |
| 5 | Audit coverage for rejected candidates | `AuditEventType` — two new events |
| 6 | `MembershipRecord` immutability | `MembershipRecord` — succession chain fields |
| 7 | Conformance declaration evolution | `ConformanceDeclaration` — versioning and succession fields |
| 8 | Phase label namespace collision | Editorial — scoped labels throughout |
| — | Quarantine escalation | `AuditEventType` — `QUARANTINE_ESCALATED` (Chronos addition, §11.3.3) |
| — | Protocol scope taxonomy | §12 — normative conformance boundary definition |

---

## Part I — Cross-Episode Linking

### §1 Protocol Constants

Named constants replace magic numbers throughout the inference pipeline. These values are protocol-level defaults; calibration is implementation-side (see §12 — behavioral tier).

```
DISCOVERY_THRESHOLD    = 0.75   // minimum composite score to surface a candidate to human review
AUTO_ACCEPT_THRESHOLD  = 0.90   // composite score above which a link may be auto-accepted without human review
```

**Calibration narrative:** Begin conservative. The rejection signal produced by `CANDIDATE_REJECTED` audit events (§5) is the primary input for threshold tuning. A high rejection rate at scores near `DISCOVERY_THRESHOLD` indicates the threshold should be raised; a low proposal rate with known missed links indicates it should be lowered. Threshold adjustment is an implementation decision (§12 behavioral tier); the protocol records the threshold value at the time of each inference event (§12 audit-the-decision pattern).

---

### §2 `EpisodeLink` Node — Amended Schema

```
EpisodeLink {
  // Identity — immutable
  link_id:               UUID
  source_episode:        EpisodeID
  target_episode:        EpisodeID
  created_at:            Timestamp
  created_by:            AgentID

  // Semantic characterization — GAP 1
  link_type:             LinkType              // see §3
  link_strength:         Float [0.0, 1.0]      // semantic similarity score; 0.0 = no semantic relationship, 1.0 = near-identical
  is_inferred:           Boolean               // true = system-generated candidate; false = human-asserted

  // Inference provenance — immutable once set
  inference_signals:     Signal[]              // see §4
  inference_threshold:   Float                 // value of DISCOVERY_THRESHOLD at inference time
  retroactive:           Boolean               // true = link created after source episode crystallization

  // Health state — mutable
  health_state:          LinkHealthState        // VALID | STALE | FROZEN | BROKEN | QUARANTINED
  health_checked_at:     Timestamp
  source_version:        SemVer                // version of source episode at link creation
  target_version:        SemVer                // version of target episode at link creation

  // Quarantine — GAP 4
  quarantine_reason:     Optional<String>
  quarantined_at:        Optional<Timestamp>
  quarantine_resolved_at:    Optional<Timestamp>    // set when quarantine exits
  quarantine_resolution:     Optional<QuarantineResolution>  // CONFIRMED | DISSOLVED | ESCALATED

  // Integrity
  content_hash:          Hash                  // SHA-256 of canonical field set (excludes health_state, health_checked_at, quarantine_resolved_at, quarantine_resolution)
}
```

**Hash preimage note:** `quarantine_resolved_at` and `quarantine_resolution` are excluded from `content_hash`. Resolution fields record lifecycle events after link creation; including them would invalidate the hash on every quarantine close. The audit log (§5) is the authoritative record of quarantine resolution events.

---

### §3 Link Type Taxonomy

| Type | Semantics | Mutual Exclusivity |
|------|-----------|-------------------|
| `CONTINUES_FROM` | Direct continuation of prior episode | ⊕ `SUPERSEDES`, ⊕ `BRANCHES_FROM` |
| `SUPERSEDES` | This episode replaces target | ⊕ `CONTINUES_FROM` |
| `BRANCHES_FROM` | Divergent thread from target | ⊕ `CONTINUES_FROM` |
| `INFORMED_BY` | Prior knowledge dependency, not continuation | — |
| `REFERENCES` | Audit-only citation; non-loading on resumption | — |
| `SPAWNED_FROM` | Task/sub-episode origin | — |
| `MERGED_INTO` | Convergence record | — |
| `PEER_REVIEWED_BY` | Cross-agent review relationship | — |

**Resumption isolation rule:** On episode resumption, the loader MUST follow `CONTINUES_FROM` and `SUPERSEDES` links (spine traversal) and MAY follow `INFORMED_BY` and `SPAWNED_FROM` links up to one hop. `REFERENCES` links are non-loading — they are available for audit but do not trigger episode content retrieval.

---

### §4 Inference Signal Specification

Signal combination is implementation-side (§12 behavioral tier). The protocol requires that all signals contributing to a candidate's composite score be recorded in `inference_signals` at the time of candidate proposal.

```
Signal {
  signal_type:    SignalType    // SEMANTIC_SIMILARITY | PARTICIPANT_OVERLAP | TEMPORAL_PROXIMITY | EXPLICIT_REFERENCE | SHARED_ARTIFACT
  signal_weight:  Float         // weight applied to this signal in composite score computation
  signal_value:   Float         // raw signal value before weighting
  computed_at:    Timestamp
}
```

**Audit-the-decision pattern (§12):** The protocol does not mandate how signals are combined. It mandates that the combination — which signals, which weights, which threshold — is recorded. This record is the basis for calibration and retrospective audit.

---

### §5 Audit Event Types — Cross-Episode Linking

```
AuditEventType (linking):
  LINK_PROPOSED          // inference candidate surfaced; score >= DISCOVERY_THRESHOLD
  LINK_ACCEPTED          // human-confirmed or auto-accepted (score >= AUTO_ACCEPT_THRESHOLD)
  LINK_REJECTED          // human-rejected candidate — GAP 5
  CANDIDATE_REJECTED     // inference candidate below threshold, not surfaced — GAP 5
  LINK_HEALTH_CHANGED    // health state transition recorded
  LINK_QUARANTINED       // link moved to QUARANTINED state — GAP 4
  LINK_QUARANTINE_RESOLVED   // quarantine exited (CONFIRMED | DISSOLVED | ESCALATED) — GAP 4
  QUARANTINE_ESCALATED   // quarantine escalated to human review after TTL — Chronos §11.3.3
```

**`CANDIDATE_REJECTED` note:** This event fires when an inference candidate is computed but falls below `DISCOVERY_THRESHOLD` and is therefore not surfaced for human review. Recording it enables retrospective analysis of the threshold calibration — if known-good links were suppressed, the threshold was too high.

---

### §6 Link Health State Machine

```
LinkHealthState:
  VALID        // target episode exists and version delta is within tolerance
  STALE        // target episode has advanced by minor/patch version since link creation
  FROZEN       // target episode is crystallized; link is permanently anchored to crystallized version
  BROKEN       // target episode unreachable or deleted
  QUARANTINED  // link flagged for integrity review; excluded from active traversal — GAP 4
```

**State transitions:**

```
VALID       → STALE        (target minor/patch version advance)
VALID       → FROZEN       (target episode crystallizes)
VALID       → BROKEN       (target episode deleted or unreachable)
VALID       → QUARANTINED  (orphan detection or integrity flag)
STALE       → BROKEN       (target episode deleted)
STALE       → QUARANTINED  (orphan detection)
QUARANTINED → VALID        (quarantine resolved: CONFIRMED)
QUARANTINED → BROKEN       (quarantine resolved: DISSOLVED — link invalid)
QUARANTINED → ESCALATED    (quarantine TTL exceeded; human review required — §11.3.3)
BROKEN      → QUARANTINED  (re-evaluation triggered)
```

**Major version advance:** A link where the target episode has advanced by a major version since link creation MUST be routed to human review. The link remains `VALID` or `STALE` during review; it does not automatically transition to `BROKEN`.

---

## Part II — Episode Grouping Interface

### §7 `MembershipRecord` Node — Amended Schema

```
MembershipRecord {
  // Identity — immutable
  record_id:             UUID
  episode_id:            EpisodeID
  group_id:              GroupID
  group_system:          String           // "claude_project" | "notion_database" | "ariadne_native" | ...
  asserted_at:           Timestamp
  asserted_by:           AgentID

  // Membership characterization — GAP 6; included in content_hash
  membership_role:       MembershipRole   // PRIMARY | SUPPORTING | REFERENCE | ARCHIVED

  // Succession — GAP 6
  supersedes_record_id:  Optional<UUID>   // prior MembershipRecord this record replaces
  succession_reason:     Optional<String> // why this record supersedes the prior

  // Integrity — immutable once set
  content_hash:          Hash             // SHA-256 of: record_id + episode_id + group_id + group_system + asserted_at + asserted_by + membership_role
}
```

**Immutability rule:** `MembershipRecord` nodes are append-only. Membership changes are recorded by creating a new `MembershipRecord` with `supersedes_record_id` pointing to the prior record. The prior record is never modified or deleted. The active record for a `(episode_id, group_id)` pair is the record with no `superseded_by_record_id` in the succession chain.

---

### §8 `ConformanceDeclaration` Node — Amended Schema

```
ConformanceDeclaration {
  // Identity — immutable
  declaration_id:        UUID
  group_id:              GroupID
  group_system:          String
  declared_at:           Timestamp
  declared_by:           AgentID

  // Versioning — GAP 7
  declaration_version:   SemVer           // major.minor.patch

  // Capabilities — included in content_hash
  capabilities:          Capability[]

  // Succession — GAP 7; excluded from content_hash
  superseded_by:         Optional<UUID>   // declaration_id of successor

  // Integrity
  declaration_hash:      Hash             // SHA-256 of: declaration_id + group_id + group_system + declared_at + declared_by + declaration_version + capabilities
}
```

**Version semantics — GAP 7:**

| Change type | Version bump | Effect |
|-------------|-------------|--------|
| Field rename, type change, removal | Major | Breaking — existing `MembershipRecord` hashes may be invalid; re-verification required |
| New optional field | Minor | Compatible — existing records remain valid |
| Documentation, threshold change | Patch | Compatible — no schema effect |

**Succession rule:** When a `ConformanceDeclaration` is superseded, the prior declaration is updated with `superseded_by` pointing to the new declaration. The `superseded_by` field is excluded from `declaration_hash` — it is a lifecycle annotation, not a content field.

---

### §9 Phase Label Scoping — GAP 8

Phase labels in this amendment are scoped to their document. There is no global phase namespace.

- **Cross-Episode Linking phases** are labeled: Linking Phase 1, Linking Phase 2, etc.
- **Grouping Interface phases** are labeled: Grouping Phase 1, Grouping Phase 2, etc.

Implementations referencing phases in documentation or tooling MUST use scoped labels. Bare phase numbers (e.g., "Phase 3") without document scope are non-conforming in any context where ambiguity is possible.

---

## Part III — Implementation Coordination, Verification & Lifecycle Governance

### §11 Implementation Architecture

> This section is normative. §11.1–§11.3 specify storage architecture, verification requirements, and lifecycle governance that implementations must honor to claim conformance with Amendment v2.0. §11.4 is the canonical audit event registry. §11.5 specifies consistency requirements.

---

### §11.1 Storage Architecture

#### 11.1.1 Consistency Model

The Ariadne storage layer is a four-tier distributed system. The consistency hierarchy is:

```
PRIMARY TRUTH:   Neo4j       (structural ground truth — synchronous writes)
AUDIT TRUTH:     Blob        (append-only audit history — authoritative for event log)
DISCOVERY:       QDrant      (semantic search — eventually consistent with Neo4j)
WORKING STATE:   Redis       (ephemeral cache and queues — always reconstructable)
```

**Neo4j is the single source of truth for structural state.** No read operation on structural data (link health, membership records, declaration versions) may serve a response that contradicts Neo4j. QDrant and Redis divergence from Neo4j is a consistency error, not an alternative view.

#### 11.1.2 Neo4j Schema (Structural Memory)

New node types and relationships introduced in Amendment v2.0:

```cypher
// Node types
(:EpisodeLink {
  link_id,
  link_strength,              // Float [0.0, 1.0] — Gap 1
  is_inferred,                // Boolean — Gap 1
  health_state,               // LinkHealthState enum — Gap 4
  quarantine_reason,          // Optional<String>
  quarantined_at,             // Optional<Timestamp>
  quarantine_resolved_at,     // Optional<Timestamp> — Gap 4 closure
  quarantine_resolution       // Optional<QuarantineResolution> — Gap 4 closure
})

(:MembershipRecord {
  record_id,
  membership_role,            // included in content_hash — Gap 6
  content_hash,
  supersedes_record_id        // Optional — Gap 6 succession
})

(:ConformanceDeclaration {
  declaration_id,
  declaration_version,        // SemVer — Gap 7
  declaration_hash,
  superseded_by               // Optional — Gap 7 succession; excluded from hash
})

// Relationships
(e1:Episode)-[:LINKED_TO {via: link_id}]->(e2:Episode)
(mr:MembershipRecord)-[:SUPERSEDES]->(mr_prev:MembershipRecord)
(cd:ConformanceDeclaration)-[:SUPERSEDED_BY]->(cd_new:ConformanceDeclaration)
(ep:Episode)-[:MEMBER_OF {record_id}]->(eg:EpisodeGroup)
```

**Active-record index:** Implementations MUST maintain a materialized index for the active `MembershipRecord` per `(episode_id, group_id)` pair — defined as the record with no `superseded_by_record_id`. This is a storage-layer obligation, not a protocol mandate on query strategy.

#### 11.1.3 QDrant Schema (Semantic Discovery)

**Collection: `episode_content_vectors`**

> **Naming note (§11 pushback #1):** This collection was previously named `episode_link_candidates`. That name was a misnomer — candidates are the result of a similarity query, not stored objects. The collection stores per-episode content vectors; candidates emerge at query time.

```json
{
  "collection": "episode_content_vectors",
  "vector_size": 1536,
  "distance": "Cosine",
  "payload_schema": {
    "episode_id": "keyword",
    "spine_version": "keyword",
    "indexed_at": "datetime",
    "discovery_threshold_at_index": "float",
    "auto_accept_threshold_at_index": "float"
  }
}
```

**Threshold payload fields:** `discovery_threshold_at_index` and `auto_accept_threshold_at_index` record the protocol threshold values in effect at the time this vector was indexed. This enables retrospective comparison — if thresholds were recalibrated between index time and query time, the stored values allow an auditor to determine whether a link would have been proposed under the prior regime. This is an audit-the-decision application (§12).

**Collection: `participant_context_vectors`**

```json
{
  "collection": "participant_context_vectors",
  "vector_size": 768,
  "distance": "Cosine",
  "payload_schema": {
    "episode_id": "keyword",
    "participant_id": "keyword",
    "context_type": "keyword"
  }
}
```

**Vector dimension note (§11 pushback #2):** `episode_content_vectors` uses 1536 dimensions (text-embedding-3-large or equivalent); `participant_context_vectors` uses 768 dimensions. The asymmetry is intentional — participant identity signals occupy a smaller semantic space than full episode content, and a reduced-dimension model is appropriate. Implementations MUST NOT mix embeddings from different model families within the same collection.

#### 11.1.4 Redis Schema (Working State)

```
// Quarantine queue — per-Episode
ariadne:quarantine:queue:{episode_id}    ZSET  // score = quarantine_deadline (Unix timestamp)
ariadne:quarantine:ttl                   STRING // default TTL in seconds (implementation-configurable)

// Threshold calibration state
ariadne:calibration:thresholds           HASH  // current DISCOVERY_THRESHOLD, AUTO_ACCEPT_THRESHOLD
ariadne:calibration:history:{date}       LIST  // daily calibration snapshots

// Link health cache
ariadne:link:health:{link_id}            HASH  // cached health_state + checked_at; always reconstructable from Neo4j
```

**Quarantine queue scope (§11 pushback #3):** The quarantine queue is keyed per-Episode (`ariadne:quarantine:queue:{episode_id}`). A single global queue across all Episodes would create scaling problems and scope confusion — a quarantine event in one Episode would be processed in the context of another. Implementations using a global key are non-conforming.

**Redis is always reconstructable.** All Redis state can be rebuilt from Neo4j and Blob. Redis failure does not constitute data loss; it constitutes a consistency window until reconstruction completes.

---

### §11.2 Verification Architecture

#### 11.2.1 Proof Types

Four proof types are defined for this amendment. A fifth (non-existence proof) is flagged as a known gap.

| Proof Type | What It Proves | Primary Storage |
|------------|---------------|-----------------|
| `LINK_INTEGRITY` | `content_hash` matches canonical field set | Neo4j |
| `MEMBERSHIP_CHAIN` | Succession chain is unbroken and hashes are valid | Neo4j |
| `DECLARATION_COMPATIBILITY` | Version transition is compatible (minor/patch) or breaking (major) | Neo4j |
| `AUDIT_COMPLETENESS` | All required audit events are present for a lifecycle | Blob |

**Known gap — non-existence proof (§11 pushback #4):** Proof that no `EpisodeLink` exists between Episode A and Episode B is not specified in this amendment. This is a meaningful proof type — "we never connected these two episodes" is an auditable claim — but specifying it requires additional Merkle commitments not introduced here. Implementations requiring negative-space proofs should treat this as a future amendment item.

#### 11.2.2 `LINK_INTEGRITY` Proof

```
Proof {
  proof_type:     LINK_INTEGRITY
  link_id:        UUID
  claimed_hash:   Hash           // hash stored in EpisodeLink.content_hash
  computed_hash:  Hash           // hash recomputed from canonical fields at proof time
  field_snapshot: {              // canonical fields at proof time
    link_id, source_episode, target_episode, created_at, created_by,
    link_type, link_strength, is_inferred, inference_signals,
    inference_threshold, retroactive, health_state, health_checked_at,
    source_version, target_version, quarantine_reason, quarantined_at
  }
  verified_at:    Timestamp
  verified_by:    AgentID
  result:         VALID | INVALID
}
```

#### 11.2.3 `MEMBERSHIP_CHAIN` Proof

```
Proof {
  proof_type:       MEMBERSHIP_CHAIN
  episode_id:       EpisodeID
  group_id:         GroupID
  chain_length:     Integer        // number of MembershipRecord nodes in succession chain
  chain_hashes:     Hash[]         // content_hash of each record, oldest first
  active_record_id: UUID           // record_id of the active (terminal) record
  verified_at:      Timestamp
  verified_by:      AgentID
  result:           VALID | INVALID | BROKEN_CHAIN
}
```

#### 11.2.4 `DECLARATION_COMPATIBILITY` Proof

```
Proof {
  proof_type:          DECLARATION_COMPATIBILITY
  prior_version:       SemVer
  new_version:         SemVer
  change_classification: COMPATIBLE | BREAKING
  affected_records:    UUID[]      // MembershipRecord IDs requiring re-verification if BREAKING
  verified_at:         Timestamp
  verified_by:         AgentID
  result:              VALID | INVALID
}
```

#### 11.2.5 `AUDIT_COMPLETENESS` Proof

```
Proof {
  proof_type:       AUDIT_COMPLETENESS
  subject_id:       UUID           // link_id or record_id
  subject_type:     EPISODE_LINK | MEMBERSHIP_RECORD
  required_events:  AuditEventType[]
  present_events:   AuditEventType[]
  missing_events:   AuditEventType[]
  verified_at:      Timestamp
  verified_by:      AgentID
  result:           COMPLETE | INCOMPLETE
}
```

#### 11.2.6 Human Ratification Verification

Human ratification of a link or membership record is verified against the crystallization chain entry in the Episode of Record.

**Session record definition:** The session record is the crystallization chain entry in the Episode of Record — the sealed spine position produced by the ratifying agent's ratification commit, verifiable against the Episode's Merkle root. For Devin's approvals within this amendment's Episode, the session record is the sealed spine position at the crystallization event, counter-signed by Devin's approval key.

#### 11.2.7 Encryption at Rest

`MembershipRecord` content is encrypted at rest with a per-Episode key.

**Key derivation dependency:** Per-Episode encryption key derivation is not fully specified in this amendment. Implementations should treat key derivation as a future amendment item; this clause is aspirational pending that specification. The encryption-at-rest requirement stands; the key derivation mechanism is deferred.

---

### §11.3 Lifecycle Governance

#### 11.3.1 Quarantine Lifecycle

```
Quarantine entry:
  1. Orphan detection OR integrity flag triggers LINK_QUARANTINED audit event
  2. EpisodeLink.health_state → QUARANTINED
  3. Link added to ariadne:quarantine:queue:{episode_id} with deadline = now() + ariadne:quarantine:ttl
  4. Link excluded from active traversal during quarantine

Quarantine resolution (before TTL):
  CONFIRMED:  Link validated; health_state → VALID; quarantine_resolved_at + quarantine_resolution set; LINK_QUARANTINE_RESOLVED audit event
  DISSOLVED:  Link invalid; health_state → BROKEN; quarantine_resolved_at + quarantine_resolution set; LINK_QUARANTINE_RESOLVED audit event

Quarantine escalation (TTL exceeded — §11.3.3):
  ESCALATED:  health_state remains QUARANTINED; QUARANTINE_ESCALATED audit event; human review required
```

**Reverse delta for `SECTION_SUPERSESSION` (§11 pushback #7):** Forward deltas are stored as diffs from the prior version. Reverse delta derivation for `SECTION_SUPERSESSION` requires the prior section text — this cannot be derived from the `supersedes_clause` identifier alone. The prior section text is stored at the superseded version's Blob path. The `supersedes_clause` identifies the path; the content is retrieved from Blob, not recomputed. Implementations MUST store prior section content in Blob before recording a supersession.

#### 11.3.2 MembershipRecord Succession Lifecycle

```
Succession entry:
  1. New MembershipRecord created with supersedes_record_id = prior record_id
  2. Prior record updated: superseded_by_record_id = new record_id (lifecycle annotation only; excluded from content_hash)
  3. Active-record index updated to point to new record
  4. Audit event recorded

Succession is irreversible. Prior records are never deleted.
```

#### 11.3.3 Quarantine Escalation — Chronos Addition

```
AuditEvent: QUARANTINE_ESCALATED {
  link_id:           UUID
  episode_id:        EpisodeID
  quarantined_at:    Timestamp
  ttl_deadline:      Timestamp
  escalated_at:      Timestamp
  escalation_reason: String      // "TTL_EXCEEDED" | "INTEGRITY_UNRESOLVABLE" | "HUMAN_REQUIRED"
}
```

Escalated links remain in `QUARANTINED` state. They are not auto-resolved. Human review is required to transition to `CONFIRMED` or `DISSOLVED`.

---

### §11.4 Audit Event Registry

Complete registry of all audit events introduced in Amendment v2.0:

| Event Type | Trigger | Required Fields | Storage |
|------------|---------|-----------------|---------|
| `LINK_PROPOSED` | Candidate score >= DISCOVERY_THRESHOLD | link_id, score, signals, threshold | Blob |
| `LINK_ACCEPTED` | Human confirmation or auto-accept | link_id, accepted_by, method | Blob |
| `LINK_REJECTED` | Human rejection of proposed candidate | link_id, rejected_by, reason | Blob |
| `CANDIDATE_REJECTED` | Candidate below DISCOVERY_THRESHOLD | episode_pair, score, threshold | Blob |
| `LINK_HEALTH_CHANGED` | Health state transition | link_id, prior_state, new_state | Blob |
| `LINK_QUARANTINED` | Link moved to QUARANTINED | link_id, reason, ttl_deadline | Blob |
| `LINK_QUARANTINE_RESOLVED` | Quarantine exited | link_id, resolution, resolved_by | Blob |
| `QUARANTINE_ESCALATED` | Quarantine TTL exceeded | link_id, escalation_reason | Blob |
| `MEMBERSHIP_RECORD_CREATED` | New MembershipRecord asserted | record_id, episode_id, group_id | Blob |
| `MEMBERSHIP_RECORD_SUPERSEDED` | Succession recorded | prior_record_id, new_record_id | Blob |
| `DECLARATION_VERSION_BUMPED` | ConformanceDeclaration versioned | declaration_id, prior_version, new_version, classification | Blob |
| `DECLARATION_SUPERSEDED` | Declaration succeeded | prior_declaration_id, new_declaration_id | Blob |

All audit events are append-only and stored in Blob. Audit events are never modified or deleted.

---

### §11.5 Consistency Requirements

#### 11.5.1 Write Path

```
1. Write to Neo4j (synchronous — must succeed before continuing)
2. Append to Blob audit log (synchronous — must succeed before continuing)
3. Propagate to QDrant (asynchronous — within consistency window)
4. Update Redis cache/queues (asynchronous — within consistency window)
```

Steps 1 and 2 are atomic from the protocol's perspective. A write that succeeds in Neo4j but fails in Blob is a partial write and MUST be retried or rolled back.

#### 11.5.2 Consistency Window SLA (§11 pushback #9)

Implementations MUST define a maximum consistency window for QDrant and Redis propagation.

**Required SLA:**
- Typical propagation: < 60 seconds
- Maximum propagation: 5 minutes

Implementations exceeding the maximum propagation window without a documented exception are non-conforming at the state tier (§12). Implementations MUST expose a consistency status endpoint or mechanism that allows callers to determine whether QDrant/Redis state is within the consistency window.

#### 11.5.3 Sequence Numbers and Timestamps (§11 pushback #8)

Two ordering mechanisms are used in this amendment. They are complementary, not redundant:

- **Sequence numbers** are scoped per-Episode and are the basis for completeness proofs within an Episode. A sequence gap within an Episode's audit log indicates a missing event.
- **Chronos-assigned timestamps** are the basis for ordering across Episodes. Cross-Episode temporal ordering uses timestamps, not sequence numbers, because sequence scopes do not extend across Episode boundaries.

Implementations MUST NOT use sequence numbers for cross-Episode ordering. Implementations MUST NOT use timestamps as the sole basis for within-Episode completeness proofs.

---

## §12 Protocol Scope and Conformance Boundaries

### 12.1 The Three-Tier Taxonomy

This protocol is a contract about externalities. Internal implementation choices are sovereign.

| Tier | What it covers | Conformance |
|------|---------------|-------------|
| **Wire tier** | Schemas, edge types, hash preimages | **Required** |
| **State tier** | Lifecycle enums, audit event types, consistency SLAs | **Required** |
| **Behavioral tier** | Scoring algorithms, embedding choices, threshold tuning, internal indexing | **Not required** |

**Wire tier** conformance makes two implementations interoperable — they can exchange `EpisodeLink`, `MembershipRecord`, and `ConformanceDeclaration` structures and verify each other's hashes.

**State tier** conformance makes audit logs comparable across implementations — a third party can verify lifecycle events and consistency guarantees without knowing implementation internals.

**Behavioral tier** is sovereign. The protocol does not mandate how signals are combined, which embedding model is used, or how thresholds are tuned. These are implementation decisions.

### 12.2 The Audit-the-Decision Pattern

Where implementation choice is permitted at the behavioral tier, the protocol mandates the audit record — what was computed, with which threshold, by which signal — not the value.

This pattern resolves all behavioral-tier questions in this amendment:

| Question | Resolution |
|----------|-----------|
| How are signals combined? | Implementation-side. Record: which signals, which weights, which composite score. |
| Which embedding model? | Implementation-side. Record: model identifier at index time. |
| What threshold values? | Implementation-side. Record: threshold values at inference time. |
| When to recalibrate? | Implementation-side. Record: prior and new threshold values, calibration event. |

**The audit record is the protocol artifact.** The decision is the implementation artifact.

### 12.3 Future Amendment Guidance

Gaps deferred from this amendment that future amendments should address:

1. **Non-existence proofs** — Proof that no `EpisodeLink` exists between two Episodes (§11.2.1)
2. **Per-Episode encryption key derivation** — Key derivation mechanism for `MembershipRecord` encryption at rest (§11.2.7)
3. **Behavioral tier calibration protocol** — Optional (non-required) standard for threshold calibration reporting, enabling cross-implementation comparison without mandating algorithm

---

## Appendix A — Breaking Change Reference

Changes that constitute major version bumps to `ConformanceDeclaration`:

- Renaming any field in `EpisodeLink`, `MembershipRecord`, or `ConformanceDeclaration` that appears in a `content_hash` preimage
- Changing the type of any such field
- Removing any such field
- Changing the hash algorithm or canonical serialization format

Changes that constitute minor version bumps:

- Adding a new optional field to any schema node
- Adding a new `LinkType` value
- Adding a new `AuditEventType`
- Adding a new `LinkHealthState` value

Changes that constitute patch version bumps:

- Documentation corrections
- Threshold default value changes (behavioral tier)
- Editorial clarifications with no schema effect

---

## Appendix B — Conformance Checklist

An implementation claiming conformance with Amendment v2.0 MUST:

**Wire tier:**
- [ ] Implement `EpisodeLink` with all fields in §2, including `link_strength`, `is_inferred`, quarantine fields
- [ ] Implement `MembershipRecord` with `membership_role` in content_hash and succession fields
- [ ] Implement `ConformanceDeclaration` with `declaration_version` and succession fields
- [ ] Compute `content_hash` and `declaration_hash` using specified canonical field sets

**State tier:**
- [ ] Implement all `LinkHealthState` values including `QUARANTINED`
- [ ] Implement all `AuditEventType` values in §11.4
- [ ] Implement quarantine lifecycle including TTL and escalation (§11.3.1, §11.3.3)
- [ ] Key Redis quarantine queue per-Episode: `ariadne:quarantine:queue:{episode_id}`
- [ ] Define and publish consistency window SLA within bounds specified in §11.5.2
- [ ] Use sequence numbers for within-Episode completeness proofs; Chronos timestamps for cross-Episode ordering

**Behavioral tier (sovereign — no conformance requirement):**
- Signal combination algorithm
- Embedding model selection
- Threshold calibration strategy
- Internal indexing implementation

---

*Amendment v2.0.0 — Final. Ratified in Episode: Amendment: Cross-Episode Linking.*
*Incorporates all nine §11 editorial resolutions. Supersedes Amendment v2.0 (Complete) and Amendment v2.0 Section 11 (Complete).*
