# ASTP 5.0.0 — Seal Constructions (Draft)

**Version:** 5.0.0-draft.5
**Status:** Draft for review — **not ratified, not normative.** Nothing here applies to any existing seal.
**Authors:** Scorched Earth Labs
**Date:** 2026-09-17
**Applies To:** proposed replacement text for `SPEC.md` §5.2–§5.8 and §9.2 in 5.0.0
**Vectors:** [`vectors/5.0.0-draft/seal-constructions.json`](../../vectors/5.0.0-draft/seal-constructions.json) (regenerate with `generate.py`, never by hand) · **Reference code:** `astp/protocol/encoding.py`, `compute_leaf_hash_v2`, `compute_merkle_root_v2`, `generate_inclusion_proof_v2` / `verify_inclusion_proof_v2`, `astp/core/seal_v2.py` · **Tests:** `tests/conformance/test_seal_constructions_v2_vectors.py`

This is one unit of the 5.0.0 amendment: how an Episode's roots are built. Draft 3 incorporates the rulings of design Episode `4b9a779e-be46-4d61-872e-fd76545aa901`, segments 29 and 31 (§9). It is a MAJOR change under [`VERSIONING.md`](../../VERSIONING.md) and requires an Episode of Record. Every construction below is **new and versioned**. Seals made under `spine_algorithm_version` 0 and 1 remain defined by SPEC 4.5.0 §5.3–§5.8 and remain reproducible; 5.0.0 retains that text as the definition of those versions.

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

**Segments created before 5.0.0.** A leaf hash is a function of a node's immutable fields, so an Episode containing Segments that predate 5.0.0 is sealed under 5.0.0 by computing their `hash_version` 2 leaf hashes **from their stored fields** at seal time. It MUST NOT be computed from a stored version 1 leaf hash: re-hashing a hash reproduces nothing. The vector file pins one such computation.

`node_id` MUST be generated with at least 122 bits of randomness (UUIDv4 or equivalent) and MUST NOT be derived from the node's content or any other guessable input. This requirement is new in 5.0.0 and takes effect when 5.0.0 is ratified; no earlier version states it. From then on it reaches back through a seal that includes older Segments: if their `node_id`s do not meet it, the Episode's leaf hashes are not safe to publish. `content_hash` is an unsalted hash of content; it is the unguessable `node_id` in this preimage that makes a published leaf hash useless for testing a guess at a Segment's content.

## 4. Merkle tree and spine — `spine_algorithm_version` 2

The tree is the one §5.4 has always described: inputs in the order given; pair from the left; an unpaired node is **carried up unchanged**, neither duplicated nor re-hashed; a single input's level-0 hash is the root; **the root of an empty list is undefined and MUST be refused.**

```
level 0:   SHA3-256( "TREE_LEAF:v2:" ‖ input )            input: 32 raw bytes
interior:  SHA3-256( "TREE_NODE:v2:" ‖ left ‖ right )      left, right: 32 raw bytes
```

The spine of an Episode is this tree over the `hash_version` 2 leaf hashes of its non-ephemeral Segments in `sequence_index` order (`ordering_version` 2, unchanged). There is no other leaf.

**`spine_algorithm_version` 2 selects the entire seal construction** — leaf hash, tree, sets and Episode root (§3–§7) — not the tree alone. There is deliberately no separate identifier for the Episode root: a second identifier would make an invalid combination representable, and one identifier makes it unrepresentable. Read the name as *seal construction version*.

A verifier MUST derive the encoding from the identifier: hex text under `spine_algorithm_version` 0 and 1, raw bytes under 2 — never assume it. The three versions are one tree; they differ in leaf input, in encoding, and in whether the Episode-identifier leaf is present.

The spine and the tree of §9 (five-test gate) and §16.5 (inclusion proofs) are now **the same tree over the same inputs**. A position-binding inclusion proof therefore proves position in the sealed spine, which under 4.x it did not.

## 4a. Inclusion proof over the version 2 tree (replaces §9.2)

The spine and the proof tree are now one tree, so a position-binding inclusion proof proves position *in the sealed spine* — which under 4.x it did not.

```
InclusionProof {
  leaf_index    UINT     position of the leaf in the spine's leaf list
  leaf_count    UINT     number of leaves in that list
  leaf_hash     HASH     the hash_version 2 leaf hash being proven
  siblings      HASH[]   the sibling at each level where one exists, leaf level first
  spine_root    HASH     the root being proven against
}
```

