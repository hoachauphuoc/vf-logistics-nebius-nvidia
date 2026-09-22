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
import time
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


# ---------------------------------------------------------------------------
# Result cache
# ---------------------------------------------------------------------------
#
# Measured on a 20-case run: 20 shipper lookups resolved to 7 distinct names, 20
# receiver lookups to 6, and 20 route lookups to 6 lanes -- 41 of 60 unconditional
# searches were repeats. At the free tier's 1,000 credits a month, that repeat rate
# is the difference between roughly 200 cases a month and roughly 500.
#
# OPT-IN PER CALL SITE, and off by default. `cache_ttl_seconds=0` means no caching,
# which is what every existing caller gets without being changed. A cache that
# switched itself on everywhere would silently start serving stale adverse-media to
# the zero-day agent, whose entire purpose is catching what a stale list missed.
#
# ONLY SUCCESSFUL SEARCHES ARE STORED. Caching a failure would turn one timeout into
# a TTL-long outage, and -- far worse here -- this module exists partly because an
# outage used to be indistinguishable from a clean result. Storing NO_API_KEY or
# RATE_LIMITED under a key and replaying it is that same bug with a longer reach. An
# empty OK result IS cached: "we searched and found nothing" is a real answer.

_CACHE: dict[tuple, tuple[float, list[dict[str, Any]], str]] = {}

# Bounded so a long-running process cannot grow it without limit. Freight traffic
# repeats, but the query space is still open-ended -- every new counterparty is a new
# key. Eviction is oldest-expiry-first rather than LRU: expiry is already tracked, and
# the cheaper policy is enough for a cache whose hit rate comes from bursts.
CACHE_MAX_ENTRIES = 512

# Counters, read by the billing surface. Tavily spend does not appear in
# `estimated_cost_usd` -- that figure is Nebius only -- yet the credit ceiling is what
# actually limits throughput, so the count has to be observable somewhere.
_STATS = {"hits": 0, "misses": 0, "stores": 0, "evictions": 0}


def _cache_key(
    query: str,
    max_results: int,
    search_depth: str,
    topic: str | None,
    days: int | None,
) -> tuple:
    """
    Every parameter that can change the response is part of the key.

    Including `max_results` matters: the same query at 3 and at 5 results are
    different answers, and serving the 3-result entry to a caller that asked for 5
    would quietly narrow the evidence a compliance decision rests on.

    The query is casefolded and whitespace-collapsed so that "Truong Hai Trading Co"
    and "truong hai  trading co" share an entry -- that normalisation is where most of
    the measured hit rate lives, because entity names arrive from documents.
    """
    normalised = " ".join(query.split()).casefold()
    return (normalised, int(max_results), search_depth, topic, days)


def _cache_get(key: tuple) -> tuple[list[dict[str, Any]], str] | None:
    entry = _CACHE.get(key)
    if entry is None:
        _STATS["misses"] += 1
        return None
    expires_at, results, status = entry
    if time.monotonic() >= expires_at:
        _CACHE.pop(key, None)
        _STATS["misses"] += 1
        return None
    _STATS["hits"] += 1
    # Copied on the way out. The caller receives a mutable list of mutable dicts, and
    # compliance_agent slices it into a prompt while the orchestrator stores a
    # trimmed version on the case -- a shared reference would let one caller's
    # trimming rewrite what the next one sees.
    return [dict(r) for r in results], status


def _cache_put(key: tuple, ttl_seconds: float, results: list[dict[str, Any]], status: str) -> None:
    if ttl_seconds <= 0 or status != OK:
        return
    if len(_CACHE) >= CACHE_MAX_ENTRIES:
        oldest = min(_CACHE, key=lambda k: _CACHE[k][0])
        _CACHE.pop(oldest, None)
        _STATS["evictions"] += 1
    _CACHE[key] = (time.monotonic() + ttl_seconds, [dict(r) for r in results], status)
    _STATS["stores"] += 1


def cache_stats() -> dict[str, int]:
    """Hit/miss counters plus the live entry count, for the billing surface."""
    return {**_STATS, "entries": len(_CACHE)}


def reset_cache() -> None:
    """
    Drop every entry and zero the counters.

    Exists for tests, and for an operator who has a reason to force fresh lookups --
    a sanctions list refresh being the obvious one.
    """
    _CACHE.clear()
    for k in _STATS:
        _STATS[k] = 0


def _ttl_from_env(name: str, default: float) -> float:
    """
    Read a TTL, treating anything unparseable as the default rather than as zero.

    Garbage silently meaning "no caching" would be the wrong direction: it turns a
    typo in a deployment variable into a quiet 2.5x increase in credit burn.
    """
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


# Six hours for a shipping lane: port congestion and lane disruptions are reported in
# hours-to-days, and the query carries no entity at all -- only a country pair.
ROUTE_CACHE_TTL_SECONDS = _ttl_from_env("TAVILY_ROUTE_CACHE_TTL_SECONDS", 6 * 3600)

