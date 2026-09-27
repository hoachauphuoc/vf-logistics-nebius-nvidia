#!/usr/bin/env python3
"""
Publish one benchmark report into data/benchmark_results/, where the API serves it.

    python scripts/publish_benchmark.py artifacts/bench_rules_holdout_tuned.json \
        rules_holdout --verifier "after false-positive tuning" \
        --note "Deterministic layer only; free to rerun."

Copies the AGGREGATE report written by run_massive_benchmark.py -- never the
*_cases.json rows beside it -- and stamps it with which verifier produced it, so
a before/after pair is told apart by a field rather than by a file name. The
report is otherwise unchanged: what the console shows is what the harness wrote.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "benchmark_results"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("report", help="an aggregate report from run_massive_benchmark.py")
    ap.add_argument("id", help="file stem under data/benchmark_results/")
    ap.add_argument("--verifier", required=True,
                    help="which verifier produced it, e.g. 'before false-positive tuning'")
    ap.add_argument("--note", action="append", default=[],
                    help="a caveat to show beside the numbers (repeatable)")
    args = ap.parse_args()

    source = pathlib.Path(args.report)
    if source.name.endswith("_cases.json"):
        print("That is the per-case file; publish the aggregate report beside it.")
        return 2
    if not re.fullmatch(r"[a-z0-9_]+", args.id):
        print("id must be lowercase letters, digits and underscores")
        return 2

    report = json.loads(source.read_text(encoding="utf-8"))
    if "detection" not in report:
        print(f"{source} is not a run_massive_benchmark.py report")
        return 2

    report["verifier"] = args.verifier
    report["notes"] = args.note
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUT_DIR / f"{args.id}.json"
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    d = report["detection"]
    print(f"wrote {target.relative_to(ROOT)}: {report['arm']} arm, "
          f"{report.get('split', 'all')} split, {report['cases_run']} cases, "
          f"precision {d['precision']:.3f} recall {d['recall']:.3f} "
          f"FPR {d['false_positive_rate']:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
