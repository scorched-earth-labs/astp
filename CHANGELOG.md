# Changelog

All notable changes to the Ariadne protocol. Version numbering follows [VERSIONING.md](./VERSIONING.md).

## [Unreleased]

Working drafts and amendments not yet integrated into a finalized version. See `AMENDMENT-*.md` for in-flight normative work.

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
