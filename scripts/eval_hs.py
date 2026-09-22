"""
Measure whether a model catches HS misclassification that the rules cannot.

Why this exists and why it does not reuse the harnesses already in the repo:
scripts/test_documents.py and tests/verify_e2e.ps1 both grade the terminal case
state, and test_documents.py says so in its own comments -- "all but one of these
is decided by a deterministic floor in verifier.py or a gate in governance.py,
not by where the fraud model happens to land." Terminal state is dominated by the
floors by design, so those harnesses would report a fine-tuned model as
indistinguishable from the base model even if it were far better or far worse.

This harness therefore grades the agent's own output, and nothing downstream of
it.

Usage:
    python scripts/eval_hs.py baseline            # rules arm only, no API calls, free
    python scripts/eval_hs.py run --arm base
    python scripts/eval_hs.py run --arm few_shot
    python scripts/eval_hs.py run --arm teacher
    python scripts/eval_hs.py report
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys
import time
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import yaml  # noqa: E402

from vf_logistics import verifier  # noqa: E402
from vf_logistics.agents.hs_classifier_agent import classify_hs, interpret  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAIRS_FILE = ROOT / "data" / "hs_pairs.yaml"
HOLDOUT_FILE = ROOT / "data" / "hs_holdout.yaml"
RESULTS_DIR = ROOT / "data" / "eval_results"

SETS = {"pairs": PAIRS_FILE, "holdout": HOLDOUT_FILE}

NANO = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
SUPER = "nvidia/nemotron-3-super-120b-a12b"

ARMS = {
    # (model, mode). The teacher arm is the accuracy ceiling we are trying to
    # reach at Nano cost, not a candidate for production -- it is ~10x the price.
    #
    # cot_zero carries no exemplars, so it is the one arm that cannot be accused
    # of leaking the answer from the pair file the test set is built from. Read it
    # first. cot adds exemplars under leave-one-out holdout; the gap between the
    # two is what the examples are worth on top of the method.
    "base": (NANO, "base"),
    "few_shot": (NANO, "few_shot"),
    "cot_zero": (NANO, "cot_zero"),
    "cot": (NANO, "cot"),
    "cot_ref": (NANO, "cot_ref"),
    "cot_strict": (NANO, "cot_strict"),
    "cot_full": (NANO, "cot_full"),
    "teacher": (SUPER, "base"),
    "teacher_cot": (SUPER, "cot_zero"),
}


# --------------------------------------------------------------------------
# Test set
# --------------------------------------------------------------------------

def load_pairs(which: str = "pairs") -> dict[str, Any]:
    with open(SETS[which], encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def holdout_is_disjoint() -> dict[str, Any]:
    """
    Prove the holdout substitutions are unseen, rather than asserting it.

    Checks the (controlled <- declared) combinations against both places an
    answer could have leaked from: the pair file the method was developed on, and
    the `excludes` notes in the reference, which were written with those pairs in
    view. A non-empty overlap here invalidates any number measured on the holdout,
    so it is checked in code and in the test suite instead of being remembered.
    """
    def combos(data: dict[str, Any]) -> set[tuple[str, str]]:
        return {(p["controlled_hs"], p["benign_hs"]) for p in data["pairs"]}

    seen = combos(load_pairs("pairs"))
    held = combos(load_pairs("holdout"))

    sys.path.insert(0, str(ROOT / "src"))
    from vf_logistics import hs_reference

    # An excludes note on heading X pointing at Y encodes the substitution
    # "Y declared as X", which is the same shape as a pair.
    noted = {
        (ex["hs"], h["hs"])
        for h in hs_reference.load()["headings"]
        for ex in (h.get("excludes") or [])
    }

    return {
        "holdout_combos": len(held),
        "overlap_with_pairs": sorted(held & seen),
        "overlap_with_reference_excludes": sorted(held & noted),
        "declared_headings_that_are_dual_use": sorted(
            d for _, d in held if hs_reference.is_dual_use(d)
        ),
    }


def build_cases(which: str = "pairs") -> list[dict[str, Any]]:
    """
    One evasive case per pair, one honest case per benign control.

    The evasive case describes the controlled goods but declares the benign
    heading -- exactly the substitution the rules cannot see. The benign controls
    are the other half of the measurement: without them a model that answers
    "inconsistent" to everything would score perfect recall.

    `pair_index` is carried through so the cot arm can hold out its own pair's
    exemplar. Honest cases have no pair, so they hold out by declared heading
    instead -- see hs_cot.build_exemplars().

    The holdout set supplies `cargo_description` per pair: realistic commercial
    text with the obfuscation applied. The original set has no such field and
    falls back to `controlled_goods`, which is the bare nomenclature wording and
    therefore a much easier input. The two sets are not interchangeable and their
    numbers should not be compared as though they were.
    """
    data = load_pairs(which)
    cases: list[dict[str, Any]] = []

    for i, p in enumerate(data["pairs"]):
        cases.append({
            "case_id": f"EVADE-{i:03d}",
            "pair_index": i,
            "cargo_description": p.get("cargo_description") or p["controlled_goods"],
            "declared_hs": p["benign_hs"],
            "expected_verdict": "inconsistent",
            "expected_hs": p["controlled_hs"],
            "control_basis": p["control_basis"],
        })

    for i, b in enumerate(data["benign_controls"]):
        cases.append({
            "case_id": f"HONEST-{i:03d}",
            "pair_index": None,
            "cargo_description": b["cargo_description"],
            "declared_hs": b["hs_code"],
            "expected_verdict": "consistent",
            "expected_hs": None,
            "control_basis": None,
        })

    return cases


# --------------------------------------------------------------------------
# Arms
# --------------------------------------------------------------------------

def run_rules_arm(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    What the deterministic checks alone produce. No API calls, no cost.

    Included because it is the honest floor to measure against. It is expected to
    score zero recall -- check_hs_code only sees the declared heading, and every
    declared heading in the evasive cases is benign by construction. Asserting
    that in code is better than asserting it in a slide.
    """
    out = []
    for c in cases:
        findings = verifier.check_hs_code({"hs_code": c["declared_hs"]})
        flagged = any(f.get("code") == "DUAL_USE_HS_CODE" for f in findings)
        out.append({
            **c,
            "arm": "rules",
            "model": None,
            "verdict": "inconsistent" if flagged else "consistent",
            "suggested_hs": None,
            "confidence": 1.0 if flagged else 0.0,
            "reasoning": "deterministic dual-use prefix match" if flagged
                         else "declared heading is not in DUAL_USE_HS_PREFIXES",
            "latency_ms": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
        })
    return out


