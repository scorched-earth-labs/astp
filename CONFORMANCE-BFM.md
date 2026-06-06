# Ariadne Protocol — BFM Conformance Test Vectors

**Version:** 1.0.0-draft
**Status:** Working Draft
**Authors:** Scorched Earth Labs / Clotho
**Date:** 2026-04-23
**Applies To:** SPEC.md §19 (Branch / Fork / Merge / Aside / Soliloquy / CoherenceFingerprint)

---

## 1. Overview

This document specifies the conformance test vectors for the Branch/Fork/Merge (BFM) feature family of the Ariadne Protocol. A conforming implementation MUST pass all vectors marked **REQUIRED**. Vectors marked **RECOMMENDED** test behaviors that conforming implementations SHOULD support.

BFM is organized into four internal phases matching `IMPLEMENTATION-BFM.md`:

| Phase | Scope | Vector Prefix |
|-------|-------|---------------|
| 1 | Branch lifecycle (linear deviation) | `BR-` |
| 2 | Fork / merge / common ancestor | `FM-` |
| 3 | Aside / Soliloquy (social & internal primitives) | `AS-` / `SL-` |
| 4 | Coherence fingerprint write-time branch detection | `CF-` |

Vector format matches `CONFORMANCE.md` (Phase 3 Trust Infrastructure §16): ID, spec reference, class, description, inputs, expected output, failure condition. All hex values lowercase. All string fields UTF-8.

---

## 2. Phase 1 — Branch Lifecycle Vectors (§19.2)

### 2.1 Hash Canonicalization

**BR-001** — `BranchPointNode` commitment hash
- **Class:** REQUIRED
- **Spec Reference:** §19.2.3, G-17
- **Description:** `compute_branch_point_hash()` MUST produce identical bytes across implementations given identical inputs. The canonical byte layout is defined in §19.2.3 and covers: `parent_episode_id`, `branch_id`, `declaration_type`, `parent_sequence_index`, `branch_root_content_hash`, `authored_by`, `created_at`.
- **Verification Protocol:** Cross-implementation consistency check (pattern matches KH-001). Two conforming implementations MUST produce identical `branch_point_hash` bytes for the same input tuple.
- **Failure Condition:** Divergent bytes indicate a canonicalization error (wrong field order, wrong integer encoding, missing field).

**BR-002** — `BranchTerminusNode` commitment hash
- **Class:** REQUIRED
- **Spec Reference:** §19.2.3
- **Description:** `compute_branch_terminus_hash()` canonicalizes `branch_id`, `terminus_type`, `final_sequence_index`, `terminus_content_hash`, `abandonment_reason` (optional), `authored_by`, `closed_at`.

**BR-003** — `AuditRecord` commitment hash
- **Class:** REQUIRED
- **Spec Reference:** §19.2.4, G-19
- **Description:** `compute_audit_record_hash()` forms a content-addressed chain where `prior_audit_hash` binds each record to its predecessor. Implementations MUST NOT allow silent tampering; recomputing the hash over stored fields MUST match the stored `audit_hash`.
- **Failure Condition:** Any stored `AuditRecord` whose recomputed hash diverges from its stored value.

**BR-004** — `IntentRecord` idempotency key
- **Class:** REQUIRED
- **Spec Reference:** §19.2.5
- **Description:** `compute_intent_idempotency_key()` MUST collapse retried writes with the same `(agent_id, intent_type, resource_id, request_sequence)` tuple to the same key. A second `create_branch` call with the same idempotency key MUST return the original `BranchResult` without creating a new `BranchPointNode`.

### 2.2 Governance Enforcement

**BR-005** — Branch depth limit (G-18)
- **Class:** REQUIRED
- **Spec Reference:** §19.2.2
- **Description:** `enforce_branch_depth_limit()` MUST reject any `create_branch` whose resulting lineage depth exceeds the spec-defined maximum (default 8). Depth is counted from the root episode, inclusive.
- **Failure Condition:** A 9-deep lineage is successfully created without raising.

**BR-006** — Access policy gate (G-20)
- **Class:** REQUIRED
- **Spec Reference:** §19.2.6
- **Description:** `enforce_access_policy()` MUST reject branch creation whose `AccessPolicy` denies the requester's `AccessLevel` for the requested `AccessResourceType`. The check happens before any write.

**BR-007** — Abandonment reason required
- **Class:** REQUIRED
- **Spec Reference:** §19.2.7
- **Description:** `enforce_abandonment_reason_required()` MUST reject `abandon_branch()` calls whose `reason` is `None` or the empty string. A branch with `terminus_type=ABANDONED` MUST have a non-empty reason recorded.

