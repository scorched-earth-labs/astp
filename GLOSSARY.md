# Glossary of Terms

**Version:** none of its own — versioned with [`SPEC.md`](./SPEC.md); last fully reconciled with SPEC `2.5.0-draft` (see below)
**Status:** Partially current — reconciliation with SPEC 4.x in progress
**Authors:** Scorched Earth Labs
**Date:** 2026-09-17
**Applies To:** `SPEC.md`, the implementation guides, and the `astp` Python package

---

A single-source definition for every term used normatively in `SPEC.md`, the implementation guides, and the `astp` Python package. Definitions are grouped by category for learning; an alphabetical index sits at the bottom for lookup.

**Currency.** This glossary was last fully reconciled with `SPEC.md` at version `2.5.0-draft`. The reproducibility terms of SPEC 4.3.0 (§5 below) have been added since; most other terms introduced in the 3.x and 4.x lines — cross-episode linking and grouping (SPEC §20), the Layer 3 Workflow & Execution DAG (SPEC §21), departure forks, ledgered operations, `AttachmentNode` — are not yet defined here, and some existing entries predate later changes to the rules and lifecycle they describe. Reconciliation with SPEC 4.x is in progress. Where this glossary and `SPEC.md` disagree, `SPEC.md` governs. If you encounter a term in code or in the specification that isn't defined here, it's a documentation gap worth raising.

---

## Reading this glossary

Several ASTP terms have a **structural relationship** that's easy to miss reading the SPEC linearly. Where present, that relationship is stated explicitly in the definition. The most important one:

> **`EpisodeNode`, `SegmentNode`, `SignalNode`, `HITLEventNode`, `ConsultationNode`, `CrystallizationDeltaNode`** are *colloquial names* for `CognitiveNode` instances with type-specific `NodePayload` subclasses. They are not separate classes parallel to `CognitiveNode` — they are parameterizations of it. See `CognitiveNode` and `NodePayload` for the underlying model.

The legacy `EpisodeNode` / `SegmentNode` / `SignalNode` standalone classes in `astp/core/schema.py` are Phase 1 artifacts being migrated to the `CognitiveNode + NodePayload` shape. New implementations should target the `astp/protocol/` surface (`CognitiveNode`, `NodePayload`), not the legacy `core/schema.py` classes. See SPEC §4 for the canonical model.

---

## 1. Core Types — the universal protocol primitives

### CognitiveNode

**The universal protocol primitive.** Every node in the cognitive record — episodes, segments, signals, consultations, HITL events, crystallization deltas — is a `CognitiveNode` with a type-specific payload. The protocol layer operates on `CognitiveNode` exclusively and never inspects payload internals; that abstraction is what keeps the protocol layer node-generic.

Key fields:
- `node_id` (UUID) — stable identity
- `node_type` (string) — discriminates the payload kind (e.g. `"episode"`, `"segment"`, `"signal"`)
- `schema_version` (string) — version of the node-type schema
- `sequence_index` (int) — immutable cognitive-timeline position; **in** the hash preimage
- `tree_leaf_index` (int) — mutable physical Merkle position; **not in** the hash preimage (see *Dual Index*)
- `content_hash` (string) — SHA3-256 of the payload via `payload.to_content_hash_input()`
- `parent_node_id` (UUID, optional) — graph position; immutable once set (see *Reparenting Prohibition*)
- `leaf_hash` (string, computed once at creation, never recomputed)
- `payload` (serialized dict) — the type-specific data; protocol never reads internal fields

Defined in `astp/protocol/node.py`. See SPEC §4.1.

### NodePayload

**The abstract interface for node-type-specific data.** Each kind of cognitive node (episode, segment, signal, etc.) implements `NodePayload` by providing:
- `validate()` — payload-specific invariant checks
- `to_content_hash_input()` — canonical byte representation used for `content_hash`; must be deterministic
- `to_dict()` — serialization for storage

This is the abstraction boundary that lets new node types slot into the protocol without protocol-layer changes. Defined in `astp/protocol/node.py`.

### CognitiveEdge

A typed, directed edge between cognitive nodes. Edges carry semantic meaning (e.g. `CONTAINS`, `PRECEDES`, `REFERENCES`) and are typed by both the edge itself and the nodes it connects. Defined in `astp/protocol/node.py`.

