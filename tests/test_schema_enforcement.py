"""
Module 4: deterministic AI output -- schema enforcement, retry, and the
human-review fallback.

These tests exist because of a specific hole that was open before this module,
and the end-to-end case at the bottom is the one that matters most.

The hole
--------
orchestrator's auto-clear condition read:

    clean = risk < FRAUD_CLEAR_BELOW and may_auto_clear and status not in (...)

`may_auto_clear` comes from reconcile(), which correctly refuses to permit an
auto-clear when the FRAUD score is missing. But nothing covered the COMPLIANCE
agent. A compliance reply that failed to parse left compliance_status at
"UNKNOWN", which is not in ("BLOCKED", "REVIEW_REQUIRED"), so a low-risk shipment
would auto-clear on the strength of a sanctions screening that never happened.

That is the worst outcome this system can produce, so
test_compliance_schema_failure_cannot_auto_clear asserts against it directly --
and asserts the control case DOES auto-clear, because a test where nothing can
ever be released would pass even if auto-clear were removed entirely.

What is deliberately NOT tested
-------------------------------
That retries happen inside complete_json. Every existing test mocks
complete_json itself, so the retry wrapper is below the seam they patch. The
wrapper is tested directly instead, which is where its behaviour lives.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from openai import (
    APIConnectionError,
    APITimeoutError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
)

os.environ.setdefault("STORE_BACKEND", "memory")

from vf_logistics import governance, nebius_client, orchestrator, verifier  # noqa: E402
from vf_logistics import store as store_mod  # noqa: E402
from vf_logistics.agents._common import envelope, parse_model_json, validate_result  # noqa: E402
from vf_logistics.schemas import (  # noqa: E402
    AGENT_OUTPUT_SCHEMAS,
    ReconciliationInfo,
)


def _run(coro):
    """Fresh loop per call; the suite shares a process and closes loops."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _reset_store():
    store_mod._store = None
    orchestrator._invalidate_shipper_feedback()


def _req():
    return httpx.Request("POST", "https://example.invalid/v1/chat/completions")


def _resp(code: int):
    return httpx.Response(code, request=_req())


