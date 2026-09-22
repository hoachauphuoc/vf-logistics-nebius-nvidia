#!/usr/bin/env python3
"""
Run the synthetic corpus through the pipeline and report what it actually detects.

Run
    python scripts/run_massive_benchmark.py --arm rules                 # free
    python scripts/run_massive_benchmark.py --arm full --limit 120
    python scripts/run_massive_benchmark.py --arm full --real-tavily 20

Arms
----
    rules   Deterministic checks only -- verifier.validate() plus the sanctions
            index. No model calls, no network, no cost. Runs the full 1,000 in
            seconds and establishes the floor any model layer has to beat.

    hs      rules + the HS classification agent. Isolates the one model call whose
            contribution is separately measurable, because the corpus records the
            true heading for every substitution.

    full    rules + HS + the zero-day radar, through the real gate.

Why the rules arm is not a formality
------------------------------------
On this corpus the deterministic layer already catches 100% of the alias-evasion
cases and 100% of the shell-company cases. It misses 13% of the HS substitutions,
and at the threshold where it catches almost everything it also holds 82% of the
clean traffic.

That is the actual shape of the problem, and it is not the shape the project
assumed. The model layer's job is not to find attacks the rules miss -- the rules
find nearly all of them. Its job is to tell a legitimate Dubai consolidation from a
diversion, so the 82% false-positive rate comes down without recall following it.
A benchmark that only reported a single F1 for the whole pipeline would hide that
entirely, so every number below is reported against the rules arm rather than
against zero.

Two hard constraints, stated because they shape the numbers
----------------------------------------------------------
Tavily's free tier is 1,000 credits a month. A 1,000-case run with two searches
each needs 2,000, so the bulk run uses a deterministic stub and real searches are
limited to an explicit `--real-tavily N` subset. A run that silently exhausted the
quota would return rate-limit errors for its second half, and those errors would
enter the report as "no adverse media found" -- the exact confusion
tavily_client.FAILED_STATUSES exists to prevent.

The Nebius credit is about 50 dollars total. `--max-cost-usd` aborts the run rather
than discovering the limit afterwards, and the estimate is checked as the run
proceeds, not at the end.

What is counted as a detection
------------------------------
`flagged` means the pipeline would NOT auto-clear: an auto-reject, or a risk floor
at or above the review threshold. Not "produced any finding at all" -- almost
every shipment produces some finding, so that definition would score a system that
does nothing as near-perfect on recall.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import pathlib
import statistics
import sys
import time
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
CASES_FILE = ROOT / "data" / "synthetic_test_cases.json"
REPORT_FILE = ROOT / "benchmark_report.json"

# The risk floor at or above which a shipment is held rather than auto-cleared.
# Matches the orchestrator's own banding.
REVIEW_THRESHOLD = 40


# --------------------------------------------------------------------------
# Tavily stub
# --------------------------------------------------------------------------

class TavilyLedger:
    """
    Counts searches and decides which get to be real.

    Deterministic by case id rather than random, so a rerun spends its real
    searches on the same cases and two runs are comparable. A random subset would
    make every rerun measure a different set of cases with real evidence.
    """

    def __init__(self, real_budget: int):
        self.real_budget = real_budget
        self.real_used = 0
        self.stubbed = 0
        self.allowed: set[str] = set()

    def plan(self, case_ids: list[str]) -> None:
        # Evenly spaced through the corpus so the real searches are not all on one
        # attack type.
        if self.real_budget <= 0 or not case_ids:
            return
        stride = max(1, len(case_ids) // self.real_budget)
        self.allowed = {
            cid for i, cid in enumerate(case_ids) if i % stride == 0
        }
        while len(self.allowed) > self.real_budget:
            self.allowed.pop()

    def wants_real(self, case_id: str) -> bool:
        return case_id in self.allowed and self.real_used < self.real_budget


def install_tavily_stub(ledger: TavilyLedger, current_case: dict[str, str]) -> None:
    """
    Replace the search function with one that returns a stub for most cases.

    The stub returns an EMPTY result with status OK, not a fabricated adverse
    finding. Inventing news would measure the corpus's labels reaching the model
    through the search tool rather than measuring detection -- the model would be
    told the answer and then graded on repeating it.

    So the stubbed zero-day arm measures the gate and the model's judgement on
    absence, and the real-search subset is the only place adverse-media detection
    is measured at all. That limitation is reported rather than papered over.
    """
    from vf_logistics import tavily_client

    real_search = tavily_client.search_with_status

    async def patched(query, max_results=5, **kwargs):
        case_id = current_case.get("id", "")
        if ledger.wants_real(case_id) and tavily_client.api_key():
            ledger.real_used += 1
            return await real_search(query, max_results, **kwargs)
        ledger.stubbed += 1
        return [], tavily_client.OK

    tavily_client.search_with_status = patched  # type: ignore[assignment]

    async def patched_plain(query, max_results=5):
        results, _ = await patched(query, max_results)
        return results

    tavily_client.search = patched_plain  # type: ignore[assignment]


# --------------------------------------------------------------------------
# One case
# --------------------------------------------------------------------------

async def run_case(
    case: dict[str, Any],
    arm: str,
    current_case: dict[str, str],
) -> dict[str, Any]:
    from vf_logistics import verifier
    from vf_logistics.agents.hs_classifier_agent import classify_hs
    from vf_logistics.agents.hs_classifier_agent import interpret as interpret_hs
    from vf_logistics.agents.zero_day_agent import (
        interpret as interpret_zero_day,
        screen_zero_day,
        should_screen,
    )

    shipment = case["shipment"]
    current_case["id"] = case["case_id"]

    started = time.monotonic()
    input_tokens = output_tokens = 0
    cost = 0.0
    errors: list[str] = []

    hs_verdict: dict[str, Any] | None = None
    zero_day_verdict: dict[str, Any] | None = None

    base = verifier.validate(shipment)

    if arm in ("hs", "full") and shipment.get("cargo_description") and shipment.get("hs_code"):
        try:
            response = await classify_hs(
                str(shipment["cargo_description"]), str(shipment["hs_code"]),
                mode="cot_strict",
            )
            hs_verdict = interpret_hs(response)
            input_tokens += response.get("input_tokens") or 0
            output_tokens += response.get("output_tokens") or 0
            # Surfaced rather than left on the envelope. A parse or schema failure
            # makes interpret() return "unknown", which is indistinguishable in the
            # aggregate from a model that genuinely could not decide -- and it was
            # exactly that conflation that hid the zero-day control-flow bug for a
            # whole 200-case run.
            if response.get("error"):
                errors.append(f"hs_parse: {str(response['error'])[:60]}")
            from vf_logistics import lineage
            cost += lineage.cost_usd(
                response.get("model"),
                response.get("input_tokens") or 0,
                response.get("output_tokens") or 0,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"hs: {type(exc).__name__}")
            # Mirrors the orchestrator: a failed check becomes a visible
            # "unavailable" finding, never silence.
            hs_verdict = {
                "verdict": "unknown", "suggested_hs": None, "confidence": 0.0,
                "reasoning": str(exc), "obfuscation": None,
            }

    gate_fired, gate_reason = should_screen(shipment, base)
    if arm == "full" and gate_fired:
        try:
            response = await screen_zero_day(shipment)
            zero_day_verdict = interpret_zero_day(response)
            input_tokens += response.get("input_tokens") or 0
            output_tokens += response.get("output_tokens") or 0
            if response.get("error"):
                errors.append(f"zero_day_parse: {str(response['error'])[:60]}")
            if response.get("verdict_forced"):
                errors.append("zero_day_verdict_forced")
            from vf_logistics import lineage
            cost += lineage.cost_usd(
                response.get("model"),
                response.get("input_tokens") or 0,
                response.get("output_tokens") or 0,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"zero_day: {type(exc).__name__}")
            zero_day_verdict = {
                "verdict": "unknown", "searched": False, "confidence": 0.0,
                "reasoning": str(exc), "evidence_urls": [], "entities_checked": [],
            }

    final = verifier.validate(
        shipment, hs_verdict=hs_verdict, zero_day=zero_day_verdict,
    )

    flagged = bool(
        final["auto_reject_by_rules"] or final["risk_floor"] >= REVIEW_THRESHOLD
    )
    codes = [f["code"] for f in final["findings"]]

    return {
        "case_id": case["case_id"],
        "attack": case["attack"],
        "expected_flagged": case["expected_flagged"],
        "hard_negative": case.get("hard_negative", False),
        "adjacent_hs_negative": case.get("adjacent_hs_negative", False),
        "hs_set": case.get("hs_set"),
        "obfuscation": case.get("obfuscation"),
        "flagged": flagged,
        "risk_floor": final["risk_floor"],
        "rules_only_floor": base["risk_floor"],
        "rules_only_flagged": bool(
            base["auto_reject_by_rules"] or base["risk_floor"] >= REVIEW_THRESHOLD
        ),
        "codes": codes,
        "expected_codes": case.get("expected_codes") or [],
        "sanctions_status": final.get("sanctions_screening"),
        "hs_verdict": (hs_verdict or {}).get("verdict"),
        "hs_suggested": (hs_verdict or {}).get("suggested_hs"),
        "ground_truth_hs": case.get("ground_truth_hs"),
        "gate_fired": gate_fired,
        "gate_reason": gate_reason,
        "zero_day_verdict": (zero_day_verdict or {}).get("verdict"),
        "zero_day_searched": (zero_day_verdict or {}).get("searched"),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost, 8),
        "latency_ms": int((time.monotonic() - started) * 1000),
        "errors": errors,
    }


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

# Prefix rather than an exact code. verifier emits HS_DESCRIPTION_MISMATCH_DUAL_USE
# when the suggested heading is controlled and HS_DESCRIPTION_MISMATCH otherwise,
# and matching the bare name scored the classifier at 0% on a run where it was
# actually catching 65 of 71 -- a reporting bug that would have read as a model
# failure.
HS_MISMATCH_PREFIX = "HS_DESCRIPTION_MISMATCH"


def _prf(tp: int, fp: int, fn: int, tn: int) -> dict[str, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "false_positive_rate": round(fp / (fp + tn), 4) if fp + tn else 0.0,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
    }


def score(results: list[dict[str, Any]], key: str = "flagged") -> dict[str, float]:
    tp = sum(1 for r in results if r["expected_flagged"] and r[key])
    fn = sum(1 for r in results if r["expected_flagged"] and not r[key])
    fp = sum(1 for r in results if not r["expected_flagged"] and r[key])
    tn = sum(1 for r in results if not r["expected_flagged"] and not r[key])
    return _prf(tp, fp, fn, tn)


def build_report(
    results: list[dict[str, Any]], arm: str, meta: dict[str, Any],
    ledger: TavilyLedger, elapsed: float,
) -> dict[str, Any]:
    overall = score(results)
    rules_only = score(results, key="rules_only_flagged")

    by_attack = {}
    for attack in sorted({str(r["attack"]) for r in results}):
        subset = [r for r in results if str(r["attack"]) == attack]
        detected = sum(1 for r in subset if r["flagged"])
        by_attack[attack] = {
            "cases": len(subset),
            "detected": detected,
            "detection_rate": round(detected / len(subset), 4) if subset else 0.0,
            "rules_only_detected": sum(1 for r in subset if r["rules_only_flagged"]),
        }

    # The HS classifier's own accuracy, separate from whether the case was flagged.
    # A case can be correctly flagged for the wrong reason -- a diversion route, say
    # -- and counting that as a classification success would overstate the
    # classifier by crediting it with the deterministic layer's work.
    hs_cases = [r for r in results if r["attack"] == "hs_code_mismatch"]
    hs_by_set = {}
    for hs_set in sorted({str(r["hs_set"]) for r in hs_cases if r["hs_set"]}):
        subset = [r for r in hs_cases if r["hs_set"] == hs_set]
        caught = [
            r for r in subset
            if any(c.startswith(HS_MISMATCH_PREFIX) for c in r["codes"])
        ]
        redirected = [
            r for r in caught
            if r["hs_suggested"] and r["ground_truth_hs"]
            and str(r["hs_suggested"]).startswith(str(r["ground_truth_hs"])[:4])
        ]
        hs_by_set[hs_set] = {
            "cases": len(subset),
            "mismatch_detected": len(caught),
            "detection_rate": round(len(caught) / len(subset), 4) if subset else 0.0,
            # Naming the right heading is a stronger claim than noticing the wrong
            # one, and it is what makes a finding actionable for a broker.
            "redirect_correct": len(redirected),
            "redirect_accuracy": (
                round(len(redirected) / len(caught), 4) if caught else 0.0
            ),
            "verdicts": dict(collections.Counter(
                str(r["hs_verdict"]) for r in subset
            )),
        }

    # False positives on the hard negatives, separately. This is the number that
    # says whether the system is usable on real traffic, where most shipments have
    # at least one odd-looking feature.
    clean = [r for r in results if not r["expected_flagged"]]
    hard = [r for r in clean if r["hard_negative"]]
    easy = [r for r in clean if not r["hard_negative"]]
    adjacent = [r for r in clean if r["adjacent_hs_negative"]]

    gate_attacks = [r for r in results if r["expected_flagged"]]
    gate_clean = [r for r in results if not r["expected_flagged"]]

    costs = [r["cost_usd"] for r in results]
    latencies = [r["latency_ms"] for r in results]
    model_ran = [r for r in results if r["input_tokens"] > 0]

    errors = collections.Counter(e for r in results for e in r["errors"])

    return {
        "arm": arm,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "cases_run": len(results),
        "elapsed_seconds": round(elapsed, 1),
        "corpus": {
            "file": str(CASES_FILE.name),
            "seed": meta.get("seed"),
            "total_available": meta.get("count"),
            "composition": meta.get("composition"),
        },

        "detection": overall,
        # Reported side by side because the deterministic layer already catches
        # nearly everything on this corpus. An absolute F1 without this comparison
        # would credit the model layer with the rules' work.
        "rules_only_baseline": rules_only,
        "model_contribution": {
            "recall_delta": round(overall["recall"] - rules_only["recall"], 4),
            "precision_delta": round(
                overall["precision"] - rules_only["precision"], 4,
            ),
            "false_positive_rate_delta": round(
                overall["false_positive_rate"] - rules_only["false_positive_rate"], 4,
            ),
            "note": (
                "A negative false_positive_rate_delta is the win worth having: on "
                "this corpus the rules catch almost every attack and hold most of "
                "the clean traffic, so the model layer is judged on whether it "
                "releases honest shipments without releasing attacks."
            ),
        },

        "by_attack_type": by_attack,
        "hs_classification": {
            "by_set": hs_by_set,
            "note": (
                "`holdout` substitutions are absent from data/hs_reference.yaml. "
                "Recall there is the number that says whether the reference table "
                "generalises; `pairs` was tuned against."
            ),
        },

        "false_positives": {
            "all_clean_cases": len(clean),
            "flagged": sum(1 for r in clean if r["flagged"]),
            "rate": round(
                sum(1 for r in clean if r["flagged"]) / len(clean), 4,
            ) if clean else 0.0,
            "hard_negatives": {
                "cases": len(hard),
                "flagged": sum(1 for r in hard if r["flagged"]),
                "rate": round(
                    sum(1 for r in hard if r["flagged"]) / len(hard), 4,
                ) if hard else 0.0,
            },
            "easy_negatives": {
                "cases": len(easy),
                "flagged": sum(1 for r in easy if r["flagged"]),
                "rate": round(
                    sum(1 for r in easy if r["flagged"]) / len(easy), 4,
                ) if easy else 0.0,
            },
            "adjacent_hs_negatives": {
                "cases": len(adjacent),
                "flagged": sum(1 for r in adjacent if r["flagged"]),
                "hs_mismatch_claimed": sum(
                    1 for r in adjacent
                    if any(c.startswith(HS_MISMATCH_PREFIX) for c in r["codes"])
                ),
                "note": (
                    "Benign goods declared under the heading an evader would use "
                    "as cover. An HS mismatch claimed here is the classifier "
                    "learning the cover heading rather than the goods."
                ),
            },
        },

        "zero_day": {
            "gate_fired_on_attacks": sum(1 for r in gate_attacks if r["gate_fired"]),
            "gate_fired_on_clean": sum(1 for r in gate_clean if r["gate_fired"]),
            "gate_precision": round(
                sum(1 for r in gate_attacks if r["gate_fired"])
                / max(1, sum(1 for r in results if r["gate_fired"])), 4,
            ),
            "verdicts": dict(collections.Counter(
                str(r["zero_day_verdict"]) for r in results
                if r["zero_day_verdict"]
            )),
            "verdicts_forced": sum(
                1 for r in results if "zero_day_verdict_forced" in r["errors"]
            ),
            "real_searches": ledger.real_used,
            "stubbed_searches": ledger.stubbed,
            "measurement_limit": (
                "Stubbed searches return an EMPTY result, never a fabricated "
                "adverse finding -- inventing news would feed the corpus labels to "
                "the model through the tool and then grade it on repeating them. "
                "So adverse-media DETECTION is measured only on the "
                "--real-tavily subset; the rest measures the gate and the model's "
                "handling of absence. Tavily's free tier is 1,000 credits a month, "
                "which is why the subset exists."
            ),
        },

        "cost": {
            "total_usd": round(sum(costs), 6),
            "cases_with_model_calls": len(model_ran),
            "avg_usd_per_case": round(
                sum(costs) / len(model_ran), 8,
            ) if model_ran else 0.0,
            "avg_usd_per_case_all": round(sum(costs) / len(results), 8) if results else 0.0,
            "total_input_tokens": sum(r["input_tokens"] for r in results),
            "total_output_tokens": sum(r["output_tokens"] for r in results),
            "projected_usd_per_1000_cases": round(
                (sum(costs) / len(results)) * 1000, 4,
            ) if results else 0.0,
        },

        "latency": {
            "mean_ms": int(statistics.mean(latencies)) if latencies else 0,
            "median_ms": int(statistics.median(latencies)) if latencies else 0,
            "p95_ms": int(
                statistics.quantiles(latencies, n=20)[18]
            ) if len(latencies) >= 20 else max(latencies, default=0),
        },

        "errors": dict(errors),
    }


# --------------------------------------------------------------------------

def print_report(report: dict[str, Any]) -> None:
    d, r = report["detection"], report["rules_only_baseline"]
    print(f"\n=== {report['arm']} arm, {report['cases_run']} cases, "
          f"{report['elapsed_seconds']}s ===\n")
    print(f"{'':<26}{'pipeline':>10}{'rules only':>12}{'delta':>10}")
    for label, key in (
        ("precision", "precision"), ("recall", "recall"), ("f1", "f1"),
        ("false positive rate", "false_positive_rate"),
    ):
        delta = d[key] - r[key]
        print(f"  {label:<24}{d[key]:>10.4f}{r[key]:>12.4f}{delta:>+10.4f}")
    print(f"  {'TP / FP / FN / TN':<24}"
          f"{f'{d[chr(116)+chr(112)]}/{d[chr(102)+chr(112)]}/{d[chr(102)+chr(110)]}/{d[chr(116)+chr(110)]}':>10}")

    print("\n  by attack type:")
    for attack, stats in report["by_attack_type"].items():
        print(f"    {attack:<32} {stats['detected']:>4}/{stats['cases']:<5} "
              f"({stats['detection_rate']:.1%})  rules alone: "
              f"{stats['rules_only_detected']}")

    if report["hs_classification"]["by_set"]:
        print("\n  HS classification:")
        for hs_set, stats in report["hs_classification"]["by_set"].items():
            print(f"    {hs_set:<10} detected {stats['mismatch_detected']:>4}/"
                  f"{stats['cases']:<5} ({stats['detection_rate']:.1%})  "
                  f"redirect {stats['redirect_accuracy']:.1%}")

    fp = report["false_positives"]
    print(f"\n  false positives: {fp['flagged']}/{fp['all_clean_cases']} "
          f"({fp['rate']:.1%})")
    print(f"    hard negatives   {fp['hard_negatives']['flagged']:>4}/"
          f"{fp['hard_negatives']['cases']:<5} ({fp['hard_negatives']['rate']:.1%})")
    print(f"    easy negatives   {fp['easy_negatives']['flagged']:>4}/"
          f"{fp['easy_negatives']['cases']:<5} ({fp['easy_negatives']['rate']:.1%})")
    adj = fp["adjacent_hs_negatives"]
    print(f"    adjacent-HS      {adj['flagged']:>4}/{adj['cases']:<5} "
          f"(HS mismatch wrongly claimed on {adj['hs_mismatch_claimed']})")

    zd = report["zero_day"]
    print(f"\n  zero-day gate: fired on {zd['gate_fired_on_attacks']} attacks, "
          f"{zd['gate_fired_on_clean']} clean (precision {zd['gate_precision']:.1%})")
    print(f"    searches: {zd['real_searches']} real, {zd['stubbed_searches']} stubbed")

    c = report["cost"]
    print(f"\n  cost: USD {c['total_usd']:.4f} total, "
          f"USD {c['avg_usd_per_case_all']:.6f}/case, "
          f"USD {c['projected_usd_per_1000_cases']:.2f} per 1000 cases")
    lat = report["latency"]
    print(f"  latency: mean {lat['mean_ms']}ms, median {lat['median_ms']}ms, "
          f"p95 {lat['p95_ms']}ms")
    if report["errors"]:
        print(f"\n  errors: {report['errors']}")


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arm", choices=["rules", "hs", "full"], default="rules")
    ap.add_argument("--limit", type=int, default=0, help="0 means all cases")
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument(
        "--real-tavily", type=int, default=0,
        help="how many cases may use a real Tavily search (free tier is 1000/month)",
    )
    ap.add_argument(
        "--max-cost-usd", type=float, default=5.0,
        help="abort when the running estimate exceeds this",
    )
    ap.add_argument("--cases", default=str(CASES_FILE))
    ap.add_argument("--out", default=str(REPORT_FILE))
    args = ap.parse_args()

    payload = json.loads(pathlib.Path(args.cases).read_text(encoding="utf-8"))
    cases = payload["cases"]
    if args.limit:
        # Stride rather than head, so a limited run keeps the corpus mix instead of
        # measuring whichever bucket happened to be shuffled to the front.
        stride = max(1, len(cases) // args.limit)
        cases = cases[::stride][:args.limit]

    ledger = TavilyLedger(args.real_tavily)
    ledger.plan([c["case_id"] for c in cases])
    current_case: dict[str, str] = {}
    if args.arm == "full":
        install_tavily_stub(ledger, current_case)

    print(f"running {len(cases)} cases, arm={args.arm}, "
          f"concurrency={args.concurrency}, real Tavily budget={args.real_tavily}")

    semaphore = asyncio.Semaphore(args.concurrency)
    results: list[dict[str, Any]] = []
    aborted = False
    started = time.monotonic()

    async def worker(case):
        nonlocal aborted
        async with semaphore:
            if aborted:
                return None
            # current_case is shared, so the Tavily stub can only attribute a
            # search to a case reliably at concurrency 1. Above that the real-search
            # subset is approximate, which is acceptable -- it selects WHICH cases
            # get real evidence, and no measured number depends on the attribution.
            out = await run_case(case, args.arm, current_case)
            results.append(out)
            spent = sum(r["cost_usd"] for r in results)
            if spent > args.max_cost_usd:
                aborted = True
                print(f"\nABORTING: estimated spend USD {spent:.4f} exceeded "
                      f"--max-cost-usd {args.max_cost_usd}")
            if len(results) % 50 == 0:
                print(f"  {len(results)}/{len(cases)}  "
                      f"USD {spent:.4f}  {time.monotonic() - started:.0f}s")
            return out

    await asyncio.gather(*(worker(c) for c in cases))

    elapsed = time.monotonic() - started
    report = build_report(results, args.arm, payload["meta"], ledger, elapsed)
    report["aborted_on_cost"] = aborted

    out = pathlib.Path(args.out)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print_report(report)
    print(f"\nwrote {out}")

    # Per-case rows kept beside the report. The aggregate says how well it did; the
    # rows are the only way to find out why, and a failure worth understanding is
    # always an individual case.
    detail = out.with_name(out.stem + "_cases.json")
    detail.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"wrote {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
