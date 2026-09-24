"""
Shared configuration for AI model selection and pricing.

Multi-model architecture, on Nebius Token Factory:
- Document intake: a vision model (Token Factory has no NVIDIA vision model yet)
- Fraud detection, compliance screening: NVIDIA Nemotron 3 Nano - fast, everyday
  calls, run on every shipment
- Investigation: NVIDIA Nemotron 3 Super (pinned separately in
  agents/investigation_agent.py) - reaches for more reasoning, but only on the
  cases that get escalated

This demonstrates strategic model selection based on task requirements, matching
the hackathon track's own guidance: "let Nano or Super handle the fast, everyday
calls; reach for Ultra when you need serious reasoning."
"""

import logging
import os
from threading import Lock

log = logging.getLogger(__name__)

_lock = Lock()
_model_id = os.getenv("NEMOTRON_MODEL", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B")
_vision_model_id = os.getenv("VISION_MODEL", "openbmb/MiniCPM-V-4_5")

# Model pricing per 1M tokens (USD)
# Source: Nebius Token Factory model catalog
PRICING = {
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B": {
        "input": 0.06,
        "output": 0.24,
        "name": "NVIDIA Nemotron 3 Nano",
        "description": "Budget - fast, everyday calls (fraud & compliance default)"
    },
    "nvidia/nemotron-3-super-120b-a12b": {
        "input": 0.30,
        "output": 0.90,
        "name": "NVIDIA Nemotron 3 Super",
        "description": "Balanced - stronger reasoning for investigation"
    },
    "nvidia/Nemotron-3-Ultra-550b-a55b": {
        "input": 1.00,
        "output": 3.00,
        "name": "NVIDIA Nemotron 3 Ultra",
        "description": "Serious reasoning - most capable, highest cost"
    },
    "openbmb/MiniCPM-V-4_5": {
        "input": 0.658,
        "output": 1.11,
        "name": "MiniCPM-V 4.5 (Vision)",
        "description": "Document intake - OCR/PDF understanding, multimodal"
    },
}

def get_model() -> str:
    """Get the current text model ID (fraud detection, compliance)."""
    return _model_id

def get_vision_model() -> str:
    """Get the current vision model ID (document intake)."""
    return _vision_model_id

# How much dearer a model may be than the current one before the switch needs saying so.
#
# `set_model()` validated against PRICING and nothing else, so every priced model was
# interchangeable by one authenticated POST -- including Ultra. That would land on
# fraud_detection and compliance, the two agents that run on EVERY case, as a runtime
# change with no deploy and nothing recorded. The tenant spend ceiling would eventually
# notice, hours and a lot of money later, because that check is soft and cached 5s.
#
# The arithmetic behind 5.0, on the blended input+output rate:
#
#     Nano   0.06 + 0.24 = 0.30   the default, so 1.0x
#     Super  0.30 + 0.90 = 1.20   4.0x   -- permitted
#     MiniCPM 0.658 + 1.11 = 1.77  5.9x  -- refused (and a vision model here is a
#                                            mistake regardless)
#     Ultra  1.00 + 3.00 = 4.00  13.3x   -- refused
#
# So the line falls between Super and Ultra, which is the useful place for it. Super on
# every case is a reasonable cost/quality trade an operator should be able to make from
# the console; Ultra on every case is a 13x bill that should require saying so out loud.
MAX_RATE_MULTIPLE_WITHOUT_OVERRIDE = float(
    os.getenv("MODEL_SWITCH_MAX_RATE_MULTIPLE", "5.0")
)


class CostlierModel(Exception):
    """
    Raised when a switch would raise the per-token rate beyond the allowed multiple.

    Carries the numbers so the caller can put them in the refusal rather than making
    the operator go and look them up.
    """

    def __init__(self, model: str, current: str, multiple: float, limit: float):
        self.model = model
        self.current = current
        self.multiple = multiple
        self.limit = limit
        super().__init__(
            f"{model} costs {multiple:.1f}x the current model ({current}) per token, "
            f"above the {limit:.1f}x limit for an unconfirmed switch"
        )


def cheapest_model() -> str:
    """
    The lowest blended rate in the table, used as the fixed baseline for a switch.

    A fixed baseline rather than the incumbent, because a relative comparison ratchets.
    Measured against the real rates: Nano -> Super is 4.0x and permitted, then
    Super -> Ultra is only 4.00/1.20 = 3.3x and also permitted -- so two ordinary
    requests put Ultra on fraud detection and compliance with no confirmation asked for
    at any point. Each step looked reasonable; the destination was not.
    """
    return min(PRICING, key=lambda m: PRICING[m]["input"] + PRICING[m]["output"])


def rate_multiple(model: str, against: str | None = None) -> float:
    """
    How many times dearer `model` is than `against`, on a blended input+output basis.

    Defaults to the CHEAPEST priced model rather than the current one; see
    cheapest_model() for why. Pass `against` explicitly to compare two models directly.

    Blended rather than input-only because the two rates do not scale together: Ultra
    is 16.7x Nano on input and 12.5x on output, and picking either alone would
    misreport the switch. Weighted 1:1, which is close to the measured mix -- 198,840
    input against 137,307 output tokens on a 20-case run.
    """
    baseline = PRICING.get(against or cheapest_model())
    if baseline is None:
        baseline = PRICING[cheapest_model()]
    target = PRICING.get(model)
    if target is None:
        return float("inf")
    base = (baseline["input"] + baseline["output"]) or 1e-9
    return (target["input"] + target["output"]) / base


