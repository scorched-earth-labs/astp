# ASTP 5.0.0 — Seal Constructions (Draft)

**Version:** 5.0.0-draft.1
**Status:** Draft for review — **not ratified, not normative.** Nothing here applies to any existing seal.
**Authors:** Scorched Earth Labs
**Date:** 2026-09-17
**Applies To:** proposed replacement text for `SPEC.md` §5.2–§5.8 in 5.0.0
**Vectors:** [`vectors/5.0.0-draft/seal-constructions.json`](../../vectors/5.0.0-draft/seal-constructions.json) · **Reference code:** `astp/protocol/encoding.py`, `compute_leaf_hash_v2`, `compute_merkle_root_v2`, `astp/core/seal_v2.py` · **Tests:** `tests/conformance/test_seal_constructions_v2_vectors.py`

This is one unit of the 5.0.0 amendment: how an Episode's roots are built. It is a MAJOR change under [`VERSIONING.md`](../../VERSIONING.md) and requires an Episode of Record. Every construction below is **new and versioned**. Seals made under `spine_algorithm_version` 0 and 1 remain defined by SPEC 4.5.0 §5.3–§5.8 and remain reproducible; 5.0.0 retains that text as the definition of those versions.

---

## 1. What changes, and why

| 4.x, as built | 5.0.0 | Reason |
|---|---|---|
| Spine leaf input is the Segment's bare `content_hash` | Spine leaf input is the Segment's **position-binding leaf hash** | The 4.x spine root commits to content and order only. It does not bind a Segment's identity, type, schema version, position or parent — the protocol's headline property, held only by a tree the seal never used. |
| Hash values enter the tree as 64 ASCII hex characters | Hash values enter every construction as **32 raw bytes** | §5.2 and G-13 already use raw bytes; the tree was the deviation. Encoding is now a property of the algorithm version. |
| First leaf is `SHA3-256(episode_id)` | **No Episode-identifier leaf**; `episode_id` is in the Episode root | Each leaf now binds its parent, the Episode, so the leaf is redundant. It is dropped in this construction and not before: under content-hash leaves it is the only guard against transplanting a spine. |
| `sealed_at` in the leaf-hash preimage | **Removed** | A leaf hash is computed once, at creation; a node is unsealed at creation. Under version 1 the field made every sealed node fail content verification. The seal record binds the seal. |
| Branch, fork and merge points and HITL events committed into no root | A **structural manifest**, fourth component of the Episode root | Removing one changes no sealed root today. As spine leaves they would need an ordering key they do not have — the defect behind the four tie-order seals. A set has no order to get wrong. |
| Colon- and pipe-joined text preimages; `NODE:` / `LEAF:` reused across constructions | One **canonical field encoding**; one **domain prefix per construction and version** | `("obj:alice","bob")` and `("obj","alice:bob")` hash identically under 4.x. A HITL node hash and a consultation node hash are byte-identical in form to a Merkle interior node. |

## 2. Canonical field encoding

A construction built from named fields is `SHA3-256(prefix ‖ enc(f₁) ‖ … ‖ enc(fₙ))`: a domain prefix, then the fields in the order the construction lists them. Each field is a one-byte type tag followed by its payload:

| Tag | Type | Payload |
|---|---|---|
| `0x00` | NULL | none — an absent optional field |
| `0x01` | BYTES | `u32be(length)` ‖ bytes |
| `0x02` | STRING | `u32be(length)` ‖ UTF-8 of the text after Unicode NFC normalization |
| `0x03` | UINT | 8 bytes big-endian, 0 ≤ n < 2⁶⁴ |
| `0x04` | UUID | 16 bytes |
| `0x05` | TIMESTAMP | 8 bytes big-endian: whole milliseconds since 1970-01-01T00:00:00Z |
| `0x06` | HASH | 32 bytes — a SHA3-256 value, raw, never its hex text |

A TIMESTAMP MUST be computed from a timezone-aware instant, converted to UTC, in integer arithmetic; a value with no timezone MUST be refused. Sub-millisecond precision is truncated. A field count is fixed by its construction, every field is self-delimiting, and no prefix in §7 is a prefix of another, so distinct inputs cannot encode to the same bytes.

An order-independent **set of hashes** is `SHA3-256(prefix ‖ u32be(n) ‖ h₁ ‖ … ‖ hₙ)` over the distinct members, 32 raw bytes each, sorted ascending bytewise. The empty set is `n = 0`; there is no sentinel.

## 3. Leaf hash — `hash_version` 2

```
leaf_hash = SHA3-256( "LEAF_HASH:v2:"
                      ‖ UUID(node_id) ‖ STRING(node_type) ‖ STRING(schema_version)
                      ‖ UINT(sequence_index) ‖ HASH(content_hash) ‖ UUID|NULL(parent_node_id) )
```

