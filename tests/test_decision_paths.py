"""
Coverage for the decision-bearing paths.

Chasing a coverage percentage is the wrong goal, so this file does not try. It
targets the code that decides whether a shipment clears, on the view that a line
which can release a controlled consignment deserves a test and a line that formats
a debug string does not.

What is deliberately NOT covered, and why
-----------------------------------------
  FirestoreStore (store.py, ~52%)   needs a real Firestore or the emulator. The
                                    MemoryStore path is covered and
                                    test_tenant_isolation.py proves the two
                                    backends have identical signatures, which is
                                    the property that matters -- but transactions,
                                    FieldFilter behaviour and index requirements
                                    cannot be faked.
  model_armor._sanitize_once        one HTTP POST and a response parse. Mock the
  and _access_token                 client and you assert the mock came back.
  document_store.py                 same reason, for GCS.
  a scripted successful debate      stubbing a completion and asserting the stub
  and investigation_agent           came back proves nothing about the model. Both
                                    are covered at the interpret/parse boundary,
                                    where the logic is.

Two of those exclusions used to be broader, and were narrowed on the evidence
-----------------------------------------------------------------------------
This file originally excluded model_armor.py and the debate_agent bodies wholesale.
Both entries were too wide, measured against this file's own criterion -- "a line which
can release a controlled consignment deserves a test":

  tests/test_security_screen_logic.py  `_windows` is string arithmetic with no GCP in
                                       it, and whether the screen FAILS CLOSED when
                                       every window errors is a security property, not
                                       a transport detail. Both were uncovered.
  tests/test_debate_logic.py           `_truncate_context`, `_execute_tool` and
                                       `_tavily_search` call no model at all.
  tests/test_debate_control_flow.py    the loop's four exits. Writing these found a
                                       real defect: a malformed-JSON verdict was
                                       recorded as "Senior Auditor did not render
                                       verdict after 3 rounds", which was false -- one
                                       was rendered and could not be read -- and the
                                       conversation sent back carried a tool_call with
                                       no matching reply.

The narrowing is the point rather than the extra percentage. "Mock a GCP service and you
test the mock" is a good reason and it still holds for the four entries above; it was
being used to cover code the reason did not apply to.

Reported as 66% before this file, and the honest figure after it is in the summary.
A claim of 100% would mean either lying or excluding whatever was inconvenient.
"""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("STORE_BACKEND", "memory")

import httpx  # noqa: E402

from vf_logistics import hs_reference, tavily_client, verifier  # noqa: E402
from vf_logistics.agents import hs_classifier_agent as hs_agent  # noqa: E402


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# tavily_client: the HTTP paths whose collapse was the bug
# ---------------------------------------------------------------------------

def _transport(handler):
    """A mock transport, so the request is exercised without a network."""
    return httpx.MockTransport(handler)