async def run_model_arm(cases: list[dict[str, Any]], arm: str) -> list[dict[str, Any]]:
    model, mode = ARMS[arm]
    from vf_logistics import config as model_config

    out = []
    for n, c in enumerate(cases, 1):
        try:
            resp = await classify_hs(
                c["cargo_description"], c["declared_hs"],
                model=model, mode=mode, temperature=0.0,
                # Leakage controls. An evasive case never sees an exemplar from
                # its own pair; an honest case never sees one declaring the same
                # heading. Both are no-ops outside the cot arm.
                exclude_pair=c.get("pair_index"),
                exclude_heading=c["declared_hs"] if c.get("pair_index") is None else None,
            )
            verdict = interpret(resp)
            pricing = model_config.pricing_for(model)
            cost = (
                resp.get("input_tokens", 0) * pricing["input"]
                + resp.get("output_tokens", 0) * pricing["output"]
            ) / 1_000_000
            out.append({
                **c, "arm": arm, "model": model, "mode": mode,
                "exemplar_pairs": resp.get("exemplar_pairs"),
                "verdict": verdict["verdict"],
                "suggested_hs": verdict["suggested_hs"],
                "confidence": verdict["confidence"],
                "reasoning": verdict["reasoning"],
                "obfuscation": verdict["obfuscation"],
                "latency_ms": resp.get("latency_ms"),
                "input_tokens": resp.get("input_tokens", 0),
                "output_tokens": resp.get("output_tokens", 0),
                "cost_usd": round(cost, 8),
            })
        except Exception as exc:
            # Recorded as an error rather than dropped. A silently shorter test
            # set inflates every rate computed from it.
            out.append({
                **c, "arm": arm, "model": model, "mode": mode, "verdict": "error",
                "suggested_hs": None, "confidence": 0.0,
                "reasoning": f"{type(exc).__name__}: {exc}",
                "latency_ms": None, "input_tokens": 0, "output_tokens": 0,
                "cost_usd": 0.0,
            })
        print(f"  [{n}/{len(cases)}] {c['case_id']} -> {out[-1]['verdict']}", flush=True)
    return out


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

