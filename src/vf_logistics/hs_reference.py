"""
HS heading reference, and the prompt block built from it.

Why a whole module for a lookup table
-------------------------------------
Because the classifier's failure mode turned out to be factual rather than
procedural. Nemotron Nano reasons its way through the classification method
correctly and then confabulates the heading contents -- and it confabulates in
the direction of whatever heading it was told the exporter declared. Handed
"electronic integrated circuits" under a declared 8543, it replied that 8543
covers integrated circuits. It does not; 8542 does. That is anchoring on the
declarant's own claim, which is precisely the claim under test.

A reasoning prompt cannot repair that. The heading definitions have to be in
front of the model, which is what this module puts there.

No retrieval, on purpose
------------------------
`reference_block()` emits every heading in the file rather than selecting
candidates for the declared code. That is a deliberate choice about measurement
integrity: any selection rule is a place where knowledge of the right answer can
leak into the prompt, and a reviewer would be right to suspect it. Emitting the
whole table removes the question. It costs roughly 1.4k prompt tokens, which at
Nano rates is a fraction of a cent per call.

It only works because the table is 25 headings. A production table spanning the
full nomenclature would need retrieval, and would then need the retrieval itself
audited for leakage. That is a real limitation and is recorded in
data/hs_reference.yaml rather than left for someone to discover.
"""

from __future__ import annotations

import functools
import pathlib
from typing import Any

import yaml

REFERENCE_FILE = pathlib.Path(__file__).resolve().parents[2] / "data" / "hs_reference.yaml"


@functools.lru_cache(maxsize=1)
def load() -> dict[str, Any]:
    with open(REFERENCE_FILE, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@functools.lru_cache(maxsize=1)
def by_heading() -> dict[str, dict[str, Any]]:
    return {h["hs"]: h for h in load()["headings"]}


def lookup(hs: str | None) -> dict[str, Any] | None:
    """Heading record for a code, tolerant of 6- and 10-digit input."""
    if not hs:
        return None
    digits = "".join(ch for ch in str(hs) if ch.isdigit())
    return by_heading().get(digits[:4])


def is_dual_use(hs: str | None) -> bool:
    rec = lookup(hs)
    return bool(rec and rec.get("dual_use"))


def is_residual(hs: str | None) -> bool:
    rec = lookup(hs)
    return bool(rec and rec.get("residual"))


def control_basis(hs: str | None) -> str | None:
    rec = lookup(hs)
    return (rec or {}).get("control_basis")


def _clean(text: str) -> str:
    """Collapse the YAML block scalars into single lines for the prompt."""
    return " ".join(str(text).split())


@functools.lru_cache(maxsize=4)
def reference_block(include_excludes: bool = True) -> str:
    """
    The nomenclature extract, as a prompt fragment.

    Residual headings are marked inline rather than in a separate list, because
    the marker is what stops the model parking controlled goods in one and the
    model has to see it at the moment it reads the heading.

    `include_excludes=False` is the honest headline configuration, and the reason
    it exists is worth stating plainly. The `excludes` notes in the YAML were
    written by someone who had already read data/hs_pairs.yaml, and between them
    they name all fifteen substitutions the test set is built from. A 100% score
    with those notes present cannot be distinguished from having been told the
    answers, however the model's own reasoning reads. Dropping them leaves only
    `covers` -- which heading holds which goods, a published fact about the
    nomenclature that a real deployment has for every heading -- plus the
    residual markers and the interpretative principles. Nothing in that subset
    points at a particular pair.

    Report the strict number as the result. The permissive one measures the
    ceiling, not the capability.
    """
    data = load()
    lines = [
        "\n\nHS heading reference. This is the nomenclature extract for the goods"
        " you will see. Use it instead of recalling heading contents from memory,"
        " and do not assume the declared heading covers the goods merely because"
        " it was declared -- checking that claim is the whole task.\n",
        "\nInterpretative principles:\n",
    ]
    for p in data["interpretative_principles"]:
        lines.append(f"  - {_clean(p['rule'])}\n")

    lines.append("\nHeadings:\n")
    for h in data["headings"]:
        tag = (" [RESIDUAL -- last resort only: before using this heading, read back"
               " over the other headings in this chapter and check whether one of them"
               " names these goods; if one does, that heading wins]") if h.get("residual") else ""
        dual = " [DUAL-USE]" if h.get("dual_use") else ""
        lines.append(f"\n  {h['hs']}{dual}{tag}\n    {_clean(h['covers'])}\n")
        if include_excludes:
            for ex in h.get("excludes") or []:
                lines.append(f"    not {ex['hs']}: {_clean(ex['why'])}\n")

    return "".join(lines)


def coverage_report() -> dict[str, Any]:
    """
    Check the table against the headings the rest of the system knows about.

    A reference that silently stopped covering a heading in
    verifier.DUAL_USE_HS_PREFIXES would leave a blind spot inside the component
    written to close a blind spot, so this is asserted in the test suite rather
    than trusted.
    """
    from vf_logistics import verifier

    table = by_heading()
    rules = set(verifier.DUAL_USE_HS_PREFIXES)
    marked = {hs for hs, rec in table.items() if rec.get("dual_use")}

    return {
        "headings": len(table),
        "chapters": sorted({rec["chapter"] for rec in table.values()}),
        "dual_use_in_rules": sorted(rules),
        "dual_use_in_reference": sorted(marked),
        "missing_from_reference": sorted(rules - set(table)),
        "rules_heading_not_marked_dual_use": sorted(rules - marked),
        "marked_but_not_in_rules": sorted(marked - rules),
        "residual_headings": sorted(hs for hs, rec in table.items() if rec.get("residual")),
    }
