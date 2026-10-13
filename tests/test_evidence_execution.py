"""
Execution of an approved decision (Plan 1, step 6).
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_evidence_eval_approve import Base, tiny_pdf  # noqa: E402
from vf_logistics import evidence  # noqa: E402

REVIEWER = "reviewer@forwarder.example"


def run(coro):
    return asyncio.run(coro)


class TestExecution(Base):
    def _full_loop(self, case_id="CASE-1"):
        """request -> submit -> reevaluate -> approve -> return approval_id."""
        self.put(case_id)
        self.request_and_submit(case_id)
        run(evidence.reevaluate(case_id))
        result = run(evidence.approve(case_id, "release", REVIEWER, note="Reviewed", actor_auth="password"))
        return result["approval"]["approval_id"]

    def test_a_valid_approval_is_executed(self):
        approval_id = self._full_loop()
        with patch("vf_logistics.tools.publish_decision", new=AsyncMock(return_value={"detail": {"message_id": "msg-1"}, "status": "done"})):
            result = run(evidence.execute_approval(
                "CASE-1", approval_id, REVIEWER, actor_auth="password",
            ))
        assert result["state"] == "RELEASED_BY_HUMAN"
        assert result["message_id"] == "msg-1"
        case = self.stored()
        assert case["state"] == "RELEASED_BY_HUMAN"
        approval = case["verification"]["approvals"][0]
        assert approval["status"] == "EXECUTED"
        exe = case["verification"]["executions"][0]
        assert exe["status"] == "sent"
        assert exe["message_id"] == "msg-1"

    def test_a_block_approval_is_executed(self):
        self.put()
        self.request_and_submit()
        run(evidence.reevaluate("CASE-1"))
        result = run(evidence.approve("CASE-1", "block", REVIEWER, actor_auth="password"))
        aid = result["approval"]["approval_id"]
        with patch("vf_logistics.tools.publish_decision", new=AsyncMock(return_value={"detail": {"message_id": "msg-2"}, "status": "done"})):
            result = run(evidence.execute_approval("CASE-1", aid, REVIEWER, actor_auth="password"))
        assert result["state"] == "BLOCKED_BY_HUMAN"

    def test_a_superseded_approval_is_refused_and_recorded(self):
        approval_id = self._full_loop()
        # New evidence supersedes the approval.
        out2 = run(evidence.request_evidence("CASE-1", REVIEWER, documents=["producer_declaration"]))
        mock = {
            "agent": "evidence_extraction", "model": "test",
            "result": {"producer_name": "X", "input_origins": ["Vietnam"]},
            "latency_ms": 10, "input_tokens": 10, "output_tokens": 10,
            "parse_error": False, "at": "2026-10-12T09:00:00Z",
        }
        with patch("vf_logistics.agents.document_agent.extract_evidence", new=AsyncMock(return_value=mock)):
            with patch("vf_logistics.model_armor.screen", new=AsyncMock(return_value={"blocked": False})):
                with patch("vf_logistics.model_armor.extract_pdf_text", return_value=("text", None)):
                    with patch("vf_logistics.document_store.archive", new=AsyncMock(return_value={"archived": True, "uri": "gs://t/d"})):
                        run(evidence.receive_evidence(out2["token"], tiny_pdf(), "d.pdf", "application/pdf"))
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        assert raised.value.status == 409
        case = self.stored()
        exe = [e for e in case["verification"]["executions"] if e.get("status") == "denied"]
        assert len(exe) == 1
        assert "SUPERSEDED" in exe[0]["reason"]

    def test_without_a_password_execution_is_refused(self):
        approval_id = self._full_loop()
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="one_click"))
        assert raised.value.status == 403

    def test_a_nonexistent_approval_is_refused(self):
        self.put()
        with pytest.raises(evidence.EvidenceError):
            run(evidence.execute_approval("CASE-1", "evapr-nope", REVIEWER, actor_auth="password"))

    def test_pub_sub_is_not_called_when_the_check_fails(self):
        approval_id = self._full_loop()
        # Tamper with the case state to make it fail.
        case = self.stored()
        case["state"] = "HELD_FOR_REVIEW"
        run(self.store.put_case(case))
        mock_pub = AsyncMock()
        with patch("vf_logistics.tools.publish_decision", mock_pub):
            with pytest.raises(evidence.EvidenceError):
                run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        mock_pub.assert_not_called()

    def test_n02_publish_failure_records_send_failed(self):
        """N02: Pub/Sub returning failed must NOT record done/RELEASED."""
        approval_id = self._full_loop()
        failed_receipt = {"detail": {}, "status": "failed"}
        with patch("vf_logistics.tools.publish_decision", new=AsyncMock(return_value=failed_receipt)):
            result = run(evidence.execute_approval(
                "CASE-1", approval_id, REVIEWER, actor_auth="password",
            ))
        assert result["state"] == "EXECUTION_FAILED"
        assert result["message_id"] is None
        case = self.stored()
        assert case["state"] == "EXECUTION_FAILED"
        exe = case["verification"]["executions"][-1]
        assert exe["status"] == "send_failed"
        # Approval reverts to VALID so retry is possible.
        approval = case["verification"]["approvals"][0]
        assert approval["status"] == "VALID"

    def test_n02_retry_after_failure_succeeds(self):
        """N02: After EXECUTION_FAILED, retry with the same approval succeeds."""
        approval_id = self._full_loop()
        failed_receipt = {"detail": {}, "status": "failed"}
        with patch("vf_logistics.tools.publish_decision", new=AsyncMock(return_value=failed_receipt)):
            run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        assert self.stored()["state"] == "EXECUTION_FAILED"
        ok_receipt = {"detail": {"message_id": "msg-retry"}, "status": "done"}
        with patch("vf_logistics.tools.publish_decision", new=AsyncMock(return_value=ok_receipt)):
            result = run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        assert result["state"] == "RELEASED_BY_HUMAN"
        assert result["message_id"] == "msg-retry"

    def test_n01_idempotency_key_is_fixed_per_approval(self):
        approval_id = self._full_loop()
        failed = AsyncMock(return_value={"detail": {}, "status": "failed"})
        with patch("vf_logistics.tools.publish_decision", new=failed):
            run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        ok = AsyncMock(return_value={"detail": {"message_id": "m"}, "status": "done"})
        with patch("vf_logistics.tools.publish_decision", new=ok):
            run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        key1 = failed.call_args.args[1]["idempotency_key"]
        key2 = ok.call_args.args[1]["idempotency_key"]
        assert key1 == key2 == f"exec-{approval_id}"

    def test_n01_executing_state_is_recoverable(self):
        approval_id = self._full_loop()
        boom = AsyncMock(side_effect=KeyboardInterrupt)
        # Simulate a crash after the claim: leave the case EXECUTING / CLAIMING.
        with patch("vf_logistics.tools.publish_decision", new=boom):
            with pytest.raises(KeyboardInterrupt):
                run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        case = self.stored()
        assert case["state"] == "EXECUTING"
        claimed = case["verification"]["executions"][0]["execution_id"]
        ok = AsyncMock(return_value={"detail": {"message_id": "m"}, "status": "done"})
        with patch("vf_logistics.tools.publish_decision", new=ok):
            result = run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        assert result["state"] == "RELEASED_BY_HUMAN"
        exes = self.stored()["verification"]["executions"]
        assert len(exes) == 1 and exes[0]["execution_id"] == claimed
