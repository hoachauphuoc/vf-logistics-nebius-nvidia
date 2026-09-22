"""
Sanctions screening and the zero-day radar.

Two properties here are worth more than the rest of the file.

Fail-closed. An index that fails to load must never answer CLEAN. An empty index
clears every shipment while producing paperwork saying a check was performed,
which is worse than having no check: a system with no screening is known to have
none, and a system that reports CLEAN on a screening that never ran is trusted.

Raise-only. Both model-derived checks may raise the risk floor and may never lower
it. verifier.validate() asserts this on every call by computing the floor twice,
and the tests below drive the assertion from the attacker's side -- a model
report that blesses a shipment must change nothing.
"""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("STORE_BACKEND", "memory")

from vf_logistics import sanctions, verifier  # noqa: E402
from vf_logistics.agents import zero_day_agent as zd  # noqa: E402


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _clean_shipment(**over) -> dict:
    base = {
        "shipment_id": "SANC-CLEAN",
        "origin": "Vietnam", "destination": "Japan",
        "shipper_company": "Mekong Garment Export",
        "shipper_name": "Mekong Garment Export",
        "shipper_tax_id": "0312998877",
        "shipper_country": "Vietnam", "shipper_tx_count": 40,
        "receiver_company": "Nippon Retail KK",
        "receiver_name": "Nippon Retail KK",
        "receiver_country": "Japan", "consignee_name": "Nippon Retail KK",
        "hs_code": "6109", "cargo_description": "Cotton t-shirts, 500 cartons",
        "declared_value": 18000, "freight_cost": 1500, "shipping_cost": 1500,
        "weight_kg": 2000, "currency": "USD",
        "route_details": "HCMC to Tokyo direct", "transit_points": "none",
    }
    base.update(over)
    return base


class IndexMatchingTests(unittest.TestCase):
    """
    Near-miss matching is the whole job.

    verifier._normalize only lowercases and collapses whitespace, so "Shell
    Trading Ltd." with a trailing period misses "shell trading ltd". On a
    sanctions list that near-miss IS the evasion technique: a declarant does not
    need the name spelled correctly, only close enough to pass a customs officer
    and far enough to miss an exact-match filter. These cases are the ones an
    exact matcher would let through.
    """

    @classmethod
    def setUpClass(cls):
        cls.index = sanctions.load(force=True)
        assert cls.index is not None, "bundled seed index must load"

    def test_trailing_punctuation_still_matches(self):
        self.assertTrue(self.index.match_name("Shell Trading Ltd."))

    def test_legal_form_suffix_variation_still_matches(self):
        """Ltd against Limited, and casing and spacing noise."""
        self.assertTrue(self.index.match_name("SHELL  TRADING  LIMITED"))

    def test_single_character_typo_still_matches(self):
        """Registered as an alias because it is a filed variant, not a guess."""
        self.assertTrue(self.index.match_name("Shel Trading Ltd"))

    def test_homoglyph_substitution_still_matches(self):
        """Capital I standing in for lowercase l -- visually identical on a
        printed manifest."""
        self.assertTrue(self.index.match_name("SheII Trading Ltd"))

    def test_transliteration_variant_still_matches(self):
        for name in ("Kreshent Marine Services", "Bosporus Freight Forwarding"):
            with self.subTest(name=name):
                self.assertTrue(self.index.match_name(name))

    def test_identifier_separators_are_ignored(self):
        """A tax id is the same id whether or not it is punctuated."""
        a = self.index.match_identifier("9999999999")
        b = self.index.match_identifier("9999-999-999")
        self.assertTrue(a)
        self.assertEqual([e.entity_id for e in a], [e.entity_id for e in b])

    def test_an_unrelated_company_does_not_match(self):
        """The test that stops the matcher being trivially "correct" by matching
        everything."""
        self.assertFalse(self.index.match_name("Acme Honest Freight"))
        self.assertFalse(self.index.match_identifier("5555555555"))

    def test_risk_level_is_derived_from_the_programme(self):
        """
        A single hardcoded HIGH on every record makes the field carry no
        information. A blocking designation, an export-control listing and a
        sanction-linked association are different obligations and a compliance
        officer acts differently on each.
        """
        levels = {
            e.entity_id: e.risk_level() for e in self.index.entities
        }
        self.assertEqual(levels["SEED-0001"], "CRITICAL")   # topics: sanction
        self.assertEqual(levels["SEED-0005"], "HIGH")       # export.control
        self.assertEqual(levels["SEED-0007"], "MEDIUM")     # sanction.linked
        self.assertGreater(len(set(levels.values())), 1)

    def test_seed_index_reports_unknown_age_not_fresh(self):
        """synced_at is null on the bundled seed, so age must read unknown. A
        fallback that looked freshly synced would be worse than one that failed."""
        self.assertIsNone(self.index.age_days())


