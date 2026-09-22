"""
Chain-of-thought prompting for HS classification consistency.

Why this module exists
----------------------
The first evaluation of hs_classifier_agent produced a result worth taking
seriously: naive few-shot prompting made the model *worse* at the job. Recall on
the evasive cases fell from 40.0% (base Nemotron Nano) to 26.7% (the same model
with two worked examples), while the false positive rate halved. Two input/output
examples did not teach the model to classify; they taught it to be cautious, and
caution is the wrong bias for a fraud control.

Meanwhile the teacher, Nemotron Super, reached 100% recall with no examples at
all. So the capability is real and the labels are right -- what was missing was a
way to get the smaller model to actually use its own capability.

Two things in the original prompt look like the cause, and this module addresses
both so their effects can be told apart.

1. Field order. In SYSTEM_PROMPT the output schema puts `consistent` first and
   `reasoning` second to last. A decoder emits tokens in order, so the model had
   to commit to true/false *before* writing a single word of analysis, and
   whatever it wrote afterwards could only rationalise a verdict already fixed.
   The schema here is deliberately inverted: the goods are named, the obfuscation
   is named, and the covering heading is chosen, and only then is `consistent`
   emitted -- by which point the answer is mechanically determined by a field the
   model has already written.

2. What the examples teach. The exemplars below carry the reasoning chain, not
   just the answer, so what is demonstrated is the procedure rather than the
   verdict distribution.

Leakage
-------
The evaluation test set is built from the same `data/hs_pairs.yaml` entries that
seeded training data, so exemplars drawn from that file could hand the model the
answer to the very case being graded. `build_exemplars()` therefore does
leave-one-out selection:

  * an evasive case from pair *i* never sees an exemplar built from pair *i*;
  * an honest case declaring heading *h* never sees an exemplar whose declared
    heading is *h*.

The pool is ordered so that dropping an entry still leaves a label-balanced
selection. An exemplar set that skewed toward "inconsistent" would buy recall by
inflating the false positive rate, which is the failure mode this module was
written to avoid in the first place.

The `cot_zero` mode has no exemplars at all and therefore cannot leak under any
argument. It is the cleanest of the measurements and should be read first.
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml

PAIRS_FILE = pathlib.Path(__file__).resolve().parents[3] / "data" / "hs_pairs.yaml"

EXEMPLAR_COUNT = 6


# --------------------------------------------------------------------------
# The method
# --------------------------------------------------------------------------

# Written as an ordered procedure rather than a description of the task, because
# the field order in the schema below *is* the procedure. Each step's output is
# the next step's input, and the verdict falls out of step 5 rather than being
# guessed at the start.
COT_SYSTEM = """\
You are a customs classification specialist. You are given a plain-language
description of goods and the Harmonized System heading the exporter declared for
them. Decide whether the description is consistent with that heading.

What you are looking for is misclassification that conceals export-control
exposure: goods belonging to a controlled heading, declared under an adjacent
benign one. The declarant chooses the code, so the code cannot be trusted; the
description is the evidence.

Method. Emit the JSON fields in exactly the order listed. The order is the
method. You name the goods before you judge them, because a heading is chosen
from what the goods are, never from what the paperwork claims they are.

1. goods_as_described -- restate the cargo in plain trade terms. Obfuscation is
   expected and you must undo it: repair misspellings, replace an unusual synonym
   with the ordinary word, compress a circumlocution into the thing it is
   circling, translate any foreign-language fragment, and when the description
   lists parts, say what the assembled item is. Describe what an inspector would
   see on opening the crate.

2. obfuscation_observed -- which single move you had to undo: "misspelling",
   "synonym", "circumlocution", "component_split", "mixed_language", or "none".

3. heading_for_goods -- working only from step 1 and ignoring the declared code
   entirely, give the 4-digit heading that covers those goods.

4. reasoning -- one or two sentences naming the specific item that decided it.

5. confidence -- 0.0 to 1.0, how firm step 3 is.

6. declared_hs -- the heading you were given, copied.

7. suggested_hs -- step 3 when it differs from step 6, null when they agree.

8. consistent -- true when step 3 equals step 6, false otherwise. The work is
   already done by this point; this field only reports it.

