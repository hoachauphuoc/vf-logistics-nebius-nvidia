"""
Unit tests for mock-based modules: orchestrator state machine, tools, agents.

Uses MemoryStore (no Firestore) and mocked AI agents.
"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from store import MemoryStore, utcnow


def run(coro):
    """Helper to run async code in sync tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_store():
    """Create a fresh MemoryStore for each test."""
    return MemoryStore()


def _agent_response(risk=25, status="completed", findings=None):
    """Build a mock agent response envelope."""
    return {
        "status": status,
        "result": {
            "risk_score": risk,
            "findings": findings or [],
            "recommendations": [],
            "severity": "LOW" if risk < 40 else "HIGH",
        },
        "analysis": {
            "risk_score": risk,
            "findings": findings or [],
            "recommendations": [],
        },
        "model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
        "latency_ms": 500,
        "input_tokens": 100,
        "output_tokens": 50,
        "parse_error": False,
        "at": utcnow(),
    }


def _compliance_response(status_val="CLEAR"):
    """Build a mock compliance agent response."""
    r = _agent_response(risk=10)
    r["result"]["compliance_status"] = status_val
    r["result"]["status"] = status_val
    r["analysis"]["compliance_status"] = status_val
    r["analysis"]["status"] = status_val
    return r


def _validation_result(skip_ai=False, auto_reject=False, risk_floor=0, findings=None):
    """Build a mock verifier.validate result."""
    fl = findings or []
    return {
        "skip_ai": skip_ai,
        "auto_clear_by_rules": skip_ai and not auto_reject,
        "auto_reject_by_rules": auto_reject,
        "risk_floor": risk_floor,
        "findings": fl,
        "finding_count": len(fl),
        "checks_run": ["freight_ratio", "value_density", "mandatory_fields",
                        "hs_code", "routing", "counterparty"],
        "auto_clear_permitted": risk_floor < 40,
        "clearance_signal": "whitelist" if skip_ai else None,
        "score_disputed": False,
        "injection_screening": {"blocked": False, "findings": []},
    }


def _fresh_patches():
    """Create fresh mock objects for each test."""
    return {
        "orchestrator.analyze_shipment": AsyncMock(return_value=_agent_response(risk=25)),
        "orchestrator.screen_shipment": AsyncMock(return_value=_compliance_response()),
        "orchestrator.investigate_case": AsyncMock(return_value=_agent_response(risk=75)),
        "orchestrator.extract_shipment": AsyncMock(),
        "orchestrator.governance.execute": AsyncMock(return_value={"status": "done", "detail": {}}),
        "orchestrator.governance.agent_readiness": AsyncMock(return_value={"state": "ACTIVE"}),
        "orchestrator.document_store.archive": AsyncMock(return_value={"archived": True, "uri": "gs://test"}),
        "orchestrator.document_render.render_bill_of_lading": MagicMock(return_value=b"%PDF"),
        "orchestrator.model_armor.screen": AsyncMock(return_value={"blocked": False}),
        "orchestrator.model_armor.extract_pdf_text": MagicMock(return_value=("text", None)),
        "orchestrator.shipper_registry.enrich": MagicMock(return_value={"status": "unknown"}),
        "orchestrator.untrusted.sanitise_shipment": MagicMock(
            side_effect=lambda raw: {
                "shipment": raw, "extraction_notes": [], "extraction_confidence": 0.95,
                "dropped_fields": [], "forbidden_fields_attempted": [],
            }
        ),
        "orchestrator.untrusted.screen_text": MagicMock(return_value={"blocked": False, "findings": []}),
        "orchestrator.untrusted.searchable_text": MagicMock(return_value="searchable"),
    }


def _patch_orchestrator():
    """Apply all patches and return a dict of mock objects."""
    patches = _fresh_patches()
    patchers = {name: patch(name, new) for name, new in patches.items()}
    mocks = {}
    for name, p in patchers.items():
        mocks[name] = p.start()
    return patchers, mocks