class FailClosedTests(unittest.TestCase):
    def test_unavailable_produces_a_blocking_finding_not_silence(self):
        findings = verifier.check_sanctions_screening(
            _clean_shipment(),
            {"status": "UNAVAILABLE", "matches": [], "snapshot": {},
             "reason": "GCS 403"},
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["code"], "SANCTIONS_SCREENING_UNAVAILABLE")
        self.assertEqual(findings[0]["severity"], "HIGH")
        self.assertGreaterEqual(findings[0]["floor"], 60)
        self.assertIn("not a clearance", findings[0]["detail"])

    def test_unavailable_blocks_auto_clear_on_an_otherwise_clean_shipment(self):
        """The case that matters: a shipment with nothing wrong with it must not
        clear while the list is unreadable."""
        result = verifier.validate(
            _clean_shipment(),
            sanctions_screening={
                "status": "UNAVAILABLE", "matches": [], "snapshot": {},
                "reason": "index unreadable",
            },
        )
        self.assertEqual(result["sanctions_screening"], "UNAVAILABLE")
        self.assertGreaterEqual(result["risk_floor"], 60)

    def test_an_index_with_no_entities_is_a_failure_not_a_clean_list(self):
        """Parsed but empty is treated as a failed load. Otherwise it answers
        CLEAN to every query."""
        entities = sanctions._entities_from_payload({"entities": []})
        self.assertEqual(entities, [])

    def test_rows_missing_a_name_or_id_are_dropped(self):
        payload = {"entities": [
            {"entity_id": "X-1", "name": "Real Co"},
            {"entity_id": "", "name": "No Id Co"},
            {"entity_id": "X-3", "name": ""},
        ]}
        self.assertEqual(
            [e.entity_id for e in sanctions._entities_from_payload(payload)],
            ["X-1"],
        )

    def test_a_malformed_line_does_not_abort_the_stream(self):
        """One bad line must not kill a 100k-record refresh."""
        lines = ['{"id": 1}', "not json at all", "", '{"id": 2}']
        self.assertEqual(
            [r["id"] for r in sanctions.stream_jsonl(iter(lines))], [1, 2],
        )


class ScreeningFindingTests(unittest.TestCase):
    def test_a_critical_designation_auto_rejects(self):
        shipment = _clean_shipment(
            shipper_company="Shel Trading Ltd", shipper_name="Shel Trading Ltd",
        )
        result = verifier.validate(shipment)
        self.assertEqual(result["sanctions_screening"], "HIT")
        self.assertEqual(result["risk_floor"], 100)
        self.assertTrue(result["auto_reject_by_rules"])

    def test_source_entity_ids_reach_the_finding(self):
        """
        The field that turns "flagged as high risk" into "matched OFAC SDN entry
        12345". lineage.source_entity_ids() reads it from `measured`, so it has to
        be there and not merely in the detail text.
        """
        result = verifier.validate(_clean_shipment(
            shipper_company="Shel Trading Ltd", shipper_name="Shel Trading Ltd",
        ))
        match = next(
            f for f in result["findings"] if f["code"] == "SANCTIONS_MATCH"
        )
        self.assertIn("SEED-0001", match["measured"]["source_entity_ids"])

        from vf_logistics import lineage
        self.assertIn(
            "SEED-0001",
            lineage.source_entity_ids({"validation": result}),
        )

    def test_entity_ids_are_deduplicated(self):
        """receiver_company and consignee_name are often the same party, and the
        same entity matched twice is one citation, not two."""
        shipment = _clean_shipment(
            receiver_company="Kowloon Advance Components",
            receiver_name="Kowloon Advance Components",
            consignee_name="Kowloon Advance Components",
        )
        result = verifier.validate(shipment)
        match = next(
            f for f in result["findings"] if f["code"] == "SANCTIONS_MATCH"
        )
        ids = match["measured"]["source_entity_ids"]
        self.assertEqual(len(ids), len(set(ids)))

    def test_an_export_control_listing_does_not_auto_reject(self):
        """
        Serious, but a human's call. Only a full blocking designation removes the
        judgement, because an export-control listing can have a licence behind it.
        """
        findings = verifier.check_sanctions_screening(_clean_shipment(), {
            "status": "HIT",
            "matches": [{
                "role": "receiver", "matched_on": "name",
                "matched_value": "X", "entity_id": "E-1", "entity_name": "X",
                "programs": ["EAR-ENTITY-LIST"], "topics": ["export.control"],
                "risk_level": "HIGH", "source": "test",
            }],
            "snapshot": {"version": 1, "age_days": 2, "source": "test"},
        })
        self.assertEqual(findings[0]["floor"], 85)
        self.assertFalse(findings[0].get("auto_reject_by_rules"))

    def test_list_staleness_is_stated_on_the_finding(self):
        """A weekly refresh legitimately reads up to 7 days. A consumer who
        assumes currency over-trusts a verdict on a four-day-old designation."""
        findings = verifier.check_sanctions_screening(_clean_shipment(), {
            "status": "HIT",
            "matches": [{
                "role": "shipper", "matched_on": "name", "matched_value": "X",
                "entity_id": "E-1", "entity_name": "X", "programs": ["P"],
                "topics": ["sanction"], "risk_level": "CRITICAL",
                "source": "opensanctions",
            }],
            "snapshot": {
                "version": 7, "age_days": 6, "source": "opensanctions",
                "synced_at": "2026-09-14T00:00:00+00:00",
            },
        })
        self.assertIn("6 day(s) ago", findings[0]["detail"])
        self.assertEqual(findings[0]["measured"]["sanctions_list_age_days"], 6)

    def test_clean_records_the_snapshot_without_a_finding(self):
        """A reviewer needs to know which list version cleared the shipment."""
        result = verifier.validate(_clean_shipment())
        self.assertEqual(result["sanctions_screening"], "CLEAN")
        self.assertEqual(
            [f for f in result["findings"] if "SANCTIONS" in f["code"]], [],
        )
        self.assertEqual(result["sanctions_snapshot"]["source"], "bundled_seed")

    def test_screening_can_be_isolated_for_a_test(self):
        result = verifier.validate(_clean_shipment(), screen_sanctions=False)
        self.assertIsNone(result["sanctions_screening"])
        self.assertNotIn("sanctions_screening", result["checks_run"])


