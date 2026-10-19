"""
A decision the broker accepted whose publish_decision audit row could not be saved, twice
(N01, review 2026-10-18): the case completes and is not sent again, the gap stays listed,
and a reconciliation writes the missing row once.
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_evidence_eval_approve import Base, approve_open  # noqa: E402
from test_evidence_execution import _fake_pubsub, _with_pubsub  # noqa: E402
from vf_logistics import evidence, tools  # noqa: E402

REVIEWER = "reviewer@forwarder.example"
OPERATOR = "operator@forwarder.example"


def run(coro):
    return asyncio.run(coro)


class AuditGapBase(Base):
    def executed_with_the_audit_down(self):
        """Approve, then execute while every save of the publish record fails."""
        self.put()
        self.request_and_submit()
        run(evidence.reevaluate("CASE-1"))
        approval_id = run(approve_open(
            "CASE-1", "release", REVIEWER, note="Reviewed", actor_auth="password",
        ))["approval"]["approval_id"]
        pubsub, published = _fake_pubsub(["msg-1", "msg-2"])
        real_audit = tools._audit

        async def store_down_for_publish(case_id, action, detail, status="done", tenant_id=None):
            if action == "publish_decision":
                raise RuntimeError("ServiceUnavailable: the store did not answer")
            return await real_audit(case_id, action, detail, status, tenant_id)

        with patch.dict(os.environ, {"PROJECT_ID": "test-project"}), _with_pubsub(pubsub), \
                patch("vf_logistics.tools._audit", new=store_down_for_publish):
            result = run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        return approval_id, result, published

    def publish_rows(self):
        return [r for r in run(self.store.list_audit(limit=500))
                if r.get("action") == "publish_decision" and r.get("case_id") == "CASE-1"]


class TestTheGapIsKeptVisible(AuditGapBase):
    def test_an_unsaved_record_says_it_was_not_saved(self):
        async def store_down(*args, **kwargs):
            raise RuntimeError("the store did not answer")

        with patch("vf_logistics.tools._audit", new=store_down):
            receipt = run(tools._save_publish_record(
                "CASE-1", "publish_decision", {"message_id": "msg-1"}, accepted=True,
            ))
        assert receipt["audit_saved"] is False
        assert receipt["detail"]["message_id"] == "msg-1"

    def test_the_case_completes_once_and_the_execution_marks_the_missing_row(self):
        _, result, published = self.executed_with_the_audit_down()
        assert result["state"] == "RELEASED_BY_HUMAN"
        assert result["message_id"] == "msg-1"
        assert len(published) == 1
        stored = self.stored()
        execution = stored["verification"]["executions"][0]
        assert execution["message_id"] == "msg-1"
        assert execution["audit_pending"] is True
        assert stored["audit_pending"] is True
        assert self.publish_rows() == []

    def test_the_gap_is_listed_with_its_message_id(self):
        approval_id, _, _ = self.executed_with_the_audit_down()
        gaps = run(evidence.unreconciled_publish_audits())
        assert [(g["case_id"], g["approval_id"], g["message_id"]) for g in gaps] == [
            ("CASE-1", approval_id, "msg-1"),
        ]

    def test_a_case_whose_row_was_saved_is_not_listed(self):
        self.put()
        self.request_and_submit()
        run(evidence.reevaluate("CASE-1"))
        approval_id = run(approve_open(
            "CASE-1", "release", REVIEWER, note="Reviewed", actor_auth="password",
        ))["approval"]["approval_id"]
        pubsub, _ = _fake_pubsub(["msg-1"])
        with patch.dict(os.environ, {"PROJECT_ID": "test-project"}), _with_pubsub(pubsub):
            run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        assert "audit_pending" not in self.stored()["verification"]["executions"][0]
        assert run(evidence.unreconciled_publish_audits()) == []


class TestReconciliation(AuditGapBase):
    def test_reconciling_writes_the_missing_row_with_the_accepted_message_id(self):
        approval_id, _, published = self.executed_with_the_audit_down()
        out = run(evidence.reconcile_publish_audits(OPERATOR))
        assert out == {"reconciled": 1, "already_recorded": 0, "failed": 0, "pending": 0}
        rows = self.publish_rows()
        assert len(rows) == 1
        detail = rows[0]["detail"]
        assert (rows[0]["status"], detail["message_id"], detail["idempotency_key"]) == (
            "done", "msg-1", f"exec-{approval_id}",
        )
        assert detail["via"] == "audit reconciliation"
        assert detail["reconciled_by"] == OPERATOR
        stored = self.stored()
        execution = stored["verification"]["executions"][0]
        assert "audit_pending" not in execution
        assert execution["audit_reconciled_by"] == OPERATOR
        assert "audit_pending" not in stored
        assert run(evidence.unreconciled_publish_audits()) == []
        assert len(published) == 1

    def test_reconciling_twice_writes_one_row(self):
        self.executed_with_the_audit_down()
        run(evidence.reconcile_publish_audits(OPERATOR))
        again = run(evidence.reconcile_publish_audits(OPERATOR))
        assert again == {"reconciled": 0, "already_recorded": 0, "failed": 0, "pending": 0}
        assert len(self.publish_rows()) == 1

    def test_a_row_the_sent_ledger_already_saved_is_not_written_twice(self):
        approval_id, _, _ = self.executed_with_the_audit_down()
        run(tools._audit("CASE-1", "publish_decision", {
            "case_id": "CASE-1", "idempotency_key": f"exec-{approval_id}",
            "message_id": "msg-1", "via": "sent ledger",
        }))
        out = run(evidence.reconcile_publish_audits(OPERATOR))
        assert out == {"reconciled": 0, "already_recorded": 1, "failed": 0, "pending": 0}
        assert len(self.publish_rows()) == 1
        assert run(evidence.unreconciled_publish_audits()) == []

    def test_a_reconciliation_that_cannot_save_keeps_the_gap(self):
        self.executed_with_the_audit_down()

        async def store_down(*args, **kwargs):
            raise RuntimeError("the store did not answer")

        with patch("vf_logistics.tools._audit_once", new=store_down):
            out = run(evidence.reconcile_publish_audits(OPERATOR))
        assert out == {"reconciled": 0, "already_recorded": 0, "failed": 1, "pending": 1}
        assert self.stored()["verification"]["executions"][0]["audit_pending"] is True
        assert self.publish_rows() == []

    def test_a_reconciliation_needs_a_named_person(self):
        self.executed_with_the_audit_down()
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.reconcile_publish_audits(""))
        assert raised.value.status == 400
        assert "named person" in str(raised.value)
        assert self.publish_rows() == []

    def test_a_retry_after_the_gap_does_not_publish_again(self):
        approval_id, _, published = self.executed_with_the_audit_down()
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        assert raised.value.status == 409
        assert len(published) == 1