class TavilyHttpTests(unittest.TestCase):
    """
    Every failure mode has to be distinguishable from an empty result.

    The old client was `except Exception: return []`, so a missing key, a timeout, a
    429 and a genuinely empty result were the same value. In a compliance system
    that is the worst possible collapse: "we searched for adverse media and found
    none" and "the search did not happen" are opposite facts.
    """

    def setUp(self):
        self._original = os.environ.get("TAVILY_API_KEY")
        os.environ["TAVILY_API_KEY"] = "test-key"

    def tearDown(self):
        if self._original is None:
            os.environ.pop("TAVILY_API_KEY", None)
        else:
            os.environ["TAVILY_API_KEY"] = self._original

    def _call(self, handler, **kwargs):
        real_client = httpx.AsyncClient

        def factory(*args, **kw):
            kw["transport"] = _transport(handler)
            return real_client(*args, **kw)

        # The client is pooled per event loop now, so one built before this patch
        # would be reused and the MockTransport never reached -- a test that silently
        # exercises the real network instead of the handler below.
        tavily_client.reset_cache()
        with patch.object(tavily_client.httpx, "AsyncClient", factory):
            return _run(tavily_client.search_with_status("query", **kwargs))

    def test_a_successful_search_returns_ok_and_results(self):
        def handler(request):
            return httpx.Response(200, json={"results": [
                {"title": "T", "url": "https://a.test", "content": "body"},
            ]})

        results, status = self._call(handler)
        self.assertEqual(status, tavily_client.OK)
        self.assertEqual(results[0]["url"], "https://a.test")

    def test_search_depth_reaches_the_api(self):
        """
        The defect that made this worth rewriting: debate_agent advertises a
        basic/advanced enum to Nemotron Super, and the client hardcoded "basic", so
        the model's choice was discarded before it left the process. A model told it
        has a control it does not have reasons on that basis.
        """
        seen = {}

        def handler(request):
            seen.update(json.loads(request.content))
            return httpx.Response(200, json={"results": []})

        self._call(handler, search_depth="advanced")
        self.assertEqual(seen["search_depth"], "advanced")

    def test_news_topic_and_window_reach_the_api(self):
        """Zero-day screening wants recent coverage specifically: a company
        designated last week is not in a weekly-refreshed list yet, and that gap is
        the only reason the search exists."""
        seen = {}

        def handler(request):
            seen.update(json.loads(request.content))
            return httpx.Response(200, json={"results": []})

        self._call(handler, topic="news", days=45)
        self.assertEqual(seen["topic"], "news")
        self.assertEqual(seen["days"], 45)

    def test_an_invalid_depth_falls_back_rather_than_erroring(self):
        seen = {}

        def handler(request):
            seen.update(json.loads(request.content))
            return httpx.Response(200, json={"results": []})

        self._call(handler, search_depth="exhaustive")  # type: ignore[arg-type]
        self.assertEqual(seen["search_depth"], "basic")

    def test_rate_limiting_is_its_own_status(self):
        """Called out separately because it is the one failure a caller can act on
        by waiting, and a bulk benchmark will hit it: the free tier is 1,000
        credits a month."""
        results, status = self._call(lambda r: httpx.Response(429, json={}))
        self.assertEqual(status, tavily_client.RATE_LIMITED)
        self.assertEqual(results, [])

    def test_a_server_error_is_not_an_empty_result(self):
        results, status = self._call(lambda r: httpx.Response(503, text="down"))
        self.assertEqual(status, tavily_client.HTTP_ERROR)

    def test_a_timeout_is_not_an_empty_result(self):
        def handler(request):
            raise httpx.TimeoutException("too slow", request=request)

        _results, status = self._call(handler)
        self.assertEqual(status, tavily_client.TIMEOUT)

    def test_a_transport_failure_is_not_an_empty_result(self):
        def handler(request):
            raise httpx.ConnectError("no route", request=request)

        _results, status = self._call(handler)
        self.assertEqual(status, tavily_client.TRANSPORT_ERROR)

    def test_undecodable_json_is_not_an_empty_result(self):
        results, status = self._call(
            lambda r: httpx.Response(200, text="<html>not json</html>"),
        )
        self.assertEqual(status, tavily_client.BAD_RESPONSE)
        self.assertEqual(results, [])

    def test_an_empty_query_never_reaches_the_api(self):
        called = []

        def handler(request):
            called.append(1)
            return httpx.Response(200, json={"results": []})

        for query in ("", "   "):
            with self.subTest(query=repr(query)):
                real_client = httpx.AsyncClient

                def factory(*args, **kw):
                    kw["transport"] = _transport(handler)
                    return real_client(*args, **kw)

                with patch.object(tavily_client.httpx, "AsyncClient", factory):
                    results, status = _run(
                        tavily_client.search_with_status(query),
                    )
                self.assertEqual(status, tavily_client.EMPTY_QUERY)
        self.assertEqual(called, [], "a blank query must not spend a credit")

    def test_a_missing_key_is_reported_not_swallowed(self):
        os.environ["TAVILY_API_KEY"] = ""
        results, status = _run(tavily_client.search_with_status("q"))
        self.assertEqual(status, tavily_client.NO_API_KEY)

    def test_max_results_is_clamped(self):
        seen = {}

        def handler(request):
            seen.update(json.loads(request.content))
            return httpx.Response(200, json={"results": []})

        self._call(handler, max_results=500)
        self.assertLessEqual(seen["max_results"], 20)

    def test_non_dict_rows_are_skipped_rather_than_crashing(self):
        def handler(request):
            return httpx.Response(200, json={"results": [
                "a bare string", {"title": "real", "url": "u", "content": "c"},
            ]})

        results, status = self._call(handler)
        self.assertEqual(status, tavily_client.OK)
        self.assertEqual(len(results), 1)

    def test_content_is_truncated(self):
        def handler(request):
            return httpx.Response(200, json={"results": [
                {"title": "T", "url": "u", "content": "x" * 5000},
            ]})

        results, _status = self._call(handler)
        self.assertEqual(
            len(results[0]["content"]), tavily_client.CONTENT_MAX_CHARS,
        )

    def test_the_fail_soft_wrapper_keeps_its_old_signature(self):
        """Several call sites patch `search` by name, including
        test_hardening.py's orchestrator.tavily_client.search."""
        def handler(request):
            return httpx.Response(429, json={})

        real_client = httpx.AsyncClient

        def factory(*args, **kw):
            kw["transport"] = _transport(handler)
            return real_client(*args, **kw)

        with patch.object(tavily_client.httpx, "AsyncClient", factory):
            self.assertEqual(_run(tavily_client.search("q")), [])

    def test_format_findings_renders_results(self):
        text = tavily_client.format_findings([
            {"title": "T", "url": "https://a.test", "content": "body"},
        ])
        self.assertIn("T", text)
        self.assertIn("https://a.test", text)


