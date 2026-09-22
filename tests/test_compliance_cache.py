"""
The compliance agent's adverse-media lookups: when they are reused, and when they
must not be.

Two behaviours are pinned here, and the second one is a bug fix rather than an
optimisation.

1. THE CACHE BYPASS. Measured on a 20-case run, 20 shipper lookups resolved to 7
   distinct names and 20 receiver lookups to 6 -- a 65-70% repeat rate, which at the
   free tier's 1,000 credits a month is the difference between roughly 200 cases a
   month and roughly 500. But a case whose deterministic floor is already at or above
   the auto-clear threshold is going to a human either way, and a reviewer reading the
   evidence for a held shipment should be looking at a live search, not a 40-minute-old
   entry. So the cache is bypassed there.

   Worth being precise about what this is and is not. Tavily is NOT the sanctions
   control: that is `validation.sanctions_screening`, a separate deterministic path
   against the official list, and the risk floor comes from code-resident findings. A
   stale entry delays an adverse-media signal -- a news article, not a sanction. The
   bypass is a conservatism, not a safety mechanism, and these tests say so rather
   than implying a guarantee the design does not make.

2. THE STATUS REACHES THE PROMPT. This call site used `tavily_client.search()`, the
   fail-soft variant that discards the status, and handed the bare list to
   `format_findings()`, which defaults to `status=OK`. So a timeout, a 429 or a
   missing API key produced empty results rendered to the model as "search ran and
   returned nothing". That is exactly the collapse `tavily_client`'s docstring
   describes being fixed -- an outage read as a clean result -- and it was still live
   in the one agent whose job is compliance.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics import tavily_client  # noqa: E402
from vf_logistics.agents import compliance_agent  # noqa: E402


def run(coro):
    import asyncio

    return asyncio.run(coro)


SHIPMENT = {
    "shipment_id": "TEST-001",
    "shipper_name": "Truong Hai Trading Co",
    "receiver_name": "Pacific Sourcing Pte Ltd",
    "cargo_description": "cotton apparel",
    "hs_code": "6109.10",
    "declared_value": 40000,
}

CLEAN_VERDICT = (
    '{"compliance_status":"CLEARED","sanctions_hits":[],"risk_factors":[],'
    '"recommendation":"proceed","confidence":0.9}'
)


class ComplianceCacheTestCase(unittest.TestCase):
    def setUp(self):
        tavily_client.reset_cache()
        self.model = patch.object(
            compliance_agent.nebius_client, "complete_json",
            new=AsyncMock(return_value=(CLEAN_VERDICT, 100, 50)),
        )
        self.model.start()

    def tearDown(self):
        self.model.stop()
        tavily_client.reset_cache()

    def _spy(self, status=tavily_client.OK, results=None):
        """A search_cached stand-in that records its TTL argument."""
        calls: list[dict] = []

        async def fake(query, max_results=5, *, ttl_seconds, **kw):
            calls.append({"query": query, "ttl": ttl_seconds})
            return (results if results is not None else
                    [{"title": "t", "url": "u", "content": "c"}]), status, False

        return calls, fake


class TestEveryCaseUsesTheCache(ComplianceCacheTestCase):
    """
    There is no bypass, and the one that was here was removed on measurement.

    A previous version skipped the cache when the deterministic floor was at or above
    the auto-clear threshold, so a case heading for human review got a live lookup. Two
    findings ended it.

    The premise was wrong. That bypass was written while Tavily was still believed to be
    compliance-critical. It is not: sanctions screening is a separate deterministic path
    in validation.sanctions_screening against the official list, and the risk floor comes
    from code-resident findings. Tavily supplies adverse media -- news -- as labelled
    untrusted evidence in a prompt.

    And it disabled what it was guarding. Measured across 22 live cases, 20 had a floor
    at or above 40, so the bypass fired on 91% of traffic. That is the nature of fraud
    screening: a shipment tripping no findings at all is the minority, so "heading for
    review" describes nearly everything.
    """

    def test_a_high_floor_case_still_uses_the_cache(self):
        calls, fake = self._spy()
        with patch.object(tavily_client, "search_cached", new=fake):
            run(compliance_agent.screen_shipment(SHIPMENT, risk_floor=95))
        self.assertEqual(len(calls), 2)
        for c in calls:
            self.assertEqual(
                c["ttl"], tavily_client.ENTITY_CACHE_TTL_SECONDS,
                "an elevated floor must no longer force a live lookup",
            )

    def test_a_low_floor_case_uses_the_cache(self):
        calls, fake = self._spy()
        with patch.object(tavily_client, "search_cached", new=fake):
            run(compliance_agent.screen_shipment(SHIPMENT, risk_floor=10))
        for c in calls:
            self.assertEqual(c["ttl"], tavily_client.ENTITY_CACHE_TTL_SECONDS)

    def test_no_floor_at_all_uses_the_cache(self):
        """The manual screening endpoint, which passes no floor."""
        calls, fake = self._spy()
        with patch.object(tavily_client, "search_cached", new=fake):
            run(compliance_agent.screen_shipment(SHIPMENT))
        self.assertEqual(len(calls), 2)
        for c in calls:
            self.assertEqual(c["ttl"], tavily_client.ENTITY_CACHE_TTL_SECONDS)

    def test_the_bypass_machinery_is_gone_rather_than_disabled(self):
        """
        Removed, not left switched off. A dormant threshold constant reads as a safety
        feature somebody can re-enable, and the reason it went is that its premise was
        false -- not that the number was wrong.
        """
        self.assertFalse(hasattr(compliance_agent, "_bypass_cache"))
        self.assertFalse(hasattr(compliance_agent, "CACHE_BYPASS_FLOOR_AT"))

    def test_the_cache_hit_record_survived_the_removal(self):
        """
        The part of the original design worth keeping. A reviewer reading a released
        shipment should still be able to tell reused evidence from live.
        """
        async def fake(query, max_results=5, *, ttl_seconds, **kw):
            hit = "Pacific" in query
            return [{"title": "t", "url": "u", "content": "c"}], tavily_client.OK, hit

        with patch.object(tavily_client, "search_cached", new=fake):
            out = run(compliance_agent.screen_shipment(SHIPMENT, risk_floor=95))

        self.assertEqual(out["external_search_cache_hits"], 1)
        self.assertEqual(out["external_search_live"], 1)

    def test_the_orchestrator_still_passes_the_floor(self):
        """
        Kept at the call site so the decision is cheap to revisit. If the floor stops
        being threaded, re-adding a bypass becomes a two-file change again.
        """
        import pathlib

        src = pathlib.Path(__file__).resolve().parents[1] / "src" / "vf_logistics" / "orchestrator.py"
        self.assertIn(
            'risk_floor=validation.get("risk_floor")',
            src.read_text(encoding="utf-8"),
        )


class TestTheSearchStatusReachesTheModel(ComplianceCacheTestCase):
    """
    The bug fix. An outage must never be rendered as a clean result.
    """

    def _prompt_for(self, status):
        calls, fake = self._spy(status=status, results=[])
        with patch.object(tavily_client, "search_cached", new=fake):
            out = run(compliance_agent.screen_shipment(SHIPMENT, risk_floor=10))
        del calls
        return out

    def test_a_failed_search_says_so_in_the_prompt(self):
        for status in (
            tavily_client.RATE_LIMITED,
            tavily_client.TIMEOUT,
            tavily_client.NO_API_KEY,
            tavily_client.HTTP_ERROR,
            tavily_client.TRANSPORT_ERROR,
            tavily_client.BAD_RESPONSE,
        ):
            with self.subTest(status=status):
                out = self._prompt_for(status)
                self.assertIn(
                    "WEB SEARCH DID NOT RUN", out["prompt"],
                    f"{status} must not be rendered to the model as a clean result",
                )
                self.assertEqual(out["external_search_status"], status)

    def test_a_genuinely_empty_result_is_reported_as_having_run(self):
        out = self._prompt_for(tavily_client.OK)
        self.assertIn("search ran and returned nothing", out["prompt"])
        self.assertNotIn("WEB SEARCH DID NOT RUN", out["prompt"])
        self.assertEqual(out["external_search_status"], tavily_client.OK)

    def test_one_failure_out_of_two_searches_is_reported_as_a_failure(self):
        """
        Worst status wins. If the receiver lookup failed, the model must not be told
        the pair came back clean on the strength of the shipper lookup succeeding.
        """
        seq = [tavily_client.OK, tavily_client.RATE_LIMITED]

        async def fake(query, max_results=5, *, ttl_seconds, **kw):
            return [], seq.pop(0), False

        with patch.object(tavily_client, "search_cached", new=fake):
            out = run(compliance_agent.screen_shipment(SHIPMENT, risk_floor=10))

        self.assertEqual(out["external_search_status"], tavily_client.RATE_LIMITED)
        self.assertIn("WEB SEARCH DID NOT RUN", out["prompt"])


class TestTheAuditRecord(ComplianceCacheTestCase):
    def test_cache_hits_are_counted_on_the_step(self):
        async def fake(query, max_results=5, *, ttl_seconds, **kw):
            # Shipper live, receiver from cache.
            hit = "Pacific" in query
            return [{"title": "t", "url": "u", "content": "c"}], tavily_client.OK, hit

        with patch.object(tavily_client, "search_cached", new=fake):
            out = run(compliance_agent.screen_shipment(SHIPMENT, risk_floor=10))

        self.assertEqual(out["external_search_count"], 2)
        self.assertEqual(out["external_search_cache_hits"], 1)
        self.assertEqual(out["external_search_live"], 1)

    def test_the_existing_fields_are_unchanged(self):
        """The console reads these two by name; renaming or dropping one empties a
        panel rather than raising."""
        calls, fake = self._spy()
        with patch.object(tavily_client, "search_cached", new=fake):
            out = run(compliance_agent.screen_shipment(SHIPMENT, risk_floor=10))
        del calls
        self.assertTrue(out["external_search_used"])
        self.assertIsInstance(out["external_search_results"], list)
        self.assertIn("title", out["external_search_results"][0])
        self.assertIn("url", out["external_search_results"][0])

    def test_a_missing_counterparty_name_issues_no_search(self):
        calls, fake = self._spy()
        with patch.object(tavily_client, "search_cached", new=fake):
            out = run(compliance_agent.screen_shipment(
                {"shipment_id": "X", "cargo_description": "goods"}, risk_floor=10,
            ))
        self.assertEqual(len(calls), 0)
        self.assertEqual(out["external_search_count"], 0)
        self.assertFalse(out["external_search_used"])


if __name__ == "__main__":
    unittest.main()
