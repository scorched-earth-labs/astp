# Security Policy

ASTP is an integrity protocol. A flaw in how it hashes, chains, seals, or verifies is a security issue even when no code crashes, so this policy covers the specification as well as the reference implementation.

## What to report

**Specification**

- A way to produce two different records with the same hash under any construction the spec defines (preimage ambiguity, missing domain separation, canonicalization gaps).
- A way to alter, reorder, insert, or remove sealed content such that a conforming verifier still accepts it.
- A way to satisfy a governance rule (`G-*`), a witness threshold, or a proof-chain check without meeting its stated conditions.
- Any path by which a Layer 3 write can affect Layer 1 or Layer 2 integrity.

**Reference implementation (`astp/`)**

- Verification that passes when the specification says it must fail.
- Writes that are reported as successful but were not performed, where a caller could rely on the result.
- Injection into adapter queries, or exposure of record content through logs or errors.

Conformance gaps that have no integrity consequence — a missing optional feature, a documentation error — are ordinary bugs. Open a public issue for those.

## How to report

Report privately. Do not open a public issue or pull request for a suspected vulnerability.

1. Preferred: use GitHub's private vulnerability reporting for this repository (**Security → Report a vulnerability**).
2. Alternatively, email **dev@scorchedearthlabs.com** with `ASTP security` in the subject line.

Include the SPEC version (the `Version:` field in `SPEC.md`) or the package version and commit, the construction or function affected, and the smallest input that demonstrates the problem. Byte-level inputs and expected versus actual digests are the most useful form of report.

## What happens next

We will acknowledge the report, confirm whether we can reproduce it, and keep you informed while we work on it. We will agree a disclosure date with you before publishing anything, and we will credit you in the advisory and the changelog unless you ask us not to.

A fix that changes canonical form is a MAJOR protocol change under [`VERSIONING.md`](./VERSIONING.md). Such fixes ship as a new versioned construction, so that records sealed under the old one remain verifiable; the advisory will say which records are affected and how to re-verify them.

## Supported versions

Security fixes are made against the current `SPEC.md` version and the current release of the `astp` package. Documents under `docs/history/` are retained for provenance and are not maintained.
