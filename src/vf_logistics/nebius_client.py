"""
Nebius Token Factory client.

Token Factory exposes an OpenAI-compatible chat completions API, so this is a
thin wrapper around `openai.AsyncOpenAI` rather than a bespoke SDK. Two helpers
cover everything the seven agents need:

  * complete_json         - text-only prompt, JSON-mode response (fraud,
                             compliance, investigation, hs_classifier, zero_day
                             and debate agents)
  * complete_vision_json  - a document image/PDF page plus a text prompt,
                             JSON-mode response (document intake agent)

Both return (text, input_tokens, output_tokens) so the caller can plug the
result straight into agents/_common.py's parse_model_json()/envelope().

Retries
-------
Every call goes through _with_retry(), which is bounded by a deadline rather than
only by an attempt count. The attempt count alone is not enough: three attempts
at a 45 second request timeout is 135 seconds, and app.py:171-174 gives the whole
request 120 seconds on the worker thread. A caller that blew that budget would be
killed mid-retry and the customer would see a dead request instead of a case in
the review queue -- the exact outcome the retry was added to prevent.

Only transport-level and server-side failures are retried. A 400 or a 401 will
fail identically on the second attempt, so retrying them wastes the budget that a
genuinely transient failure needs.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import random
import time
from typing import Any, Awaitable, Callable, TypeVar

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)

from vf_logistics import budget

log = logging.getLogger(__name__)

NEBIUS_BASE_URL = os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/")
NEBIUS_API_KEY = os.getenv("NEBIUS_API_KEY", "")

# Per-request ceiling. The SDK default is 600s, long enough for one hung call to
# consume the entire worker budget on its own.
REQUEST_TIMEOUT_SECONDS = float(os.getenv("NEBIUS_REQUEST_TIMEOUT", "45"))

# Total wall-clock allowance for all attempts combined, deliberately under the
# 120s worker timeout so the caller gets a real answer -- success or a routable
# failure -- rather than being cut off.
RETRY_BUDGET_SECONDS = float(os.getenv("NEBIUS_RETRY_BUDGET", "90"))

MAX_ATTEMPTS = int(os.getenv("NEBIUS_MAX_ATTEMPTS", "3"))
BACKOFF_BASE_SECONDS = 1.0

# Worth another attempt: the request was well formed and the failure was in the
# network or on the far side.
_RETRYABLE = (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError)

_client: AsyncOpenAI | None = None

T = TypeVar("T")


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, _RETRYABLE):
        return True
    # Any other 5xx. A 4xx is the caller's fault and will fail again identically.
    if isinstance(exc, APIStatusError):
        return exc.status_code >= 500
    return False


async def _with_retry(label: str, call: Callable[[], Awaitable[T]]) -> T:
    """
    Run `call`, retrying transient failures until attempts or the deadline run out.

    Raises the last exception when it gives up. Raising rather than returning a
    sentinel is deliberate: each agent already runs inside a try/Timer structure
    that turns an exception into an envelope carrying `error`, and the orchestrator
    routes that to a human. Inventing a fake successful response here would put a
    made-up number into a compliance decision.

    Also the one place every model call in this service passes through, which is why
    the tenant spend ceiling is enforced here rather than at each of the nine agent
    call sites. Checked once per logical call, not once per retry: a retry is the
    same billable intent, and refusing halfway through a backoff sequence would
    abandon a call that has already been paid for.
    """
    # Before the first attempt and before any token is spent. BudgetExceeded is not
    # retryable and is deliberately allowed to propagate untouched -- the agent's
    # own try/except turns it into an error envelope, and the orchestrator routes
    # the case to a human rather than silently dropping it.
    await budget.assert_within_budget()

    deadline = time.monotonic() + RETRY_BUDGET_SECONDS
    last: BaseException | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return await call()
        except Exception as exc:  # noqa: BLE001 - re-raised below
            last = exc
            if not _is_retryable(exc):
                raise
            if attempt == MAX_ATTEMPTS:
                break

            # Jittered exponential backoff. Without jitter a batch of shipments
            # failing together would retry in lockstep and rate-limit itself.
            delay = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
            delay += random.uniform(0, delay * 0.25)

            remaining = deadline - time.monotonic()
            if remaining <= delay:
                log.warning(
                    "%s: giving up after attempt %d, retry budget exhausted (%s: %s)",
                    label, attempt, type(exc).__name__, exc,
                )
                break

            log.warning(
                "%s: attempt %d failed (%s), retrying in %.1fs",
                label, attempt, type(exc).__name__, delay,
            )
            await asyncio.sleep(delay)

    assert last is not None
    raise last


def get_client() -> AsyncOpenAI:
    """Lazily build the client so import doesn't fail before NEBIUS_API_KEY is set."""
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=NEBIUS_BASE_URL,
            api_key=NEBIUS_API_KEY,
            timeout=REQUEST_TIMEOUT_SECONDS,
            # The SDK's own retries are disabled so there is one retry policy
            # rather than two multiplying together -- 2 SDK retries inside 3 of
            # ours is 6 calls and 6x the budget.
            max_retries=0,
        )
    return _client


def _usage(response) -> tuple[int, int]:
    usage = getattr(response, "usage", None)
    if not usage:
        return 0, 0
    input_t = getattr(usage, "prompt_tokens", 0) or 0
    output_t = getattr(usage, "completion_tokens", 0) or 0
    return input_t, output_t


