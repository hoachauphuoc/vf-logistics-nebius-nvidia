"""
Is Nemotron Ultra worth its rate on the debate agent?

    python scripts/compare_debate_models.py

The debate moved to Ultra on a judgement, not a measurement, and this script exists so
the judgement can be checked. It replays the same disputed cases through Super and
Ultra and reports what each costs and what each concludes.

WHAT MAKES THE DEBATE DIFFERENT FROM EVERY OTHER AGENT

Ultra is 1.00/3.00 per million against Super's 0.30/0.90. It is deliberately not used
on fraud_detection or compliance, and the reason is architectural rather than
financial: verifier.py computes a deterministic risk floor, and an agent may raise risk
but never lower it below that floor. A stronger model on those two agents cannot change
the outcome in the direction that matters, because the floor already decides. Paying
3.3x for a score that gets overridden buys nothing.

The debate is the one place that does not hold. It runs only when `score_disputed` is
set -- the floor and the model disagree by 15 points or more -- so auto-clear is already
ruled out and a person decides the case either way. Its output is not a score awaiting
override but a reasoned CONFIRM or DISAGREE on whether the junior analyst missed
something, and a genuine DISAGREE at or above DEBATE_ESCALATE_CONFIDENCE sends the case
to deep investigation (orchestrator.debate_escalation). That judgement can change a
case's route instead of being floored, so reasoning capacity there is load-bearing.

WHAT TO LOOK FOR

The number that would justify Ultra is not agreement with Super, it is verdicts worth
acting on. Nothing the debate says can clear a case: CONFIRM changes nothing, and a
confident DISAGREE sends it to deep investigation before a reviewer sees it, so each
one should be an investigation worth having run. So:

  * dispute resolution rate -- how many debates reach a verdict at all, rather than
    failing to parse or running out of tool rounds
  * the split between CONFIRM and DISAGREE, and whether the DISAGREE reasons read as
    argument or as compliance with the prompt
  * cost per debate, which is NOT small: measured at $0.0198 for Ultra against $0.0015
    for Super, 13x rather than the 3.3x rate multiple. Ultra consumed 13,151-16,502
    input tokens where Super used 2,522-5,546, because it emits more tool-call rounds
    and each round resends the growing transcript. Volume compounds on top of price,
    which is why the cost column below is worth reading rather than assuming.

If Ultra shows no better resolution rate, set DEBATE_MODEL back to
nvidia/nemotron-3-super-120b-a12b. That reverses the decision without a deploy, which
is why the model is read from the environment rather than pinned.

This costs real tokens on a real endpoint. It is a deliberate spend, run manually.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vf_logistics import config, lineage  # noqa: E402
from vf_logistics.agents import debate_agent  # noqa: E402

from _eval_common import NANO as NANO_ID, SUPER, ULTRA  # noqa: E402

# Read over HTTP, not through store.get_store().
#
# The first version imported the store directly and found nothing, twice, for two
# different reasons that both looked like "the board is empty":
#
#   1. list_cases returns a LIST; it was being unpacked as a paginated dict.
#   2. get_store() falls back to MemoryStore when Firestore cannot be reached and
#      records why in store._init_note -- which nothing here read. On this machine the
#      reason was `ModuleNotFoundError: No module named 'google.cloud'`, so the script
#      cheerfully read an empty in-process store and reported an empty board.
#
# That fallback is right for the service, where a Firestore outage must not take the demo
# down. It is wrong for a diagnostic script, where a silent empty result is the one
# outcome that wastes the most time. Reading the public state endpoint removes the
# question: no local credentials, no google-cloud dependency, and it works against any
# deployment.
BOARD = os.getenv(
    "VF_TEST_BASE", "https://vf-app-350828852747.asia-southeast1.run.app",
).rstrip("/")


def disputed_cases(limit: int) -> list[dict]:
    """
    Cases where the floor and the model actually disagreed.

    Taken from the board rather than synthesised, because a disagreement a handwritten
    fixture produces is not the disagreement the pipeline produces -- the whole question
    is how a model handles the real ones.
    """
    with urllib.request.urlopen(BOARD + "/api/v1/orchestrator/state", timeout=120) as r:
        payload = json.loads(r.read().decode())

    cases = payload.get("cases") or payload.get("items") or []
    disputed = [
        c for c in cases
        if (c.get("reconciliation") or {}).get("score_disputed")
    ]
    print(f"board: {len(cases)} cases, {len(disputed)} disputed")
    return disputed[:limit]


async def run_one(case: dict, model: str) -> dict:
    """One debate, with the model forced."""
    original = debate_agent.MODEL_ID
    debate_agent.MODEL_ID = model
    started = time.monotonic()
    try:
        result = await debate_agent.conduct_debate(case)
        error = None
    except Exception as exc:  # noqa: BLE001 - reported, not raised, so one failure
        result, error = {}, f"{type(exc).__name__}: {exc}"
    finally:
        debate_agent.MODEL_ID = original

    verdict_obj = (result.get("result") or {}).get("verdict")
    # conduct_debate returns the verdict as {"verdict", "confidence", "forced", ...}; the
    # first version of this script read the whole object as the verdict string.
    verdict = verdict_obj.get("verdict") if isinstance(verdict_obj, dict) else verdict_obj
    confidence = verdict_obj.get("confidence") if isinstance(verdict_obj, dict) else None
    forced = bool(verdict_obj.get("forced")) if isinstance(verdict_obj, dict) else False
    input_tokens = result.get("input_tokens") or 0
    output_tokens = result.get("output_tokens") or 0
    return {
        "case_id": case.get("case_id"),
        "model": model,
        "verdict": verdict,
        "confidence": confidence,
        "forced": forced,
        "parsed": bool(verdict) and not forced,
        "error": error,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": lineage.cost_usd(model, input_tokens, output_tokens),
        "seconds": round(time.monotonic() - started, 1),
    }


def summarise(rows: list[dict], model: str) -> None:
    mine = [r for r in rows if r["model"] == model]
    if not mine:
        print(f"  {model}: no runs")
        return
    resolved = [r for r in mine if r["parsed"] and r["verdict"]]
    cost = sum(r["cost_usd"] for r in mine)
    name = config.pricing_for(model).get("name", model)
    print(f"  {name}")
    print(f"    debates            {len(mine)}")
    print(f"    reached a verdict  {len(resolved)} ({100 * len(resolved) // len(mine)}%)")
    verdicts: dict[str, int] = {}
    for r in resolved:
        verdicts[str(r["verdict"])] = verdicts.get(str(r["verdict"]), 0) + 1
    for v, n in sorted(verdicts.items()):
        print(f"      {v:20} {n}")
    print(f"    total cost         ${cost:.6f}")
    print(f"    cost per debate    ${cost / len(mine):.6f}")
    print(f"    median seconds     {sorted(r['seconds'] for r in mine)[len(mine) // 2]}")
    failures = [r for r in mine if r["error"]]
    if failures:
        print(f"    errors             {len(failures)}")
        for r in failures[:3]:
            print(f"      {r['case_id']}: {r['error']}")


# --------------------------------------------------------------------------
# --corpus: the same question with the answer known
# --------------------------------------------------------------------------
#
# The board mode above has no labels, so it can say what each model concludes and what
# it costs but not whether a DISAGREE was right. The corpus has a label on every case
# (`expected_flagged`), which makes the question answerable:
#
#   P(DISAGREE | the case is fraud)  -- the debate noticed what Nano missed
#   P(DISAGREE | the case is honest) -- the debate manufactured an investigation
#
# A model worth its rate has the first clearly above the second. Nothing the debate says
# can clear a case, so a DISAGREE on an honest one costs an investigation, not a release.
#
# Nano screens each candidate exactly as production does (fraud and compliance, with an
# empty Tavily stub), verifier.reconcile() sets the floor/score gap, and only the cases
# where the gap is 15 or more are debated -- the same trigger as orchestrator.py.


async def nano_screen(case: dict, sem: asyncio.Semaphore) -> dict | None:
    """Build the case dict the debate reviews, from Nano's real fraud and compliance output."""
    from vf_logistics import lineage, verifier
    from vf_logistics.agents import compliance_agent, fraud_detection_agent

    shipment = case["shipment"]
    validation = verifier.validate(shipment)
    async with sem:
        try:
            fraud, compliance = await asyncio.gather(
                fraud_detection_agent.analyze_shipment(shipment),
                compliance_agent.screen_shipment(shipment, risk_floor=validation["risk_floor"]),
            )
        except Exception:  # noqa: BLE001 - a screening failure drops the candidate
            return None
    fraud_result = fraud.get("result") or {}
    compliance_result = compliance.get("result") or {}
    if fraud.get("parse_error") or not isinstance(fraud_result.get("risk_score"), (int, float)):
        return None
    reconciled = verifier.reconcile(fraud_result.get("risk_score"), validation)
    cost = sum(
        lineage.cost_usd(r.get("model"), r.get("input_tokens") or 0, r.get("output_tokens") or 0)
        for r in (fraud, compliance)
    )
    return {
        "case_id": case["case_id"],
        "fraud": bool(case["expected_flagged"]),
        "disputed": bool(reconciled["score_disputed"]),
        "screen_cost_usd": cost,
        "case": {
            "case_id": case["case_id"],
            "shipment": shipment,
            "steps": [
                {"agent": "fraud_detection", "result": fraud_result},
                {"agent": "compliance", "result": compliance_result},
            ],
            "model_risk_score": reconciled["model_risk"],
            "risk_score": reconciled["effective_risk"],
            "risk_level": fraud_result.get("risk_level"),
            "compliance_status": compliance_result.get("compliance_status"),
            "compliance_score": compliance_result.get("compliance_score"),
            "validation": validation,
            "reconciliation": reconciled,
        },
    }


