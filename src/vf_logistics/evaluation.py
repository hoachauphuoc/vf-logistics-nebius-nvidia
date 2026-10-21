"""
The measured results, served by the service that produced them.

GET /api/v1/evaluation reads two directories committed with the code:

  data/benchmark_results/   the whole pipeline on the synthetic corpus, one
                            aggregate report per (arm, split, verifier version),
                            written by scripts/run_massive_benchmark.py
  data/eval_results/        the HS classifier on its own, one file per arm and
                            test set, written by scripts/eval_hs.py
  data/operating_curve/     the rules arm at every review threshold, written by
                            scripts/operating_curve.py
  data/model_comparison/    the model choices tested head to head, written by
                            scripts/compare_fraud_models.py and
                            scripts/compare_debate_models.py --corpus

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
import math
import pathlib
from statistics import NormalDist
from typing import Any

DATA_DIR = pathlib.Path(__file__).resolve().parents[2] / "data"
BENCHMARK_DIR = DATA_DIR / "benchmark_results"
HS_EVAL_DIR = DATA_DIR / "eval_results"
CURVE_DIR = DATA_DIR / "operating_curve"
MODEL_COMPARISON_DIR = DATA_DIR / "model_comparison"

# The fields of a benchmark report worth showing, in the order a reader needs
# them. Everything else in the report (latency percentiles, per-verdict counts)
# stays in the file.
_PIPELINE_FIELDS = (
    "arm", "split", "split_method", "generated_at", "cases_run", "verifier",
    "detection", "rules_only_baseline", "model_contribution", "by_attack_type",
    "false_positives", "hs_classification", "zero_day", "cost", "notes",
    "corpus", "sanctions_index", "pairs",
)

# Fraud prevalence the workload figures are computed at.
#
# 0.2% is the measured rate on the corridor this was built for: Vietnam Customs
# found a violation in 29,849 of 16.84 million declarations in 2024, 0.18%
# (customs.gov.vn, 2 Jan 2025). Declarations, not cases: the same release counts
# 18,558 violation files. 1% and 2% bracket a forwarder whose book skews to the higher-risk lanes. A
# corpus is 20-50% fraud by construction, so precision measured on it says
# nothing about what a reviewer's queue looks like; these do.
PREVALENCES = (0.002, 0.01, 0.02)

# Two-sided 95%.
Z_95 = NormalDist().inv_cdf(0.975)


def wilson(successes: int, n: int, z: float = Z_95) -> tuple[float, float] | None:
    """
    The Wilson score interval for `successes` out of `n`; None when n is 0.

    Wilson rather than the textbook p +/- z*sqrt(p(1-p)/n) because these counts
    are small and often at the edge -- 11 of 12, 0 of 12, 15 of 15. The textbook
    interval collapses to a point at 0 or n, so 15 of 15 would read as 100% with
    no uncertainty at all, and near the edges it spills past 0 and 1.

    The bounds are rounded outward to 4 dp, not to the nearest: the console rounds
    them outward again to whole percent, and a low of 0.299993 rounded up to 0.3
    would show as 30 where the interval reaches 29.
    """
    if n <= 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z / denom * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    low = math.floor(max(0.0, centre - half) * 10_000) / 10_000
    high = math.ceil(min(1.0, centre + half) * 10_000) / 10_000
    return low, high


# Each rate as (the count it is the share of, the count that completes its
# denominator).
_RATES = {
    "precision": ("tp", "fp"),
    "recall": ("tp", "fn"),
    "false_positive_rate": ("fp", "tn"),
}


def _count(counts: dict[str, Any], key: str) -> int | None:
    value = counts.get(key)
    # bool is an int to Python; True here is a malformed report, not a count of one.
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def intervals(counts: dict[str, Any]) -> dict[str, dict[str, Any] | None]:
    """
    95% Wilson intervals for precision, recall and false-positive rate.

    Built from the confusion counts a report carries beside its rates, never from
    the rates: 0.9167 is 11 of 12 or 1,100 of 1,200, and the interval is the whole
    difference between them. A rate whose counts are missing, or whose denominator
    is zero, is None rather than an interval on a guessed n.
    """
    out: dict[str, dict[str, Any] | None] = {}
    for rate, (hit, other) in _RATES.items():
        out[rate] = None
        k, rest = _count(counts, hit), _count(counts, other)
        if k is None or rest is None:
            continue
        bounds = wilson(k, k + rest)
        if bounds:
            out[rate] = {"low": bounds[0], "high": bounds[1], "successes": k, "n": k + rest}
    return out


def _queue(p: float, recall: float, fpr: float) -> dict[str, Any]:
    true_held = 1000 * p * recall
    held = true_held + 1000 * (1 - p) * fpr
    return {
        "held_per_1000": round(held, 1),
        "precision_at_prevalence": round(true_held / held, 4) if held else 0.0,
        "held_per_true_case": round(held / true_held, 1) if true_held else None,
    }


def workload(detection: dict[str, Any], prevalences: tuple[float, ...] = PREVALENCES) -> list[dict[str, Any]]:
    """
    What a reviewer sees per 1,000 shipments, at each prevalence.

    held = p * recall + (1 - p) * false_positive_rate, and the share of the held
    that are real is the precision at that prevalence rather than the corpus's.
    The rates are the corpus's, so the result inherits its limits -- a small n
    above all -- and is labelled with them where it is shown.

    best_case and worst_case redo held_per_true_case and precision_at_prevalence
    with recall and the false-alarm rate at the favourable and the unfavourable
    ends of their 95% intervals at once. That is not itself a 95% interval: the
    two rates are measured on disjoint cases, so both sit inside their intervals
    with probability about 0.95 x 0.95, and whenever they do the true figure lies
    between the two ends, because each figure improves with recall and worsens
    with false alarms. held_per_1000 rises with both, so these ends do not bound
    it and it is left out of them.
    Both are None when the report carries no counts to build intervals from.
    """
    recall = float(detection.get("recall") or 0.0)
    fpr = float(detection.get("false_positive_rate") or 0.0)
    bounds = intervals(detection)
    r_iv, f_iv = bounds["recall"], bounds["false_positive_rate"]
    ends = {
        "best_case": (r_iv["high"], f_iv["low"]),
        "worst_case": (r_iv["low"], f_iv["high"]),
    } if r_iv and f_iv else {}
    out = []
    for p in prevalences:
        row = {
            "prevalence": p,
            **_queue(p, recall, fpr),
            "true_per_1000": round(1000 * p * recall, 2),
            "missed_per_1000": round(1000 * p * (1 - recall), 2),
        }
        for name in ("best_case", "worst_case"):
            row[name] = None
            if name in ends:
                r, f = ends[name]
                queue = _queue(p, r, f)
                row[name] = {
                    "recall": r,
                    "false_positive_rate": f,
                    "precision_at_prevalence": queue["precision_at_prevalence"],
                    "held_per_true_case": queue["held_per_true_case"],
                }
        out.append(row)
    return out

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
        entry["intervals"] = intervals(report["detection"])
        entry["workload"] = workload(report["detection"])
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
        sets[which].append({
            **metrics, "measured_at": (data or {}).get("at"), "intervals": intervals(metrics),
        })
    for rows in sets.values():
        rows.sort(key=lambda m: _HS_ARM_ORDER.get(str(m.get("arm")), 99))
    return sets


def operating_curves(directory: pathlib.Path = CURVE_DIR) -> dict[str, dict[str, Any]]:
    """
    Threshold sweeps by arm, each point with its intervals and workload range.

    The range matters most at the strict end of a curve, where no clean case was
    held: a false-alarm rate of 0 of 86 puts the point estimate at one shipment
    held per real one, and only the interval says that is a small sample, not a
    perfect screen. A file without a "splits" block is not a sweep and is
    skipped, as a benchmark report without "detection" is.
    """
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        curve = _read(path)
        if not curve or not isinstance(curve.get("splits"), dict):
            continue
        prevalence = float(curve.get("prevalence") or PREVALENCES[0])
        for split in curve["splits"].values():
            for point in (split.get("points") or []) if isinstance(split, dict) else []:
                if isinstance(point, dict):
                    point["intervals"] = intervals(point)
                    queue = workload(point, (prevalence,))[0]
                    point["best_case"], point["worst_case"] = queue["best_case"], queue["worst_case"]
        out[path.stem] = curve
    return out


def model_comparisons(directory: pathlib.Path = MODEL_COMPARISON_DIR) -> dict[str, dict[str, Any]]:
    """
    Head-to-head model comparisons, keyed by file name.

    Each report carries its own counts and 95% Wilson intervals (the scripts compute them
    with wilson() above), so they are served as written. A file without a `kind` and a
    `results` block is not a comparison and is skipped, as are unreadable ones.
    """
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        report = _read(path)
        if report and report.get("kind") and isinstance(report.get("results"), dict):
            out[path.stem] = report
    return out


def summary() -> dict[str, Any]:
    """The GET /api/v1/evaluation payload."""
    return {
        "pipeline": pipeline_results(),
        "hs_classifier": hs_results(),
        "operating_curve": operating_curves(),
        "model_comparison": model_comparisons(),
        "caveats": [
            "The pipeline corpus is synthetic (data/synthetic_test_cases.json, "
            "1,000 cases, fixed seed). No real customer traffic has been measured.",
            "The public-case set (data/public_cases.json) is 19 enforcement cases from "
            "BIS, OFAC, US Commerce, EPPO and OLAF, each rebuilt as one shipment and "
            "paired with the honest trade it imitated. Real typologies, small n, and "
            "screened against today's lists, which is retrospective.",
            "Workload is computed at 0.2% fraud, the 2024 rate on the Vietnam corridor "
            "(a violation found in 29,849 of 16.84 million declarations), and at 1% and 2%.",
            "The corpus is split in two by a hash of each case id. Thresholds were "
            "chosen on the dev half; the holdout half is what is reported.",
            "Real Tavily searches are limited to a small subset of a full-arm run "
            "(the free tier is 1,000 credits a month); the rest use an empty stub, "
            "so adverse-media detection is measured on that subset only.",
            "The HS classifier test sets are small (30 and 24 cases), so a single "
            "case moves recall by several points.",
            "The model comparisons use the same synthetic corpus: 179 cases the rules "
            "scored 0 (52 of them fraud) for the fraud models, and 46 disputed cases for "
            "the debate. The debate's auditor is shown the rules' findings and every honest "
            "case in that sample was one the rules had held, so a DISAGREE largely tracks "
            "agreement with the rules.",
            "Ranges in brackets are 95% Wilson score intervals on the counts behind "
            "each rate. A workload range puts recall and the false-alarm rate at the "
            "ends of their intervals at once, the favourable ends and then the "
            "unfavourable ones.",
        ],
    }
