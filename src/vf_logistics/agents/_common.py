"""
Shared helpers for the three agents.

Centralises three things that were previously duplicated or missing:
  * a uniform response envelope, so callers stop guessing between
    `analysis` / `screening_result` / `investigation_result`
  * server-side JSON parsing, so the browser and the orchestrator receive
    objects instead of a string that has to be parsed a second time
  * per-call latency, which the dashboard and the demo video both need
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Any


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_model_json(text: str) -> tuple[dict[str, Any] | None, str | None]:
    """
    Turn a model reply into a dict.

    The agents all set response_mime_type="application/json", so the happy path
    is a straight json.loads. The fallbacks cover the two ways that still
    occasionally breaks: a ```json fenced block, or prose wrapped around the
    object. Returns (parsed, error_message).
    """
    if text is None:
        return None, "empty response"

    raw = text.strip()
    if not raw:
        return None, "empty response"

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed, None
        return {"value": parsed}, None
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(.+?)```", raw, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip()), None
        except json.JSONDecodeError:
            pass

    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start : end + 1]), None
        except json.JSONDecodeError:
            pass

    return None, "model reply was not valid JSON"


class Timer:
    """Wall-clock timer for a single model call."""

    def __enter__(self) -> Timer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        self.ms = int((time.perf_counter() - self._start) * 1000)


def envelope(
    *,
    agent: str,
    model: str,
    result: dict[str, Any] | None,
    error: str | None,
    raw: str,
    latency_ms: int,
    legacy_key: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    **ids: Any,
) -> dict[str, Any]:
    """
    Build the uniform response.

    `legacy_key` mirrors `result` under the field name the existing dashboard
    already reads, so this change does not break the single-agent view.
    """
    out: dict[str, Any] = {
        **ids,
        "agent": agent,
        "result": result or {},
        "model": model,
        "latency_ms": latency_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "at": utcnow(),
        "parse_error": error is not None,
    }
    if error:
        out["error"] = error
        out["raw"] = raw
    out[legacy_key] = result or {}
    return out
