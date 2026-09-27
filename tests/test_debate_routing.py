"""
The auto-debate's verdict changes routing -- upward only.

WHY THIS FILE EXISTS

When the deterministic floor outscores the junior analyst by 15+ points, the
orchestrator puts the Senior Auditor on the case (conduct_debate). Its verdict was
recorded on the case and then read by nothing: routing used the floor alone, so
the pipeline's most expensive model call could not change a single outcome.

orchestrator.debate_escalation() now lets exactly one answer matter: a DISAGREE
the model genuinely rendered, at or above DEBATE_ESCALATE_CONFIDENCE, sends the
case to the deep investigation it would otherwise have skipped, and may raise --
never lower -- its risk. These tests pin both halves: that the verdict now acts,
and every way it must NOT.

The shipment below trips exactly one finding (SHIPPER_NO_HISTORY, HIGH, floor
65). With the junior analyst at 20 that is a 45-point dispute, and 65 is below
INVESTIGATE_AT (70) -- so without the debate the case is queued for review, and
the debate is the only thing that can send it to investigation.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

from vf_logistics import orchestrator, store as store_mod

SHIPMENT = {
    "shipment_id": "TEST-DEBATE-1",
    "origin": "Ho Chi Minh City, Vietnam",
    "destination": "Rotterdam, Netherlands",
    "weight_kg": 1200,
    "declared_value": 40000,
    "shipping_cost": 2600,
    "avg_route_cost": 2500,
    "shipper_name": "Lotus Garment Works",
    "shipper_company": "Lotus Garment Works JSC",
    "shipper_country": "Vietnam",
    "shipper_tax_id": "0312345678",
    "receiver_name": "Procurement",
    "receiver_company": "Noordzee Textiel BV",
    "receiver_country": "Netherlands",
    "shipper_tx_count": 1,
    "cargo_description": "Cotton T-shirts, 4000 units",
    "hs_code": "6109.10",
    "transit_points": "none",
    "route_details": "direct sailing",
}
FLOOR = 65

FRAUD_LOW = {
    "result": {"risk_score": 20, "risk_level": "LOW"},
    "model": "nano", "latency_ms": 800, "input_tokens": 900, "output_tokens": 200,
    "at": "2026-09-26T12:00:00+00:00", "parse_error": False,
    "prompt": "fraud prompt", "raw": '{"risk_score":20}',
}
COMPLIANT = {
    "result": {"compliance_status": "COMPLIANT", "compliance_score": 90},
    "model": "nano", "latency_ms": 700, "input_tokens": 800, "output_tokens": 150,
    "at": "2026-09-26T12:00:01+00:00", "parse_error": False,
    "prompt": "compliance prompt", "raw": "{}",
}
INVESTIGATION = {
    "result": {
        "summary": "Shipper has one prior shipment; pattern consistent with a front company.",
        "fraud_pattern": "front company",
        "exposure_estimate": "40,000 USD",
    },
    "model": "super", "latency_ms": 3000, "input_tokens": 2000, "output_tokens": 400,
    "at": "2026-09-26T12:00:09+00:00", "parse_error": False,
    "prompt": "investigation prompt", "raw": "{}",
}


def debate(verdict: dict | None) -> dict:
    return {
        "agent": "debate", "model": "ultra", "latency_ms": 4200,
        "input_tokens": 3000, "output_tokens": 700,
        "at": "2026-09-26T12:00:05+00:00", "prompt": "CASE UNDER REVIEW...",
        "result": {"verdict": verdict, "debate_trace": [], "rounds_used": 2},
    }


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def drive(verdict: dict | None, *, adjustment: int = 0, env: dict | None = None):
    """Ingest SHIPMENT and advance it until it stops. Returns (case, investigate mock)."""
    store_mod._store = None
    orchestrator._invalidate_shipper_feedback()
    investigate = AsyncMock(return_value=INVESTIGATION)
    offline = RuntimeError("no model calls in this test")
    with patch.dict(os.environ, env or {}), \
         patch.object(orchestrator, "analyze_shipment", AsyncMock(return_value=FRAUD_LOW)), \
         patch.object(orchestrator, "screen_shipment", AsyncMock(return_value=COMPLIANT)), \
         patch.object(orchestrator, "conduct_debate", AsyncMock(return_value=debate(verdict))), \
         patch.object(orchestrator, "investigate_case", investigate), \
         patch.object(orchestrator, "classify_hs", AsyncMock(side_effect=offline)), \
         patch.object(orchestrator, "screen_zero_day", AsyncMock(side_effect=offline)), \
         patch.object(orchestrator, "shipper_risk_adjustment", AsyncMock(return_value=adjustment)), \
         patch.object(orchestrator.tavily_client, "search", AsyncMock(return_value=[])):
        case = _run(orchestrator.ingest_shipment(dict(SHIPMENT)))
        for _ in range(6):
            if case["state"] not in ("INGESTED", "SPECIALISTS_DONE", "INVESTIGATED"):
                break
            case = _run(orchestrator.advance(case))
    return case, investigate


class TestTheVerdictNowActs(unittest.TestCase):

    def test_the_premise(self):
        """Without an escalating verdict this case is queued, not investigated."""
        case, investigate = drive({"verdict": "CONFIRM", "confidence": 0.9, "forced": False})
        self.assertEqual(case["reconciliation"]["risk_floor"], FLOOR)
        self.assertTrue(case["reconciliation"]["score_disputed"])
        self.assertEqual(case["proposed_outcome"], "HELD_FOR_REVIEW")
        investigate.assert_not_called()

    def test_a_confident_disagree_sends_the_case_to_investigation(self):
        case, investigate = drive(
            {"verdict": "DISAGREE", "confidence": 0.85, "forced": False,
             "rationale": "One prior shipment and a round-number value."}
        )
        investigate.assert_called_once()
        self.assertTrue(case["debate_escalated"])
        self.assertTrue(case["debate_effect"]["escalated"])
        self.assertEqual(case["proposed_outcome"], "ESCALATED")
        # The investigation is told why it is running.
        payload = investigate.call_args.args[0]
        self.assertIn("Senior Auditor disagreed", payload["trigger_reason"])

    def test_it_may_raise_risk_to_the_auditors_score(self):
        case, _ = drive({"verdict": "DISAGREE", "confidence": 0.85, "forced": False,
                         "adjusted_risk_score": 78})
        self.assertEqual(case["risk_score"], 78)
        self.assertEqual(case["reconciliation"]["raised_by"], "debate")
        self.assertEqual(case["debate_effect"]["risk_before"], FLOOR)


class TestItNeverLowersAnything(unittest.TestCase):

    def test_a_lower_adjusted_score_does_not_lower_risk(self):
        """The auditor's number is an opinion; it does not undercut the floor."""
        case, _ = drive({"verdict": "DISAGREE", "confidence": 0.9, "forced": False,
                         "adjusted_risk_score": 30})
        self.assertEqual(case["risk_score"], FLOOR)
        self.assertNotIn("raised_by", case["reconciliation"])
        self.assertEqual(case["proposed_outcome"], "ESCALATED")

    def test_confirm_changes_nothing(self):
        case, investigate = drive({"verdict": "CONFIRM", "confidence": 0.99, "forced": False,
                                   "adjusted_risk_score": 5})
        investigate.assert_not_called()
        self.assertEqual(case["risk_score"], FLOOR)
        self.assertFalse(case["debate_effect"]["escalated"])
        self.assertIn("confirmed", case["debate_effect"]["reason"])

    def test_a_forced_verdict_changes_nothing(self):
        """A default the system filled in is not a judgement, whatever it says."""
        case, investigate = drive({"verdict": "DISAGREE", "confidence": 0.95,
                                   "forced": True, "forced_reason": "rounds_exhausted"})
        investigate.assert_not_called()
        self.assertEqual(case["proposed_outcome"], "HELD_FOR_REVIEW")
        self.assertIn("default", case["debate_effect"]["reason"])

    def test_a_timid_disagree_changes_nothing_and_says_why(self):
        case, investigate = drive({"verdict": "DISAGREE", "confidence": 0.55, "forced": False})
        investigate.assert_not_called()
        self.assertEqual(case["proposed_outcome"], "HELD_FOR_REVIEW")
        self.assertIn("below", case["debate_effect"]["reason"])

    def test_the_threshold_is_configurable(self):
        case, investigate = drive(
            {"verdict": "DISAGREE", "confidence": 0.55, "forced": False},
            env={"DEBATE_ESCALATE_CONFIDENCE": "0.5"},
        )
        investigate.assert_called_once()
        self.assertEqual(case["debate_effect"]["threshold"], 0.5)