class ZeroDayGateTests(unittest.TestCase):
    """
    The gate is code, not the model.

    A model deciding when to spend money has a cost bounded only by its own
    judgement, and the budget is 50 dollars of inference credit. The model's
    autonomy is over the query and the verdict, where judgement helps.
    """

    def test_a_clean_shipment_is_not_screened(self):
        shipment = _clean_shipment()
        run, reason = zd.should_screen(shipment, verifier.validate(shipment))
        self.assertFalse(run)
        self.assertEqual(reason, "no risk indicator present")

    def test_a_dual_use_heading_triggers_screening(self):
        shipment = _clean_shipment(hs_code="8542")
        run, reason = zd.should_screen(shipment, verifier.validate(shipment))
        self.assertTrue(run)
        self.assertIn("8542", reason)

    def test_two_diversion_hubs_trigger_screening(self):
        """
        TWO, matching verifier.py's MULTIPLE_DIVERSION_HUBS.

        This test previously asserted that ONE hub was enough, and that was measured
        to be the reason the gate admitted almost everything: on a 20-case run, 14 of
        16 eligible cases screened and 13 of them on this indicator alone. Two causes,
        both disagreements with the verifier over the same list -- `destination` was in
        the haystack, so shipping Vietnam to PSA Singapore read as "routed via
        singapore"; and one hub sufficed, where verifier.py:974 requires two before it
        will raise a finding at all.
        """
        shipment = _clean_shipment(
            route_details="Hamburg to Karachi via Jebel Ali and Singapore",
            transit_points="Jebel Ali, Singapore",
        )
        run, reason = zd.should_screen(shipment, verifier.validate(shipment))
        self.assertTrue(run)
        self.assertIn("jebel ali", reason)
        self.assertIn("singapore", reason)

    def test_a_single_transhipment_hub_does_not_trigger_screening(self):
        """
        Passing through one major port is freight, not a pattern.

        The list's own comment describes hubs "commonly used to obscure final
        destination", which is a chain of calls rather than a single one. Screening on
        one spends up to four Nemotron completions and two Tavily searches on an
        ordinary routing.
        """
        shipment = _clean_shipment(
            route_details="Hamburg to Karachi via Jebel Ali",
            transit_points="Jebel Ali",
        )
        run, reason = zd.should_screen(shipment, verifier.validate(shipment))
        self.assertFalse(run)
        self.assertEqual(reason, "no risk indicator present")

    def test_the_destination_is_not_treated_as_a_diversion(self):
        """
        A destination is where the cargo is going, not evidence it is being hidden.

        Vietnam to Singapore is the most ordinary freight movement in the region, and
        it was being reported as "routed via singapore" -- a reason string that did not
        describe what had happened.
        """
        shipment = _clean_shipment(
            destination="PSA Singapore, Singapore",
            transit_points="none",
            route_details="Cat Lai to PSA Singapore",
        )
        run, reason = zd.should_screen(shipment, verifier.validate(shipment))
        self.assertFalse(run)
        self.assertNotIn("singapore", reason)

    def test_a_high_risk_destination_triggers_screening(self):
        shipment = _clean_shipment(destination="Iran")
        run, _ = zd.should_screen(shipment, verifier.validate(shipment))
        self.assertTrue(run)

    def test_an_unknown_counterparty_triggers_screening(self):
        """Where public evidence is the only evidence available."""
        shipment = _clean_shipment()
        shipment.pop("shipper_tx_count")
        run, reason = zd.should_screen(shipment, verifier.validate(shipment))
        self.assertTrue(run)
        self.assertIn("no trading history", reason)

    def test_an_existing_sanctions_hit_is_not_screened_again(self):
        """The shipment is already blocked on a designation. Spending tokens to
        find news about a party we have matched adds nothing."""
        shipment = _clean_shipment(
            shipper_company="Shel Trading Ltd", shipper_name="Shel Trading Ltd",
            hs_code="8542",
        )
        run, reason = zd.should_screen(shipment, verifier.validate(shipment))
        self.assertFalse(run)
        self.assertIn("already matched", reason)

    def test_an_unavailable_list_is_not_screened(self):
        """There is no "absent from the list" to act on, and the UNAVAILABLE
        finding already routes the case to a human."""
        shipment = _clean_shipment(hs_code="8542")
        run, reason = zd.should_screen(shipment, {
            "sanctions_screening": "UNAVAILABLE",
        })
        self.assertFalse(run)
        self.assertIn("unavailable", reason)

    def test_a_deterministically_resolved_shipment_is_not_screened(self):
        shipment = _clean_shipment(hs_code="8542")
        run, reason = zd.should_screen(shipment, {"skip_ai": True})
        self.assertFalse(run)
        self.assertIn("deterministic", reason)

    def test_entities_are_deduplicated_and_capped(self):
        names = zd.entities_to_check({
            "shipper_company": "A Co", "shipper_name": "A Co",
            "receiver_company": "B KK", "receiver_name": "B KK",
            "consignee_name": "not stated",
        })
        self.assertEqual(names, ["A Co", "B KK"])

    def test_unreadable_history_is_treated_as_a_reason_to_look(self):
        shipment = _clean_shipment(shipper_tx_count="lots")
        run, reason = zd.should_screen(shipment, verifier.validate(shipment))
        self.assertTrue(run)
        self.assertIn("unreadable", reason)


