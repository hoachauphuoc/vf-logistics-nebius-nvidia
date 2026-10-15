"""
The release path fails closed: a missing or unexpected value withholds release.

WHY THIS FILE EXISTS

Every condition on an automated release is a place where "absent" has to be
decided, and each of these read absence as permission:

  * the orchestrator took a case with no reconciliation as auto_clear_permitted;
  * it read compliance through a denylist of BLOCKED and REVIEW_REQUIRED, so any
    other status -- UNKNOWN, an off-schema value -- could clear;
  * the learning loop discounted risk by 10 after five human releases of any
    shipment bearing the same free-text shipper name, enough to carry a
    borderline 45 under the 40 auto-clear threshold;
  * the governance gate read a missing finding count as zero, a missing or
    unreadable declared value as 0 USD, and a blank destination as one that
    matched no excluded country.

Each test below pairs the closed case with a control that DOES release through
the same fixture, because a fixture in which nothing can ever be released would
pass these tests with the release path deleted.
"""

from __future__ import annotations

import asyncio
import copy
import math
import os
import unittest
from typing import Any, Callable
from unittest.mock import AsyncMock, patch

os.environ.setdefault("STORE_BACKEND", "memory")

from vf_logistics import governance, orchestrator  # noqa: E402
from vf_logistics import store as store_mod  # noqa: E402


def _run(coro):
    """Fresh loop per call; the suite shares a process and closes loops."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# No deterministic findings, under the delegated value ceiling, a benign heading
# on a plain lane: with a low model score and CLEARED compliance it auto-clears.
SHIPMENT = {
    "shipment_id": "S-FAILCLOSED-1",
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

# An entry in shipper_registry's book: tax ID and company name both match, so
# enrich() marks the shipment's identity verified.
VERIFIED_SHIPPER = {
    "shipper_company": "Saigon Textile Export JSC",
    "shipper_name": "Saigon Textile Export JSC",
    "shipper_tax_id": "0301234567",
}

TERMINAL = (
    "AUTO_CLEARED", "HELD_FOR_REVIEW", "PENDING_HUMAN",
    "ESCALATED", "BLOCKED", "RELEASED", "DEAD_LETTER",
)


def _fraud(score: int) -> dict[str, Any]:
    return {
        "result": {"risk_score": score, "risk_level": "LOW"},
        "model": "nano", "latency_ms": 800, "input_tokens": 900, "output_tokens": 200,
        "at": "2026-10-01T12:00:00+00:00", "parse_error": False,
        "prompt": "fraud prompt", "raw": "{}",
    }


def _compliance(status: Any) -> dict[str, Any]:
    """A reply that reached the orchestrator unflagged, whatever its status says.

    Built by hand rather than through envelope(), which would reject an off-schema
    status as a model failure. These tests are about the orchestrator's own reading
    of the status, the line of defence behind schema validation.
    """
    return {
        "result": {"compliance_status": status, "compliance_score": 90},
        "model": "nano", "latency_ms": 700, "input_tokens": 800, "output_tokens": 150,
        "at": "2026-10-01T12:00:01+00:00", "parse_error": False,
        "prompt": "compliance prompt", "raw": "{}",
    }


INVESTIGATION = {
    "result": {"summary": "x", "fraud_pattern": "none", "exposure_estimate": "0 USD"},
    "model": "super", "latency_ms": 3000, "input_tokens": 2000, "output_tokens": 400,
    "at": "2026-10-01T12:00:09+00:00", "parse_error": False,
    "prompt": "investigation prompt", "raw": "{}",
}


def _human_releases(shipment: dict[str, Any], n: int = 5) -> list[dict[str, Any]]:
    return [
        {
            "case_id": f"CASE-HIST-{i}", "shipment_id": f"HIST-{i}",
            "state": "RELEASED_BY_HUMAN",
            "created_at": f"2026-09-30T10:{i:02d}:00.000000+00:00",
            "shipment": dict(shipment), "steps": [], "actions": [],
        }
        for i in range(n)
    ]


def drive(
    shipment: dict[str, Any],
    *,
    fraud: int = 12,
    compliance: Any = "CLEARED",
    history: list[dict[str, Any]] | None = None,
    before_decision: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Ingest `shipment` and advance it until it stops.

    `before_decision` edits the case once it reaches SPECIALISTS_DONE, which is
    how a case that arrives there with a value missing is simulated.
    """
    store_mod._store = None
    orchestrator._invalidate_shipper_feedback()
    # Without an ACTIVE boundary the gate refuses every release, so the controls
    # would fail and the closed cases would pass for the wrong reason.
    _run(governance.publish_boundary(
        governance.proposed_boundary("fail-closed test"),
        "test-harness", "enable auto-release so the controls can clear",
    ))
    store = store_mod.get_store()
    for past in history or []:
        _run(store.put_case(past))
    orchestrator._invalidate_shipper_feedback()

    with patch.object(orchestrator, "analyze_shipment", AsyncMock(return_value=_fraud(fraud))), \
         patch.object(orchestrator, "screen_shipment",
                      AsyncMock(return_value=_compliance(compliance))), \
         patch.object(orchestrator, "conduct_debate",
                      AsyncMock(return_value={"result": {"verdict": {}}})), \
         patch.object(orchestrator, "investigate_case", AsyncMock(return_value=INVESTIGATION)), \
         patch.object(orchestrator.tavily_client, "search", AsyncMock(return_value=[])):
        case = _run(orchestrator.ingest_shipment(copy.deepcopy(shipment)))
        for _ in range(8):
            if case.get("state") in TERMINAL:
                break
            if case.get("state") == "SPECIALISTS_DONE" and before_decision:
                before_decision(case)
                before_decision = None
            case = _run(orchestrator.advance(case)) or case
    return case


