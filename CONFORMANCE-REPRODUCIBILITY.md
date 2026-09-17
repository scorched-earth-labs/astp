# ASTP — Reproducibility Conformance Test Vectors

**Version:** 1.0.0
**Status:** Working Draft
**Authors:** Scorched Earth Labs
**Date:** 2026-09-13
**Applies To:** SPEC.md v4.3.0 — §5.6 Episode Spine Leaf Set, §5.7 Episode Root, §5.8 Algorithm and Ordering Versions, §9.3 Reproducibility Obligation, G-1
**Companions:** [CONFORMANCE.md](CONFORMANCE.md) (§16 trust infrastructure), [CONFORMANCE-BFM.md](CONFORMANCE-BFM.md), [CONFORMANCE-LAYER3.md](CONFORMANCE-LAYER3.md), [CONFORMANCE-CROSS-EPISODE-LINKING.md](CONFORMANCE-CROSS-EPISODE-LINKING.md)

---

## 1. Overview

The Five-Test Gate (§9.1) is only as strong as the verifier's ability to rebuild the
sealed root. These vectors test that ability directly. They exist because the first
corpus-scale re-verification of a production deployment (2026-09-13, 62 sealed
Episodes) found seals that could not be reconstructed from stored nodes alone: some
because the hash implementation had been replaced in place, some because the seal's
leaf ordering depended on arrival timestamps that collide, and one because a closed
Episode had accepted new content. None involved tampering; all were invisible until
a verifier tried to reproduce the roots.

A conforming implementation MUST pass all vectors marked **REQUIRED**. Format follows
[CONFORMANCE.md §1](CONFORMANCE.md).

Reference implementation: `astp/core/schema.py` (`compute_spine_root_v2`,
`compute_signal_manifest_hash`, `compute_exclusion_hash`, `compute_episode_root_hash`,
`enforce_G1_write_guard`), tested in
`tests/unit/protocol/test_reproducibility_conformance.py`.

---

## 2. Spine Reproducibility (§5.6, §9.3)

**RP-001** — Spine Root From Stored Nodes Only
- **Class:** REQUIRED
- **Spec Reference:** §5.6, §9.3
- **Description:** The spine root is a function of the Episode's non-ephemeral Segment content hashes in `sequence_index` order and nothing else. Two verifiers holding the same stored Segments produce the same root; any state not on the nodes (insertion order, a store's default sort, a cache, the signals) plays no part.
- **Inputs:**
  ```
  segment_content_hashes (sequence_index order): 7 hashes, SHA3-256("leaf-0") … SHA3-256("leaf-6")
  episode_id: "550e8400-e29b-41d4-a716-446655440000"
  spine_algorithm_version: 1
  ordering_version: 2
  ```
- **Expected Output:** `spine_root` identical across two independent computations; equal to the Adaptive Merkle Tree root over the segment leaves alone; **not** equal to the ordering-version-1 root computed with any signals included; different when the segment order is permuted; an empty leaf set is refused.
- **Failure Condition:** Two computations differ; the root changes when signals are added; the root is order-insensitive; an empty leaf set yields a root.

---

## 3. Signal Manifest (§5.7)

**RP-002** — Signal Manifest Is a Set
- **Class:** REQUIRED
- **Spec Reference:** §5.7
- **Description:** The signal manifest hash depends only on the *set* of SPINE-placed signal content hashes. Arrival order, timestamps, and duplicates do not change it; membership does. The empty manifest is well defined and distinct from the empty exclusion set. The Episode root changes when any component changes.
- **Inputs:**
  ```
  signal_content_hashes: 5 hashes, SHA3-256("leaf-100") … SHA3-256("leaf-104"), presented in five different orders
  construction: SHA3-256("SIGNAL_MANIFEST:v1:" || sorted hashes joined by "|"); empty → SHA3-256("SIGNAL_MANIFEST:v1:EMPTY")
  exclusion: SHA3-256("EXCLUSION:v1:" || …); empty → SHA3-256("EXCLUSION:v1:EMPTY")
  episode_root_hash = SHA3-256("NODE:" || spine_root || signal_manifest_hash || exclusion_hash)
  ```
- **Expected Output:** One manifest hash for all five orderings; the same hash with a duplicated member; a different hash with a member removed; `signal_manifest_hash([]) ≠ exclusion_hash([])`; the Episode root differs when the manifest or the exclusion set differs.
- **Failure Condition:** Any ordering-dependence; duplicates altering the hash; empty manifest and empty exclusion colliding; a root insensitive to a component.

---

## 4. Version Identifiers (§5.8)

**RP-003** — Version Tags Select the Function and Stay Out of the Preimage
- **Class:** REQUIRED
- **Spec Reference:** §5.8
- **Description:** A seal record carries `spine_algorithm_version` and `ordering_version`; a `CognitiveNode` carries `hash_version`. They are recorded and retrievable, default to absent (seal) / `1` (node) so pre-4.3.0 records read as legacy, and are **outside** every hash preimage: two seal records differing only in tags have the same content hash, and two nodes differing only in `hash_version` have the same leaf hash.
- **Inputs:**
  ```
  CrystallizationDelta A: sealed_chain_root R, spine_algorithm_version 1, ordering_version 2
  CrystallizationDelta B: sealed_chain_root R, no version tags
  CognitiveNode N1: hash_version 1 (default);  N2: identical fields, hash_version 7
  ```
- **Expected Output:** A reports (1, 2); B reports (None, None); `content_hash(A) == content_hash(B)`; `leaf_hash(N1) == leaf_hash(N2)`.
- **Failure Condition:** Tags not persisted; tags entering a preimage (content or leaf hash differs by tag alone); a tagless record read as current rather than legacy.

---

## 5. Fixed Record (G-1)

**RP-004** — A Closed Episode Refuses Content
- **Class:** REQUIRED
- **Spec Reference:** G-1, §4.4.1
- **Description:** A Segment or Signal commit against an Episode whose record is fixed MUST be refused with a governance error. Fixed means `CLOSING_PENDING_SEAL`, `CLOSED`, `CRYSTALLIZATION_PENDING`, `SEALING`, `SEALED`, `ARCHIVED`. Open means `CREATED`, `ACTIVE`, `PENDING_HITL`, `CLOSING`, `CRYSTALLIZED`. Codicils are exempt and use their own path.
- **Inputs:** each `EpisodeStatus` value, presented to the write guard.
- **Expected Output:** governance error for every fixed state — **`CLOSED` included**; no error for every open state.
- **Failure Condition:** Any fixed state admits a commit. (The reference guard before 4.3.0 admitted `CLOSED`; the production corpus holds one post-closure append as a result.)

---

## 6. Governance Rule Enforcement Matrix

| Governance Rule | Description | Test Vectors | Class |
|----------------|-------------|-------------|-------|
| **G-1** | Write guard — no appends to a fixed record | RP-004 | REQUIRED |
| §9.3 | Reproducibility obligation | RP-001, RP-002, RP-003 | REQUIRED |

## 7. Out of Scope

- Reproduction of seals written under `ordering_version` 1 with colliding arrival timestamps. Such seals are reproducible only by search; an implementation MAY record a verified-by-search attestation (§5.8) but no vector requires it.
- Re-sealing of historical records. Prohibited by §5.8 — a re-seal is a post-closure mutation.

---

*ASTP Reproducibility Conformance Test Vectors are maintained by Scorched Earth Labs.*