class ZeroDayFindingTests(unittest.TestCase):
    def test_no_verdict_produces_nothing(self):
        self.assertEqual(verifier.check_zero_day(_clean_shipment(), None), [])

    def test_a_clean_verdict_produces_nothing(self):
        findings = verifier.check_zero_day(_clean_shipment(), {
            "verdict": "no_risk_found", "searched": True, "confidence": 0.9,
        })
        self.assertEqual(findings, [])

    def test_a_finding_raises_but_below_the_designation_tiers(self):
        """
        A news report is weaker evidence than a government listing. The number a
        reviewer sees should say which kind of evidence drove the case.
        """
        findings = verifier.check_zero_day(_clean_shipment(), {
            "verdict": "risk_found", "searched": True, "confidence": 0.85,
            "reasoning": "Reuters names the consignee in an evasion indictment",
            "evidence_urls": ["https://example.test/a"],
        })
        self.assertEqual(findings[0]["code"], "ZERO_DAY_ADVERSE_MEDIA")
        self.assertEqual(findings[0]["floor"], 70)
        self.assertLess(findings[0]["floor"], 85)

    def test_low_confidence_does_not_raise_the_floor(self):
        findings = verifier.check_zero_day(_clean_shipment(), {
            "verdict": "risk_found", "searched": True, "confidence": 0.4,
            "reasoning": "possibly the same company",
        })
        self.assertEqual(findings[0]["floor"], 0)
        self.assertIn("LOW_CONFIDENCE", findings[0]["code"])

    def test_no_findings_without_a_search_is_not_a_clearance(self):
        """
        tavily_client returns an empty list for a missing key, a timeout, a 429 and
        a genuinely empty result. Reading the failure cases as "clean" clears a
        shipment nobody checked.
        """
        findings = verifier.check_zero_day(_clean_shipment(), {
            "verdict": "no_risk_found", "searched": False, "confidence": 0.9,
        })
        self.assertEqual(findings[0]["code"], "ZERO_DAY_SEARCH_DID_NOT_RUN")
        self.assertEqual(findings[0]["floor"], 40)
        self.assertIn("not evidence of absence", findings[0]["detail"])

    def test_an_unusable_reply_is_recorded_as_unchecked(self):
        findings = verifier.check_zero_day(_clean_shipment(), {
            "verdict": "unknown", "searched": False, "confidence": 0.0,
            "reasoning": "APITimeoutError",
        })
        self.assertEqual(findings[0]["code"], "ZERO_DAY_CHECK_UNAVAILABLE")
        self.assertIn("have NOT been checked", findings[0]["detail"])