The version 1 fields without `sealed_at`, under the encoding of §2. An absent parent is NULL, which cannot be confused with the nil UUID. `tree_leaf_index` remains excluded (dual-index invariant, §3.3). The leaf hash is computed once, at node creation, and never recomputed.

`node_id` MUST be generated with at least 122 bits of randomness (UUIDv4 or equivalent) and MUST NOT be derived from the node's content or any other guessable input. `content_hash` is an unsalted hash of content; it is the unguessable `node_id` in this preimage that makes a published leaf hash useless for testing a guess at a Segment's content.

## 4. Merkle tree and spine — `spine_algorithm_version` 2

The tree is the one §5.4 has always described: inputs in the order given; pair from the left; an unpaired node is **carried up unchanged**, neither duplicated nor re-hashed; a single input's level-0 hash is the root; **the root of an empty list is undefined and MUST be refused.**

```
level 0:   SHA3-256( "TREE_LEAF:v2:" ‖ input )            input: 32 raw bytes
interior:  SHA3-256( "TREE_NODE:v2:" ‖ left ‖ right )      left, right: 32 raw bytes
```

The spine of an Episode is this tree over the `hash_version` 2 leaf hashes of its non-ephemeral Segments in `sequence_index` order (`ordering_version` 2, unchanged). There is no other leaf.

A verifier MUST derive the encoding from the identifier: hex text under `spine_algorithm_version` 0 and 1, raw bytes under 2 — never assume it. The three versions are one tree; they differ in leaf input, in encoding, and in whether the Episode-identifier leaf is present.

The spine and the tree of §9 (five-test gate) and §16.5 (inclusion proofs) are now **the same tree over the same inputs**. A position-binding inclusion proof therefore proves position in the sealed spine, which under 4.x it did not.

## 5. Sets

```
signal_manifest_hash     = set( "SIGNAL_MANIFEST:v2:",     content_hash of each SPINE-placed Signal )
exclusion_hash           = set( "EXCLUSION:v2:",           content_hash of each EPHEMERAL Segment )
structural_manifest_hash = set( "STRUCTURAL_MANIFEST:v1:", member hashes — §6 )
```

## 6. Structural manifest

Members are the hashes of the structural nodes that sit on the Episode, each under its own prefix (so the set needs no per-member type tag):

| Node | Member hash | Fields, in order |
|---|---|---|
| BranchPoint | `BRANCH_POINT:v2:` | UUID `branch_point_id`, UUID `episode_id`, UUID `branch_id`, UUID `source_segment_id`, STRING `branch_type`, STRING `declaration_type`, STRING `initiated_by`, TIMESTAMP `created_at`, HASH\|NULL `parent_hash` |
| ForkPoint | `FORK_POINT:v2:` | UUID `fork_point_id`, UUID `fork_id`, UUID `episode_id`, UUID `origin_episode_id`, UUID `origin_segment_id`, STRING `fork_objective`, STRING `initiator`, UINT `sibling_index`, TIMESTAMP `created_at`, HASH\|NULL `parent_hash` |
| DepartureForkPoint | `DEPARTURE_FORK_POINT:v2:` | UUID `fork_point_id`, UUID `fork_id`, UUID `fork_episode_id`, UUID `origin_episode_id`, UUID `origin_segment_id`, STRING `fork_objective`, STRING `fork_creation_trigger`, HASH `spine_tip_hash_at_departure`, STRING `initiator`, TIMESTAMP `created_at`, HASH\|NULL `parent_hash` |
| MergePoint | `MERGE_POINT:v2:` | UUID `merge_point_id`, UUID `merge_id`, UUID `source_episode_id`, UUID `target_episode_id`, HASH `source_merkle_root`, HASH `target_merkle_root_pre`, HASH `target_merkle_root_post`, UUID\|NULL `common_ancestor_id`, TIMESTAMP `created_at`, HASH\|NULL `parent_hash` |
| HITL event (terminal) | `HITL_NODE:v2:` | HASH `context_hash`, HASH `resolution_hash` — where `context_hash` = `HITL_CONTEXT:v2:` over STRING `hitl_request_id`, UUID `episode_id`, STRING `gate_type`, STRING `requesting_agent`, TIMESTAMP `invoked_at`, STRING `context_json`; and `resolution_hash` = `HITL_RESOLUTION:v2:` over UUID `hitl_event_id`, STRING `decision`, STRING `resolved_by`, TIMESTAMP `resolved_at`, STRING\|NULL `rationale` |

Field lists are those the 4.x constructions hash, in the same order; what changes is the encoding. `parent_hash` is NULL at the head of a chain (4.x used the text `GENESIS`). Removing any member changes `structural_manifest_hash` and therefore the Episode root. This is the anchoring path for human decisions: a resolved HITL event is not a spine leaf, and it is committed.

## 7. Episode root — and the prefix registry

