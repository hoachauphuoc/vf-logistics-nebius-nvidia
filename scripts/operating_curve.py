#!/usr/bin/env python3
"""
The rules arm at every review threshold, not only at the one in use.

    python scripts/operating_curve.py                  # writes data/operating_curve/rules.json

Runs the rules-only benchmark (run_massive_benchmark.py --arm rules: no model
calls, no cost, a few seconds) on the dev and the holdout split, then re-scores
the same per-case risk floors at every threshold that changes the answer, and
writes the aggregate that GET /api/v1/evaluation serves.

Why a curve: one recall and one false-alarm rate say how the current threshold
does, not what moving it would buy. The question a reviewer's lead actually asks
-- how many fewer honest shipments if we accept missing a few more frauds -- is
answered by the neighbouring points, and at 0.2% fraud the answer is in reviewer
hours (held per real case), not in corpus precision.

Floors take a handful of values, because each finding carries a fixed floor, so
every threshold between two adjacent floors holds exactly the same shipments.
The curve therefore has one point per distinct floor seen on either split, and
each point names the range of thresholds it stands for. A shipment is held when
its floor is at or above the threshold; an auto-reject has a floor of 100, so
that covers it too, and the run refuses to write if the benchmark's own
`flagged` column ever disagrees.

Only counts and rates are written. The per-case rows carry the corpus's labels
next to every shipment and stay in a temporary directory.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vf_logistics.evaluation import PREVALENCES, workload  # noqa: E402

BENCHMARK = ROOT / "scripts" / "run_massive_benchmark.py"
OUT_FILE = ROOT / "data" / "operating_curve" / "rules.json"
SPLITS = ("dev", "holdout")


def cut_points(rows_by_split: dict[str, list[dict[str, Any]]]) -> list[int]:
    """Every distinct non-zero floor on any split: the thresholds that change something."""
    floors = {int(r["risk_floor"]) for rows in rows_by_split.values() for r in rows}
    return sorted(f for f in floors if f > 0)


def sweep(
    rows: list[dict[str, Any]],
    cuts: list[int],
    review_threshold: int,
    prevalence: float = PREVALENCES[0],
) -> list[dict[str, Any]]:
    """One point per cut: the counts and rates if shipments at or above it were held."""
    points = []
    below = 0
    for cut in cuts:
        held = [r["risk_floor"] >= cut for r in rows]
        tp = sum(1 for r, h in zip(rows, held) if r["expected_flagged"] and h)
        fn = sum(1 for r, h in zip(rows, held) if r["expected_flagged"] and not h)
        fp = sum(1 for r, h in zip(rows, held) if not r["expected_flagged"] and h)
        tn = sum(1 for r, h in zip(rows, held) if not r["expected_flagged"] and not h)
        rates = {
            "precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "recall": round(tp / (tp + fn), 4) if tp + fn else None,
            "false_positive_rate": round(fp / (fp + tn), 4) if fp + tn else None,
        }
        queue = workload(rates, (prevalence,))[0]
        points.append({
            "threshold": cut,
            # Integer floors, so any threshold in this range holds the same shipments.
            "thresholds": [below + 1, cut],
            "current": below < review_threshold <= cut,
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            **rates,
            "held_per_1000": queue["held_per_1000"],
            "held_per_true_case": queue["held_per_true_case"],
        })
        below = cut
    return points


def run_rules(split: str, workdir: pathlib.Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The benchmark's aggregate report and per-case rows for one split."""
    out = workdir / f"rules_{split}.json"
    # Nothing on the rules path writes to a store. If that ever changes, the run
    # gets the in-process one rather than whatever Firestore the shell points at.
    env = {**os.environ, "STORE_BACKEND": "memory"}
    proc = subprocess.run(
        [sys.executable, str(BENCHMARK), "--arm", "rules", "--split", split, "--out", str(out)],
        env=env, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout + proc.stderr)
        raise SystemExit(f"run_massive_benchmark.py --split {split} failed ({proc.returncode})")
    report = json.loads(out.read_text(encoding="utf-8"))
    rows = json.loads(out.with_name(out.stem + "_cases.json").read_text(encoding="utf-8"))
    return report, rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(OUT_FILE))
    args = ap.parse_args()

    sys.path.insert(0, str(ROOT / "scripts"))
    from run_massive_benchmark import REVIEW_THRESHOLD

    reports: dict[str, dict[str, Any]] = {}
    rows_by_split: dict[str, list[dict[str, Any]]] = {}
    with tempfile.TemporaryDirectory(prefix="operating_curve_") as tmp:
        for split in SPLITS:
            reports[split], rows_by_split[split] = run_rules(split, pathlib.Path(tmp))

    for split, rows in rows_by_split.items():
        disagree = [r["case_id"] for r in rows if r["flagged"] != (r["risk_floor"] >= REVIEW_THRESHOLD)]
        if disagree:
            print(f"REFUSING: on {split}, {len(disagree)} cases are flagged other than by "
                  f"floor >= {REVIEW_THRESHOLD} (e.g. {disagree[0]}), so a sweep over the "
                  "floor would not describe what the benchmark measures.")
            return 2

    cuts = cut_points(rows_by_split)
    curve = {
        "arm": "rules",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "generated_by": "scripts/operating_curve.py",
        "review_threshold": REVIEW_THRESHOLD,
        "prevalence": PREVALENCES[0],
        "corpus": reports["holdout"].get("corpus"),
        "sanctions_index": reports["holdout"].get("sanctions_index"),
        "split_method": reports["holdout"].get("split_method"),
        "splits": {
            split: {
                "cases_run": len(rows),
                "attacks": sum(1 for r in rows if r["expected_flagged"]),
                "clean": sum(1 for r in rows if not r["expected_flagged"]),
                "points": sweep(rows, cuts, REVIEW_THRESHOLD),
            }
            for split, rows in rows_by_split.items()
        },
    }

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(curve, indent=2) + "\n", encoding="utf-8")

    def pct(v: float | None) -> str:
        return "-" if v is None else f"{v:.1%}"

    print(f"{'hold at floor >=':>18}  {'split':8}{'recall':>8}{'false alarms':>14}"
          f"{'precision':>11}{'held per real case @0.2%':>26}")
    for split in SPLITS:
        for p in curve["splits"][split]["points"]:
            mark = "  <- current" if p["current"] else ""
            print(f"{p['threshold']:>18}  {split:8}{pct(p['recall']):>8}"
                  f"{pct(p['false_positive_rate']):>14}{pct(p['precision']):>11}"
                  f"{str(p['held_per_true_case'] or '-'):>26}{mark}")
    try:
        shown = out.resolve().relative_to(ROOT)
    except ValueError:
        shown = out
    print(f"\nwrote {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