def debate_stats(rows: list[dict], model: str) -> dict:
    from _eval_common import rate

    mine = [r for r in rows if r["model"] == model]
    resolved = [r for r in mine if r["parsed"]]
    fraud = [r for r in resolved if r["is_fraud"]]
    honest = [r for r in resolved if not r["is_fraud"]]
    confident = lambda r: r["verdict"] == "DISAGREE" and (r["confidence"] or 0) >= CONFIDENT  # noqa: E731
    cost = sum(r["cost_usd"] for r in mine)
    return {
        "debates": len(mine),
        "reached_a_verdict": rate(len(resolved), len(mine)),
        "disagree_on_fraud": rate(sum(r["verdict"] == "DISAGREE" for r in fraud), len(fraud)),
        "disagree_on_honest": rate(sum(r["verdict"] == "DISAGREE" for r in honest), len(honest)),
        "confident_disagree_on_fraud": rate(sum(confident(r) for r in fraud), len(fraud)),
        "confident_disagree_on_honest": rate(sum(confident(r) for r in honest), len(honest)),
        "cost_usd": round(cost, 6),
        "cost_per_debate_usd": round(cost / len(mine), 6) if mine else None,
        "mean_input_tokens": round(sum(r["input_tokens"] for r in mine) / len(mine)) if mine else None,
        "median_seconds": sorted(r["seconds"] for r in mine)[len(mine) // 2] if mine else None,
    }


CONFIDENT = 0.7  # orchestrator.DEBATE_ESCALATE_CONFIDENCE_DEFAULT


async def corpus_main(args: argparse.Namespace) -> int:
    from _eval_common import install_empty_tavily, load_cases, write_report
    from vf_logistics import verifier

    cases = load_cases()
    # Candidates are cases the rules hold (floor >= 40): only those can be disputed,
    # since the debate needs the floor to exceed Nano's score by 15. Both halves are used
    # because no threshold is being tuned, and honest held cases are scarce (73 in all).
    held = [c for c in cases if verifier.validate(c["shipment"]).get("risk_floor", 0) >= 40]
    fraud = [c for c in held if c["expected_flagged"]]
    honest = [c for c in held if not c["expected_flagged"]]
    print(f"{len(held)} held cases: {len(fraud)} fraud, {len(honest)} honest")

    # Screen enough of each to expect --per-label disputed cases of each label. Honest
    # cases are screened in full (few); fraud are sampled evenly across the corpus.
    stride = max(1, len(fraud) // max(1, args.screen_fraud))
    pool = honest + fraud[::stride][: args.screen_fraud]
    print(f"screening {len(pool)} candidates with Nano ({len(honest)} honest, {len(pool) - len(honest)} fraud)")

    from vf_logistics import lineage
    est_screen = len(pool) * lineage.cost_usd(NANO_ID, 3000, 1800)
    est_debate = args.per_label * 2 * (lineage.cost_usd(SUPER, 4000, 500) + lineage.cost_usd(ULTRA, 15000, 1800))
    print(f"estimated: screening ${est_screen:.2f}, debates up to ${est_debate:.2f} (ceiling ${args.max_cost_usd})")
    if args.dry_run:
        return 0

    install_empty_tavily()
    sem = asyncio.Semaphore(args.concurrency)
    screened = [r for r in await asyncio.gather(*(nano_screen(c, sem) for c in pool)) if r]
    spent = sum(r["screen_cost_usd"] for r in screened)
    disputed = [r for r in screened if r["disputed"]]
    d_fraud = [r for r in disputed if r["fraud"]][: args.per_label]
    d_honest = [r for r in disputed if not r["fraud"]][: args.per_label]
    print(f"screened {len(screened)} ok, {len(disputed)} disputed -> debating {len(d_fraud)} fraud + {len(d_honest)} honest   (${spent:.3f} spent)")
    chosen = d_fraud + d_honest
    if not chosen:
        print("no disputed cases; nothing to debate")
        return 1

    rows: list[dict] = []
    stopped = False

    async def debate(rec: dict, model: str) -> None:
        nonlocal spent, stopped
        async with sem:
            if stopped:
                return
            row = await run_one(rec["case"], model)
            row["is_fraud"] = rec["fraud"]
            rows.append(row)
            spent += row["cost_usd"]
            if spent > args.max_cost_usd:
                stopped = True

    await asyncio.gather(*(debate(r, m) for r in chosen for m in (SUPER, ULTRA)))
    if stopped:
        print(f"ABORTED: spend ${spent:.4f} passed --max-cost-usd {args.max_cost_usd}; the report is partial")

    report = {
        "kind": "debate_corpus",
        "question": "Does the Senior Auditor on Ultra notice what Nano missed more reliably than on Super?",
        "trigger": "floor exceeds Nano's score by 15 or more (verifier.reconcile score_disputed)",
        "confident_threshold": CONFIDENT,
        "labels": "corpus expected_flagged; both halves used because nothing is tuned here",
        "partial": stopped,
        "candidates_screened": len(screened),
        "candidates_disputed": len(disputed),
        "debated": {"fraud": len(d_fraud), "honest": len(d_honest)},
        "results": {"super": {"model": SUPER, **debate_stats(rows, SUPER)},
                    "ultra": {"model": ULTRA, **debate_stats(rows, ULTRA)}},
        "total_cost_usd": round(spent, 6),
        "notes": [
            "DISAGREE on a fraud case is the debate noticing what Nano missed; DISAGREE on an honest case is an investigation that did not need to run. A model worth its rate has the first clearly above the second.",
            "Nothing the debate says can clear a case: a CONFIRM changes nothing and a DISAGREE only routes a held case to investigation.",
            "Small samples: read the intervals. Synthetic corpus, no real customer traffic.",
            "A debate with no verdict, or a forced default, counts against 'reached a verdict' and is left out of the DISAGREE rates.",
        ],
    }
    path = write_report(args.out, report)
    print()
    for name in ("super", "ultra"):
        s = report["results"][name]
        f, h, v = s["disagree_on_fraud"], s["disagree_on_honest"], s["reached_a_verdict"]
        print(f"{name:6} verdict {v['count']}/{v['of']}   DISAGREE fraud {f['count']}/{f['of']} {f['ci95']}   "
              f"honest {h['count']}/{h['of']} {h['ci95']}   ${s['cost_per_debate_usd']}/debate")
    print(f"\nwritten to {path}   total ${spent:.4f}")
    return 1 if stopped else 0


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases", type=int, default=3,
        help="how many disputed cases to replay through each model",
    )
    parser.add_argument("--corpus", action="store_true",
                        help="debate labelled corpus cases instead of the live board (see corpus_main)")
    parser.add_argument("--per-label", type=int, default=25,
                        help="--corpus: disputed cases to debate for each label")
    parser.add_argument("--screen-fraud", type=int, default=120,
                        help="--corpus: fraud candidates Nano screens to find disputed ones")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--max-cost-usd", type=float, default=3.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out", default="debate_corpus.json")
    args = parser.parse_args()

    if args.corpus:
        return await corpus_main(args)

    cases = disputed_cases(args.cases)
    if not cases:
        print(f"No disputed cases on {BOARD}. Seed the board first:")
        print("  python scripts/seed_full_board.py --yes")
        return 1

    print(f"Replaying {len(cases)} disputed case(s) through both models.")
    print("This spends real tokens.\n")

    rows: list[dict] = []
    for case in cases:
        for model in (SUPER, ULTRA):
            row = await run_one(case, model)
            rows.append(row)
            flag = "ok" if row["parsed"] else "NO VERDICT"
            print(
                f"  {row['case_id'][:34]:34} {model.split('/')[-1][:28]:28} "
                f"{flag:10} {row['seconds']:5}s ${row['cost_usd']:.6f}"
            )

    print()
    print("=" * 70)
    for model in (SUPER, ULTRA):
        summarise(rows, model)
        print()

    ultra_cost = sum(r["cost_usd"] for r in rows if r["model"] == ULTRA)
    super_cost = sum(r["cost_usd"] for r in rows if r["model"] == SUPER)
    if super_cost:
        print(f"Ultra costs {ultra_cost / super_cost:.1f}x Super on this sample.")
    print(
        "The number that justifies Ultra is a better resolution rate, not agreement\n"
        "with Super. If the rates match, set DEBATE_MODEL back to Super."
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
