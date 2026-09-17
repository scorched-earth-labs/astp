# Changelog

All notable changes to ASTP (the AI State Tree Protocol). Version numbering follows [VERSIONING.md](./VERSIONING.md).

## [Unreleased]

The next change-set queues here.

## [4.3.1] — 2026-09-17

**PATCH (errata).** Editorial pass over `SPEC.md` and the companion documents ahead of public release. **No normative change:** no hash construction, governance rule, field, state or requirement is altered, and every 4.3.0-conformant implementation is 4.3.1-conformant unchanged.

### Changed (editorial — `SPEC.md`)
- **Header.** Replaced with the standard block (Version, Status, Authors, Date, Supersedes — now naming `SPEC-v3.md` as well as `SPEC-v1.md`). The version-by-version narrative that had accumulated in the `Status` field is removed; every release it described already has an entry in this file. The header now states the BCP 14 (RFC 2119, RFC 8174) reading of the requirement keywords, which the document had used without citing, and states plainly that the Episode of Record identifier for 4.0.0 is not yet published.
- **§18 Version History** is now a pointer to this file. Details that existed only in that table were carried into the corresponding entries below (2.0.0–2.5.0-draft, 3.4.0, 4.0.0). §18's rows for 2.0.0–2.3.0 carried a `-draft` suffix that this file's headings omit; the dates agree.
- **§22 References** lists the public standards the text relies on (FIPS 202, RFC 2119, RFC 8174, RFC 5869, RFC 8032, RFC 9562, SemVer 2.0.0) in place of a list of unpublished internal design documents. §5.1 cites FIPS 202 for SHA3-256. Two references to an unpublished proof-system label ("P2") in §5.4 and §9.2 now describe the property (position-binding) in words.
- **§3.4** pointed at the former amendment document as "the authoritative reference" for Layer 3; it now points at §21 of this document, which is where that text has lived since 3.2.1.
- **§2.5.2** said "Governance rules G-1 through G-16"; the range is G-1 through G-39.
- **Cross-references corrected:** §5.6 "(§4.1 dual index)" → §3.3 and G-3; G-24 "§5 Step 8 of the build spec" (an unpublished document) → §19.3.3, where the three assertions are defined; §19.3.7 "§19.3.5 STEP 6" → §19.3.5 (that section has no numbered steps); §21 Appendix B "§13.2" → §13 item 2.
- **Cross-references removed because no correct target exists:** "codicil (§4.9)" in §4.4.1 and G-1 — there is no §4.9; both now cite the registered `CODICIL_APPEND` operation (§12.4.1) instead. "(§7)" for the crystallization lock in §4.4.1 (§7 is Delta Records; the lock has no section of its own — the text now cites §4.6 and G-18 for the HITL guard). "(§8)" in §5.6 (§8 is the audit chain). "(§4.4)" for Segment `content_ref` in §4.7 (§4.4 is Episode). Defining the codicil, the crystallization lock and the Segment schema is left to a later release.
- **Review residue removed from normative text** with the substance kept: internal review labels in §19 and §20 (gap numbers, review-round numbers, a decision number, a scenario label — including the label in the §20 §9 heading) and the names of internal reviewers. Cross-Episode ordering timestamps in §20 §11.5.3 and the §20 checklist, previously attributed to a named internal component, now read "timestamps assigned by a workspace-wide monotonic timestamp authority". The §20 §11.3.3 heading is now "Quarantine Escalation". A personal name in §20 §11.2.6 is generalized to "the ratifying human principal".
- **§21.** The `WORKFLOW_CLOSED` trigger named a downstream product's tool; it now names the `close_workflow` operation of §21 §10. Normative text that named the downstream runtime now says "reference implementation", and the non-normative Appendix A says once what that runtime (Ignis OS) is. The provisional version numerals attached to two deferred items in §21 §13 (both numerals have since been used for other releases) are dropped; the items remain deferred to "a future amendment".
- **Removed:** the stale "Amendment v3.0.0 — Working Draft … Pending ratification" footer at the end of §21; a doubled `## 13. Spine Tip Cache` heading.
- **Removed (orphan paragraph):** a paragraph in §20 §11.3.1 on "Reverse delta for `SECTION_SUPERSESSION`". Neither `SECTION_SUPERSESSION` nor `supersedes_clause` is defined or used anywhere else in the specification or the reference implementation, so the paragraph's requirement could not be implemented or tested. It is retained in the historical amendment text under `docs/history/`.