def _note_truncation(label: str, response: Any, max_tokens: int | None) -> None:
    """
    Log loudly when a reply was cut off at the output ceiling.

    `finish_reason: "length"` is Token Factory's documented truncation signal, and it
    is the difference between two failures that look identical downstream. A truncated
    JSON object does not parse, so `parse_model_json` reports "model reply was not
    valid JSON" -- which reads as a model quality problem when the actual cause is that
    the reply was longer than the ceiling allowed. One calls for a prompt change, the
    other for a larger number.

    Worth logging even though the ceilings have generous headroom, because this is how
    a ceiling that is too tight announces itself. Measured on a 20-case run before any
    ceiling existed, two calls returned exactly 8,192 output tokens and both failed to
    parse -- 8,192 being the provider's own default when `max_tokens` is omitted, not a
    model limit. Without this log, the same event under an explicit ceiling would look
    like the model got worse.
    """
    try:
        reason = response.choices[0].finish_reason
    except (AttributeError, IndexError):
        return
    if reason != "length":
        return
    log.error(
        "OUTPUT TRUNCATED AT CEILING %s finish_reason=length max_tokens=%s -- the "
        "reply was cut off, so any JSON in it is incomplete and will be reported as a "
        "parse failure. Raise the ceiling if this is legitimate output; investigate a "
        "runaway if it is not.",
        label, max_tokens if max_tokens is not None else "8192 (provider default)",
    )


def _ceiling(max_tokens: int | None) -> dict[str, int]:
    """
    Render `max_tokens` as kwargs, omitting it entirely when unset.

    Omitted rather than passed as None so an unset ceiling produces exactly the
    request this client sent before the parameter existed -- the provider default.

    WHY A CEILING EXISTS AT ALL, and it is containment rather than thrift.

    Measured on a 20-case production run: two calls returned exactly 8,192 output
    tokens, and both were `parse_error`. They account for two of the only three parse
    errors on the whole board. The investigation one ended
    `', {}, {}, {}, {}, {}, {}, {}, {},\\n...[truncated, 28364 more chars]'` -- a
    degenerate repetition loop emitting empty objects until it hit the provider's own
    limit, 38.6 seconds and $0.007873 for a single call that produced nothing usable,
    or 29% of all investigation spend on that run. The compliance one burned 45.2
    seconds the same way.

    A ceiling does NOT fix that. A truncated JSON object is still invalid JSON, so the
    case still routes to a human -- which it already does today. What the ceiling
    changes is the price of the failure: bounded output tokens, bounded latency, and a
    runaway that stops in seconds instead of three quarters of a minute.

    The values are therefore set with headroom over the largest LEGITIMATE output each
    agent has produced, not near its average. Too tight a ceiling would convert working
    calls into parse errors, and a human review costs incomparably more than the tokens
    it saved.
    """
    return {} if max_tokens is None else {"max_tokens": int(max_tokens)}


async def complete_json(
    *,
    model: str,
    system_prompt: str,
    user_text: str,
    temperature: float = 0.1,
    max_tokens: int | None = None,
) -> tuple[str, int, int]:
    """
    One text-only, JSON-mode chat completion.

    Returns (raw_text, input_tokens, output_tokens). Raises on transport/API
    errors - callers already run inside a Timer/try structure in each agent.
    """
    client = get_client()

    async def _call():
        return await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
            **_ceiling(max_tokens),
        )

    response = await _with_retry(f"complete_json[{model}]", _call)
    _note_truncation(f"complete_json[{model}]", response, max_tokens)
    text = response.choices[0].message.content or ""
    input_tokens, output_tokens = _usage(response)
    return text, input_tokens, output_tokens


async def complete_with_tools(
    *,
    model: str,
    messages: list[dict],
    tools: list[dict],
    temperature: float = 0.3,
    max_tokens: int | None = None,
):
    """
    Chat completion with function calling (tool use) support.

    Used by the debate agent where Nemotron Super reviews Nano's assessment
    and can call tools like request_nano_reevaluation or search_tavily.

    Returns the raw ChatCompletion response so the caller can access
    tool_calls on the assistant message.
    """
    client = get_client()

    async def _call():
        return await client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            temperature=temperature,
            **_ceiling(max_tokens),
        )

    response = await _with_retry(f"complete_with_tools[{model}]", _call)
    _note_truncation(f"complete_with_tools[{model}]", response, max_tokens)
    return response


async def complete_vision_json(
    *,
    model: str,
    system_prompt: str,
    document_bytes: bytes,
    mime_type: str,
    user_text: str,
    temperature: float = 0.0,
    max_tokens: int | None = None,
) -> tuple[str, int, int]:
    """
    One multimodal (image/PDF-page + text), JSON-mode chat completion.

    Images/documents are sent as base64 data URLs, the standard OpenAI-compatible
    multimodal message shape that vision models on Token Factory accept.
    """
    client = get_client()
    b64 = base64.b64encode(document_bytes).decode("ascii")
    data_url = f"data:{mime_type};base64,{b64}"

    async def _call():
        return await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": user_text},
                    ],
                },
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
            **_ceiling(max_tokens),
        )

    response = await _with_retry(f"complete_vision_json[{model}]", _call)
    _note_truncation(f"complete_vision_json[{model}]", response, max_tokens)
    text = response.choices[0].message.content or ""
    input_tokens, output_tokens = _usage(response)
    return text, input_tokens, output_tokens
