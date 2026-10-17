"""
The origin-circumvention watch and the evidence check (Plan 1, step 1).

What these tests pin, in the order it matters:

1. A shipment on a watched lane gets ORIGIN_INPUTS_UNVERIFIED and can no longer be
   cleared by the rules -- including when its shipper is on the whitelist. Without
   that, the one population most likely to be waved through (known shippers) is the
   one the authorities' findings do not exempt.
2. Good papers do not lower anything. The check reports `provided` and the floor
   stays where it was: the extractor is a model, and a model reading a forged
   certificate must never be able to release a shipment.
3. Contradicting papers raise the floor and nothing else can lower it.
4. A lane nobody has found fraudulent is left alone.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_console_session import TEST_KEY, TEST_SECRET, mint  # noqa: E402
from vf_logistics import store as store_mod  # noqa: E402
from vf_logistics.dossier import EVIDENCE_CATALOGUE, guidance_for  # noqa: E402
from vf_logistics.verifier import (
    CIRCUMVENTION_WATCH,
    ORIGIN_EVIDENCE_DOCS,
    check_origin_evidence,
    check_origin_inputs,
    validate,
    watched_lane,
)

ROOT = Path(__file__).resolve().parent.parent

_ROUTE_ENV = {
    "VF_API_KEY": TEST_KEY, "VF_SESSION_SECRET": TEST_SECRET, "IAP_ENABLED": "false",
    "MULTI_TENANT": "false", "ANONYMOUS_ROLE": "viewer", "STORE_BACKEND": "memory",
}


def plywood(**over) -> dict:
    base = {
        "shipment_id": "T-PLY", "shipper_name": "Saigon Plywood Co.", "shipper_tax_id": "VN0300000001",
        "shipper_tx_count": 40, "shipper_country": "Vietnam", "receiver_country": "United States",
        "origin": "Hai Phong Port, Vietnam", "destination": "Long Beach, United States",
        "hs_code": "4412.33", "cargo_description": "Hardwood plywood, 18 mm",
        "declared_value": 28000.0, "weight_kg": 22000.0, "currency": "USD",
        "shipping_cost": 3000.0, "avg_route_cost": 3000.0, "transport_mode": "sea",
    }
    base.update(over)
    return base


def codes(result) -> list[str]:
    return [f["code"] for f in result["findings"]]


class TestTheWatch:
    def test_every_row_is_a_public_decision_with_a_link(self):
        ids = {rule.rule_id for rule in CIRCUMVENTION_WATCH}
        public = {c["source_ref"] for c in json.loads(
            (ROOT / "data" / "public_cases.json").read_text(encoding="utf-8"))["cases"]
            if c.get("source_ref")}
        assert ids <= public, f"watch rows with no public case behind them: {ids - public}"
        for rule in CIRCUMVENTION_WATCH:
            assert rule.source_url.startswith("https://")

    def test_a_declared_lane_on_the_list_is_flagged(self):
        findings = check_origin_inputs(plywood())
        assert [f["code"] for f in findings] == ["ORIGIN_INPUTS_UNVERIFIED"]
        f = findings[0]
        assert (f["severity"], f["floor"]) == ("MEDIUM", 45)
        assert f["blocks_auto_clear"] is True
        assert f["measured"]["documents_needed"] == list(ORIGIN_EVIDENCE_DOCS)
        assert "china" in f["detail"].lower()

    @pytest.mark.parametrize("over", [
        {"destination": "Rotterdam, Netherlands", "receiver_country": "Netherlands"},  # not a US duty
        {"origin": "Qingdao, China", "shipper_country": "China"},                       # declared as China
        {"hs_code": "9403.60"},                                                         # furniture, not plywood
        {"hs_code": ""},
    ])
    def test_a_lane_nobody_found_fraudulent_is_left_alone(self, over):
        assert watched_lane(plywood(**over)) is None
        assert check_origin_inputs(plywood(**over)) == []

    def test_country_spellings_do_not_hide_a_lane(self):
        spoofed = plywood(destination="Houston, USA", shipper_country="Viet Nam", origin="Hai Phong")
        assert watched_lane(spoofed) is not None
        assert watched_lane(plywood(destination="Houston, U.S.A.")) is not None

    def test_the_eu_rows_match_any_member_state(self):
        foil = plywood(
            origin="Yangon, Myanmar", shipper_country="Myanmar", hs_code="7607.11",
            destination="Hamburg, Germany", receiver_country="Germany",
        )
        assert watched_lane(foil).rule_id == "EPPO-2024-ALFOIL-DE"
        assert watched_lane({**foil, "destination": "Valencia, Spain"}).rule_id == "EPPO-2024-ALFOIL-DE"

    def test_the_watch_does_not_touch_the_synthetic_corpus(self):
        """Measured when this was added: 0 of 1,000, so it cannot move that benchmark's
        false-positive rate. If the corpus or the watch changes and this starts failing,
        re-measure rather than loosening it."""
        cases = json.loads((ROOT / "data" / "synthetic_test_cases.json").read_text(encoding="utf-8"))["cases"]
        assert sum(1 for c in cases if watched_lane(c["shipment"])) == 0


class TestTheRulesCannotClearIt:
    def test_a_watched_lane_cannot_be_auto_cleared_by_a_whitelisted_shipper(self):
        """The case that matters. Vinamilk is on the whitelist; its cargo on a watched lane
        must still wait for a person, because the authorities' findings are about the lane."""
        vip = plywood(shipper_company="Vinamilk Joint Stock Company", shipper_tax_id="0100107518")
        result = validate(vip)
        assert "ORIGIN_INPUTS_UNVERIFIED" in codes(result)
        assert result["skip_ai"] is False
        assert result["risk_floor"] >= 45
        assert result["auto_clear_by_rules"] is True  # the whitelist still fires; it is simply not honoured
        # And the same shipper on a lane nobody flagged is still cleared at zero cost.
        ordinary = validate(plywood(
            shipper_company="Vinamilk Joint Stock Company", shipper_tax_id="0100107518",
            hs_code="0401", cargo_description="Milk powder", destination="Singapore",
            receiver_country="Singapore",
        ))
        assert ordinary["skip_ai"] is True
        assert ordinary["risk_floor"] == 0

    def test_an_ordinary_shipper_gets_the_floor_and_the_finding(self):
        result = validate(plywood())
        assert "ORIGIN_INPUTS_UNVERIFIED" in codes(result)
        assert result["risk_floor"] >= 45
        assert "origin_inputs" in result["checks_run"]


