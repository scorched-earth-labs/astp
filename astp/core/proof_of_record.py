# Copyright 2026 Scorched Earth Labs, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Proof of record — a sealed Episode, exported so that a third party verifies it
with this package alone (SPEC §9.3; GLOSSARY *Proof of Record*).

A proof of record is a JSON document. Two profiles:

* **full** — everything a verifier needs to rebuild the roots from stored
  state: the seal record with its §5.8 version identifiers and, per that
  version, the Segments' stored fields (version 2: the six leaf-hash fields;
  versions 0 and 1: content hashes in `sequence_index` order), the SPINE
  Signals' content hashes, the excluded content hashes, the structural member
  hashes (version 2), and a `resolved_signal_order` if the seal needed one.
  It contains unsalted content hashes and is published only where those are.
* **attested** — the seal record only: the roots, the version identifiers and
  the times. A verifier checks that the Episode root recomposes from its
  components under the named construction, and that the document is
  internally consistent; it cannot rebuild the spine root, and says so.

``verify_proof_of_record`` reproduces what the profile allows and reports
exactly what it checked. It never returns "verified" for a claim it could not
rebuild.
"""

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID

from astp import PROTOCOL_VERSION
from astp.core.schema import reproduce_spine_root
from astp.core.seal_v2 import SegmentSealInput, compute_episode_seal_v2, reproduce_episode_root
from astp.core.context_v1 import ContextEntryNode, compute_episode_seal_v3

FORMAT = "astp-proof-of-record/1"
PROFILES = ("attested", "full")


@dataclass
class ProofVerification:
    ok: bool
    profile: str
    checks: List[str] = field(default_factory=list)        # what was reproduced and agreed
    not_checked: List[str] = field(default_factory=list)   # what the profile withholds
    failures: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def build_proof_of_record(
    *,
    episode_id: str,
    profile: str,
    spine_algorithm_version: int,
    ordering_version: int,
    sealed_at: str,
    closed_at: Optional[str],
    spine_root: str,
    signal_manifest_hash: Optional[str],
    exclusion_hash: Optional[str],
    episode_root_hash: Optional[str],
    structural_manifest_hash: Optional[str] = None,
    context_manifest_hash: Optional[str] = None,     # version 3 (6.0.0): the sixth root field
    capture_posture: Optional[str] = None,           # version 3: sealed with the manifest
    context_entry_count: Optional[int] = None,
    leaf_count: Optional[int] = None,
    segments: Optional[List[dict]] = None,             # full, version 2: six fields each; versions 0/1: {sequence_index|leaf_index, content_hash}
    signal_content_hashes: Optional[List[str]] = None,
    excluded_content_hashes: Optional[List[str]] = None,
    structural_member_hashes: Optional[List[str]] = None,
    context_entries: Optional[List[dict]] = None,       # full, version 3: the stored fields of every context entry
    resolved_signal_order: Optional[List[str]] = None,
    title: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    if profile not in PROFILES:
        raise ValueError(f"profile must be one of {PROFILES}")
    doc: Dict[str, Any] = {
        "format": FORMAT,
        "protocol_version": PROTOCOL_VERSION,
        "profile": profile,
        "episode_id": episode_id,
        "title": title,
        "seal": {
            "spine_algorithm_version": spine_algorithm_version,
            "ordering_version": ordering_version,
            "hash_version": 2 if spine_algorithm_version in (2, 3) else 1,
            "sealed_at": sealed_at,
            "closed_at": closed_at,
            "spine_root": spine_root,
            "signal_manifest_hash": signal_manifest_hash,
            "exclusion_hash": exclusion_hash,
            "structural_manifest_hash": structural_manifest_hash,
            "context_manifest_hash": context_manifest_hash,
            "capture_posture": capture_posture,
            "context_entry_count": context_entry_count,
            "episode_root_hash": episode_root_hash,
            "leaf_count": leaf_count,
        },
        "notes": notes,
    }
    if profile == "full":
        doc["stored"] = {
            "segments": segments or [],
            "signal_content_hashes": list(signal_content_hashes or []),
            "excluded_content_hashes": list(excluded_content_hashes or []),
            "structural_member_hashes": list(structural_member_hashes or []),
            "context_entries": list(context_entries or []),
            "resolved_signal_order": resolved_signal_order,
        }
    return doc


def verify_proof_of_record(doc: dict) -> ProofVerification:
    """Reproduce what the document's profile allows and report it."""
    v = ProofVerification(ok=False, profile=str(doc.get("profile")))
    if doc.get("format") != FORMAT:
        v.failures.append(f"unknown format {doc.get('format')!r}; expected {FORMAT}")
        return v
    if v.profile not in PROFILES:
        v.failures.append(f"unknown profile {v.profile!r}")
        return v
    seal = doc.get("seal") or {}
    sav, ov = seal.get("spine_algorithm_version"), seal.get("ordering_version")
    eid = str(doc.get("episode_id"))
    # spine_root is the one root every seal has. The manifests and the Episode root
    # were introduced at 4.3.0; a seal made before that carries none, and a proof
    # says so with null rather than inventing them. Version 2 always has all four.
    for k in ("spine_root", "signal_manifest_hash", "exclusion_hash", "episode_root_hash", "structural_manifest_hash", "context_manifest_hash"):
        val = seal.get(k)
        if val is not None and (not isinstance(val, str) or len(val) != 64):
            v.failures.append(f"seal.{k} is not a 64-hex digest")
    if not seal.get("spine_root"):
        v.failures.append("seal.spine_root missing")
    if sav in (2, 3):
        for k in ("signal_manifest_hash", "exclusion_hash", "structural_manifest_hash", "episode_root_hash"):
            if not seal.get(k):
                v.failures.append(f"version {sav} seal without {k}")
    if sav == 3:
        if not seal.get("context_manifest_hash"):
            v.failures.append("version 3 seal without context_manifest_hash")
        if not seal.get("capture_posture"):
            v.failures.append("version 3 seal without capture_posture (G-41)")
    if sav not in (0, 1, 2, 3) or ov not in (1, 2):
        v.failures.append(f"unknown version identifiers sav={sav!r} ov={ov!r}")
    if sav in (2, 3) and ov != 2:
        v.failures.append(f"spine_algorithm_version {sav} requires ordering_version 2")
    if seal.get("sealed_at") and seal.get("closed_at") and seal["sealed_at"] < seal["closed_at"]:
        v.failures.append("sealed_at precedes closed_at (G-40)")
    if v.failures:
        return v

    if v.profile == "attested":
        v.not_checked += ["spine_root (leaf list withheld)", "signal_manifest_hash and exclusion_hash membership (hash lists withheld)"]
        if sav in (2, 3):
            v.not_checked.append("structural_manifest_hash membership (member list withheld)")
        if sav == 3:
            v.not_checked.append("context_manifest_hash membership (entry list withheld)")
        v.checks.append("document internally consistent; version identifiers known")
        v.checks.append("attested profile: the Episode root's composition is verifiable only with the component hash lists, which this profile withholds — request the full profile to reproduce it")
        v.ok = True
        return v

    stored = doc.get("stored") or {}
    sigs = list(stored.get("signal_content_hashes") or [])
    excl = list(stored.get("excluded_content_hashes") or [])
    members = list(stored.get("structural_member_hashes") or [])
    segs = stored.get("segments") or []
    entries = stored.get("context_entries") or []
    try:
        if sav == 3:
            inputs = [SegmentSealInput(node_id=UUID(s["node_id"]), node_type=s.get("node_type", "segment"),
                                       schema_version=s["schema_version"], sequence_index=int(s["sequence_index"]),
                                       content_hash=s["content_hash"], parent_node_id=UUID(s["parent_node_id"]) if s.get("parent_node_id") else None)
                      for s in segs]
            sealed3 = compute_episode_seal_v3(UUID(eid), inputs, capture_posture=str(seal.get("capture_posture")),
                                              context_entries=[ContextEntryNode(**e) for e in entries],
                                              signal_content_hashes=sigs, excluded_content_hashes=excl, structural_member_hashes=members)
            root, ep_root = sealed3.spine_root, sealed3.episode_root_hash
            comp = {"signal_manifest_hash": sealed3.signal_manifest_hash, "exclusion_hash": sealed3.exclusion_hash,
                    "structural_manifest_hash": sealed3.structural_manifest_hash, "context_manifest_hash": sealed3.context_manifest_hash}
        elif sav == 2:
            inputs = [SegmentSealInput(node_id=UUID(s["node_id"]), node_type=s.get("node_type", "segment"),
                                       schema_version=s["schema_version"], sequence_index=int(s["sequence_index"]),
                                       content_hash=s["content_hash"], parent_node_id=UUID(s["parent_node_id"]) if s.get("parent_node_id") else None)
                      for s in segs]
            sealed = compute_episode_seal_v2(UUID(eid), inputs, signal_content_hashes=sigs, excluded_content_hashes=excl,
                                             structural_member_hashes=members)
            root, ep_root = sealed.spine_root, sealed.episode_root_hash
            comp = {"signal_manifest_hash": sealed.signal_manifest_hash, "exclusion_hash": sealed.exclusion_hash,
                    "structural_manifest_hash": sealed.structural_manifest_hash}
        else:
            # versions 0/1 seal by leaf order; a document may carry sequence_index or, if the
            # exporter had only the ordered leaf list, leaf_index
            content = [s["content_hash"] for s in sorted(segs, key=lambda s: int(s.get("sequence_index", s.get("leaf_index", 0))))]
            order = stored.get("resolved_signal_order")
            signals_in_order = list(order) if order else sigs
            if ov == 1 and order and sorted(order) != sorted(sigs):
                v.failures.append("resolved_signal_order is not a reordering of the stored SPINE signals; ignored")
                signals_in_order = sigs
            root = reproduce_spine_root(content, signals_in_order, spine_algorithm_version=sav, ordering_version=ov,
                                        episode_id=eid if sav == 1 else None)
            from astp.core.schema import compute_exclusion_hash, compute_signal_manifest_hash
            comp = {"signal_manifest_hash": compute_signal_manifest_hash(sigs), "exclusion_hash": compute_exclusion_hash(excl),
                    "structural_manifest_hash": None}
            ep_root = reproduce_episode_root(spine_algorithm_version=sav, episode_id=eid, spine_root=root,
                                             signal_content_hashes=sigs, excluded_content_hashes=excl)
    except Exception as e:  # a malformed document is a failed verification, not a crash
        v.failures.append(f"could not reproduce: {e}")
        return v

    def check(name, got, want):
        if want is None:
            why = ("a version 1 seal has no structural manifest" if name == "structural_manifest_hash"
                   else "not recorded by this seal — it predates the Episode root of 4.3.0")
            v.not_checked.append(f"{name} ({why})")
            return
        if got == want:
            v.checks.append(f"{name} reproduced")
        else:
            v.failures.append(f"{name} differs: recomputed {got} != sealed {want}")

    check("spine_root", root, seal["spine_root"])
    for k, got in comp.items():
        check(k, got, seal.get(k))
    check("episode_root_hash", ep_root, seal["episode_root_hash"])
    if seal.get("leaf_count") is not None and int(seal["leaf_count"]) != len(segs):
        v.failures.append(f"leaf_count {seal['leaf_count']} != {len(segs)} segments supplied")
    if sav == 3 and seal.get("context_entry_count") is not None and int(seal["context_entry_count"]) != len(entries):
        v.failures.append(f"context_entry_count {seal['context_entry_count']} != {len(entries)} entries supplied")
    v.ok = not v.failures
    return v


def dumps(doc: dict) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    """``python -m astp.core.proof_of_record verify <file.json>``"""
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2 or argv[0] != "verify":
        print("usage: python -m astp.core.proof_of_record verify <proof.json>", file=sys.stderr)
        return 2
    with open(argv[1], "rb") as f:
        doc = json.load(f)
    result = verify_proof_of_record(doc)
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