def _release_attempted(case: dict[str, Any]) -> bool:
    return any(a.get("action") == "release_shipment" for a in case.get("actions", []))


class TestTheOrchestratorReleasesOnlyOnAnExplicitClearance(unittest.TestCase):

    def test_control_case_auto_clears(self):
        case = drive(SHIPMENT)
        self.assertEqual(case["state"], "AUTO_CLEARED")
        self.assertTrue(_release_attempted(case))

    def test_a_case_with_no_reconciliation_is_not_proposed_for_release(self):
        """
        The governance gate would refuse it too, but the orchestrator must not
        propose a release on a case with no record that the floor agreed: the
        case belongs in the review queue, not in a refused AUTO_CLEARED.
        """
        case = drive(SHIPMENT, before_decision=lambda c: c.pop("reconciliation"))
        self.assertEqual(case["state"], "HELD_FOR_REVIEW")
        self.assertFalse(_release_attempted(case))
        self.assertIn("did not permit an automated release", case["decision"]["rationale"])

    def test_a_reconciliation_without_the_permission_is_not_a_permission(self):
        def strip(c):
            c["reconciliation"].pop("auto_clear_permitted")
        case = drive(SHIPMENT, before_decision=strip)
        self.assertEqual(case["state"], "HELD_FOR_REVIEW")
        self.assertFalse(_release_attempted(case))

    def test_a_compliance_status_that_is_not_cleared_does_not_release(self):
        """
        BLOCKED and REVIEW_REQUIRED are not the only statuses that must stop a
        release. Every one of these reached AUTO_CLEARED through the denylist.
        """
        for status in ("UNKNOWN", "COMPLIANT", "CLEAR", "", None, "PROBABLY_FINE"):
            with self.subTest(status=status):
                case = drive(SHIPMENT, compliance=status)
                self.assertEqual(case["state"], "HELD_FOR_REVIEW")
                self.assertFalse(_release_attempted(case))
                self.assertIn("which is not a clearance", case["decision"]["rationale"])
                assign = next(a for a in case["actions"] if a["action"] == "assign_analyst")
                self.assertEqual(assign["detail"].get("priority"), "HIGH")


