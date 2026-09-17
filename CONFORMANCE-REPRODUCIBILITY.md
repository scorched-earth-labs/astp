# ASTP — Reproducibility Conformance Test Vectors

**Version:** 1.1.0
**Status:** Working Draft
**Authors:** Scorched Earth Labs
**Date:** 2026-09-17
**Applies To:** SPEC.md v4.3.0 — §5.6 Episode Spine Leaf Set, §5.7 Episode Root, §5.8 Algorithm and Ordering Versions, §9.3 Reproducibility Obligation, G-1
**Companions:** [CONFORMANCE.md](CONFORMANCE.md) (§16 trust infrastructure), [CONFORMANCE-BFM.md](CONFORMANCE-BFM.md), [CONFORMANCE-LAYER3.md](CONFORMANCE-LAYER3.md), [CONFORMANCE-CROSS-EPISODE-LINKING.md](CONFORMANCE-CROSS-EPISODE-LINKING.md)

---

## 1. Overview

The Five-Test Gate (§9.1) is only as strong as the verifier's ability to rebuild the
sealed root. These vectors test that ability directly. They exist because the first
corpus-scale re-verification of a production deployment (2026-09-13, 62 sealed
Episodes) found that 17 of them could not be rebuilt from stored nodes under the
construction their seal claimed:

| Outcome | Episodes |
|---|---|
| Root rebuilt from stored nodes | 45 |
| Rebuilt only under an earlier tree function, which had been replaced in place | 8 |
| Rebuilt only by searching the orderings of same-timestamp signals | 4 |
| Not rebuilt under any construction — one has too many tied signals to search and had also accepted content after closure; the other is within reach of a longer search | 2 |
| In a sealed status with no seal record at all, so no root to rebuild | 3 |

Of the 57 seals that were rebuilt, none showed evidence of content tampering. The
remaining 5 could not be evaluated: 2 did not rebuild under any construction, and 3
have no root to rebuild. None of this was visible until a verifier tried to
reproduce the roots.

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
- **Description:** The spine root is a function of the Episode's non-ephemeral Segment content hashes in `sequence_index` order and, under `spine_algorithm_version` 1, the Episode's identifier (the Episode-identifier leaf, §5.6) — and nothing else. Two verifiers holding the same stored Segments and the same `episode_id` produce the same root; any state not on the nodes (insertion order, a store's default sort, a cache, the signals) plays no part.
- **Inputs:**
  ```
  segment_content_hashes (sequence_index order): 7 hashes, SHA3-256("leaf-0") … SHA3-256("leaf-6")
  episode_id: "550e8400-e29b-41d4-a716-446655440000"
  spine_algorithm_version: 1
  ordering_version: 2
  ```
- **Expected Output:**
  ```
  SHA3-256("leaf-0")                         aa6c290f56f0f7eb3a8da563ae72efc5d10cc89b88a3112c612d8e3825e20aad
  Episode-identifier leaf input
    SHA3-256(episode_id)                     0bdfe537564300a840a9b2279b3c4d0c8ca0e0c3b0c3d9c95c105852f991f222
  spine_root  (spine_algorithm_version 1)    3cdbc3f20a909338a55a5b9687d72ce4b6f74ad1d3784a377c91b1bba06f2491
  spine_root  (spine_algorithm_version 0,
               same seven inputs)            0654211304f104a768b81432567776c7f13f65b97e4937f114f5c65e8dbc5fed
  ```
  Hash values enter the tree as 64-character lowercase hex strings, ASCII-encoded (§5.3); an unpaired node is carried up unchanged (§5.4). The root is **not** equal to the `ordering_version` 1 root computed with any signals included; it differs when the segment order is permuted; an empty leaf set is refused.
- **Failure Condition:** Either root differs from the value above; the root changes when signals are added; the root is order-insensitive; an empty leaf set yields a root.

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
- **Expected Output:**
  ```
  signal_manifest_hash (the five hashes, any order, with or without duplicates)
                                             0a4a4582ad36da24dcd21853b07ed97d13a8c223cf14845588861d9d5786b670
  signal_manifest_hash (SHA3-256("leaf-104") removed)
                                             5b73a9aa0cf76aaa0399dce72733b48d5e441b7f236dc063d570eecdde5ff22d
  signal_manifest_hash (empty)               5188531fe69daafc79126dfa880419494179ca220d60d5dda2fee8279d4ae847
  exclusion_hash (empty)                     45849be4da47e279538916284a2ac74cd6acd60a67b9a8982992f97afa149be6
  episode_root_hash  (RP-001 spine_root under spine_algorithm_version 1,
                      the five-member manifest, empty exclusion set)
                                             49c1b61c22d00c185dceca5eb39f65bd88c2666281444687c59c48b0b199d7fe
  ```
  The Episode root differs when the manifest or the exclusion set differs.
- **Failure Condition:** Any value differs from the one above; any ordering-dependence; duplicates altering the hash; a root insensitive to a component.

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