### Changed (editorial — other documents)
- **Historical documents moved to `docs/history/`**, each with a uniform banner saying it is retained for provenance, what superseded it and when: `VISION.md`, `SPEC-v1.md`, `SPEC-v3.md`, `AMENDMENT-v2.0-CROSS-EPISODE-LINKING.md`, `AMENDMENT-v3.0-WORKFLOW-EXECUTION-DAG.md`. `AMENDMENT-v3.0`'s status line said "Working Draft"; it now records that the amendment was published as SPEC 3.1.0 and folded into §21 at 3.2.1. `VERSIONING.md`'s retention rule names the new location.
- **Headers.** `GLOSSARY.md`, `VERSIONING.md` and `IMPLEMENTATION-BFM.md` gain the standard header block. `IMPLEMENTATION-PHASE3.md`'s header said 1.0.0 / SPEC v2.3.0-draft while its footer said 1.1.0 / v2.4.0-draft; the header now agrees with the footer. `CONFORMANCE.md` and `IMPLEMENTATION-PHASE3.md` state that they were written against the 2.x drafts and have not yet been re-verified against 4.x.
- **`GLOSSARY.md`** states which SPEC version it was last fully reconciled with (`2.5.0-draft`) and that reconciliation with 4.x is in progress. Its "Conformance Test Vectors" entry no longer says byte-level vectors live in `tests/`.
- **`README.md`.** The Conformance Testing section described a three-layer framework in `astp.core.contracts` that adapters "must pass"; nothing in the package or the test suite uses that module. The section now describes what exists: the `CONFORMANCE*.md` requirement documents and the reference test suite, with machine-readable vectors planned and not shipped. Installation is `pip install -e ".[neo4j,dev]"` from a checkout (Python >= 3.11; distribution and import name are both `astp`). Copyright line and an explicit statement that specification text and code are both Apache-2.0.
- **`CONFORMANCE.md`** no longer refers to a conformance registry at an unspecified location, or to a separate ASI conformance suite; neither exists. Reference values will be published as vector files in this repository in a later release.
- Example identifiers in the implementation guides are neutral (`agent-a`, `human-1`); stale absolute test counts and notes-to-self are removed from the guides and from this file; review labels are removed from `CONFORMANCE-CROSS-EPISODE-LINKING.md` and `CONFORMANCE-BFM.md`.
- **This file:** the 0.1.0-draft date now agrees with the document it describes (2026-04-07); a link to a non-public repository and references to downstream internals are removed.

### Changed (reference package — no protocol change)

- The Python import package is renamed `ariadne` → `astp`, matching the distribution name (package version 0.2.0). `from ariadne.…` becomes `from astp.…`; nothing else about the API moves.
- **Not renamed, deliberately:** the HKDF `info` strings (`ariadne.workspace.v1`, `ariadne.node.v1:{node_type}`, `ariadne.seal.v1`), the coordinator key prefix (`ariadne::`), the graph labels (`Ariadne*`), the `ARIADNE_ENABLED` flag, and the `Ariadne*` class names. The first three are inputs to derived keys or names of stored data; `tests/unit/protocol/test_wire_constants.py` pins them.
- `astp.PROTOCOL_VERSION` names the `SPEC.md` version the package implements; a test compares its MAJOR.MINOR with this specification's `Version:` field. `astp.__version__` remains the package's own version.
- `sha3_256` is defined in `astp.protocol.hashing` (still importable from `astp.core.schema`), so that `astp.protocol` imports nothing from `astp.core` or `astp.adapters`. The test suite now enforces that as well as the `astp.nodes` firewall, including relative and dynamic imports.
- Importing `astp.nodes` registers both shipped node types (`episode`, `segment`); previously `segment` was registered only when its subpackage was imported directly.
- Removed the unused module `astp.core.contracts`. Added `py.typed`, PEP 639 licence metadata and a `MANIFEST.in`; the sdist now carries the specification, the companion documents and the tests.
- Every test file passes when run on its own; CI checks this.

## [4.3.0] — 2026-09-13