---

## 3. Phase 2 — Fork / Merge Vectors (§19.3)

### 3.1 Hash Canonicalization

**FM-001** — `ForkPointNode` commitment hash
- **Class:** REQUIRED
- **Spec Reference:** §19.3.2
- **Description:** `compute_fork_point_hash()` canonicalizes `parent_episode_id`, `fork_id`, `objective_hash`, `sibling_branch_ids` (sorted), `parent_sequence_index`, `authored_by`, `created_at`.

**FM-002** — `MergePointNode` commitment hash
- **Class:** REQUIRED
- **Spec Reference:** §19.3.4
- **Description:** `compute_merge_point_hash()` canonicalizes all three integrity roots (`parent_root`, `left_root`, `right_root`) plus `merge_id`, `merge_type`, `merge_strategy`, `summary_hash`, `authored_by`, `merged_at`.

**FM-003** — `ConflictManifest` commitment hash
- **Class:** REQUIRED
- **Spec Reference:** §19.3.5
- **Description:** `compute_conflict_manifest_hash()` canonicalizes an ordered list of `ConflictSegment`+`ConflictResolution` pairs. Order-independence is a non-goal; reordering changes the hash.

### 3.2 Governance Enforcement

**FM-004** — Fork objective required
- **Class:** REQUIRED
- **Spec Reference:** §19.3.1, G-21
- **Description:** `enforce_fork_objective_required()` MUST reject `create_fork()` whose `objective` is missing or empty. The forked branches inherit a shared objective hash.

**FM-005** — Fork sibling count ≥ 2
- **Class:** REQUIRED
- **Spec Reference:** §19.3.1
- **Description:** `enforce_fork_sibling_count()` MUST reject a fork creating fewer than 2 sibling branches. A "fork of one" is semantically a branch, not a fork.

**FM-006** — Merge summary required (G-22)
- **Class:** REQUIRED
- **Spec Reference:** §19.3.4
- **Description:** `enforce_merge_summary_required()` MUST reject `execute_merge()` calls without a non-empty `summary`. Every merge records why the convergence happened.

**FM-007** — Three-root conflict-surface integrity (G-23)
- **Class:** REQUIRED
- **Spec Reference:** §19.3.5, IMPLEMENTATION-BFM §4.3
- **Description:** A successful merge MUST record all three integrity roots (`parent_root`, `left_root`, `right_root`) and the `ConflictManifest` MUST reference segments that exist under those three roots only. Resolving a conflict against a segment outside this surface is a governance violation.
- **Verification Protocol:** Given a conflict manifest, every referenced segment's `content_hash` MUST be reachable from at least one of the three recorded roots.
- **Failure Condition:** A manifest entry references a segment_id not present under any of the three roots.

**FM-008** — `find_common_ancestor()` determinism
- **Class:** REQUIRED
- **Spec Reference:** §19.3.3
- **Description:** `find_common_ancestor(branch_id, target_episode_id)` MUST return the same `CommonAncestorResult` across repeated invocations on stable graph state. The algorithm MUST prefer the most-recent shared ancestor (LCA semantics) when multiple common ancestors exist.

**FM-009** — Merge integrity verification
- **Class:** REQUIRED
- **Spec Reference:** §19.3.6
- **Description:** `verify_merge_integrity()` MUST re-verify all three Merkle roots and the conflict manifest hash against stored `MergePointNode` fields. Any field-level mutation MUST produce a verification failure.

---

## 4. Phase 3 — Aside / Soliloquy Vectors (§19.4)

### 4.1 Aside Hash Canonicalization

**AS-001** — `AsideSegmentNode` commitment hash
- **Class:** REQUIRED
- **Spec Reference:** §19.4.2
- **Description:** `compute_aside_hash()` canonicalizes `aside_id`, `parent_segment_id`, `initiated_by_human`, `target_agent_id`, `content_hash`, `opened_at`.

### 4.2 Aside Governance

**AS-002** — Aside human-initiated (G-24)
- **Class:** REQUIRED
- **Spec Reference:** §19.4.1
- **Description:** `enforce_aside_human_initiated()` MUST reject an aside whose `initiated_by_human` is missing or does not identify a human user. Asides are strictly human-initiated — agent-initiated diversions use soliloquy.

**AS-003** — Aside target agent required
- **Class:** REQUIRED
- **Spec Reference:** §19.4.1
- **Description:** `enforce_aside_target_agent()` MUST reject an aside without a `target_agent_id`. Every aside pairs one human with one agent; multi-agent asides are modeled as nested asides.