def _unpatch(patchers):
    for p in patchers.values():
        p.stop()


class TestOrchestratorIngest(unittest.TestCase):
    def setUp(self):
        self.store = _make_store()
        self.store_patcher = patch("orchestrator.get_store", return_value=self.store)
        self.store_patcher.start()
        self.patchers, self.mocks = _patch_orchestrator()

    def tearDown(self):
        _unpatch(self.patchers)
        self.store_patcher.stop()

    def test_ingest_creates_case_in_ingested_state(self):
        import orchestrator
        ship = {"shipment_id": "S-001", "origin": "HCM", "destination": "Singapore",
                "weight_kg": 100, "declared_value": 5000, "shipping_cost": 300}
        case = run(orchestrator.ingest_shipment(ship))
        self.assertEqual(case["state"], "INGESTED")
        self.assertIn("case_id", case)

    def test_ingest_idempotent(self):
        import orchestrator
        ship = {"shipment_id": "S-DUP", "origin": "A", "destination": "B",
                "weight_kg": 10, "declared_value": 100}
        c1 = run(orchestrator.ingest_shipment(ship))
        c2 = run(orchestrator.ingest_shipment(ship))
        self.assertEqual(c1["case_id"], c2["case_id"])


class TestOrchestratorPreFilter(unittest.TestCase):
    def setUp(self):
        self.store = _make_store()
        self.store_patcher = patch("orchestrator.get_store", return_value=self.store)
        self.store_patcher.start()
        self.patchers, self.mocks = _patch_orchestrator()

    def tearDown(self):
        _unpatch(self.patchers)
        self.store_patcher.stop()

    @patch("orchestrator.verifier.validate", return_value=_validation_result(skip_ai=True))
    def test_whitelist_fast_path_skips_ai(self, mock_validate):
        import orchestrator
        ship = {"shipment_id": "S-WL", "origin": "HCM", "destination": "SG",
                "weight_kg": 100, "declared_value": 5000}
        case = run(orchestrator.ingest_shipment(ship))
        case = run(orchestrator.advance(case))
        self.assertEqual(case["state"], "AUTO_CLEARED")
        self.assertEqual(case.get("cleared_by"), "rules")
        self.mocks["orchestrator.analyze_shipment"].assert_not_called()

    @patch("orchestrator.verifier.validate", return_value=_validation_result(
        skip_ai=True, auto_reject=True, risk_floor=100))
    def test_blacklist_fast_path_rejects(self, mock_validate):
        import orchestrator
        ship = {"shipment_id": "S-BL", "origin": "HCM", "destination": "SG",
                "weight_kg": 100, "declared_value": 5000}
        case = run(orchestrator.ingest_shipment(ship))
        case = run(orchestrator.advance(case))
        self.assertEqual(case["state"], "ESCALATED")
        self.mocks["orchestrator.analyze_shipment"].assert_not_called()


