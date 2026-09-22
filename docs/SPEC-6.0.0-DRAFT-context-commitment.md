# ASTP 6.0.0 — Context Commitment (Draft)

**Version:** 6.0.0-draft.2
**Status:** Draft for review — **not ratified, not normative.** Nothing here applies to any existing seal. A MAJOR change under [`VERSIONING.md`](../VERSIONING.md): it needs an Episode of Record before it is folded into `SPEC.md`.
**Authors:** Scorched Earth Labs — rulings by Clotho with Devin, structure by Daedalus, in design Episode `ec31d0c0-50eb-4a2a-9f95-32536c9e645e` ("Attachments, RAG, External Websites and Privacy/RTD", 2026-09-22); the erasure question descends from Episode `531a045b-a945-4aa2-8648-edf618067a11` ("Ariadne and Data Privacy, Right to Delete", 2026-03-30).
**Date:** 2026-09-22
**Applies To:** proposed text for `SPEC.md` 5.2.0 — §2, §4.7, new §4.8–§4.9, §5.1.3, §5.7, new §5.7.3, §5.8, §9.2, §9.3, §11, §12.4.1, §21 (relation only), and new G-41 … G-43.
**Written against:** `SPEC.md` **5.2.0** (main at `e8cca7b`). The design Episode's retrieved spec text was the pre-5.0.0 line (commit `3346838`, 2026-09-17); §1 lists every point where that matters.

---

## 0. What this amendment does

