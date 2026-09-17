> **HISTORICAL — retained for provenance. Superseded by [`SPEC.md`](../../SPEC.md); do not implement from this document.**
>
> The normative content of this amendment was published as SPEC 3.1.0 (2026-06-07) and folded into the body of `SPEC.md` at 3.2.1 (2026-07-04) as **§21 — Layer 3 Workflow & Execution DAG**. `SPEC.md` is authoritative; this file is no longer maintained. Amendment filenames keep their authoring numerals; see [`VERSIONING.md`](../../VERSIONING.md). The CIA conformance rule numbered **G-19** below was renumbered to **G-36** on integration (the authoring numeral collided with the BFM Taxonomy's G-19). Section numbers referenced below (§1–§13) are internal to this amendment and appear as subsections of SPEC §21.

# Workflow & Execution DAG — Layer 3 Codification
## Protocol Amendment — Schema Version 3.0.0

**Supersedes:** Schema v2.x.x
**Status:** Integrated — published as SPEC v3.1.0 (2026-06-07); text folded into `SPEC.md` §21 at v3.2.1 (2026-07-04). No longer maintained.
**Episode of Record:** Autonomous Agentic Workflows and Skills (`615b41e2-33cf-49e4-8491-b8a3f2e4cd75`)
**Breaking Changes:** None — Layer 3 is net-new protocol surface. No existing node hash preimage is altered.
**Compatible Changes:**
- Three new node types: `WorkflowDeclaration`, `ExecutionNode`, `SkillInvocation`
- Seven new edge types: `DECLARED_WITHIN`, `SERVES_INTENTION`, `SPAWNED_BY_MANDATE`, `EXECUTES_WITHIN`, `PRECEDES`, `INVOKED_WITHIN`, `SKILL_PRECEDES`
- Four new `CognitiveDeltaType` values: `WORKFLOW_DECLARED`, `EXECUTION_RECORDED`, `SKILL_INVOKED`, `WORKFLOW_CLOSED`
- One new conformance principle: **Cognitive Implementation Authority** (sole-writer guarantee per workspace)
- One reserved field: `SkillInvocation.registry_id` (deferred — see §13)

---

## Amendment Summary

The protocol's first two layers — the kernel-owned Merkle Spine (Layer 1) and the Adaptive Merkle Tree of episode content (Layer 2) — record **cognition**: what an agent came to believe, intended, and committed to. They do not record **execution**: what the agent (or a delegated process acting on the agent's behalf) actually did. As autonomous agentic processes and skill-driven invocations become the dominant execution substrate across the AI ecosystem, that omission has become load-bearing.

This amendment introduces **Layer 3 — the Workflow & Execution DAG**: a Merkle DAG of execution records that references Layers 1 and 2 by ID but is cryptographically isolated from Spine integrity. Layer 3 nodes are written under a strict sole-writer principle — each workspace designates one **Cognitive Implementation Authority** (CIA) per node type — and every write emits an audit-chain event, making execution recording verifiable in the same sense Spine cognition is. The amendment also codifies the deliberation-to-execution **provenance handoff**: a `mandate_id` reference frozen into the WorkflowDeclaration hash at declaration time, eliminating the class of failures where live BDI queries at execution time record an intention different from the one that motivated the delegation.

The combined result is a protocol surface in which autonomous agentic execution, including arbitrary skill invocation by external agents (Claude Code, SDK-based task agents, capability-registry agents), is recorded with the same integrity guarantees as the cognitive states that produced it — without polluting the Spine with execution-layer churn.

| Gap # | Topic | Schema Impact | Resolution |
|-------|-------|---------------|------------|
| 1 | No protocol surface exists for recording autonomous agentic execution. Layer 1/2 record cognition only. | New protocol layer | Layer 3 codified as Workflow & Execution DAG (§4–§7). |
| 2 | Execution records, if hash-linked into Spine, could corrupt cognitive integrity proofs through a high-churn write surface. | Hard invariant | Layer 3 nodes never participate in Spine hash. All cross-layer references are by ID only. Spine hash chain remains kernel-owned and unaffected by Layer 3 writes (§2). |
| 3 | Multiple writers to Layer 3 could fragment the execution record or open injection paths. | New conformance principle | Each workspace designates a single **Cognitive Implementation Authority** (CIA) per Layer 3 node type. Non-CIA writes are forbidden at the wire tier (§3). |
| 4 | Skill invocation taxonomy varies across implementations (Claude Code, SDK agents, capability registries, custom). A closed enum would lock implementations into one vocabulary. | Open behavioral-tier surface | `SkillInvocation.skill_source` is an implementation-defined string. The audit-the-decision pattern applies: the protocol records what was chosen, not which choices are permitted (§6, §12). |
| 5 | BDI deliberation → execution provenance is fragile when queried live: the intention that motivated a delegation may have been superseded by the time execution records it. | Schema-anchored handoff | `mandate_id` and `intention_id` are immutable, hash-included fields on `WorkflowDeclaration`, populated from the mandate the agent received at deliberation time, not from live BDI state (§4, §7). |
| 6 | Execution records must be cryptographically anchored, not merely logged, for verifiable-cognition guarantees to extend across the execution layer. | Audit chain extension | Four new `CognitiveDeltaType` entries — `WORKFLOW_DECLARED`, `EXECUTION_RECORDED`, `SKILL_INVOKED`, `WORKFLOW_CLOSED` — added to the canonical audit registry, mandatory at the wire tier (§11). |
| 7 | Retried steps in implementations that mutate prior records erase forensic evidence of failure paths. | Immutability invariant | `ExecutionNode` and `SkillInvocation` are terminal-on-write. Retries produce **new** nodes with incremented sequence indices; the prior failure record is preserved (§9). |

