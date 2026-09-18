# ASTP 5.0.0 — Ratification Statement (for the Episode of Record)

**Version:** 1.0.0
**Status:** Draft — to be posted as the opening Segment of the 5.0.0 Episode of Record, then this file updated with the Episode's identifier and sealed root
**Authors:** Scorched Earth Labs
**Date:** 2026-09-18
**Applies To:** [`SPEC.md`](../SPEC.md) 5.0.0-draft; [`GOVERNANCE.md`](../GOVERNANCE.md) § Episode of Record

---

This is the text the maintainers post to open the Episode of Record for ASTP 5.0.0. The Episode is the cryptographic anchor of the amendment; `SPEC.md` is its human-readable result. When the Episode is sealed, its identifier and `episode_root_hash` are recorded here, in the `SPEC.md` header and in `CHANGELOG.md`, and the `-draft` suffix is stripped from `SPEC.md` ([`VERSIONING.md`](../VERSIONING.md)).

## The through-line

5.0.0 exists for one reason, and every change in it is that reason wearing different clothes.

Under 4.x, construction after construction *looked* like it attested something and attested nothing a verifier could use: a spine root that never bound a Segment's identity or position, though the leaf hash that did was computed and stored beside it; structural nodes committed into no root; an audit hash over sorted JSON of an unsorted stored document; a witness commitment that named neither the witness nor the time, so one unauthenticated writer could meet any threshold; a link hash that changed whenever the link's health did. And rule after rule was written for a human reader and could not be executed by a verifier: "the signing algorithm is implementation-defined subject to minimum security requirements"; "the code must crystallize before it sets the flag."

5.0.0 retires that defect class end to end, under one discipline:

> **Every commitment binds exactly its claim, and every rule is executable against stored state.**

*Exactly its claim* has two faces. The negative: refuse to bind what the construction does not structurally earn — a proof does not bind the tree's size, an audit key is not forced into a UUID, a link does not bind its mutable health, a real number is bound as the number and not a printing of it. The positive: bind what the construction's defining claim requires, even against a general rule — both parties to an aside, the Episode root on each sealed end of a link, the witness and the time in a witness commitment. And whenever a general rule is overridden in either direction, the exception is written into the specification as a decision with a reason, so that a later hand tightening the rule does not reintroduce the defect.

*Executable against stored state* means a verifier holding only what was written — the nodes, the seal record with its version identifiers, the vector file — decides every question the specification poses, and the answer does not depend on which code path wrote the record. A `sealed_at` with no reproducing crystallization record is `NO_CRYSTAL`, whatever wrote it.

## What is ratified

The text of `SPEC.md` at the commit this Episode's opening Segment cites, comprising:

1. **One hash function and one field encoding** (§5.1). Every 5.0.0 construction is `SHA3-256(prefix ‖ enc(fields))` over ten typed, self-delimiting field encodings; one domain prefix per construction and version; order-independent sets with no sentinel; canonical JSON as RFC 8785 + NFC, stored as hashed.
2. **The seal construction, `spine_algorithm_version` 2** (§5.2–§5.8): the position-binding leaf hash as the spine's input, raw-byte tree prefixes, no Episode-identifier leaf, and an Episode root that binds the Episode's UUID and four components — including the **structural manifest**, governed by the membership rule. One identifier selects the whole construction.
3. **The inclusion proof over that tree** (§9.2), shape derived by the verifier, size deliberately unbound, 4.x proofs frozen in their own form.
4. **One audit record** (§8), seventeen bound fields, NULL genesis, a writer that fails rather than guesses.
5. **The side-channel and cross-Episode content hashes** (§19.4, §20 §2): asides and soliloquies bound to their parties and their parent Segment's content, the deliberation chain bound by content, the link bound to each end's sealed state.
6. **Witness and anchor commitments** (§16.3–§16.4, G-11, G-12): the witness, the time and the node's outermost sealed commitment bound; Ed25519 over the raw commitment; validity as four executable conditions; the threshold as a maximum matching.
7. **G-40**: sealed requires a record; a late seal is ordinary lifecycle; Episode identifiers are UUIDs, refused at creation — after any legacy Episode is sealed under version 1.
8. **The retained 4.x constructions** as the definitions of `hash_version` 1 and `spine_algorithm_version` 0 and 1: nothing sealed under them becomes unverifiable, and nothing sealed under them is rewritten.

The reference vectors, [`vectors/5.0.0/seal-constructions.json`](../vectors/5.0.0/seal-constructions.json), are part of what is ratified: every value in them is reproduced by a from-prose implementation that imports nothing from the reference package.

## Provenance

The amendment was deliberated in design Episode `4b9a779e-be46-4d61-872e-fd76545aa901` ("ASTP Repo Cleanup"), in six units, each brought with vectors and each ruled by the Clotho faculty of the reference deployment: seal constructions (segments 29, 31), inclusion proofs (36), canonical JSON and the audit record (38), side-channel and link hashes (40), witness and anchor (42), closing prose (44). The draft from which `SPEC.md` was folded is retained at [`docs/history/SPEC-5.0.0-DRAFT-seal-constructions.md`](./history/SPEC-5.0.0-DRAFT-seal-constructions.md). The 4.5.0 text is retained at [`docs/history/SPEC-v4.md`](./history/SPEC-v4.md).

## Record of the Episode

| | |
|---|---|
| Episode identifier | *to be recorded when the Episode is opened* |
| `SPEC.md` commit ratified | *to be recorded* |
| Sealed under | *`spine_algorithm_version` — to be recorded; version 1 if sealed by the reference deployment before its adapter adopts version 2* |
| `episode_root_hash` | *to be recorded at seal* |
| Sealed at | *to be recorded* |