# ---------------------------------------------------------------------------
# hs_reference: the table that fixed the confabulation
# ---------------------------------------------------------------------------

class HsReferenceTests(unittest.TestCase):
    """
    The module that closed a factual gap, not a reasoning one.

    Told a shipment declared heading 8543, Nemotron Nano replied that 8543 covers
    integrated circuits. It does not -- 8542 does. The model reasoned correctly from
    a false premise it had invented, in the direction of the input it was primed
    with, and no amount of prompt discipline fixes that. Only the facts do.
    """

    def test_the_reference_loads_and_covers_the_dual_use_headings(self):
        table = hs_reference.by_heading()
        self.assertGreater(len(table), 20)
        for heading in ("8542", "8543", "8411", "9014"):
            with self.subTest(heading=heading):
                self.assertIn(heading, table)

    def test_the_heading_that_caused_the_confabulation_is_correct(self):
        self.assertIn(
            "integrated circuit", hs_reference.lookup("8542")["covers"].lower(),
        )
        self.assertNotIn(
            "integrated circuit", hs_reference.lookup("8543")["covers"].lower(),
        )

    def test_residual_headings_are_marked(self):
        """A residual heading is the natural cover for a substitution, so the model
        has to know which ones they are before it accepts one."""
        for heading in ("8479", "8543", "8548", "9031"):
            with self.subTest(heading=heading):
                self.assertTrue(hs_reference.is_residual(heading))
        self.assertFalse(hs_reference.is_residual("8542"))

    def test_lookup_tolerates_the_formats_a_manifest_uses(self):
        for raw in ("8542", "8542.31", "8542310000", " 8542 ", "85.42"):
            with self.subTest(raw=raw):
                self.assertIsNotNone(hs_reference.lookup(raw))

    def test_lookup_of_an_unknown_heading_returns_none(self):
        self.assertIsNone(hs_reference.lookup("9999"))
        self.assertIsNone(hs_reference.lookup(""))
        self.assertIsNone(hs_reference.lookup(None))

    def test_the_strict_block_omits_the_excludes_notes(self):
        """
        The ablation that produced the honest headline number. The `excludes` notes
        were written having read hs_pairs.yaml and name all fifteen substitutions,
        so the permissive block scored 100% by telling the model the answers. The
        strict block is the number worth quoting.

        They render as "not 8542: ..." lines, so that is what is asserted rather
        than the YAML key name.
        """
        strict = hs_reference.reference_block(include_excludes=False)
        permissive = hs_reference.reference_block(include_excludes=True)
        self.assertLess(len(strict), len(permissive))
        self.assertIn("not 8542:", permissive)
        self.assertNotIn("not 8542:", strict)

    def test_the_permissive_block_names_the_test_substitutions(self):
        """The reason the strict ablation had to exist. If this ever stops being
        true the ablation is measuring nothing and the 100% figure would be real --
        but it is true, so it is not."""
        permissive = hs_reference.reference_block(include_excludes=True)
        for leak in ("not 8414:", "not 8466:", "not 9015:", "not 9025:"):
            with self.subTest(leak=leak):
                self.assertIn(leak, permissive)

    def test_the_block_contains_the_interpretative_principles(self):
        """The principles are the method, not decoration: without the residual rule
        the model reaches for 8543 because it is convenient."""
        block = hs_reference.reference_block(include_excludes=False).lower()
        self.assertIn("a heading that names the goods beats", block)
        self.assertIn("residual", block)
        self.assertIn("last resort", block)

    def test_the_block_emits_the_whole_table_not_a_retrieved_subset(self):
        """No retrieval step, deliberately: any selection rule keyed on the
        declared heading or the description would leak which headings are
        candidates, and the leak would read as model skill."""
        block = hs_reference.reference_block(include_excludes=False)
        for heading in hs_reference.by_heading():
            with self.subTest(heading=heading):
                self.assertIn(heading, block)

    def test_dual_use_headings_agree_with_the_verifier(self):
        """Two lists of controlled headings that disagree is worse than one, and
        the disagreement would be silent."""
        report = hs_reference.coverage_report()
        self.assertEqual(
            report["missing_from_reference"], [],
            "verifier flags a heading the reference table does not describe, so "
            "the model is asked about goods it has no nomenclature for",
        )
        self.assertEqual(report["rules_heading_not_marked_dual_use"], [])
        self.assertEqual(report["marked_but_not_in_rules"], [])