---

## 2. Node Types — parameterizations of CognitiveNode

Each of the following is a **`CognitiveNode` with `node_type=<type>` and a type-specific `NodePayload` subclass**. They are not separate top-level classes.

### EpisodeNode

A `CognitiveNode` with `node_type="episode"` and an `EpisodePayload`. An **Episode** is a bounded unit of agent work — the first node type the protocol supports, and the entry point for most cognitive activity. Episodes have a formal lifecycle (see *Episode Lifecycle*).

Defined via `astp/nodes/episode/payload.py` (`EpisodePayload`). See SPEC §4.4.

### SegmentNode

A `CognitiveNode` with `node_type="segment"` and a `SegmentPayload`. A **Segment** is an ordered, immutable content unit within an episode. Each segment carries a `content_hash` (SHA3-256 of its content) and a `content_ref` (pointer to the full content in durable storage). The hash chain is over the pointers and hashes — not the content bytes themselves — so content scales independently of the integrity layer.

See SPEC §4 and the *Spine* entry below.

### SignalNode

A `CognitiveNode` with `node_type="signal"` and a `SignalPayload`. A **Signal** is a state observation, alert, or annotation attached to an episode or segment. Signals are first-class protocol nodes (not implementation-level metadata) and participate in the hash chain. See SPEC §4.

### ConsultationNode

A `CognitiveNode` representing a **cross-agent exchange** as a first-class protocol concept rather than an application-level convention. Consultations form their own hash chain of `ExchangeEntry` nodes (see below). The branch point is recorded **before** any exchange occurs (G-8); resolution requires at least one entry (G-9).

### ExchangeEntry

An individual entry in a consultation's hash chain. Each entry records one turn of the cross-agent exchange. Entries are immutable once written and ordered by `sequence_index`.

### HITLEventNode

A `CognitiveNode` representing a **human-in-the-loop decision gate** as a first-class protocol node. Two-phase lifecycle:

```
INVOKED  →  RESOLVED   (decision recorded)
         ↘  TIMED_OUT  (no decision within window)
```

HITL events participate in the Merkle spine as causal anchors — they are not advisory metadata. While a `HITLEventNode` is `INVOKED` and unresolved, the containing episode cannot be sealed (the `PENDING_HITL` crystallization guard blocks sealing). Introduced in v2.4 (HITL Protocol Amendment). See SPEC §4.6.

### CrystallizationDeltaNode

A `CognitiveNode` representing a **state transition** in the cognitive record — specifically, a point-in-time integrity snapshot. Structurally analogous to a blockchain block header. Crystallization deltas are immutable once created; corrections flow forward through successor episodes, not by editing the original delta. See *Crystallization*.

---

## 3. Identifiers and Hashes

### `node_id`

Stable UUID identifying a node across stores. Assigned at creation; immutable.

### `content_hash`

SHA3-256 hash of a node's payload, computed via the payload's `to_content_hash_input()` method. Captures *what the node is about*. Stable: same payload state always produces the same `content_hash`.

### `content_ref`

Pointer to the full content in durable storage (e.g. an object-store key, a filesystem path). The hash chain references this pointer plus the `content_hash`; the content bytes themselves do not need to be hash-chain-resident, which lets content scale independently of the integrity layer.

### `leaf_hash`

The position-binding leaf hash for a node in the Merkle Spine. Combines the `content_hash` with position-binding fields (including `sequence_index`, `parent_node_id`, and others — see SPEC §5.2). Computed **once** at node creation and never recomputed. Any change to a node's position or content invalidates the chain at that point.

### `spine_hash`

The hash chain over leaf hashes within a cognitive node's tree. Iteratively combined to produce the *Merkle root*.

### `episode_root_hash`

The Merkle root of an episode's spine — the episode's cryptographic fingerprint. Used to verify the episode hasn't been tampered with.

### `parent_node_id`

UUID reference to a node's parent in the graph. **Immutable once set** — reparenting is a governance violation (see *Reparenting Prohibition*). To "fix" a parent reference, create a new node and deprecate the old one.

### `schema_version`

