# Contributing to ASTP

This repository ships a protocol: a normative specification, conformance requirements, and a Python reference implementation. Most of what makes a contribution easy or hard to accept follows from that, so read this page before opening a pull request.

Participation is governed by the [Code of Conduct](./CODE_OF_CONDUCT.md). Suspected vulnerabilities go through [`SECURITY.md`](./SECURITY.md), not the issue tracker. How decisions are made, and who makes them, is in [`GOVERNANCE.md`](./GOVERNANCE.md).

## Setting up

Python 3.11 or later.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
```

The suite needs no database and no network: the operations run against the in-memory reference store. A deployment's adapter lives with that deployment, and so do its integration tests.

Run a single file or test the usual way:

```bash
pytest tests/unit/protocol/test_verification.py
pytest tests/unit/protocol/test_verification.py::test_name -v
```

Every test file must pass on its own as well as in the full run. CI checks both.

## Decide what kind of change it is first

[`VERSIONING.md`](./VERSIONING.md) is the policy. The question that sorts almost every change is: *does an implementation that conforms today still conform afterwards, without modification?*

| Change | Version | What it needs |
|---|---|---|
| Wording, clarification, a broken reference, a contradiction resolved in favour of existing behaviour | PATCH | A pull request. |
| New optional node type, edge type, field with a safe default, or query surface | MINOR | An issue first, so the design is agreed before the text is written. |
| Anything that touches canonical form — a hash preimage, a serialization, a required field, the semantics of a governance rule, removal or renaming of normative surface | MAJOR | An issue first, then the amendment process in [`GOVERNANCE.md`](./GOVERNANCE.md). |

If you are unsure, open an issue and ask. A pull request that quietly changes a preimage will be closed however good the reason; records already sealed under the old construction have to stay verifiable, and that takes a versioned change, not an edit.

Any change to normative text updates the `Version:` field in `SPEC.md` and adds an entry to `CHANGELOG.md` in the same pull request. A test enforces that the two agree.

## Rules that are not negotiable in review

- **The namespace firewall.** Nothing under `astp/protocol/` may import from `astp/nodes/`. If a change seems to need it, the symbol is in the wrong layer. Move the symbol; do not relax the test.
- **Dual index.** `sequence_index` is in the leaf hash preimage. `tree_leaf_index` is not. They are never swapped.
- **No reparenting, no in-place edits of sealed records.** Corrections go forward: a new node and a deprecation or succession edge.
- **Layer 3 stays isolated.** Workflow and execution records reference Layers 1 and 2 by identifier only, and each Layer 3 node type has a single designated writer.
- **Wire constants keep their names.** The HKDF `info` strings, the `ariadne::` coordinator key prefix, and the `Ariadne*` graph labels predate the package rename and are inputs to derived keys or names of stored data. `tests/unit/protocol/test_wire_constants.py` pins them.
- **Governance violations raise.** Rules `G-*` are enforced where the write happens and surface as exceptions. Do not catch and continue.

## Documents

- [`GLOSSARY.md`](./GLOSSARY.md) is the single source for definitions. If a term is there, reference it. If you are introducing a term, add it to the glossary first and then use it.
- New normative or companion documents carry the header block the existing ones use: **Version**, **Status**, **Authors**, **Date**.
- Write requirements with the BCP 14 keywords (MUST, SHOULD, MAY) in capitals, and only where you mean them.
- Conformance requirements state inputs, the expected output, and the failure condition. Where the expected output is a digest, give the digest.

## Code

- Every `.py` file starts with the Apache-2.0 header used throughout the repository, before the module docstring.
- Match the surrounding code: naming, comment density, error types.
- A change to behaviour comes with a test that fails without it. For anything that produces a hash, that means a fixed expected value, not a check that the function agrees with itself.
- There is no formatter or linter configured. Please do not reformat files you are not otherwise changing.

## Pull requests

Keep them to one purpose. Say which kind of change it is (PATCH, MINOR, MAJOR, or no protocol change), which sections of `SPEC.md` it touches, and how you tested it. Every commit must carry a `Signed-off-by` line certifying its origin — see **Certificate of origin** below.

## Certificate of origin

This project uses the [Developer Certificate of Origin](https://developercertificate.org/)
1.1. It is a statement about where your contribution came from and that you have
the right to submit it. There is nothing to sign and no account to create.

Add a `Signed-off-by` line to every commit, matching the name and address you
commit under:

    Signed-off-by: Jane Developer <jane@example.com>

`git commit -s` adds it for you. `git rebase --signoff` adds it to commits you
have already made.

By signing off you certify the DCO, reproduced in [`DCO.txt`](./DCO.txt), and
you agree that your contribution is licensed under the
[Apache License 2.0](./LICENSE.txt). Section 5 of that licence covers what you
grant, including the patent grant in section 3.

**Specification changes carry more weight than code.** A contribution to
`SPEC.md` becomes part of the text that [`PATENTS.md`](./PATENTS.md) pledges
against and that [`PROTOCOL-CONFORMANCE.md`](./PROTOCOL-CONFORMANCE.md) defines
conformance to. Apache 2.0 governs what you contribute, and the sign-off is your
statement that it is yours to contribute. If a proposed change touches
`SPEC.md`, say in the pull request whether any of it derives from work owned by
an employer or a third party, or is covered by a patent or application you know
of. It does not necessarily prevent the change; it does need to be known before
the change is merged.

A pull request whose commits are not signed off cannot be merged.
