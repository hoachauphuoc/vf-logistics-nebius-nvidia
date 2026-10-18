"""
The fault module of the separate service vf-app-faulttest (review 2026-10-18, open items 1 and 2):
it refuses to load anywhere it was not asked for, ends the worker only at the record of a publish
the broker accepted, and holds back only a finished Execute.
"""

from __future__ import annotations

import asyncio
import importlib
import sys

import pytest
from werkzeug.test import Client

from vf_logistics import tools

MODULE = "vf_logistics.faulttest"


def load(monkeypatch, tmp_path, **env):
    # tools._audit is replaced by the kill fault; this restores it after the test.
    monkeypatch.setattr(tools, "_audit", tools._audit)
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.setenv("FAULT_MARKER", str(tmp_path / "fired"))
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    sys.modules.pop(MODULE, None)
    return importlib.import_module(MODULE)


class TestItRefusesToLoad:
    def test_without_fault_test_allowed(self, monkeypatch, tmp_path):
        monkeypatch.delenv("FAULT_TEST_ALLOWED", raising=False)
        with pytest.raises(RuntimeError, match="FAULT_TEST_ALLOWED"):
            load(monkeypatch, tmp_path, FAULT="kill_after_publish")

    def test_on_the_production_service(self, monkeypatch, tmp_path):
        with pytest.raises(RuntimeError, match="vf-app"):
            load(monkeypatch, tmp_path, FAULT_TEST_ALLOWED="true", FAULT="kill_after_publish", K_SERVICE="vf-app")

    def test_with_an_unknown_fault(self, monkeypatch, tmp_path):
        with pytest.raises(RuntimeError, match="FAULT must be one of"):
            load(monkeypatch, tmp_path, FAULT_TEST_ALLOWED="true", FAULT="something_else")


class Exited(BaseException):
    pass


class TestKillAfterPublish:
    @pytest.fixture
    def fault(self, monkeypatch, tmp_path):
        module = load(monkeypatch, tmp_path, FAULT_TEST_ALLOWED="true", FAULT="kill_after_publish")
        codes: list[int] = []
        saved: list[str] = []

        def fake_exit(code):
            codes.append(code)
            raise Exited()

        async def recorded(case_id, action, detail, status="done", tenant_id=None):
            saved.append(action)
            return {"action": action}

        monkeypatch.setattr(module.os, "_exit", fake_exit)
        monkeypatch.setattr(module, "real_audit", recorded)
        return module, codes, saved, tmp_path / "fired"

    def test_the_worker_ends_at_the_record_of_an_accepted_publish(self, fault):
        _, codes, saved, marker = fault
        with pytest.raises(Exited):
            asyncio.run(tools._audit("CASE-1", "publish_decision", {"message_id": "m-1"}))
        assert codes == [17]
        assert saved == []
        assert marker.exists()

    def test_any_other_record_is_saved(self, fault):
        _, codes, saved, _ = fault
        asyncio.run(tools._audit("CASE-1", "release_shipment", {"shipment_id": "S-1"}))
        assert (codes, saved) == ([], ["release_shipment"])

    def test_a_publish_with_no_message_id_is_saved(self, fault):
        _, codes, saved, _ = fault
        asyncio.run(tools._audit("CASE-1", "publish_decision", {"error": "timeout"}, status="unknown"))
        assert (codes, saved) == ([], ["publish_decision"])

    def test_a_record_the_sent_ledger_writes_is_saved(self, fault):
        _, codes, saved, _ = fault
        asyncio.run(tools._audit("CASE-1", "publish_decision", {"message_id": "m-1", "via": "sent ledger"}))
        assert (codes, saved) == ([], ["publish_decision"])

    def test_it_fires_once(self, fault):
        _, codes, saved, _ = fault
        with pytest.raises(Exited):
            asyncio.run(tools._audit("CASE-1", "publish_decision", {"message_id": "m-1"}))
        asyncio.run(tools._audit("CASE-1", "publish_decision", {"message_id": "m-2"}))
        assert (codes, saved) == ([17], ["publish_decision"])


class TestSlowAfterExecute:
    @pytest.fixture
    def fault(self, monkeypatch, tmp_path):
        module = load(monkeypatch, tmp_path, FAULT_TEST_ALLOWED="true", FAULT="slow_after_execute", FAULT_SLOW_SECONDS="7")
        slept: list[float] = []
        monkeypatch.setattr(module.time, "sleep", slept.append)
        return module, slept

    def test_a_finished_execute_is_held_back(self, fault):
        module, slept = fault
        response = Client(module.app).post("/api/v1/review/CASE-1/execute", json={})
        assert response.status_code >= 200
        assert slept == [7.0]

    def test_other_requests_are_not(self, fault):
        module, slept = fault
        Client(module.app).get("/health")
        Client(module.app).post("/api/v1/review/CASE-1/approve", json={})
        assert slept == []

    def test_the_answer_is_the_apps_own(self, fault):
        module, _ = fault
        from vf_logistics.app import app as flask_app

        wrapped = Client(module.app).get("/health")
        direct = Client(flask_app).get("/health")
        assert wrapped.status_code == direct.status_code == 200
        assert wrapped.get_json()["status"] == direct.get_json()["status"]
