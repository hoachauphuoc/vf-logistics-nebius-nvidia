"""
Generate obfuscated training data for the HS classification evaluator.

Design decision worth stating: the teacher generates TEXT, not labels. The ground
truth for every example is already known from the structure of hs_pairs.yaml --
if we take the controlled goods and pair them with the benign heading, the label
is "inconsistent" and the correct heading is the controlled one, by construction.
Asking a model to label would introduce noise into data whose labels are exact.
So Super is used only for the thing it is actually good at here: inventing
realistic ways a declarant would disguise a description.

Leakage control: the split is by SEED PAIR, not by example. Goods held out for
test never appear in training under any obfuscation. Splitting by example would
put a misspelled variant of the same turbine in both halves and report a score
that means nothing.

Usage:
    python scripts/gen_hs_data.py --per-type 20          # ~3000 examples
    python scripts/gen_hs_data.py --per-type 4 --dry-run # cheap smoke test
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import random
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import yaml  # noqa: E402

from vf_logistics import nebius_client  # noqa: E402
from vf_logistics.agents._common import parse_model_json  # noqa: E402
from vf_logistics.agents.hs_classifier_agent import SYSTEM_PROMPT  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAIRS_FILE = ROOT / "data" / "hs_pairs.yaml"
OUT_DIR = ROOT / "data" / "training"

TEACHER = "nvidia/nemotron-3-super-120b-a12b"
CONCURRENCY = 6          # generation is I/O bound; keeps well clear of rate limits
HOLDOUT_PAIRS = 4        # of 15 -- goods the model never sees in training
SEED = 20260919

OBFUSCATIONS = {
    "misspelling": (
        "Misspell the technical nouns the way a hurried or deliberately careless "
        "clerk would -- transposed letters, dropped letters, phonetic spellings. "
        "Keep the goods identifiable to a specialist."
    ),
    "synonym": (
        "Replace the technical nouns with less searchable synonyms or trade "
        "jargon. Do not use the obvious term that a keyword filter would match."
    ),
    "circumlocution": (
        "Describe the goods by function and material without ever naming the "
        "category. A specialist should still recognise them."
    ),
    "component_split": (
        "Break the goods into individually innocuous-sounding components listed "
        "together, so no single item reads as sensitive."
    ),
    "mixed_language": (
        "Mix English with Vietnamese or Chinese commercial terms, the way a real "
        "regional shipping document does. Keep it plausible, not gibberish."
    ),
}

GEN_PROMPT = """\
You write realistic cargo descriptions for customs documents. You are helping
build a detection training set, so the descriptions must be the kind a real
exporter would write, not caricatures.

