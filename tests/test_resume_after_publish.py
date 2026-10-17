"""
A resume after a publish that was accepted but never confirmed (N01): the lease has
run out, the same execution continues, and the decision is not published a second time.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_evidence_eval_approve import Base  # noqa: E402
from test_evidence_execution import _fake_pubsub, _with_pubsub  # noqa: E402
from vf_logistics import evidence, tools  # noqa: E402

REVIEWER = "reviewer@forwarder.example"


def run(coro):
    return asyncio.run(coro)


class TestAResumeAfterAnAcceptedPublish(Base):
    def test_the_resume_does_not_publish_the_decision_again(self):
        self.put()
        self.request_and_submit()
        run(evidence.reevaluate("CASE-1"))
        approval_id = run(evidence.approve(
            "CASE-1", "release", REVIEWER, note="Reviewed", actor_auth="password",
        ))["approval"]["approval_id"]
        pubsub, published = _fake_pubsub(["msg-1", "msg-2"])
        real_publish = tools.publish_decision

        async def publish_then_die(*args, **kwargs):
            await real_publish(*args, **kwargs)
            raise asyncio.CancelledError

        env = {"PROJECT_ID": "test-project"}
        # First attempt: the claim is written, the publish is accepted, and the process
        # dies before the outcome is confirmed.
        with patch.dict(os.environ, env), _with_pubsub(pubsub):
            with patch("vf_logistics.tools.publish_decision", new=publish_then_die), \
                    pytest.raises(asyncio.CancelledError):
                run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        assert len(published) == 1
        assert self.stored()["state"] == "EXECUTING"

        case = self.stored()
        case["verification"]["executions"][0]["claim_expires_epoch"] = time.time() - 1
        run(self.store.put_case(case))

        with patch.dict(os.environ, env), _with_pubsub(pubsub):
            result = run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        assert result["state"] == "RELEASED_BY_HUMAN"
        assert result["message_id"] == "msg-1"
        assert len(published) == 1
        stored = self.stored()
        assert [e["status"] for e in stored["verification"]["executions"]] == ["sent"]
        assert stored["verification"]["executions"][0]["message_id"] == "msg-1"
        assert stored["verification"]["approvals"][0]["status"] == "EXECUTED"


class TestARecordThatFailsToSaveAfterTheBrokerAccepted(Base):
    def test_the_message_id_is_kept_and_the_decision_is_sent_once(self):
        self.put()
        self.request_and_submit()
        run(evidence.reevaluate("CASE-1"))
        approval_id = run(evidence.approve(
            "CASE-1", "release", REVIEWER, note="Reviewed", actor_auth="password",
        ))["approval"]["approval_id"]
        pubsub, published = _fake_pubsub(["msg-1", "msg-2"])
        real_audit = tools._audit
        refused: list[str] = []

        async def store_down_once(case_id, action, detail, status="done", tenant_id=None):
            # The first save of the publish record fails after the broker accepted the message.
            if action == "publish_decision" and not refused:
                refused.append(action)
                raise RuntimeError("ServiceUnavailable: the store did not answer")
            return await real_audit(case_id, action, detail, status, tenant_id)

        with patch.dict(os.environ, {"PROJECT_ID": "test-project"}), _with_pubsub(pubsub), \
                patch("vf_logistics.tools._audit", new=store_down_once):
            result = run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))

        assert result["state"] == "RELEASED_BY_HUMAN"
        assert result["message_id"] == "msg-1"
        assert len(published) == 1
        stored = self.stored()
        assert [e["status"] for e in stored["verification"]["executions"]] == ["sent"]
        assert stored["verification"]["executions"][0]["message_id"] == "msg-1"
        rows = [r for r in run(self.store.list_audit(limit=500)) if r.get("action") == "publish_decision"]
        assert [(r["status"], r["detail"]["message_id"]) for r in rows] == [("done", "msg-1")]


class TestARecordThatFailsToSaveTwiceAfterTheBrokerAccepted(Base):
    def test_the_execution_is_recorded_as_sent_with_the_message_id(self):
        self.put()
        self.request_and_submit()
        run(evidence.reevaluate("CASE-1"))
        approval_id = run(evidence.approve(
            "CASE-1", "release", REVIEWER, note="Reviewed", actor_auth="password",
        ))["approval"]["approval_id"]
        pubsub, published = _fake_pubsub(["msg-1", "msg-2"])
        real_audit = tools._audit

        async def store_down_for_publish(case_id, action, detail, status="done", tenant_id=None):
            # Both saves of the publish record fail; the broker has the message (N01).
            if action == "publish_decision":
                raise RuntimeError("ServiceUnavailable: the store did not answer")
            return await real_audit(case_id, action, detail, status, tenant_id)

        with patch.dict(os.environ, {"PROJECT_ID": "test-project"}), _with_pubsub(pubsub), \
                patch("vf_logistics.tools._audit", new=store_down_for_publish):
            result = run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))

        assert result["state"] == "RELEASED_BY_HUMAN"
        assert result["message_id"] == "msg-1"
        assert len(published) == 1
        stored = self.stored()
        assert [e["status"] for e in stored["verification"]["executions"]] == ["sent"]
        assert stored["verification"]["executions"][0]["message_id"] == "msg-1"

    def test_a_record_that_cannot_be_saved_for_a_message_that_never_went_out_still_raises(self):
        # Nothing went out, so there is no message id to hand back: the error goes on and
        # the caller records a failed send.
        class ServiceUnavailable(Exception):
            pass

        pubsub, _ = _fake_pubsub([ServiceUnavailable("503 Service Unavailable")])

        async def store_down(*args, **kwargs):
            raise RuntimeError("the store did not answer")

        with patch.dict(os.environ, {"PROJECT_ID": "test-project"}), _with_pubsub(pubsub), \
                patch("vf_logistics.tools._audit", new=store_down), \
                pytest.raises(RuntimeError, match="store did not answer"):
            run(tools.publish_decision("CASE-1", {"outcome": "RELEASED_BY_HUMAN", "idempotency_key": "exec-apr-9"}))


class TestACancellationAroundThePublish(Base):
    def test_a_cancellation_after_the_broker_accepted_keeps_the_message_id_for_the_resume(self):
        self.put()
        self.request_and_submit()
        run(evidence.reevaluate("CASE-1"))
        approval_id = run(evidence.approve(
            "CASE-1", "release", REVIEWER, note="Reviewed", actor_auth="password",
        ))["approval"]["approval_id"]
        pubsub, published = _fake_pubsub(["msg-1", "msg-2"])
        real_audit = tools._audit
        cancelled: list[str] = []

        async def cancelled_while_saving(case_id, action, detail, status="done", tenant_id=None):
            # The task is cancelled while it saves the publish record, after the broker accepted.
            if action == "publish_decision" and not cancelled:
                cancelled.append(action)
                raise asyncio.CancelledError
            return await real_audit(case_id, action, detail, status, tenant_id)

        env = {"PROJECT_ID": "test-project"}
        with patch.dict(os.environ, env), _with_pubsub(pubsub), \
                patch("vf_logistics.tools._audit", new=cancelled_while_saving), \
                pytest.raises(asyncio.CancelledError):
            run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        assert len(published) == 1
        assert self.stored()["state"] == "EXECUTING"
        rows = [r for r in run(self.store.list_audit(limit=500)) if r.get("action") == "publish_decision"]
        assert [(r["status"], r["detail"]["message_id"]) for r in rows] == [("done", "msg-1")]

        case = self.stored()
        case["verification"]["executions"][0]["claim_expires_epoch"] = time.time() - 1
        run(self.store.put_case(case))

        with patch.dict(os.environ, env), _with_pubsub(pubsub):
            result = run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        assert result["state"] == "RELEASED_BY_HUMAN"
        assert result["message_id"] == "msg-1"
        assert len(published) == 1

    def test_a_cancellation_before_the_broker_answered_is_recorded_as_unknown(self):
        pubsub, _ = _fake_pubsub(["msg-1"])

        async def cancelled_while_waiting(*args, **kwargs):
            raise asyncio.CancelledError

        with patch.dict(os.environ, {"PROJECT_ID": "test-project"}), _with_pubsub(pubsub), \
                patch("asyncio.to_thread", new=cancelled_while_waiting), \
                pytest.raises(asyncio.CancelledError):
            run(tools.publish_decision("CASE-1", {"outcome": "RELEASED_BY_HUMAN", "idempotency_key": "exec-apr-7"}))
        rows = [r for r in run(self.store.list_audit(limit=500)) if r.get("action") == "publish_decision"]
        assert [r["status"] for r in rows] == ["unknown"]
        assert rows[0]["detail"]["error"].startswith("CancelledError")
        assert rows[0]["detail"]["idempotency_key"] == "exec-apr-7"

    def test_the_cancellation_still_reaches_the_caller_when_the_store_is_down_too(self):
        pubsub, _ = _fake_pubsub(["msg-1"])

        async def cancelled_while_waiting(*args, **kwargs):
            raise asyncio.CancelledError

        async def store_down(*args, **kwargs):
            raise RuntimeError("the store did not answer")

        with patch.dict(os.environ, {"PROJECT_ID": "test-project"}), _with_pubsub(pubsub), \
                patch("asyncio.to_thread", new=cancelled_while_waiting), \
                patch("vf_logistics.tools._audit", new=store_down), \
                pytest.raises(asyncio.CancelledError):
            run(tools.publish_decision("CASE-1", {"outcome": "RELEASED_BY_HUMAN", "idempotency_key": "exec-apr-6"}))