---

## Part I — Layer 3 Architecture

### §1 Three-Layer Cognitive Model

The Ariadne protocol now defines **three layers** of cryptographic persistence, each owned by a distinct authority and each isolated from the others' hash integrity:

```
┌──────────────────────────────────────────────────────────────┐
│  LAYER 1 — Merkle Spine (kernel-owned, hash-chained)         │
│  EpisodeNode, IntentionNode, BeliefNode, SignalNode, …       │
│  → Authoritative cognitive record. Owned by the protocol     │
│    kernel implementation. Hash-chained. Witness-signable.    │
└────────────────────────┬─────────────────────────────────────┘
                         │ referenced by ID only
┌────────────────────────▼─────────────────────────────────────┐
│  LAYER 2 — Episode Content (Adaptive Merkle Tree)            │
│  Segments, BranchPoints, HITLEventNodes                      │
│  → Episode body. Adaptive tree under the Spine.              │
└────────────────────────┬─────────────────────────────────────┘
                         │ referenced by ID only
┌────────────────────────▼─────────────────────────────────────┐
│  LAYER 3 — Workflow & Execution DAG (CIA-owned)              │
│  WorkflowDeclaration, ExecutionNode, SkillInvocation         │
│  → What was done. Written by the workspace's Cognitive       │
│    Implementation Authority. Hash-isolated from Spine.       │
└──────────────────────────────────────────────────────────────┘
```

**Layer 3's purpose** is to answer the questions that Layers 1 and 2 cannot:

- *What did the agent (or its delegates) actually do to act on this intention?*
- *Which discrete steps composed that execution?*
- *Which skills were invoked, by whom, with what parameters, with what result?*
- *Where did execution fail, and what state preceded that failure?*

These questions are forensic; their answers must survive arbitrary failure modes (process kill, partial writes, retries) without contaminating the cognitive record above them.

### §2 Layer Isolation and the Spine Firewall

The defining invariant of Layer 3 is **isolation from Spine hash computation**:

> **Invariant L3-I1 (Spine Isolation).** No field of any Layer 3 node, and no field of any Layer 3 edge, shall be included in the preimage of any Layer 1 or Layer 2 hash. Layer 3 nodes reference Layer 1/2 nodes by `node_id` (UUID) only. Layer 1/2 nodes shall not contain references to Layer 3 `node_id` values in their hash preimage.

This invariant has three consequences that conforming implementations MUST guarantee:

1. **No write to Layer 3, under any circumstance, can invalidate any Spine hash.** The kernel may freeze, the Spine may seal, the Spine fingerprint may be witness-signed — none of these states are altered by Layer 3 activity.
2. **A workspace whose Layer 3 is entirely absent or entirely corrupt remains a valid Ariadne workspace** at Layers 1 and 2. Layer 3 is a strict augmentation, never a dependency.
3. **Layer 3 verification is performed against its own audit chain** (§11), not by walking the Spine. Verification at Layer 3 confirms execution-record integrity; verification at Layer 1 confirms cognitive integrity. The two verifications are independent.

The protocol layer makes no claim about whether Layer 3 storage and Layer 1/2 storage share infrastructure. They MAY share a database, a blob store, an index. Adapter choices are unconstrained. What is constrained is the **hash preimage** — never crosses the layer boundary.

### §3 The Sole-Writer Principle — Cognitive Implementation Authority (CIA)

A second invariant governs **who** may write Layer 3:

> **Invariant L3-I2 (Sole Writer).** For each Layer 3 node type within a workspace, exactly one entity — the **Cognitive Implementation Authority** (CIA) for that node type in that workspace — is authorized to issue creation writes. Writes from any other source MUST be rejected at the wire tier.

A CIA is a protocol-level role, not a specific implementation technology. The CIA for `WorkflowDeclaration` in a workspace may be:

- An MCP server (the Ignis reference implementation),
- An in-process module of a single-process implementation,
- A network-attached daemon with cryptographic identity,
- Any other entity that the workspace's `ConformanceDeclaration` names.