The version of the node-type schema, separate from the protocol version. A field on `CognitiveNode`. Allows individual node types to evolve their payload schemas independently of the protocol version, provided the protocol-level fields stay stable.

---

## 4. The Three-Layer Model

The protocol defines **three Merkle layers** with distinct integrity domains. Layers are conceptually nested but cryptographically isolated: a change in one layer must not invalidate hashes in another. See SPEC §3.1.

### Layer 1 — Merkle Spine

The kernel-owned, hash-chained backbone of an episode. Contains the `EpisodeNode`, `SegmentNode`, `SignalNode`, and (when present) `HITLEventNode` instances. The Spine carries cognition — *what the agent did and observed*. Its integrity is the foundation of the protocol's verifiability guarantees.

### Layer 2 — Adaptive Merkle Tree

The episode-content tree built **over** the Spine. Adapts its branching to the episode's actual shape (segments, signals, branches) rather than imposing a fixed tree topology. Used by *Crystallization* and the *WIL*.

### Layer 3 — Workflow & Execution DAG

The substrate for **autonomous-process audit trails**. Reserved for execution-side cognitive records (kernel-spawned work, tool calls, skill invocations) that need provenance without participating in Spine integrity. **Layer 3 nodes are cryptographically isolated from the Spine** — they reference Layer 1 / 2 nodes by ID only and must never be hash-linked into the Spine. This structural separation is by design: Layer 3 can grow without bound; the Spine stays untouched.

Specific Layer 3 node types are specified in SPEC §21 (Workflow & Execution DAG, added at 3.1.0) and are not yet defined in this glossary.

---

## 5. Spine and Merkle Concepts

### Spine

The ordered hash chain of leaf hashes within a cognitive node's tree. Each leaf hash is computed from its node's `content_hash` plus position-binding fields (see *`leaf_hash`*). The Merkle root of the spine is the node tree's integrity fingerprint. The spine is the proof; the content blobs are the payload — the spine carries hashes and pointers, not bytes.

### Spine Leaf Set

**What is, and is not, a leaf of an Episode's spine.** Exactly the Episode's non-ephemeral Segments, ordered by `sequence_index`. Signals are not leaves (they commit through the *Signal Manifest*); `EPHEMERAL` segments are not leaves (they commit through the *Exclusion Set*). `sequence_index` is the only ordering key and is unique per Episode, so the order is total with no tiebreak. Defined in SPEC §5.6; reference function `compute_spine_root_v2`.

### Signal Manifest

**The order-independent commitment to an Episode's SPINE-placed Signals.** `SHA3-256("SIGNAL_MANIFEST:v1:" || sorted content hashes joined by "|")`; the empty set hashes a sentinel. A set, not a sequence: membership binds, arrival order and timestamps do not. One of the three components of the *Episode Root*. SPEC §5.7; `compute_signal_manifest_hash`.

### Exclusion Set

**The commitment to what was deliberately left out of the spine** — the content hashes of `EPHEMERAL` segments — so that the omission is itself verifiable. Same set construction as the Signal Manifest under the `EXCLUSION:v1:` domain. SPEC §5.7; `compute_exclusion_hash`.

### Episode Root

**The three-component integrity commitment of a sealed Episode**: `SHA3-256("NODE:" || spine_root || signal_manifest_hash || exclusion_hash)`. `sealed_chain_root` on the CrystallizationDelta records the spine root; `episode_root_hash` on the Episode records the composition. SPEC §5.7; `compute_episode_root_hash`.

### Version Identifiers (hash_version, spine_algorithm_version, ordering_version)

**Which construction produced a record's hashes.** `hash_version` on every CognitiveNode; `spine_algorithm_version` (0 legacy iterative Merkle, 1 Adaptive Merkle Tree) and `ordering_version` (1 legacy segments-then-signals-by-arrival, 2 segments-only per §5.6) on the CrystallizationDelta. Diagnostic metadata outside every hash preimage — a verifier reads them to pick the reproduction function; altering them cannot make a tampered root verify. Absent means pre-4.3.0. SPEC §5.8.

### Reproducibility Obligation

**A sealed root must be rebuildable from stored nodes alone.** A verifier with only the Segments, Signals and seal record (with its version identifiers) recomputes `spine_root` and `episode_root_hash`; any construction needing insertion order, a store's default sort, or a cache is non-conformant. Returning a *stored* root is an anchor lookup, not a verification. SPEC §9.3; conformance family `RP-*`.