def set_model(model: str, *, allow_costlier: bool = False) -> bool:
    """
    Set the text model ID. Returns False if model is not in PRICING.

    Raises CostlierModel when the switch would put the per-token rate beyond
    MAX_RATE_MULTIPLE_WITHOUT_OVERRIDE of the cheapest available model and
    `allow_costlier` is not set. A refusal is not a judgement that the switch is wrong
    -- it is a requirement that it be deliberate, because this model is used by the two
    agents that run on every case and the change takes effect on the next shipment with
    nothing recorded.

    The check is inside the lock with the assignment. Outside it, two concurrent
    switches could both read the old rate, both pass, and the second could land a model
    the first would have made ineligible.
    """
    global _model_id
    if model not in PRICING:
        return False

    # Absolute, not relative to the incumbent. See cheapest_model().
    multiple = rate_multiple(model)
    with _lock:
        if multiple > MAX_RATE_MULTIPLE_WITHOUT_OVERRIDE and not allow_costlier:
            log.error(
                "MODEL SWITCH REFUSED model=%s current=%s multiple=%.1fx limit=%.1fx "
                "-- this model is used by fraud detection and compliance, which run on "
                "every shipment. Pass allow_costlier to confirm.",
                model, _model_id, multiple, MAX_RATE_MULTIPLE_WITHOUT_OVERRIDE,
            )
            raise CostlierModel(
                model, _model_id, multiple, MAX_RATE_MULTIPLE_WITHOUT_OVERRIDE,
            )

        if multiple > rate_multiple(_model_id):
            # Logged even when permitted. A switch that raises the bill should be
            # findable afterwards, and the audit trail does not cover configuration.
            log.warning(
                "MODEL SWITCH model=%s current=%s multiple=%.1fx confirmed=%s",
                model, _model_id, multiple, allow_costlier,
            )

        _model_id = model
    return True

def get_pricing() -> dict:
    """Get pricing info for current model."""
    return PRICING.get(_model_id, PRICING["nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"])

def pricing_for(model: str | None) -> dict:
    """
    Get pricing for a specific model id.

    Cost must be computed per step, not per project: the investigation agent runs
    on Nemotron Super at a different rate than fraud/compliance's Nano, so pricing
    every token at the currently selected model's rate would misreport the bill.

    AN UNKNOWN ID IS LOGGED AT ERROR, and the reason is the direction of the error.
    The fallback is Nano, the CHEAPEST entry in the table, so an unpriced model
    under-reports spend rather than over-reporting it. That protects the customer's
    invoice and endangers the operator's budget: `budget.assert_within_budget()`
    reads these same figures, so an unpriced model makes the spend ceiling leak.
    Silence here would make a leaking ceiling look like a cheap month.

    This is reachable in production. `set_model()` refuses anything absent from
    PRICING, but `_model_id` is read straight from the NEMOTRON_MODEL environment
    variable with no such check, so a deployment can be pointed at an unpriced model
    -- `nvidia/Nemotron-3_5-Lightning` is servable on Token Factory today and is not
    in this table -- or simply at a typo.
    """
    if not model:
        return PRICING["nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"]
    known = PRICING.get(model)
    if known is None:
        log.error(
            "UNPRICED MODEL model=%s -- billing this call at the cheapest rate in "
            "the table (Nemotron 3 Nano). Reported spend is too LOW, and the tenant "
            "spend ceiling reads the same figure. Add it to config.PRICING.",
            model,
        )
        return PRICING["nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"]
    return known


def model_label(model: str | None) -> str:
    """
    Human-readable name for a model id, for strings a person will read.

    Deliberately NOT `pricing_for(model)["name"]`: that logs at ERROR on an unknown
    id, which is right when money is being computed and wrong when a label is being
    rendered. Calling it here would emit a spurious billing error every time an
    event line is written, and duplicate the one the cost path already emits.

    An unknown id falls back to the id itself rather than to a guess. That matters
    for the reason this function exists at all: `orchestrator.py` used to hard-code
    "Super" into the auto-debate event string while the hop ran Ultra, and
    `debate_agent.py` records that the same comment-vs-constant drift had already
    been copied into the README, the architecture diagram and the Devpost
    submission. A wrong name is worse than a raw id, because a raw id cannot be
    mistaken for a claim.
    """
    if not model:
        return "an unnamed model"
    entry = PRICING.get(model)
    if entry is None:
        return model
    return str(entry.get("name") or model)


def warn_on_unpriced_selection() -> list[str]:
    """
    Report any configured model that has no entry in PRICING.

    Called at startup so an unpriced model is found when the service boots rather
    than a month later in a billing reconciliation. Returns the offending ids so a
    caller can decide how loud to be; logs each one regardless.

    Deliberately does NOT refuse to start. A wrong rate is a billing defect, not a
    safety one, and taking a working service offline over it would be the larger
    outage. Contrast auth.py, which does halt the boot when the anonymous role
    grants write -- that one is a breach, not an accounting error.
    """
    offenders = [
        model for model in (_model_id, _vision_model_id) if model not in PRICING
    ]
    for model in offenders:
        log.error(
            "UNPRICED MODEL CONFIGURED model=%s -- every call will be costed at the "
            "cheapest rate in config.PRICING, so spend will be under-reported and "
            "the tenant spend ceiling will not hold. Add it to config.PRICING.",
            model,
        )
    return offenders

def get_all_models() -> list[dict]:
    """Get list of all available models with their info."""
    return [
        {"id": model_id, **info}
        for model_id, info in PRICING.items()
    ]