class TestDebateEscalationRules(unittest.TestCase):
    """The pure rule, including the inputs a model can get wrong."""

    def test_malformed_verdicts_never_escalate(self):
        for verdict in (
            None, {}, {"verdict": "DISAGREE"},
            {"verdict": "DISAGREE", "confidence": "very"},
            {"verdict": "DISAGREE", "confidence": 7},
            {"verdict": "disagree", "confidence": 0.9},
        ):
            with self.subTest(verdict=verdict):
                self.assertFalse(orchestrator.debate_escalation(verdict)[0])

    def test_a_bad_threshold_falls_back_to_the_default(self):
        for raw in ("", "high", "1.5", "-0.1"):
            with self.subTest(raw=raw), patch.dict(os.environ, {"DEBATE_ESCALATE_CONFIDENCE": raw}):
                self.assertEqual(
                    orchestrator.debate_escalate_confidence(),
                    orchestrator.DEBATE_ESCALATE_CONFIDENCE_DEFAULT,
                )

    def test_a_model_cannot_claim_its_own_verdict_is_forced(self):
        """debate_agent strips `forced` from the model's arguments and sets it itself."""
        from vf_logistics.agents import debate_agent  # noqa: F401 -- import is the check

        verdict = {"verdict": "DISAGREE", "confidence": 0.9}
        self.assertTrue(orchestrator.debate_escalation({**verdict, "forced": False})[0])
        self.assertFalse(orchestrator.debate_escalation({**verdict, "forced": True})[0])


class TestLearningLoopRespectsTheFloor(unittest.TestCase):
    """
    Found while wiring the debate in: the shipper-history adjustment clamped at 0,
    not at the deterministic floor, despite its comment promising the opposite.
    """

    def test_a_trusted_shipper_is_not_discounted_below_the_floor(self):
        case, _ = drive({"verdict": "CONFIRM", "confidence": 0.9, "forced": False},
                        adjustment=-10)
        self.assertEqual(case["risk_score"], FLOOR)
        self.assertEqual(case["reconciliation"]["learning_adjustment"], 0)
        self.assertIn("held at the deterministic floor", case["reconciliation"]["learning_note"])

    def test_a_distrusted_shipper_is_still_raised(self):
        case, _ = drive({"verdict": "CONFIRM", "confidence": 0.9, "forced": False},
                        adjustment=15)
        self.assertEqual(case["risk_score"], FLOOR + 15)
        # 80 is above INVESTIGATE_AT, so history alone now sends it to investigation.
        self.assertEqual(case["proposed_outcome"], "ESCALATED")


if __name__ == "__main__":
    unittest.main()
