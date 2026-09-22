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

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from vf_logistics.schemas import AGENT_OUTPUT_SCHEMAS


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


def validate_result(
    agent: str, parsed: dict[str, Any] | None
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Check a parsed model reply against the schema registered for the agent.

    Returns (validated, error). On failure `validated` is None, which makes a
    schema violation indistinguishable downstream from a JSON parse failure --
    deliberately, because the two mean the same thing to a caller: there is no
    usable answer here. The existing handling for that case is already fail-safe:
    reconcile() sets `effective_risk = max(floor, 50)`, `score_disputed = True`
    and `auto_clear_permitted = False` when the score is missing, so a rejected
    reply can send a shipment to a human but never release one.

    An agent with no registered schema passes through unchanged rather than
    raising. That keeps the document and investigation agents working while their
    output shapes are still moving, and AGENT_OUTPUT_SCHEMAS is the one place to
    look to see which agents are covered.

    The validated model is returned as a plain dict, not a BaseModel. Every
    caller downstream -- the orchestrator, the store, the dashboard JSON -- reads
    this with .get(), and the case document has to be JSON-serialisable for
    Firestore. Handing back a model object would mean touching all of them for no
    gain.
    """
    if parsed is None:
        return None, None  # already an error upstream; don't mask it

    schema = AGENT_OUTPUT_SCHEMAS.get(agent)
    if schema is None:
        return parsed, None

    try:
        model = schema.model_validate(parsed)
    except ValidationError as exc:
        # One line per bad field, naming the field and what was wrong with it.
        # "validation failed" alone would leave a reviewer unable to tell a
        # malfunctioning model from a prompt that needs changing.
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}"
            for err in exc.errors()[:5]
        )
        return None, f"model reply failed {schema.__name__}: {problems}"

    return model.model_dump(mode="json"), None


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
    prompt: str | None = None,
    validate: bool = True,
    **ids: Any,
) -> dict[str, Any]:
    """
    Build the uniform response.

    `legacy_key` mirrors `result` under the field name the existing dashboard
    already reads, so this change does not break the single-agent view.

    `prompt` and `raw` are retained on every call, not only on a parse error.
    A reviewer auditing a decision needs to see the exact text the model was
    given and the exact text it returned; keeping them only when parsing failed
    meant the successful decisions -- the ones that actually released or held a
    shipment -- were the ones nobody could inspect. Both are truncated because
    they are stored on the case document, which has a size ceiling.

    Schema validation runs here, at the single point every agent already passes
    through, rather than being added to each agent separately -- an agent that
    forgot to call it would silently lose the guarantee. `schema_error` is set
    apart from `parse_error` so the two failure modes stay countable: JSON that
    would not parse is a formatting problem, JSON that parsed into the wrong
    shape is a model behaviour problem, and they call for different fixes.

    `validate=False` exists for callers holding something other than a single
    model reply -- the debate agent's envelope wraps a trace plus a verdict, and
    the verdict is validated on its own before it gets here.
    """
    schema_error: str | None = None
    if validate and error is None:
        result, schema_error = validate_result(agent, result)
        if schema_error:
            error = schema_error

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
        "raw": _truncate(raw, RAW_MAX_CHARS),
    }
    if schema_error:
        out["schema_error"] = True
    if prompt is not None:
        out["prompt"] = _truncate(prompt, PROMPT_MAX_CHARS)
        # Hashed from the FULL prompt, before _truncate. A hash of the stored
        # 4000-character excerpt would fingerprint the excerpt rather than what
        # the model was actually given, so two genuinely different prompts that
        # happened to share a prefix would hash identically -- useless as the
        # evidence an auditor needs that a specific prompt version produced a
        # specific decision.
        out["prompt_sha256"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    if error:
        out["error"] = error
    out[legacy_key] = result or {}
    return out


PROMPT_MAX_CHARS = 4000
RAW_MAX_CHARS = 4000


def _truncate(text: str | None, limit: int) -> str:
    """Clip long text, saying so rather than leaving a silent partial value."""
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n...[truncated, {len(text) - limit} more chars]"
