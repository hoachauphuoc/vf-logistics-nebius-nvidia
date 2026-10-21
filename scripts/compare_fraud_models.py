"""
Does a larger model catch what Nano misses where the rules see nothing?

    python scripts/compare_fraud_models.py --dry-run            # offline: counts and cost estimate
    python scripts/compare_fraud_models.py --limit 6            # a few live calls
    python scripts/compare_fraud_models.py                      # the full comparison

Nano scores fraud and compliance on every case that reaches the models. Where the
deterministic floor is zero, that score is the only check: auto-clear needs a floor of
zero AND a model score under 40, so a case the rules do not see is released unless the
model flags it. The documentation said a larger model might catch more there and that
this had not been measured. This measures it.

The population is every corpus case whose verifier.validate() floor is 0, labelled by
the corpus's own `expected_flagged`. Each model gets the same shipment through the
production fraud_detection_agent. A model "flags" when its risk_score is 40 or more.
Recall is the share of labelled-fraud cases it flags; the false-alarm rate is the share
of labelled-honest cases it flags. Replies that did not parse are counted and left out
of both rates, never read as a low score.

The thresholds were tuned on the dev half for the rules, and no model threshold is tuned
here, so the dev and holdout halves are reported separately and together.

The population is small: 24 fraud cases on holdout, 52 across both halves. The Wilson
intervals say how little that settles, and the report carries them.

Cost is checked as the run proceeds; --max-cost-usd stops it rather than discovering the
bill afterwards. NEBIUS_API_KEY comes from the environment and is never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from typing import Any

from _eval_common import (
    FLAG_AT, NANO, SUPER, ULTRA, install_empty_tavily, load_cases, rate, split_of, write_report,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SHORT = {NANO: "nano", SUPER: "super", ULTRA: "ultra"}


def install_super_json_workaround() -> None:
    """
    Ask every model except Nano for JSON by prompt alone.

    Nemotron 3 Super does not survive response_format=json_object (its reasoning is
    cut off by the constrained decoding; investigation_agent.JSON_MODE is False for
    that reason, and 6 of 12 replies were fragments when it was on). The fraud agent
    hard-codes JSON mode, which is right for Nano and would make Super look worse than
    it is. Wrapping the one transport function once, up front, keeps the comparison
    about the model and not about the decoding mode. Nano is untouched, so its arm is
    exactly what production runs.
    """
    from vf_logistics import nebius_client

    original = nebius_client.complete_json

    async def complete_json(*, model, json_mode=True, **kwargs):
        return await original(model=model, json_mode=json_mode and model == NANO, **kwargs)

    nebius_client.complete_json = complete_json  # type: ignore[assignment]


def floor_zero_cases() -> list[dict[str, Any]]:
    from vf_logistics import verifier

    out = []
    for case in load_cases():
        if verifier.validate(case["shipment"]).get("risk_floor") == 0:
            out.append(case)
    return out


async def score_one(case: dict[str, Any], model: str) -> dict[str, Any]:
    from vf_logistics import lineage
    from vf_logistics.agents import fraud_detection_agent as agent

    # The agent reads its model through get_model_id() at call time, so replacing the
    # function replaces the model for this call and nothing else.
    original = agent.get_model_id
    agent.get_model_id = lambda: model  # type: ignore[assignment]
    started = time.monotonic()
    try:
        resp = await agent.analyze_shipment(case["shipment"])
        error = resp.get("error") if resp.get("parse_error") else None
        score = (resp.get("result") or {}).get("risk_score")
        in_tok, out_tok = resp.get("input_tokens") or 0, resp.get("output_tokens") or 0
    except Exception as exc:  # noqa: BLE001 - reported, so one failure does not end the run
        error, score, in_tok, out_tok = f"{type(exc).__name__}", None, 0, 0
    finally:
        agent.get_model_id = original  # type: ignore[assignment]

    usable = error is None and isinstance(score, (int, float))
    return {
        "case_id": case["case_id"],
        "split": split_of(case["case_id"]),
        "fraud": bool(case["expected_flagged"]),
        "model": model,
        "usable": usable,
        "error": None if usable else (str(error)[:80] if error else "no risk_score in reply"),
        "score": float(score) if usable else None,
        "flagged": bool(usable and score >= FLAG_AT),
        "cost_usd": lineage.cost_usd(model, in_tok, out_tok),
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "seconds": round(time.monotonic() - started, 1),
    }


def summarise(rows: list[dict[str, Any]], model: str, splits: tuple[str, ...]) -> dict[str, Any]:
    mine = [r for r in rows if r["model"] == model and r["split"] in splits]
    usable = [r for r in mine if r["usable"]]
    fraud = [r for r in usable if r["fraud"]]
    honest = [r for r in usable if not r["fraud"]]
    return {
        "cases": len(mine),
        "unusable_replies": len(mine) - len(usable),
        "unusable_reasons": {
            reason: sum(1 for r in mine if not r["usable"] and r["error"] == reason)
            for reason in sorted({r["error"] for r in mine if not r["usable"]})
        },
        "recall": rate(sum(r["flagged"] for r in fraud), len(fraud)),
        "false_alarm_rate": rate(sum(r["flagged"] for r in honest), len(honest)),
        "cost_usd": round(sum(r["cost_usd"] for r in mine), 6),
        "cost_per_case_usd": round(sum(r["cost_usd"] for r in mine) / len(mine), 6) if mine else None,
        "median_seconds": sorted(r["seconds"] for r in mine)[len(mine) // 2] if mine else None,
        "mean_input_tokens": round(sum(r["input_tokens"] for r in mine) / len(mine)) if mine else None,
    }


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", default="nano,super", help="comma list of nano, super, ultra")
    ap.add_argument("--limit", type=int, default=0, help="0 means every floor-zero case")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--max-cost-usd", type=float, default=1.5)
    ap.add_argument("--dry-run", action="store_true", help="count cases and estimate cost; no model calls")
    ap.add_argument("--out", default="fraud_floor0.json")
    args = ap.parse_args()

    by_short = {v: k for k, v in SHORT.items()}
    models = [by_short[m.strip()] for m in args.models.split(",") if m.strip()]

    cases = floor_zero_cases()
    if args.limit:
        # Alternate labels so a small --limit still contains both kinds.
        fraud = [c for c in cases if c["expected_flagged"]]
        honest = [c for c in cases if not c["expected_flagged"]]
        cases = [x for pair in zip(fraud, honest) for x in pair][: args.limit]

    by = {(split_of(c["case_id"]), bool(c["expected_flagged"])): 0 for c in cases}
    for c in cases:
        by[(split_of(c["case_id"]), bool(c["expected_flagged"]))] += 1
    print(f"{len(cases)} floor-zero cases: " + ", ".join(f"{s} {'fraud' if f else 'honest'} {n}" for (s, f), n in sorted(by.items())))

    # About 1.1k tokens in and 0.8k out on Nano; Super and Ultra are priced from the table.
    from vf_logistics import lineage
    estimate = {m: len(cases) * lineage.cost_usd(m, 1100, 800) for m in models}
    print("estimated cost: " + ", ".join(f"{SHORT[m]} ${v:.3f}" for m, v in estimate.items())
          + f" (total ${sum(estimate.values()):.3f}; ceiling ${args.max_cost_usd})")
    if args.dry_run:
        return 0

    install_empty_tavily()
    install_super_json_workaround()
    sem = asyncio.Semaphore(args.concurrency)
    rows: list[dict[str, Any]] = []
    spent = 0.0
    stop = False

    async def one(case: dict[str, Any], model: str) -> None:
        nonlocal spent, stop
        async with sem:
            if stop:
                return
            row = await score_one(case, model)
            rows.append(row)
            spent += row["cost_usd"]
            if spent > args.max_cost_usd:
                stop = True

    await asyncio.gather(*(one(c, m) for c in cases for m in models))
    if stop:
        print(f"ABORTED: spend ${spent:.4f} passed --max-cost-usd {args.max_cost_usd}; the report is partial")

    report = {
        "kind": "fraud_floor_zero",
        "question": "Where the deterministic floor is 0 the model is the only check. Does a larger model flag more of the fraud the rules miss?",
        "population": "corpus cases whose verifier floor is 0, labelled by expected_flagged",
        "flag_threshold": FLAG_AT,
        "corpus": "data/synthetic_test_cases.json (synthetic, 1,000 cases)",
        "partial": stop,
        "results": {
            SHORT[m]: {
                "model": m,
                "holdout": summarise(rows, m, ("holdout",)),
                "dev": summarise(rows, m, ("dev",)),
                "all": summarise(rows, m, ("dev", "holdout")),
            }
            for m in models
        },
        "total_cost_usd": round(spent, 6),
        "notes": [
            "A model flags a case when its risk_score is 40 or more. Unparseable replies are excluded from both rates and counted.",
            "No model threshold was tuned on this data, so both halves are reported; the holdout half is the headline.",
            "24 fraud cases on holdout and 52 in total: read the intervals, not the point estimates.",
            "Synthetic corpus: no real customer traffic has been measured.",
        ],
    }
    path = write_report(args.out, report)
    print()
    for m in models:
        for split in ("holdout", "all"):
            s = report["results"][SHORT[m]][split]
            r, f = s["recall"], s["false_alarm_rate"]
            print(f"{SHORT[m]:6} {split:8} recall {r['count']}/{r['of']} ci {r['ci95']}   "
                  f"false alarms {f['count']}/{f['of']} ci {f['ci95']}   ${s['cost_usd']}  unusable {s['unusable_replies']} {s['unusable_reasons'] or ''}")
    print(f"\nwritten to {path}   total ${spent:.4f}")
    return 1 if stop else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