A sealed Episode cannot today prove what external information an agent was given. An `AttachmentNode` (§4.7) is content-hashed and ledgered but is a member of no Episode-root component; retrieved knowledge exists only in the best-effort §11.1 audit, outside every hash; content fetched from the web or an external API has no defined treatment. "This is what the agent was given" is a claim (§5.0.0's principle: every claim needs a commitment) without one.

The amendment adds one thing and states one thing.

**It adds a context manifest**: a sixth field of the Episode root, committing every external input an agent was given during the Episode — attachments, retrieved knowledge, external content, tool output — as typed entries, each a stored node with its own hash construction, with inclusion proofs over the manifest so one entry can be proven without disclosing the others.

**It states that the seal proves history, not retention.** The seal commits to hashes and pointers, never to content. That is what lets presence be bound into the root (the manifest) and content be lawfully erased from it (right-to-delete) without contradiction: erasure destroys content behind a pointer and appends a witnessed tombstone; no sealed preimage moves. Where the content is low-entropy personal data, its commitment MUST be non-reversible (salted), so that erasing the content also destroys the means of confirming a guess at it.

**They are safe only together.** Committing context without the non-reversible construction produces a permanent, guessable commitment to a borrower's account number or a patient's date of birth — deletion that is not deletion. A conforming 6.0.0 implementation implements both halves (§13, CM-09).

> **The governing invariant: the seal proves history, not retention.**

---

## 1. Re-basing notes — what the design Episode saw, and what changed

The Episode's spec retrieval served the pre-5.0.0 text: a three-component Episode root under `NODE:`, `SIGNAL_MANIFEST:v1:` joined by `|`, `hash_version 1 (default)`, `spine_algorithm_version 0 · 1`. Every ruling below is preserved in substance; where 5.0.0–5.2.0 already changed the ground the ruling stood on, the draft says so here and marks the item **REQUIRES RE-RULING** where the Episode's decision and the ratified text conflict. Clotho's corpus has since been re-indexed at main, and the one conflicting item (R1) was re-ruled in the same Episode at segment 57 (draft.2). R4 still awaits confirmation.

| # | Episode ruling | 5.2.0 ground | Disposition |
|---|---|---|---|
| R1 | A **standalone third §5.8 axis**, `root_composition_version` (1 = three-component root, 2 = four-component), because "neither existing axis governs root composition" (segments 26–28). | 5.0.0 §5.8 rules the opposite: *"`spine_algorithm_version` 2 selects the entire seal construction … There is deliberately no separate identifier for the Episode root: a second identifier would make an invalid combination representable, and one identifier makes it unrepresentable. Read the name as seal construction version."* The Episode's premise — that a spine-only identifier would misdescribe a root-only change — was true of the 4.x text and is not true of 5.0.0's. | **RE-RULED (Episode `ec31d0c0`, segment 57, 2026-09-22): the standalone axis is rescinded in full, and the context manifest is carried by `spine_algorithm_version` 3 as the sixth root field under `EPISODE_ROOT:v3:`.** Clotho, re-reading ratified §5.7/§5.8: a standalone `root_composition_version` "is precisely the second identifier §5.8 forbids"; version 3 gives the hard version gate, the unrepresentable invalid combination and no retroactive re-seal, so the change is a re-basing, not a re-design. §7 is as written; nothing else in the draft moves. |
| R2 | The context manifest is the **fourth** root component beside spine, signal manifest and exclusion set. | Since 5.0.0 the root already has four components: the **structural manifest** (§5.7.1) is the fourth. | Carried as the **fifth component / sixth field** of `EPISODE_ROOT:v3:` (§7). No ruling changes. |
| R3 | Preimages written as `SHA3-256(b"ASTP_MANIFEST_ENTRY_V1:" + type.to_bytes(1) + id.bytes + …)` and `"ASTP_ATTACHMENT_V1:" + bytes`. | 5.0.0 §5.1.1 fixes one canonical field encoding for every construction and §5.1.3 one registered prefix per construction and version, of the form `NAME:vN:`. | Rewritten in 5.0.0 form (§5, §6). Same fields, same claims; different byte form. Not a re-ruling. |
| R4 | Attachments: Devin chose the standalone axis *"for now; we'll tackle the attachments when we get to it"* (seg. 27), which the Episode records as a live fork; the final artifact (seg. 51) then includes `AttachmentNode` as a manifest entry (its §4) as if the fork were closed. | — | **CONFIRM.** This draft includes attachments as an entry type (§4.8). It is the natural reading of the artifact and of Finding 1 as summarised at seg. 49; the Episode never recorded the closing of the fork it opened. |
| R5 | Manifest is an **order-free set**, "constructed like §5.7's signal manifest" (seg. 22, 26, 28) — and the artifact's manifest is an **ordered** list of Merkle leaves with `manifest_root = MerkleRoot(entries)`, and the brief asks for single-entry inclusion proofs. | Set semantics and inclusion proofs are both wanted. | Reconciled (§6.2): the manifest is a Merkle tree (§5.4, the version 2 tree) over entry hashes in **canonical order — ascending bytewise**. Sorting makes the tree a function of the set (membership binds, insertion order does not) and gives §9.2-style inclusion proofs. Not a re-ruling; a construction that satisfies both rulings. |
| R6 | Artifact §3: the leaf commits `salt_ref`'s presence "so a retroactively added or stripped salt is detectable"; artifact §6.2 step 4: on erasure, "null `content_ref` **and `salt_ref`**". | — | **Internal contradiction in the artifact**: nulling `salt_ref` would change a leaf that commits its presence, which changes the root, which is the re-seal Finding 4 forbids. Resolved (§5.3): the entry commits **which construction** hashed the content (`salted`, a BOOL), never the pointer to the salt. The pointer is side-channel, nulled on erasure; the bit is permanent. The property the ruling wanted — a retroactively added or stripped salt is detectable — holds, because a plain-hashed entry cannot later claim to have been salted or vice versa. |
| R7 | The Episode ruled: a sealed **`context_capture_posture`** in the manifest preimage (seg. 35–37); per-entry **verifiability state** VERIFIABLE / ATTESTED / DECLARED-INCOMPLETE (seg. 10, 15, 17); **repair is append-only** — a later entry `resolves` a declared-incomplete one, states never mutate (seg. 17, 22); each entry binds the **spine position** it preceded (seg. 15, 22). The artifact (seg. 51) carries none of these; it has `reproducibility` and `erasure_state` only. | — | **Restored** (§5.2, §5.4, §6.1, §6.3). The artifact was built from Daedalus's structure and the later rulings did not survive the hand-off; the Episode's own summaries (seg. 37, 49) list them as locked. The artifact's `reproducibility` enum is subsumed: `NOT_REPRODUCIBLE` is the `external` entry type with `attested`-or-`verifiable` at seal (§5.4). |
| R8 | Layer 3: an external tool result is **committed once**, as a `SkillInvocation`; the manifest entry **references** it and "does not re-hash the result" (seg. 10, finding 5). The brief's common field: `content_hash` is over "the exact bytes provided to the agent (after chunking/extraction/formatting — what entered context)". | The two are not the same bytes: `output_result` is JSON on the invocation; what entered context is whatever the implementation rendered from it. | Refined (§4.8 `tool_output`): the entry hashes **what entered context** (the brief's rule, which every other entry type follows) and binds the invocation by its **`content_hash`** in `source_version_hash`. One invocation record; one context entry; an explicit, hash-bound reference between them. No result is committed twice under the same claim. |
| R9 | The "Known limitation (context commitment)" wording is the time-sensitive item (seg. 10). | 5.1.x errata (PR #58) already added *"What the seal covers"* to §4.7, stating substitution is detectable and addition or omission after the seal is not, and that binding attachments into the root is a MAJOR change not made in that version. | The retraction target is that paragraph (§4). The Episode's proposed wording is folded into it as the retired statement. |
| R10 | Finding 6 (what the proposal gets wrong about the immutability–erasure Episode) was **deferred and never closed** (seg. 10 "Open items"). | Episode `531a045b` converged on a two-layer approach: an engineering gate (Metis's inference-residue threshold) plus a formal legal-opinion layer (Themis), with three mitigation paths — data minimisation at ingestion, a **pointer/reference off-chain architecture**, jurisdictional scoping — and Odysseus's closing read that the pointer/reference path is *"the most implementable … it doesn't require retrofitting the append-only chain itself — you're externalizing the sensitive payload and leaving a reference node that can be nullified without corrupting chain integrity."* | Consistent, not contradicted: this amendment **is** the pointer/reference path, made protocol surface (§8). Persistence-coefficient tagging and residue quantification are operational-layer instruments that sit above `pii_classification` (§8.1) and are out of this amendment's scope; §14 says so. |
| R11 | Decision A (seg. 10) recommended **per-entry keyed HMAC via HKDF** for sensitive entries; Finding 4 (seg. 47, 51) settled on a **per-entry CSPRNG salt stored in a separate namespace, destroyed with the content**. | Both are non-reversible commitments with a per-entry secret. | The salt form is adopted (§5.3): no key hierarchy dependency, no verifier key-disclosure protocol, one secret per entry with the same blast radius. Recorded so the HMAC path is not re-proposed as new. |

Everything not in this table is carried from the Episode unchanged.

---

## 2. Terminology (additions to §2)

| Term | Definition |
|---|---|
| **Context entry** | A stored node (`ContextEntryNode`, §4.8) recording that external content was provided to an agent's context during the Episode, or that a provision was attempted and its content not captured. |
| **Context manifest** | The Episode-root component committing the Episode's context entries: a Merkle tree over their entry hashes in canonical order, bound with the capture posture (§6). |
| **Provided** | Content is *provided* when it enters the context window of an agent whose reasoning is recorded as Segments in this Episode. What a retriever or fetcher returned but did not place before such an agent is not provided; it stays in the §11.1 audit. The claim of a context entry is "what the agent was given," never "what it relied on." |
| **Capture posture** | The Episode's sealed declaration of what it undertook to capture: `all_external`, `declared_only` or `none` (§6.1). It bounds what the absence of an entry may be read to mean. |
| **Verifiability at seal** | Of a captured entry: `verifiable` — a retained copy of the provided bytes existed at seal and re-hashes to `content_hash`; `attested` — the commitment exists but no retained copy did. Fixed at seal; a later erasure is recorded by tombstone, not by changing it. |
| **Declared incomplete** | A context entry whose provision was attempted and whose content was not captured. A positive member of the manifest: a gap that cannot be stripped. |
| **Erasure tombstone** | The §12.4.1 codicil that witnesses the erasure of a context entry's content (§4.9). |
| **Content plane / integrity plane** | Content lives behind `content_ref` and `salt_ref` (content plane). Hashes, entries, manifests and roots (integrity plane) never bind content, only its commitment. Right-to-delete acts on the content plane alone. |

---

## 3. What changes, and why

| 5.2.0, as ratified | 6.0.0 | Reason |
|---|---|---|
| `AttachmentNode` is in no root component; §4.7 says so ("What the seal covers"). | Every attachment provided to an agent is a context entry, a member of the context manifest, committed by the Episode root. | Addition or omission of an attachment after the seal becomes detectable. |
| Retrieved knowledge is recorded only by the §11.1 audit: best-effort, outside every hash, records the *act* of reading. | A retrieval that entered context is a context entry recording the *thing* read; §11.1 is unchanged and still records the act. | "What did it know" needs the thing, committed; the audit stays what it is. |
| External web / API content has no treatment. | An `external` entry: the bytes as received, hashed; the URI is provenance outside the preimage; verifiability at seal states whether a retained copy existed. | The seal vouches for the bytes, never for the source's willingness to serve them again. |
| A capture failure leaves a silent hole. | A `declared_incomplete` entry is a committed member; the Episode's capture posture is sealed. | A gap that is itself committed cannot be stripped; a sparse manifest is readable against a stated posture. |
| Erasing content behind a sealed hash leaves a working oracle for low-entropy content (§5.6 already admits it). | Low-entropy personal data commits through a salted construction; erasure destroys content and salt together and appends a witnessed tombstone; no sealed preimage moves. | Deletion is real, the seal survives, and the erasure is on the record. |
| Episode root version 2: five fields. | Episode root **version 3**: six fields, adding `context_manifest_hash`. Selected by `spine_algorithm_version` 3. | One identifier selects the whole seal construction (§5.8). |

---

## 4. §4.7 AttachmentNode — amended

The paragraph **"What the seal covers"** (5.1.x) is retired and replaced:

> **What the seal covers.** Under `spine_algorithm_version` 3 an attachment that was provided to an agent is a context entry (§4.8) and a member of the context manifest (§5.7.3): its presence is committed by the Episode root, and adding or removing one after the seal changes that root. Under versions 0–2 an AttachmentNode is a member of no root component: `content_hash` detects substitution of the bytes, and nothing detects addition or omission after the seal — retained as the property of those constructions. An `AttachmentNode` that was attached but never provided to an agent is still not a manifest member: the manifest commits what agents were given, not what the Episode holds.

`AttachmentNode` itself is unchanged. The context entry references it by `attachment_id` (provenance, outside the entry preimage) and carries its own commitment to the bytes as provided.

---

## 5. §4.8 ContextEntryNode (new)

A stored node recording one provision of external content to one agent — or one attempted provision whose content was not captured. Kind is a property, not a node type (§4.7's rule, one level up): one node type, `entry_type` discriminates.

```
ContextEntryNode {
  entry_id:                        UUID
  episode_id:                      UUID
  entry_type:                      "attachment" | "retrieval" | "external" | "tool_output"
  provided_to:                     string        (agent_id whose context received it)
  provided_at:                     datetime
  provided_before_sequence_index:  int?          (§5.2 — the spine position the provision preceded)
  capture_state:                   "captured" | "declared_incomplete"
  content_hash:                    HASH?         (§5.3; NULL when declared_incomplete)
  salted:                          bool          (which construction produced content_hash; false when declared_incomplete)
  verifiability_at_seal:           "verifiable" | "attested" | null   (null when declared_incomplete)
  media_type:                      string?       (IANA media type of the bytes as provided)
  source_version_hash:             HASH?         (§5.4)
  resolves:                        UUID?         (entry_id of the declared_incomplete entry this entry fills — §5.5)
  schema_version:                  string

  // provenance and content plane — outside the preimage; see §5.6
  source_ref:                      string?
  content_ref:                     string?
  salt_ref:                        string?
  erasure_state:                   "present" | "tombstoned"
}
```

### 5.1 Entry types

| `entry_type` | What was provided | `source_ref` (provenance) | `source_version_hash` |
|---|---|---|---|
| `attachment` | An `AttachmentNode`'s content, as provided | `attachment_id` | NULL |
| `retrieval` | Content from a knowledge source the implementation controls — a Segment of another Episode, a document store, an index | the source's identifier (a `node_id`, a document key) | a hash identifying the **version** of the source that was read (its `content_hash`, its Episode root, a snapshot digest) — so "the September 1 guidance, not the September 10 bulletin" is a claim of the entry |
| `external` | Content from a source the implementation does not control — a web page, a third-party API | the URI or endpoint, and the fetch metadata the implementation keeps (status, ETag, Last-Modified) | NULL (an external pointer cannot be re-resolved to a version) |
| `tool_output` | The rendering of a Layer 3 `SkillInvocation`'s `output_result` that entered context (§21) | the `SkillInvocation.node_id` | the `SkillInvocation.content_hash` — binding the invocation record, which committed the result once, at Layer 3 |

A `SkillInvocation` is committed when its result was produced *by* the agent's action; a context entry is committed when content was provided *to* the agent's context. A pricing-engine call is both — one invocation, one entry, an explicit hash-bound reference between them. A static attachment is only the latter. Nothing is committed twice under the same claim.

### 5.2 The spine-position binding

`provided_before_sequence_index` is the `sequence_index` of the first non-ephemeral Segment authored by `provided_to` after `provided_at`, or NULL if none had been written when the Episode sealed. It is what makes an entry mean *then*: an agent traversing the Episode later — or a verifier reconstructing what the agent knew when it wrote Segment *n* — reads the entries whose bound position is ≤ *n*. It is a claim of the entry and is in its preimage. It is not an ordering key of the manifest (§6.2), exactly as a Segment's `sequence_index` is in its leaf preimage and not re-derived from any set.

### 5.3 The content commitment — two constructions, one bit

`content_hash` is over the bytes **as provided** — what entered context after any chunking, extraction or formatting — never over the source artifact (§4.7's rule applies to the provided form: an extraction is hashed as what it is, the thing the agent was given).

```
plain    content_hash = SHA3-256( "CONTEXT_CONTENT:v1:"        ‖ BYTES(content) )
salted   content_hash = SHA3-256( "CONTEXT_CONTENT_SALTED:v1:" ‖ BYTES(salt) ‖ BYTES(content) )
                        salt: 32 bytes from a CSPRNG at write time, stored at salt_ref,
                        in a namespace separate from the content's
```

`salted` records which construction was used and is in the entry preimage. The **pointer** to the salt is not (§5.6): erasure destroys the salt and nulls the pointer, and the entry's preimage does not move. A plain-hashed entry cannot later present itself as salted, nor a salted one as plain — the bit is sealed.

**When salting is required — G-42.** Content that is personal data and low-entropy — a value whose space of possibilities is small enough that a commitment to it confirms a guess: an identifier, a date of birth, an account number, a short structured field — MUST commit through the salted construction. A plain commitment to such content is a disclosure that survives its own deletion. High-entropy content (a document, a transcript, an image) MAY commit plain; the implementation classifies at write time (§8.1) and the classification's quality is the implementation's residual risk (§14).

### 5.4 Verifiability at seal

A captured entry is `verifiable` at seal if a copy of the provided bytes was retained (at `content_ref`) and re-hashes to `content_hash` (with the salt, for a salted entry); `attested` if the commitment was made and no retained copy existed at seal. Retention is RECOMMENDED, not required: an implementation may be obliged not to retain (copyright; personal data in a fetched page). What is required is the declaration — an implementation MUST NOT report an `attested` entry as verified.

The field is fixed at seal. A retained copy later erased under §8 does not change it; the tombstone records the erasure, and a verifier reading `verifiable` with a `tombstoned` erasure state knows exactly what happened and when.

For an `external` entry the `source_ref` URI is provenance the seal deliberately does not vouch for: a verifier MUST NOT re-fetch it and treat a difference as an integrity failure. The entry proves *these bytes entered this agent's context at this time, tagged with this provenance*; it proves nothing about what the source serves now.

### 5.5 Declared-incomplete entries and append-only repair

An implementation that attempted a provision and could not capture its content writes the entry with `capture_state = declared_incomplete`, `content_hash = NULL`, and whatever provenance it holds (the query, the result count, the source). It is a positive member of the manifest: the gap is committed with the same tamper-evidence as content, and a silent hole is impossible by construction.

An Episode can seal over any number of declared-incomplete entries; it is not claiming a completeness it lacks. **It cannot seal over an undeclared one**: an entry whose write did not complete blocks the seal until the write completes — as `captured` if the content is still in hand, as `declared_incomplete` if not (G-41). Completing an incomplete write is not rewriting history.

A declared-incomplete entry is never mutated. If its content is recovered later, a **new** entry is written at the current position with `resolves = <the incomplete entry's entry_id>`; the incomplete entry stays exactly as sealed — permanently true that at seal time the content was not held. Resolution is a relationship between two entries, discoverable by following `resolves`, never a state change on the old one. The resolving entry's preimage binds the resolved entry's hash (§6.1), so the relationship is itself committed.

### 5.6 Side-channel fields

`source_ref`, `content_ref`, `salt_ref` and `erasure_state` are outside the entry preimage and outside every root, on the footing of §11's access counters. `content_ref` and `salt_ref` are nulled by erasure (§8); `erasure_state` records it; `source_ref` is provenance. None of them can be used to alter a sealed claim, and none is needed to reproduce one.

---

## 6. §5.7.3 The context manifest (new) and the entry hash

### 6.1 Entry hash

```
entry_hash = SHA3-256( "CONTEXT_ENTRY:v1:"
             ‖ UUID(entry_id) ‖ UUID(episode_id) ‖ STRING(entry_type)
             ‖ STRING(provided_to) ‖ TIMESTAMP(provided_at) ‖ UINT|NULL(provided_before_sequence_index)
             ‖ STRING(capture_state) ‖ HASH|NULL(content_hash) ‖ BOOL(salted)
             ‖ STRING|NULL(verifiability_at_seal) ‖ STRING|NULL(media_type)
             ‖ HASH|NULL(source_version_hash) ‖ HASH|NULL(resolves_entry_hash) )
```

`resolves_entry_hash` is the entry hash of the entry named by `resolves`, or NULL. Every field is recomputable from the stored node alone (§9.3).

### 6.2 Manifest hash

```
context_tree_root      = MerkleRoot_v2( sorted ascending bytewise ( entry_hash of every context entry ) )
                         — the §5.4 tree, TREE_LEAF:v2: / TREE_NODE:v2:, raw bytes; undefined for zero entries
context_manifest_hash  = SHA3-256( "CONTEXT_MANIFEST:v1:" ‖ STRING(capture_posture) ‖ UINT(n) ‖ HASH|NULL(context_tree_root) )
                         — n = number of entries; the root is NULL when n = 0
```

Sorting the leaves makes the tree a function of the **set** of entries: membership binds, insertion order does not, duplicated hashes are distinct entries only if their `entry_id`s differ (repeated provision of the same content is separate entries with the same `content_hash` and different hashes). The tree, rather than a §5.1.1 set hash, is what gives §9.2 inclusion proofs over the manifest: an examiner can be shown one entry's presence without the other entries — data minimisation is a property of the construction. The empty manifest is defined and is load-bearing: every Episode with no context entries composes `n = 0`, root NULL.

Every entry is a member — captured or declared-incomplete, present or tombstoned, resolved or not. A verifier MUST be able to rebuild `context_manifest_hash` from the stored context entries and the Episode's posture alone (§9.3).

### 6.3 Capture posture — G-41

The Episode declares, before it seals, what it undertook to capture:

| `capture_posture` | Meaning of an absent entry |
|---|---|
| `all_external` | Every provision of external content to a recorded agent has an entry (captured or declared-incomplete). Absence means no such provision occurred. |
| `declared_only` | Entries exist for the provisions the implementation elected to commit. Absence means "not committed," not "did not happen." |
| `none` | The Episode committed no context. Absence means nothing. |

The posture is in the manifest preimage, so the interpretation-governing field is sealed with the entries it governs: a manifest sealed `declared_only` cannot later claim `all_external`. Capture is agent-elective (a seal cannot bind an obligation §11 permits an implementation to skip); the posture is what makes elective capture legible rather than silently ambiguous. Verifier semantics, once: an entry proves *this content entered context at this time*; the posture bounds what the absence of an entry is permitted to mean.

---

## 7. §5.7 Episode root, version 3; §5.8 `spine_algorithm_version` 3

```
episode_root_hash = SHA3-256( "EPISODE_ROOT:v3:" ‖ UUID(episode_id)
                              ‖ HASH(spine_root) ‖ HASH(signal_manifest_hash)
                              ‖ HASH(structural_manifest_hash) ‖ HASH(exclusion_hash)
                              ‖ HASH(context_manifest_hash) )
```

The first five fields are the version 2 construction unchanged; the spine root of an Episode sealed under version 3 is byte-identical to the one it would have under version 2.

**§5.8 gains a row.** `spine_algorithm_version` **3** selects: leaf hash `hash_version` 2, the §5.4 tree, raw-byte encoding, `ordering_version` 2, the sets and manifests of §5.7, the context manifest of §5.7.3, and Episode root version 3. One identifier, one construction; an invalid combination remains unrepresentable. Records lacking the identifier read as before (§5.8). A seal made under 2 reproduces forever under 2; nothing is re-sealed.

| `spine_algorithm_version` | Leaf input | Encoding | Episode-identifier leaf | Episode root |
|---|---|---|---|---|
| `0` · `1` · `2` | as ratified | | | |
| `3` | `hash_version` 2 leaf hash, `sequence_index` order | raw bytes | none | **version 3** (§5.7, with §5.7.3) |

*(R1 re-ruled in-Episode, segment 57: `spine_algorithm_version` 3, no standalone axis. §1.)*

**§5.1.3 gains** `CONTEXT_ENTRY:v1:` · `CONTEXT_CONTENT:v1:` · `CONTEXT_CONTENT_SALTED:v1:` · `CONTEXT_MANIFEST:v1:` · `EPISODE_ROOT:v3:` · `ERASURE_TOMBSTONE:v1:`. None is a prefix of another or of an existing one.

---

## 8. Right-to-delete: content-plane erasure (§4.9, G-43)

### 8.1 Classification at write time

An implementation classifies each captured entry's content at write time as personal data or not, and as low- or high-entropy (`pii_classification`, an implementation field). The classification selects the construction (§5.3, G-42). Automated detection is out of scope for the protocol; the classifier is the implementation's and its quality is the implementation's residual risk (§14). Persistence-coefficient tagging and inference-residue quantification (Episode `531a045b`) are instruments an implementation may place above this classification; the protocol does not define them.

### 8.2 The erasure operation

On an authorised erasure request against a context entry:

1. Destroy the content at `content_ref`.
2. Destroy the salt at `salt_ref` — **atomically with step 1**: a surviving salt after a destroyed content, or the reverse, is an erasure that did not happen.
3. Append an **erasure tombstone** as a codicil (§8.3, `CODICIL_APPEND`).
4. Null `content_ref` and `salt_ref`; set `erasure_state = tombstoned`.
5. **Touch nothing else.** `content_hash`, `salted`, `verifiability_at_seal`, the entry hash, the manifest hash and the Episode root are unchanged.

Steps 4's fields are side-channel (§5.6). No sealed preimage moves; G-1 and §5.8's re-seal prohibition are preserved, not excepted. After erasure a salted `content_hash` is an unopenable commitment — non-reversible, non-confirming, dead — and a plain one is exactly as reversible as it always was, which is why G-42 forbids the plain form where erasure may be owed.

### 8.3 §4.9 ErasureTombstone — a codicil

```
ErasureTombstone (the content of a CodicilNode; CODICIL_APPEND) {
  tombstone_id:        UUID
  episode_id:          UUID
  entry_id:            UUID
  entry_hash:          HASH          (the erased entry's §6.1 hash — unchanged by erasure)
  erased_at:           datetime
  erasure_authority:   string        (the obligation invoked, e.g. "GDPR-Art17", "CCPA-1798.105")
  erasure_request_id:  string
  erased_by:           string        (agent_id or user_id)
}
tombstone_hash = SHA3-256( "ERASURE_TOMBSTONE:v1:" ‖ UUID(tombstone_id) ‖ UUID(episode_id) ‖ UUID(entry_id)
                           ‖ HASH(entry_hash) ‖ TIMESTAMP(erased_at) ‖ STRING(erasure_authority)
                           ‖ STRING(erasure_request_id) ‖ STRING(erased_by) )
```

The tombstone is the sole sanctioned post-closure append (§12.4.1) applied to erasure: a first-class, ledgered, chained fact that a sealed Episode's content was lawfully erased, witnessed by the same integrity machinery the erasure appears to threaten. A tombstone in an unsealed side log is a tombstone a deployment can drop; a codicil is not. Edge: `TOMBSTONE_WITNESSES: CodicilNode → ContextEntryNode`.

*(The 5.2.0 text names the codicil in §4.4.1 and §12.4.1 and the reference package carries `CodicilNode`; the SPEC has no schema block for it. This amendment adds one in §4.9 alongside the tombstone — `codicil_id`, `episode_id`, `author`, `content`, `content_hash`, `created_at`, `schema_version` — as ratified-by-implementation text, no construction change.)*

### 8.4 Erasure of a Segment's content

The same discipline applies to a Segment: its content lives behind `content_ref`; `content_hash` and the leaf hash are in the spine and never move. This amendment does not add a salted Segment construction — a Segment's `content_hash` is unsalted (§5.6, stated as a property) and the `node_id` in the leaf preimage is what protects a published leaf list, not the content hash. A future amendment may address Segments carrying low-entropy personal data; §14 records it.

---

## 9. Governance rules (new)

**G-41 — Capture posture and undeclared gaps.** An Episode sealed under `spine_algorithm_version` 3 MUST carry a `capture_posture`. A context entry whose write did not complete blocks the seal until it completes as `captured` or `declared_incomplete`. A declared-incomplete entry is a member of the manifest and MUST NOT be mutated; recovery of its content is a new entry that `resolves` it.

**G-42 — Non-reversible commitment for low-entropy personal data.** A context entry whose content is personal data and low-entropy MUST use `CONTEXT_CONTENT_SALTED:v1:`. An implementation that commits context without implementing this rule is not conformant to 6.0.0 (CM-09).

**G-43 — Erasure is content-plane.** Erasure of a context entry's content MUST destroy content and salt atomically, MUST append an erasure tombstone as a codicil, and MUST NOT alter `content_hash`, the entry hash, any manifest hash, any Episode root, or any sealed record. An implementation MUST NOT report an erased entry as an integrity failure; it reports it as erased and witnessed.

---

## 10. Verification (§9.2, §9.3 amended)

- **§9.3 extends to the sixth field.** A verifier holding the stored context entries and the posture rebuilds `context_manifest_hash` with no out-of-band state — no live source, no fetch, no cache.
- **Inclusion proofs over the manifest** are the §9.2 form over the context tree: `{ leaf_index, leaf_count, leaf_hash = entry_hash, siblings, context_tree_root }`, then `context_manifest_hash` from the root, posture and count, then the Episode root. One entry is proven without disclosing the others. `leaf_index` here is the entry's position in the sorted leaf list and carries no meaning beyond the proof.
- **The root is stable across erasure.** An Episode root verifies identically before and after any erasure (§8.2 step 5). A `tombstoned` entry verifies its entry hash from stored fields; the verifier consults the codicil chain for the tombstone and reports the erasure as witnessed, not as a failure.
- **`attested` entries verify to the commitment only**; a salted entry whose salt is destroyed can no longer be independently re-derived from content — expected, by design.
- **`external` entries are never re-fetched** for verification (§5.4).
- **Absence is read against the posture**, never as a fact of its own.

---

## 11. §11 and §12.4.1

§11 and §11.1 are **unchanged**. The retrieval audit records the act of reading, best-effort, outside every hash; it MUST still never fail a retrieval. The context entry records the thing read, committed. Two objects, deliberately separate; the audit is not promoted into the seal.

§12.4.1: the register gains **`CONTEXT_COMMIT`** (Tier 1) — writing a context entry is a ledgered operation. `CODICIL_APPEND` covers the tombstone. `ATTACHMENT_COMMIT` remains the ledger entry for attaching; providing an attachment to an agent is a `CONTEXT_COMMIT`.

---

## 12. §21 — relation, no change

`SkillInvocation` is unchanged. A `tool_output` context entry binds an invocation by its `content_hash` (§5.1). A conforming implementation writes the entry when the rendered result enters an agent's context; the invocation alone does not put the result under the Episode seal, and the entry alone does not record that the agent performed the action.

---

## 13. Conformance sketch (`CONFORMANCE-CONTEXT.md`, to be written with vectors)

| ID | Class | Requires |
|---|---|---|
| CM-01 | REQUIRED | An Episode with zero context entries seals under version 3 with `n = 0`, root NULL, and reproduces. |
| CM-02 | REQUIRED | Entry hash: field order, encoding, NULLs for a declared-incomplete entry; changing any preimage field changes it; changing a side-channel field does not. |
| CM-03 | REQUIRED | Manifest hash is order-independent: the same entries in any insertion order yield one hash; removing any entry changes it; the posture changes it. |
| CM-04 | REQUIRED | Inclusion proof of one entry verifies to the Episode root without the other entries. |
| CM-05 | REQUIRED | A `resolves` entry binds the resolved entry's hash; the resolved entry is unchanged. |
| CM-06 | REQUIRED | Erasure: after §8.2 the Episode root verifies unchanged; the entry reads `tombstoned`; a codicil tombstone with the entry's hash exists; content and salt are both gone. |
| CM-07 | REQUIRED | A salted entry's `content_hash` does not confirm a guess at the content once the salt is destroyed; a plain entry's does (stated as a property, tested by construction). |
| CM-08 | REQUIRED | An `external` entry verifies without a fetch; a differing fetch is not a failure. |
| CM-09 | REQUIRED | *Safe only together*: an implementation whose `ConformanceDeclaration` claims 6.0.0 context commitment and does not implement G-42 is non-conformant. |
| CM-10 | REQUIRED | A version 2 seal of an Episode that has context entries reproduces under version 2 (the entries are not members of a version 2 root). |

Vectors go in `vectors/6.0.0/context-commitment.json`, generated, never hand-written.

---

## 14. Known limitations and what this amendment does not do

- **Classification is only as good as the classifier.** `pii_classification` is set at write time; a low-entropy value classified as high-entropy gets a plain, reversible commitment. This is the amendment's principal residual risk and belongs in the implementation's conformance declaration.
- **Segments** carrying low-entropy personal data are not given a salted construction here (§8.4).
- **Verifiability of salted entries needs the salt.** Independent verification of an un-erased salted entry requires disclosure of that one entry's salt to the verifier — the inherent trade of "verifiable by anyone" against "truly deletable," made per entry rather than per Episode.
- **Nothing is retroactive.** No existing seal gains a context manifest; no record is re-sealed; the 4.x and 5.x constructions are retained as the definitions of the seals made under them.

---

## 15. Reference package and reference deployment obligations (not normative)

- `astp`: `ContextEntryNode` and `ErasureTombstone` models; `compute_context_entry_hash`, `compute_context_content_hash` (plain / salted), `compute_context_manifest_hash`, `compute_episode_root_hash_v3`, `compute_episode_seal_v3`; `reproduce_episode_root(spine_algorithm_version=3)`; `InMemoryStore` and `StructuralStore` gain context-entry, tombstone and posture operations; `proof_of_record` learns the sixth field; vectors and `CONFORMANCE-CONTEXT.md`; `MAJOR` release 2.0.0 of the package with SPEC 6.0.0.
- Ignis OS: the adapter writes context entries at the three seams that already exist — attachment injection into a prompt, the retrieval tools (alongside their §11.1 audit), the web-fetch tool — and `tool_output` entries from Layer 3; sets the Episode's capture posture (`declared_only` until the seams are complete, then `all_external`); a `salt://` namespace with atomic paired deletion; the erasure operation and its tombstone codicil; the crystallize handler seals under version 3.

---

*ASTP 6.0.0 — Context Commitment, draft.2. The seal proves history, not retention.*