**MINOR.** Reproducibility. Motivated by the first corpus-scale re-verification of the
reference deployment's 62 sealed Episodes (2026-09-13): 45 spine roots rebuilt from
stored nodes; 8 rebuildable only under the pre-2026-04-01 tree implementation (the
function had been replaced in place before the versioning rule existed); 4 rebuildable
only by searching orderings of same-timestamp signals (the seal ordered SPINE signals by
arrival time — an ordering key signals do not reliably have); one post-closure append
that the reference G-1 guard did not refuse because it covered SEALING/SEALED/ARCHIVED
but not CLOSED. No evidence of content tampering. Every item below is additive.

### Added
- **§5.6 Episode Spine Leaf Set** — the spine is the Episode's non-ephemeral Segments in
  `sequence_index` order and nothing else; signals are not spine leaves. `sequence_index`
  is the sole ordering key and is total, so no tiebreak exists to get wrong.
- **§5.7 Episode Root** — publishes the three-component root
  `SHA3-256("NODE:" ‖ spine_root ‖ signal_manifest_hash ‖ exclusion_hash)` (previously an
  internal design). The signal manifest and exclusion set are order-independent sets
  with domain-separated constructions and empty-set sentinels.
- **§5.8 Version identifiers** — optional `hash_version` on `CognitiveNode`,
  `spine_algorithm_version` and `ordering_version` on `CrystallizationDelta`. Outside every
  hash preimage; absent means pre-4.3.0. Backfill is an annotation, never a re-seal.
- **§9.3 Reproducibility obligation** — a verifier holding only stored nodes MUST be able to
  recompute the sealed roots; a stored-root lookup is not a verification.
- **`CONFORMANCE-REPRODUCIBILITY.md`** — new `RP-*` family (RP-001…RP-004) and
  `tests/unit/protocol/test_reproducibility_conformance.py`.
- Reference implementation: `compute_spine_root_v2`, `compute_signal_manifest_hash`,
  `compute_exclusion_hash`, version constants; `compute_spine_hash` (ordering version 1)
  is retained unchanged so historical seals remain reproducible.

### Changed
- **G-1** — states that appends are refused from `CLOSING_PENDING_SEAL` onward, including
  `CLOSED`, `CRYSTALLIZATION_PENDING`, `SEALING`, `SEALED`, `ARCHIVED`; codicils are the sole
  sanctioned post-closure append. Reference `enforce_G1_write_guard` widened to match
  (`G1_FROZEN_STATES`). This is a clarification of §4.4.1, which already said a `CLOSED`
  Episode admits only codicils.

### Changed (editorial — no normative change)
- **Public naming residue.** The four `CONFORMANCE*.md` titles and their intro/footer lines still said "Ariadne Protocol"; they now say ASTP, matching the SPEC/README rebrand (v3.2.2 era). Code identifiers, package paths, HKDF info strings, Redis key prefixes and Neo4j labels are unchanged by design — "Ariadne" remains the internal codename.
- **README drift.** The README restated the protocol version (`3.2.2`, while SPEC was 4.2.1) and the governance range ("G-1 through G-9", while SPEC defines through G-39). Both now defer to `SPEC.md` instead of restating it. The package structure tree now shows the `protocol/` and `nodes/` layers and the namespace firewall.

### Clarified (errata — PATCH)
- **Segment parentage vs. proof-chain parentage.** New §3.4.1 states explicitly that a Segment's `parent_node_id` is its **`EpisodeNode`** (an upward anchor), that segments order by `sequence_index` with no segment→segment edge, and that the canonical materialization is an ordered `(Episode)-[:CONTAINS {sequence_index}]->(Segment)` fan-out (derive next/prev at read time, don't persist a chain). A reciprocal note at §16.5.3 distinguishes this from the proof-chain rule `B.parent_node_id == A.node_id`, which links whole nodes causally (e.g. episode→episode). **No canonical-form change** — this clarifies existing semantics (G-2 reparenting prohibition; §5.2 leaf-hash preimage). Surfaced by a reference-implementation question: an adapter graph showed a segment→segment containment chain instead of the canonical episode→segment fan-out.

## [4.2.1] — 2026-08-21

**PATCH.** `write_attachment_node_sync` — sync variant of `create_attachment_node`, for callers that are not async and cannot become so without restructuring their caller in turn. Exists for the same reason `write_document_node_sync` does, and writes the same node and edge, so the two variants are indistinguishable in the graph.