```
episode_root_hash = SHA3-256( "EPISODE_ROOT:v2:" ‖ UUID(episode_id)
                              ‖ HASH(spine_root) ‖ HASH(signal_manifest_hash)
                              ‖ HASH(structural_manifest_hash) ‖ HASH(exclusion_hash) )
```

Prefixes introduced here, each used by exactly one construction, none a prefix of another, none shared with 4.x (`LEAF:`, `NODE:`, `SIGNAL_MANIFEST:v1:`, `EXCLUSION:v1:`): `LEAF_HASH:v2:` · `TREE_LEAF:v2:` · `TREE_NODE:v2:` · `SIGNAL_MANIFEST:v2:` · `EXCLUSION:v2:` · `STRUCTURAL_MANIFEST:v1:` · `EPISODE_ROOT:v2:` · `BRANCH_POINT:v2:` · `FORK_POINT:v2:` · `DEPARTURE_FORK_POINT:v2:` · `MERGE_POINT:v2:` · `HITL_CONTEXT:v2:` · `HITL_RESOLUTION:v2:` · `HITL_NODE:v2:`.

## 8. Vectors

Every value in the vector file is checked twice by the reference tests: against the library, and against a few lines of `hashlib` written from this text that import nothing from `astp`. Headline values (fixture: `episode_id` `550e8400-e29b-41d4-a716-446655440000`; seven Segments with fixed `node_id`s, `content_hash` = `SHA3-256("leaf-i")`):

```
leaf_hash (hash_version 2), segment 0        25b617f0d7ac09871f88ce7e2851cc8f50b48305dee51d081b62a5f21ed84935
spine_root (spine_algorithm_version 2), n=7  4420e38a22409317822ac14e3d5bc8069e6556c0fc08928290f76d23396daa01
episode_root_hash (v2), five structural members, five signals, empty exclusion
                                             e0be867164b3565846e05e2de90099de1d629acecf293ced04b11f88ec533a98
```

The file also fixes each field type's bytes, NFC equivalence, UTC normalization of a timestamp given at −08:00, spine roots for n = 1, 2, 3, 7, both manifests empty and populated, each structural member, the structural manifest with a member removed, and the Episode root with an empty structural manifest.

## 9. Open questions for ratification

1. **Leaf layout.** The ruling was "§5.2 minus `sealed_at`". This draft keeps those fields in that order but re-encodes them under §2 (type tags, a domain prefix, NULL for an absent parent) so that one encoding serves every construction. The alternative is the version 1 byte layout with eight bytes deleted. Which?
2. **One identifier or two.** As drafted, `spine_algorithm_version` 2 implies the whole 5.0.0 seal form — leaf, tree, sets and Episode root. That keeps "implied, not tagged" minimal, at the cost of a name that under-describes what it selects. The alternative is a separate `episode_root_version`.
3. **The retroactive spine write (§19.3.7).** Class B orphan recovery permits one retroactive write that recreates a missing divergence point on an origin Episode, which may already be sealed. With structural nodes committed into the sealed Episode root, a node created after the seal cannot be a member of that seal's manifest. Either such a node is committed by the origin's *next* crystallization delta (deltas chain, so this is expressible), or it is never committed and must say so. This needs a rule.
4. **Membership.** Should BranchTerminus and ForkReturn be members? Without the terminus, a closed branch can be made to look open by removing it. ForkOrphanMarker is a diagnostic satellite by design and is excluded.
5. **Omitted fields.** The 4.x member preimages leave out fields that look significant and immutable: `spine_merkle_snapshot` and `branch_label` on a BranchPoint; `merge_type`, `merge_summary` and `initiator` on a MergePoint. This draft does not add them. Should it?
6. **HITL membership.** "Terminal" is RESOLVED and TIMED_OUT in §2, and also ESCALATED in §4.6 and G-17. The manifest needs one list.
7. **Identifiers are UUIDs.** Every identifier field here is a UUID, as §4.1 requires. At least one Episode in the reference deployment has a non-UUID identifier and could not be sealed under this construction.
8. **What the seal path must now read.** A 4.x seal needs each Segment's `content_hash`. A 5.0.0 seal needs `node_id`, `node_type`, `schema_version`, `sequence_index`, `content_hash` and `parent_node_id` — or the stored `leaf_hash`, if it was computed under `hash_version` 2 at creation. Segments created before 5.0.0 carry version 1 leaf hashes; an Episode containing them is sealed under 5.0.0 by computing version 2 leaf hashes from their stored fields at seal time, which is permitted because the leaf hash is a function of immutable fields only. This should be stated.

## 10. Not in this unit

The remaining 5.0.0 items — the other §19 content hashes (terminus, fork return, aside, soliloquy, fingerprint), the audit record schema and preimage, witness commitment and witness validity (G-11/G-12), anchor commitment, `EpisodeLink.content_hash`, canonical JSON, the single hashing statement, role-named store values, the sealed-requires-a-record rule and the late-seal wording, and the inclusion-proof format over this tree — follow in further units, each with vectors.
