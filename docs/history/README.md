# docs/history/ — superseded documents

**Nothing in this directory is normative. Do not implement from it.** The protocol is defined by [`SPEC.md`](../../SPEC.md) at the repository root, and only there.

These files are kept for provenance: they show what earlier versions said and what each ratified amendment was ratified from. Each carries a banner at the top naming what superseded it.

| Files | What they are |
|---|---|
| `SPEC-v{N}.md` | The final text of a prior MAJOR version of the specification, moved here when the next MAJOR version replaced it ([`VERSIONING.md`](../../VERSIONING.md)). |
| `SPEC-{version}-DRAFT-*.md` | Amendment drafts that a MAJOR version was ratified from and then folded into `SPEC.md`. |
| `AMENDMENT-*.md` | Former standalone amendment documents, since integrated into the body of `SPEC.md`. |
| `VISION.md` | The original architecture vision, written against the `0.1.0-draft` design. |

**When an older file is still the right one to read.** Conformance is not preserved across MAJOR versions ([`VERSIONING.md`](../../VERSIONING.md)). An implementation built against an earlier MAJOR version needs the specification it was built against, and that is the matching `SPEC-v{N}.md` here. Seals made under earlier constructions remain verifiable: `SPEC.md` retains those constructions as the definitions of their `hash_version` and `spine_algorithm_version` values.

**These files are not edited.** Some banners record the digest of a file as it stood when it was ratified, and records outside this directory cite these files by commit. A correction belongs in `SPEC.md`, under the process in [`GOVERNANCE.md`](../../GOVERNANCE.md).
