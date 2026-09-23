"""
What the cache does NOT do: collapse concurrent identical queries.

The measured saving -- 20 shipper lookups resolving to 7 names, 20 route lookups to 6
lanes -- was measured on SERIAL traffic, one case at a time. The cache is a plain
read-then-write around an await, so under concurrency every caller that arrives before
the first response lands misses, and every one of them fetches.

This matters because bulk load is the realistic shape for the saving. POST
/api/v1/simulate/bulk pushes many shipments at once, and shipments arriving together are
exactly the ones most likely to share a lane and a counterparty -- a freight forwarder
submits a day's manifests, not one every ten minutes. So the case where the repeat rate is
highest is also the case where the cache helps least.

These tests measure the gap rather than asserting it away. They are written to FAIL if
single-flight is ever added, with a message saying so, because at that point the numbers
in the docs change and should be re-measured rather than assumed.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics import tavily_client  # noqa: E402


class SlowClient:
    """
    A client with a deliberate delay, so concurrent callers overlap.

    Without the delay the event loop would serialise these completely and the test would
    measure nothing -- the first call would finish and populate the cache before the
    second was scheduled, which is the serial case already covered elsewhere.
    """

    calls = 0
    delay = 0.05
    is_closed = False

    def __init__(self, *_a, **_kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def post(self, *_a, **_kw):
        SlowClient.calls += 1
        await asyncio.sleep(SlowClient.delay)

        class R:
            status_code = 200

            @staticmethod
            def json():
                return {"results": [
                    {"title": "t", "url": "https://x.test", "content": "c"},
                ]}

        return R()


class ConcurrencyTestCase(unittest.TestCase):
    def setUp(self):
        tavily_client.reset_cache()
        SlowClient.calls = 0
        self._key = patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"})
        self._key.start()

    def tearDown(self):
        self._key.stop()
        tavily_client.reset_cache()


class TestConcurrentIdenticalQueriesAllMiss(ConcurrencyTestCase):
    def test_ten_concurrent_identical_queries_issue_ten_requests(self):
        """
        The gap, stated as a number.

        Ten shipments for the same counterparty arriving together cost ten credits, not
        one. The cache is populated ten times over with the same entry and saves nothing
        on this burst -- it only helps the eleventh caller, who arrives after the first
        response has landed.
        """
        async def go():
            return await asyncio.gather(*(
                tavily_client.search_cached("same query", ttl_seconds=3600)
                for _ in range(10)
            ))

        with patch.object(tavily_client.httpx, "AsyncClient", SlowClient):
            results = asyncio.run(go())

        hits = sum(1 for _r, _s, hit in results if hit)
        self.assertEqual(
            SlowClient.calls, 10,
            "if this is no longer 10, single-flight has been added -- which is good, but "
            "the repeat-rate figures in the README and .env.example were measured "
            "WITHOUT it and need re-measuring",
        )
        self.assertEqual(hits, 0, "nothing can be a cache hit before the first store")
        self.assertEqual(len(results), 10)
        for r, status, _hit in results:
            self.assertEqual(status, tavily_client.OK)
            self.assertTrue(r)

    def test_the_eleventh_caller_after_the_burst_does_hit(self):
        """The cache is not broken, it is just not a barrier. Once a response has landed,
        the next caller is served from it."""
        async def go():
            await asyncio.gather(*(
                tavily_client.search_cached("same query", ttl_seconds=3600)
                for _ in range(5)
            ))
            return await tavily_client.search_cached("same query", ttl_seconds=3600)

        with patch.object(tavily_client.httpx, "AsyncClient", SlowClient):
            _r, _s, hit = asyncio.run(go())

        self.assertEqual(SlowClient.calls, 5)
        self.assertTrue(hit, "a caller arriving after the burst must be served cached")

    def test_a_serial_sequence_still_collapses_to_one_request(self):
        """
        The contrast, and the reason the measured figures are what they are.

        Awaited one after another, five identical queries cost one credit. That is the
        traffic shape the 65-70% repeat saving was measured on.
        """
        async def go():
            for _ in range(5):
                await tavily_client.search_cached("same query", ttl_seconds=3600)

        with patch.object(tavily_client.httpx, "AsyncClient", SlowClient):
            asyncio.run(go())

        self.assertEqual(SlowClient.calls, 1)

    def test_the_realistic_exposure_is_bounded_by_MAX_CONCURRENT(self):
        """
        The number that decides whether this is worth fixing, and it is 3.

        orchestrator.MAX_CONCURRENT caps how many cases advance at once, and each case
        issues its Tavily calls sequentially within itself. So the worst realistic
        collision is three identical queries in flight, not the twenty a bulk POST might
        suggest -- a colliding query costs 3 credits instead of 1, and only when two or
        three cases sharing a counterparty land in the same batch of three.

        Over a 20-case run that is a handful of extra credits against roughly 40 used,
        which is why an in-flight map has NOT been added: the exposure is bounded at a
        small multiple, and the change would sit in the path of every case for a saving
        that rounds to noise. If MAX_CONCURRENT is ever raised substantially, this
        reasoning expires -- the assertion below is what will notice.
        """
        from vf_logistics import orchestrator

        self.assertLessEqual(
            orchestrator.MAX_CONCURRENT, 5,
            "MAX_CONCURRENT has been raised, so the un-collapsed cache now wastes more "
            "than a few credits per run -- reconsider adding single-flight to "
            "tavily_client.search_cached",
        )

        async def go():
            return await asyncio.gather(*(
                tavily_client.search_cached("lane query", ttl_seconds=3600)
                for _ in range(orchestrator.MAX_CONCURRENT)
            ))

        with patch.object(tavily_client.httpx, "AsyncClient", SlowClient):
            asyncio.run(go())

        self.assertEqual(
            SlowClient.calls, orchestrator.MAX_CONCURRENT,
            "at the real concurrency limit, a colliding query costs one credit per "
            "in-flight case",
        )


class TestOneCaseIsStillCoveredConcurrently(ConcurrencyTestCase):
    def test_the_two_compliance_lookups_within_one_case_are_not_identical(self):
        """
        Worth being precise about the blast radius: this gap does NOT affect a single
        case. compliance_agent issues its shipper and receiver lookups sequentially, and
        they are different queries anyway, so nothing within one shipment is racing.

        The exposure is strictly ACROSS cases running at the same time.
        """
        import inspect

        from vf_logistics.agents import compliance_agent

        source = inspect.getsource(compliance_agent.screen_shipment)
        self.assertNotIn(
            "asyncio.gather", source,
            "the two counterparty lookups are sequential; gathering them would put the "
            "shipper and receiver of one shipment in flight together, which is harmless "
            "for the cache (different queries) but changes the failure semantics",
        )


if __name__ == "__main__":
    unittest.main()
