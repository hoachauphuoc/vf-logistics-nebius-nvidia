"""
The Tavily result cache, and the one thing it must never do.

Why it exists, measured rather than assumed. On a 20-case run the three unconditional
search sites issued 60 searches that resolved to 19 distinct queries: 20 shipper
lookups to 7 names, 20 receiver lookups to 6, 20 route lookups to 6 lanes. One shipper
appeared 14 times and one lane 15. At the free tier's 1,000 credits a month that
repeat rate is the difference between roughly 200 cases a month and roughly 500, and
Tavily -- not Nemotron -- is what limits throughput: the same 20 cases cost under seven
cents of model spend.

THE RULE THAT MATTERS MOST: a failure is never cached.

`tavily_client` was written partly to fix a collapse where a missing API key, a
timeout, a 429 and a genuinely empty result all returned the same empty list -- so
"we found no adverse media on this company" and "the search did not happen" became
the same fact, and reading the second as the first clears a shipment nobody checked.
Storing a failure under a cache key and replaying it for an hour is that same bug with
a longer reach. The tests below pin it from every failure direction, because it is the
one regression here that would be invisible in production.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics import tavily_client  # noqa: E402


def run(coro):
    import asyncio

    return asyncio.run(coro)


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"results": []}

    def json(self):
        return self._payload


class RecordingClient:
    """Counts how many HTTP requests actually leave, which is what a credit is."""

    calls = 0

    # The client is pooled and reused across searches now, so `_client()` checks this
    # before handing one back. A stub without it raises AttributeError.
    is_closed = False

    def __init__(self, *_a, **_kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def post(self, *_a, **_kw):
        RecordingClient.calls += 1
        return FakeResponse(payload={
            "results": [
                {"title": f"result {RecordingClient.calls}", "url": "https://x.test",
                 "content": "body"},
            ],
        })


class CacheTestCase(unittest.TestCase):
    def setUp(self):
        tavily_client.reset_cache()
        RecordingClient.calls = 0
        self._key = patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"})
        self._key.start()

    def tearDown(self):
        self._key.stop()
        tavily_client.reset_cache()


class TestAFailureIsNeverCached(CacheTestCase):
    """
    Each failure status, replayed twice, must issue two real requests.

    If any of these caches, an outage becomes a TTL-long outage and a compliance
    decision reads a stored "nothing found" that was really "nothing happened".
    """

    def _twice(self, factory):
        with patch.object(tavily_client.httpx, "AsyncClient", factory):
            a = run(tavily_client.search_cached("q", ttl_seconds=3600))
            b = run(tavily_client.search_cached("q", ttl_seconds=3600))
        return a, b

    def test_a_429_is_not_cached(self):
        class Client(RecordingClient):
            async def post(self, *_a, **_kw):
                Client.calls += 1
                return FakeResponse(status_code=429)

        (_r1, s1, h1), (_r2, s2, h2) = self._twice(Client)
        self.assertEqual(s1, tavily_client.RATE_LIMITED)
        self.assertEqual(s2, tavily_client.RATE_LIMITED)
        self.assertFalse(h1)
        self.assertFalse(h2, "a rate-limited response must not be served from cache")
        self.assertEqual(Client.calls, 2)

    def test_an_http_error_is_not_cached(self):
        class Client(RecordingClient):
            async def post(self, *_a, **_kw):
                Client.calls += 1
                return FakeResponse(status_code=500)

        (_r1, s1, _h1), (_r2, s2, h2) = self._twice(Client)
        self.assertEqual(s1, tavily_client.HTTP_ERROR)
        self.assertEqual(s2, tavily_client.HTTP_ERROR)
        self.assertFalse(h2)
        self.assertEqual(Client.calls, 2)

    def test_a_timeout_is_not_cached(self):
        class Client(RecordingClient):
            async def post(self, *_a, **_kw):
                Client.calls += 1
                raise tavily_client.httpx.TimeoutException("slow")

        (_r1, s1, _h1), (_r2, s2, h2) = self._twice(Client)
        self.assertEqual(s1, tavily_client.TIMEOUT)
        self.assertEqual(s2, tavily_client.TIMEOUT)
        self.assertFalse(h2)
        self.assertEqual(Client.calls, 2)

    def test_a_bad_response_body_is_not_cached(self):
        class Client(RecordingClient):
            async def post(self, *_a, **_kw):
                Client.calls += 1

                class Broken:
                    status_code = 200

                    def json(self):
                        raise ValueError("not json")

                return Broken()

        (_r1, s1, _h1), (_r2, s2, h2) = self._twice(Client)
        self.assertEqual(s1, tavily_client.BAD_RESPONSE)
        self.assertEqual(s2, tavily_client.BAD_RESPONSE)
        self.assertFalse(h2)
        self.assertEqual(Client.calls, 2)

    def test_a_missing_api_key_is_not_cached(self):
        with patch.dict(os.environ, {"TAVILY_API_KEY": ""}):
            r1, s1, h1 = run(tavily_client.search_cached("q", ttl_seconds=3600))
            self.assertEqual(s1, tavily_client.NO_API_KEY)
            self.assertFalse(h1)
        # Key restored: the earlier failure must not have poisoned the entry.
        with patch.object(tavily_client.httpx, "AsyncClient", RecordingClient):
            r2, s2, h2 = run(tavily_client.search_cached("q", ttl_seconds=3600))
        self.assertEqual(s2, tavily_client.OK)
        self.assertFalse(h2)
        self.assertTrue(r2)
        del r1

    def test_an_empty_but_successful_result_IS_cached(self):
        """
        The one case that looks like a failure and is not.

        "We searched and found nothing" is a real answer and the whole point of the
        status field is that it is distinguishable from an outage. Refusing to cache
        it would throw away the cheapest hits -- clean counterparties are the common
        case.
        """
        class Client(RecordingClient):
            async def post(self, *_a, **_kw):
                Client.calls += 1
                return FakeResponse(payload={"results": []})

        with patch.object(tavily_client.httpx, "AsyncClient", Client):
            r1, s1, h1 = run(tavily_client.search_cached("q", ttl_seconds=3600))
            r2, s2, h2 = run(tavily_client.search_cached("q", ttl_seconds=3600))
        self.assertEqual((r1, s1, h1), ([], tavily_client.OK, False))
        self.assertEqual((r2, s2, h2), ([], tavily_client.OK, True))
        self.assertEqual(Client.calls, 1)


class TestCachingIsOptIn(CacheTestCase):
    """
    Off by default, so no existing call site silently changes behaviour.

    The zero-day agent is the reason. Its entire purpose is catching an entity the
    weekly list has not reached yet; serving it an hour-old search would defeat the
    agent while leaving it apparently working.
    """

    def test_no_ttl_means_no_caching(self):
        with patch.object(tavily_client.httpx, "AsyncClient", RecordingClient):
            run(tavily_client.search_with_status("q"))
            run(tavily_client.search_with_status("q"))
        self.assertEqual(RecordingClient.calls, 2)
        self.assertEqual(tavily_client.cache_stats()["entries"], 0)

    def test_search_still_takes_two_positional_arguments(self):
        """The signature tests and call sites rely on. `cache_ttl_seconds` is
        keyword-only precisely so adding it cannot change an existing call."""
        with patch.object(tavily_client.httpx, "AsyncClient", RecordingClient):
            results = run(tavily_client.search("q", 3))
        self.assertTrue(results)
        self.assertEqual(tavily_client.cache_stats()["entries"], 0)

    def test_search_with_status_still_returns_exactly_two_values(self):
        with patch.object(tavily_client.httpx, "AsyncClient", RecordingClient):
            pair = run(tavily_client.search_with_status("q"))
        self.assertEqual(len(pair), 2, "zero_day and debate unpack two values")


class TestTheKeyCoversEverythingThatChangesTheAnswer(CacheTestCase):
    def test_a_different_max_results_is_a_different_entry(self):
        """
        Serving a 3-result entry to a caller that asked for 5 would quietly narrow
        the evidence a compliance decision rests on.
        """
        with patch.object(tavily_client.httpx, "AsyncClient", RecordingClient):
            run(tavily_client.search_cached("q", 3, ttl_seconds=3600))
            run(tavily_client.search_cached("q", 5, ttl_seconds=3600))
        self.assertEqual(RecordingClient.calls, 2)

    def test_a_different_search_depth_is_a_different_entry(self):
        with patch.object(tavily_client.httpx, "AsyncClient", RecordingClient):
            run(tavily_client.search_cached("q", ttl_seconds=3600, search_depth="basic"))
            run(tavily_client.search_cached("q", ttl_seconds=3600, search_depth="advanced"))
        self.assertEqual(RecordingClient.calls, 2)

    def test_a_different_news_window_is_a_different_entry(self):
        with patch.object(tavily_client.httpx, "AsyncClient", RecordingClient):
            run(tavily_client.search_cached("q", ttl_seconds=3600, topic="news", days=7))
            run(tavily_client.search_cached("q", ttl_seconds=3600, topic="news", days=30))
        self.assertEqual(RecordingClient.calls, 2)

    def test_case_and_whitespace_differences_share_an_entry(self):
        """
        Where most of the measured hit rate lives: entity names arrive from
        transcribed documents, so spacing and casing vary between shipments naming
        the same company.
        """
        with patch.object(tavily_client.httpx, "AsyncClient", RecordingClient):
            _r, _s, h1 = run(tavily_client.search_cached(
                '"Truong Hai Trading Co" sanctions', ttl_seconds=3600,
            ))
            _r, _s, h2 = run(tavily_client.search_cached(
                '"truong hai  trading co"   SANCTIONS', ttl_seconds=3600,
            ))
        self.assertFalse(h1)
        self.assertTrue(h2, "casefold + whitespace collapse should make these one key")
        self.assertEqual(RecordingClient.calls, 1)


class TestExpiryAndBounds(CacheTestCase):
    def test_an_expired_entry_is_refetched(self):
        clock = {"t": 1000.0}
        with patch.object(tavily_client.time, "monotonic", lambda: clock["t"]), \
             patch.object(tavily_client.httpx, "AsyncClient", RecordingClient):
            run(tavily_client.search_cached("q", ttl_seconds=60))
            clock["t"] = 1059.0
            _r, _s, hit_before = run(tavily_client.search_cached("q", ttl_seconds=60))
            clock["t"] = 1061.0
            _r, _s, hit_after = run(tavily_client.search_cached("q", ttl_seconds=60))
        self.assertTrue(hit_before, "still inside the TTL")
        self.assertFalse(hit_after, "past the TTL, must go back to the API")
        self.assertEqual(RecordingClient.calls, 2)

    def test_the_cache_is_bounded(self):
        with patch.object(tavily_client, "CACHE_MAX_ENTRIES", 4), \
             patch.object(tavily_client.httpx, "AsyncClient", RecordingClient):
            for i in range(10):
                run(tavily_client.search_cached(f"query {i}", ttl_seconds=3600))
        stats = tavily_client.cache_stats()
        self.assertLessEqual(stats["entries"], 4)
        self.assertGreater(stats["evictions"], 0)

    def test_a_mutated_result_does_not_corrupt_the_entry(self):
        """
        Callers mutate what they get back -- compliance slices it into a prompt, the
        orchestrator trims it onto the case. A shared reference would let one
        caller's trimming rewrite what the next one reads.
        """
        with patch.object(tavily_client.httpx, "AsyncClient", RecordingClient):
            first, _s, _h = run(tavily_client.search_cached("q", ttl_seconds=3600))
            first.clear()
            second, _s, hit = run(tavily_client.search_cached("q", ttl_seconds=3600))
        self.assertTrue(hit)
        self.assertEqual(len(second), 1, "the stored entry must survive a caller's edit")


class TestTheTTLConfiguration(unittest.TestCase):
    def test_the_route_ttl_is_longer_than_the_entity_ttl(self):
        """
        Deliberate, and the asymmetry is the point. A lane query carries no entity at
        all, only a country pair. An entity query carries a counterparty, and although
        Tavily is NOT the sanctions control -- that is validation.sanctions_screening,
        a separate deterministic path -- a shorter window there is the cheap
        conservative choice.
        """
        self.assertGreater(
            tavily_client.ROUTE_CACHE_TTL_SECONDS,
            tavily_client.ENTITY_CACHE_TTL_SECONDS,
        )

    def test_garbage_in_the_environment_falls_back_to_the_default_not_to_zero(self):
        """
        A typo meaning "no caching" would turn a deployment mistake into a quiet 2.5x
        increase in credit burn, which is exactly the kind of failure nobody notices
        until the month ends.
        """
        for bad in ("abc", "", "  ", "-5"):
            with patch.dict(os.environ, {"TAVILY_ENTITY_CACHE_TTL_SECONDS": bad}):
                self.assertEqual(tavily_client._ttl_from_env(
                    "TAVILY_ENTITY_CACHE_TTL_SECONDS", 3600,
                ), 3600, f"{bad!r} should fall back to the default")

    def test_a_valid_override_is_honoured(self):
        with patch.dict(os.environ, {"TAVILY_ENTITY_CACHE_TTL_SECONDS": "120"}):
            self.assertEqual(
                tavily_client._ttl_from_env("TAVILY_ENTITY_CACHE_TTL_SECONDS", 3600),
                120.0,
            )

    def test_zero_is_honoured_as_disabling(self):
        """An operator must be able to turn caching off without editing code."""
        with patch.dict(os.environ, {"TAVILY_ROUTE_CACHE_TTL_SECONDS": "0"}):
            self.assertEqual(
                tavily_client._ttl_from_env("TAVILY_ROUTE_CACHE_TTL_SECONDS", 6 * 3600),
                0.0,
            )


if __name__ == "__main__":
    unittest.main()
