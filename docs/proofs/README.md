# Proofs of record

**Version:** 1.0.0
**Status:** Stable
**Authors:** Scorched Earth Labs
**Date:** 2026-09-22
**Applies To:** [`SPEC.md`](../../SPEC.md) 6.0.0 §9.3; [`GLOSSARY.md`](../../GLOSSARY.md) *Proof of Record*

Exported sealed Episodes that a third party verifies with the `astp` package alone — no access to the deployment that sealed them:

```bash
pip install /path/to/astp            # or the published package
python -m astp.core.proof_of_record verify docs/proofs/episode-of-record-5.0.0.ce3f569c.full.json
```

The verifier reproduces every root the document's profile allows from the stored inputs it carries, under the construction the seal's §5.8 version identifiers name, and prints exactly what it checked, what the profile withholds, and what failed. It never reports a claim it could not rebuild.

| File | Episode | Sealed | Construction | Reproduces |
|---|---|---|---|---|
| `episode-of-record-patents-1.0.0.df3434bd.full.json` | Episode of Record for `PATENTS.md` 1.0.0 (`df3434bd-6936-441c-a896-254149f2bd48`) | 2026-10-01 | `spine_algorithm_version` 3, `ordering_version` 2 | spine root, signal manifest, structural manifest, exclusion set, context manifest, Episode root |
| `episode-of-record-spec-6.0.2.46490010.full.json` | Episode of Record for `SPEC.md` 6.0.2 (whole document) and `PROTOCOL-CONFORMANCE.md` 1.0.1 (`46490010-e8a7-4d79-8092-a1a82de3c93f`) | 2026-10-01 | `spine_algorithm_version` 3, `ordering_version` 2 | spine root, signal manifest, structural manifest, exclusion set, context manifest, Episode root |
| `episode-of-record-protocol-conformance-1.0.0.19d4390f.full.json` | Episode of Record for `PROTOCOL-CONFORMANCE.md` 1.0.0 (`19d4390f-ac46-4840-bc9a-f419c6626fb4`) | 2026-10-01 | `spine_algorithm_version` 3, `ordering_version` 2 | spine root, signal manifest, structural manifest, exclusion set, context manifest, Episode root |
| `episode-of-record-6.0.0.80e5a2dd.full.json` | Episode of Record for 6.0.0 (`80e5a2dd-3d9f-45d0-abfb-6489c8caf1b8`) | 2026-09-22 | `spine_algorithm_version` 2, `ordering_version` 2 | spine root, signal manifest, structural manifest, exclusion set, Episode root |
| `episode-of-record-5.0.0.ce3f569c.full.json` | Episode of Record for 5.0.0 (`ce3f569c-9cdc-4a3d-913a-b9d8573d9a28`) | 2026-09-18 | `spine_algorithm_version` 1, `ordering_version` 2 | spine root, signal manifest, exclusion set, Episode root |
| `episode-of-record-4.0.0.458fb62b.full.json` | Episode of Record for 4.0.0 (`458fb62b-faee-4e42-9f92-c63187c1b59a`) | 2026-08-22 | `spine_algorithm_version` 1, `ordering_version` 1 (+ `resolved_signal_order`) | spine root (the seal predates the Episode root of 4.3.0) |

**Profiles.** `full` carries the stored inputs — content hashes in leaf order (or the six leaf-hash fields under version 2 and 3), SPINE Signal hashes, exclusions, structural members, under version 3 the stored context entries and the capture posture, and a `resolved_signal_order` where a version-1 seal needed one. Content hashes are unsalted, so a full proof is published only where those may be; for these Episodes the content is the ratification deliberation, which is public. `attested` carries the seal record only and verifies nothing that requires the withheld lists; it says so.

**Exporting.** A deployment exports with its own reader; the reference deployment's is `scripts/export_proof_of_record.py` in ignis-os, which refuses to write a document that does not reproduce. The format is `astp-proof-of-record/1` (`astp/core/proof_of_record.py`).