def score(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Confusion matrix and rates, treating "inconsistent" as the positive class.

    `unknown` and `error` are counted separately and NOT folded into either
    class. Folding them into negatives would flatter a model that fails to answer,
    and folding them into positives would flatter one that crashes.
    """
    tp = fp = tn = fn = unknown = errors = 0
    correct_redirect = 0
    redirect_opportunities = 0

    for r in rows:
        exp, got = r["expected_verdict"], r["verdict"]
        if got == "error":
            errors += 1
            continue
        if got == "unknown":
            unknown += 1
            continue

        if exp == "inconsistent":
            if got == "inconsistent":
                tp += 1
                redirect_opportunities += 1
                if r.get("suggested_hs") == r.get("expected_hs"):
                    correct_redirect += 1
            else:
                fn += 1
        else:
            if got == "consistent":
                tn += 1
            else:
                fp += 1

    graded = tp + fp + tn + fn
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0

    return {
        "arm": rows[0]["arm"] if rows else "?",
        "model": rows[0].get("model") if rows else None,
        "n": len(rows),
        "graded": graded,
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "unknown": unknown, "errors": errors,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "false_positive_rate": round(fpr, 4),
        "correct_redirect": correct_redirect,
        "redirect_opportunities": redirect_opportunities,
        "redirect_accuracy": round(correct_redirect / redirect_opportunities, 4)
                             if redirect_opportunities else 0.0,
        "total_cost_usd": round(sum(r.get("cost_usd") or 0 for r in rows), 8),
        "avg_latency_ms": round(
            sum(r["latency_ms"] for r in rows if r.get("latency_ms")) /
            max(1, sum(1 for r in rows if r.get("latency_ms")))
        ),
    }


def save(rows: list[dict[str, Any]], arm: str, which: str = "pairs") -> pathlib.Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # Holdout results are filed separately. Overwriting a development-set result
    # with a holdout result under the same name would silently mix two
    # populations into one comparison table.
    stem = arm if which == "pairs" else f"holdout_{arm}"
    path = RESULTS_DIR / f"{stem}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"arm": arm, "set": which, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "metrics": score(rows), "rows": rows}, fh, indent=2, ensure_ascii=False)
    return path


def print_metrics(m: dict[str, Any]) -> None:
    print(f"\n  arm              : {m['arm']}  ({m['model'] or 'no model'})")
    print(f"  cases            : {m['n']} ({m['graded']} graded, "
          f"{m['unknown']} unknown, {m['errors']} errors)")
    print(f"  confusion        : tp={m['tp']} fp={m['fp']} tn={m['tn']} fn={m['fn']}")
    print(f"  recall           : {m['recall']:.1%}   <- evasions caught")
    print(f"  precision        : {m['precision']:.1%}")
    print(f"  f1               : {m['f1']:.3f}")
    print(f"  false pos rate   : {m['false_positive_rate']:.1%}   <- honest cargo wrongly flagged")
    print(f"  redirect acc     : {m['redirect_accuracy']:.1%} "
          f"({m['correct_redirect']}/{m['redirect_opportunities']} named the right heading)")
    print(f"  cost             : ${m['total_cost_usd']:.6f}   avg {m['avg_latency_ms']}ms")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("baseline", help="rules arm only, no API calls")
    b.add_argument("--set", dest="which", choices=sorted(SETS), default="pairs")
    r = sub.add_parser("run", help="run a model arm")
    r.add_argument("--arm", choices=sorted(ARMS), required=True)
    r.add_argument("--set", dest="which", choices=sorted(SETS), default="pairs",
                   help="pairs = development set; holdout = unseen substitutions")
    r.add_argument("--limit", type=int, default=0, help="cap cases (smoke test)")
    rep = sub.add_parser("report", help="compare every saved arm")
    rep.add_argument("--set", dest="which", choices=sorted(SETS), default="pairs")
    sub.add_parser("disjoint", help="prove the holdout substitutions are unseen")

    args = ap.parse_args()

    if args.cmd == "disjoint":
        rep = holdout_is_disjoint()
        print(json.dumps(rep, indent=2))
        bad = (rep["overlap_with_pairs"] or rep["overlap_with_reference_excludes"]
               or rep["declared_headings_that_are_dual_use"])
        print("\n  CONTAMINATED" if bad else "\n  clean: no substitution in the holdout was seen"
              " during development, and every declared heading is non-dual-use")
        return 1 if bad else 0

    cases = build_cases(getattr(args, "which", "pairs"))

    if args.cmd == "baseline":
        evade = sum(1 for c in cases if c["expected_verdict"] == "inconsistent")
        print(f"Test set: {len(cases)} cases ({evade} evasive, {len(cases)-evade} honest)")
        rows = run_rules_arm(cases)
        m = score(rows)
        print_metrics(m)
        print(f"\n  saved -> {save(rows, 'rules', getattr(args, 'which', 'pairs'))}")
        if m["recall"] == 0.0:
            print("\n  Rules recall is 0% as predicted. check_hs_code only reads the")
            print("  declared heading, and every evasive case declares a benign one.")
            print("  This is the gap a model has to close.")
        return 0

    if args.cmd == "run":
        if not os.getenv("NEBIUS_API_KEY"):
            print("NEBIUS_API_KEY is not set; this arm calls the API.", file=sys.stderr)
            return 2
        if args.limit:
            cases = cases[:args.limit]
        model, mode = ARMS[args.arm]
        print(f"Arm '{args.arm}': {model} (mode={mode}), set={args.which}, "
              f"{len(cases)} cases")
        rows = asyncio.run(run_model_arm(cases, args.arm))
        m = score(rows)
        print_metrics(m)
        print(f"\n  saved -> {save(rows, args.arm, args.which)}")
        return 0

    if args.cmd == "report":
        if not RESULTS_DIR.exists():
            print("No results yet.", file=sys.stderr)
            return 1
        mets = []
        prefix = "holdout_" if args.which == "holdout" else ""
        for f in sorted(RESULTS_DIR.glob("*.json")):
            if args.which == "holdout" and not f.name.startswith("holdout_"):
                continue
            if args.which == "pairs" and f.name.startswith("holdout_"):
                continue
            with open(f, encoding="utf-8") as fh:
                mets.append(json.load(fh)["metrics"])
        if not mets:
            print(f"No results yet for set '{args.which}'.", file=sys.stderr)
            return 1
        order = {"rules": 0, "base": 1, "few_shot": 2, "cot_zero": 3, "cot": 4,
                 "cot_strict": 5, "cot_ref": 6, "cot_full": 7, "finetuned": 8,
                 "teacher": 9, "teacher_cot": 10}
        mets.sort(key=lambda m: order.get(m["arm"], 99))
        w = max(len(m["arm"]) for m in mets) + 2
        print(f"\nset: {args.which}")
        print(f"\n{'arm':<{w}}{'recall':>9}{'precis':>9}{'f1':>8}{'fpr':>8}"
              f"{'redirect':>10}{'cost':>12}{'ms':>8}")
        print("-" * (w + 64))
        for m in mets:
            print(f"{m['arm']:<{w}}{m['recall']:>8.1%}{m['precision']:>9.1%}"
                  f"{m['f1']:>8.3f}{m['false_positive_rate']:>8.1%}"
                  f"{m['redirect_accuracy']:>10.1%}${m['total_cost_usd']:>11.6f}"
                  f"{m['avg_latency_ms']:>8}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