Calibration. Ordinary commercial cargo is the common case and must come back
consistent. A residual heading or a parts heading is not suspicious on its own --
plenty of honest shipments belong in one. Flagging legitimate freight has a real
cost and is not a safe default.

Return only the JSON object.\
"""

# The closing instruction differs from the base arm's ("Is the description
# consistent with the declared heading?"), which invites an immediate yes/no and
# would work against everything above. Recorded here so the comparison is not
# reported as a single-variable experiment when it is not: the cot arms change
# the system prompt and this line together.
COT_USER_SUFFIX = "Work through the method and return the JSON."


# --------------------------------------------------------------------------
# Exemplars
# --------------------------------------------------------------------------

# Each entry is tagged with the pair index it was built from so it can be held
# out. The descriptions are written for this dataset -- they are not drawn from
# the generated training data, so a fine-tuned model cannot have memorised them.
#
# The pool alternates inconsistent and consistent so that any prefix of it is
# roughly label-balanced.
_POOL: list[dict[str, Any]] = [
    {
        "pair": 10,
        "description": "Gas centrafuge rotor assemblies, maraging steel, balanced, for isotopic enrichement cascade, 40 units",
        "declared_hs": "8421",
        "answer": {
            "goods_as_described": "Gas centrifuge rotor assemblies in maraging steel, intended for an isotope enrichment cascade",
            "obfuscation_observed": "misspelling",
            "heading_for_goods": "8479",
            "reasoning": "Maraging steel rotors for an enrichment cascade are isotope separation equipment, which 8479 covers by name; 8421 covers ordinary separating and filtering centrifuges.",
            "confidence": 0.94,
            "declared_hs": "8421",
            "suggested_hs": "8479",
            "consistent": False,
        },
    },
    {
        "pair": 5,
        "description": "Granite surface plate with dial indicator stand, for shop floor flatness checking",
        "declared_hs": "9031",
        "answer": {
            "goods_as_described": "A granite reference surface plate and a dial indicator stand used to check flatness of workpieces",
            "obfuscation_observed": "none",
            "heading_for_goods": "9031",
            "reasoning": "A surface plate and indicator stand are checking instruments not specified in any earlier heading, which is what 9031 is for.",
            "confidence": 0.9,
            "declared_hs": "9031",
            "suggested_hs": None,
            "consistent": True,
        },
    },
    {
        "pair": 0,
        "description": "Rotating assemblies that turn a stream of combusted fuel into shaft power, incorporating cooled first-stage blading in nickel superalloy",
        "declared_hs": "8414",
        "answer": {
            "goods_as_described": "Gas turbine rotating assemblies with cooled first-stage turbine blades in nickel superalloy",
            "obfuscation_observed": "circumlocution",
            "heading_for_goods": "8411",
            "reasoning": "Converting combusted fuel flow into shaft power with cooled first-stage blading describes a gas turbine, which is 8411; 8414 covers pumps, compressors and fans, which add no energy by combustion.",
            "confidence": 0.93,
            "declared_hs": "8414",
            "suggested_hs": "8411",
            "consistent": False,
        },
    },
    {
        "pair": 13,
        "description": "Spare relay sockets, crimp terminals and terminal blocks, mixed sizes, for conveyor control panel repairs",
        "declared_hs": "8548",
        "answer": {
            "goods_as_described": "Assorted electrical accessories -- relay sockets, crimp terminals and terminal blocks -- held as repair spares",
            "obfuscation_observed": "none",
            "heading_for_goods": "8548",
            "reasoning": "Mixed low-value electrical parts with no single machine function fall to the residual electrical parts heading 8548.",
            "confidence": 0.85,
            "declared_hs": "8548",
            "suggested_hs": None,
            "consistent": True,
        },
    },
    {
        "pair": 2,
        "description": "Kit comprising bare substrate carrier, thermal interface shim, retention frame, and one packaged logic die rated 400W TDP",
        "declared_hs": "8543",
        "answer": {
            "goods_as_described": "A packaged high-power logic processor shipped together with its carrier, shim and retention hardware -- assembled, a processor module",
            "obfuscation_observed": "component_split",
            "heading_for_goods": "8542",
            "reasoning": "Listing the carrier and shim separately does not change what is being shipped: a packaged logic die at 400W is an electronic integrated circuit under 8542.",
            "confidence": 0.9,
            "declared_hs": "8543",
            "suggested_hs": "8542",
            "consistent": False,
        },
    },
    {
        "pair": 6,
        "description": "Alcohol-in-glass laboratory thermometers, -10 to 110 C, box of 50",
        "declared_hs": "9025",
        "answer": {
            "goods_as_described": "Liquid-in-glass laboratory thermometers covering -10 to 110 degrees C",
            "obfuscation_observed": "none",
            "heading_for_goods": "9025",
            "reasoning": "Thermometers are named explicitly in 9025 alongside hydrometers and barometers.",
            "confidence": 0.96,
            "declared_hs": "9025",
            "suggested_hs": None,
            "consistent": True,
        },
    },
    {
        "pair": 12,
        "description": "Iridium-192 \u5bc6\u5c01\u7ebf\u6e90, activity 10 Ci, trong v\u1ecf ch\u00ec v\u1eadn chuy\u1ec3n",
        "declared_hs": "9022",
        "answer": {
            "goods_as_described": "A sealed Iridium-192 radioactive source of about 10 Ci, supplied in a lead transport shield",
            "obfuscation_observed": "mixed_language",
            "heading_for_goods": "2844",
            "reasoning": "What is shipped is the radioactive isotope itself as a sealed source, which is 2844; 9022 would cover the radiography apparatus the source is later loaded into, not the source.",
            "confidence": 0.92,
            "declared_hs": "9022",
            "suggested_hs": "2844",
            "consistent": False,
        },
    },
    {
        "pair": 8,
        "description": "Computer-directed turning centre for chip-forming metal shaping, 4-axis, 2 micron repeatability",
        "declared_hs": "8462",
        "answer": {
            "goods_as_described": "A numerically controlled lathe -- a turning centre that removes metal as chips -- with 4 axes and 2 micron repeatability",
            "obfuscation_observed": "synonym",
            "heading_for_goods": "8458",
            "reasoning": "Turning with chip formation is metal removal, so this is a numerically controlled lathe under 8458; 8462 covers forming by forging, bending or punching, which removes no material.",
            "confidence": 0.93,
            "declared_hs": "8462",
            "suggested_hs": "8458",
            "consistent": False,
        },
    },
]

# Emitted in the schema order so the demonstration matches the instruction. json
# with sorted keys or python dict order would both break that, so the order is
# written out explicitly.
_FIELD_ORDER = (
    "goods_as_described",
    "obfuscation_observed",
    "heading_for_goods",
    "reasoning",
    "confidence",
    "declared_hs",
    "suggested_hs",
    "consistent",
)


def _render(answer: dict[str, Any]) -> str:
    import json

    ordered = {k: answer[k] for k in _FIELD_ORDER}
    return json.dumps(ordered, ensure_ascii=False)


def build_exemplars(
    *,
    exclude_pair: int | None = None,
    exclude_heading: str | None = None,
    count: int = EXEMPLAR_COUNT,
) -> tuple[str, list[int]]:
    """
    Render worked examples, holding out anything that would leak the answer.

    Returns the prompt fragment and the pair indices actually used, so a caller
    can record which exemplars a given measurement saw. Selection is a stable
    prefix of the pool rather than a sample, because an exemplar set that varies
    between runs cannot be attributed.
    """
    chosen: list[dict[str, Any]] = []
    for ex in _POOL:
        if exclude_pair is not None and ex["pair"] == exclude_pair:
            continue
        if exclude_heading is not None and ex["declared_hs"] == exclude_heading:
            continue
        chosen.append(ex)
        if len(chosen) == count:
            break

    if not chosen:
        return "", []

    blocks = [
        "\n\nWorked examples. Note that the fields are written in the order given"
        " by the method, and that the verdict comes last.\n"
    ]
    for ex in chosen:
        blocks.append(
            f"\nDescription: \"{ex['description']}\"\n"
            f"Declared heading: {ex['declared_hs']}\n"
            f"{_render(ex['answer'])}\n"
        )
    return "".join(blocks), [ex["pair"] for ex in chosen]


def load_pairs() -> dict[str, Any]:
    with open(PAIRS_FILE, encoding="utf-8") as fh:
        return yaml.safe_load(fh)