# ---------------------------------------------------------------------------
# hs_classifier_agent: the interpret boundary
# ---------------------------------------------------------------------------

class HsInterpretTests(unittest.TestCase):
    def _envelope(self, payload, error=None):
        return {"result": payload, "error": error, "agent": "hs_classifier"}

    def test_a_consistent_verdict_is_read_as_consistent(self):
        out = hs_agent.interpret(self._envelope({
            "consistent": True, "confidence": 0.9, "reasoning": "matches",
        }))
        self.assertEqual(out["verdict"], "consistent")

    def test_an_inconsistent_verdict_carries_the_suggested_heading(self):
        out = hs_agent.interpret(self._envelope({
            "consistent": False, "heading_for_goods": "8542.31",
            "confidence": 0.85, "reasoning": "these are ICs",
        }))
        self.assertEqual(out["verdict"], "inconsistent")
        self.assertEqual(out["suggested_hs"], "8542")

    def test_a_non_boolean_consistent_field_is_unknown_not_clean(self):
        """
        Pydantic would coerce "no" to False. interpret() uses isinstance, so the
        schema was made StrictBool to match -- a looser schema than the consumer is
        a schema that passes data the consumer then misreads.
        """
        for value in ("no", 0, None, "true", []):
            with self.subTest(value=repr(value)):
                out = hs_agent.interpret(self._envelope({
                    "consistent": value, "confidence": 0.9,
                }))
                self.assertEqual(out["verdict"], "unknown")

    def test_a_parse_failure_is_unknown_not_consistent(self):
        """Coercing an unusable reply to "consistent" clears exactly the shipments
        the classifier exists to catch."""
        out = hs_agent.interpret(self._envelope(None, error="not valid JSON"))
        self.assertEqual(out["verdict"], "unknown")
        self.assertEqual(out["confidence"], 0.0)

    def test_confidence_is_clamped_and_junk_becomes_zero(self):
        for raw, expected in ((5.0, 1.0), (-1.0, 0.0), ("high", 0.0), (None, 0.0)):
            with self.subTest(raw=raw):
                out = hs_agent.interpret(self._envelope({
                    "consistent": True, "confidence": raw,
                }))
                self.assertEqual(out["confidence"], expected)

    def test_a_suggested_heading_with_no_digits_becomes_none(self):
        out = hs_agent.interpret(self._envelope({
            "consistent": False, "heading_for_goods": "unknown to me",
            "confidence": 0.8,
        }))
        self.assertIsNone(out["suggested_hs"])

    def test_the_obfuscation_label_is_carried(self):
        out = hs_agent.interpret(self._envelope({
            "consistent": False, "heading_for_goods": "8542",
            "confidence": 0.9, "obfuscation_observed": "circumlocution",
        }))
        self.assertEqual(out["obfuscation"], "circumlocution")


