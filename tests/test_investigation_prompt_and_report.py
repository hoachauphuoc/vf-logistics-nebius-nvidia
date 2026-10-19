"""
What the investigation agent puts in front of the model, and the consolidated report it asks for. Upstream
agents hand over alerts and related shipments as objects or as plain strings, so both shapes are accepted;
the lists are bounded so one noisy case cannot flood the prompt.
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics.agents import investigation_agent as agent  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class TestFormatting:
    def test_an_empty_or_non_object_shipment_or_entity_is_no_data(self):
        for value in ({}, None, "x", []):
            assert agent._format_shipment(value) == "No data"
            assert agent._format_entity(value) == "No data"

    def test_a_shipment_lists_its_fields_and_marks_the_missing_ones(self):
        text = agent._format_shipment({"shipment_id": "S-1", "shipper_name": "Saigon Plywood"})
        assert "ID: S-1" in text and "Shipper: Saigon Plywood" in text
        assert "Value: N/A USD" in text and "Status: N/A" in text

    def test_an_entity_lists_its_history(self):
        text = agent._format_entity({"name": "Ana", "transaction_count": 12, "previous_flags": 2})
        assert "Name: Ana" in text and "Total Transactions: 12" in text and "Previous Flags: 2" in text
        assert "Risk Rating: N/A" in text

    def test_no_related_shipments_says_so(self):
        assert agent._format_related_shipments([]) == "None found"

    def test_related_shipments_accept_objects_and_plain_strings_and_stop_at_ten(self):
        items = [{"shipment_id": f"S-{i}", "origin": "A", "destination": "B", "declared_value": 5} for i in range(9)]
        items += ["S-free-text", {"shipment_id": "S-eleventh"}]
        lines = agent._format_related_shipments(items).split("\n")
        assert len(lines) == 10
        assert "S-0" in lines[0] and "(5 USD)" in lines[0]
        assert lines[9] == "  - S-free-text"
        assert "S-eleventh" not in "\n".join(lines)

    def test_no_alerts_says_so(self):
        assert agent._format_alerts([]) == "No previous alerts"

    def test_alerts_accept_objects_and_plain_strings_and_stop_at_five(self):
        alerts = [{"date": "2026-01-01", "type": "hold", "description": "late docs"}, {"type": "x"}, "plain text"]
        alerts += [f"a{i}" for i in range(5)]
        lines = agent._format_alerts(alerts).split("\n")
        assert len(lines) == 5
        assert lines[0] == "  - [2026-01-01] hold: late docs"
        assert lines[1] == "  - [undated] x: "
        assert lines[2] == "  - plain text"


class TestConsolidatedReport:
    def generate(self, investigations, reply='{"executive_summary": "s"}'):
        with patch.object(agent.nebius_client, "complete_json", new=AsyncMock(return_value=(reply, 100, 40))) as model:
            return run(agent.generate_report(investigations)), model

    def test_the_cases_are_listed_for_the_model_and_counted(self):
        result, model = self.generate([
            {"case_id": "C-1", "result": {"verdict": "hold"}},
            {"case_id": "C-2", "investigation_result": {"verdict": "release"}},
            {"case_id": "C-3"},
        ])
        text = model.call_args.kwargs["user_text"]
        assert 'Case C-1: {"verdict": "hold"}' in text
        assert 'Case C-2: {"verdict": "release"}' in text
        assert "Case C-3: {}" in text
        assert result["cases_analyzed"] == 3
        assert result["agent"] == "investigation_report"
        assert (result["input_tokens"], result["output_tokens"]) == (100, 40)

    def test_a_reply_that_is_not_json_is_reported_as_a_parse_error_not_raised(self):
        result, _ = self.generate([{"case_id": "C-1"}], reply="not json at all")
        assert result["parse_error"] is True
        assert result["cases_analyzed"] == 1