Documents its own limit: a caller performing an attachment owes an `ATTACHMENT_COMMIT` entry under G-39, and this function cannot produce one because write-intent coordination is async by necessity. A sync caller must surface that its write is unledgered rather than absorb the gap (§12.4.2).

## [4.2.0] — 2026-08-21

**MINOR.** Restores `CONSULTATION_COMMIT` to the §12.4.1 register (Tier 1) and corrects a contradiction.

v3.5.0 removed the operation on the stated ground that "the protocol does not define" consultation. **It does, and always has:** G-8 and G-9 have governed consultation since v1, and `compute_consultation_node_hash` / `compute_exchange_chain_hash` are protocol hash functions. SPEC.md asserted both positions at once until now.

- One operation covers the consultation node, its ordered exchange entries and the consulted agent's participation record — they commit together, so they are one operation rather than three.
- **Collaboration gets no separate operation.** It is a `ConsultationType`, so a collaborative session commits as a consultation and the type distinguishes it; a second register name would encode in the ledger what the node already records.
- §12.4 clarifies that an operation's **tier turns on whether an interruption leaves recoverable work, not on store count** — a multi-record write to one store is Tier 1 when a partial write leaves a chain stopping mid-sequence. The register already assigned tiers this way; the definitions had said "more than one store".
- Reference implementation gains `create_consultation_node`, `create_exchange_entry_node`, `create_consultation_participant_node` and `execute_consultation_commit`. These were the last abstract adapter methods without implementations, and they were unimplemented only because of the same mistaken premise.

**Additive** — no existing operation, node or conformance requirement changes.

## [4.1.1] — 2026-08-20

**PATCH.** `create_amendment_link_node` — the last abstract adapter method with no Neo4j implementation.

`AriadneAdapter.create_amendment_link` was declared and left `...`, so consumers reopening a sealed Episode wrote their own node and edges. Same gap as codicils, closure records, episode-status transitions and attachments; this closes the set.

Writes the node and **both** edges — `AMENDS` to the source, `PRODUCES` to the new Episode. The link is not symmetric: following provenance backwards wants the source, asking "what came of this" wants the amendment, and one edge would make the other direction a scan. G-1 is deliberately not enforced — the source is sealed *by definition*, which is the precondition for amending it, not an obstacle.

**Known gap recorded, not closed:** `create_consultation`, `create_exchange_entry` and `create_consultation_participant` remain abstract with no implementation. v3.5.0 retired consultation from the protocol but removed only its WIL operations and `SegmentType` members — these three methods and the `ConsultationNode` / `ExchangeEntry` / `ConsultationParticipantNode` types survived, and appear nowhere in SPEC.md. Finishing that removal is a cross-repository migration, because downstream consumers import these types from the protocol schema. Pinned by test so the gap cannot grow.

## [4.1.0] — 2026-08-20

**MINOR.** SPEC §4.7 `AttachmentNode` — external content injected into an Episode's context, recorded so the injection is verifiable after the fact.

- Narrow by design: episode, content hash, media type, locator, who and when.
- **Kind is a property, not a node type.** A document, an image and an audio file are one node distinguished by `media_type`. Separate node types per artifact kind would contradict §1 ("agnostic to node type") and force a protocol revision for every new format.
- `content_hash` is over the content **as received**, never an extraction — hashing text pulled from a PDF proves the extraction unchanged while leaving the PDF unverified.
- `ATTACHMENT_COMMIT` registered (Tier 1), with writer and coordinated write.

**Additive** — no existing node, operation or conformance requirement changes. `DocumentNode` remains as legacy in the reference implementation; its docstring claimed protocol status the specification never conferred, and its `drive_url` / `content_text` / `char_count` fields are precisely why that claim was untrue.

## [4.0.0] — 2026-08-20

**MAJOR.** Ledgering obligations (SPEC §12.4.2), deferred since 3.4.0. Requires a ratifying **Episode of Record**.