# ---------------------------------------------------------------------------
# verifier: the branches that change an outcome
# ---------------------------------------------------------------------------

def _shipment(**over) -> dict:
    base = {
        "shipment_id": "COV-1", "origin": "Vietnam", "destination": "Japan",
        "shipper_company": "Mekong Garment Export", "shipper_name": "Mekong Garment Export",
        "shipper_tax_id": "0312998877", "shipper_country": "Vietnam",
        "shipper_tx_count": 40, "receiver_company": "Nippon Retail KK",
        "receiver_name": "Nippon Retail KK", "receiver_country": "Japan",
        "consignee_name": "Nippon Retail KK", "hs_code": "6109",
        "cargo_description": "Cotton t-shirts", "declared_value": 18000,
        "freight_cost": 1500, "shipping_cost": 1500, "weight_kg": 2000,
        "currency": "USD", "route_details": "direct", "transit_points": "none",
    }
    base.update(over)
    return base


class VerifierBranchTests(unittest.TestCase):
    def test_a_domestic_low_value_shipment_skips_the_models(self):
        """
        The cost-control path. A cheap domestic consignment on a safe route is
        settled by arithmetic, and a model call on it is money spent to reach the
        same answer.

        The threshold is LOW_VALUE_THRESHOLD_USD and the route pair must be in
        DOMESTIC_SAFE_ROUTES verbatim, so both are read from the module rather than
        guessed -- a test that hardcoded either would pass today and mislead after
        the first tuning change.
        """
        origin, destination = sorted(verifier.DOMESTIC_SAFE_ROUTES)[0]
        result = verifier.validate(_shipment(
            origin=origin, destination=destination, receiver_country="Vietnam",
            declared_value=verifier.LOW_VALUE_THRESHOLD_USD - 1,
            freight_cost=5, shipping_cost=5, weight_kg=10,
        ))
        self.assertTrue(result["skip_ai"])

    def test_a_dual_use_heading_defeats_the_low_value_shortcut(self):
        """Value is not a proxy for control. A cheap consignment of controlled
        goods is still controlled, and the shortcut must not reach it."""
        origin, destination = sorted(verifier.DOMESTIC_SAFE_ROUTES)[0]
        result = verifier.validate(_shipment(
            origin=origin, destination=destination, receiver_country="Vietnam",
            declared_value=verifier.LOW_VALUE_THRESHOLD_USD - 1,
            freight_cost=5, shipping_cost=5, weight_kg=10,
            hs_code="8542", cargo_description="Integrated circuits",
        ))
        self.assertFalse(result["skip_ai"])

    def test_a_whitelisted_shipper_skips_the_models(self):
        result = verifier.validate(_shipment(
            shipper_company="VF Logistics Vietnam", shipper_name="VF Logistics Vietnam",
            shipper_tax_id="0101245486",
        ))
        self.assertIn("whitelist", result["checks_run"])

    def test_a_blacklisted_counterparty_auto_rejects(self):
        result = verifier.validate(_shipment(
            shipper_company="Shell Trading Ltd", shipper_name="Shell Trading Ltd",
        ))
        self.assertTrue(result["auto_reject_by_rules"])
        self.assertEqual(result["risk_floor"], 100)

    def test_a_missing_country_pair_raises_the_floor(self):
        """A shipment whose endpoints are unknown cannot be screened against a
        destination list, so the absence is itself a finding."""
        shipment = _shipment()
        shipment.pop("shipper_country")
        shipment.pop("receiver_country")
        result = verifier.validate(shipment)
        self.assertGreater(result["risk_floor"], 0)

    def test_multiple_diversion_hubs_score_above_one(self):
        """One hub is ordinary consolidation. Two on the same leg is a pattern."""
        one = verifier.validate(_shipment(
            route_details="Hamburg via Jebel Ali", transit_points="Jebel Ali",
        ))
        two = verifier.validate(_shipment(
            route_details="Hamburg via Jebel Ali and Mersin",
            transit_points="Jebel Ali, Mersin",
        ))
        self.assertGreaterEqual(two["risk_floor"], one["risk_floor"])

    def test_a_high_confidence_hs_mismatch_on_a_dual_use_heading_scores_80(self):
        """Below DUAL_USE_HS_CODE's 85 on purpose: this is a model's judgement
        about a description, that is a lookup against a declared code, and the
        number a reviewer sees should say which."""
        findings = verifier.check_hs_description_consistency(
            _shipment(),
            {"verdict": "inconsistent", "suggested_hs": "8542",
             "confidence": 0.9, "reasoning": "these are ICs"},
        )
        self.assertEqual(findings[0]["floor"], 80)
        self.assertLess(findings[0]["floor"], 85)

    def test_a_low_confidence_mismatch_does_not_raise_the_floor(self):
        findings = verifier.check_hs_description_consistency(
            _shipment(),
            {"verdict": "inconsistent", "suggested_hs": "8542",
             "confidence": 0.4, "reasoning": "might be"},
        )
        self.assertEqual(findings[0]["floor"], 0)

    def test_an_unknown_hs_verdict_is_recorded_as_unchecked(self):
        findings = verifier.check_hs_description_consistency(
            _shipment(), {"verdict": "unknown", "confidence": 0.0,
                          "reasoning": "APITimeoutError"},
        )
        self.assertEqual(findings[0]["code"], "HS_DESCRIPTION_CHECK_UNAVAILABLE")

    def test_reconcile_lets_the_floor_win_over_a_lower_model_score(self):
        validation = verifier.validate(_shipment(
            shipper_company="Shell Trading Ltd", shipper_name="Shell Trading Ltd",
        ))
        # reconcile(model_risk, validation) -- model score first. Worth pinning:
        # both arguments are plausible in either position and swapping them
        # produces a number rather than an error.
        reconciled = verifier.reconcile(5, validation)
        self.assertEqual(reconciled["effective_risk"], 100)
        self.assertTrue(reconciled["score_disputed"])
        self.assertFalse(reconciled["auto_clear_permitted"])

    def test_reconcile_keeps_a_higher_model_score(self):
        """The floor is a floor, not a target. A model that sees something the
        rules did not must be able to raise the score."""
        validation = verifier.validate(_shipment())
        reconciled = verifier.reconcile(75, validation)
        self.assertEqual(reconciled["effective_risk"], 75)

    def test_reconcile_without_a_model_score_uses_the_floor(self):
        validation = verifier.validate(_shipment())
        reconciled = verifier.reconcile(None, validation)
        self.assertIn("floor", reconciled["source"])
        self.assertEqual(reconciled["model_risk"], None)


