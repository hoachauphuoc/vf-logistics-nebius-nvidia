"""
The idempotency key travels with the Pub/Sub message as an attribute (N01), so a
subscriber can drop a repeat without parsing the body.
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


class TestTheKeyIsAMessageAttribute(Base):
    def _publish(self, decision):
        pubsub, published = _fake_pubsub(["msg-1"])
        with patch.dict(os.environ, {"PROJECT_ID": "test-project"}), _with_pubsub(pubsub):
            receipt = run(tools.publish_decision("CASE-1", decision))
        return receipt, published

    def test_the_idempotency_key_is_sent_as_an_attribute(self):
        receipt, published = self._publish({"outcome": "RELEASED_BY_HUMAN", "idempotency_key": "exec-abc"})
        assert receipt["status"] == "done"
        assert published[0]["attributes"] == {"idempotency_key": "exec-abc"}
        assert published[0]["body"]["idempotency_key"] == "exec-abc"

    def test_a_decision_without_a_key_carries_no_attribute(self):
        receipt, published = self._publish({"outcome": "HELD_FOR_REVIEW"})
        assert receipt["status"] == "done"
        assert published[0]["attributes"] == {}