### Merkle Tree / Merkle Root

A binary tree of hashes computed bottom-up from the leaf hashes. The root is a single hash that summarizes the entire tree — change any leaf, the root changes. Used as the cryptographic fingerprint of an episode (`episode_root_hash`).

### Hash Chain

The strictly ordered sequence of `leaf_hash` values. Each leaf hash binds to its `sequence_index`, so the chain encodes both *what* happened and *in what order*. Tampering with order changes hashes; appending out of order is rejected by governance (G-3).

### Dual Index

The **epistemological core** of the v2 model. Every `CognitiveNode` carries two indices:

- `sequence_index` — **immutable** cognitive-timeline position. Represents *when* the node was created in the agent's reasoning. **Included** in the leaf hash preimage. Cannot be changed.
- `tree_leaf_index` — **mutable** physical Merkle position. Represents *where* the node sits in the Merkle tree for storage / retrieval. **Not included** in the leaf hash preimage. Can be re-balanced.

This separation lets the Merkle tree rebalance for performance without invalidating any hashes. Confusing the two is a protocol violation. See SPEC §3.3.

### Domain Separation

The technique of prefixing hash preimages with a domain tag so the same byte sequence in different contexts produces different hashes. Prevents cross-protocol hash collisions. See SPEC §5.3.

---

## 6. Episode Lifecycle

An Episode moves through a defined state machine:

```
CREATED → ACTIVE → CLOSING → CLOSING_PENDING_SEAL → SEALED → ARCHIVED
                 ↘ CRYSTALLIZATION_PENDING → CRYSTALLIZED ↗
```

### CREATED

The episode has been instantiated but no segments have been added. No content has been hashed yet.

### ACTIVE

Segments and signals are being appended. The hash chain is growing. New writes are permitted.

### CLOSING

The episode is winding down. New writes are no longer expected, but any pending HITL gates must resolve before sealing can complete.

### CLOSING_PENDING_SEAL

All content is in place; the cryptographic seal is being computed. Transient.

### CRYSTALLIZATION_PENDING

A crystallization event has been initiated. See *Crystallization*. Transient.

### CRYSTALLIZED

A crystallization snapshot has been produced and committed. The episode can move forward to sealing or back to ACTIVE depending on the crystallization's purpose.

### SEALED

The episode's integrity is cryptographically fixed. **Sealed nodes are immutable.** Corrections flow forward through successor episodes — there is no in-place edit path.

### ARCHIVED

The episode is no longer actively retained for hot retrieval. Its hashes and structure remain verifiable; its content may move to colder storage.

### Sealed (state)

A general property: a sealed node is one whose integrity is cryptographically fixed and is no longer modifiable. The protocol does not provide an "unseal" operation.

---

## 7. Crystallization

A protocol-level **state transition** that captures a point-in-time integrity snapshot. Each crystallization produces a `CrystallizationDeltaNode` (see above) structurally analogous to a blockchain block header. Three properties:

1. **Crystallization is in the chain, not about it.** The delta is itself a hash-chained node, not an external receipt or annotation.
2. **Crystallization deltas are immutable after creation.** Like all hash-chained nodes.
3. **Corrections flow forward.** If something needs to change after crystallization, the change is recorded as a new delta in a successor episode — the original is never amended.

See SPEC §5.5 (Type Isolation Property) and SPEC §6 (Governance Rules).

---

## 8. WIL — Write Intent Log

A coordination protocol for multi-store writes that guarantees ordering and recoverability. Writes proceed in **strict durability order**:

1. **Durable content store** — where the bytes live.
2. **Authoritative structural store** — where the hash chain and graph live.
3. **Ephemeral coordinator** — runtime coordination state.
4. **Semantic search index** — derived retrieval surface.

These are **roles, not products**: the protocol names no storage provider, the implementer chooses what fills each role, and one system may fill more than one.

An interrupted write at any phase **must be recoverable** — all writes must be idempotent. The WIL state machine tracks each write through these phases and replays incomplete writes on recovery.

Defined in `astp/core/wil.py`. See SPEC for the full WIL contract.

---