**The prover does not state the path's shape.** From `leaf_index` and `leaf_count` a verifier derives, level by level, whether the node has a sibling (it has none exactly when it is the unpaired last node of its level, which is carried up unchanged) and on which side that sibling sits (a node at an even position is the left child). The verifier then: rejects the proof if `leaf_index` is out of range or the number of siblings is not the number the shape requires; hashes the leaf under `TREE_LEAF:v2:`; and at each level with a sibling computes `TREE_NODE:v2:` over left ‖ right in the derived order. The proof is valid if and only if the result equals `spine_root`.

**What a proof commits to.** The leaf, and its position: a sibling list verifies at no position other than the one the tree gave it, and no sibling can be altered. It does not commit to the tree's size — a `leaf_count` that yields the same path shape verifies too — so the number of leaves in a sealed spine is a claim of the seal record, not of any proof. A proof carries no content and no identifiers; it is safe to publish wherever the leaf hash it proves is.

It does not commit to the size for a reason: the seal record already makes that claim, reproducibly, and two mechanisms binding one fact can disagree — a verifier would then have to decide which is authoritative. Binding the count into the leaf hash would also make every leaf hash depend on the tree's eventual size, so no leaf hash could be final when its Segment was written; incremental append is a property of the spine, not a convenience. Each mechanism makes exactly one claim: the proof, that this leaf sits at this position under this root; the seal record, how many leaves there are.

**Two proof forms, selected by `spine_algorithm_version`.** A proof over a version 0 or 1 tree is the 4.x form of §9.2 — hex-ASCII values, `LEAF:` and `NODE:`, the Episode-identifier leaf, and explicit `path_directions` — frozen, and never re-issued in this form. The two are different formats because they make different claims: a version 2 proof proves position in the sealed spine, while a 4.x proof proves position in a proof tree that was a separate structure from the spine the seal recorded. Re-issuing a 4.x proof in the version 2 form would claim a guarantee the 4.x seal never made. The version identifier therefore selects which claim a proof makes, not merely how it is encoded; and a verifier of a 4.x proof MUST use its stated directions rather than derive them, because the derivation rule is earned by the version 2 tree's discipline and was never stated for the 4.x tree.

`leaf_index` is not `sequence_index`: ephemeral Segments have a `sequence_index` but are not leaves. The leaf hash binds `sequence_index`; the path binds `leaf_index`; a verifier holding the Segment checks both.

Vectors (over the seven leaves of §8): leaf 3 of 7 carries 3 siblings; leaf 6 of 7 carries 2 (unpaired at the leaf level, then paired twice); the single leaf of a one-leaf tree carries none.

```
leaf 3 of 7, sibling 0    8c5558dd9cf6dbbfb7d5c64757d4c2640fabc5b1105404a77c6fd5120fce9889
leaf 6 of 7, sibling 0    62bb7692435aef7234c85f8dec29fb8b13b140211713889b899c14eead95fbf1
```

## 5. Sets

```
signal_manifest_hash     = set( "SIGNAL_MANIFEST:v2:",     content_hash of each SPINE-placed Signal )
exclusion_hash           = set( "EXCLUSION:v2:",           content_hash of each EPHEMERAL Segment )
structural_manifest_hash = set( "STRUCTURAL_MANIFEST:v1:", member hashes — §6 )
```

## 6. Structural manifest

**Membership rule.** A structural node is a member if and only if removing it would let a verifier be deceived about the Episode's branch, fork, merge or termination structure. The same rule decides fields: a field that makes a structural claim is in a member's preimage; commentary is not. `spine_merkle_snapshot` binds a divergence to the history it left from, and `merge_type` says how two histories combined — both are in. A `branch_label`, a `merge_summary` or a `synthesis_summary` is commentary: binding it would make an honest edit break a seal while proving nothing. Who initiated a branch, fork or merge, and who returned a fork, is provenance: binding actor identity is the audit chain's job, and the manifest binding it for some nodes and not others, as 4.x did, has no principled defence. All of these are out. The *nodes* remain members; it is only these fields that a member's preimage no longer carries. 4.x seals that bound them remain reproducible under 4.x. A `ForkOrphanMarker` is a diagnostic satellite and is not a member.

Members, each under its own prefix (so the set needs no per-member type tag):