class TestOrchestratorAIPath(unittest.TestCase):
    def setUp(self):
        self.store = _make_store()
        self.store_patcher = patch("orchestrator.get_store", return_value=self.store)
        self.store_patcher.start()
        self.patchers, self.mocks = _patch_orchestrator()

    def tearDown(self):
        _unpatch(self.patchers)
        self.store_patcher.stop()

    @patch("orchestrator.verifier.validate", return_value=_validation_result(risk_floor=10))
    @patch("orchestrator.verifier.reconcile", return_value={
        "effective_risk": 25, "model_risk": 25, "risk_floor": 10, "source": "agent score",
        "score_disputed": False, "auto_clear_permitted": True,
    })
    def test_advance_ingested_to_specialists_done(self, mock_reconcile, mock_validate):
        import orchestrator
        ship = {"shipment_id": "S-AI1", "origin": "A", "destination": "B",
                "weight_kg": 100, "declared_value": 5000}
        case = run(orchestrator.ingest_shipment(ship))
        case = run(orchestrator.advance(case))
        self.assertEqual(case["state"], "SPECIALISTS_DONE")
        self.mocks["orchestrator.analyze_shipment"].assert_called_once()
        self.mocks["orchestrator.screen_shipment"].assert_called_once()

    @patch("orchestrator.verifier.validate", return_value=_validation_result(risk_floor=10))
    @patch("orchestrator.verifier.reconcile", return_value={
        "effective_risk": 25, "model_risk": 25, "risk_floor": 10, "source": "agent score",
        "score_disputed": False, "auto_clear_permitted": True,
    })
    def test_clean_case_auto_clears(self, mock_reconcile, mock_validate):
        import orchestrator
        ship = {"shipment_id": "S-CLR", "origin": "A", "destination": "B",
                "weight_kg": 100, "declared_value": 5000}
        case = run(orchestrator.ingest_shipment(ship))
        case = run(orchestrator.advance(case))
        self.assertEqual(case["state"], "SPECIALISTS_DONE")
        case = run(orchestrator.advance(case))
        self.assertEqual(case["state"], "AUTO_CLEARED")

    @patch("orchestrator.verifier.validate", return_value=_validation_result(risk_floor=60))
    @patch("orchestrator.verifier.reconcile", return_value={
        "effective_risk": 80, "model_risk": 80, "risk_floor": 60, "source": "agent score",
        "score_disputed": False, "auto_clear_permitted": False,
    })
    @patch("orchestrator.verifier.check_exposure_claim", return_value=None)
    def test_high_risk_escalates(self, mock_exposure, mock_reconcile, mock_validate):
        import orchestrator
        self.mocks["orchestrator.screen_shipment"].return_value = _compliance_response("REVIEW_REQUIRED")
        ship = {"shipment_id": "S-HR", "origin": "A", "destination": "B",
                "weight_kg": 100, "declared_value": 50000, "shipping_cost": 200}
        case = run(orchestrator.ingest_shipment(ship))
        case = run(orchestrator.advance(case))
        self.assertEqual(case["state"], "SPECIALISTS_DONE")
        case = run(orchestrator.advance(case))
        self.assertEqual(case["state"], "INVESTIGATED")
        case = run(orchestrator.advance(case))
        self.assertEqual(case["state"], "ESCALATED")


class TestOrchestratorHumanDecide(unittest.TestCase):
    def setUp(self):
        self.store = _make_store()
        self.store_patcher = patch("orchestrator.get_store", return_value=self.store)
        self.store_patcher.start()
        self.patchers, self.mocks = _patch_orchestrator()

    def tearDown(self):
        _unpatch(self.patchers)
        self.store_patcher.stop()

    def _create_pending_case(self):
        import orchestrator
        case = {
            "case_id": "CASE-PENDING",
            "state": "PENDING_HUMAN",
            "shipment": {"shipment_id": "S-P"},
            "shipment_id": "S-P",
            "risk_score": 75,
            "steps": [],
            "actions": [],
            "_version": 0,
        }
        run(self.store.put_case(case))
        return case

    def test_human_release(self):
        import orchestrator
        self._create_pending_case()
        result = run(orchestrator.human_decide("CASE-PENDING", "release", "Reviewer1", "looks clean"))
        self.assertIn(result.get("state", ""),
                      ["RELEASED", "RELEASED_BY_HUMAN", "release"])

    def test_human_block(self):
        import orchestrator
        self._create_pending_case()
        result = run(orchestrator.human_decide("CASE-PENDING", "block", "Reviewer1", "suspicious"))
        self.assertIn(result.get("state", ""),
                      ["BLOCKED", "BLOCKED_BY_HUMAN", "block"])