# One hour for a counterparty, deliberately shorter. Tavily is NOT the sanctions
# control -- that is validation.sanctions_screening, a separate deterministic path
# against the official list, and the risk floor comes from code-resident findings.
# What a stale entry here delays is an adverse-media signal, a news article rather
# than a sanction. One hour still captures the repeat traffic the saving comes from:
# the measured 20-case run completed inside 8 minutes.
ENTITY_CACHE_TTL_SECONDS = _ttl_from_env("TAVILY_ENTITY_CACHE_TTL_SECONDS", 3600)


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
    cache_ttl_seconds: float = 0.0,
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

    `cache_ttl_seconds` defaults to 0, meaning no caching, so every existing caller
    behaves exactly as before. Only OK responses are ever stored; see the cache
    section above for why storing a failure would reintroduce the bug this module was
    written to remove.
    """
    results, status, _hit = await _search(
        query,
        max_results,
        search_depth=search_depth,
        topic=topic,
        days=days,
        cache_ttl_seconds=cache_ttl_seconds,
    )
    return results, status


async def search_cached(
    query: str,
    max_results: int = 5,
    *,
    ttl_seconds: float,
    search_depth: SearchDepth = "basic",
    topic: str | None = None,
    days: int | None = None,
) -> tuple[list[dict[str, Any]], str, bool]:
    """
    Search, returning (results, status, served_from_cache).

    The third value exists so a decision can record which of its evidence was fetched
    live and which was reused. A reviewer reading a released shipment should be able
    to tell those apart; "we checked this counterparty" and "we reused a check from 40
    minutes ago" are different statements, and only one of them is what the audit
    trail implies if the distinction is dropped.

    `ttl_seconds` is required rather than defaulted: a caller asking for the caching
    variant has to state how stale it is willing to be.
    """
    return await _search(
        query,
        max_results,
        search_depth=search_depth,
        topic=topic,
        days=days,
        cache_ttl_seconds=ttl_seconds,
    )


async def _search(
    query: str,
    max_results: int = 5,
    *,
    search_depth: SearchDepth = "basic",
    topic: str | None = None,
    days: int | None = None,
    cache_ttl_seconds: float = 0.0,
) -> tuple[list[dict[str, Any]], str, bool]:
    """The one implementation. Returns (results, status, served_from_cache)."""
    key = api_key()
    if not key:
        return [], NO_API_KEY, False
    if not query or not query.strip():
        return [], EMPTY_QUERY, False

    depth = search_depth if search_depth in ("basic", "advanced") else "basic"
    bounded_results = max(1, min(int(max_results or 5), 20))
    bounded_days = None if days is None else max(1, min(int(days), 365))

    # Keyed on the bounded values, not the requested ones, so max_results=50 and
    # max_results=20 share the entry they will actually share a response for.
    cache_key = _cache_key(query, bounded_results, depth, topic, bounded_days)
    if cache_ttl_seconds > 0:
        hit = _cache_get(cache_key)
        if hit is not None:
            results, status = hit
            return results, status, True

    payload: dict[str, Any] = {
        "query": query,
        "max_results": bounded_results,
        "search_depth": depth,
    }
    if topic:
        payload["topic"] = topic
    if bounded_days is not None:
        payload["days"] = bounded_days

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                TAVILY_URL,
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
            )
    except httpx.TimeoutException:
        return [], TIMEOUT, False
    except httpx.HTTPError:
        return [], TRANSPORT_ERROR, False

    if response.status_code == 429:
        # Called out separately because it is the one failure a caller can act on
        # by retrying later, and because a bulk benchmark will hit it: the free
        # tier is 1,000 credits a month.
        return [], RATE_LIMITED, False
    if response.status_code >= 400:
        return [], HTTP_ERROR, False

    try:
        data = response.json()
        raw = data.get("results") or []
    except Exception:  # noqa: BLE001 - any decode failure is the same to a caller
        return [], BAD_RESPONSE, False

    results = [
        {
            "title": item.get("title") or "",
            "url": item.get("url") or "",
            "content": (item.get("content") or "")[:CONTENT_MAX_CHARS],
        }
        for item in raw
        if isinstance(item, dict)
    ]
    _cache_put(cache_key, cache_ttl_seconds, results, OK)
    return results, OK, False


async def search(
    query: str,
    max_results: int = 5,
    *,
    cache_ttl_seconds: float = 0.0,
) -> list[dict[str, Any]]:
    """
    Fail-soft search, unchanged behaviour.

    Kept callable exactly as it was because several call sites and their tests patch
    this name -- tests/test_hardening.py patches orchestrator.tavily_client.search,
    and debate_agent calls it from inside its tool loop. New code that needs to tell
    an outage from an empty result should call search_with_status() instead, and code
    that needs to know whether its evidence was reused should call search_cached().

    `cache_ttl_seconds` is keyword-only with a zero default, so adding it cannot
    change any existing call.
    """
    results, _status, _hit = await _search(
        query, max_results, cache_ttl_seconds=cache_ttl_seconds,
    )
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
