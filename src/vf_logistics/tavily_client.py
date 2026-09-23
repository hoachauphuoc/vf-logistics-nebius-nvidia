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

import asyncio
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

# No search was attempted, because there was nothing to search for -- a shipment with
# no counterparty name on it. Distinct from OK for the same reason every other status
# here is: "we found nothing adverse" and "we did not look" are opposite facts, and the
# second must never render as the first.
NOT_ATTEMPTED = "not_attempted"

# Every status that means the search did not happen. A caller must not read any of
# these as "nothing adverse found".
FAILED_STATUSES = frozenset({
    NO_API_KEY, TIMEOUT, RATE_LIMITED, HTTP_ERROR, TRANSPORT_ERROR, BAD_RESPONSE,
    # Included deliberately, though neither is an outage. A blank query and an absent
    # counterparty both mean no adverse-media check was performed, which is the only
    # thing this set is used to decide.
    EMPTY_QUERY, NOT_ATTEMPTED,
})

# Statuses where a request actually reached the API and therefore cost a credit.
#
# An empty OK result is billable -- the search ran. Everything else in FAILED_STATUSES
# either never left the process (no key, blank query, nothing to search) or never got a
# response, and counting those as spend makes the credit figure wrong in the direction
# that matters: a deployment with no TAVILY_API_KEY would report a full bill for zero
# requests.
BILLABLE_STATUSES = frozenset({OK})

CONTENT_MAX_CHARS = 500
REQUEST_TIMEOUT_SECONDS = 10.0


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------
#
# One client, not one per search. Every call built its own `httpx.AsyncClient` and
# therefore its own connection pool, so each of the 3+ searches on a case's critical
# path paid for a fresh TCP handshake and a fresh TLS negotiation to the same host.
#
# Created lazily and per event loop. `store.py` runs work on a separate worker loop, and
# an httpx client bound to a loop that has closed raises on its next use -- so the loop
# is part of the key rather than assuming one process means one loop.
_CLIENTS: dict[int, httpx.AsyncClient] = {}


def _client() -> httpx.AsyncClient:
    try:
        loop_id = id(asyncio.get_running_loop())
    except RuntimeError:
        # No running loop: the caller is about to fail anyway, but returning a
        # throwaway client keeps the failure theirs rather than ours.
        return httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)

    # The loop is checked as well as the client. `id()` is a reusable address, so a
    # new loop can land on a dead loop's key, and `is_closed` on the CLIENT says
    # nothing about whether its LOOP is gone -- the stale client passes the guard and
    # then raises RuntimeError("Event loop is closed"), which is not an httpx.HTTPError
    # and so is not caught by the handlers around the request.
    #
    # Not reachable in the deployed service, which runs one immortal worker loop, but
    # it is reachable from tests that call asyncio.run() repeatedly.
    existing = _CLIENTS.get(loop_id)
    if existing is not None and not existing.is_closed:
        try:
            if not asyncio.get_running_loop().is_closed():
                return existing
        except RuntimeError:
            pass
        _CLIENTS.pop(loop_id, None)
    created = httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)
    _CLIENTS[loop_id] = created
    return created


async def aclose() -> None:
    """
    Close the pooled clients.

    Not wired into a shutdown hook: Cloud Run's container is killed rather than asked
    to wind down, and a socket left open at SIGKILL costs nothing. This exists so a
    test or a script can close cleanly without a ResourceWarning.
    """
    for client in list(_CLIENTS.values()):
        if not client.is_closed:
            await client.aclose()
    _CLIENTS.clear()


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

# Process-local counters, for diagnosis rather than billing.
#
# The billing figure is the per-case `_tavily_searches` rollup, which survives a
# restart and is tenant-scoped; these do neither. They answer "is the cache working at
# all" when a TTL is being tuned, and nothing reads them in production.
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
    """
    Hit/miss counters plus the live entry count.

    Diagnostic, not billing. Note that when caching is off neither counter moves, so
    `hits + misses` is not total search volume -- the billable figure is the per-case
    `_tavily_searches` rollup.
    """
    return {**_STATS, "entries": len(_CACHE)}


def reset_cache() -> None:
    """
    Drop every entry, zero the counters, and forget the pooled HTTP clients.

    Exists for tests, and for an operator who has a reason to force fresh lookups -- a
    sanctions list refresh being the obvious one.

    The pooled clients are dropped too, and that matters for tests specifically: a test
    that patches `httpx.AsyncClient` gets nothing if a client built before the patch is
    still cached, and the symptom is a test that silently exercises the real transport.
    Dropped rather than closed, because closing another loop's client from here is not
    safe; the sockets are collected with the loop.
    """
    _CACHE.clear()
    for k in _STATS:
        _STATS[k] = 0
    _CLIENTS.clear()


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

    NO SINGLE-FLIGHT, and that is a measured decision rather than an oversight. This is a
    read-then-write around an await, so concurrent callers with the same query all miss
    and all fetch -- the cache helps the caller who arrives after a response has landed,
    not the ones already waiting. tests/test_cache_concurrency.py measures it: ten
    concurrent identical queries issue ten requests, where five serial ones issue one.

    It is not worth fixing at this scale. orchestrator.MAX_CONCURRENT is 3 and each case
    makes its lookups sequentially, so a colliding query costs 3 credits instead of 1, and
    only when cases sharing a counterparty land in the same batch of three -- a handful of
    extra credits against roughly 40 for a 20-case run. An in-flight map would sit in the
    path of every case in the system to recover that. The test asserts MAX_CONCURRENT
    stays small and will fail if this reasoning stops holding.
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
        # The pooled client is NOT closed here. `async with` on a shared client would
        # close it after the first search and leave every later call on this loop
        # holding a dead pool.
        response = await _client().post(
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

    A PARTIAL FAILURE RENDERS BOTH THE WARNING AND THE RESULTS. Where several searches
    were combined and one failed, the caller passes the failed status along with the
    results it did get, and those have to be shown. Returning only the warning destroyed
    real evidence: a shipper lookup timing out while the receiver lookup returned a
    genuine adverse-media hit produced a prompt with the warning and nothing else, while
    the case record still listed the receiver URLs the model was never shown.
    """
    if status == NOT_ATTEMPTED:
        return (
            "NO WEB SEARCH WAS ATTEMPTED: the record carries no counterparty name to "
            "search for. This is not a clean result."
        )
    if status in FAILED_STATUSES:
        warning = (
            f"WEB SEARCH DID NOT RUN, OR RAN ONLY IN PART ({status}). Anything below is "
            "incomplete, and the absence of a finding is not evidence of absence: no "
            "complete adverse-media check was performed on these entities."
        )
        if not results:
            return warning
        return warning + "\n" + "\n".join(
            f"  - {r['title']}: {r['content']} ({r['url']})" for r in results
        )
    if not results:
        return "No external web search findings (search ran and returned nothing)."
    return "\n".join(
        f"  - {r['title']}: {r['content']} ({r['url']})" for r in results
    )
