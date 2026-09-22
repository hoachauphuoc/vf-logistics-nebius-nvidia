"""
HS classification consistency agent.

The deterministic checks in verifier.py cannot do this job, and the reason is
structural rather than a gap in their configuration. check_hs_code() reads
shipment["hs_code"] and compares it against DUAL_USE_HS_PREFIXES;
cargo_description appears exactly once in that whole module, as a presence check.
So a declarant who writes a benign heading over controlled goods passes the
dual-use check outright, and no amount of adding prefixes to the list fixes it,
because the declarant is the one choosing the code.

Deciding whether a plain-language description of goods matches a declared tariff
heading is a semantic judgement. That is what this agent is for, and it is the
only thing it is for -- freight ratios, value density and sanctions lists stay in
verifier.py where they are exact and free.

The model is a parameter rather than a module constant so the evaluation harness
can put base, few-shot and fine-tuned variants side by side in one process.
"""

from __future__ import annotations

import os
from typing import Any

from vf_logistics import config as model_config
from vf_logistics import hs_reference, nebius_client
from . import hs_cot
from ._common import Timer, envelope, parse_model_json

# base      -- instruction only, verdict field emitted first
# few_shot  -- base plus two input/output examples. Measured WORSE than base
#              (recall 26.7% vs 40.0%); kept so the regression stays visible
#              rather than being quietly dropped from the comparison.
# cot_zero  -- ordered method, verdict emitted last, no examples at all
# cot       -- cot_zero plus worked examples carrying the reasoning chain
# cot_ref   -- cot_zero plus the nomenclature extract. Added after cot_zero's
#              own reasoning showed the failures were confabulated heading
#              contents anchored on the declared code, not bad reasoning.
# cot_strict -- cot_ref with the exclusion notes stripped from the reference.
#              This is the one to quote: the exclusion notes were written with
#              the test pairs in view, so cot_ref cannot be told apart from
#              having been handed the answers. cot_strict sees only published
#              heading contents.
# cot_full  -- method, examples and reference together
MODES = ("base", "few_shot", "cot_zero", "cot", "cot_ref", "cot_strict", "cot_full")

# Falls back to whatever the shared registry currently serves, so this agent
# tracks the configured model unless a caller overrides it.
DEFAULT_MODEL = os.getenv("HS_CLASSIFIER_MODEL", "").strip()


def get_model_id() -> str:
    return DEFAULT_MODEL or model_config.get_model()


SYSTEM_PROMPT = """\
You are a customs classification specialist. You are given a plain-language
description of goods and the Harmonized System heading the exporter declared for
them. Decide whether the description is consistent with that heading.

You are looking for misclassification that conceals export-control exposure. The
pattern to catch is goods that belong to a controlled heading being declared
under an adjacent benign heading -- for example gas turbine components (8411)
declared as air compressors (8414), or enrichment centrifuges (8479) declared as
filtering machinery (8421).

Judge the goods as described, not the wording. Obfuscation is expected:
deliberate misspelling, an unusual synonym, a circumlocution, a description split
into individually harmless components, or a description mixing languages. See
through it and classify what the goods actually are.

Be precise in both directions. A description that genuinely belongs to the
declared heading must be reported as consistent. Flagging ordinary commercial
cargo is a real cost, not a safe default.

Return only JSON:
{
  "consistent": true or false,
  "declared_hs": "the 4-digit heading given to you",
  "suggested_hs": "the 4-digit heading the goods belong to, or null if consistent",
  "confidence": 0.0 to 1.0,
  "reasoning": "one or two sentences naming the specific goods that decided it",
  "obfuscation_observed": "misspelling" | "synonym" | "circumlocution" | "component_split" | "mixed_language" | "none"
}\
"""

# Two worked examples, one in each direction. Kept to two on purpose: the point
# of the few-shot arm in the evaluation is to measure what prompting alone buys
# before any training, so it has to stay a prompt rather than becoming a
# retrieval system.
FEW_SHOT = """\

Worked examples.

Description: "Rotor assemblies and hot section segments for industrial power units, nickel alloy"
Declared heading: 8414
{"consistent": false, "declared_hs": "8414", "suggested_hs": "8411", "confidence": 0.88, "reasoning": "Hot section segments and nickel alloy rotor assemblies are gas turbine components, not air compressor parts.", "obfuscation_observed": "circumlocution"}

Description: "Industrial ventilation fans, 600mm axial, for warehouse air circulation"
Declared heading: 8414
{"consistent": true, "declared_hs": "8414", "suggested_hs": null, "confidence": 0.95, "reasoning": "Axial ventilation fans sit squarely in 8414 alongside air pumps and compressors.", "obfuscation_observed": "none"}\
"""