class TestOrchestratorTokenRollup(unittest.TestCase):
    def setUp(self):
        self.store = _make_store()
        self.store_patcher = patch("orchestrator.get_store", return_value=self.store)
        self.store_patcher.start()
        self.patchers, self.mocks = _patch_orchestrator()

    def tearDown(self):
        _unpatch(self.patchers)
        self.store_patcher.stop()

    @patch("orchestrator.verifier.validate", return_value=_validation_result(risk_floor=10))
    @patch("orchestrator.verifier.reconcile", return_value={
        "effective_risk": 25, "model_risk": 25, "risk_floor": 10, "source": "agent score",
        "score_disputed": False, "auto_clear_permitted": True,
    })
    def test_token_cost_accumulated(self, mock_reconcile, mock_validate):
        import orchestrator
        ship = {"shipment_id": "S-TOK", "origin": "A", "destination": "B",
                "weight_kg": 100, "declared_value": 5000}
        case = run(orchestrator.ingest_shipment(ship))
        case = run(orchestrator.advance(case))
        self.assertGreater(case.get("_agent_calls", 0), 0)
        self.assertGreater(case.get("_input_tokens", 0), 0)
        self.assertGreater(case.get("_output_tokens", 0), 0)
        self.assertGreater(case.get("_estimated_cost_usd", 0), 0)


# ────────────────────────────────────────────────────────────────
# Tools tests
# ────────────────────────────────────────────────────────────────
class TestTools(unittest.TestCase):
    def setUp(self):
        self.store = _make_store()
        self.store_patcher = patch("tools.get_store", return_value=self.store)
        self.store_patcher.start()

    def tearDown(self):
        self.store_patcher.stop()

    def test_release_writes_audit(self):
        import tools
        result = run(tools.release_shipment("C1", "S1", "clean"))
        self.assertEqual(result["action"], "release_shipment")
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["case_id"], "C1")

    def test_hold_writes_audit(self):
        import tools
        result = run(tools.hold_shipment("C1", "S1", "suspicious"))
        self.assertEqual(result["action"], "hold_shipment")
        self.assertEqual(result["status"], "done")

    def test_draft_sar_truncates_narrative(self):
        import tools
        result = run(tools.draft_sar("C1", "S1", "x" * 3000, "100k"))
        detail = result.get("detail", {})
        if isinstance(detail, dict):
            narrative = detail.get("narrative", "")
            self.assertLessEqual(len(narrative), 2000)

    def test_draft_sar_requires_human_signoff(self):
        import tools
        result = run(tools.draft_sar("C1", "S1", "fraud", "50k"))
        detail = result.get("detail", {})
        if isinstance(detail, dict):
            self.assertTrue(detail.get("requires_human_signoff", False))

    @patch("tools.NOTIFY_WEBHOOK_URL", "")
    def test_notify_webhook_skipped_no_url(self):
        import tools
        result = run(tools.notify_webhook("C1", "Alert", "body", "HIGH"))
        self.assertEqual(result["status"], "skipped")


# ────────────────────────────────────────────────────────────────
# Agent envelope tests
# ────────────────────────────────────────────────────────────────
class TestAgentModules(unittest.TestCase):
    @patch("agents.fraud_detection_agent.nebius_client.complete_json",
           new_callable=AsyncMock,
           return_value=('{"risk_score": 25, "findings": [], "recommendations": []}', 100, 50))
    def test_fraud_agent_returns_envelope(self, mock_complete):
        from agents.fraud_detection_agent import analyze_shipment
        ship = {"shipment_id": "X", "origin": "A", "destination": "B",
                "weight_kg": 10, "declared_value": 100}
        result = run(analyze_shipment(ship))
        self.assertIn("result", result)
        self.assertIn("model", result)
        self.assertIn("latency_ms", result)

    @patch("agents.fraud_detection_agent.nebius_client.complete_json",
           new_callable=AsyncMock,
           return_value=("not valid json at all", 100, 50))
    def test_fraud_agent_handles_parse_failure(self, mock_complete):
        from agents.fraud_detection_agent import analyze_shipment
        ship = {"shipment_id": "X", "origin": "A", "destination": "B"}
        result = run(analyze_shipment(ship))
        self.assertTrue(result.get("parse_error", False))


if __name__ == "__main__":
    unittest.main()