What matters is that **the CIA is unique** for a given (workspace, node type) pair, and that the implementation demonstrates enforcement. Enforcement may take any of the following forms (this list is illustrative, not exhaustive):

- Database-level access control (only the CIA's principal has INSERT on the relevant tables/collections).
- Application-layer guards (all write paths route through the CIA, no parallel ingestion).
- Cryptographic identity (writes are signed by the CIA's key; non-CIA writes fail signature verification).
- Audit-detection (writes by non-CIA principals are admitted but flagged in the audit chain as `WIRE_VIOLATION`, which conforming verifiers reject).

A workspace MAY designate **the same CIA for all three Layer 3 node types**, and the reference implementation does so. A workspace MAY also designate **distinct CIAs per node type** — for example, one authority writes WorkflowDeclarations under organizational policy review, while another writes ExecutionNodes from a high-throughput operational substrate. The protocol permits either; the audit chain records which CIA wrote each record (§11).

> **Conformance G-19 (CIA Declaration).** Every conforming workspace's `ConformanceDeclaration` MUST name the CIA for each Layer 3 node type, identify the enforcement mechanism, and commit to the chosen mechanism in the wire tier. Changes to CIA assignment are protocol events that MUST be recorded in the audit chain (event type: `CIA_DESIGNATION_CHANGED`, deferred to a future amendment if/when CIA changes prove non-rare).

The sole-writer principle is what makes verifiable cognition extend across the execution layer. Without it, an attacker (or an unaware sibling process) could inject forged execution records whose audit chain would still verify cryptographically. The CIA designation is the protocol's commitment that *only one principal* could have written a given record, and the audit chain's job is to prove the chain of those writes is unbroken.

---

## Part II — Data Model

### §4 WorkflowDeclaration

A `WorkflowDeclaration` is the intent-record for a discrete autonomous agentic workflow. It is created at workflow initiation — before any execution step writes — and it persists independently of whether execution completes. A WorkflowDeclaration with zero child ExecutionNodes is a valid forensic state ("workflow declared but never started"), and the protocol assigns it no different treatment from a fully-executed workflow.

```
WorkflowDeclaration {
  // Identity
  node_id            UUID            [primary key, immutable]
  node_type          "WorkflowDeclaration"  [literal, immutable]
  schema_version     String          [semver, immutable]

  // Spine References (Layer 1, by ID only)
  episode_id         UUID            [→ EpisodeNode, REQUIRED, immutable]
  intention_id       UUID            [→ IntentionNode, NULLABLE, immutable]

  // Mandate Provenance — see §13 for Mandate's deferred protocol surface
  mandate_id         UUID            [→ Mandate, NULLABLE, immutable]

  // Declaration Content
  workflow_name      String          [human-readable identifier, immutable]
  workflow_version   String          [semver, default "1.0.0", immutable]
  declared_by        String          [agent or CIA identifier, immutable]
  declared_at        ISO8601         [immutable]

  // Execution Parameters
  input_context      JSON            [parameters at declaration, immutable]
  expected_outputs   JSON            [success criteria, NULLABLE, immutable]
  timeout_ms         Integer         [NULLABLE — absent = no timeout, immutable]

  // Mutable Terminal State (the only mutation surface in Layer 3)
  status             WorkflowStatus  [DECLARED | IN_PROGRESS | COMPLETED | FAILED | INTERRUPTED]
  status_updated_at  ISO8601         [updated on every status transition]
  error_detail       JSON            [NULLABLE, populated on FAILED/INTERRUPTED close]

  // Integrity
  content_hash       String          [hash of all IMMUTABLE fields; see §8]
}
```

**Immutability**: every field above is immutable after creation **except** `status`, `status_updated_at`, and `error_detail`. The mutable trio constitutes the controlled mutation surface; no other mutation is permitted. The state machine governing valid `status` transitions is given in §10.

**Hash preimage note (§8 governs the byte form):** `status`, `status_updated_at`, `error_detail`, and `content_hash` itself are **excluded** from the preimage. `mandate_id` and `intention_id`, though nullable, are **included** — they are immutable provenance fields, and their nullability is itself part of the immutable record. A WorkflowDeclaration declared with `mandate_id = null` produces a different hash than one declared with a non-null `mandate_id`, even if no other field differs.

### §5 ExecutionNode

An `ExecutionNode` is the atomic record of one discrete execution step within a workflow. **ExecutionNodes are terminal-on-write**: the `status` field is final at the moment of creation, and no update path exists. A failed step that is retried produces a *new* ExecutionNode with the same `step_name`, a new `node_id`, and a new `sequence_index`; the original failed node is preserved unchanged. This guarantees that the failure trace is a permanent forensic record, not erasable by retry.

```
ExecutionNode {
  // Identity
  node_id            UUID            [primary key, immutable]
  node_type          "ExecutionNode" [literal, immutable]
  schema_version     String          [semver, immutable]

  // Workflow & Episode References (Layer 3 and Layer 1, by ID only)
  workflow_id        UUID            [→ WorkflowDeclaration, REQUIRED, immutable]
  episode_id         UUID            [→ EpisodeNode, REQUIRED, immutable; denormalized for query speed]

  // Sequence
  sequence_index     Integer         [0-based position in workflow, immutable]
  step_name          String          [human-readable step identifier, immutable]

  // Execution Record
  agent_id           String          [executing agent identifier, immutable]
  executed_at        ISO8601         [immutable]
  duration_ms        Integer         [NULLABLE if interrupted, immutable]

  // Input / Output State
  input_state        JSON            [REQUIRED — may be {}, immutable]
  output_state       JSON            [NULLABLE if failed or interrupted, immutable]

  // Terminal Status (written once, never updated)
  status             ExecutionStatus [COMPLETED | FAILED | INTERRUPTED]
  error_detail       JSON            [NULLABLE — populated when status ≠ COMPLETED]
  error_type         ErrorType       [NULLABLE — required when status ≠ COMPLETED]

  // Integrity
  content_hash       String          [hash of all fields except content_hash; see §8]
}
```

**Immutability**: every field is immutable. There is no write-after-create path of any kind.

**Hash preimage note:** all fields except `content_hash` itself contribute to the preimage. Unlike WorkflowDeclaration, `status` is **included** in the ExecutionNode hash — because it is terminal-on-write, never mutated, and forensically meaningful (the hash binds the agent's record of *what status was written*, not just *what data*).

**The retry pattern is a protocol commitment, not an adapter choice.** If an implementation provides a "retry" surface that mutates the prior ExecutionNode, it is non-conforming. Retry creates a new node.

### §6 SkillInvocation

A `SkillInvocation` records a single skill invocation performed within an ExecutionNode. It is the protocol surface for capturing what skills (in any sense the workspace's CIA defines that term — markdown-driven, capability-registry-resolved, tool-call-style, model-context-protocol-tool, or otherwise) were invoked in service of a step. SkillInvocation is **optional**: an ExecutionNode may complete without any SkillInvocation children (a step that consists entirely of native agent reasoning, for instance).

```
SkillInvocation {
  // Identity
  node_id            UUID            [primary key, immutable]
  node_type          "SkillInvocation" [literal, immutable]
  schema_version     String          [semver, immutable]

  // Parent References (Layer 3 and Layer 1, by ID only)
  execution_node_id  UUID            [→ ExecutionNode, REQUIRED, immutable]
  workflow_id        UUID            [→ WorkflowDeclaration, REQUIRED, immutable; denormalized]
  episode_id         UUID            [→ EpisodeNode, REQUIRED, immutable; denormalized]

  // Skill Identity — open behavioral-tier surface (§12)
  skill_id           String          [implementation-defined string, immutable]
  skill_source       String          [implementation-defined enum value, immutable]
  skill_version      String          [NULLABLE, implementation-defined, immutable]

  // Invocation Record
  invoked_by         String          [agent or CIA identifier, immutable]
  invoked_at         ISO8601         [immutable]
  duration_ms        Integer         [NULLABLE, immutable]

  // Parameters & Result
  input_parameters   JSON            [REQUIRED — may be {}, immutable]
  output_result      JSON            [NULLABLE if failed, immutable]

  // Terminal Status
  status             SkillStatus     [COMPLETED | FAILED | INTERRUPTED]
  error_detail       JSON            [NULLABLE, immutable]

  // Reserved — Skill Registry bridge (deferred; see §13)
  registry_id        UUID            [NULLABLE, EXCLUDED from content_hash]

  // Integrity
  content_hash       String          [hash of all fields except content_hash and registry_id; see §8]
}
```

**Immutability**: all fields immutable except `registry_id` (a deferred field; see §13). `registry_id` may be populated later by a backfill operation **without** invalidating `content_hash`, because it is excluded from the preimage by design.

**Hash preimage note:** `registry_id` is the **only** Layer 3 field excluded from a content hash for reasons other than mutation. Its exclusion is a forward-compatibility provision (see §13).

**On `skill_id` and `skill_source`:** these fields are deliberately open. The protocol does not constrain what counts as a "skill," what counts as a "source," or how implementations choose between sources. The protocol's commitment is that *whatever the implementation chose, it is recorded immutably and contributes to the content hash.* This is the **audit-the-decision pattern** (§12) applied to skill taxonomy.

### §7 Cross-Layer References

All Layer 3 → Layer 1/2 references are by `node_id` (UUID). No Layer 3 field is embedded by value in any Layer 1/2 hash. The seven edges introduced by this amendment are:

| Edge | From | To | Cardinality | Required? | Purpose |
|------|------|-----|-------------|-----------|---------|
| `DECLARED_WITHIN` | `WorkflowDeclaration` | `EpisodeNode` | many-to-one | REQUIRED | Workflow's episode anchor |
| `SERVES_INTENTION` | `WorkflowDeclaration` | `IntentionNode` | many-to-one | OPTIONAL | BDI-spawned workflow's intention link |
| `SPAWNED_BY_MANDATE` | `WorkflowDeclaration` | `Mandate` | many-to-one | OPTIONAL | Faculty-delegation provenance |
| `EXECUTES_WITHIN` | `ExecutionNode` | `WorkflowDeclaration` | many-to-one | REQUIRED | Step's workflow parent |
| `PRECEDES` | `ExecutionNode` | `ExecutionNode` | flexible | OPTIONAL | Sequence ordering (absent on first step) |
| `INVOKED_WITHIN` | `SkillInvocation` | `ExecutionNode` | many-to-one | REQUIRED | Skill's step parent |
| `SKILL_PRECEDES` | `SkillInvocation` | `SkillInvocation` | one-to-one | OPTIONAL | Skill chaining within a step |

The edge **names** above are normative at the protocol level. Edge **storage format** is adapter-defined: implementations using a graph database MAY store them as native edges; implementations using a relational database MAY store them as foreign keys; implementations using a document store MAY store them as embedded reference arrays. Whatever the storage, conforming implementations MUST expose query paths equivalent to the seven edges (see Appendix A for reference patterns).

**Edge property normativity.** Edge property *names* are normative where given (e.g., `PRECEDES` carries `sequence_gap: Integer` and `edge_type: SEQUENTIAL | CONDITIONAL | PARALLEL`). Edge property *types* are normative. Additional implementation-specific edge properties are permitted but MUST NOT alter the semantics of the seven core edges.

---

## Part III — Integrity and Lifecycle

### §8 Hash Preimages — Deterministic Serialization Requirement

The protocol does not lock Layer 3 implementations to a specific byte-form for hash preimages. It does, however, impose three normative requirements:

> **Conformance W-L3-1 (Determinism).** Each Layer 3 node type's `content_hash` MUST be computed from a deterministic byte serialization of its immutable-and-hashable field set. The same field values MUST always produce the same hash, on any conforming implementation.

> **Conformance W-L3-2 (Field Inclusion).** The byte serialization MUST include every field marked immutable-and-hashable in §4, §5, and §6 exactly once. It MUST exclude every field marked excluded-from-hash. No additional fields may contribute to the hash.

> **Conformance W-L3-3 (Documentation).** The implementation MUST document its chosen byte serialization in its `ConformanceDeclaration`, in sufficient detail that an independent verifier can reproduce any node's hash from its field values.

Two valid byte-serialization forms are illustrated here:

**Form A — Length-prefixed concatenation (Spine-style, SHA3-256), modeled on SPEC.md §5.2:**

```
preimage = (
  node_id                              (16 bytes, UUID)
  len(node_type).to_bytes(4, "big")    (4 bytes, length prefix)
  node_type                            (variable, UTF-8)
  len(schema_version).to_bytes(4, "big")
  schema_version                       (variable, UTF-8)
  …                                    (remaining immutable fields, in declared order)
)
content_hash = SHA3-256(preimage).hex()
```

**Form B — Canonical JSON (SHA-256), used by the Ignis reference implementation:**

```
payload = {field: value for every immutable-and-hashable field}
canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
content_hash = SHA256(canonical).hex()
```

Both forms satisfy W-L3-1, W-L3-2, and W-L3-3. An implementation choosing Form A and an implementation choosing Form B will produce **different hashes for the same field values** — this is intentional and acceptable. Cross-implementation hash equivalence is not a protocol requirement at Layer 3; cross-implementation *verifiability* is, and is achieved via the documented serialization, not via a single canonical hash function.

**Excluded fields** (per §4–§6, summarized):

| Node | Excluded from `content_hash` |
|------|------------------------------|
| `WorkflowDeclaration` | `status`, `status_updated_at`, `error_detail`, `content_hash` itself |
| `ExecutionNode` | `content_hash` itself |
| `SkillInvocation` | `registry_id`, `content_hash` itself |

### §9 Immutability Invariants

> **Invariant L3-I3 (Terminal-on-Write).** `ExecutionNode` and `SkillInvocation` are fully immutable after creation. No field of either type may be altered. Implementations MUST reject any update operation.

> **Invariant L3-I4 (WorkflowDeclaration Mutation Surface).** The only mutable fields on `WorkflowDeclaration` are `status`, `status_updated_at`, and `error_detail`. Any mutation to any other field is a wire-tier violation. Mutations to the permitted three are constrained by the state machine of §10.

> **Invariant L3-I5 (Retry-by-New-Node).** A retried execution step MUST produce a new `ExecutionNode` with a new `node_id` and a new `sequence_index`. The prior `ExecutionNode` is preserved unchanged. Implementations MUST NOT provide a "retry" surface that mutates a prior node.

### §10 Workflow Status State Machine

`WorkflowDeclaration.status` follows this transition graph:

```
                                    ┌─────────────┐
            ┌─────────────────────► │ INTERRUPTED │  (process killed before
            │                       └─────────────┘   any ExecutionNode written)
            │
   ┌──────────────┐  first ExecutionNode write   ┌─────────────┐
   │   DECLARED   │ ───────────────────────────► │ IN_PROGRESS │
   └──────────────┘                              └──────┬──────┘
                                                        │
                                                        ▼
                                       ┌──────────────────────────────┐
                                       │  close_workflow(COMPLETED)   │ ──► COMPLETED
                                       │  close_workflow(FAILED)      │ ──► FAILED
                                       │  close_workflow(INTERRUPTED) │ ──► INTERRUPTED
                                       └──────────────────────────────┘
```

**Auto-transition rule:** the first creation of an `ExecutionNode` with a given `workflow_id` MUST transition that workflow's `status` from `DECLARED` to `IN_PROGRESS` atomically with the ExecutionNode write. The transition is a wire-tier guarantee: a workspace whose `WorkflowDeclaration.status` is `DECLARED` while ExecutionNodes for it exist is non-conforming.

**Terminal states:** `COMPLETED`, `FAILED`, and `INTERRUPTED` are terminal. No transition out of these states is permitted. A workflow in any terminal state is closed permanently.

**Two distinct `INTERRUPTED` states are observable**, both valid:
- WorkflowDeclaration with `status = INTERRUPTED` and zero ExecutionNodes — declared, never started.
- WorkflowDeclaration with `status = INTERRUPTED` and one or more ExecutionNodes (the last of which may itself have status `INTERRUPTED`) — started, terminated mid-execution.

Neither is a schema violation. Conforming verifiers MUST distinguish them in forensic output.

### §11 Audit Event Registry

Layer 3 writes are anchored to the protocol's audit chain by four new `CognitiveDeltaType` values:

| Event Type | Trigger | Required Fields | Storage |
|------------|---------|-----------------|---------|
| `WORKFLOW_DECLARED` | `WorkflowDeclaration` creation | `workflow_id`, `episode_id`, `intention_id` (nullable), `mandate_id` (nullable), `declared_by`, `declared_at`, `content_hash`, `cia_identifier` | Blob, append-only |
| `EXECUTION_RECORDED` | `ExecutionNode` creation | `execution_node_id`, `workflow_id`, `episode_id`, `sequence_index`, `agent_id`, `status`, `executed_at`, `content_hash`, `cia_identifier` | Blob, append-only |
| `SKILL_INVOKED` | `SkillInvocation` creation | `skill_invocation_id`, `execution_node_id`, `workflow_id`, `episode_id`, `skill_id`, `skill_source`, `invoked_by`, `invoked_at`, `status`, `content_hash`, `cia_identifier` | Blob, append-only |
| `WORKFLOW_CLOSED` | `ignis_close_workflow`-equivalent operation | `workflow_id`, `final_status`, `status_updated_at`, `error_detail` (nullable), `cia_identifier` | Blob, append-only |

**Audit chain integrity.** Each Layer 3 audit event is hash-chained per the existing protocol convention: each record carries `prev_audit_hash` pointing at the preceding record in its chain, and records form an append-only sequence per workspace (or per chain-key as the implementation declares). The chain key for Layer 3 events MAY be the `episode_id` (Ignis reference choice) or any other declared key, provided the implementation documents the choice in its `ConformanceDeclaration` and is consistent within a workspace.

**`cia_identifier` is mandatory in every Layer 3 audit event.** The principal that performed the write — the workspace's designated CIA for that node type — MUST be recorded. This is what makes the sole-writer principle (§3) verifiable: a verifier walking the audit chain can confirm that every L3 write was performed by the declared CIA, and that no other principal contributed.

**Conformance W-L3-4 (Audit Emission).** Every Layer 3 node creation and every `WorkflowDeclaration.status` mutation MUST emit the corresponding audit event into the chain **before** the operation is considered durable. Implementations MAY use the existing protocol convention of Blob → Adapter → Index write ordering, in which case the audit-event blob write precedes the node creation in the adapter store.

---

## Part IV — Conformance and Governance

### §12 Three-Tier Conformance

This amendment slots into the conformance taxonomy established by Amendment v2.0 §12:

| Tier | What Layer 3 covers at this tier | Required? |
|------|----------------------------------|-----------|
| **Wire** | Node schemas (§4–§6), edge names (§7), hash preimage rules (§8), immutability invariants (§9), state machine (§10), audit event types and required fields (§11), CIA sole-writer enforcement (§3) | **REQUIRED** |
| **State** | Status transition semantics, retry-by-new-node, distinction between the two `INTERRUPTED` states | **REQUIRED** |
| **Behavioral** | Hash byte-form choice (Form A / Form B / other), `skill_id` and `skill_source` vocabularies, CIA enforcement mechanism, audit-chain chain-key choice, edge storage representation, denormalization choices | **NOT REQUIRED** — but the audit-the-decision pattern applies: the choice MUST be documented in the `ConformanceDeclaration`. |

**Audit-the-decision pattern applied to Layer 3:**

| Question | Where the protocol commits | Where the implementation chooses |
|----------|---------------------------|----------------------------------|
| What hash algorithm? | Result MUST be deterministic | Implementation picks (SHA3-256 / SHA-256 / other) |
| What byte form? | Field inclusion is fixed | Implementation picks (concatenation / canonical JSON / other) |
| What `skill_source` values are valid? | Field is recorded immutably | Implementation defines its enum |
| Who is the CIA? | Sole-writer principle | Workspace names the entity in its `ConformanceDeclaration` |
| How is CIA enforcement implemented? | Enforcement at wire tier required | Implementation picks (DB ACL / app guard / signing / audit-detection) |
| What is the audit chain key? | Append-only, hash-chained, per-chain-key | Implementation picks the key dimension |

### §13 Deferred Items

Three protocol surfaces touched by this amendment are explicitly deferred to future amendments:

1. **Mandate — full protocol surface.** This amendment introduces `mandate_id` as an optional, immutable, hash-included field on `WorkflowDeclaration`, and the `SPAWNED_BY_MANDATE` edge to a `Mandate` node. The `Mandate` node type itself — its fields, its hash preimage, its lifecycle, its position in the layer hierarchy (Mandate is most naturally a Layer 1 or Layer 2 cognitive primitive, not Layer 3) — is **not specified by this amendment**. Conforming implementations MAY treat `Mandate` as an opaque reference for the purposes of Layer 3 conformance. A future amendment (provisional designation: **v3.1.0 — Mandate Codification**) will define the full Mandate surface.

2. **Skill Registry.** The `SkillInvocation.registry_id` field is reserved for a future protocol surface that catalogues skills as first-class addressable entities. Until that surface is defined, conforming implementations MUST leave `registry_id` null. The field's exclusion from `content_hash` is a deliberate forward-compatibility provision: when the Skill Registry amendment ships, a backfill operation MAY populate `registry_id` on existing `SkillInvocation` records without invalidating their content hashes.

3. **SkillInvocation as Spine-resident node.** Some implementations may eventually want SkillInvocation to participate in Spine hashing — turning skill invocation into a cryptographically-anchored cognitive primitive for ecosystems where agent cognition is substantially composed of skill chains rather than native reasoning. This amendment **declines** that promotion: SkillInvocation remains a Layer 3 node. A future major amendment (provisional designation: **v4.0.0 — SkillInvocation Spine Promotion**) may revisit this decision once production usage of Layer 3 has informed the design.

---

## Appendix A — Reference Adapter Notes (Non-Normative)

The following notes derive from the reference implementation in the Ignis OS. They are non-normative: conforming implementations need not adopt them. They are included to illustrate one complete adapter path and to inform implementers considering similar designs.

### A.1 Neo4j edge vocabulary

The reference implementation stores Layer 3 edges as native Neo4j relationships with the names given in §7:

```cypher
(:WorkflowDeclaration)-[:DECLARED_WITHIN {declared_at}]->(:EpisodeNode)
(:WorkflowDeclaration)-[:SERVES_INTENTION {declared_at}]->(:IntentionNode)
(:WorkflowDeclaration)-[:SPAWNED_BY_MANDATE {declared_at}]->(:Mandate)
(:ExecutionNode)-[:EXECUTES_WITHIN {sequence_index}]->(:WorkflowDeclaration)
(:ExecutionNode)-[:PRECEDES {sequence_gap, edge_type}]->(:ExecutionNode)
(:SkillInvocation)-[:INVOKED_WITHIN {invoked_at}]->(:ExecutionNode)
(:SkillInvocation)-[:SKILL_PRECEDES {sequence_index}]->(:SkillInvocation)
```

### A.2 Suggested indexes

```cypher
CREATE INDEX workflow_episode_idx FOR (w:WorkflowDeclaration) ON (w.episode_id);
CREATE INDEX workflow_mandate_idx FOR (w:WorkflowDeclaration) ON (w.mandate_id);
CREATE INDEX workflow_status_idx FOR (w:WorkflowDeclaration) ON (w.status);
CREATE INDEX execution_workflow_idx FOR (e:ExecutionNode) ON (e.workflow_id);
CREATE INDEX execution_status_idx FOR (e:ExecutionNode) ON (e.status);
CREATE INDEX execution_agent_status_idx FOR (e:ExecutionNode) ON (e.agent_id, e.status);
CREATE INDEX skill_execution_idx FOR (s:SkillInvocation) ON (s.execution_node_id);
CREATE INDEX skill_id_idx FOR (s:SkillInvocation) ON (s.skill_id);
CREATE CONSTRAINT workflow_node_id_unique FOR (w:WorkflowDeclaration) REQUIRE w.node_id IS UNIQUE;
CREATE CONSTRAINT execution_node_id_unique FOR (e:ExecutionNode) REQUIRE e.node_id IS UNIQUE;
CREATE CONSTRAINT skill_node_id_unique FOR (s:SkillInvocation) REQUIRE s.node_id IS UNIQUE;
```

### A.3 Reference forensic query patterns

**"What led to this failure?"**
```cypher
MATCH (w:WorkflowDeclaration {node_id: $workflow_id})
OPTIONAL MATCH (w)<-[:EXECUTES_WITHIN]-(e:ExecutionNode)
OPTIONAL MATCH (e)<-[:INVOKED_WITHIN]-(s:SkillInvocation)
RETURN w.workflow_name, w.status, e.step_name, e.status, e.error_type,
       e.error_detail, s.skill_id, s.status, s.error_detail
ORDER BY e.sequence_index, s.invoked_at
```

**"Full provenance chain: intention → mandate → workflow → execution"**
```cypher
MATCH (i:IntentionNode {node_id: $intention_id})
OPTIONAL MATCH (i)<-[:SERVES_INTENTION]-(w:WorkflowDeclaration)
OPTIONAL MATCH (w)-[:SPAWNED_BY_MANDATE]->(m:Mandate)
OPTIONAL MATCH (w)<-[:EXECUTES_WITHIN]-(e:ExecutionNode)
RETURN i, m, w, collect(e) AS executions
```

### A.4 Reference CIA implementation

The Ignis reference implementation designates a single MCP server (the `ignis_mcp_server`) as the CIA for all three Layer 3 node types in the SEL workspace. Enforcement is achieved through:

- **Application-layer guard:** no other process holds Neo4j credentials with INSERT privileges on the Layer 3 labels.
- **MCP-tool surface:** the four write tools (`ignis_declare_workflow`, `ignis_record_execution_step`, `ignis_record_skill_invocation`, `ignis_close_workflow`) are the only authorized write paths.
- **Database constraint:** `node_id` uniqueness constraints (above) prevent accidental duplicate writes from any source.

The `cia_identifier` value emitted in audit events for this implementation is `ignis_mcp_server@<workspace_id>`.

---

## Appendix B — Conformance Checklist

A conforming Layer 3 implementation MUST:

- [ ] Implement `WorkflowDeclaration`, `ExecutionNode`, and `SkillInvocation` with the fields specified in §4–§6, respecting all immutability constraints.
- [ ] Support all seven edge types named in §7 (storage form is unconstrained).
- [ ] Compute `content_hash` from a documented deterministic serialization per §8, including only the fields marked immutable-and-hashable and excluding all fields marked excluded-from-hash.
- [ ] Enforce the immutability invariants of §9 — reject all mutation attempts on ExecutionNode and SkillInvocation; permit only `status`, `status_updated_at`, `error_detail` mutations on WorkflowDeclaration.
- [ ] Enforce the WorkflowDeclaration state machine of §10, including the atomic auto-transition `DECLARED → IN_PROGRESS` on first ExecutionNode write.
- [ ] Emit `WORKFLOW_DECLARED`, `EXECUTION_RECORDED`, `SKILL_INVOKED`, `WORKFLOW_CLOSED` audit events per §11, with `cia_identifier` populated, into a documented append-only hash-chained audit log.
- [ ] Designate, in its `ConformanceDeclaration`, exactly one Cognitive Implementation Authority per Layer 3 node type, identify the enforcement mechanism, and demonstrate enforcement at the wire tier (§3, §12).
- [ ] Document its chosen hash byte serialization in sufficient detail that an independent verifier can reproduce any Layer 3 node's hash from its field values (§8, W-L3-3).
- [ ] Document its `skill_source` vocabulary, its audit chain-key dimension, and its CIA enforcement mechanism in its `ConformanceDeclaration` (§12, audit-the-decision pattern).
- [ ] Leave `SkillInvocation.registry_id` null pending the future Skill Registry amendment (§13.2).

A conforming Layer 3 implementation MUST NOT:

- [ ] Include any Layer 3 field in the preimage of any Layer 1 or Layer 2 hash (§2, L3-I1).
- [ ] Mutate any field of an `ExecutionNode` or `SkillInvocation` after creation (§9, L3-I3).
- [ ] Mutate any field of a `WorkflowDeclaration` other than the three permitted (§9, L3-I4).
- [ ] Provide a "retry" surface that updates a prior `ExecutionNode` (§9, L3-I5).
- [ ] Admit Layer 3 writes from any principal other than the designated CIA for the relevant node type (§3, L3-I2).
- [ ] Populate `SkillInvocation.registry_id` until the future Skill Registry amendment defines its semantics (§13.2).

---

*Amendment v3.0.0 — integrated into `SPEC.md` §21 (see Status above). Episode of Record: `615b41e2-33cf-49e4-8491-b8a3f2e4cd75` (Autonomous Agentic Workflows and Skills).*
