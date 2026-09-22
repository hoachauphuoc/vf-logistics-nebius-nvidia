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

def set_model(model: str) -> bool:
    """Set the text model ID. Returns False if model is not in PRICING."""
    global _model_id
    if model not in PRICING:
        return False
    with _lock:
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