## 9. Consultation

A cross-agent exchange recorded as a first-class protocol node, not an application-level convention. Consultations form their own hash chain of `ExchangeEntry` nodes (see above). Branch points are recorded **before** any exchange occurs (G-8); resolution requires at least one entry (G-9).

The Consultation chain is distinct from the episode's main Spine — it's a side chain anchored at a specific point in the episode's flow.

---

## 10. BFM Taxonomy — Branch, Fork, Merge

The taxonomy of how episodes diverge and reconverge. Introduced in v2.5.0 (SPEC §19).

### Branch

A path that diverges from the main trajectory but remains within the same episode — a side line of reasoning that may rejoin (merge) without producing a new episode.

### Fork

A divergence that produces a **new episode** — a path that has moved far enough from the original trajectory that it constitutes its own bounded unit of work. A fork is committed past a structural threshold; once committed it cannot be reversed.

### Merge

A previously-divergent path rejoining the main trajectory. The reconvergence is recorded explicitly so the cognitive history reflects "we came back together here."

### Aside

A *social* primitive: a brief excursion from the current line of reasoning (e.g. a clarifying question or a meta-comment) that doesn't represent a true divergence. Returns to the original line.

### Soliloquy

An *internal* primitive: an agent's self-directed reasoning that doesn't engage the external trajectory. Recorded but not treated as a divergence.

### Coherence Fingerprint

A signature of the current line's semantic/structural state used by the BFM **write intercept** (Phase 4 prescriptive enforcement) to detect when a write would cross a divergence threshold. See SPEC §19.

---

## 11. Governance

The protocol's normative rules. Each rule has a number (`G-N`), a specific failure mode, and is enforced by adapters (a non-enforcing adapter is non-conformant).

### G-1 — Write Guard

Writes to sealed nodes are rejected. The seal is the integrity boundary.

### G-2 — Reparenting Prohibition

`parent_node_id` is immutable once set. To "fix" parentage, create a new node with the correct parent and deprecate the old one. See SPEC §6.

### G-3 — Sequence Monotonicity

`sequence_index` values within a chain must be strictly increasing. Out-of-order appends are rejected.

### G-4 — Logical Clock Monotonicity

Logical clock values must be monotonically non-decreasing. Prevents temporal anomalies.

### G-5 through G-9

Additional governance rules covering hash chain integrity, segment ordering, consultation chain semantics, etc. See SPEC §6.

### G-N (HITL, BFM, others)

Higher-numbered rules added by post-v2.0 amendments (HITL, BFM Taxonomy). See SPEC §6 and the relevant amendment documents for the full enumeration.

### Reparenting Prohibition

The architectural invariant enforced by G-2: a node's position in the graph is immutable. This makes sealed records auditable — any apparent change to a parentage relationship is suspicious by construction, because the protocol prohibits it.

### Namespace Firewall

The architectural invariant that `astp.protocol.*` modules cannot import from `astp.nodes.*`. Enforced by a test (`tests/unit/protocol/test_namespace_firewall.py`); a failure is a protocol-layer leak, not a style issue. Keeps the protocol layer node-generic. See SPEC §3.2 and G-6.

---

## 12. Adapter and Conformance

### AriadneAdapter

The abstract interface any storage backend must implement to serve as an ASTP adapter. Provides methods for writing nodes, querying the graph, computing hashes, and recovering from WIL state. Defined in `astp/adapters/base.py`.

### ASI — Adapter Service Interface

The formal name for the abstract contract that any conforming adapter must implement (i.e., the `AriadneAdapter` interface). See SPEC §2 (Terminology).

### Reference Implementation

The Neo4j adapter in `astp/adapters/neo4j/`. Serves as the worked example of a conforming adapter — implementing its own ASI methods, the WIL state machine, crystallization, and the namespace firewall. Used as ground truth for the conformance test vectors.

### Conformance Layers

An earlier three-layer scheme (structural / contextual / experiential) for grading adapter checks. It is not part of the specification: nothing in `SPEC.md` or the `CONFORMANCE*.md` documents depends on it. Conformance is defined by `SPEC.md` and the `CONFORMANCE*.md` documents; the conformance *tiers* (wire / state / behavioral) are defined in SPEC §20 §12.

