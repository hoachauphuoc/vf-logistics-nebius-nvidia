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

import os
from threading import Lock

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
    """
    if not model:
        return PRICING["nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"]
    return PRICING.get(model, PRICING["nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"])

def get_all_models() -> list[dict]:
    """Get list of all available models with their info."""
    return [
        {"id": model_id, **info}
        for model_id, info in PRICING.items()
    ]