async def classify_hs(
    cargo_description: str,
    declared_hs: str,
    *,
    model: str | None = None,
    few_shot: bool = False,
    mode: str | None = None,
    exclude_pair: int | None = None,
    exclude_heading: str | None = None,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """
    Judge whether a goods description matches the declared tariff heading.

    `model` overrides the registry, which is what lets one process evaluate
    several variants. `temperature` defaults to 0 because this is a
    classification, and a classification that changes between identical runs
    cannot be measured.

    `mode` selects the prompting strategy; see MODES. `few_shot=True` is the
    old spelling of `mode="few_shot"` and still works so existing callers and
    saved evaluation runs stay comparable.

    `exclude_pair` and `exclude_heading` are leakage controls for the cot mode
    and are forwarded to hs_cot.build_exemplars(). They do nothing in the other
    modes, which carry no exemplars drawn from the pair file.
    """
    if mode is None:
        mode = "few_shot" if few_shot else "base"
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {MODES}")

    model_id = model or get_model_id()
    exemplar_pairs: list[int] = []

    if mode == "base":
        system = SYSTEM_PROMPT
        closing = "Is the description consistent with the declared heading?"
    elif mode == "few_shot":
        system = SYSTEM_PROMPT + FEW_SHOT
        closing = "Is the description consistent with the declared heading?"
    else:
        system = hs_cot.COT_SYSTEM
        closing = hs_cot.COT_USER_SUFFIX
        if mode in ("cot", "cot_full"):
            fragment, exemplar_pairs = hs_cot.build_exemplars(
                exclude_pair=exclude_pair, exclude_heading=exclude_heading,
            )
            system += fragment
        if mode in ("cot_ref", "cot_full"):
            system += hs_reference.reference_block(include_excludes=True)
        elif mode == "cot_strict":
            system += hs_reference.reference_block(include_excludes=False)

    # Delimited so that instruction-looking text inside a cargo description is
    # read as cargo data. untrusted.screen_text() is the actual defence against
    # injection; this only stops accidental prompt bleed.
    user_text = (
        "<<<BEGIN GOODS RECORD>>>\n"
        f"Description: {cargo_description}\n"
        f"Declared heading: {declared_hs}\n"
        "<<<END GOODS RECORD>>>\n\n"
        f"{closing}"
    )

    with Timer() as timer:
        text, input_tokens, output_tokens = await nebius_client.complete_json(
            model=model_id,
            system_prompt=system,
            user_text=user_text,
            temperature=temperature,
        )

    parsed, error = parse_model_json(text)
    out = envelope(
        agent="hs_classifier",
        model=model_id,
        result=parsed,
        error=error,
        raw=text,
        latency_ms=timer.ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        legacy_key="hs_classification",
        prompt=user_text,
    )
    out["few_shot"] = mode == "few_shot"
    out["mode"] = mode
    if exemplar_pairs:
        out["exemplar_pairs"] = exemplar_pairs
    return out


def interpret(result: dict[str, Any]) -> dict[str, Any]:
    """
    Reduce a model reply to the fields a caller can act on.

    A reply that failed to parse, or that omits `consistent`, is reported as
    `verdict: "unknown"` rather than being coerced to either outcome. Treating an
    unparseable reply as "consistent" would silently clear the exact cases this
    agent exists to catch; treating it as "inconsistent" would let a model
    outage flood the review queue. The caller decides.
    """
    payload = result.get("result") or {}
    consistent = payload.get("consistent")

    if not isinstance(consistent, bool):
        return {
            "verdict": "unknown",
            "suggested_hs": None,
            "confidence": 0.0,
            "reasoning": payload.get("reasoning") or result.get("error") or "no verdict returned",
            "obfuscation": None,
        }

    # In the cot schema the covering heading is chosen at step 3 and only copied
    # into suggested_hs at step 7, so a reply can name the right heading and
    # still leave suggested_hs null. Falling back to it costs nothing in the
    # other modes, whose schema has no heading_for_goods field to fall back to.
    suggested = payload.get("suggested_hs")
    if suggested in (None, "") and consistent is False:
        suggested = payload.get("heading_for_goods")
    if suggested is not None:
        suggested = "".join(ch for ch in str(suggested) if ch.isdigit())[:4] or None

    try:
        confidence = max(0.0, min(1.0, float(payload.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0

    return {
        "verdict": "consistent" if consistent else "inconsistent",
        "suggested_hs": suggested,
        "confidence": confidence,
        "reasoning": str(payload.get("reasoning") or "")[:400],
        "obfuscation": payload.get("obfuscation_observed"),
    }


def get_agent_info() -> dict[str, Any]:
    return {
        "name": "VF Logistics HS Classification Agent",
        "version": "1.0.0",
        "model": get_model_id(),
        "purpose": (
            "Detect goods declared under a benign tariff heading to conceal "
            "export-control exposure -- the one judgement the deterministic "
            "checks in verifier.py cannot make."
        ),
        "capabilities": [
            "hs_description_consistency",
            "obfuscation_detection",
            "suggested_reclassification",
        ],
    }