def docs(**sets) -> list[dict]:
    return [{"doc_type": t, "extracted": e} for t, e in sets.items() if e is not None]


GOOD = {
    "certificate_of_origin": {"producer_name": "Saigon Plywood Co., Ltd.", "origin_country": "Vietnam"},
    "producer_declaration": {"producer_name": "SAIGON PLYWOOD COMPANY LIMITED", "input_origins": ["Vietnam", "Indonesia"]},
    "input_purchase_invoices": {
        "supplier_name": "Mekong Veneer", "supplier_country": "Vietnam",
        "goods_origin_country": "Vietnam", "producer_name": "Saigon Plywood Co",
    },
}


class TestTheEvidence:
    def test_nothing_received_is_missing_and_says_what(self):
        out = check_origin_evidence(plywood(), [])
        assert out["status"] == "missing"
        assert out["missing"] == list(ORIGIN_EVIDENCE_DOCS)
        assert out["findings"] == []

    def test_part_of_the_set_is_still_missing(self):
        out = check_origin_evidence(plywood(), docs(certificate_of_origin=GOOD["certificate_of_origin"]))
        assert out["status"] == "missing"
        assert out["missing"] == ["producer_declaration", "input_purchase_invoices"]

    def test_good_papers_are_reported_and_raise_nothing(self):
        out = check_origin_evidence(plywood(), docs(**GOOD))
        assert out["status"] == "provided"
        assert out["findings"] == []
        # The point of the whole design: a complete, consistent set changes no score.
        before = validate(plywood())["risk_floor"]
        assert before >= 45
        assert out["missing"] == []

    def test_company_name_suffixes_and_case_do_not_make_a_mismatch(self):
        out = check_origin_evidence(plywood(), docs(**GOOD))
        assert "ORIGIN_PRODUCER_MISMATCH" not in [f["code"] for f in out["findings"]]

    def test_chinese_veneer_on_an_invoice_contradicts_the_declaration(self):
        bad = {**GOOD, "input_purchase_invoices": {
            "supplier_name": "Guangxi Veneer Ltd", "supplier_country": "China",
            "goods_origin_country": "China", "producer_name": "Saigon Plywood Co",
        }}
        out = check_origin_evidence(plywood(), docs(**bad))
        assert out["status"] == "contradicted"
        finding = next(f for f in out["findings"] if f["code"] == "ORIGIN_EVIDENCE_CONTRADICTION")
        assert (finding["severity"], finding["floor"]) == ("HIGH", 80)
        assert "Guangxi" in finding["detail"]

    def test_a_declaration_that_lists_the_watched_origin_contradicts(self):
        bad = {**GOOD, "producer_declaration": {
            "producer_name": "Saigon Plywood Co", "input_origins": ["China"],
        }}
        assert check_origin_evidence(plywood(), docs(**bad))["status"] == "contradicted"

    def test_a_certificate_for_another_country_contradicts(self):
        bad = {**GOOD, "certificate_of_origin": {
            "producer_name": "Saigon Plywood Co", "origin_country": "China",
        }}
        out = check_origin_evidence(plywood(), docs(**bad))
        assert out["status"] == "contradicted"
        assert any(c["kind"] == "certificate_country" for c in out["contradictions"])

    def test_a_different_producer_on_the_certificate_is_a_mismatch(self):
        bad = {**GOOD, "certificate_of_origin": {
            "producer_name": "Hanoi Timber Works", "origin_country": "Vietnam",
        }}
        out = check_origin_evidence(plywood(), docs(**bad))
        finding = next(f for f in out["findings"] if f["code"] == "ORIGIN_PRODUCER_MISMATCH")
        assert (finding["severity"], finding["floor"]) == ("HIGH", 75)

    def test_malformed_extractions_are_ignored_not_trusted(self):
        out = check_origin_evidence(plywood(), [
            {"doc_type": "certificate_of_origin", "extracted": "not a dict"},
            "not a doc",
            {"doc_type": "certificate_of_origin"},
        ])
        assert out["status"] == "missing"

    def test_contradicting_findings_only_ever_raise_the_floor(self):
        """Adding the findings the evidence check returns to the case's own cannot lower it."""
        bad = {**GOOD, "input_purchase_invoices": {"supplier_country": "China", "goods_origin_country": "China"}}
        extra = check_origin_evidence(plywood(), docs(**bad))["findings"]
        from vf_logistics.verifier import _floor_for
        base = validate(plywood())["findings"]
        floor_before = _floor_for(base)[0]
        floor_after = _floor_for(base + extra)[0]
        assert floor_after > floor_before