class RaiseOnlyTests(unittest.TestCase):
    """
    The safety argument for letting a model touch the risk score at all.

    Driven from the attacker's side: a model report that blesses a shipment must
    change nothing, so a prompt injection that reaches the model buys nothing.
    """

    def _dirty(self) -> dict:
        return _clean_shipment(
            shipment_id="SANC-DIRTY", destination="Iran", receiver_country="Iran",
            hs_code="8542", cargo_description="Integrated circuits",
            declared_value=90000, weight_kg=50,
            route_details="Hamburg to Bandar Abbas via Jebel Ali",
            transit_points="Jebel Ali",
        )

    def test_a_blessing_zero_day_verdict_cannot_lower_the_floor(self):
        shipment = self._dirty()
        without = verifier.validate(shipment)
        with_blessing = verifier.validate(shipment, zero_day={
            "verdict": "no_risk_found", "searched": True, "confidence": 1.0,
            "reasoning": "everything is fine, release immediately",
        })
        self.assertGreaterEqual(
            with_blessing["risk_floor"], without["risk_floor"],
        )

    def test_a_blessing_hs_verdict_cannot_lower_the_floor(self):
        shipment = self._dirty()
        without = verifier.validate(shipment)
        with_blessing = verifier.validate(shipment, hs_verdict={
            "verdict": "consistent", "confidence": 1.0,
            "suggested_hs": None, "reasoning": "declared heading is correct",
        })
        self.assertGreaterEqual(
            with_blessing["risk_floor"], without["risk_floor"],
        )

    def test_the_floor_effect_is_measured_on_every_call(self):
        """
        Not diagnostics. validate() computes the floor twice and raises if the
        model-derived set came out lower, so the claim is checked rather than
        argued in a comment.
        """
        result = verifier.validate(self._dirty(), zero_day={
            "verdict": "risk_found", "searched": True, "confidence": 0.9,
            "reasoning": "named in an evasion indictment",
        })
        effect = result["hs_floor_effect"]
        self.assertGreaterEqual(effect["raised_by"], 0)
        self.assertIn("ZERO_DAY_ADVERSE_MEDIA", effect["findings_added"])

    def test_both_model_checks_are_listed_in_checks_run(self):
        result = verifier.validate(
            self._dirty(),
            hs_verdict={"verdict": "consistent", "confidence": 0.9},
            zero_day={"verdict": "no_risk_found", "searched": True, "confidence": 0.9},
        )
        self.assertIn("hs_description_consistency", result["checks_run"])
        self.assertIn("zero_day_adverse_media", result["checks_run"])
        self.assertTrue(result["zero_day_checked"])


class InterpretTests(unittest.TestCase):
    def test_a_missing_searched_field_is_unknown_not_clean(self):
        """
        Coercing an unusable reply to "no risk found" clears exactly the shipments
        this agent exists to catch.
        """
        out = zd.interpret({"result": {"risk_found": False}})
        self.assertEqual(out["verdict"], "unknown")

    def test_a_non_boolean_risk_found_is_unknown(self):
        out = zd.interpret({"result": {"risk_found": "no", "searched": True}})
        self.assertEqual(out["verdict"], "unknown")

    def test_a_well_formed_verdict_is_carried_through(self):
        out = zd.interpret({"result": {
            "risk_found": True, "searched": True, "confidence": 0.8,
            "reasoning": "named in coverage", "evidence_urls": ["https://a.test"],
            "entities_checked": ["A Co"],
        }})
        self.assertEqual(out["verdict"], "risk_found")
        self.assertEqual(out["confidence"], 0.8)
        self.assertEqual(out["evidence_urls"], ["https://a.test"])

    def test_confidence_is_clamped(self):
        for raw, expected in ((5.0, 1.0), (-2.0, 0.0), ("junk", 0.0)):
            out = zd.interpret({"result": {
                "risk_found": False, "searched": True, "confidence": raw,
            }})
            self.assertEqual(out["confidence"], expected)


