#!/usr/bin/env python3
"""
Attribute the benchmark's false positives to the findings that caused them.

    python scripts/run_massive_benchmark.py --arm rules --split dev --out artifacts/dev.json
    python scripts/analyse_false_positives.py artifacts/dev_cases.json

Reads the per-case rows run_massive_benchmark.py writes beside its report (every
row carries each finding's code, floor and severity) and answers the three
questions a threshold change has to be argued from:

  1. Which finding set the floor on each clean shipment that was held?
  2. Which clean shipments were held by ONE finding alone -- the ones a change to
     that finding would release?
  3. How much attack recall rests on each finding alone -- what the same change
     would cost?

A finding that is (2)-heavy and (3)-light is a candidate. One that is (3)-heavy
is not, however many clean shipments it holds. This is the analysis behind the
FREIGHT_ABOVE_LANE_TYPICAL and SHIPPER_THIN_HISTORY observations in verifier.py;
run it on the dev split only, and report the result on holdout.
"""

from __future__ import annotations

import collections
import json
import pathlib
import sys

REVIEW_THRESHOLD = 40


def main(path: str) -> int:
    rows = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if not rows or "findings" not in rows[0]:
        print("These rows carry no per-finding detail; rerun run_massive_benchmark.py.")
        return 2

    clean = [r for r in rows if not r["expected_flagged"]]
    held = [r for r in clean if r["flagged"]]
    attacks = [r for r in rows if r["expected_flagged"]]
    splits = sorted({r.get("split", "?") for r in rows})
    print(f"{path}: split {', '.join(splits)}; {len(clean)} clean, {len(held)} held "
          f"({len(held) / max(1, len(clean)):.1%}); {len(attacks)} attacks\n")

    def scoring(r):
        return [f for f in r["findings"] if f["floor"] >= REVIEW_THRESHOLD]

    top = collections.Counter()
    for r in held:
        found = scoring(r)
        corroborated = sum(f["severity"] in ("HIGH", "CRITICAL") for f in r["findings"]) >= 2
        name = max(found, key=lambda f: f["floor"])["code"] if found else "(corroboration only)"
        top[name + (" +corroboration" if corroborated else "")] += 1

    sole_clean = collections.Counter(
        scoring(r)[0]["code"] for r in held if len(scoring(r)) == 1
    )
    sole_attack = collections.Counter(
        scoring(r)[0]["code"] for r in attacks if r["flagged"] and len(scoring(r)) == 1
    )

    print("1. finding that set the floor on each held clean shipment")
    for code, n in top.most_common():
        print(f"   {n:4}  {code}")

    print("\n2. clean shipments held by one finding alone (released if it stopped scoring)")
    print("3. attacks caught by that finding alone (lost if it stopped scoring)")
    print(f"   {'finding':32}{'clean held':>12}{'attacks':>10}")
    for code in sorted(set(sole_clean) | set(sole_attack),
                       key=lambda c: -(sole_clean[c] - sole_attack[c])):
        print(f"   {code:32}{sole_clean[code]:>12}{sole_attack[code]:>10}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
