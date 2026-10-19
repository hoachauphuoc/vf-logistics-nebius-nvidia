"""
Operator routes that move work: the storage event sink (always acks, so Pub/Sub never retries a poison
document), the scripted simulator, the drain and tick levers, deep review, the document upload's refusals,
and the governance simulation's input checks.
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(__file__))
from test_console_session import TEST_KEY  # noqa: E402
from test_evidence_eval_approve import Base  # noqa: E402

KEY = {"X-VF-API-Key": TEST_KEY}


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


def push(payload=None, attributes=None):
    message = {}
    if payload is not None:
        message["data"] = base64.b64encode(json.dumps(payload).encode()).decode()
    if attributes:
        message["attributes"] = attributes
    return {"message": message}


class TestStorageEvent(RouteBase):
    def post(self, body, ingest=None, refusal=None):
        orchestrator = self.app_mod.orchestrator
        ingest = ingest or AsyncMock(return_value={"accepted": True, "blocked": False, "case_id": "CASE-1"})
        with patch.object(orchestrator, "ingest_from_storage", new=ingest), \
                patch.object(orchestrator, "WORKER_MODE", "poll"), \
                patch.object(self.app_mod.document_store, "ingest_refusal", return_value=refusal):
            response = self.client.post("/api/v1/events/storage", json=body, headers=KEY)
        return response, ingest

    def test_a_notification_with_no_object_is_acked_and_ignored(self):
        for body in ({}, push({"bucket": "b"}), {"message": {"data": "!!not base64!!"}}):
            response, ingest = self.post(body)
            assert response.status_code == 200
            assert response.get_json() == {"ignored": True, "reason": "no bucket/object in notification"}
            ingest.assert_not_called()

    def test_the_object_may_be_named_in_the_attributes(self):
        response, ingest = self.post(push(attributes={"bucketId": "b", "objectId": "inbox/a.pdf"}))
        assert response.status_code == 200
        assert ingest.call_args.args[:2] == ("b", "inbox/a.pdf")

    def test_an_object_the_service_may_not_ingest_is_ignored_with_the_reason(self):
        response, ingest = self.post(push({"bucket": "b", "name": "archive/a.pdf"}), refusal="service output")
        assert response.get_json() == {"ignored": True, "reason": "service output"}
        ingest.assert_not_called()

    def test_an_unsupported_type_is_ignored_and_named(self):
        response, ingest = self.post(push({"bucket": "b", "name": "inbox/a.exe"}))
        assert response.get_json() == {"ignored": True, "reason": "unsupported type: inbox/a.exe"}
        ingest.assert_not_called()

    def test_an_accepted_document_is_returned_as_ingested(self):
        response, _ = self.post(push({"bucket": "b", "name": "inbox/a.pdf"}))
        assert (response.status_code, response.get_json()["case_id"]) == (200, "CASE-1")

    def test_in_request_mode_the_case_is_run_to_a_terminal_state(self):
        orchestrator = self.app_mod.orchestrator
        self.put("CASE-1", state="INGESTED")
        finished = {"case_id": "CASE-1", "state": "AUTO_CLEARED"}
        with patch.object(orchestrator, "ingest_from_storage", new=AsyncMock(return_value={"accepted": True, "case_id": "CASE-1"})), \
                patch.object(orchestrator, "advance_until_terminal", new=AsyncMock(return_value=finished)), \
                patch.object(orchestrator, "WORKER_MODE", "ondemand"):
            response = self.client.post("/api/v1/events/storage", json=push({"bucket": "b", "name": "inbox/a.pdf"}), headers=KEY)
        assert response.get_json()["state"] == "AUTO_CLEARED"

    def test_a_crash_is_still_a_200_so_pubsub_does_not_redeliver_and_leaks_nothing(self):
        response, _ = self.post(push({"bucket": "b", "name": "inbox/a.pdf"}), ingest=AsyncMock(side_effect=RuntimeError("secret detail")))
        assert response.status_code == 200
        assert response.get_json() == {"error": "storage event failed", "acked": True}


class TestSimulate(RouteBase):
    def test_the_scripted_batch_is_injected_and_its_cases_listed(self):
        orchestrator = self.app_mod.orchestrator
        with patch.object(self.app_mod.simulator, "scripted_shipments", return_value=[{"a": 1}, {"b": 2}]), \
                patch.object(orchestrator, "ingest_shipment", new=AsyncMock(side_effect=[{"case_id": "C1"}, {"case_id": "C2"}])):
            response = self.client.post("/api/v1/simulate", headers=KEY)
        body = response.get_json()
        assert (response.status_code, body["injected"], body["case_ids"]) == (202, 2, ["C1", "C2"])

    def test_a_failure_while_injecting_is_a_500(self):
        with patch.object(self.app_mod.simulator, "scripted_shipments", side_effect=RuntimeError("x")):
            assert self.client.post("/api/v1/simulate", headers=KEY).status_code == 500


class TestDrainAndTick(RouteBase):
    def drain(self, body=None, query=""):
        with patch.object(self.app_mod.orchestrator, "drain", new=AsyncMock(return_value={"drained": 1})) as drain:
            response = self.client.post(f"/api/v1/orchestrator/drain{query}", json=body or {}, headers=KEY)
        return response, drain

    def test_the_default_is_three_cases(self):
        response, drain = self.drain()
        assert (response.status_code, response.get_json()) == (200, {"drained": 1})
        assert drain.call_args.kwargs["max_cases"] == 3

    def test_the_count_comes_from_the_body_or_the_query_and_is_kept_between_one_and_ten(self):
        assert self.drain({"cases": 7})[1].call_args.kwargs["max_cases"] == 7
        assert self.drain(query="?cases=4")[1].call_args.kwargs["max_cases"] == 4
        assert self.drain({"cases": 99})[1].call_args.kwargs["max_cases"] == 10
        assert self.drain({"cases": -2})[1].call_args.kwargs["max_cases"] == 1

    def test_a_count_that_is_not_a_number_is_the_callers_mistake_not_a_server_error(self):
        response, drain = self.drain({"cases": "lots"})
        assert response.status_code == 400
        assert "cases must be a whole number" in response.get_json()["error"]
        drain.assert_not_called()

    def test_tick_reports_how_many_cases_it_moved(self):
        with patch.object(self.app_mod.orchestrator, "tick", new=AsyncMock(return_value=2)):
            response = self.client.post("/api/v1/orchestrator/tick", headers=KEY)
        assert response.get_json() == {"advanced": 2}

    def test_a_tick_that_fails_is_a_500(self):
        with patch.object(self.app_mod.orchestrator, "tick", new=AsyncMock(side_effect=RuntimeError("x"))):
            assert self.client.post("/api/v1/orchestrator/tick", headers=KEY).status_code == 500


class TestDeepReviewRoute(RouteBase):
    def review(self, result=None, error=None):
        mock = AsyncMock(side_effect=error) if error else AsyncMock(return_value=result)
        with patch.object(self.app_mod.orchestrator, "deep_review", new=mock):
            return self.client.post("/api/v1/review/CASE-1/deep-review", headers=KEY)

    def test_a_debate_is_200(self):
        response = self.review({"ok": True, "verdict": {}})
        assert (response.status_code, response.get_json()["ok"]) == (200, True)

    def test_a_refused_debate_is_400_with_the_reason(self):
        response = self.review({"ok": False, "error": "case not found"})
        assert (response.status_code, response.get_json()["error"]) == (400, "case not found")

    def test_a_crash_is_a_500(self):
        assert self.review(error=RuntimeError("x")).status_code == 500


class TestDocumentUploadRefusals(RouteBase):
    def upload(self, name="bl.pdf", data=b"%PDF-1.4 x", env=None):
        form = {"file": (io.BytesIO(data), name)}
        with patch.dict(os.environ, env or {}):
            return self.client.post("/api/v1/events/document", data=form, content_type="multipart/form-data", headers=KEY)

    def test_no_file_is_400(self):
        response = self.client.post("/api/v1/events/document", data={}, content_type="multipart/form-data", headers=KEY)
        assert response.status_code == 400
        assert "No file provided" in response.get_json()["error"]

    def test_an_unsupported_type_is_415_and_lists_what_is_supported(self):
        response = self.upload(name="x.exe")
        assert response.status_code == 415
        assert response.get_json()["supported"]

    def test_an_empty_file_is_400(self):
        response = self.upload(data=b"")
        assert (response.status_code, response.get_json()["error"]) == (400, "Uploaded file is empty")

    def test_a_file_over_the_limit_is_413_and_names_the_limit(self):
        response = self.upload(data=b"x" * (1024 * 1024 + 1), env={"MAX_DOCUMENT_MB": "1"})
        assert response.status_code == 413
        assert "1MB" in response.get_json()["error"]

    def test_a_document_that_could_not_be_read_is_422(self):
        refused = {"accepted": False, "error": "could not read"}
        with patch.object(self.app_mod.orchestrator, "ingest_document", new=AsyncMock(return_value=refused)):
            response = self.upload()
        assert (response.status_code, response.get_json()["error"]) == (422, "could not read")


class TestGovernanceSimulationInputs(RouteBase):
    def simulate(self, body):
        return self.client.post("/api/v1/governance/simulate", json=body, headers=KEY)

    def test_permissions_must_be_a_non_empty_object(self):
        for body in ({}, {"permissions": []}, {"permissions": "x"}):
            response = self.simulate(body)
            assert response.status_code == 400
            assert "permissions must be a non-empty object" in response.get_json()["error"]

    def test_permissions_that_break_the_schema_are_422_with_the_details(self):
        response = self.simulate({"permissions": {"nonsense": True}})
        assert response.status_code == 422
        assert response.get_json()["details"]

    def test_a_sample_that_is_not_a_number_falls_back_to_forty_and_is_capped_at_200(self):
        good = self.app_mod.governance.proposed_boundary("t")
        with patch.object(self.app_mod.governance, "simulate_boundary", new=AsyncMock(return_value={"ok": 1})) as simulate:
            self.simulate({"permissions": good, "sample": "many"})
            assert simulate.call_args.kwargs["sample"] == 40
            self.simulate({"permissions": good, "sample": 5000})
            assert simulate.call_args.kwargs["sample"] == 200

    def test_a_value_error_from_the_simulation_is_400(self):
        good = self.app_mod.governance.proposed_boundary("t")
        with patch.object(self.app_mod.governance, "simulate_boundary", new=AsyncMock(side_effect=ValueError("bad action"))):
            response = self.simulate({"permissions": good})
        assert response.status_code == 400
