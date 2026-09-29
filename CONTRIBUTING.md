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

A pull request whose commits are not signed off cannot be merged.

**Specification changes carry more weight than code.** A contribution to
`SPEC.md` becomes part of the text that [`PATENTS.md`](./PATENTS.md) pledges
against and that [`PROTOCOL-CONFORMANCE.md`](./PROTOCOL-CONFORMANCE.md) defines
conformance to. The additional requirements are below.

## Specification contributions and patent disclosure

Normative changes to the ASTP Specification are subject to the following
patent-disclosure requirements.

### 1. DCO requirement

Every contributor submitting a specification change must provide the Developer
Certificate of Origin sign-off required by this repository's contribution
policy.

The DCO governs contributor provenance and authority to submit the contribution.
It does not modify or expand the patent commitments described in
[`PATENTS.md`](./PATENTS.md).

### 2. Patent disclosure

A contributor proposing a normative specification change must disclose, in the
applicable pull request, any patent, patent application, or known third-party
patent right of which the contributor has actual knowledge and that the
contributor reasonably believes may contain a claim necessarily infringed by
implementation of the proposed normative requirement.

Where the contributor is acting on behalf of an employer or other organization,
the contributor must disclose any relevant patent ownership or control known to
the contributor or identified through the contributor's applicable
organizational review process.

A disclosure should identify, to the extent reasonably available:

- the patent or patent application;
- the owner or applicant;
- the specification section or requirement implicated; and
- any known licensing commitment applicable to the disclosed claim.

### 3. No patent warranty

A patent disclosure is not a representation that a patent claim is valid,
enforceable, essential, or necessarily infringed by the Specification. It is a
disclosure of known or reasonably identified patent rights for consideration by
the maintainers.

Contributors are not required to identify patents of which they have no actual
knowledge.

### 4. Disclosure does not create a license

Disclosure of a patent or patent application does not, by itself, grant a patent
license or create a commitment by the patent owner to license the disclosed
patent.

Patent rights applicable to contributions remain governed by the Apache License,
Version 2.0, any separate agreement with the relevant rights holder, and
[`PATENTS.md`](./PATENTS.md), as applicable.

### 5. Normative changes affecting patent rights

Before merging a normative specification change, maintainers should determine
whether a disclosed patent right presents an issue for implementation of the
proposed requirement.

Where appropriate, the maintainers may:

- obtain an appropriate patent licensing commitment;
- modify the proposed requirement to avoid the disclosed claim;
- make the feature optional rather than mandatory;
- document that the relevant patent right is outside the project's patent
  commitment; or
- decline to merge the proposed requirement.

No specification contribution shall be understood to expand the patent pledge
beyond the express terms of [`PATENTS.md`](./PATENTS.md).

### 6. Employer and organizational rights

A contributor must not represent that a patent right is available for licensing
on behalf of an employer or other organization unless the contributor is
authorized to make that commitment.

Where a proposed normative change is owned or controlled by an employer or other
organization, the maintainers may require a written patent commitment from the
applicable rights holder before incorporating the change into a normative
Specification Version.

### 7. Apache License

Specification text accepted into the repository is subject to the applicable
copyright and patent terms of the Apache License, Version 2.0, unless a separate
written agreement provides otherwise.

Nothing in this policy limits the patent rights granted by Apache License §3 or
modifies the terms of Apache License §5.
