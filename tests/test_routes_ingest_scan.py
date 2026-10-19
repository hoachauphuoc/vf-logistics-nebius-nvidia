"""
Three more routes that spend model or search budget, whose request handling no test reached: the
shipment event sink (a bare shipment or a Pub/Sub push), the capped bulk simulator, and the Tavily scan.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(__file__))
from test_console_session import TEST_KEY  # noqa: E402
from test_evidence_eval_approve import Base  # noqa: E402

KEY = {"X-VF-API-Key": TEST_KEY}
SHIPMENT = {"shipment_id": "S-1", "shipper_name": "Saigon Plywood", "declared_value": 1000}


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


def envelope(data):
    encoded = base64.b64encode(data if isinstance(data, bytes) else json.dumps(data).encode()).decode()
    return {"message": {"data": encoded}, "subscription": "projects/p/subscriptions/s"}


class TestShipmentEventSink(RouteBase):
    def post(self, body, mode="ondemand"):
        case = {"case_id": "CASE-S-1", "state": "INGESTED", "decision": None}
        finished = {**case, "state": "AUTO_CLEARED", "decision": {"outcome": "AUTO_CLEARED"}}
        orchestrator = self.app_mod.orchestrator
        with patch.object(orchestrator, "ingest_shipment", new=AsyncMock(return_value=case)) as ingest, \
                patch.object(orchestrator, "advance_until_terminal", new=AsyncMock(return_value=finished)) as advance, \
                patch.object(orchestrator, "WORKER_MODE", mode):
            response = self.client.post("/api/v1/events/shipment", json=body, headers=KEY)
        return response, ingest, advance

    def test_a_bare_shipment_is_ingested_and_run_to_a_terminal_state(self):
        response, ingest, advance = self.post(SHIPMENT)
        assert response.status_code == 202
        assert response.get_json() == {
            "accepted": True, "case_id": "CASE-S-1", "state": "AUTO_CLEARED", "decision": {"outcome": "AUTO_CLEARED"},
        }
        assert ingest.call_args.args[0] == SHIPMENT
        advance.assert_called_once()

    def test_a_pubsub_push_is_decoded_to_the_shipment(self):
        response, ingest, _ = self.post(envelope(SHIPMENT))
        assert response.status_code == 202
        assert ingest.call_args.args[0] == SHIPMENT

    def test_push_data_that_is_not_base64_json_is_400_and_ingests_nothing(self):
        response, ingest, _ = self.post({"message": {"data": "!!not base64!!"}})
        assert response.status_code == 400
        assert "could not decode" in response.get_json()["error"]
        ingest.assert_not_called()

    def test_push_data_that_is_not_json_is_400(self):
        response, ingest, _ = self.post(envelope(b"plain text, not json"))
        assert response.status_code == 400
        ingest.assert_not_called()

    def test_an_empty_body_is_400(self):
        response, ingest, _ = self.post({})
        assert response.status_code == 400
        assert response.get_json()["error"] == "No shipment provided"
        ingest.assert_not_called()

    def test_in_poll_mode_the_worker_does_the_work_not_this_request(self):
        response, _, advance = self.post(SHIPMENT, mode="poll")
        assert response.status_code == 202
        assert response.get_json()["state"] == "INGESTED"
        advance.assert_not_called()

    def test_an_anonymous_caller_is_refused(self):
        assert self.client.post("/api/v1/events/shipment", json=SHIPMENT).status_code in (401, 403)


class TestBulkSimulator(RouteBase):
    def post(self, body=None, query="", cap="10"):
        orchestrator = self.app_mod.orchestrator
        with patch.object(orchestrator, "ingest_shipment", new=AsyncMock(return_value={"case_id": "C"})) as ingest, \
                patch.dict(os.environ, {"MAX_BULK_COUNT": cap}):
            response = self.client.post(f"/api/v1/simulate/bulk{query}", json=body or {}, headers=KEY)
        return response, ingest

    def test_the_count_is_honoured_up_to_the_cap(self):
        response, ingest = self.post({"count": 4})
        body = response.get_json()
        assert (response.status_code, body["injected"], body["requested"], body["capped_at"]) == (202, 4, 4, None)
        assert ingest.call_count == 4
        assert sum(body["profile_mix"].values()) == 4

    def test_a_request_over_the_cap_is_cut_and_says_so(self):
        response, ingest = self.post({"count": 500}, cap="6")
        body = response.get_json()
        assert (body["injected"], body["requested"], body["capped_at"]) == (6, 500, 6)
        assert ingest.call_count == 6

    def test_the_default_is_ten_and_the_count_may_come_from_the_query(self):
        assert self.post()[0].get_json()["injected"] == 10
        assert self.post(query="?count=3")[0].get_json()["injected"] == 3

    def test_zero_or_negative_is_one(self):
        assert self.post({"count": -5})[0].get_json()["injected"] == 1

    def test_each_case_is_tagged_as_coming_from_the_bulk_simulator(self):
        _, ingest = self.post({"count": 2})
        assert {call.kwargs["source"] for call in ingest.call_args_list} == {"bulk-simulator"}

    def test_a_count_that_is_not_a_number_is_the_callers_mistake_not_a_server_error(self):
        response, ingest = self.post({"count": "many"})
        assert response.status_code == 400
        assert "count must be a whole number" in response.get_json()["error"]
        ingest.assert_not_called()


class TestTavilyScan(RouteBase):
    def post(self, body, results):
        with patch("vf_logistics.tavily_client.search", new=AsyncMock(return_value=results)) as search:
            response = self.client.post("/api/v1/governance/tavily-scan", json=body, headers=KEY)
        return response, search

    def test_without_queries_the_three_default_scans_run(self):
        response, search = self.post({}, [{"title": "t", "content": "c", "url": "u"}])
        body = response.get_json()
        assert body["scan_count"] == 3
        assert search.call_count == 3
        assert body["alert_count"] == 3
        assert body["summary"] == "Scanned 3 queries, found 3 result(s)"

    def test_custom_queries_are_used_and_capped_at_five(self):
        _, search = self.post({"queries": [f"q{i}" for i in range(9)]}, [])
        assert [call.args[0] for call in search.call_args_list] == ["q0", "q1", "q2", "q3", "q4"]
        assert all(call.kwargs == {"max_results": 3} for call in search.call_args_list)

    def test_one_query_is_singular(self):
        response, _ = self.post({"queries": ["only one"]}, [])
        assert response.get_json()["summary"] == "Scanned 1 query, found 0 result(s)"

    def test_a_snippet_is_cut_to_400_characters(self):
        response, _ = self.post({"queries": ["q"]}, [{"title": "t", "content": "z" * 1000, "url": "u"}])
        assert len(response.get_json()["alerts"][0]["snippet"]) == 400

    def test_a_result_with_no_content_has_an_empty_snippet(self):
        response, _ = self.post({"queries": ["q"]}, [{"title": "t", "url": "u"}])
        assert response.get_json()["alerts"][0]["snippet"] == ""

    def test_an_anonymous_caller_is_refused(self):
        assert self.client.post("/api/v1/governance/tavily-scan", json={}).status_code in (401, 403)