- **G-39** — an implementation MUST record a ledger entry for every §12.4.1 operation it performs. Performing one without an entry is a conformance violation, not a degraded mode.
- Scoped to operations *performed*: an implementation owes nothing for capabilities it does not implement.
- Ledger writes MAY be best-effort with respect to availability, but a gap MUST be surfaced rather than absorbed — the distinction is between an implementation that cannot record and knows it, and one that does not record and cannot tell.
- **Consequence:** a missing entry from a conforming implementation now means the operation did not occur. That inference was explicitly unavailable before. It remains unavailable for records written prior to this version, and an implementation MUST NOT retroactively assert coverage over a period it did not have it.
- Tier 1 entries with `completed_at=null` past the provisional window continue to record an interrupted write — strictly more information than either a completed entry or none.

**Breaking.** Every 3.x-conformant implementation that performs a registered operation without ledgering it becomes non-conformant. `SPEC.md` at 3.5.1 retained as `SPEC-v3.md` (now [`docs/history/SPEC-v3.md`](./docs/history/SPEC-v3.md)).

## [3.5.1] — 2026-08-20

**PATCH (errata).** SPEC §4.4.1 Episode Lifecycle States.

The prior one-line list read "ACTIVE, REBALANCING, SEALING, SEALED, SEALING_FAILED, REBALANCE_FAILED, ARCHIVED, EXPIRED". Four of those states have never existed in any implementation; seven real ones were missing, including the entire closure workflow. Four of eleven overlapped.

Written 2026-04-09, two days *after* the enum it was describing already carried the states it omitted — wrong on the day it was authored, not drift. Replaced with the closed set as a table, plus: **crystallization is a fact recorded by a `CrystallizationDelta`, not a state**; an implementation MUST NOT infer it from `episode_status`, and MAY restore the pre-lock status, which is required for correctness mid-closure.

## [3.5.0] — 2026-08-19

**MINOR.** Retires `CONSULTATION_COMMIT` and `COLLABORATION_COMMIT` from the §12.4.1 register, and the never-used `SegmentType.CONSULTATION` / `COLLABORATION` members.

Both describe multi-agent interaction patterns the protocol does not define; registering their operations extended the protocol's vocabulary to cover behaviour it does not specify. Implementations that ledger them namespace them (for example `vendor:CONSULTATION_COMMIT`) under the §12.4.1 prefix rule. No conformant implementation affected — neither operation was ever emitted by the reference implementation, and the segment types had no writer and zero instances.

## [3.4.0] — 2026-08-18

**MINOR.** Write Intent Log operation register (SPEC §12.4).

§12 defined *how* a write intent is recorded but never *which* operations record one, so the vocabulary existed only as a Python enum documented nowhere normative. Adds the closed register of all operation values and the two entry forms: **Tier 1 coordinated write** (multi-store, full three-phase §12.2 protocol, `completed_at=null` past the provisional window is a recovery candidate) and **Tier 2 ledger record** (single authoritative store, one completed entry at commit, never a recovery candidate).

New governance rules **G-37** and **G-38** constrain the *form* of an entry whenever one is written; neither compels an entry to exist. §12.4.2 deferred that obligation to 4.0.0.

§12.4.1 closes the register against extension values that lack an implementation namespace prefix, and records that `SEGMENT_COMMIT` and `SIGNAL_COMMIT` are not interchangeable. §12.4.2 states that, while the obligation is deferred, a verifier MUST NOT infer from a missing entry that an operation did not occur.

## [3.3.0] — 2026-07-05

**MINOR.** Departure-fork orphan recovery (SPEC §19.3.7). Additive on top of v3.2.x — no breaking changes; every v3.2.x-conformant implementation remains conformant. The runtime enforcement layer for the §19.3.5 producer invariants: it catches partial-failure states the producers couldn't prevent (a crash between the two writes, a rolled-back status).