| Node | Member hash | Fields, in order |
|---|---|---|
| BranchPoint | `BRANCH_POINT:v2:` | UUID `branch_point_id`, UUID `episode_id`, UUID `branch_id`, UUID `source_segment_id`, HASH `spine_merkle_snapshot`, STRING `branch_type`, STRING `declaration_type`, TIMESTAMP `created_at`, HASH\|NULL `parent_hash` |
| BranchTerminus | `BRANCH_TERMINUS:v2:` | UUID `terminus_id`, UUID `branch_id`, STRING `terminus_type`, HASH `branch_point_hash`, HASH\|NULL `final_merkle_root`, TIMESTAMP `created_at` |
| ForkPoint | `FORK_POINT:v2:` | UUID `fork_point_id`, UUID `fork_id`, UUID `episode_id`, UUID `origin_episode_id`, UUID `origin_segment_id`, STRING `fork_objective`, UINT `sibling_index`, TIMESTAMP `created_at`, HASH\|NULL `parent_hash` |
| DepartureForkPoint | `DEPARTURE_FORK_POINT:v2:` | UUID `fork_point_id`, UUID `fork_id`, UUID `fork_episode_id`, UUID `origin_episode_id`, UUID `origin_segment_id`, STRING `fork_objective`, STRING `fork_creation_trigger`, HASH `spine_tip_hash_at_departure`, TIMESTAMP `created_at`, HASH\|NULL `parent_hash` |
| ForkReturn | `FORK_RETURN:v2:` | UUID `fork_return_id`, UUID `fork_id`, UUID `fork_episode_id`, UUID `origin_episode_id`, STRING `return_type`, HASH `fork_final_spine_tip_hash`, TIMESTAMP `created_at`, HASH\|NULL `parent_hash` |
| MergePoint | `MERGE_POINT:v2:` | UUID `merge_point_id`, UUID `merge_id`, UUID `source_episode_id`, UUID `target_episode_id`, HASH `source_merkle_root`, HASH `target_merkle_root_pre`, HASH `target_merkle_root_post`, UUID\|NULL `common_ancestor_id`, STRING `merge_type`, TIMESTAMP `created_at`, HASH\|NULL `parent_hash` |
| HITL event in a terminal state — `RESOLVED`, `TIMED_OUT` or `ESCALATED` | `HITL_NODE:v2:` | HASH `context_hash`, HASH `resolution_hash` — where `context_hash` = `HITL_CONTEXT:v2:` over STRING `hitl_request_id`, UUID `episode_id`, STRING `gate_type`, STRING `requesting_agent`, TIMESTAMP `invoked_at`, STRING `context_json`; and `resolution_hash` = `HITL_RESOLUTION:v2:` over UUID `hitl_event_id`, STRING `decision`, STRING `resolved_by`, TIMESTAMP `resolved_at`, STRING\|NULL `rationale` |

Relative to the 4.x constructions the lists add `spine_merkle_snapshot` and `merge_type` and drop `initiated_by`, `initiator`, `returned_by` and `synthesis_summary`; the remaining fields keep their 4.x order. `parent_hash` is NULL at the head of a chain (4.x used the text `GENESIS`). A HITL event still `INVOKED` is not a member. `ESCALATED` is terminal: escalation concludes *this* gate — its resolution is the escalation decision — and any further deliberation happens at a distinct gate raised with the higher authority. `ESCALATED` and `RESOLVED` MUST remain distinguishable: whether a human decided here or passed the decision up is a fact about how the gate concluded. Removing any member changes `structural_manifest_hash` and therefore the Episode root. This is the anchoring path for human decisions: a concluded HITL event is not a spine leaf, and it is committed.

**A structural node created after a seal.** A sealed Episode root is immutable, so a node created after a seal is never a member of that seal's manifest. It is committed by the Episode's **next** crystallization — deltas chain — and it MUST carry a reference to the earlier seal it structurally relates to. It is a member of the later root that *references* the earlier one; it is not a member of the earlier one, and the two MUST NOT be conflated. A structural node that is never committed into any root is not permitted: it would assert structure while bound to nothing. This governs the one retroactive write of §19.3.7 (Class B orphan recovery), which must cross-reference this rule.

## 7. Episode root — and the prefix registry

```
episode_root_hash = SHA3-256( "EPISODE_ROOT:v2:" ‖ UUID(episode_id)
                              ‖ HASH(spine_root) ‖ HASH(signal_manifest_hash)
                              ‖ HASH(structural_manifest_hash) ‖ HASH(exclusion_hash) )
```

`episode_id` is a UUID, as §4.1 requires; the root does not admit a string identifier, because identity bound by string equality is only as strong as the strings' encoding. An Episode whose identifier is not a UUID cannot be sealed under this construction and must say so; it is brought into conformance by being given one, with the old identifier kept as provenance and bound to nothing.

