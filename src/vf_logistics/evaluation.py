"""
The measured results, served by the service that produced them.

GET /api/v1/evaluation reads two directories committed with the code:

  data/benchmark_results/   the whole pipeline on the synthetic corpus, one
                            aggregate report per (arm, split, verifier version),
                            written by scripts/run_massive_benchmark.py
  data/eval_results/        the HS classifier on its own, one file per arm and
                            test set, written by scripts/eval_hs.py

Why serve them at all: a README number is a claim about a moment. These files are
the reports themselves, versioned with the code that produced them, so the console
can show a judge exactly what was measured, on which split, and at what cost --
including the unflattering parts (the synthetic corpus, the recall the tuning gave
up) that a headline figure leaves out.

Only aggregates are served. The per-case rows stay in artifacts/ (gitignored):
they are large, and they carry the corpus's labels next to every shipment.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

DATA_DIR = pathlib.Path(__file__).resolve().parents[2] / "data"
BENCHMARK_DIR = DATA_DIR / "benchmark_results"
HS_EVAL_DIR = DATA_DIR / "eval_results"

# The fields of a benchmark report worth showing, in the order a reader needs
# them. Everything else in the report (latency percentiles, per-verdict counts)
# stays in the file.
_PIPELINE_FIELDS = (
    "arm", "split", "split_method", "generated_at", "cases_run", "verifier",
    "detection", "rules_only_baseline", "model_contribution", "by_attack_type",
    "false_positives", "hs_classification", "zero_day", "cost", "notes",
)

# HS classifier arms in the order the harness reports them.
_HS_ARM_ORDER = {
    "rules": 0, "base": 1, "few_shot": 2, "cot_zero": 3, "cot": 4,
    "cot_strict": 5, "cot_ref": 6, "cot_full": 7, "teacher": 9, "teacher_cot": 10,
}


def _read(path: pathlib.Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def pipeline_results(directory: pathlib.Path = BENCHMARK_DIR) -> list[dict[str, Any]]:
    """One entry per committed benchmark report, trimmed to the shown fields."""
    out = []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        report = _read(path)
        if not report or "detection" not in report:
            continue
        entry = {key: report[key] for key in _PIPELINE_FIELDS if key in report}
        entry["id"] = path.stem
        out.append(entry)
    return out


def hs_results(directory: pathlib.Path = HS_EVAL_DIR) -> dict[str, list[dict[str, Any]]]:
    """HS classifier metrics by test set, without the per-case rows."""
    sets: dict[str, list[dict[str, Any]]] = {"pairs": [], "holdout": []}
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        data = _read(path)
        metrics = (data or {}).get("metrics")
        if not isinstance(metrics, dict):
            continue
        which = "holdout" if path.stem.startswith("holdout_") else "pairs"
        sets[which].append({**metrics, "measured_at": (data or {}).get("at")})
    for rows in sets.values():
        rows.sort(key=lambda m: _HS_ARM_ORDER.get(str(m.get("arm")), 99))
    return sets


def summary() -> dict[str, Any]:
    """The GET /api/v1/evaluation payload."""
    return {
        "pipeline": pipeline_results(),
        "hs_classifier": hs_results(),
        "caveats": [
            "The pipeline corpus is synthetic (data/synthetic_test_cases.json, "
            "1,000 cases, fixed seed). No real customer traffic has been measured.",
            "The corpus is split in two by a hash of each case id. Thresholds were "
            "chosen on the dev half; the holdout half is what is reported.",
            "Real Tavily searches are limited to a small subset of a full-arm run "
            "(the free tier is 1,000 credits a month); the rest use an empty stub, "
            "so adverse-media detection is measured on that subset only.",
            "The HS classifier test sets are small (30 and 24 cases), so a single "
            "case moves recall by several points.",
        ],
    }