### Conformance Test Vectors

Test cases stated in the `CONFORMANCE*.md` documents — inputs plus the property a conforming implementation must exhibit — that a third-party adapter must satisfy to claim conformance. Vectors are deterministic: same input bytes, same hashes, across implementations. Machine-readable vector files with pinned expected digests are planned and not yet published; the reference test suite in `tests/` exercises the reference implementation against the documents.

---

## 13. Versioning, Documents, and Amendments

### Episode of Record

For protocol amendments: the ASTP Episode that **ratifies** the change cryptographically. The amendment document is the human-readable description; the Episode of Record is the authoritative cryptographic anchor. Amendments without an Episode of Record are drafts, not ratified surface. See `VERSIONING.md`.

### Schema Version

The version of an individual node-type's payload schema, recorded as the `schema_version` field on `CognitiveNode`. Distinct from the protocol's overall version (which lives in `SPEC.md`'s header).

### Amendment

A normative change to the protocol, documented as an `AMENDMENT-vN.M-*.md` file. **Amendment-numbering as a separate scheme retires going forward** (see `VERSIONING.md`); amendments are deltas that integrate into the next published `SPEC.md` version. Existing amendment files are retained as historical artifacts under `docs/history/`.

### Versioning Policy

Defined in `VERSIONING.md`. SemVer `MAJOR.MINOR.PATCH`: MAJOR on canonical-form change (hash preimages, serialization, required fields), MINOR on additive surface, PATCH on errata. `SPEC.md`'s `Version:` field IS the protocol version — no separate Implementation Guide / Conformance / Amendment numbering schemes.

---

## Alphabetical Index

For lookup. Each term links back to its categorical definition above.

- **Adapter** — see §12 AriadneAdapter
- **Adapter Service Interface (ASI)** — §12
- **Aside** — §10
- **AriadneAdapter** — §12
- **Archived** — §6 (Episode Lifecycle)
- **BFM Taxonomy** — §10
- **Branch** — §10
- **CognitiveEdge** — §1
- **CognitiveNode** — §1
- **Coherence Fingerprint** — §10
- **Conformance Layers** — §12
- **Conformance Test Vectors** — §12
- **Consultation / ConsultationNode** — §2, §9
- **`content_hash`** — §3
- **`content_ref`** — §3
- **CREATED** — §6
- **Crystallization** — §7
- **CrystallizationDeltaNode** — §2
- **CRYSTALLIZED** — §6
- **CLOSING / CLOSING_PENDING_SEAL** — §6
- **Domain Separation** — §5
- **Dual Index** — §5
- **Episode / EpisodeNode** — §2
- **Episode Lifecycle** — §6
- **Episode of Record** — §13
- **`episode_root_hash`** — §3
- **ExchangeEntry** — §2
- **Fork** — §10
- **Governance (G-1 through G-N)** — §11
- **Hash Chain** — §5
- **HITLEventNode** — §2
- **Layer 1 / 2 / 3** — §4
- **`leaf_hash`** — §3
- **Merkle Spine** — §4 Layer 1
- **Merkle Tree / Merkle Root** — §5
- **Merge** — §10
- **Namespace Firewall** — §11
- **`node_id`** — §3
- **NodePayload** — §1
- **`parent_node_id`** — §3
- **Reference Implementation** — §12
- **Reparenting Prohibition** — §11
- **`schema_version`** — §3, §13
- **Sealed** — §6
- **Segment / SegmentNode** — §2
- **Signal / SignalNode** — §2
- **Soliloquy** — §10
- **Spine** — §5
- **`spine_hash`** — §3
- **Versioning Policy** — §13
- **WIL — Write Intent Log** — §8

---

*This glossary is a living document. When you encounter a term in code, in `SPEC.md`, or in an amendment that isn't defined here — or whose definition here is unclear — that's a gap worth raising. Each gap is documentation feedback from the implementation surface.*
- **Episode Root** — §5 (Hash Chain)
- **Exclusion Set** — §5 (Hash Chain)
- **Reproducibility Obligation** — §5 (Hash Chain)
- **Signal Manifest** — §5 (Hash Chain)
- **Spine Leaf Set** — §5 (Hash Chain)
- **Version Identifiers** — §5 (Hash Chain)
