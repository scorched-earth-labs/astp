# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository purpose

Ariadne is a **protocol** (specification + reference adapter), not an application. The artifacts shipped from this repo are:

1. The normative spec documents (`SPEC.md`, `AMENDMENT-v*.md`, `CONFORMANCE*.md`, `IMPLEMENTATION-*.md`, `VISION.md`).
2. The Python package `ariadne/` — protocol primitives, episode node type, and the Neo4j reference adapter.
3. Conformance test vectors that any third-party adapter must pass.

The downstream consumer is `ignis-os` (sibling repo at `../ignis-langgraph` / `../ignis-os`); changes here trigger a Hephaestus auto-ingestion hook (`.git/hooks/post-commit`) that re-indexes ignis-os against the new protocol code. Treat that hook as the canonical signal: if you change `ariadne/**/*.py`, the next commit will run ingestion against ignis-os.

## Commands

```bash
# Dev install (editable, with reference adapter + test deps)
pip install -e ".[neo4j,dev]"

# Full unit test suite
pytest

# Single file / single test
pytest tests/unit/protocol/test_verification.py
pytest tests/unit/protocol/test_verification.py::test_name -v

# Async tests are auto-mode (configured in pyproject.toml); no decorator needed
```

There is no lint, format, or typecheck command configured. Don't invent one.

The Neo4j adapter tests assume an adapter is wired by the caller — there is no fixture that boots Neo4j in this repo. Adapter integration tests live downstream in ignis-os.

## Architecture — the three-layer model

The codebase enforces a **three-layer split** that is load-bearing for the protocol's design. Violating the boundaries is a spec violation, not a style issue:

```
ariadne/protocol/   ← Layer-generic. Operates on CognitiveNode only.
                      NEVER imports from ariadne.nodes.*
                      Enforced by tests/unit/protocol/test_namespace_firewall.py
ariadne/nodes/      ← Node-type instantiation. Currently only `episode/`.
                      Each node type defines its own NodePayload.
ariadne/core/       ← Episode-era / Phase 2+ schema, governance, WIL,
                      branching, grouping, cross-episode linking,
                      workflow_execution (Layer 3).
ariadne/adapters/   ← AriadneAdapter ABC + Neo4j reference implementation.
                      Adapters import from core; core has no DB deps.
```

The **namespace firewall** (`ariadne.protocol.*` cannot import `ariadne.nodes.*`) is the most important invariant in the tree. If you add a file under `ariadne/protocol/`, the firewall test will fail if it reaches into `ariadne.nodes`. Move the symbol or rethink the design — do not relax the test.

### Layers in the spec sense (not the directory sense)

The protocol now defines **three Merkle layers** (see `AMENDMENT-v3.0-WORKFLOW-EXECUTION-DAG.md`):

- **Layer 1 — Merkle Spine**: kernel-owned, hash-chained `EpisodeNode`, `SegmentNode`, `SignalNode`, etc.
- **Layer 2 — Adaptive Merkle Tree**: episode content tree (crystallization, WIL).
- **Layer 3 — Workflow & Execution DAG**: `WorkflowDeclaration`, `ExecutionNode`, `SkillInvocation` in `ariadne/core/workflow_execution.py`. Layer 3 is **cryptographically isolated** from Spine integrity — it references Layers 1/2 by ID only and must never be hash-linked into the Spine.

Each Layer 3 node type has a designated **Cognitive Implementation Authority (CIA)** per workspace: a single writer is allowed. Don't add multi-writer paths to Layer 3 nodes — the sole-writer guarantee is a wire-tier conformance principle.

## Core invariants when modifying code

These come up constantly and aren't obvious from local context:

- **Dual Index**: `sequence_index` (immutable temporal position) is in the leaf hash preimage. `tree_leaf_index` (mutable structural position) is **not**. Never swap which one goes into the hash. See `ariadne/protocol/leaf_hash.py`.
- **Hash preimage stability within a major version**: any change to leaf-hash construction, spine Merkle algorithm, or `ContentDelta`/`StructuralDelta` core fields is a breaking protocol change and needs an amendment doc (`AMENDMENT-vN.0-*.md`) with a ratifying Episode of Record, not a quiet code change.
- **Governance rules G-1 through G-17+**: enforced inline in `ariadne/core/schema.py` and `ariadne/protocol/governance.py`. Each rule throws a specific subclass of `AriadneProtocolError`. Don't bypass them — adapters are required to surface the violation.
- **Reparenting is forbidden**, not "discouraged". `parent_node_id` is in the leaf hash. To "fix" parentage, create a new node and deprecate the old one.
- **Sealed nodes are immutable**. The pattern for amending a sealed record is always forward: new node + deprecation/succession edge. There is no in-place edit path.
- **Crystallization is a state transition, not a receipt**. `CrystallizationDeltaNode` is a block-header analog: immutable after creation, corrections flow forward through successor episodes.
- **WIL write ordering** (see `ariadne/core/wil.py`): durable content store → authoritative structural store → ephemeral coordinator → semantic search index. Interruption at any phase must be recoverable; all writes must be idempotent.

## Spec / implementation drift

The spec lives in this repo; the consumer implementation lives in `../ignis-os` (or `../ignis-langgraph`) under `src/ignis/ariadne/`. The `/spec-impl-diff` skill (user-invoked) is the canonical way to check drift between the two. When you change a spec section, expect the downstream implementation to either need an update or already be ahead of the spec — both are real cases.

The current spec is **v2.5.0-draft** in `SPEC.md`, with amendments v2.0 (cross-episode linking) and v3.0 (Layer 3 workflow/execution DAG) layered on top. `SPEC-v1.md` is retained for historical reference and is superseded.

## Documentation conventions

When you create new documents, follow the existing pattern: every normative document has a **Version**, **Status**, **Authors**, **Date**, and (for amendments) an **Episode of Record** with a UUID. Amendments are ratified in their Episode of Record — the document is the human-readable artifact, the Episode is the cryptographic anchor. Don't add docs without this header structure.

`GLOSSARY.md` is the **single source for term definitions**. Before defining a term inline in a new document, check whether it already lives in the glossary — if it does, reference it; if it doesn't and you're introducing the term, add it to `GLOSSARY.md` *first*, then use it. Inline definitions that contradict or duplicate glossary entries are a documentation drift hazard.

## Versioning

`VERSIONING.md` is the canonical policy: SemVer `MAJOR.MINOR.PATCH`, MAJOR on canonical-form change, MINOR on additive surface, PATCH on errata. `SPEC.md`'s `Version:` field IS the protocol version — no separate Implementation Guide / Amendment / Protocol version schemes. Change history lives in `CHANGELOG.md`. When making any change that touches normative surface, check whether it crosses canonical form (MAJOR) or is additive (MINOR) and update both `SPEC.md` and `CHANGELOG.md` accordingly.