**AS-004** — Aside close reason required
- **Class:** REQUIRED
- **Spec Reference:** §19.4.3
- **Description:** `enforce_aside_close_reason()` MUST reject `close_aside()` without a non-empty `reason`. The close reason is what distinguishes `AsideTerminationStatus` values (`resolved`, `abandoned`, `superseded`, etc).

**AS-005** — Aside return obligation at episode seal
- **Class:** REQUIRED
- **Spec Reference:** §19.4.4, G-25
- **Description:** `check_aside_return_obligation(aside_open=True, episode_sealing=True)` MUST raise. An episode MUST NOT seal while an aside is open; all asides must either close or be explicitly abandoned first.

**AS-006** — Aside external reference scan
- **Class:** RECOMMENDED
- **Spec Reference:** IMPLEMENTATION-BFM §5.2
- **Description:** On aside close, implementations SHOULD scan for segments outside the aside subgraph that reference the aside's segments (via `mentions`, `derives_from`, etc.) and flag them for review. This is advisory (not governance) but valuable for downstream audit.

### 4.3 Soliloquy Hash Canonicalization

**SL-001** — `SoliloquySegmentNode` content hash
- **Class:** REQUIRED
- **Spec Reference:** §19.4.5
- **Description:** `compute_soliloquy_content_hash()` behavior is policy-dependent on `SoliloquyContentHashPolicy`:
  - `FULL` — hash over all deliberation segments concatenated canonically
  - `STRUCTURAL` — hash over segment count + sequence index tuple only (content excluded)
  - `OMITTED` — hash is the zero digest (soliloquy content treated opaque)
- **Verification Protocol:** Given a fixed `SoliloquyVisibilityPolicy`, implementations MUST match byte-for-byte. Switching policy across implementations expectedly produces different hashes.

**SL-002** — Deliberation chain hash
- **Class:** REQUIRED
- **Spec Reference:** §19.4.6
- **Description:** `compute_deliberation_chain_hash()` binds each soliloquy segment to its predecessor via a rolling hash chain. Tampering with any intermediate segment MUST be detectable by recomputing the chain and comparing to the stored conclusion's `chain_hash`.

**SL-003** — `SoliloquyConclusionNode` hash
- **Class:** REQUIRED
- **Spec Reference:** §19.4.6
- **Description:** `compute_soliloquy_conclusion_hash()` canonicalizes `soliloquy_id`, `chain_hash`, `summary_hash`, `termination_status`, `concluded_at`.

### 4.4 Soliloquy Governance

**SL-004** — Soliloquy purpose required
- **Class:** REQUIRED
- **Spec Reference:** §19.4.5
- **Description:** `enforce_soliloquy_purpose_required()` MUST reject `create_soliloquy()` without a non-empty `purpose`. A soliloquy without a purpose is indistinguishable from a branch.

**SL-005** — Human-accessible visibility policy (G-26)
- **Class:** REQUIRED
- **Spec Reference:** §19.4.7
- **Description:** `enforce_soliloquy_human_accessible()` MUST verify that every soliloquy's `SoliloquyVisibilityPolicy` allows at least one identified human user to view the conclusion. Agent-only soliloquies (no human visibility ever) are forbidden.

**SL-006** — Conclusion summary required
- **Class:** REQUIRED
- **Spec Reference:** §19.4.6
- **Description:** `enforce_soliloquy_conclusion_required()` MUST reject `conclude_soliloquy()` without a non-empty `summary`. The summary is the only content guaranteed visible to humans under all visibility policies.

**SL-007** — Soliloquy return obligation
- **Class:** REQUIRED
- **Spec Reference:** §19.4.8
- **Description:** `check_soliloquy_return_obligation()` MUST raise when an episode attempts to seal with an open soliloquy. Mirror of AS-005 for agent-initiated deliberation.

---

## 5. Phase 4 — Coherence Fingerprint Vectors (§19.5)

### 5.1 Hash Canonicalization

**CF-001** — `CoherenceFingerprint` hash
- **Class:** REQUIRED
- **Spec Reference:** §19.5.2
- **Description:** `compute_fingerprint_hash()` canonicalizes `fingerprint_id`, `agent_id`, `session_id`, `computed_at`, `components` (a fixed-order dict of signal→score), `version`. Field order and component ordering are part of canonicalization.

**CF-002** — Objective hash
- **Class:** REQUIRED
- **Spec Reference:** §19.5.3
- **Description:** `compute_objective_hash()` MUST be a stable function of the objective text. Two semantically-equivalent objectives with different wording MUST produce different hashes — the hash is syntactic, not semantic.

### 5.2 Detection State Machine

