"""
A publish that timed out is "unknown", not "failed" (review VI, N01): the broker may have
accepted the message, so the retry is read as "result unknown, same key". Any other send
error stays a failed send.
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
from test_evidence_eval_approve import Base  # noqa: E402
from test_evidence_execution import _fake_pubsub, _with_pubsub  # noqa: E402
from vf_logistics import evidence, tools  # noqa: E402

REVIEWER = "reviewer@forwarder.example"
KEY = "exec-apr-9"


def run(coro):
    return asyncio.run(coro)


class TestAPublishThatTimedOut(Base):
    def _publish(self, pubsub):
        decision = {"outcome": "RELEASED_BY_HUMAN", "idempotency_key": KEY}
        with patch.dict(os.environ, {"PROJECT_ID": "test-project"}), _with_pubsub(pubsub):
            return run(tools.publish_decision("CASE-1", decision))

    def test_a_timeout_is_recorded_as_unknown_and_keeps_the_key(self):
        pubsub, _ = _fake_pubsub([TimeoutError("deadline exceeded")])
        receipt = self._publish(pubsub)
        assert receipt["status"] == "unknown"
        assert receipt["detail"]["idempotency_key"] == KEY
        assert "TimeoutError" in receipt["detail"]["error"]

    def test_any_other_error_is_still_a_failed_publish(self):
        pubsub, _ = _fake_pubsub([ConnectionError("unreachable")])
        assert self._publish(pubsub)["status"] == "failed"

    def test_an_unknown_publish_is_not_taken_as_an_earlier_send(self):
        first_pubsub, _ = _fake_pubsub([TimeoutError("deadline exceeded")])
        assert self._publish(first_pubsub)["status"] == "unknown"
        second_pubsub, published = _fake_pubsub(["msg-2"])
        second = self._publish(second_pubsub)
        assert second["status"] == "done"
        assert second["detail"]["message_id"] == "msg-2"
        assert len(published) == 1


class TestAnExecutionWhoseSendTimedOut(Base):
    def _approved(self):
        self.put()
        self.request_and_submit()
        run(evidence.reevaluate("CASE-1"))
        return run(evidence.approve(
            "CASE-1", "release", REVIEWER, note="Reviewed", actor_auth="password",
        ))["approval"]["approval_id"]

    def test_a_timed_out_send_is_unknown_and_the_retry_sends_with_the_same_key(self):
        approval_id = self._approved()
        pubsub, published = _fake_pubsub([TimeoutError("deadline exceeded"), "msg-ok"])
        with patch.dict(os.environ, {"PROJECT_ID": "test-project"}), _with_pubsub(pubsub):
            first = run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
            after_first = self.stored()
            second = run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        assert first["state"] == "EXECUTION_FAILED"
        executions = after_first["verification"]["executions"]
        assert [e["status"] for e in executions] == ["send_unknown"]
        assert "may have been accepted" in executions[0]["reason"]
        assert after_first["verification"]["approvals"][0]["status"] == "VALID"
        assert second["state"] == "RELEASED_BY_HUMAN" and second["message_id"] == "msg-ok"
        assert [p["body"]["idempotency_key"] for p in published] == [f"exec-{approval_id}"] * 2
        assert [e["status"] for e in self.stored()["verification"]["executions"]] == ["send_unknown", "sent"]

    def test_any_other_send_error_stays_a_failed_send(self):
        approval_id = self._approved()
        pubsub, _ = _fake_pubsub([ConnectionError("unreachable")])
        with patch.dict(os.environ, {"PROJECT_ID": "test-project"}), _with_pubsub(pubsub):
            result = run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        assert result["state"] == "EXECUTION_FAILED"
        assert [e["status"] for e in self.stored()["verification"]["executions"]] == ["send_failed"]
