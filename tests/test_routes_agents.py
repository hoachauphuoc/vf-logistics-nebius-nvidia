"""
The direct agent routes: each takes a JSON body, refuses an empty or malformed one before any model is
called, hands the body to its agent, and bounds a batch so one request cannot become unlimited model calls.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_console_session import TEST_KEY  # noqa: E402
from test_evidence_eval_approve import Base  # noqa: E402

KEY = {"X-VF-API-Key": TEST_KEY}

# route, name of the agent function the app calls, a valid body, what that agent answers
SINGLE = [
    ("/api/v1/fraud/analyze", "analyze_shipment", {"shipment_id": "S-1"}, {"risk_score": 12}),
    ("/api/v1/compliance/screen", "screen_shipment", {"shipment_id": "S-1"}, {"status": "CLEARED"}),
    ("/api/v1/compliance/entity", "screen_entity", {"name": "Saigon Plywood"}, {"status": "CLEARED"}),
    ("/api/v1/investigation/case", "investigate_case", {"case_id": "C-1"}, {"narrative": "n"}),
]


class RouteBase(Base):
    def setup_method(self):
        super().setup_method()
        from vf_logistics import app as app_mod

        self.app_mod = app_mod
        self.limiter_was = app_mod.limiter.enabled
        app_mod.limiter.enabled = False
        self.client = app_mod.app.test_client()

    def teardown_method(self):
        self.app_mod.limiter.enabled = self.limiter_was
        super().teardown_method()

    def post(self, route, body, agent, answer=None, error=None):
        mock = AsyncMock(side_effect=error) if error else AsyncMock(return_value=answer)
        with patch.object(self.app_mod, agent, new=mock):
            return self.client.post(route, json=body, headers=KEY), mock


@pytest.mark.parametrize("route,agent,body,answer", SINGLE)
class TestTheSingleItemAgents:
    def test_the_body_goes_to_the_agent_and_its_answer_comes_back(self, route, agent, body, answer):
        case = RouteBase()
        case.setup_method()
        try:
            response, mock = case.post(route, body, agent, answer)
            assert (response.status_code, response.get_json()) == (200, answer)
            mock.assert_called_once_with(body)
        finally:
            case.teardown_method()

    def test_an_empty_body_is_400_and_no_model_is_called(self, route, agent, body, answer):
        case = RouteBase()
        case.setup_method()
        try:
            response, mock = case.post(route, {}, agent, answer)
            assert response.status_code == 400
            assert "No data provided" in response.get_json()["error"]
            mock.assert_not_called()
        finally:
            case.teardown_method()

    def test_an_agent_that_raises_is_a_500(self, route, agent, body, answer):
        case = RouteBase()
        case.setup_method()
        try:
            response, _ = case.post(route, body, agent, error=RuntimeError("model down"))
            assert response.status_code == 500
        finally:
            case.teardown_method()

    def test_an_anonymous_caller_is_refused(self, route, agent, body, answer):
        case = RouteBase()
        case.setup_method()
        try:
            assert case.client.post(route, json=body).status_code in (401, 403)
        finally:
            case.teardown_method()


class TestTheBatchRoutes(RouteBase):
    def test_a_fraud_batch_is_analysed_and_counted(self):
        results = [{"risk_score": 1}, {"risk_score": 2}]
        response, mock = self.post("/api/v1/fraud/batch", {"shipments": [{"a": 1}, {"b": 2}]}, "batch_analyze", results)
        assert (response.status_code, response.get_json()) == (200, {"results": results, "count": 2})
        mock.assert_called_once_with([{"a": 1}, {"b": 2}])

    def test_a_fraud_batch_needs_its_list(self):
        for body in ({}, {"other": 1}):
            response, mock = self.post("/api/v1/fraud/batch", body, "batch_analyze", [])
            assert response.status_code == 400
            assert "No shipments provided" in response.get_json()["error"]
            mock.assert_not_called()

    def test_a_batch_that_is_not_a_list_is_refused_and_says_what_it_received(self):
        response, mock = self.post("/api/v1/fraud/batch", {"shipments": "nope"}, "batch_analyze", [])
        body = response.get_json()
        assert response.status_code == 400
        assert (body["error"], body["received"]) == ("'shipments' must be a list", "str")
        mock.assert_not_called()

    def test_a_batch_over_the_ceiling_is_refused_before_any_model_call(self):
        too_many = [{"i": i} for i in range(self.app_mod.MAX_BATCH_ITEMS + 1)]
        response, mock = self.post("/api/v1/fraud/batch", {"shipments": too_many}, "batch_analyze", [])
        assert response.status_code == 413
        mock.assert_not_called()

    def test_a_batch_exactly_at_the_ceiling_is_accepted(self):
        at_limit = [{"i": i} for i in range(self.app_mod.MAX_BATCH_ITEMS)]
        response, mock = self.post("/api/v1/fraud/batch", {"shipments": at_limit}, "batch_analyze", [])
        assert response.status_code == 200
        mock.assert_called_once()

    def test_the_investigation_report_takes_its_list_and_bounds_it_the_same_way(self):
        response, mock = self.post("/api/v1/investigation/report", {"investigations": [{"id": 1}]}, "generate_report", {"report": "r"})
        assert (response.status_code, response.get_json()) == (200, {"report": "r"})
        mock.assert_called_once_with([{"id": 1}])
        refused, none = self.post("/api/v1/investigation/report", {"investigations": "x"}, "generate_report", {})
        assert refused.status_code == 400
        none.assert_not_called()

    def test_the_investigation_report_needs_investigations(self):
        response, mock = self.post("/api/v1/investigation/report", {"other": 1}, "generate_report", {})
        assert response.status_code == 400
        assert "No investigations provided" in response.get_json()["error"]
        mock.assert_not_called()