class TestTheLearningDiscountNeedsAVerifiedIdentity(unittest.TestCase):
    """
    A model score of 45 holds the case; the -10 discount would release it at 35.
    The discount must rest on what the registry verified, not on the name the
    document typed.
    """

    def test_premise_a_borderline_score_is_held(self):
        case = drive(SHIPMENT, fraud=45)
        self.assertEqual(case["state"], "HELD_FOR_REVIEW")
        self.assertEqual(case["risk_score"], 45)

    def test_control_a_verified_shipper_with_five_releases_is_discounted(self):
        verified = dict(SHIPMENT, **VERIFIED_SHIPPER)
        history = _human_releases(dict(verified, shipper_identity_status="verified"))
        case = drive(verified, fraud=45, history=history)
        self.assertEqual(case["shipment"]["shipper_identity_status"], "verified")
        self.assertEqual(case["reconciliation"]["learning_adjustment"], -10)
        self.assertEqual(case["risk_score"], 35)
        self.assertEqual(case["state"], "AUTO_CLEARED")
        self.assertIn("registry-verified identity", case["reconciliation"]["learning_note"])

    def test_an_unverified_shipper_with_five_releases_is_not_discounted(self):
        history = _human_releases(SHIPMENT)
        case = drive(SHIPMENT, fraud=45, history=history)
        self.assertNotEqual(case["shipment"]["shipper_identity_status"], "verified")
        self.assertNotIn("learning_adjustment", case["reconciliation"])
        self.assertEqual(case["risk_score"], 45)
        self.assertEqual(case["state"], "HELD_FOR_REVIEW")

    def test_typing_a_trusted_shippers_name_does_not_borrow_its_history(self):
        """Its name and company, but a tax ID the book does not hold for it."""
        verified = dict(SHIPMENT, **VERIFIED_SHIPPER)
        history = _human_releases(dict(verified, shipper_identity_status="verified"))
        impostor = dict(verified, shipper_tax_id="0312998877")
        case = drive(impostor, fraud=45, history=history)
        self.assertEqual(case["shipment"]["shipper_identity_status"], "unknown")
        self.assertEqual(case["risk_score"], 45)
        self.assertEqual(case["state"], "HELD_FOR_REVIEW")

    def test_releases_that_only_used_the_name_do_not_count_for_the_verified_shipper(self):
        verified = dict(SHIPMENT, **VERIFIED_SHIPPER)
        history = _human_releases(dict(verified, shipper_tax_id="0312998877"))
        case = drive(verified, fraud=45, history=history)
        self.assertEqual(case["risk_score"], 45)
        self.assertEqual(case["state"], "HELD_FOR_REVIEW")


# The gate itself, against the template boundary a human would publish.
CLEAN_CASE = {
    "case_id": "CASE-GATE",
    "risk_score": 10,
    "compliance_status": "CLEARED",
    "shipment": {"declared_value": 1000, "hs_code": "6205.20", "destination": "Japan"},
    "validation": {"finding_count": 0, "findings": []},
    "reconciliation": {"auto_clear_permitted": True, "score_disputed": False},
    "input_security": {"injection_screening": {"blocked": False}},
}
BOUNDARY = {
    "boundary_id": "BOUNDARY-test", "version": 1, "status": "ACTIVE",
    "permissions": governance.proposed_boundary("gate test"),
}


def _gate(case: dict[str, Any] | None = None, **shipment: Any) -> dict[str, Any]:
    """The gate's verdict on CLEAN_CASE (or `case`) with `shipment` fields changed."""
    case = copy.deepcopy(case or CLEAN_CASE)
    case["shipment"].update(shipment)
    return governance.check("release_shipment", case, BOUNDARY)


class TestTheReleaseGateReadsAbsenceAsRefusal(unittest.TestCase):

    def test_control_the_clean_case_is_released(self):
        self.assertTrue(_gate()["allowed"])

    def test_a_missing_finding_count_is_not_zero_findings(self):
        for validation in ({}, {"findings": []}, {"finding_count": None}):
            with self.subTest(validation=validation):
                verdict = _gate(dict(CLEAN_CASE, validation=validation))
                self.assertFalse(verdict["allowed"])
                self.assertIn("finding count", verdict["reason"])

    def test_an_absent_or_unreadable_declared_value_is_not_zero(self):
        for value in (None, "", "about ten thousand", math.nan, -500):
            with self.subTest(value=value):
                verdict = _gate(declared_value=value)
                self.assertFalse(verdict["allowed"])
                self.assertIn("declared value", verdict["reason"])

    def test_a_stated_zero_value_is_still_a_value(self):
        self.assertTrue(_gate(declared_value=0)["allowed"])

    def test_a_blank_destination_cannot_pass_the_excluded_destinations(self):
        for dest in (None, "", "not stated", "N/A"):
            with self.subTest(destination=dest):
                verdict = _gate(destination=dest)
                self.assertFalse(verdict["allowed"])
                self.assertIn("destination is not stated", verdict["reason"])

    def test_a_boundary_with_no_excluded_destinations_has_nothing_to_check(self):
        boundary = copy.deepcopy(BOUNDARY)
        boundary["permissions"]["auto_release"]["forbidden_destinations"] = []
        case = copy.deepcopy(CLEAN_CASE)
        case["shipment"]["destination"] = ""
        self.assertTrue(governance.check("release_shipment", case, boundary)["allowed"])


if __name__ == "__main__":
    unittest.main()