Prefixes introduced here, each used by exactly one construction, none a prefix of another, none shared with 4.x (`LEAF:`, `NODE:`, `SIGNAL_MANIFEST:v1:`, `EXCLUSION:v1:`): `LEAF_HASH:v2:` · `TREE_LEAF:v2:` · `TREE_NODE:v2:` · `SIGNAL_MANIFEST:v2:` · `EXCLUSION:v2:` · `STRUCTURAL_MANIFEST:v1:` · `EPISODE_ROOT:v2:` · `BRANCH_POINT:v2:` · `BRANCH_TERMINUS:v2:` · `FORK_POINT:v2:` · `DEPARTURE_FORK_POINT:v2:` · `FORK_RETURN:v2:` · `MERGE_POINT:v2:` · `HITL_CONTEXT:v2:` · `HITL_RESOLUTION:v2:` · `HITL_NODE:v2:`.

## 8. Vectors

Every value in the vector file is checked twice by the reference tests: against the library, and against a few lines of `hashlib` written from this text that import nothing from `astp`. Headline values (fixture: `episode_id` `550e8400-e29b-41d4-a716-446655440000`; seven Segments with fixed `node_id`s, `content_hash` = `SHA3-256("leaf-i")`):

```
leaf_hash (hash_version 2), segment 0        25b617f0d7ac09871f88ce7e2851cc8f50b48305dee51d081b62a5f21ed84935
spine_root (spine_algorithm_version 2), n=7  4420e38a22409317822ac14e3d5bc8069e6556c0fc08928290f76d23396daa01
structural_manifest_hash, seven members      0a4b777227b87ee0d6c8efd5b2e9a5fc05c02e61d677f2460f868ab06779b537
episode_root_hash (v2), seven structural members, five signals, empty exclusion
                                             f0511b4d1be172554b9f87ec64d400d24a1409f1742ad72f628bf5ab7b7d33f0
```

The file also fixes each field type's bytes, NFC equivalence, UTC normalization of a timestamp given at −08:00, spine roots for n = 1, 2, 3, 7, both manifests empty and populated, each structural member, the structural manifest with a BranchTerminus removed, the Episode root with an empty structural manifest, a pre-5.0.0 Segment's leaf hash computed from its fields, and three inclusion proofs with their sibling counts.

## 9. Rulings incorporated, and what remains open

Ruled in design Episode `4b9a779e…`, segments 29 and 31, and reflected above: the leaf is re-encoded under §2 rather than being the version 1 layout with bytes deleted (sixteen zero bytes is a valid UUID, so version 1 cannot tell "no parent" from "parent is the nil UUID"); one identifier selects the whole construction; the membership rule, applied uniformly to nodes and to fields — BranchTerminus and ForkReturn in, ForkOrphanMarker out, `spine_merkle_snapshot` and `merge_type` in, labels, summaries and actor provenance out; HITL terminal states are RESOLVED, TIMED_OUT and ESCALATED, with ESCALATED terminal for the gate at which it occurs; pre-5.0.0 Segments are sealed from their fields; a structural node created after a seal is committed by the next crystallization and references the earlier seal; the Episode root binds a UUID and admits no string identifier.

Consequences outside this text:

1. **Reference implementation.** Its HITL status enum describes `ESCALATED` as awaiting resolution, and its resolution writer records every decision other than a timeout as `resolved`, so an escalation does not survive as a status. Both are defects against §4.6 and G-17 and are to be fixed with the adapter work; an escalated event cannot be a manifest member until they are.
2. **The write boundary.** An Episode identifier that is not a UUID MUST be refused where Episodes are created, not merely be unrepresentable in the root. The reference deployment holds one Episode created with a string identifier; 286 immutable Layer 3 nodes carry that string inside their content hashes, so it cannot be renamed. It is a well-formed `spine_algorithm_version` 1 Episode — version 1 hashes the identifier as text — and is to be closed and sealed under version 1 before the deployment adopts version 2.
3. **What the seal path must now read** — six fields per Segment rather than one — is an implementation note for the consuming runtime, to be written with the adapter work.

## 10. Not in this unit

The remaining 5.0.0 items — the other §19 content hashes (aside, soliloquy, fingerprint), the audit record schema and preimage, witness commitment and witness validity (G-11/G-12), anchor commitment, `EpisodeLink.content_hash`, canonical JSON, the single hashing statement, role-named store values, and the sealed-requires-a-record rule with the late-seal wording — follow in further units, each with vectors.