class TestTheDossierJson:
    """The findings of a case with their guidance, as data (GET .../dossier.json)."""

    def setup_method(self):
        from vf_logistics import app as app_mod

        self.env = patch.dict(os.environ, _ROUTE_ENV)
        self.env.start()
        store_mod._store = None
        self.was = app_mod.limiter.enabled
        app_mod.limiter.enabled = False
        self.app_mod = app_mod
        self.client = app_mod.app.test_client()
        self.store = store_mod.get_store()

    def teardown_method(self):
        self.app_mod.limiter.enabled = self.was
        store_mod._store = None
        self.env.stop()

    def _put_case(self, case_id: str, shipment: dict):
        asyncio.run(self.store.put_case({
            "case_id": case_id, "shipment_id": case_id, "state": "HELD_FOR_REVIEW",
            "created_at": "2026-10-12T01:00:00+00:00", "validation": validate(shipment),
            "shipment": shipment,
        }))

    def test_an_origin_finding_comes_with_the_documents_that_would_answer_it(self):
        self._put_case("CASE-PLY", plywood())
        body = self.client.get("/api/v1/orchestrator/case/CASE-PLY/dossier.json").get_json()
        finding = next(f for f in body["findings"] if f["code"] == "ORIGIN_INPUTS_UNVERIFIED")
        assert [d["doc_type"] for d in finding["documents_needed"]] == list(ORIGIN_EVIDENCE_DOCS)
        assert all(d["label"] and d["purpose"] for d in finding["documents_needed"])
        assert finding["action"].startswith("Ask for the certificate of origin")
        assert body["precedents"]["origin"]["url"].startswith("https://")

    def test_a_finding_that_asks_for_nothing_lists_no_documents(self):
        self._put_case("CASE-NOPLY", plywood(destination="Rotterdam, Netherlands"))
        body = self.client.get("/api/v1/orchestrator/case/CASE-NOPLY/dossier.json").get_json()
        assert all(f["documents_needed"] == [] for f in body["findings"])

    def test_a_case_that_is_not_there_is_not_found(self):
        assert self.client.get("/api/v1/orchestrator/case/NOPE/dossier.json").status_code == 404

    def test_a_signed_in_viewer_may_read_it(self):
        self._put_case("CASE-PLY", plywood())
        viewer = {"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint("someone@x.example", amr="password")}
        response = self.client.get("/api/v1/orchestrator/case/CASE-PLY/dossier.json", headers=viewer)
        assert response.status_code == 200


class TestTheCatalogue:
    def test_every_document_the_watch_asks_for_can_be_read(self):
        for doc in ORIGIN_EVIDENCE_DOCS:
            entry = EVIDENCE_CATALOGUE[doc]
            assert entry["label"] and entry["purpose"] and entry["fields"]

    def test_the_fields_the_check_reads_are_fields_the_extractor_is_told_to_read(self):
        """The rule and the extractor must agree on names, or a correct document reads as empty."""
        read_by_check = {
            "certificate_of_origin": {"producer_name", "origin_country"},
            "producer_declaration": {"producer_name", "input_origins"},
            "input_purchase_invoices": {"producer_name", "goods_origin_country", "supplier_country"},
        }
        for doc, fields in read_by_check.items():
            assert fields <= set(EVIDENCE_CATALOGUE[doc]["fields"]), doc

    @pytest.mark.parametrize("code", [
        "ORIGIN_INPUTS_UNVERIFIED", "ORIGIN_EVIDENCE_CONTRADICTION", "ORIGIN_PRODUCER_MISMATCH",
    ])
    def test_each_new_finding_has_its_own_guidance(self, code):
        refs, precedent, action = guidance_for(code)
        assert precedent == "origin"
        assert action != "Review the finding detail."


# N06: what a model writes where a paper states nothing. The prompt asks for "not
# stated", but replies vary, and none of these is a country, a company or a claim.
NOT_STATED = [
    "not stated", "Not stated.", "NOT STATED", "not  stated", "N/A", "n/a.", "N.A.",
    "na", "-", "--", "—", "?", "unknown", "Unspecified", "not specified",
    "Not available", "not provided", "Not applicable", "not shown", "not mentioned",
    "nil", "null", "none", "", "   ", None, ["not stated"], [],
]


class TestN06WhatCountsAsNothingStated:
    @pytest.mark.parametrize("value", NOT_STATED)
    def test_a_certificate_that_states_no_country_is_missing_not_contradicting(self, value):
        cert = {"producer_name": "Saigon Plywood Co., Ltd.", "origin_country": value}
        out = check_origin_evidence(plywood(), docs(**{**GOOD, "certificate_of_origin": cert}))
        assert out["contradictions"] == []
        assert out["findings"] == []
        assert out["status"] == "missing"
        assert out["missing"] == ["certificate_of_origin"]

    @pytest.mark.parametrize("value", NOT_STATED)
    def test_a_placeholder_producer_is_not_a_producer_to_mismatch_against(self, value):
        no_producer_on_invoice = {k: v for k, v in GOOD["input_purchase_invoices"].items() if k != "producer_name"}
        out = check_origin_evidence(plywood(), docs(
            certificate_of_origin=GOOD["certificate_of_origin"],
            producer_declaration={"producer_name": value, "input_origins": ["Vietnam"]},
            input_purchase_invoices=no_producer_on_invoice,
        ))
        assert "ORIGIN_PRODUCER_MISMATCH" not in [f["code"] for f in out["findings"]]

    @pytest.mark.parametrize("value", NOT_STATED)
    def test_a_placeholder_goods_origin_does_not_hide_a_real_supplier_country(self, value):
        # supplier_country says China; goods_origin_country says "not stated". The
        # truthy placeholder used to win the `or`, so this read as "provided".
        invoice = {
            "supplier_name": "Guangxi Veneer Ltd", "supplier_country": "China",
            "goods_origin_country": value, "producer_name": "Saigon Plywood Co",
        }
        out = check_origin_evidence(plywood(), docs(**{**GOOD, "input_purchase_invoices": invoice}))
        assert out["status"] == "contradicted"
        assert any(c["kind"] == "input_origin" for c in out["contradictions"])

    @pytest.mark.parametrize("value", [v for v in NOT_STATED if v not in (None, [], "", "   ")])
    def test_a_placeholder_supplier_name_never_reaches_the_reviewer_text(self, value):
        invoice = {
            "supplier_name": value, "goods_origin_country": "China",
            "producer_name": "Saigon Plywood Co",
        }
        out = check_origin_evidence(plywood(), docs(**{**GOOD, "input_purchase_invoices": invoice}))
        assert out["status"] == "contradicted"
        text = " ".join(c["detail"] for c in out["contradictions"]).lower()
        assert "not stated" not in text and "n/a" not in text and " from " not in text

    def test_goods_origin_wins_over_supplier_country_when_both_are_stated(self):
        # Pin the precedence: a Vietnamese goods origin from a China-based trader is
        # not a contradiction (the goods are what the watch is about).
        invoice = {
            "supplier_name": "HK Trader", "supplier_country": "China",
            "goods_origin_country": "Vietnam", "producer_name": "Saigon Plywood Co",
        }
        out = check_origin_evidence(plywood(), docs(**{**GOOD, "input_purchase_invoices": invoice}))
        assert out["status"] == "provided" and out["contradictions"] == []

    def test_real_values_are_not_swallowed_by_the_filter(self):
        from vf_logistics.verifier import is_placeholder_text
        for real in ("Vietnam", "China", "Saigon Plywood Co., Ltd.", "Nilsen Timber", "Nathan Ltd", "Nagoya"):
            assert not is_placeholder_text(real), real

    def test_every_list_of_placeholders_in_the_code_agrees(self):
        # They used to be three hand-copied sets that had drifted apart. Anything
        # any of them treats as nothing, the evidence check must too.
        from vf_logistics.agents import compliance_agent, zero_day_agent
        from vf_logistics.verifier import MISSING_MARKERS, is_placeholder_text
        for marker in MISSING_MARKERS:
            assert is_placeholder_text(marker), marker
        for marker in ("", "n/a", "na", "none", "not stated", "not provided", "unknown", "-"):
            assert compliance_agent._searchable_name(marker) == "", marker
        for marker in ("n/a", "not stated", "none", "Not stated.", "NA"):
            assert zero_day_agent.entities_to_check({"shipper_name": marker}) == [], marker
        assert compliance_agent._searchable_name("Saigon Plywood Co.") == "Saigon Plywood Co."

    @pytest.mark.parametrize("origins", [[], "not stated", ["not stated"], None, ["N/A", "-"]])
    def test_a_declaration_that_names_the_producer_but_no_inputs_is_not_proof(self, origins):
        # N06-E: the declaration is there to say where the inputs came from. One that
        # names the producer and nothing else does not document the inputs' origin.
        declaration = {"producer_name": "Saigon Plywood Co., Ltd.", "input_origins": origins}
        out = check_origin_evidence(plywood(), docs(**{**GOOD, "producer_declaration": declaration}))
        assert out["status"] == "missing" and out["missing"] == ["producer_declaration"]

    @pytest.mark.parametrize("origins", [["Vietnam"], ["Vietnam", "Indonesia"], "Vietnam", ["not stated", "Vietnam"]])
    def test_a_declaration_with_a_stated_input_origin_is_proof(self, origins):
        declaration = {"producer_name": "Saigon Plywood Co., Ltd.", "input_origins": origins}
        out = check_origin_evidence(plywood(), docs(**{**GOOD, "producer_declaration": declaration}))
        assert out["status"] == "provided"


class TestN06ACountryFieldsNameOneCountry:
    """origin_country, goods_origin_country and supplier_country must name ONE country.
    A list of two different countries used to count as stated (one meaningful entry was
    enough), so a certificate for ["Vietnam", "China"] read as "provided"."""

    @pytest.mark.parametrize("value", [
        ["Vietnam", "China"], ["China", "Vietnam"], ["Vietnam", "Indonesia"],
        ["Vietnam", "Viet Nam", "China"], ["not stated", "Vietnam", "China"],
    ])
    def test_a_certificate_for_two_countries_is_not_provided(self, value):
        cert = {"producer_name": "Saigon Plywood Co., Ltd.", "origin_country": value}
        out = check_origin_evidence(plywood(), docs(**{**GOOD, "certificate_of_origin": cert}))
        assert out["status"] == "missing"
        assert out["missing"] == ["certificate_of_origin"]
        assert "certificate_of_origin" not in out["present"]
        assert out["findings"] == [] and out["contradictions"] == []

    @pytest.mark.parametrize("value", [
        ["Vietnam"], "Vietnam", ["Viet Nam"], ["Vietnam", "Viet Nam"],
        ["not stated", "Vietnam"], ["Vietnam", "N/A"],
    ])
    def test_one_country_is_still_provided_however_it_is_wrapped_or_spelled(self, value):
        cert = {"producer_name": "Saigon Plywood Co., Ltd.", "origin_country": value}
        out = check_origin_evidence(plywood(), docs(**{**GOOD, "certificate_of_origin": cert}))
        assert out["status"] == "provided"
        assert out["missing"] == []

    @pytest.mark.parametrize("origins", [
        ["Vietnam"], ["Vietnam", "Indonesia"], ["Vietnam", "Indonesia", "Malaysia"],
    ])
    def test_the_producers_declaration_may_still_list_several_input_origins(self, origins):
        # input_origins is a list on purpose; it is not one of the one-country fields.
        declaration = {"producer_name": "Saigon Plywood Co., Ltd.", "input_origins": origins}
        out = check_origin_evidence(plywood(), docs(**{**GOOD, "producer_declaration": declaration}))
        assert out["status"] == "provided"

    @pytest.mark.parametrize("field", ["goods_origin_country", "supplier_country"])
    def test_an_invoice_listing_two_countries_is_not_provided(self, field):
        invoice = {**GOOD["input_purchase_invoices"], field: ["Vietnam", "China"]}
        out = check_origin_evidence(plywood(), docs(**{**GOOD, "input_purchase_invoices": invoice}))
        assert out["status"] == "missing"
        assert out["missing"] == ["input_purchase_invoices"]

    @pytest.mark.parametrize("value", [
        ["not stated", "China"], ["China", "PRC"], ["N/A", "People's Republic of China"],
    ])
    def test_a_certificate_for_china_contradicts_a_vietnam_declaration(self, value):
        # One country, however it is wrapped: it must be compared with the declaration (N06).
        cert = {"producer_name": "Saigon Plywood Co., Ltd.", "origin_country": value}
        out = check_origin_evidence(plywood(), docs(**{**GOOD, "certificate_of_origin": cert}))
        assert out["status"] == "contradicted"
        assert "certificate_country" in [c["kind"] for c in out["contradictions"]]

    @pytest.mark.parametrize("goods_origin,supplier_country", [
        (["not stated", "China"], "Vietnam"),
        (["China", "PRC"], "Vietnam"),
        ("not stated", ["China", "PRC"]),
    ])
    def test_an_invoice_for_china_goods_contradicts_however_the_field_is_written(self, goods_origin, supplier_country):
        invoice = {
            **GOOD["input_purchase_invoices"],
            "goods_origin_country": goods_origin,
            "supplier_country": supplier_country,
        }
        out = check_origin_evidence(plywood(), docs(**{**GOOD, "input_purchase_invoices": invoice}))
        assert out["status"] == "contradicted"
        assert "input_origin" in [c["kind"] for c in out["contradictions"]]

    def test_two_spellings_of_the_declared_country_contradict_nothing(self):
        cert = {"producer_name": "Saigon Plywood Co., Ltd.", "origin_country": ["Vietnam", "Viet Nam"]}
        out = check_origin_evidence(plywood(), docs(**{**GOOD, "certificate_of_origin": cert}))
        assert out["status"] == "provided"
        assert out["contradictions"] == []

    def test_an_invoice_with_two_countries_is_still_read_for_contradictions(self):
        # Still read for contradictions: China is a watched input origin on the plywood lane.
        invoice = {
            "supplier_name": "Mekong Veneer",
            "supplier_country": "China",
            "goods_origin_country": ["Vietnam", "Indonesia"],
            "producer_name": "Saigon Plywood Co",
        }
        out = check_origin_evidence(plywood(), docs(**{**GOOD, "input_purchase_invoices": invoice}))
        assert out["status"] == "contradicted"
        assert any(c["kind"] == "input_origin" for c in out["contradictions"])