Return only JSON: {"descriptions": ["...", "..."]}
Each description is one line of cargo text, 8 to 25 words, as it would appear on
a bill of lading. Vary length, punctuation, capitalisation and units. Include
quantities and specifications where natural. Do not number them. Do not explain.\
"""


async def _generate(sem: asyncio.Semaphore, instruction: str, goods: str,
                    count: int) -> list[str]:
    async with sem:
        try:
            text, _, _ = await nebius_client.complete_json(
                model=TEACHER,
                system_prompt=GEN_PROMPT,
                user_text=(
                    f"Goods: {goods}\n\n"
                    f"Task: {instruction}\n\n"
                    f"Write {count} different descriptions of these goods."
                ),
                temperature=0.9,   # high on purpose: we want lexical variety
            )
            parsed, _ = parse_model_json(text)
            items = (parsed or {}).get("descriptions") or []
            return [
                " ".join(str(d).split())
                for d in items
                if isinstance(d, str) and 4 <= len(str(d).split()) <= 60
            ]
        except Exception as exc:
            print(f"    generation failed: {type(exc).__name__}: {exc}", flush=True)
            return []


def _example(description: str, declared_hs: str, consistent: bool,
             suggested_hs: str | None, obfuscation: str,
             pair_id: str, split: str) -> dict[str, Any]:
    """One training example, in the shape the agent is expected to produce."""
    target = {
        "consistent": consistent,
        "declared_hs": declared_hs,
        "suggested_hs": suggested_hs,
        # Not model-derived. High where the label is structural, which it is here.
        "confidence": 0.92 if not consistent else 0.95,
        "reasoning": "",   # filled by caller; kept in the schema for ordering
        "obfuscation_observed": obfuscation,
    }
    return {
        "pair_id": pair_id,
        "split": split,
        "label_consistent": consistent,
        "expected_hs": suggested_hs,
        "obfuscation": obfuscation,
        "cargo_description": description,
        "declared_hs": declared_hs,
        "_target": target,
    }


async def build(per_type: int, dry_run: bool) -> list[dict[str, Any]]:
    data = yaml.safe_load(open(PAIRS_FILE, encoding="utf-8"))
    pairs, benign = data["pairs"], data["benign_controls"]

    rng = random.Random(SEED)
    idx = list(range(len(pairs)))
    rng.shuffle(idx)
    holdout = set(idx[:HOLDOUT_PAIRS])
    print(f"Seed pairs: {len(pairs)}  train={len(pairs)-len(holdout)}  "
          f"holdout={sorted(holdout)}")

    sem = asyncio.Semaphore(CONCURRENCY)
    # Job specs, not coroutines. Coroutines are created only after any slicing,
    # because a coroutine that is built and then discarded raises
    # "never awaited" and silently drops the work.
    specs: list[tuple[dict[str, Any], dict[str, Any]]] = []

    # Evasive: controlled goods described obfuscatedly, benign heading declared.
    for i, p in enumerate(pairs):
        split = "test" if i in holdout else "train"
        for obf, instruction in OBFUSCATIONS.items():
            specs.append((
                {"instruction": instruction, "goods": p["controlled_goods"],
                 "count": per_type},
                {"declared_hs": p["benign_hs"], "consistent": False,
                 "suggested_hs": p["controlled_hs"], "obfuscation": obf,
                 "pair_id": f"P{i:02d}", "split": split, "kind": "evasive",
                 "reason": (f"Goods described are {p['controlled_goods']}, which "
                            f"fall under {p['controlled_hs']}, not the declared "
                            f"{p['benign_hs']}.")},
            ))

    # Honest: goods that genuinely belong to the declared heading. Without these
    # the model learns that the answer is always "inconsistent".
    honest_per = max(1, per_type * len(OBFUSCATIONS) // 2)
    for i, b in enumerate(benign):
        split = "test" if i in holdout else "train"
        specs.append((
            {"instruction": "Write ordinary, honest commercial descriptions. "
                            "No evasion.",
             "goods": b["cargo_description"], "count": honest_per},
            {"declared_hs": b["hs_code"], "consistent": True,
             "suggested_hs": None, "obfuscation": "none",
             "pair_id": f"B{i:02d}", "split": split, "kind": "honest",
             "reason": (f"Description matches the scope of heading "
                        f"{b['hs_code']}.")},
        ))

    if dry_run:
        # Sample both kinds and both splits, or the smoke test exercises only
        # the evasive path and proves less than it appears to.
        picked: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for kind in ("evasive", "honest"):
            for split in ("train", "test"):
                match = [s for s in specs
                         if s[1]["kind"] == kind and s[1]["split"] == split]
                picked.extend(match[:2])
        specs = picked
        print(f"DRY RUN: {len(specs)} generation calls "
              f"({sum(1 for s in specs if s[1]['kind']=='evasive')} evasive, "
              f"{sum(1 for s in specs if s[1]['kind']=='honest')} honest)")

    print(f"Generating with {TEACHER} ({len(specs)} calls, concurrency {CONCURRENCY})...")
    results = await asyncio.gather(*(
        _generate(sem, a["instruction"], a["goods"], a["count"]) for a, _ in specs
    ))

    examples: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for descriptions, meta in zip(results, (m for _, m in specs)):
        for d in descriptions:
            key = (d.lower(), meta["declared_hs"])
            if key in seen:      # the teacher repeats itself across calls
                continue
            seen.add(key)
            ex = _example(d, meta["declared_hs"], meta["consistent"],
                          meta["suggested_hs"], meta["obfuscation"],
                          meta["pair_id"], meta["split"])
            ex["_target"]["reasoning"] = meta["reason"]
            examples.append(ex)

    return examples


def to_jsonl(examples: list[dict[str, Any]]) -> list[str]:
    """Nebius conversational format. System prompt matches the agent exactly."""
    lines = []
    for ex in examples:
        user = (
            "<<<BEGIN GOODS RECORD>>>\n"
            f"Description: {ex['cargo_description']}\n"
            f"Declared heading: {ex['declared_hs']}\n"
            "<<<END GOODS RECORD>>>\n\n"
            "Is the description consistent with the declared heading?"
        )
        lines.append(json.dumps({"messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
            {"role": "assistant",
             "content": json.dumps(ex["_target"], ensure_ascii=False)},
        ]}, ensure_ascii=False))
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-type", type=int, default=20,
                    help="descriptions per obfuscation type per pair")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    examples = asyncio.run(build(args.per_type, args.dry_run))
    if not examples:
        print("No examples generated.", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    train = [e for e in examples if e["split"] == "train"]
    test = [e for e in examples if e["split"] == "test"]
    # Validation comes out of train, stratified by pair so every pair is present.
    rng = random.Random(SEED)
    rng.shuffle(train)
    cut = max(1, len(train) // 10)
    val, train = train[:cut], train[cut:]

    for name, rows in (("train", train), ("val", val), ("test", test)):
        with open(OUT_DIR / f"hs_{name}.jsonl", "w", encoding="utf-8") as fh:
            fh.write("\n".join(to_jsonl(rows)) + "\n")
        with open(OUT_DIR / f"hs_{name}_meta.json", "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=2, ensure_ascii=False)

    def summarise(name: str, rows: list[dict[str, Any]]) -> None:
        pos = sum(1 for r in rows if not r["label_consistent"])
        pairs = len({r["pair_id"] for r in rows})
        print(f"  {name:<6} {len(rows):>5} examples  "
              f"{pos:>4} evasive / {len(rows)-pos:>4} honest  {pairs:>2} pairs")

    print(f"\nGenerated {len(examples)} unique examples -> {OUT_DIR}")
    summarise("train", train)
    summarise("val", val)
    summarise("test", test)

    train_pairs = {r["pair_id"] for r in train} | {r["pair_id"] for r in val}
    test_pairs = {r["pair_id"] for r in test}
    overlap = train_pairs & test_pairs
    print(f"\n  pair overlap train/test: {sorted(overlap) or 'NONE'}")
    if overlap:
        print("  LEAKAGE -- test pairs appear in training. Do not trust the eval.")
        return 1
    print("  No leakage: held-out goods never appear in training.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
