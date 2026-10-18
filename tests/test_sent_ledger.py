"""
The sent ledger (N01): a retry reads the decisions the broker accepted before it sends
again, so a decision whose own record was never saved is not published a second time.
An unreadable ledger sends nothing: the outcome stays unknown and the retry can come
later (fail closed). The first attempt never reads it.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_evidence_eval_approve import REVIEWER, Base  # noqa: E402
from test_evidence_execution import _fake_pubsub, _with_pubsub  # noqa: E402
from vf_logistics import evidence, tools  # noqa: E402

KEY = "exec-apr-1"
DECISION = {"outcome": "RELEASED_BY_HUMAN", "idempotency_key": KEY}
ENV = {"PROJECT_ID": "test-project"}


def run(coro):
    return asyncio.run(coro)


def _ledger(module, batches):
    """Give the fake pubsub module a SubscriberClient whose pull() answers `batches` in turn, then nothing."""
    acked: list[str] = []
    queue = list(batches)

    def pull(subscription, max_messages, timeout):
        if queue:
            outcome = queue.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return SimpleNamespace(received_messages=outcome)
        return SimpleNamespace(received_messages=[])

    client = MagicMock()
    client.subscription_path.side_effect = lambda project, name: f"projects/{project}/subscriptions/{name}"
    client.pull.side_effect = pull
    client.acknowledge.side_effect = lambda subscription, ack_ids: acked.extend(ack_ids)
    module.SubscriberClient.return_value = client
    return acked


def _received(case_id, key, message_id, tenant="", ack_id="ack-1"):
    body = {"case_id": case_id, "outcome": "RELEASED_BY_HUMAN", "idempotency_key": key, "at": "2026-10-18T00:00:00Z"}
    attributes = {"idempotency_key": key, **({"tenant_id": tenant} if tenant else {})}
    message = SimpleNamespace(data=json.dumps(body).encode(), attributes=attributes, message_id=message_id)
    return SimpleNamespace(ack_id=ack_id, message=message)


class TestARetryReadsTheSentLedger(Base):
    def _publish(self, pubsub, after_attempt=True):
        with patch.dict(os.environ, ENV), _with_pubsub(pubsub), \
                patch.object(tools, "SENT_LEDGER_SUBSCRIPTION", "decisions-sent"):
            return run(tools.publish_decision("CASE-1", dict(DECISION), after_attempt=after_attempt))

    def test_a_decision_found_in_the_ledger_is_not_sent_again(self):
        pubsub, published = _fake_pubsub(["msg-2"])
        acked = _ledger(pubsub, [[_received("CASE-1", KEY, "msg-1")]])
        receipt = self._publish(pubsub)
        assert published == []
        assert receipt["status"] == "done"
        assert receipt["detail"]["message_id"] == "msg-1"
        assert receipt["detail"]["via"] == "sent ledger"
        assert acked == ["ack-1"]

    def test_a_decision_not_in_the_ledger_is_sent(self):
        pubsub, published = _fake_pubsub(["msg-2"])
        _ledger(pubsub, [])
        receipt = self._publish(pubsub)
        assert len(published) == 1
        assert receipt["detail"]["message_id"] == "msg-2"

    def test_an_unreadable_ledger_sends_nothing_and_leaves_the_outcome_unknown(self):
        pubsub, published = _fake_pubsub(["msg-2"])
        _ledger(pubsub, [RuntimeError("503 the ledger did not answer")])
        receipt = self._publish(pubsub)
        assert published == []
        assert receipt["status"] == "unknown"
        assert "sent ledger unreadable" in receipt["detail"]["error"]

    def test_a_first_attempt_does_not_read_the_ledger(self):
        pubsub, published = _fake_pubsub(["msg-2"])
        _ledger(pubsub, [RuntimeError("must not be read")])
        receipt = self._publish(pubsub, after_attempt=False)
        assert receipt["detail"]["message_id"] == "msg-2"
        assert pubsub.SubscriberClient.return_value.pull.call_count == 0

    def test_another_decision_in_the_ledger_is_recorded_in_its_own_tenant(self):
        pubsub, published = _fake_pubsub(["msg-2"])
        acked = _ledger(pubsub, [[_received("CASE-9", "exec-apr-9", "msg-9", tenant="acme", ack_id="ack-9")]])
        receipt = self._publish(pubsub)
        assert receipt["detail"]["message_id"] == "msg-2"  # ours was not in the ledger: sent
        assert run(tools._earlier_publish("CASE-9", "exec-apr-9", "acme"))["detail"]["message_id"] == "msg-9"
        assert run(tools._earlier_publish("CASE-9", "exec-apr-9", None)) is None
        assert acked == ["ack-9"]

    def test_the_tenant_travels_as_a_message_attribute(self):
        pubsub, published = _fake_pubsub(["msg-1"])
        with patch.dict(os.environ, ENV), _with_pubsub(pubsub):
            run(tools.publish_decision("CASE-1", dict(DECISION), tenant_id="acme", after_attempt=False))
        assert published[0]["attributes"] == {"idempotency_key": KEY, "tenant_id": "acme"}


class TestAResumeAfterAHardKill(Base):
    def _interrupted(self):
        self.put()
        self.request_and_submit()
        run(evidence.reevaluate("CASE-1"))
        approval_id = run(evidence.approve(
            "CASE-1", "release", REVIEWER, note="Reviewed", actor_auth="password",
        ))["approval"]["approval_id"]

        async def killed(*args, **kwargs):
            # Stands in for a process killed after the broker accepted: nothing is recorded.
            raise asyncio.CancelledError

        with patch("vf_logistics.tools.publish_decision", new=killed), pytest.raises(asyncio.CancelledError):
            run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        case = self.stored()
        case["verification"]["executions"][0]["claim_expires_epoch"] = time.time() - 1
        run(self.store.put_case(case))
        return approval_id

    def _resume(self, pubsub, approval_id):
        with patch.dict(os.environ, ENV), _with_pubsub(pubsub), \
                patch.object(tools, "SENT_LEDGER_SUBSCRIPTION", "decisions-sent"):
            return run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))

    def test_the_resume_is_settled_from_the_ledger_and_sends_nothing(self):
        approval_id = self._interrupted()
        pubsub, published = _fake_pubsub(["msg-2"])
        _ledger(pubsub, [[_received("CASE-1", f"exec-{approval_id}", "msg-1")]])
        result = self._resume(pubsub, approval_id)
        assert result["state"] == "RELEASED_BY_HUMAN"
        assert result["message_id"] == "msg-1"
        assert published == []

    def test_a_resume_with_an_unreadable_ledger_sends_nothing_and_can_be_retried(self):
        approval_id = self._interrupted()
        pubsub, published = _fake_pubsub(["msg-2"])
        _ledger(pubsub, [RuntimeError("503 the ledger did not answer")])
        result = self._resume(pubsub, approval_id)
        assert result["state"] == "EXECUTION_FAILED"
        assert published == []
        assert self.stored()["verification"]["executions"][0]["status"] == "send_unknown"
