"""
Module 3: the B2B integration contract.

Two of these tests exist because of mistakes made while writing the module, and
they are the ones worth keeping.

test_no_terminal_state_is_unmapped and test_case_state_enum_matches_orchestrator
------------------------------------------------------------------------------
The first version of b2b.py took the state names from schemas.CaseState, which
declared INTAKE, PENDING_ANALYSIS and RELEASED -- none of which the orchestrator
ever sets -- and omitted INGESTED, the state every new case starts in. A live
case therefore read as complete and was published to the integrator as ERROR:
the shipment was fine, and we told the customer we had failed.

Nothing caught it because nothing imported schemas.py. These two tests are the
thing that catches it, and they will catch the next state added to the
orchestrator without a published mapping.

test_idempotent_replay_does_not_spend_tokens
--------------------------------------------
Module 4 retries a failed model call, and an ERP whose HTTP request timed out
retries the whole POST. Without a dedupe key that is two audits, two token bills
and two possibly different verdicts for one shipment. Asserting the audit_id
matches is not enough -- the token count has to be unchanged too, which is what
proves no second pipeline run happened.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("STORE_BACKEND", "memory")

from vf_logistics import b2b, governance, orchestrator  # noqa: E402
from vf_logistics import store as store_mod  # noqa: E402
from vf_logistics import verifier  # noqa: E402
from vf_logistics.agents._common import envelope, parse_model_json  # noqa: E402
from vf_logistics.app import app  # noqa: E402
from vf_logistics.openapi import build_spec  # noqa: E402
from vf_logistics.schemas import CaseState, ComplianceAuditResponse  # noqa: E402


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _envelope_for(agent: str, text: str, legacy_key: str) -> dict:
    parsed, error = parse_model_json(text)
    return envelope(
        agent=agent, model="nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
        result=parsed, error=error, raw=text, latency_ms=10,
        legacy_key=legacy_key, input_tokens=100, output_tokens=50,
        prompt=f"SYSTEM PROMPT v1 for {agent}",
    )


VALID_FRAUD = (
    '{"risk_score": 12, "risk_level": "LOW", "flags": [], '
    '"recommendations": [], "confidence": 0.9}'
)
VALID_COMPLIANCE = (
    '{"compliance_status": "CLEARED", "compliance_score": 95, "risk_factors": [], '
    '"sanctions_hits": null, "regulatory_issues": [], "required_actions": [], '
    '"confidence": 0.9}'
)

# Complete enough to reach auto-clear: shipper_tx_count included because its
# absence raises SHIPPER_HISTORY_UNVERIFIED with a floor of 45, and declared
# value under the boundary's 25,000 ceiling.
CLEARABLE_REQUEST = {
    "shipment_id": "B2B-CLEAN-1",
    "origin": "Vietnam",
    "destination": "Japan",
    "shipper_company": "Mekong Garment Export",
    "shipper_name": "Mekong Garment Export",
    "shipper_tax_id": "0312998877",
    "shipper_country": "Vietnam",
    "shipper_tx_count": 40,
    "receiver_company": "Nippon Retail KK",
    "receiver_name": "Nippon Retail KK",
    "receiver_country": "Japan",
    "consignee_name": "Nippon Retail KK",
    "hs_code": "6109",
    "cargo_description": "Cotton t-shirts, 500 cartons",
    "declared_value": 18000,
    "freight_cost": 1500,
    "shipping_cost": 1500,
    "weight_kg": 2000,
    "currency": "USD",
    "route_details": "Ho Chi Minh to Tokyo direct",
    "transit_points": "none",
}


class ContractDriftTests(unittest.TestCase):
    """Guards against the published contract diverging from the code."""

    def test_no_terminal_state_is_unmapped(self):
        self.assertEqual(
            b2b.unmapped_terminal_states(), set(),
            "a terminal state with no published outcome reaches integrators as "
            "ERROR, which says we failed on a shipment that was actually decided",
        )

    def test_case_state_enum_matches_orchestrator(self):
        real = set(orchestrator.ACTIONABLE) | set(orchestrator.TERMINAL)
        declared = {s.value for s in CaseState}
        self.assertEqual(
            declared - real, set(), "CaseState declares states that do not exist",
        )
        self.assertEqual(
            real - declared, set(), "CaseState is missing real states",
        )

    def test_in_flight_states_come_from_the_orchestrator(self):
        """Not restated locally, which is how the drift happened."""
        for state in orchestrator.ACTIONABLE:
            self.assertFalse(
                b2b.is_complete({"state": state}), f"{state} is still in flight",
            )
        for state in orchestrator.TERMINAL:
            self.assertTrue(b2b.is_complete({"state": state}), state)

    def test_unknown_state_is_error_not_leaked(self):
        """
        An unmapped state must not be passed through into a customer's switch
        statement. ERROR is a poor answer; a string they have never seen is worse.
        """
        self.assertEqual(
            b2b.outcome_for({"state": "SOME_FUTURE_STATE"}).value, "ERROR",
        )


class OpenApiSpecTests(unittest.TestCase):
    def test_spec_has_no_dangling_refs(self):
        spec = build_spec("https://example.test")
        refs = set(re.findall(
            r'"#/components/schemas/([A-Za-z0-9_]+)"', json.dumps(spec),
        ))
        defined = set(spec["components"]["schemas"])
        self.assertEqual(
            refs - defined, set(), "a $ref points at an undefined schema",
        )

    def test_only_shipment_id_is_required(self):
        """
        The request is loose on purpose. A shipment with no cargo description is
        what the system exists to flag -- verifier raises
        CARGO_DESCRIPTION_MISSING with a floor of 60 -- so rejecting it at the
        door would turn a detection into a silence and the integrator would
        "fix" their feed by inventing a value.
        """
        spec = build_spec()
        required = spec["components"]["schemas"]["ComplianceAuditRequest"]["required"]
        self.assertEqual(required, ["shipment_id"])

    def test_response_requires_the_decision_bearing_fields(self):
        spec = build_spec()
        required = set(
            spec["components"]["schemas"]["ComplianceAuditResponse"]["required"]
        )
        for field in ("outcome", "effective_risk", "risk_floor", "lineage", "usage"):
            self.assertIn(field, required)

    def test_spec_is_served_unauthenticated(self):
        """An integrator needs it to generate a client before they have creds,
        and it contains no customer data."""
        app.config["TESTING"] = True
        response = app.test_client().get("/api/v1/openapi.json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["openapi"], "3.1.0")


class AuditEndpointTests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        store_mod._store = None
        orchestrator._invalidate_shipper_feedback()
        # Without an ACTIVE boundary the governance gate is fail-closed and
        # nothing can clear, so a CLEARED assertion would fail for the wrong
        # reason.
        _run(governance.publish_boundary(
            governance.proposed_boundary("b2b contract test"),
            "test-harness", "enable auto-release",
        ))

    def _patches(self, fraud=VALID_FRAUD, compliance=VALID_COMPLIANCE):
        """Every seam that would otherwise reach the network, in one list."""
        return [
            patch.object(orchestrator, "analyze_shipment", new=AsyncMock(
                return_value=_envelope_for("fraud_detection", fraud, "analysis"))),
            patch.object(orchestrator, "screen_shipment", new=AsyncMock(
                return_value=_envelope_for(
                    "compliance", compliance, "screening_result"))),
            patch.object(orchestrator.tavily_client, "search",
                         new=AsyncMock(return_value=[])),
            patch.object(orchestrator, "conduct_debate",
                         new=AsyncMock(return_value={"result": {"verdict": {}}})),
            patch.object(orchestrator, "investigate_case", new=AsyncMock(
                return_value=_envelope_for(
                    "investigation", '{"summary": "x"}', "investigation_result"))),
        ]

    def _post(self, payload, query="", **kw):
        with contextlib.ExitStack() as stack:
            for p in self._patches(**kw):
                stack.enter_context(p)
            return self.client.post(
                f"/api/v1/compliance/audit{query}", json=payload,
            )

    def test_clean_shipment_clears_and_validates_against_the_schema(self):
        response = self._post(CLEARABLE_REQUEST)
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        # The published response must satisfy its own published schema.
        ComplianceAuditResponse.model_validate(body)
        self.assertEqual(body["outcome"], "CLEARED")
        self.assertFalse(body["requires_human_review"])
        self.assertIsNone(body["review_reason"])

    def test_sparse_request_is_accepted_and_absences_become_findings(self):
        response = self._post({"shipment_id": "B2B-SPARSE-1"})
        self.assertEqual(
            response.status_code, 200,
            "a sparse feed must be audited, not rejected at the door",
        )
        body = response.get_json()
        codes = {f["code"] for f in body["findings"]}
        self.assertIn("CARGO_DESCRIPTION_MISSING", codes)
        self.assertIn("HS_CODE_MISSING", codes)
        self.assertNotEqual(body["outcome"], "CLEARED")

    def test_bad_types_are_rejected_with_the_field_name(self):
        """
        Validation at the edge earns its place here: a negative declared value is
        an integrator data error, and naming the field beats letting it become a
        confusing risk score.
        """
        response = self.client.post("/api/v1/compliance/audit", json={
            "shipment_id": "X", "declared_value": -5, "currency": "usd",
        })
        self.assertEqual(response.status_code, 422)
        fields = {d["field"] for d in response.get_json()["details"]}
        self.assertIn("declared_value", fields)
        self.assertIn("currency", fields)

    def test_missing_shipment_id_is_rejected(self):
        response = self.client.post(
            "/api/v1/compliance/audit", json={"cargo_description": "x"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn(
            "shipment_id", {d["field"] for d in response.get_json()["details"]},
        )

    def test_idempotent_replay_does_not_spend_tokens(self):
        payload = {**CLEARABLE_REQUEST, "client_reference": "ERP-IDEMPOTENT-1"}
        first = self._post(payload).get_json()
        second = self._post(payload).get_json()

        self.assertFalse(first["idempotent_replay"])
        self.assertTrue(second["idempotent_replay"])
        self.assertEqual(first["audit_id"], second["audit_id"])
        # The assertion that actually proves no second run happened.
        self.assertEqual(
            second["usage"]["input_tokens"], first["usage"]["input_tokens"],
        )
        self.assertEqual(
            second["usage"]["agent_calls"], first["usage"]["agent_calls"],
        )

    def test_client_reference_never_reaches_the_shipment(self):
        """Transport concerns have no business in a risk assessment, and keeping
        them out also keeps them out of the text the model sees."""
        shipment = b2b.shipment_from_request({
            "shipment_id": "X", "client_reference": "ERP-1",
            "webhook_url": "https://example.test/hook", "hs_code": "6109",
        })
        self.assertNotIn("client_reference", shipment)
        self.assertNotIn("webhook_url", shipment)
        self.assertEqual(shipment["hs_code"], "6109")

    def test_none_valued_fields_are_dropped_not_passed_through(self):
        """verifier._is_missing() already distinguishes absent from
        present-but-empty; handing it an explicit None adds noise."""
        shipment = b2b.shipment_from_request(
            {"shipment_id": "X", "hs_code": None, "cargo_description": None},
        )
        self.assertNotIn("hs_code", shipment)
        self.assertNotIn("cargo_description", shipment)

    def test_schema_failure_surfaces_as_human_review_not_cleared(self):
        response = self._post(
            CLEARABLE_REQUEST, compliance='{"compliance_status": "NOPE"}',
        )
        body = response.get_json()
        self.assertNotEqual(body["outcome"], "CLEARED")
        self.assertTrue(body["requires_human_review"])
        self.assertIn("compliance", body["review_reason"])
        self.assertIn(
            "not a risk finding", body["review_reason"],
            "an integrator must not read a failed check as a clean result",
        )

    def test_lineage_carries_prompt_hash_and_model_per_agent(self):
        body = self._post(CLEARABLE_REQUEST).get_json()
        hashes = body["lineage"]["prompt_hashes"]
        self.assertIn("fraud_detection", hashes)
        self.assertIn("compliance", hashes)
        # SHA-256 hex, and of the full prompt rather than the truncated copy.
        for value in hashes.values():
            self.assertEqual(len(value), 64)
        self.assertIn("fraud_detection", body["lineage"]["model_versions"])

    def test_usage_is_reported_for_billing(self):
        body = self._post(CLEARABLE_REQUEST).get_json()
        self.assertGreater(body["usage"]["agent_calls"], 0)
        self.assertGreater(body["usage"]["input_tokens"], 0)
        self.assertGreater(body["usage"]["estimated_cost_usd"], 0)

    def test_async_submission_returns_202_with_a_poll_url(self):
        response = self._post({"shipment_id": "B2B-ASYNC-1"}, query="?async=true")
        self.assertEqual(response.status_code, 202)
        body = response.get_json()
        self.assertEqual(body["status"], "accepted")
        self.assertTrue(body["poll_url"].endswith(body["audit_id"]))

    def test_fetch_one_audit_and_unknown_is_404(self):
        created = self._post(CLEARABLE_REQUEST).get_json()
        found = self.client.get(f"/api/v1/compliance/audit/{created['audit_id']}")
        self.assertEqual(found.status_code, 200)
        self.assertEqual(found.get_json()["audit_id"], created["audit_id"])
        self.assertEqual(
            self.client.get("/api/v1/compliance/audit/AUD-nope").status_code, 404,
        )

    def test_reports_filters_and_rejects_a_bad_min_risk(self):
        self._post(CLEARABLE_REQUEST)
        listed = self.client.get("/api/v1/compliance/reports?limit=10")
        self.assertEqual(listed.status_code, 200)
        self.assertGreaterEqual(len(listed.get_json()["audits"]), 1)

        cleared = self.client.get("/api/v1/compliance/reports?outcome=CLEARED")
        self.assertTrue(
            all(a["outcome"] == "CLEARED" for a in cleared.get_json()["audits"]),
        )

        high = self.client.get("/api/v1/compliance/reports?min_risk=99")
        self.assertTrue(
            all(a["effective_risk"] >= 99 for a in high.get_json()["audits"]),
        )

        bad = self.client.get("/api/v1/compliance/reports?min_risk=abc")
        self.assertEqual(bad.status_code, 400)

    def test_reports_only_lists_completed_audits(self):
        """An in-flight case has no verdict, and publishing one would invite an
        integrator to act on a decision that has not been made."""
        self._post({"shipment_id": "B2B-ASYNC-2"}, query="?async=true")
        for audit in self.client.get(
            "/api/v1/compliance/reports?limit=50"
        ).get_json()["audits"]:
            self.assertNotIn(audit["outcome"], ("",))


    def test_a_concurrent_advance_does_not_fail_the_post(self):
        """
        POST must survive another writer advancing the same case.

        This handler is not the only thing that drives a case. In poll mode the
        background worker advances it; in ondemand mode GET
        /api/v1/orchestrator/state drains one case per request, so merely having
        the dashboard open makes a second advancer. When one lands between this
        handler's read and its write the store raises OptimisticLockError -- the
        lock working correctly, refusing a lost update.

        The bug this covers is what the handler did with that: it let the error
        escape as a 500, so an integrator's POST failed whenever someone had the
        dashboard open, for a case that was in fact being advanced perfectly
        well by the other writer. Reloading and continuing is the documented
        response ("Reload and retry") and it is what the handler now does.

        Raised once rather than always: the retry has to make progress, not just
        swallow the error, so the second call is allowed through and the
        response must still be a complete audit.
        """
        real_advance = orchestrator.advance
        calls = {"n": 0}

        async def flaky_advance(case):
            calls["n"] += 1
            if calls["n"] == 1:
                raise store_mod.OptimisticLockError(case["case_id"], 2, 3)
            return await real_advance(case)

        with patch.object(orchestrator, "advance", new=flaky_advance):
            response = self._post(dict(CLEARABLE_REQUEST, shipment_id="B2B-RACE-1"))

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        body = response.get_json()
        ComplianceAuditResponse.model_validate(body)
        self.assertGreaterEqual(calls["n"], 2, "the handler gave up instead of reloading")
        self.assertNotEqual(
            body["outcome"], "ERROR",
            "the reload produced no verdict, so the retry did not make progress",
        )


class EvidenceUrlContractTests(unittest.TestCase):
    """
    evidence_urls must distinguish "no search was recorded" from "a search ran
    and found nothing".

    These are opposite facts. Collapsing them lets a consumer render a
    counterparty nobody screened as a counterparty with no adverse media, which
    is the failure the searched/risk_found split in check_zero_day exists to
    prevent. The conflation is easy to reintroduce at this boundary with a
    `measured.get("evidence_urls") or []`, so it is asserted here rather than
    left to review.
    """

    @staticmethod
    def _case(findings):
        return {"case_id": "EV-1", "validation": {"findings": findings}}

    def test_absent_key_becomes_null_not_empty_list(self):
        findings = b2b._findings(self._case([{
            "code": "ZERO_DAY_SEARCH_DID_NOT_RUN",
            "severity": "MEDIUM",
            "detail": "no search ran",
            "floor": 40,
            "measured": {"zero_day_status": "not_searched"},
        }]))
        self.assertIsNone(findings[0].evidence_urls)

    def test_empty_list_survives_as_empty_list(self):
        findings = b2b._findings(self._case([{
            "code": "ZERO_DAY_ADVERSE_MEDIA",
            "severity": "HIGH",
            "detail": "searched, nothing found",
            "floor": 70,
            "measured": {"evidence_urls": []},
        }]))
        self.assertEqual(findings[0].evidence_urls, [])

    def test_citations_are_published(self):
        findings = b2b._findings(self._case([{
            "code": "ZERO_DAY_ADVERSE_MEDIA",
            "severity": "HIGH",
            "detail": "adverse coverage",
            "floor": 70,
            "measured": {
                "evidence_urls": ["https://example.org/a", "https://example.org/b"],
            },
        }]))
        self.assertEqual(
            findings[0].evidence_urls,
            ["https://example.org/a", "https://example.org/b"],
        )

    def test_verifier_output_round_trips_through_the_contract(self):
        """
        Wired against the real check, not a hand-built dict, so a change to what
        check_zero_day records in `measured` fails here rather than silently
        emptying the citation block in the console.
        """
        risk_found = verifier.check_zero_day({}, {
            "verdict": "risk_found",
            "searched": True,
            "confidence": 0.9,
            "reasoning": "procurement network reporting",
            "evidence_urls": ["https://example.org/report"],
        })
        not_searched = verifier.check_zero_day({}, {
            "verdict": "no_risk_found",
            "searched": False,
            "confidence": 0.0,
            "reasoning": "",
        })

        published = b2b._findings(self._case(risk_found + not_searched))
        by_code = {f.code: f for f in published}

        self.assertEqual(
            by_code["ZERO_DAY_ADVERSE_MEDIA"].evidence_urls,
            ["https://example.org/report"],
        )
        self.assertIsNone(
            by_code["ZERO_DAY_SEARCH_DID_NOT_RUN"].evidence_urls,
        )

    def test_payload_separation_holds(self):
        """
        A citation is a public URL, which is why it belongs on the contract at
        all. Nothing commercial may ride along with it.
        """
        findings = b2b._findings(self._case([{
            "code": "ZERO_DAY_ADVERSE_MEDIA",
            "severity": "HIGH",
            "detail": "adverse coverage",
            "floor": 70,
            "measured": {
                "evidence_urls": ["https://example.org/a"],
                "raw_article_text": "SECRET CARGO MANIFEST",
                "cargo_description": "controlled semiconductors",
            },
        }]))
        blob = findings[0].model_dump_json()
        self.assertNotIn("SECRET CARGO MANIFEST", blob)
        self.assertNotIn("controlled semiconductors", blob)


if __name__ == "__main__":
    unittest.main()