### Added
- **`ForkOrphanMarker`** — a non-chained diagnostic satellite recording a detection event. Self-hashed (domain `FORK_ORPHAN_MARKER:`) for tamper-evidence, but NOT a member of the origin spine's Merkle chain (no `parent_hash`; writing it never alters the origin episode's root/tip). Read-only after write; deduplicated one-per-orphaned-fork (keyed on `fork_id`); excluded from departure-registry queries. New `OrphanClass` enum (`CLASS_A..D`).
- **Four orphan classes** — A (dangling `DepartureForkPointNode`, no episode), B (unanchored fork episode, no point), C (`ForkReturnNode` present but fork not `COMPLETED`), D (stale `ACTIVE` fork).
- **The one permitted retroactive spine write** (Class B) — `write_retroactive_departure_fork_point_sync` appends the missing `DepartureForkPointNode` using the fork episode's stored `fork_origin_spine_tip_hash` as the point's `spine_tip_hash_at_departure` (cross-verify holds by construction), gated by a hash-consistency check (escalate, don't write, on mismatch). Byte-identical to an on-time write; `retroactive`/`orphan_recovery_timestamp` are diagnostic metadata outside the hash preimage. Mirrors RETROACTIVE branch declaration.
- **Recovery write-primitives** (protocol exposes the writes; the consumer orchestrates detection): `write_fork_orphan_marker_sync`, `mark_departure_fork_point_orphaned_sync` (Class A), `write_retroactive_departure_fork_point_sync` + `mark_fork_episode_unanchored_sync` (Class B), `correct_fork_status_by_orphan_recovery_sync` (Class C).
- **New diagnostic fields** — on `DepartureForkPointNode`: `orphaned`, `retroactive`, `orphan_recovery_timestamp`; on the fork `EpisodeNode`: `fork_orphaned`, `fork_orphan_class` (`UNANCHORED`), `status_corrected_by_orphan_recovery`, `status_corrected_at`. New `ForkOrphanClass` enum. None participate in any content hash.

### Not normative
- **Detection cadence.** Whether/how often an implementation scans for orphans is operational hygiene, not protocol conformance. Only the shape of a conformant *recovery* (the node, the field mutations, the retroactive-write discipline) is normative.

### Tests
`test_phase2_operations.py` — `TestForkOrphanRecovery` (6): marker hash determinism + satellite (no `parent_hash`), dedup-on-`fork_id`, Class-A append-only flag, Class-B retroactive append (backdated anchor + byte-identical hash), Class-B unanchored, Class-C status correction.

## [3.2.2] — 2026-07-04

**PATCH.** Prose errata — the §20/§21 hash-preimage descriptions were reconciled to the reference implementation. **No canonical-form change; the code was already correct** — only the SPEC prose was wrong, so every v3.2.1-conformant implementation remains conformant unchanged. Surfaced while authoring the §20/§21 implementation & conformance companion docs.

### Corrected (errata)
- **§20 hash algorithm.** `EpisodeLink.content_hash`, `MembershipRecord.content_hash`, and `ConformanceDeclaration.declaration_hash` are computed with **SHA3-256**, not SHA-256 — consistent with the §5 "all hashing uses SHA3-256, no exceptions" commitment and the `hash_canonical.py` implementation. The prose said "SHA-256".
- **§20 MembershipRecord preimage.** The preimage binds `supersedes_record_id` and `succession_reason` in addition to the seven fields the prose listed (per `_MEMBERSHIP_HASH_PREIMAGE_FIELDS`).
- **§20 EpisodeLink exclusions.** The preimage **includes** `health_state` and `health_checked_at`; it excludes only `quarantine_resolved_at` and `quarantine_resolution` (set after the hash, on quarantine exit). The prose had the exclusion list inverted.
- **§21 Form-B attribution.** The reference implementation serializes in declared field order and hashes with SHA3-256 — not key-sorted JSON with SHA-256. §21 §8 still leaves the Layer-3 byte-form implementation-open; this only corrects the description of what the reference implementation does.

## [3.2.1] — 2026-07-04

**PATCH.** SPEC integration pass — editorial only, no normative change. The full protocol surface now lives in the SPEC body; the two standalone amendment documents are retired to provenance-only historical references.

### Changed (editorial)
- **Cross-episode linking + grouping** folded into SPEC **§20** (was `AMENDMENT-v2.0-CROSS-EPISODE-LINKING.md`, canonical SPEC v3.0.0).
- **Layer 3 Workflow & Execution DAG** folded into SPEC **§21** (was `AMENDMENT-v3.0-WORKFLOW-EXECUTION-DAG.md`, canonical SPEC v3.1.0). References section moved to §22.
- The amendment's CIA conformance rule was renumbered from its authoring numeral **G-19** (which collided with the BFM Taxonomy's G-19) to **G-36**, keeping the governance-rule namespace contiguous (G-1…G-36).
- Status line + §18 Version History updated; the amendment files carry historical-reference banners pointing at their in-body sections.

