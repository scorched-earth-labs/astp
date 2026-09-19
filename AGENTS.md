# AGENTS.md

Guidance for AI coding agents (Claude Code, Codex, Copilot, Cursor and others) working in this repository. Human contributors: start with [`CONTRIBUTING.md`](./CONTRIBUTING.md).

## What this repository is

ASTP is a **protocol** — a specification plus a reference implementation — not an application. It ships:

1. The normative specification, `SPEC.md`, with its companion documents: `CONFORMANCE*.md` (conformance requirements), `IMPLEMENTATION-*.md` (implementer guides), `GLOSSARY.md`, `VERSIONING.md`, `CHANGELOG.md`.
2. The Python package `astp/` — protocol primitives, node types, and a Neo4j reference adapter.
3. The test suite under `tests/`.

`docs/history/` holds superseded documents, kept for provenance. Do not implement from them and do not update them.

## Commands

```bash
pip install -e ".[neo4j,dev]"     # editable install with adapter and test dependencies
pytest                            # full suite; needs no database and no network
pytest tests/unit/protocol/test_verification.py
pytest tests/unit/protocol/test_verification.py::test_name -v
```

There is no lint, format, or typecheck command configured. Don't invent one. Every test file must pass on its own as well as in the full run.

The Neo4j adapter takes a driver object from the caller. Nothing here starts a database; adapter integration tests belong to whoever wires the adapter to one.

## Architecture

```
astp/protocol/   Node-generic layer. Operates on CognitiveNode only.
astp/nodes/      Node-type instantiation (episode/, segment/). Each defines its NodePayload.
astp/core/       Episode-era schema, governance, WIL, branching, grouping,
                 cross-episode linking, workflow_execution (Layer 3).
astp/adapters/   AriadneAdapter ABC + the Neo4j reference implementation.
```

**The namespace firewall is the most important invariant in the tree:** nothing under `astp/protocol/` imports from `astp/nodes/`. `tests/unit/protocol/test_namespace_firewall.py` enforces it, along with a second rule: `astp/protocol/` imports nothing from `astp/core/` or `astp/adapters/` either. If a change seems to need such an import, the symbol is in the wrong layer — move the symbol or rethink the design. Do not relax the test.

### Persistence layers (SPEC §3.4 — not the same thing as the directories above)

- **Layer 1 — Merkle Spine.** The hash-chained, authoritative cognitive record.
- **Layer 2 — Episode Content.** Segments and their supporting structures, anchored to Layer 1 by parent reference.
- **Layer 3 — Workflow & Execution DAG** (SPEC §21; `astp/core/workflow_execution.py`). Cryptographically isolated: it references Layers 1 and 2 by identifier only and is never hash-linked into the Spine. Each Layer 3 node type has one designated writer per workspace (the Cognitive Implementation Authority). Do not add multi-writer paths.

## Invariants that are not obvious from local context

- **Dual index.** `sequence_index` (immutable temporal position) is in the leaf hash preimage. `tree_leaf_index` (mutable structural position) is not. Never swap them. See `astp/protocol/leaf_hash.py`.
- **Canonical form is stable within a major version.** A change to any hash preimage, Merkle construction, canonical serialization, or required field is a MAJOR protocol change under `VERSIONING.md` and goes through the amendment process in `GOVERNANCE.md`. It is never a quiet code change, and it is always introduced as a new versioned construction so existing sealed records stay verifiable.
- **Wire constants kept the `ariadne` prefix when the package became `astp`.** HKDF `info` strings, the `ariadne::` coordinator key prefix, `Ariadne*` graph labels. They feed derived keys or name stored data. `tests/unit/protocol/test_wire_constants.py` pins them; do not "fix" them.
- **Governance rules (`G-*`, numbered in `SPEC.md`)** are enforced where the write happens and raise. Do not catch and continue; adapters must surface the violation.
- **Reparenting is forbidden.** `parent_node_id` is in the leaf hash. To correct parentage, create a new node and deprecate the old one.
- **Sealed nodes are immutable.** Corrections go forward: new node plus a deprecation or succession edge. There is no in-place edit path.
- **Crystallization is a state transition, not a receipt.** `CrystallizationDelta` is immutable after creation.
- **WIL write ordering** (`astp/core/wil.py`, SPEC §12): durable content store → authoritative structural store → ephemeral coordinator → search index. Every write is idempotent, and an interruption at any phase is recoverable.

## Documents

- `SPEC.md`'s `Version:` field **is** the protocol version. A normative change updates that field and `CHANGELOG.md` together; a test checks they agree. `astp.PROTOCOL_VERSION` names the SPEC version the package implements; `astp.__version__` is the package's own version.
- `GLOSSARY.md` is the single source for definitions. Reference it; if you introduce a term, add it there first.
- New normative or companion documents carry the header block the existing ones use: **Version**, **Status**, **Authors**, **Date**.
- New `.py` files start with the repository's Apache-2.0 header, before the module docstring.
