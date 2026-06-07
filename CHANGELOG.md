# Changelog

All notable changes to the Ariadne protocol. Version numbering follows [VERSIONING.md](./VERSIONING.md).

## [Unreleased]

The next change-set queues here. `AMENDMENT-*.md` documents that have not yet been integrated into the SPEC body remain authoritative for the surface they define until the integration pass lands.

## [3.1.0] — 2026-06-07

**MINOR.** Layer 3 Workflow & Execution DAG codification. Additive on top of v3.0.0.

### Added
- **Layer 3 — Workflow & Execution DAG.** Source: `AMENDMENT-v3.0-WORKFLOW-EXECUTION-DAG.md` (amendment file retains its authoring numeral; canonical SPEC version per `VERSIONING.md` is v3.1.0).
- New node types: `WorkflowDeclaration`, `ExecutionNode`, `SkillInvocation`. Pydantic implementation in `ariadne/core/workflow_execution.py`.
- Three-Merkle-layer model formally specified in SPEC §3.4 Persistence Layer Model — Layer 1 Spine, Layer 2 episode content, Layer 3 Workflow & Execution DAG.
- New `CognitiveDeltaType` variants in `branching.py` for Layer 3 delta records.
- **Cognitive Implementation Authority (CIA)** — sole-writer pattern per workspace; wire-tier conformance principle. Only the designated CIA may write each Layer 3 node type.
- 40 new unit tests across the protocol suite.

### Invariants
- **Layer 3 is cryptographically isolated from Spine integrity.** Layer 3 nodes reference Layers 1/2 by ID only; they MUST NOT participate in Spine hash computation. No future Layer-3 change can retroactively force a MAJOR bump on Spine grounds — structural separation is the guarantee.
- `ExecutionNode` and `SkillInvocationNode` are immutable after creation. The only mutable Layer 3 field is `WorkflowDeclaration.status` (and `status_updated_at`).
- Hash byte-form left open at protocol layer per amendment §3 — each conformant implementation may choose its serialization, provided the canonical form is consistent within that implementation.

### Notes
- Layer 3 is the formal protocol surface for the autonomous-process audit trail; downstream consumers writing here include the Ignis Delegation Runner.
- The amendment was previously held on a private branch under the Chinese Wall agreement; the wall was lifted 2026-06-07 and the surface is now public.

## [3.0.0] — 2026-06-07

**MAJOR.** Cross-episode linking + grouping interface. Breaking hash preimage changes on three node types.

### Added
- **Cross-episode linking (Phase 1).** Source: `AMENDMENT-v2.0-CROSS-EPISODE-LINKING.md` (amendment file retains its authoring numeral; canonical SPEC version per `VERSIONING.md` is v3.0.0).
- `EpisodeLink` schema with `LinkType`, `LinkHealthState`, `Signal`/`SignalType` machinery, and `QuarantineResolution`. Neo4j adapter for cross-episode link reads/writes.
- `LINK_*` audit events + `assert_episode_link` operation. `LinkAcceptedDelta` for delta-record stream.
- `LinkGovernanceError` taxonomy for governance-layer failures.
- **Cross-episode discovery (Phase 2).** Link-proposal primitives + calibration loop for adapter-side discovery against existing episode corpora.
- **Grouping (Phase 1).** `MembershipRecord` as protocol-owned grouping artifact. `ConformanceDeclaration` for downstream conformance assertions. Succession-chain governance for both. Adapter-level grouping support.
- **Audit-the-decision pattern** for behavioral-tier implementation choices (SPEC §12 framing).
- **Three-tier conformance taxonomy** — wire / state / behavioral — formalized in the amendment.
- Shared core modules: `audit_chain.py`, `hash_canonical.py`, `constants.py` (refactor lifted duplicated helpers).

### Breaking changes (canonical form)
- Hash preimage changes on `EpisodeLink`, `MembershipRecord`, `ConformanceDeclaration`. Existing v2.x implementations are not wire-conformant against v3.0. See amendment Appendix A for the per-node breaking-change reference.

### Notes
- The amendment was previously held on a private branch under the Chinese Wall agreement; the wall was lifted 2026-06-07 and the surface is now public.
- v2.5.0-draft was never finalized as v2.5.0 — main moved directly to the v3.x line. v2.5.x is therefore not a maintenance line going forward; new work targets v3.x.

## [2.5.0-draft] — 2026-04-21

Working Draft. Phase 1-3 (node system) + Phase 4 (HITL) implemented; Branch/Fork/Merge Taxonomy §19 Phases 1-4 implemented.

### Added
- **Branch/Fork/Merge Taxonomy** — formal taxonomy of episode branching, forking, and merging events. SPEC §19. Includes prescriptive enforcement, resolution primitives (fork, merge, conflict surface), social/internal primitives (aside, soliloquy), and coherence-fingerprint write intercepts.
- `CONFORMANCE-BFM.md` — conformance vectors for the BFM Taxonomy.
- `IMPLEMENTATION-BFM.md` — implementation guide for BFM Taxonomy.
- `list_episodes_for_user` query.

## [2.4.0-draft] — 2026-04-16

### Added
- **HITL Protocol Amendment** — Phase 1 through Phase 4. Human-in-the-loop decision gates as first-class protocol nodes.
  - `HITLEventNode` — two-phase lifecycle (INVOKED → RESOLVED / TIMED_OUT). Participates in the Merkle spine as a causal anchor.
  - `PENDING_HITL` crystallization guard — blocks sealing during active human review.
  - Two-layer Ed25519 cryptographic attestation.
  - HITL Merkle spine participation and advisory gates.
- Implementation Guide updates to incorporate HITL guidance.

## [2.3.0] — 2026-04-12

### Added
- **Phase 3 trust infrastructure** — keys, anchoring, witnesses, chain proofs.
- **Protocol Boundary** documentation — clarifies what is normative protocol vs. implementation latitude.

## [2.2.0] — 2026-04-12

### Added
- **Phase 2 observability** — retrieval audit, `signal_versions_read` segment metadata.
- Caching and rebalance events.

## [2.1.0] — 2026-04-10

### Added
- **Retrieval coordination protocol** — the cross-agent retrieval surface.

## [2.0.0] — 2026-04 (pre-changelog history, inferred from `SPEC.md` introduction)

### Changed (BREAKING)
- **Protocol primitive becomes `CognitiveNode`, not `Episode`.** Episodes are the first *parameterization* of the protocol, not a precondition of it. Future node types (signals, agents, artifacts) slot into the same framework with zero protocol-layer changes.
- **Dual Index invariant**: `sequence_index` (immutable temporal position, hash-included) vs. `tree_leaf_index` (mutable structural position, hash-excluded). The epistemological core of the v2 line.

## [0.1.0-draft] — 2026-04-08

Original spec. Episode-centric model. Retained as `SPEC-v1.md` for historical reference; superseded by the v2.x line.