### Notes
- No hash preimage, serialization, or required-field changes. Every v3.2.0-conformant implementation is v3.2.1-conformant unchanged.

## [3.2.0] — 2026-07-04

**MINOR.** Phase D departure-fork lifecycle. Additive on top of v3.1.0 — no breaking changes. Defined in the SPEC body (§19.3.5–19.3.6), not as a standalone amendment.

### Added
- **`create_departure_fork()`** — a single **directional departure**: one topic diverges into a new Episode while the originating Episode *continues*. Distinct from the speculative `create_fork()` (N siblings, resolve→promote/discard). Atomic: fork Episode (ACTIVE + immutable provenance) + `DepartureForkPointNode` on the origin spine (`FORK_ORIGIN`) + `DEPARTURE_FORK_CREATED` audit.
- **Lifecycle FSM** — `ACTIVE → COMPLETED | ABANDONED`. `complete_departure_fork()` (fork's own agent), `abandon_departure_fork()` (origin agent / system stub-cleanup). Resumption (re-entering the origin while the fork stays ACTIVE) is a non-event.
- **`declare_fork_return()`** — a **declarative** return (origin asserts incorporation across two independent spines; never the branch's structural merge). Writes `ForkReturnNode` on the origin spine + `FORK_RETURN`/`RETURNED_FROM` edges + `DEPARTURE_FORK_RETURNED` audit. `return_type ∈ {INCORPORATED, ACKNOWLEDGED, SUPERSEDED}`.
- **New nodes/domains** — `DepartureForkPointNode` (`DEPARTURE_FORK_POINT:`), `ForkReturnNode` (`FORK_RETURN:`). **New deltas** — `DEPARTURE_FORK_CREATED` / `_COMPLETED` / `_ABANDONED` / `_RETURNED`. **New edges** — `FORK_RETURN`, `RETURNED_FROM`. **Immutable Episode fork provenance** fields (§19.3.6).
- **Governance G-30 through G-35** — the backdating integrity invariant (G-30: `spine_tip_hash_at_departure` == the fork Episode's `fork_origin_spine_tip_hash`), non-empty objective, trigger whitelist, `AGENT_ESCALATION` requires a trigger segment, return-requires-COMPLETED, one-return-per-fork.

### Tests
`test_phase2_operations.py` — `TestCreateDepartureFork`, `TestDepartureForkFSM`.

## [3.1.0] — 2026-06-07

**MINOR.** Layer 3 Workflow & Execution DAG codification. Additive on top of v3.0.0.

### Added
- **Layer 3 — Workflow & Execution DAG.** Source: `AMENDMENT-v3.0-WORKFLOW-EXECUTION-DAG.md` (amendment file retains its authoring numeral; canonical SPEC version per `VERSIONING.md` is v3.1.0).
- New node types: `WorkflowDeclaration`, `ExecutionNode`, `SkillInvocation`. Pydantic implementation in `ariadne/core/workflow_execution.py`.
- Three-Merkle-layer model formally specified in SPEC §3.4 Persistence Layer Model — Layer 1 Spine, Layer 2 episode content, Layer 3 Workflow & Execution DAG.
- New `CognitiveDeltaType` variants in `branching.py` for Layer 3 delta records.
- **Cognitive Implementation Authority (CIA)** — sole-writer pattern per workspace; wire-tier conformance principle. Only the designated CIA may write each Layer 3 node type.
- New unit tests across the protocol suite.

### Invariants
- **Layer 3 is cryptographically isolated from Spine integrity.** Layer 3 nodes reference Layers 1/2 by ID only; they MUST NOT participate in Spine hash computation. No future Layer-3 change can retroactively force a MAJOR bump on Spine grounds — structural separation is the guarantee.
- `ExecutionNode` and `SkillInvocationNode` are immutable after creation. The only mutable Layer 3 field is `WorkflowDeclaration.status` (and `status_updated_at`).
- Hash byte-form left open at protocol layer per amendment §3 — each conformant implementation may choose its serialization, provided the canonical form is consistent within that implementation.

### Notes
- Layer 3 is the formal protocol surface for the autonomous-process audit trail.

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
- v2.5.0-draft was never finalized as v2.5.0 — main moved directly to the v3.x line. v2.5.x is therefore not a maintenance line going forward; new work targets v3.x.

## [2.5.0-draft] — 2026-04-21

Working Draft. Phase 1-3 (node system) + Phase 4 (HITL) implemented; Branch/Fork/Merge Taxonomy §19 Phases 1-4 implemented.

### Added
- **Branch/Fork/Merge Taxonomy** — formal taxonomy of episode branching, forking, and merging events. SPEC §19. Includes prescriptive enforcement, resolution primitives (fork, merge, conflict surface), social/internal primitives (aside, soliloquy), and coherence-fingerprint write intercepts.
- BranchPoint/BranchTerminus (§19.2); ForkPoint/MergePoint/BranchReturn with three-Merkle-root verification (§19.3); AsideSegment/SoliloquySegment with the HASH_PLACEHOLDER content policy (§19.4); CoherenceFingerprint write-intercept state machine and ConfirmationCache (§19.5).
- Governance rules **G-19 through G-29**. Delta types `BRANCH_CREATED`/`ABANDONED`, `FORK_CREATED`/`RESOLVED`, `MERGE_EXECUTED`, `ASIDE_OPENED`/`CLOSED`, `SOLILOQUY_INITIATED`/`CONCLUDED`. AuditRecord chain integrity (`prior_audit_hash`), IntentRecord idempotency, derived lifecycle state (§19.2.4).
- `CONFORMANCE-BFM.md` — conformance vectors for the BFM Taxonomy.
- `IMPLEMENTATION-BFM.md` — implementation guide for BFM Taxonomy.
- `list_episodes_for_user` query.

## [2.4.0-draft] — 2026-04-16

### Added
- **HITL Protocol Amendment** — Phase 1 through Phase 4. Human-in-the-loop decision gates as first-class protocol nodes.
  - `HITLEventNode` — two-phase lifecycle (INVOKED → RESOLVED / TIMED_OUT). Participates in the Merkle spine as a causal anchor.
  - `PENDING_HITL` crystallization guard — blocks sealing during active human review.
  - Two-layer Ed25519 cryptographic attestation.
  - HITL Merkle spine participation and advisory gates (`CONDITIONALLY_VALID`); `HITL_GATE` edges (BLOCKS / FOLLOWS); `pending_hitl_ref` segment tagging.
  - Governance rules **G-17** (invocation before resolution) and **G-18** (crystallization block). Schema version 1.2.0. SPEC §4.6.
- Implementation Guide updates to incorporate HITL guidance.

## [2.3.0] — 2026-04-12

### Added
- **Phase 3 trust infrastructure** — node key hierarchy (§16.2), transparency log anchoring (§16.3), witness signatures (§16.4), cross-node chain proof (§16.5). Governance rules **G-11 through G-16**.
- **Protocol Boundary** documentation (§2.5) — clarifies what is normative protocol vs. implementation latitude.

## [2.2.0] — 2026-04-12

### Added
- **Phase 2 observability** — retrieval audit records (§11.1), `signal_versions_read` segment metadata (§4.5).
- Spine tip cache (§13) and rebalance events (§14).

## [2.1.0] — 2026-04-10

### Added
- **Retrieval coordination protocol** — the cross-agent retrieval surface: snapshot isolation (§10.4), tail write advisory (§10.5), HITL re-validation gate (§10.6), side-effect contract (§11).

## [2.0.0] — 2026-04-09 (pre-changelog history, inferred from `SPEC.md` introduction)

### Changed (BREAKING)
- **Protocol primitive becomes `CognitiveNode`, not `Episode`.** Episodes are the first *parameterization* of the protocol, not a precondition of it. Future node types (signals, agents, artifacts) slot into the same framework with zero protocol-layer changes.
- **Dual Index invariant**: `sequence_index` (immutable temporal position, hash-included) vs. `tree_leaf_index` (mutable structural position, hash-excluded). The epistemological core of the v2 line.
- Position-binding leaf hash, the five-test gate, and the namespace firewall.

## [0.1.0-draft] — 2026-04-07

Original spec. Episode-centric model. Retained as [`docs/history/SPEC-v1.md`](./docs/history/SPEC-v1.md) for historical reference; superseded by the v2.x line.
