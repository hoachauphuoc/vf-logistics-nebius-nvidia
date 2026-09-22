"""
Tavily web search.

Two defects were fixed here, and both mattered more than they looked.

1. The tool schema was lying to the model
   ------------------------------------
   agents/debate_agent.py advertises a `search_depth` parameter with an enum of
   "basic" and "advanced" to Nemotron Super as part of its function-calling
   schema. This client hardcoded `"search_depth": "basic"` in the request body,
   so the model's choice was discarded before it reached the API -- the debate
   agent papered over it by mapping "advanced" to max_results=5 and calling that
   depth. A model told it has a control it does not have will make decisions on
   that basis.

2. An outage was indistinguishable from a clean result
   --------------------------------------------------
   The old body was `except Exception: return []`. A missing API key, a timeout, a
   429 and a genuinely empty result all produced the same empty list. In a
   compliance system that is the worst possible collapse: "we searched for adverse
   media on this company and found none" and "the search did not happen" are
   opposite facts, and reading the second as the first clears a shipment nobody
   checked.

   search() keeps its old signature and fail-soft behaviour so existing callers
   and their tests are unaffected. search_with_status() is the same call with the
   reason attached, and it is what the zero-day agent uses -- its verdict schema
   has a required `searched` field precisely so this distinction survives into the
   audit record.

The API key is read per call rather than at import, because reading it at import
meant a process that set the variable afterwards searched nothing, silently, for
its whole life.
"""

from __future__ import annotations

import os
from typing import Any, Literal

import httpx

TAVILY_URL = "https://api.tavily.com/search"

SearchDepth = Literal["basic", "advanced"]

# Statuses returned alongside the results by search_with_status(). Strings rather
# than an enum so they can be stored on a case document and read back from JSON
# without a decoder.
OK = "ok"
NO_API_KEY = "no_api_key"
EMPTY_QUERY = "empty_query"
TIMEOUT = "timeout"
RATE_LIMITED = "rate_limited"
HTTP_ERROR = "http_error"
TRANSPORT_ERROR = "transport_error"
BAD_RESPONSE = "bad_response"

# Every status that means the search did not happen. A caller must not read any of
# these as "nothing adverse found".
FAILED_STATUSES = frozenset({
    NO_API_KEY, TIMEOUT, RATE_LIMITED, HTTP_ERROR, TRANSPORT_ERROR, BAD_RESPONSE,
})

CONTENT_MAX_CHARS = 500
REQUEST_TIMEOUT_SECONDS = 10.0


def api_key() -> str:
    """Read at call time; see the module docstring."""
    return os.getenv("TAVILY_API_KEY", "").strip()


def configured() -> bool:
    return bool(api_key())


async def search_with_status(
    query: str,
    max_results: int = 5,
    *,
    search_depth: SearchDepth = "basic",
    topic: str | None = None,
    days: int | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """
    Search, returning (results, status).

    `search_depth` now reaches the API. `topic="news"` with `days=N` restricts to
    recent coverage, which is what zero-day screening actually wants -- a company
    that was sanctioned last week will not be in a weekly-refreshed list yet, and
    that gap is the whole reason the search exists.

    Status is never OK on a failure, and results are never non-empty on one, so a
    caller that checks only one of the two still cannot mistake an outage for a
    clean answer.
    """
    key = api_key()
    if not key:
        return [], NO_API_KEY
    if not query or not query.strip():
        return [], EMPTY_QUERY

    payload: dict[str, Any] = {
        "query": query,
        "max_results": max(1, min(int(max_results or 5), 20)),
        "search_depth": search_depth if search_depth in ("basic", "advanced") else "basic",
    }
    if topic:
        payload["topic"] = topic
    if days is not None:
        payload["days"] = max(1, min(int(days), 365))

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                TAVILY_URL,
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
            )
    except httpx.TimeoutException:
        return [], TIMEOUT
    except httpx.HTTPError:
        return [], TRANSPORT_ERROR

    if response.status_code == 429:
        # Called out separately because it is the one failure a caller can act on
        # by retrying later, and because a bulk benchmark will hit it: the free
        # tier is 1,000 credits a month.
        return [], RATE_LIMITED
    if response.status_code >= 400:
        return [], HTTP_ERROR

    try:
        data = response.json()
        raw = data.get("results") or []
    except Exception:  # noqa: BLE001 - any decode failure is the same to a caller
        return [], BAD_RESPONSE

    results = [
        {
            "title": item.get("title") or "",
            "url": item.get("url") or "",
            "content": (item.get("content") or "")[:CONTENT_MAX_CHARS],
        }
        for item in raw
        if isinstance(item, dict)
    ]
    return results, OK


async def search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """
    Fail-soft search, unchanged signature.

    Kept exactly as it was because several call sites and their tests patch this
    name -- tests/test_hardening.py patches orchestrator.tavily_client.search, and
    debate_agent calls it from inside its tool loop. New code that needs to tell an
    outage from an empty result should call search_with_status() instead.
    """
    results, _status = await search_with_status(query, max_results)
    return results


def format_findings(results: list[dict[str, Any]], status: str = OK) -> str:
    """
    Render results for a prompt.

    When `status` says the search failed, the text says so rather than reporting
    an absence of findings. A model handed "no findings" will reason as though the
    company came back clean, which is the exact confusion this module was fixed to
    remove.
    """
    if status in FAILED_STATUSES:
        return (
            f"WEB SEARCH DID NOT RUN ({status}). This is not a clean result: no "
            "adverse-media check was performed on these entities."
        )
    if not results:
        return "No external web search findings (search ran and returned nothing)."
    return "\n".join(
        f"  - {r['title']}: {r['content']} ({r['url']})" for r in results
    )