# A shipment that genuinely clears: no deterministic findings, under the
# delegated value ceiling, benign HS heading, low-risk lane. Every field the
# mandatory-field check looks for is present, because a missing one sets a floor
# of 45 and the case can then never reach auto-clear -- which would make the
# control case useless.
CLEARABLE_SHIPMENT = {
    "shipment_id": "S-SCHEMA-1",
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

VALID_FRAUD = (
    '{"risk_score": 12, "risk_level": "LOW", "flags": [], '
    '"recommendations": [], "confidence": 0.9}'
)
VALID_COMPLIANCE = (
    '{"compliance_status": "CLEARED", "compliance_score": 95, "risk_factors": [], '
    '"sanctions_hits": null, "regulatory_issues": [], "required_actions": [], '
    '"confidence": 0.9}'
)
TERMINAL = (
    "AUTO_CLEARED", "HELD_FOR_REVIEW", "PENDING_HUMAN",
    "ESCALATED", "BLOCKED", "RELEASED", "DEAD_LETTER",
)


def _envelope_for(agent: str, text: str, legacy_key: str) -> dict:
    parsed, error = parse_model_json(text)
    return envelope(
        agent=agent,
        model="nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
        result=parsed, error=error, raw=text, latency_ms=10,
        legacy_key=legacy_key, input_tokens=100, output_tokens=50,
    )


class TestSchemaValidation(unittest.TestCase):
    def test_existing_test_mock_shape_still_validates(self):
        """
        tests/test_orchestrator_unit.py mocks fraud with `findings`, while the
        prompt at fraud_detection_agent.py:41 asks for `flags`. Both are accepted
        because nothing downstream reads either to make a decision; only
        risk_score is required. If this fails, the schema has started demanding
        fields the system does not use.
        """
        out, err = validate_result(
            "fraud_detection",
            {"risk_score": 25, "findings": [], "recommendations": []},
        )
        self.assertIsNone(err)
        self.assertEqual(out["risk_score"], 25)

    def test_missing_risk_score_is_rejected(self):
        out, err = validate_result("fraud_detection", {"flags": []})
        self.assertIsNone(out)
        self.assertIn("risk_score", err)

    def test_non_numeric_risk_score_is_rejected_not_coerced(self):
        out, err = validate_result("fraud_detection", {"risk_score": "high"})
        self.assertIsNone(out)
        self.assertIn("risk_score", err)

    def test_out_of_range_risk_score_is_rejected_not_clamped(self):
        """
        A model returning 150 is malfunctioning and clamping to 100 would hide
        it. Rejection is safe: reconcile() treats a missing score as
        max(floor, 50) with auto_clear_permitted False, so this can only send a
        shipment to a human, never release one.
        """
        for bad in (150, -5):
            out, err = validate_result("fraud_detection", {"risk_score": bad})
            self.assertIsNone(out, f"{bad} should be rejected")
            self.assertIn("risk_score", err)

    def test_off_enum_compliance_status_is_rejected(self):
        out, err = validate_result(
            "compliance",
            {"compliance_status": "PROBABLY_FINE", "compliance_score": 90},
        )
        self.assertIsNone(out)
        self.assertIn("compliance_status", err)

    def test_hs_consistent_must_be_a_real_bool(self):
        """
        StrictBool, matching hs_classifier_agent.interpret(), which requires
        isinstance(consistent, bool). Pydantic's lax mode reads "no" as False, so
        a plain bool annotation accepted replies that interpret() then reported
        as "unknown" -- two layers disagreeing about the same reply.
        """
        out, err = validate_result("hs_classifier", {"consistent": False})
        self.assertIsNone(err)

        for bad in ("no", "false", 0, 1, None):
            out, err = validate_result("hs_classifier", {"consistent": bad})
            self.assertIsNone(out, f"{bad!r} should not pass as a bool")

    def test_zero_day_separates_searched_from_risk_found(self):
        """
        tavily_client returns [] for a missing API key, a timeout, and a
        genuinely empty result alike. Without `searched` as its own required
        field, an outage would be indistinguishable from a clean entity.
        """
        schema = AGENT_OUTPUT_SCHEMAS["zero_day"]
        self.assertIn("searched", schema.model_fields)
        self.assertTrue(schema.model_fields["searched"].is_required())

        out, err = validate_result(
            "zero_day",
            {"risk_found": False, "confidence": 0.8, "reasoning": "nothing found"},
        )
        self.assertIsNone(out, "a verdict that does not say whether it searched")
        self.assertIn("searched", err)

    def test_investigation_fragments_are_rejected(self):
        """
        The four shapes Nemotron 3 Super actually returned on 8 of 16
        investigations on the 20-case board. Each is valid JSON, so the parser
        accepts it; before this schema each was stored as a finished
        investigation with parse_error False.
        """
        fragments = (
            '{": {}}": null}',
            '{".json": null}',
            '{": {": {}}',
            '{": {}}? Actually top-level JSON object with fields. Provide '
            'summary, evidence list, connections list.": null}',
        )
        for text in fragments:
            parsed, perr = parse_model_json(text)
            self.assertIsNone(perr, f"{text!r} is valid JSON; the parser is not the gap")
            out, err = validate_result("investigation", parsed)
            self.assertIsNone(out, f"{text!r} should not pass as an investigation")
            self.assertIn("summary", err)

    def test_investigation_blank_summary_is_rejected(self):
        for blank in ("", "   ", None):
            out, err = validate_result("investigation", {"summary": blank})
            self.assertIsNone(out, f"{blank!r} is not a narrative")

    def test_investigation_real_report_is_kept_whole(self):
        """
        The shape of the six good replies on the board, including the one that
        returned `connections` as a dict instead of a list. Nothing is dropped:
        the trace shows the whole report, not only the fields the schema names.
        """
        for connections in ([{"entity": "Truong Hai Trading Co"}], {"related": []}):
            report = {
                "investigation_id": "INV-1",
                "summary": "Shipment exhibits multiple red flags.",
                "evidence": ["future-dated creation timestamp"],
                "connections": connections,
                "fraud_pattern": "Trade-based money laundering",
                "exposure_estimate": "USD 88,000 cargo value plus penalties",
                "confidence_level": 0.85,
                "recommended_actions": ["hold shipment"],
                "escalation_required": True,
                "escalation_reason": "sanctioned destination",
            }
            out, err = validate_result("investigation", report)
            self.assertIsNone(err)
            self.assertEqual(out, report)

    def test_unregistered_agent_passes_through(self):
        payload = {"anything": 1}
        out, err = validate_result("document", payload)
        self.assertIsNone(err)
        self.assertEqual(out, payload)

    def test_upstream_parse_error_is_not_masked(self):
        """None in means the parse already failed; don't overwrite that error."""
        out, err = validate_result("fraud_detection", None)
        self.assertIsNone(out)
        self.assertIsNone(err)

    def test_extra_fields_are_kept_not_rejected(self):
        out, err = validate_result(
            "fraud_detection", {"risk_score": 30, "invented_field": "x"},
        )
        self.assertIsNone(err)
        self.assertEqual(out["invented_field"], "x")


class TestReconciliationSchemaMatchesCode(unittest.TestCase):
    def test_schema_validates_real_reconcile_output(self):
        """
        ReconciliationInfo previously declared `effective`, `disputed` and
        `dispute_delta` while reconcile() returns `effective_risk`,
        `score_disputed` and `auto_clear_permitted`. No route imported the
        module, which is the only reason the mismatch survived.
        """
        validation = verifier.validate(CLEARABLE_SHIPMENT)
        for model_score in (12, None):
            reconciled = verifier.reconcile(model_score, validation)
            ReconciliationInfo.model_validate(reconciled)  # raises on mismatch


class TestEnvelopeFlags(unittest.TestCase):
    def test_schema_error_is_flagged_separately_from_parse_error(self):
        """
        JSON that would not parse is a formatting problem; JSON that parsed into
        the wrong shape is a model behaviour problem. Different fixes, so they
        stay separately countable.
        """
        out = _envelope_for("fraud_detection", '{"risk_score": "high"}', "analysis")
        self.assertTrue(out["parse_error"])
        self.assertTrue(out["schema_error"])
        self.assertEqual(out["result"], {})

        out = _envelope_for("fraud_detection", "not json at all", "analysis")
        self.assertTrue(out["parse_error"])
        self.assertNotIn("schema_error", out)

    def test_raw_reply_is_retained_on_schema_failure(self):
        """A reviewer has to be able to see what the model actually said."""
        out = _envelope_for("fraud_detection", '{"risk_score": "high"}', "analysis")
        self.assertIn("high", out["raw"])

    def test_validate_false_skips_enforcement(self):
        """
        The debate agent's envelope wraps a trace plus a verdict; the verdict is
        validated on its own before it gets here.
        """
        out = envelope(
            agent="fraud_detection", model="m", result={"not": "a score"},
            error=None, raw="{}", latency_ms=1, legacy_key="analysis",
            validate=False,
        )
        self.assertFalse(out["parse_error"])
        self.assertEqual(out["result"], {"not": "a score"})


class TestRetry(unittest.TestCase):
    def setUp(self):
        self._backoff = nebius_client.BACKOFF_BASE_SECONDS
        nebius_client.BACKOFF_BASE_SECONDS = 0.001

    def tearDown(self):
        nebius_client.BACKOFF_BASE_SECONDS = self._backoff

    def test_transport_and_server_failures_are_retryable(self):
        for exc in (
            APITimeoutError(request=_req()),
            APIConnectionError(request=_req()),
            RateLimitError("429", response=_resp(429), body=None),
            InternalServerError("500", response=_resp(500), body=None),
        ):
            self.assertTrue(
                nebius_client._is_retryable(exc), type(exc).__name__,
            )

    def test_client_errors_are_not_retryable(self):
        """A 400 or 404 fails identically on the second attempt, and the retry
        budget belongs to failures that might actually succeed."""
        for exc in (
            BadRequestError("400", response=_resp(400), body=None),
            NotFoundError("404", response=_resp(404), body=None),
            ValueError("not an API error"),
        ):
            self.assertFalse(
                nebius_client._is_retryable(exc), type(exc).__name__,
            )

    def test_recovers_after_transient_failures(self):
        calls = {"n": 0}

        async def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise APITimeoutError(request=_req())
            return "ok"

        self.assertEqual(_run(nebius_client._with_retry("t", flaky)), "ok")
        self.assertEqual(calls["n"], 3)

    def test_raises_after_exhausting_attempts(self):
        """
        Raises rather than returning a sentinel. Each agent already turns an
        exception into an envelope carrying `error`, which the orchestrator
        routes to a human; inventing a successful-looking response here would put
        a made-up number into a compliance decision.
        """
        calls = {"n": 0}

        async def always():
            calls["n"] += 1
            raise APITimeoutError(request=_req())

        with self.assertRaises(APITimeoutError):
            _run(nebius_client._with_retry("t", always))
        self.assertEqual(calls["n"], nebius_client.MAX_ATTEMPTS)

    def test_does_not_retry_a_client_error(self):
        calls = {"n": 0}

        async def bad():
            calls["n"] += 1
            raise BadRequestError("400", response=_resp(400), body=None)

        with self.assertRaises(BadRequestError):
            _run(nebius_client._with_retry("t", bad))
        self.assertEqual(calls["n"], 1)

    def test_budget_is_bounded_below_the_worker_timeout(self):
        """
        app.py:171-174 gives the whole request 120s on the worker thread. Three
        attempts at the per-request timeout must not exceed that, or a caller
        gets killed mid-retry and the customer sees a dead request instead of a
        case in the review queue.
        """
        self.assertLess(nebius_client.RETRY_BUDGET_SECONDS, 120)
        self.assertLessEqual(
            nebius_client.REQUEST_TIMEOUT_SECONDS, nebius_client.RETRY_BUDGET_SECONDS,
        )

    def test_sdk_retries_are_disabled(self):
        """Two retry policies multiply: 2 SDK retries inside 3 of ours is 6 calls
        and 6x the budget."""
        saved_client, saved_key = nebius_client._client, nebius_client.NEBIUS_API_KEY
        nebius_client._client = None
        # The SDK raises OpenAIError on an empty key, so the build needs one. A
        # missing credential is correctly NOT retryable -- OpenAIError is absent
        # from _RETRYABLE, so it propagates on the first attempt rather than
        # burning the budget on a failure that cannot succeed.
        nebius_client.NEBIUS_API_KEY = "test-key-not-used-for-requests"
        try:
            client = nebius_client.get_client()
            self.assertEqual(client.max_retries, 0)
            self.assertEqual(
                client.timeout, nebius_client.REQUEST_TIMEOUT_SECONDS,
                "an unbounded per-request timeout lets one hung call eat the "
                "whole worker budget",
            )
        finally:
            nebius_client._client = saved_client
            nebius_client.NEBIUS_API_KEY = saved_key


class TestHumanReviewFallback(unittest.TestCase):
    """
    The hole this module was written to close, asserted end to end.
    """

    def _drive(
        self,
        fraud_text: str,
        compliance_text: str,
        investigation_text: str = '{"summary": "x"}',
    ) -> dict:
        _reset_store()
        # Without an ACTIVE boundary the governance gate is fail-closed and
        # nothing can be released, so the control case would pass for the wrong
        # reason.
        _run(governance.publish_boundary(
            governance.proposed_boundary("schema enforcement test"),
            "test-harness", "enable auto-release so the control can clear",
        ))

        with patch.object(
            orchestrator, "analyze_shipment",
            new=AsyncMock(return_value=_envelope_for(
                "fraud_detection", fraud_text, "analysis")),
        ), patch.object(
            orchestrator, "screen_shipment",
            new=AsyncMock(return_value=_envelope_for(
                "compliance", compliance_text, "screening_result")),
        ), patch.object(
            orchestrator.tavily_client, "search", new=AsyncMock(return_value=[]),
        ), patch.object(
            orchestrator, "conduct_debate",
            new=AsyncMock(return_value={"result": {"verdict": {}}}),
        ), patch.object(
            orchestrator, "investigate_case",
            new=AsyncMock(return_value=_envelope_for(
                "investigation", investigation_text, "investigation_result")),
        ):
            case = _run(orchestrator.ingest_shipment(dict(CLEARABLE_SHIPMENT)))
            for _ in range(10):
                if case.get("state") in TERMINAL:
                    break
                case = _run(orchestrator.advance(case)) or case
        return case

    def test_control_case_does_auto_clear(self):
        """
        Asserted first and on purpose. If auto-clear were unreachable in this
        fixture, every test below would pass even with the guard removed.
        """
        case = self._drive(VALID_FRAUD, VALID_COMPLIANCE)
        self.assertEqual(case["state"], "AUTO_CLEARED")
        self.assertEqual(case.get("_model_failures", 0), 0)

    def test_compliance_schema_failure_cannot_auto_clear(self):
        """
        The specific hole: fraud says 12, so risk is low and reconcile() permits
        an auto-clear, but the sanctions screening returned nothing usable.
        Releasing here means releasing on a screening that never happened.
        """
        case = self._drive(
            VALID_FRAUD,
            '{"compliance_status": "PROBABLY_FINE", "compliance_score": "very good"}',
        )
        self.assertNotEqual(case["state"], "AUTO_CLEARED")
        self.assertIn(case["state"], ("HELD_FOR_REVIEW", "PENDING_HUMAN"))
        self.assertEqual(case["_model_failure_agents"], ["compliance"])

    def test_compliance_unparseable_cannot_auto_clear(self):
        case = self._drive(VALID_FRAUD, "the shipment looks fine to me")
        self.assertNotEqual(case["state"], "AUTO_CLEARED")
        self.assertEqual(case["_model_failure_agents"], ["compliance"])

    def test_fraud_schema_failure_cannot_auto_clear(self):
        case = self._drive('{"risk_score": "quite low really"}', VALID_COMPLIANCE)
        self.assertNotEqual(case["state"], "AUTO_CLEARED")
        self.assertEqual(case["_model_failure_agents"], ["fraud_detection"])

    def test_both_agents_failing_is_counted_once_each(self):
        case = self._drive('{"nope": true}', '{"nope": true}')
        self.assertNotEqual(case["state"], "AUTO_CLEARED")
        self.assertEqual(case["_model_failures"], 2)
        self.assertEqual(
            sorted(case["_model_failure_agents"]),
            ["compliance", "fraud_detection"],
        )

    def test_failure_is_visible_on_the_step_for_a_reviewer(self):
        case = self._drive(VALID_FRAUD, '{"compliance_status": "NOPE"}')
        compliance_steps = [s for s in case["steps"] if s["agent"] == "compliance"]
        self.assertTrue(compliance_steps)
        step = compliance_steps[0]
        self.assertTrue(step["parse_error"])
        self.assertTrue(step.get("schema_error"))
        self.assertIn("NOPE", step["raw_response"])

    def _investigated(self, investigation_text: str) -> tuple[dict, dict]:
        """A valid REVIEW_REQUIRED screening, so the case goes to investigation."""
        case = self._drive(
            VALID_FRAUD,
            VALID_COMPLIANCE.replace('"CLEARED"', '"REVIEW_REQUIRED"'),
            investigation_text,
        )
        steps = [s for s in case["steps"] if s["agent"] == "investigation"]
        self.assertEqual(len(steps), 1, "the fixture must reach the investigation")
        return case, steps[0]

    def test_good_investigation_is_not_counted_as_a_failure(self):
        """Control for the test below: same route, a usable report."""
        case, step = self._investigated('{"summary": "Red flags on the lane."}')
        self.assertFalse(step["parse_error"])
        self.assertEqual(case.get("_model_failures", 0), 0)
        self.assertEqual(case["state"], "ESCALATED")

    def test_fragment_investigation_is_a_counted_failure_and_still_escalates(self):
        """
        The reply Super gave on 8 of 16 board investigations. It must show as
        failed on the step and be named in _model_failure_agents, which is what
        b2b._review_reason reports to the integrator. Routing is unchanged: the
        case was already going to a human and still does.
        """
        case, step = self._investigated('{": {}}": null}')
        self.assertTrue(step["parse_error"])
        self.assertTrue(step.get("schema_error"))
        self.assertEqual(step["result"], {})
        self.assertEqual(case["_model_failure_agents"], ["investigation"])
        self.assertEqual(case["state"], "ESCALATED")


class TestInvestigationRequest(unittest.TestCase):
    """
    How the investigation agent asks Super, and what it does with a fragment.

    Measured on the live model: json_object with reasoning gave 6/12 usable
    reports, the same prompt without response_format 12/12. These pin the request
    shape that measurement chose, and the one retry that covers what is left.
    """

    FRAGMENT = '{": {}}": null}'
    GOOD = '{"summary": "Red flags on the lane.", "fraud_pattern": "undervaluation"}'

    def _investigate(self, *replies: str):
        from vf_logistics import tavily_client
        from vf_logistics.agents import investigation_agent

        calls = AsyncMock(side_effect=[(r, 1000, 300) for r in replies])
        with patch.object(investigation_agent.nebius_client, "complete_json", calls), \
             patch.object(
                 investigation_agent.tavily_client, "search_with_status",
                 new=AsyncMock(return_value=([], tavily_client.OK)),
             ):
            out = _run(investigation_agent.investigate_case({
                "case_id": "CASE-T", "trigger_reason": "test",
                "primary_shipment": {"shipper_name": "A Co"},
            }))
        return out, calls

    def test_super_is_not_asked_through_json_object(self):
        out, calls = self._investigate(self.GOOD)
        self.assertIs(calls.await_args.kwargs["json_mode"], False)

    def test_json_mode_false_sends_no_response_format(self):
        captured: dict = {}

        class FakeCompletions:
            async def create(self, **kw):
                captured.update(kw)
                message = type("M", (), {"content": "{}"})()
                choice = type("C", (), {"message": message, "finish_reason": "stop"})()
                usage = type("U", (), {"prompt_tokens": 1, "completion_tokens": 1})()
                return type("R", (), {"choices": [choice], "usage": usage})()

        client = type("Client", (), {
            "chat": type("Chat", (), {"completions": FakeCompletions()})(),
        })()
        with patch.object(nebius_client, "get_client", return_value=client), \
             patch.object(nebius_client.budget, "assert_within_budget", new=AsyncMock()):
            _run(nebius_client.complete_json(
                model="m", system_prompt="s", user_text="u", json_mode=False))
            self.assertNotIn("response_format", captured)
            captured.clear()
            _run(nebius_client.complete_json(model="m", system_prompt="s", user_text="u"))
            self.assertEqual(captured["response_format"], {"type": "json_object"})

    def test_good_first_reply_is_one_call(self):
        out, calls = self._investigate(self.GOOD)
        self.assertEqual(calls.await_count, 1)
        self.assertFalse(out["parse_error"])
        self.assertEqual(out["attempts"], 1)

    def test_a_fragment_is_asked_again_and_both_calls_are_billed(self):
        out, calls = self._investigate(self.FRAGMENT, self.GOOD)
        self.assertEqual(calls.await_count, 2)
        self.assertFalse(out["parse_error"])
        self.assertEqual(out["result"]["summary"], "Red flags on the lane.")
        self.assertEqual(out["attempts"], 2)
        self.assertEqual((out["input_tokens"], out["output_tokens"]), (2000, 600))

    def test_two_fragments_stop_and_are_reported(self):
        out, calls = self._investigate(self.FRAGMENT, self.FRAGMENT)
        self.assertEqual(calls.await_count, 2)
        self.assertTrue(out["parse_error"])
        self.assertTrue(out.get("schema_error"))
        self.assertEqual(out["raw"], self.FRAGMENT)


if __name__ == "__main__":
    unittest.main()