**CF-003** — State machine transitions
- **Class:** REQUIRED
- **Spec Reference:** §19.5.4, IMPLEMENTATION-BFM §6.2
- **Description:** `advance_detection_state()` MUST implement the canonical state machine:
  - `CLEAR` → `WARNING` when divergence exceeds `DetectionThresholds.warning_threshold`
  - `WARNING` → `MATERIALIZED` when divergence exceeds `materialize_threshold` and persists `materialize_sustain_turns` consecutive turns
  - `MATERIALIZED` → `CLEAR` only via operator override or via convergence below `clear_threshold` for `clear_sustain_turns` turns
  - Direct `CLEAR` → `MATERIALIZED` MUST NOT occur
- **Verification Protocol:** Given a sequence of `(fingerprint, thresholds)` inputs, the output `DetectionState` sequence MUST match the canonical state machine execution.

**CF-004** — Materialized recommendation
- **Class:** REQUIRED
- **Spec Reference:** §19.5.5
- **Description:** `compute_materialized_recommendation()` MUST produce a deterministic `IntentClass` recommendation given the same `DetectionResult`. Non-determinism (e.g., model-sampling-based suggestions) violates conformance.

### 5.3 Write-Time Enforcement

**CF-005** — Write-time fingerprint gate (G-27)
- **Class:** REQUIRED
- **Spec Reference:** §19.5.6
- **Description:** `enforce_write_time_fingerprint()` MUST reject segment writes whose `fingerprint` is `None` in episodes where fingerprint enforcement is enabled. Segments written without fingerprints cannot be retroactively analyzed for branch candidacy.

**CF-006** — Intercept sequence ordering
- **Class:** REQUIRED
- **Spec Reference:** IMPLEMENTATION-BFM §6.3
- **Description:** `intercept_segment_write()` MUST execute in the order: (1) compute fingerprint, (2) query registry for prior fingerprints, (3) `detect_branch_candidate()`, (4) `advance_detection_state()`, (5) consult `ConfirmationCache`, (6) return a decision to the caller. A different ordering may produce inconsistent results.

### 5.4 Confirmation Cache Idempotency

**CF-007** — `ConfirmationCache` idempotency
- **Class:** REQUIRED
- **Spec Reference:** §19.5.7, IMPLEMENTATION-BFM §6.4
- **Description:** Given the same `(fingerprint_hash, intent_class, confirming_party)` tuple, `ConfirmationCache` MUST return the same `ConfirmedAction` across repeated lookups. Cache entries are idempotent — re-confirming a prior decision is a no-op, not a new decision.
- **Failure Condition:** Two lookups with identical tuples produce different `ConfirmedAction` values.

**CF-008** — Cache invalidation on fingerprint change
- **Class:** REQUIRED
- **Spec Reference:** §19.5.7
- **Description:** A fingerprint change (new `fingerprint_hash`) MUST force fresh detection; a prior `ConfirmedAction` under the old fingerprint MUST NOT apply to the new one. Confirmations are bound to the fingerprint that produced them.

---

## 6. Governance Rule Enforcement Matrix

Summary of governance rules enforced across BFM, for cross-reference with SPEC §19's rule catalog:

| Rule | Scope | Vector(s) |
|------|-------|-----------|
| G-17 | Branch point integrity | BR-001 |
| G-18 | Branch depth limit | BR-005 |
| G-19 | Audit chain | BR-003 |
| G-20 | Access policy | BR-006 |
| G-21 | Fork objective | FM-004 |
| G-22 | Merge summary | FM-006 |
| G-23 | Three-root conflict surface | FM-007 |
| G-24 | Aside human-initiated | AS-002 |
| G-25 | Aside return obligation | AS-005 |
| G-26 | Soliloquy human visibility | SL-005 |
| G-27 | Write-time fingerprint | CF-005 |

---

## 7. Conformance Levels

### Level 1: Protocol Conformance

Implementation passes all **REQUIRED** vectors in sections 2–5 and the governance matrix in section 6. No claim is made about storage layout or performance.

### Level 2: Full Conformance

Level 1 plus all **RECOMMENDED** vectors and the advisory checks in IMPLEMENTATION-BFM §5.2 (aside external reference scan) and §8 (test coverage matrix).

---

## 8. Cross-Reference

- **SPEC.md §19** — normative protocol surface
- **IMPLEMENTATION-BFM.md** — Neo4j reference adapter (non-normative)
- **CONFORMANCE.md** — Phase 3 Trust Infrastructure vectors (§16)

---

*Ariadne Protocol BFM Conformance Test Vectors are maintained by Scorched Earth Labs.*
*Vector set version: 1.0.0-draft | Applies to SPEC.md: v2.3.0-draft §19*
