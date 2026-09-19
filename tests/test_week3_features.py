"""Tests for Week 3-4 features: auto-debate, learning loop, Tavily integration."""
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
import asyncio


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestShipperFeedbackLoop(unittest.TestCase):
    """Test the human feedback learning loop in orchestrator."""

    def setUp(self):
        from vf_logistics import orchestrator
        orchestrator._SHIPPER_FEEDBACK.clear()

    def test_initial_feedback_empty(self):
        from vf_logistics.orchestrator import get_shipper_feedback
        self.assertIsNone(get_shipper_feedback("Unknown Corp"))

    def test_release_increments(self):
        from vf_logistics.orchestrator import _update_shipper_feedback, get_shipper_feedback
        store = MagicMock()
        _update_shipper_feedback(store, "ACME Corp", "release")
        _update_shipper_feedback(store, "ACME Corp", "release")
        fb = get_shipper_feedback("ACME Corp")
        self.assertEqual(fb["released"], 2)
        self.assertEqual(fb["blocked"], 0)
        self.assertAlmostEqual(fb["clearance_rate"], 1.0)

    def test_block_increments(self):
        from vf_logistics.orchestrator import _update_shipper_feedback, get_shipper_feedback
        store = MagicMock()
        _update_shipper_feedback(store, "Bad Corp", "block")
        _update_shipper_feedback(store, "Bad Corp", "block")
        fb = get_shipper_feedback("Bad Corp")
        self.assertEqual(fb["blocked"], 2)
        self.assertAlmostEqual(fb["clearance_rate"], 0.0)

    def test_mixed_rate(self):
        from vf_logistics.orchestrator import _update_shipper_feedback, get_shipper_feedback
        store = MagicMock()
        for _ in range(3):
            _update_shipper_feedback(store, "Mixed Corp", "release")
        _update_shipper_feedback(store, "Mixed Corp", "block")
        fb = get_shipper_feedback("Mixed Corp")
        self.assertAlmostEqual(fb["clearance_rate"], 0.75)

    def test_risk_adjustment_trusted(self):
        from vf_logistics.orchestrator import _update_shipper_feedback, shipper_risk_adjustment
        store = MagicMock()
        for _ in range(5):
            _update_shipper_feedback(store, "Trusted Corp", "release")
        self.assertEqual(shipper_risk_adjustment("Trusted Corp"), -10)

    def test_risk_adjustment_risky(self):
        from vf_logistics.orchestrator import _update_shipper_feedback, shipper_risk_adjustment
        store = MagicMock()
        _update_shipper_feedback(store, "Risky Corp", "block")
        _update_shipper_feedback(store, "Risky Corp", "block")
        self.assertEqual(shipper_risk_adjustment("Risky Corp"), 15)

    def test_risk_adjustment_neutral(self):
        from vf_logistics.orchestrator import shipper_risk_adjustment
        self.assertEqual(shipper_risk_adjustment("Unknown Corp"), 0)

    def test_case_insensitive(self):
        from vf_logistics.orchestrator import _update_shipper_feedback, get_shipper_feedback
        store = MagicMock()
        _update_shipper_feedback(store, "ACME Corp", "release")
        _update_shipper_feedback(store, "acme corp", "release")
        fb = get_shipper_feedback("Acme Corp")
        self.assertEqual(fb["released"], 2)

    def test_empty_name_ignored(self):
        from vf_logistics.orchestrator import _update_shipper_feedback, get_shipper_feedback
        store = MagicMock()
        _update_shipper_feedback(store, "", "release")
        self.assertIsNone(get_shipper_feedback(""))


class TestTavilyInvestigationEnrichment(unittest.TestCase):
    """Test that investigation agent uses Tavily."""

    @patch("vf_logistics.agents.investigation_agent.nebius_client")
    @patch("vf_logistics.agents.investigation_agent.tavily_client")
    def test_tavily_called_with_trigger(self, mock_tavily, mock_nebius):
        from vf_logistics.agents.investigation_agent import investigate_case

        mock_tavily.search = AsyncMock(return_value=[
            {"title": "Fraud scheme", "url": "https://example.com", "content": "shell company detected"}
        ])
        mock_tavily.format_findings = MagicMock(return_value="External findings here")
        mock_nebius.complete_json = AsyncMock(return_value=(
            '{"summary":"test","evidence":[],"fraud_pattern":"shell company"}',
            100, 50
        ))

        case = {
            "case_id": "TEST-001",
            "trigger_reason": "under-invoicing pattern",
            "risk_score": 80,
            "primary_shipment": {"shipper_name": "Shell Corp", "receiver_name": "Buyer Inc"},
        }
        result = _run(investigate_case(case))
        self.assertTrue(mock_tavily.search.called)
        self.assertTrue(result.get("external_search_used"))

    @patch("vf_logistics.agents.investigation_agent.nebius_client")
    @patch("vf_logistics.agents.investigation_agent.tavily_client")
    def test_tavily_graceful_on_no_results(self, mock_tavily, mock_nebius):
        from vf_logistics.agents.investigation_agent import investigate_case

        mock_tavily.search = AsyncMock(return_value=[])
        mock_tavily.format_findings = MagicMock(return_value="")
        mock_nebius.complete_json = AsyncMock(return_value=(
            '{"summary":"test","evidence":[]}', 100, 50
        ))

        case = {"case_id": "TEST-002", "primary_shipment": {}}
        result = _run(investigate_case(case))
        self.assertFalse(result.get("external_search_used"))


class TestGovernanceTavilyScanRoute(unittest.TestCase):
    """Test the governance Tavily scan endpoint exists."""

    def test_tavily_scan_endpoint_registered(self):
        from vf_logistics.app import app
        rules = [rule.rule for rule in app.url_map.iter_rules()]
        self.assertIn("/api/v1/governance/tavily-scan", rules)

    def test_drift_endpoint_registered(self):
        from vf_logistics.app import app
        rules = [rule.rule for rule in app.url_map.iter_rules()]
        self.assertIn("/api/v1/governance/drift", rules)


if __name__ == "__main__":
    unittest.main()
