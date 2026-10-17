"""
A decision is published once per idempotency key (N01). A retry after an interrupted
execution must not publish it again when the first publish was accepted.
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
from test_evidence_eval_approve import Base  # noqa: E402
from test_evidence_execution import _fake_pubsub, _with_pubsub  # noqa: E402
from vf_logistics import tools  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class TestAnEarlierPublishIsNotRepeated(Base):
    KEY = "exec-apr-1"

    def _publish(self, pubsub, case_id="CASE-1", key=KEY):
        decision = {"outcome": "RELEASED_BY_HUMAN"}
        if key:
            decision["idempotency_key"] = key
        with patch.dict(os.environ, {"PROJECT_ID": "test-project"}), _with_pubsub(pubsub):
            return run(tools.publish_decision(case_id, decision))

    def test_a_second_publish_with_the_same_key_returns_the_first_receipt(self):
        pubsub, published = _fake_pubsub(["msg-1", "msg-2"])
        first = self._publish(pubsub)
        second = self._publish(pubsub)
        assert len(published) == 1
        assert second["audit_id"] == first["audit_id"]
        assert second["status"] == "done"
        assert second["detail"]["message_id"] == "msg-1"

    def test_a_publish_that_failed_is_sent_again(self):
        pubsub, published = _fake_pubsub([TimeoutError("deadline exceeded"), "msg-2"])
        first = self._publish(pubsub)
        assert first["status"] == "failed"
        second = self._publish(pubsub)
        assert second["status"] == "done"
        assert second["detail"]["message_id"] == "msg-2"
        assert len(published) == 2

    def test_another_key_or_another_case_is_sent(self):
        pubsub, published = _fake_pubsub(["msg-1", "msg-2", "msg-3"])
        self._publish(pubsub)
        self._publish(pubsub, key="exec-apr-2")
        self._publish(pubsub, case_id="CASE-2")
        assert len(published) == 3

    def test_a_decision_without_a_key_is_always_sent(self):
        pubsub, published = _fake_pubsub(["msg-1", "msg-2"])
        self._publish(pubsub, key=None)
        self._publish(pubsub, key=None)
        assert len(published) == 2