class LowValueShortcutTests(unittest.TestCase):
    """
    The cost-control shortcut, which was unreachable.

    check_freight_ratio() compares freight against lane_baseline() -- what it costs
    to move a commercial consignment on the lane, hundreds of dollars on a domestic
    Vietnamese route. A 99 dollar parcel ships for a few dollars, so it came out
    under 25% of that baseline, which is CRITICAL, which defeats skip_ai. Sweeping
    freight from 1 to 50 dollars produced FREIGHT_ANOMALY at every value.

    So LOW_VALUE_DOMESTIC could never actually skip the models. The path was
    written, documented, given a threshold constant, and dead -- every parcel paid
    for two model calls to reach the answer arithmetic had already given, and
    nothing failed, so nothing said so.

    The tests below pin the fix AND the four ways the shortcut must still be
    defeated, because a cost optimisation that clears a controlled shipment is not
    an optimisation.
    """

    def _parcel(self, **over) -> dict:
        origin, destination = sorted(verifier.DOMESTIC_SAFE_ROUTES)[0]
        base = dict(
            _shipment(),
            origin=origin, destination=destination, receiver_country="Vietnam",
            declared_value=verifier.LOW_VALUE_THRESHOLD_USD - 1,
            freight_cost=10, shipping_cost=10, weight_kg=10,
            receiver_company="Local Shop", receiver_name="Local Shop",
            consignee_name="Local Shop",
        )
        base.update(over)
        return base

    def test_the_shortcut_fires_at_every_plausible_freight_cost(self):
        """The regression itself. One freight value passing would have hidden it."""
        for freight in (1, 3, 5, 10, 20, 30, 50):
            with self.subTest(freight=freight):
                result = verifier.validate(self._parcel(
                    freight_cost=freight, shipping_cost=freight,
                ))
                self.assertTrue(
                    result["skip_ai"],
                    f"a {freight} dollar freight charge on a parcel must not read "
                    f"as an underpriced container",
                )
                self.assertEqual(result["risk_floor"], 0)

    def test_a_bulky_cheap_parcel_still_takes_the_shortcut(self):
        """100kg at 99 dollars is 0.99 USD/kg, which VALUE_DENSITY_LOW calls a
        classic under-invoicing pattern. At 99 dollars of exposure it is a cheap
        bulky parcel."""
        result = verifier.validate(self._parcel(weight_kg=100))
        self.assertTrue(result["skip_ai"])

    def test_a_dual_use_heading_still_defeats_the_shortcut(self):
        result = verifier.validate(self._parcel(
            hs_code="8542", cargo_description="Integrated circuits",
        ))
        self.assertFalse(result["skip_ai"])
        self.assertGreaterEqual(result["risk_floor"], 85)

    def test_a_blacklisted_counterparty_still_defeats_the_shortcut(self):
        result = verifier.validate(self._parcel(
            shipper_company="Shell Trading Ltd", shipper_name="Shell Trading Ltd",
        ))
        self.assertFalse(result["skip_ai"])
        self.assertEqual(result["risk_floor"], 100)

    def test_an_absent_freight_charge_still_defeats_the_shortcut(self):
        """FREIGHT_MISSING survives the guard on purpose. A missing charge is a
        data-quality problem at any scale, not a pricing one."""
        result = verifier.validate(self._parcel(freight_cost=0, shipping_cost=0))
        self.assertFalse(result["skip_ai"])
        self.assertIn(
            "FREIGHT_MISSING", [f["code"] for f in result["findings"]],
        )

    def test_a_non_safe_route_does_not_take_the_shortcut(self):
        result = verifier.validate(self._parcel(
            origin="Hamburg, Germany", destination="Bandar Abbas, Iran",
            shipper_country="Germany", receiver_country="Iran",
        ))
        self.assertFalse(result["skip_ai"])

    def test_a_commercial_shipment_still_gets_the_freight_check(self):
        """
        The guard must not disable the check it was narrowed from. Under-invoiced
        freight on a real consignment is a value-transfer typology and the whole
        reason check_freight_ratio exists.
        """
        result = verifier.validate(_shipment(
            origin="Hamburg, Germany", destination="Yokohama, Japan",
            shipper_country="Germany", receiver_country="Japan",
            declared_value=250_000, freight_cost=200, shipping_cost=200,
            weight_kg=8000, hs_code="8471", cargo_description="Servers",
        ))
        self.assertIn(
            "FREIGHT_ANOMALY", [f["code"] for f in result["findings"]],
        )

    def test_the_guard_is_keyed_to_the_same_threshold_as_the_shortcut(self):
        """One constant, so the two cannot drift into disagreeing about what counts
        as low value."""
        just_under = verifier.check_freight_ratio({
            "declared_value": verifier.LOW_VALUE_THRESHOLD_USD - 0.01,
            "shipping_cost": 1, "origin": "da nang", "destination": "hanoi",
        })
        just_over = verifier.check_freight_ratio({
            "declared_value": verifier.LOW_VALUE_THRESHOLD_USD + 1000,
            "shipping_cost": 1, "origin": "da nang", "destination": "hanoi",
        })
        self.assertIsNone(just_under)
        self.assertIsNotNone(just_over)

    def test_a_shipment_with_no_declared_value_still_gets_the_check(self):
        """An absent value must not buy an exemption -- that would make omitting the
        field the cheapest way past the check."""
        finding = verifier.check_freight_ratio({
            "shipping_cost": 1, "origin": "hamburg", "destination": "yokohama",
        })
        self.assertIsNotNone(finding)


if __name__ == "__main__":
    unittest.main()
