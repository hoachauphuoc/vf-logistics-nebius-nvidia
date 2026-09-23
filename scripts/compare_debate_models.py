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
set -- the floor and the model disagree by 15 points or more -- and its output is not a
score awaiting override. It is a reasoned CONFIRM or DISAGREE on whether that
disagreement can be resolved without a person. That judgement IS the outcome, so
reasoning capacity there is load-bearing.

WHAT TO LOOK FOR

The number that would justify Ultra is not agreement with Super, it is fewer cases
landing in front of a human for no good reason. A debate that CONFIRMs the floor sends
the case to review; one that DISAGREEs with a well-argued reason can let it clear. So:

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

from vf_logistics import config, lineage  # noqa: E402
from vf_logistics.agents import debate_agent  # noqa: E402

SUPER = "nvidia/nemotron-3-super-120b-a12b"
ULTRA = "nvidia/Nemotron-3-Ultra-550b-a55b"

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
    "VF_TEST_BASE", "https://vf-logistics-f7rcctz26a-as.a.run.app",
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

    verdict = (result.get("result") or {}).get("verdict")
    input_tokens = result.get("input_tokens") or 0
    output_tokens = result.get("output_tokens") or 0
    return {
        "case_id": case.get("case_id"),
        "model": model,
        "verdict": verdict,
        "parsed": not result.get("parse_error", True),
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


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases", type=int, default=3,
        help="how many disputed cases to replay through each model",
    )
    args = parser.parse_args()

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
