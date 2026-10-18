"""
The audit gap of N01 (review 2026-10-18) as a verifiable count, and its reconciliation
behind the operator role and a named person.
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
from test_console_session import TEST_KEY, mint  # noqa: E402
from test_publish_audit_gap import AuditGapBase  # noqa: E402

REVIEWER = "reviewer@forwarder.example"
OPERATOR = "operator@forwarder.example"


def run(coro):
    return asyncio.run(coro)


class TestTheAuditGapRoutes(AuditGapBase):
    def setup_method(self):
        super().setup_method()
        from vf_logistics import app as app_mod

        self.operators = patch.dict(os.environ, {"OPERATOR_EMAILS": OPERATOR})
        self.operators.start()
        self.app_mod = app_mod
        self.was = app_mod.limiter.enabled
        app_mod.limiter.enabled = False
        self.client = app_mod.app.test_client()

    def teardown_method(self):
        self.app_mod.limiter.enabled = self.was
        self.operators.stop()
        super().teardown_method()

    def _headers(self, email):
        return {"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint(email, amr="password")}

    def test_the_gap_count_is_readable(self):
        self.executed_with_the_audit_down()
        response = self.client.get("/api/v1/audit/unreconciled")
        assert response.status_code == 200
        body = response.get_json()
        assert body["count"] == 1
        assert body["items"][0]["message_id"] == "msg-1"

    def test_a_reviewer_may_not_reconcile(self):
        self.executed_with_the_audit_down()
        response = self.client.post("/api/v1/audit/reconcile", json={}, headers=self._headers(REVIEWER))
        assert response.status_code == 403
        assert self.client.get("/api/v1/audit/unreconciled").get_json()["count"] == 1

    def test_an_operator_reconciles_and_the_count_goes_to_zero(self):
        self.executed_with_the_audit_down()
        response = self.client.post("/api/v1/audit/reconcile", json={}, headers=self._headers(OPERATOR))
        assert response.status_code == 200
        assert response.get_json() == {"reconciled": 1, "already_recorded": 0, "failed": 0, "pending": 0}
        assert self.client.get("/api/v1/audit/unreconciled").get_json()["count"] == 0
        rows = [r for r in run(self.store.list_audit(limit=500)) if r.get("action") == "publish_decision"]
        assert [r["detail"]["reconciled_by"] for r in rows] == [OPERATOR]

    def test_the_key_alone_must_name_the_person(self):
        self.executed_with_the_audit_down()
        response = self.client.post("/api/v1/audit/reconcile", json={}, headers={"X-VF-API-Key": TEST_KEY})
        assert response.status_code == 400
        assert "named person" in response.get_json()["error"]
        assert self.client.get("/api/v1/audit/unreconciled").get_json()["count"] == 1