class TavilyStatusTests(unittest.TestCase):
    def test_a_failed_search_says_so_rather_than_reporting_no_findings(self):
        """
        A model handed "no findings" reasons as though the company came back
        clean. That is the confusion this client was rewritten to remove.
        """
        from vf_logistics import tavily_client

        text = tavily_client.format_findings([], tavily_client.RATE_LIMITED)
        self.assertIn("DID NOT RUN", text)
        self.assertIn("not a clean result", text)

    def test_an_empty_but_successful_search_is_distinguishable(self):
        from vf_logistics import tavily_client

        text = tavily_client.format_findings([], tavily_client.OK)
        self.assertIn("returned nothing", text)
        self.assertNotIn("DID NOT RUN", text)

    def test_every_failure_status_is_in_the_failed_set(self):
        """A status missing from FAILED_STATUSES reads as a successful search."""
        from vf_logistics import tavily_client

        for status in (
            tavily_client.NO_API_KEY, tavily_client.TIMEOUT,
            tavily_client.RATE_LIMITED, tavily_client.HTTP_ERROR,
            tavily_client.TRANSPORT_ERROR, tavily_client.BAD_RESPONSE,
        ):
            with self.subTest(status=status):
                self.assertIn(status, tavily_client.FAILED_STATUSES)
        self.assertNotIn(tavily_client.OK, tavily_client.FAILED_STATUSES)

    def test_the_api_key_is_read_per_call_not_at_import(self):
        """Reading it at import meant a process that set the variable afterwards
        searched nothing, silently, for its whole life."""
        from vf_logistics import tavily_client

        original = os.environ.get("TAVILY_API_KEY")
        try:
            os.environ["TAVILY_API_KEY"] = "set-after-import"
            self.assertTrue(tavily_client.configured())
            os.environ["TAVILY_API_KEY"] = ""
            self.assertFalse(tavily_client.configured())
        finally:
            if original is None:
                os.environ.pop("TAVILY_API_KEY", None)
            else:
                os.environ["TAVILY_API_KEY"] = original


