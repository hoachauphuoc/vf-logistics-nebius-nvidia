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