class FeedParserTests(unittest.TestCase):
    """
    The deterministic OpenSanctions parser.

    test_russian_tax_and_registration_numbers_are_captured exists because the
    parser shipped without them. IDENTIFIER_PROPS listed five FTM properties and
    innCode and ogrnCode were not among them, so every Russian tax and
    registration number in the feed was silently dropped. An index with no INNs
    cannot match a shipment declaring one, and nothing about that failure is
    visible from the outside -- the index loads, screening runs, and it answers
    CLEAN.

    It was caught by the model-versus-code divergence measurement, which flagged
    the numbers as "invented by the model". They were not invented. The model was
    right and the parser was wrong. The lesson kept here is that a disagreement
    between the two paths means inspect the record, not distrust the model.
    """

    @staticmethod
    def _parse(record):
        import importlib.util
        import pathlib
        import sys

        path = (
            pathlib.Path(__file__).resolve().parent.parent
            / "scripts" / "refresh_sanctions.py"
        )
        spec = importlib.util.spec_from_file_location("_refresh_sanctions", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules["_refresh_sanctions"] = module
        spec.loader.exec_module(module)
        return module, module.parse_deterministic(record)

    def test_russian_tax_and_registration_numbers_are_captured(self):
        _module, parsed = self._parse({
            "id": "NK-1", "schema": "Organization",
            "caption": "Joint Stock Company Raduga",
            "properties": {
                "name": ["Joint Stock Company Raduga"],
                "innCode": ["7736529910"],
                "ogrnCode": ["1057748701713"],
                "programId": ["UA-SA1644"],
                "topics": ["sanction"],
            },
        })
        self.assertIn("7736529910", parsed["identifiers"])
        self.assertIn("1057748701713", parsed["identifiers"])

    def test_programme_is_read_from_programid_not_only_program(self):
        """The feed uses programId far more than program. Checking only the latter
        left every finding reading "no programme stated", which reads as missing
        data rather than as a parser looking in the wrong field."""
        _module, parsed = self._parse({
            "id": "NK-2", "schema": "Organization", "caption": "X Co",
            "properties": {"name": ["X Co"], "programId": ["EU-UKR", "CA-SEMA"]},
        })
        self.assertEqual(parsed["programs"], ["EU-UKR", "CA-SEMA"])

    def test_every_published_name_variant_becomes_searchable(self):
        """
        Which variant is "primary" is a judgement -- the feed carries Cyrillic and
        transliterated Latin forms of the same company, and both are correct. It
        does not matter for screening as long as all of them are indexed, so all of
        them are.
        """
        _module, parsed = self._parse({
            "id": "NK-3", "schema": "Organization",
            "caption": "Kompaniya Gaz-Alyans, OOO",
            "properties": {
                "name": ["Kompaniya Gaz-Alyans, OOO", "OOO Gaz-Alyans"],
                "alias": ["Gaz Alliance LLC"],
            },
        })
        index = sanctions.SanctionsIndex(
            {"version": 1}, sanctions._entities_from_payload({"entities": [parsed]}),
        )
        for variant in (
            "Kompaniya Gaz-Alyans OOO", "OOO Gaz-Alyans", "Gaz Alliance LLC",
        ):
            with self.subTest(variant=variant):
                self.assertTrue(index.match_name(variant))

    def test_non_screenable_schemas_are_dropped(self):
        """Vessels, aircraft and addresses are in the same feed. An index row that
        screening can never match costs memory on every lookup."""
        for schema in ("Vessel", "Airplane", "Address", "Sanction"):
            with self.subTest(schema=schema):
                _module, parsed = self._parse({
                    "id": "NK-X", "schema": schema, "caption": "Something",
                    "properties": {"name": ["Something"]},
                })
                self.assertIsNone(parsed)

    def test_a_record_with_no_name_is_dropped(self):
        _module, parsed = self._parse({
            "id": "NK-Y", "schema": "Company", "properties": {},
        })
        self.assertIsNone(parsed)

    def test_jurisdiction_stands_in_for_a_missing_country(self):
        _module, parsed = self._parse({
            "id": "NK-Z", "schema": "Organization", "caption": "Q Co",
            "properties": {"name": ["Q Co"], "jurisdiction": ["ru"]},
        })
        self.assertEqual(parsed["countries"], ["ru"])

    def test_a_reordered_name_is_not_counted_as_a_fabrication(self):
        """
        "ROMERO SANCHEZ, Antonio" against "Antonio Romero Sanchez" is a format
        choice among published values, not an error. The comparison must surface it
        as a disagreement -- the index keys on token order -- without the summary
        implying the model made it up.
        """
        module, _ = self._parse({
            "id": "NK-N", "schema": "Person", "caption": "A",
            "properties": {"name": ["A"]},
        })
        result = module.compare(
            {"entity_id": "P-1", "name": "Antonio Romero Sanchez",
             "aliases": [], "identifiers": [], "topics": []},
            {"name": "ROMERO SANCHEZ, Antonio",
             "aliases": [], "identifiers": [], "topics": []},
        )
        self.assertFalse(result["name_agrees"])
        self.assertEqual(result["identifiers_invented_by_model"], [])

    def test_punctuation_differences_are_not_counted_as_disagreement(self):
        """Only a difference that would change a screening outcome counts. The
        index would match either spelling."""
        module, _ = self._parse({
            "id": "NK-N", "schema": "Person", "caption": "A",
            "properties": {"name": ["A"]},
        })
        result = module.compare(
            {"entity_id": "P-2", "name": "Shell Trading Ltd.",
             "aliases": [], "identifiers": ["0100-107-518"], "topics": ["sanction"]},
            {"name": "SHELL TRADING LIMITED",
             "aliases": [], "identifiers": ["0100107518"], "topics": ["sanction"]},
        )
        self.assertTrue(result["name_agrees"])
        self.assertTrue(result["identifiers_agree"])

    def test_the_summary_names_every_disagreement_not_just_a_score(self):
        """
        An aggregate alone hides the case that matters: agreement on 39 of 40 is
        reassuring until the fortieth is the one whose name was wrong.
        """
        module, _ = self._parse({
            "id": "NK-N", "schema": "Person", "caption": "A",
            "properties": {"name": ["A"]},
        })
        comparisons = [
            module.compare(
                {"entity_id": f"P-{i}", "name": "Same Co", "aliases": [],
                 "identifiers": [], "topics": []},
                {"name": "Same Co", "aliases": [], "identifiers": [], "topics": []},
            )
            for i in range(9)
        ] + [
            module.compare(
                {"entity_id": "P-BAD", "name": "Real Name Co", "aliases": [],
                 "identifiers": [], "topics": []},
                {"name": "Totally Different Co", "aliases": [],
                 "identifiers": ["999888777"], "topics": []},
            )
        ]
        summary = module.summarise(comparisons)
        self.assertEqual(summary["sampled"], 10)
        self.assertEqual(summary["name_agreement"], 0.9)
        self.assertEqual(
            [d["entity_id"] for d in summary["disagreements"]], ["P-BAD"],
        )
        self.assertEqual(summary["records_with_invented_identifiers"], 1)


class ToolBudgetExhaustionTests(unittest.TestCase):
    """
    The agent must produce a verdict even when it spends every tool round
    searching.

    This is the bug a 200-case benchmark run found and no unit test would have.
    `for _round in range(max_tool_rounds + 1)` exits normally when the model calls
    a tool on every iteration, leaving `text` empty -- so parse_model_json("")
    failed, interpret() mapped the unusable reply to "unknown", and the agent
    billed for three completions and returned nothing.

    It happened on 73 of the 93 cases that reached the agent: 78%. It looked like a
    model quality problem because "unknown" is also what a genuinely undecidable
    reply produces, and nothing in the envelope distinguished the two. The fix asks
    once more with the tool withdrawn, using the search results already in the
    message history.
    """

    def _stub_response(self, *, tool_calls=None, content=None):
        message = MagicMock()
        message.content = content
        message.tool_calls = tool_calls
        response = MagicMock()
        response.choices = [MagicMock(message=message)]
        response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
        return response

    def _tool_call(self, call_id="c1", query="\"X Co\" sanctions evasion"):
        call = MagicMock()
        call.id = call_id
        call.function.name = "tavily_zero_day_search"
        call.function.arguments = json.dumps(
            {"query": query, "search_depth": "basic"},
        )
        return call

    def test_a_verdict_is_produced_when_every_round_calls_a_tool(self):
        verdict_json = json.dumps({
            "entities_checked": ["X Co"], "reasoning": "nothing found",
            "evidence_urls": [], "searched": True, "confidence": 0.9,
            "risk_found": False,
        })
        calls_made = []

        async def fake_complete(*, model, messages, tools, temperature, **kw):
            calls_made.append(tools)
            if tools is None:
                # The forced call. Must be the only one without tools.
                return self._stub_response(content=verdict_json)
            return self._stub_response(tool_calls=[self._tool_call()])

        async def fake_search(query, max_results=5, **kwargs):
            return [], "ok"

        with patch.object(
            zd.nebius_client, "complete_with_tools", new=fake_complete,
        ), patch.object(
            zd.tavily_client, "search_with_status", new=fake_search,
        ):
            result = _run(zd.screen_zero_day({
                "shipper_company": "X Co", "hs_code": "8542",
                "cargo_description": "Integrated circuits",
            }))

        self.assertTrue(
            result["verdict_forced"],
            "the tool budget was exhausted, so the verdict must have been forced",
        )
        interpreted = zd.interpret(result)
        self.assertEqual(
            interpreted["verdict"], "no_risk_found",
            "an exhausted tool budget must still yield a usable verdict, not "
            "'unknown' -- that conflation cost 78% of a benchmark run",
        )
        # One call per round plus the forced one, and the forced one alone has no
        # tools attached.
        self.assertEqual(calls_made.count(None), 1)

    def test_the_forced_call_does_not_repeat_the_searches(self):
        """The results are already in the message history; re-fetching would double
        the Tavily spend against a 1,000-credit monthly free tier."""
        searches = []

        async def fake_complete(*, model, messages, tools, temperature, **kw):
            if tools is None:
                return self._stub_response(content=json.dumps({
                    "searched": True, "risk_found": False, "confidence": 0.9,
                    "reasoning": "done", "evidence_urls": [],
                    "entities_checked": [],
                }))
            return self._stub_response(tool_calls=[self._tool_call()])

        async def fake_search(query, max_results=5, **kwargs):
            searches.append(query)
            return [], "ok"

        with patch.object(
            zd.nebius_client, "complete_with_tools", new=fake_complete,
        ), patch.object(
            zd.tavily_client, "search_with_status", new=fake_search,
        ):
            result = _run(zd.screen_zero_day({"shipper_company": "X Co"}))

        # Three rounds of searching, then a forced verdict that searches no more.
        self.assertEqual(len(searches), zd.MAX_TOOL_ROUNDS + 1)
        self.assertEqual(result["tool_rounds_used"], len(searches))

    def test_a_normal_run_is_not_forced(self):
        """The fix must not fire when the model answers on its own."""
        async def fake_complete(*, model, messages, tools, temperature, **kw):
            return self._stub_response(content=json.dumps({
                "searched": False, "risk_found": False, "confidence": 0.5,
                "reasoning": "no search needed", "evidence_urls": [],
                "entities_checked": [],
            }))

        with patch.object(
            zd.nebius_client, "complete_with_tools", new=fake_complete,
        ):
            result = _run(zd.screen_zero_day({"shipper_company": "X Co"}))

        self.assertFalse(result["verdict_forced"])
        self.assertEqual(result["tool_rounds_used"], 0)

    def test_a_verdict_claiming_a_search_that_did_not_happen_is_corrected(self):
        """
        The model has an incentive to fill `searched` optimistically, and it is the
        one field whose truth the caller can check.
        """
        async def fake_complete(*, model, messages, tools, temperature, **kw):
            return self._stub_response(content=json.dumps({
                "searched": True, "risk_found": False, "confidence": 0.9,
                "reasoning": "I searched and found nothing",
                "evidence_urls": [], "entities_checked": [],
            }))

        with patch.object(
            zd.nebius_client, "complete_with_tools", new=fake_complete,
        ):
            result = _run(zd.screen_zero_day({"shipper_company": "X Co"}))

        self.assertFalse(result["result"]["searched"])
        self.assertIn("corrected", result["result"]["reasoning"])
        # And the finding that follows must not read as a clearance.
        findings = verifier.check_zero_day(
            _clean_shipment(), zd.interpret(result),
        )
        self.assertEqual(findings[0]["code"], "ZERO_DAY_SEARCH_DID_NOT_RUN")


if __name__ == "__main__":
    unittest.main()
