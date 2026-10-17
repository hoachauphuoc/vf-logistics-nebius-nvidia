"""
Execution of an approved decision (Plan 1, step 6).
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_console_session import TEST_KEY  # noqa: E402
from test_evidence_eval_approve import Base, tiny_pdf  # noqa: E402
from test_origin_inputs import plywood  # noqa: E402
from vf_logistics import evidence, orchestrator  # noqa: E402

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
        with patch("vf_logistics.tools.publish_decision", new=boom), pytest.raises(KeyboardInterrupt):
            run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        case = self.stored()
        assert case["state"] == "EXECUTING"
        claimed = case["verification"]["executions"][0]["execution_id"]
        # Resuming is for a claim whose lease has run out (N01: not inside it, even for
        # the claimant, see TestN01TwoExecutesAtOnce).
        case["verification"]["executions"][0]["claim_expires_epoch"] = 0
        run(self.store.put_case(case))
        ok = AsyncMock(return_value={"detail": {"message_id": "m"}, "status": "done"})
        with patch("vf_logistics.tools.publish_decision", new=ok):
            result = run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        assert result["state"] == "RELEASED_BY_HUMAN"
        exes = self.stored()["verification"]["executions"]
        assert len(exes) == 1 and exes[0]["execution_id"] == claimed

    def test_n01_a_second_person_cannot_resume_inside_the_lease(self):
        approval_id = self._full_loop()
        boom = AsyncMock(side_effect=asyncio.CancelledError)
        with patch("vf_logistics.tools.publish_decision", new=boom), pytest.raises(asyncio.CancelledError):
            run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        assert self.stored()["state"] == "EXECUTING"
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.execute_approval("CASE-1", approval_id, "other@forwarder.example", actor_auth="password"))
        assert raised.value.status == 409

    def test_n01_a_second_person_can_resume_after_the_lease_expires(self):
        approval_id = self._full_loop()
        boom = AsyncMock(side_effect=asyncio.CancelledError)
        with patch("vf_logistics.tools.publish_decision", new=boom), pytest.raises(asyncio.CancelledError):
            run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        case = self.stored()
        case["verification"]["executions"][0]["claim_expires_epoch"] = 0
        run(self.store.put_case(case))
        ok = AsyncMock(return_value={"detail": {"message_id": "m"}, "status": "done"})
        with patch("vf_logistics.tools.publish_decision", new=ok):
            result = run(evidence.execute_approval("CASE-1", approval_id, "other@forwarder.example", actor_auth="password"))
        assert result["state"] == "RELEASED_BY_HUMAN"


OK_RECEIPT = {"detail": {"message_id": "msg-ok"}, "status": "done"}


class TestN01TwoExecutesAtOnce(Base):
    """Two callers on one approval must produce exactly one publish.

    MemoryStore never suspends, so two gathered coroutines would simply run one after
    the other and the second would be refused by approval_is_executable ("already
    EXECUTED"), which says nothing about the optimistic lock. These tests make both
    callers hold the SAME stale read (or hold the send open) so the guard under test
    is the one that matters.
    """

    def _approved(self):
        self.put()
        self.request_and_submit()
        run(evidence.reevaluate("CASE-1"))
        return run(evidence.approve(
            "CASE-1", "release", REVIEWER, note="Reviewed", actor_auth="password",
        ))["approval"]["approval_id"]

    def _both_read_before_either_writes(self):
        real = self.store.get_case

        async def slow_read(*args, **kwargs):
            snapshot = await real(*args, **kwargs)
            await asyncio.sleep(0)  # let the other caller read the same version
            return snapshot

        return patch.object(self.store, "get_case", new=slow_read)

    def test_two_simultaneous_executes_publish_once(self):
        approval_id = self._approved()
        publish = AsyncMock(return_value=OK_RECEIPT)

        async def both():
            return await asyncio.gather(
                evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"),
                evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"),
                return_exceptions=True,
            )

        with patch("vf_logistics.tools.publish_decision", new=publish), self._both_read_before_either_writes():
            results = run(both())
        winners = [r for r in results if isinstance(r, dict)]
        losers = [r for r in results if isinstance(r, evidence.EvidenceError)]
        assert len(winners) == 1 and len(losers) == 1, results
        assert losers[0].status == 409
        assert publish.call_count == 1
        case = self.stored()
        assert case["state"] == "RELEASED_BY_HUMAN"
        assert [e["status"] for e in case["verification"]["executions"]] == ["sent"]
        assert case["verification"]["approvals"][0]["status"] == "EXECUTED"

    def test_two_different_people_at_once_publish_once(self):
        approval_id = self._approved()
        publish = AsyncMock(return_value=OK_RECEIPT)

        async def both():
            return await asyncio.gather(
                evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"),
                evidence.execute_approval("CASE-1", approval_id, "other@forwarder.example", actor_auth="password"),
                return_exceptions=True,
            )

        with patch("vf_logistics.tools.publish_decision", new=publish), self._both_read_before_either_writes():
            results = run(both())
        assert sorted(type(r).__name__ for r in results) == ["EvidenceError", "dict"], results
        assert publish.call_count == 1

    @pytest.mark.parametrize("second_caller", [REVIEWER, "other@forwarder.example"])
    def test_a_second_execute_while_the_first_is_still_sending_is_refused(self, second_caller):
        # N01-b: the same person calling again while their own first call is mid-send
        # used to be treated as "resuming a crashed claim" and sent a second message.
        approval_id = self._approved()

        async def scenario():
            gate, entered = asyncio.Event(), asyncio.Event()

            async def slow_publish(*args, **kwargs):
                entered.set()
                await gate.wait()
                return OK_RECEIPT

            publish = AsyncMock(side_effect=slow_publish)
            with patch("vf_logistics.tools.publish_decision", new=publish):
                first = asyncio.ensure_future(evidence.execute_approval(
                    "CASE-1", approval_id, REVIEWER, actor_auth="password"))
                await entered.wait()
                assert (await self.store.get_case("CASE-1"))["state"] == "EXECUTING"
                second = asyncio.ensure_future(evidence.execute_approval(
                    "CASE-1", approval_id, second_caller, actor_auth="password"))
                await asyncio.sleep(0.05)  # give the second call time to decide
                gate.set()
                return publish, await asyncio.gather(first, second, return_exceptions=True)

        publish, (first_result, second_result) = run(scenario())
        assert isinstance(first_result, dict) and first_result["message_id"] == "msg-ok"
        assert isinstance(second_result, evidence.EvidenceError) and second_result.status == 409
        assert publish.call_count == 1
        exes = self.stored()["verification"]["executions"]
        assert [e["status"] for e in exes] == ["sent"]

    def test_the_claimant_may_resume_once_its_lease_has_run_out(self):
        approval_id = self._approved()
        boom = AsyncMock(side_effect=asyncio.CancelledError)
        with patch("vf_logistics.tools.publish_decision", new=boom), pytest.raises(asyncio.CancelledError):
            run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        # Inside the lease even the claimant is refused: nothing can tell a crashed
        # process from a slow one, and a second message is worse than a short wait.
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        assert raised.value.status == 409
        case = self.stored()
        case["verification"]["executions"][0]["claim_expires_epoch"] = 0
        run(self.store.put_case(case))
        with patch("vf_logistics.tools.publish_decision", new=AsyncMock(return_value=OK_RECEIPT)):
            result = run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        assert result["state"] == "RELEASED_BY_HUMAN"


def _fake_pubsub(results):
    """A pubsub_v1 whose publish() answers `results` in turn: an Exception raised from
    .result(), anything else returned as the message id. Returns (module, published)."""
    published: list[dict] = []

    def publish(topic, data, **attributes):
        published.append({"topic": topic, "attributes": attributes, "body": __import__("json").loads(data)})
        outcome = results.pop(0)
        future = MagicMock()
        if isinstance(outcome, Exception):
            future.result.side_effect = outcome
        else:
            future.result.return_value = outcome
        return future

    client = MagicMock()
    client.topic_path.side_effect = lambda project, topic: f"projects/{project}/topics/{topic}"
    client.publish.side_effect = publish
    module = MagicMock()
    module.PublisherClient.return_value = client
    return module, published


def _with_pubsub(module):
    """The real tools.publish_decision_direct, with only the Google client replaced."""
    cloud = types.ModuleType("google.cloud")
    cloud.pubsub_v1 = module
    return patch.dict(sys.modules, {"google.cloud": cloud, "google.cloud.pubsub_v1": module})


class TestN02APublishThatFails(Base):
    def _approved(self, action="release"):
        self.put()
        self.request_and_submit()
        run(evidence.reevaluate("CASE-1"))
        return run(evidence.approve(
            "CASE-1", action, REVIEWER, note="Reviewed", actor_auth="password",
        ))["approval"]["approval_id"]

    def _audit_rows(self, action):
        rows = run(self.store.list_audit(limit=500))
        return sorted((r for r in rows if r.get("action") == action and r.get("case_id") == "CASE-1"),
                      key=lambda r: r["at"])

    def test_a_publish_that_raises_is_a_failed_send_not_a_crash(self):
        approval_id = self._approved()
        boom = AsyncMock(side_effect=RuntimeError("topic not found"))
        with patch("vf_logistics.tools.publish_decision", new=boom):
            result = run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        assert result["state"] == "EXECUTION_FAILED" and result["message_id"] is None
        case = self.stored()
        assert case["state"] == "EXECUTION_FAILED"
        assert case["verification"]["executions"][-1]["status"] == "send_failed"
        assert case["verification"]["approvals"][0]["status"] == "VALID"
        # The release had already been recorded before the publish raised; it must
        # stay attached to the case rather than vanish from its actions.
        assert [a["action"] for a in case["actions"]] == ["release_shipment"]

    def test_a_real_publish_failure_then_a_retry_leaves_a_complete_record(self):
        approval_id = self._approved()
        pubsub, published = _fake_pubsub([TimeoutError("deadline exceeded"), "msg-real"])
        with patch.dict(os.environ, {"PROJECT_ID": "test-project"}), _with_pubsub(pubsub):
            first = run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
            assert first["state"] == "EXECUTION_FAILED"
            assert self.stored()["state"] == "EXECUTION_FAILED"
            second = run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        assert second["state"] == "RELEASED_BY_HUMAN" and second["message_id"] == "msg-real"

        case = self.stored()
        record = case["verification"]
        assert [e["status"] for e in record["executions"]] == ["send_failed", "sent"]
        assert len({e["execution_id"] for e in record["executions"]}) == 2
        assert record["approvals"][0]["status"] == "EXECUTED"
        assert case["state"] == "RELEASED_BY_HUMAN"
        # The two attempts carry one idempotency key, so a consumer can drop the repeat.
        assert [p["body"]["idempotency_key"] for p in published] == [f"exec-{approval_id}"] * 2
        # The review trail says where each attempt started from.
        starts = [(r["state_before"], r["state_after"]) for r in case["reviews"][-2:]]
        assert starts == [("APPROVED", "EXECUTION_FAILED"), ("EXECUTION_FAILED", "RELEASED_BY_HUMAN")]
        # The audit trail: the failed publish is recorded as failed, the retry as done.
        assert [r["status"] for r in self._audit_rows("publish_decision")] == ["failed", "done"]
        assert [r["detail"]["pub_failed"] for r in self._audit_rows("evidence_executed_release")] == [True, False]
        # release_shipment is re-run on every attempt, so there are two rows. That is
        # today's behaviour (it is not idempotent), pinned so a change is deliberate.
        assert len(self._audit_rows("release_shipment")) == 2

    def test_a_block_that_fails_to_publish_can_be_retried_the_same_way(self):
        approval_id = self._approved("block")
        pubsub, _ = _fake_pubsub([ConnectionError("unreachable"), "msg-block"])
        with patch.dict(os.environ, {"PROJECT_ID": "test-project"}), _with_pubsub(pubsub):
            assert run(evidence.execute_approval(
                "CASE-1", approval_id, REVIEWER, actor_auth="password"))["state"] == "EXECUTION_FAILED"
            result = run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        assert result["state"] == "BLOCKED_BY_HUMAN"


class TestN02bSplitIdentityReceipt(Base):
    """With EXECUTOR_URL set, the publish is delegated and the message id comes back
    nested one level down. It used to be read from the top, so a message that WAS
    published was recorded as a failed send and the approval stayed retryable."""

    def _approved(self):
        self.put()
        self.request_and_submit()
        run(evidence.reevaluate("CASE-1"))
        return run(evidence.approve(
            "CASE-1", "release", REVIEWER, note="Reviewed", actor_auth="password",
        ))["approval"]["approval_id"]

    def test_a_delegated_publish_that_succeeded_is_recorded_as_sent(self):
        approval_id = self._approved()
        delegated = AsyncMock(return_value={
            "delegated": True, "status": "done", "executed": True, "message_id": "msg-split",
        })
        with patch("vf_logistics.executor_client.configured", return_value=True), \
                patch("vf_logistics.executor_client.request_protected_action", new=delegated):
            result = run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        assert result["state"] == "RELEASED_BY_HUMAN" and result["message_id"] == "msg-split"
        assert self.stored()["verification"]["executions"][-1]["status"] == "sent"

    @pytest.mark.parametrize("outcome", [
        {"delegated": True, "status": "failed", "reason": "executor refused the call"},
        {"delegated": True, "status": "failed", "executed": False, "error": "boom"},
        {"delegated": True, "status": "done", "executed": True},  # claims done, sent nothing
        {"delegated": True, "status": "failed", "message_id": "m-stale"},  # failed outranks an id
    ])
    def test_a_delegated_publish_that_did_not_happen_is_a_failed_send(self, outcome):
        approval_id = self._approved()
        with patch("vf_logistics.executor_client.configured", return_value=True), \
                patch("vf_logistics.executor_client.request_protected_action", new=AsyncMock(return_value=outcome)):
            result = run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        assert result["state"] == "EXECUTION_FAILED"
        assert self.stored()["verification"]["approvals"][0]["status"] == "VALID"


class TestN02Route(Base):
    """The same failure at the HTTP boundary: a 200 that says EXECUTION_FAILED, then a
    200 that says RELEASED_BY_HUMAN on retry."""

    def setup_method(self):
        super().setup_method()
        from vf_logistics import app as app_mod

        self.app_mod = app_mod
        self.was = app_mod.limiter.enabled
        app_mod.limiter.enabled = False
        self.client = app_mod.app.test_client()

    def teardown_method(self):
        self.app_mod.limiter.enabled = self.was
        super().teardown_method()

    def test_execute_twice_over_http(self):
        from test_console_session import mint

        self.put()
        self.request_and_submit()
        run(evidence.reevaluate("CASE-1"))
        approval_id = run(evidence.approve(
            "CASE-1", "release", REVIEWER, note="Reviewed", actor_auth="password",
        ))["approval"]["approval_id"]
        headers = {"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint(REVIEWER, amr="password")}
        pubsub, _ = _fake_pubsub([TimeoutError("deadline exceeded"), "msg-http"])
        with patch.dict(os.environ, {"PROJECT_ID": "test-project"}), _with_pubsub(pubsub):
            first = self.client.post("/api/v1/review/CASE-1/execute",
                                     json={"approval_id": approval_id}, headers=headers)
            second = self.client.post("/api/v1/review/CASE-1/execute",
                                      json={"approval_id": approval_id}, headers=headers)
        assert first.status_code == 200 and first.get_json()["state"] == "EXECUTION_FAILED"
        assert second.status_code == 200 and second.get_json()["state"] == "RELEASED_BY_HUMAN"
        assert second.get_json()["message_id"] == "msg-http"


class TestN08BInterruptedExecutionOverHttp(Base):
    """What the console reads and does about an execution that was claimed and never
    confirmed. It offers Resume from the case JSON a viewer can read, so that JSON must
    carry the claim and its deadline (Unix seconds); the answer to Resume is the
    backend's, and its 409 text is what the console shows."""

    def setup_method(self):
        super().setup_method()
        from vf_logistics import app as app_mod

        self.app_mod = app_mod
        self.was = app_mod.limiter.enabled
        app_mod.limiter.enabled = False
        self.client = app_mod.app.test_client()

    def teardown_method(self):
        self.app_mod.limiter.enabled = self.was
        super().teardown_method()

    def _interrupted(self):
        """A case left EXECUTING / CLAIMING by a send that never came back."""
        self.put()
        self.request_and_submit()
        run(evidence.reevaluate("CASE-1"))
        approval_id = run(evidence.approve(
            "CASE-1", "release", REVIEWER, note="Reviewed", actor_auth="password",
        ))["approval"]["approval_id"]
        boom = AsyncMock(side_effect=asyncio.CancelledError)
        with patch("vf_logistics.tools.publish_decision", new=boom), pytest.raises(asyncio.CancelledError):
            run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        return approval_id

    def _headers(self):
        from test_console_session import mint

        return {"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint(REVIEWER, amr="password")}

    def test_the_case_a_viewer_reads_carries_the_claim_and_its_deadline(self):
        before = time.time()
        approval_id = self._interrupted()
        served = self.client.get("/api/v1/orchestrator/case/CASE-1").get_json()
        assert served["state"] == "EXECUTING"
        record = served["verification"]
        assert [(a["approval_id"], a["status"]) for a in record["approvals"]] == [(approval_id, "CLAIMING")]
        (execution,) = record["executions"]
        assert execution["approval_id"] == approval_id and execution["status"] == "claiming"
        # Seconds since the epoch, one lease from the claim: the console compares it with
        # its own clock to tell a running execution from an interrupted one.
        assert before + evidence.CLAIM_LEASE_S <= execution["claim_expires_epoch"] <= time.time() + evidence.CLAIM_LEASE_S

    def test_a_resume_inside_the_lease_is_refused_with_the_text_the_console_shows(self):
        approval_id = self._interrupted()
        with patch("vf_logistics.tools.publish_decision", new=AsyncMock(return_value=OK_RECEIPT)) as publish:
            response = self.client.post("/api/v1/review/CASE-1/execute",
                                        json={"approval_id": approval_id}, headers=self._headers())
        assert response.status_code == 409
        assert "Another execution of this approval is in progress" in response.get_json()["error"]
        publish.assert_not_called()
        assert self.stored()["state"] == "EXECUTING"

    def test_a_resume_after_the_lease_continues_the_same_execution(self):
        approval_id = self._interrupted()
        case = self.stored()
        claimed = case["verification"]["executions"][0]["execution_id"]
        case["verification"]["executions"][0]["claim_expires_epoch"] = time.time() - 1
        run(self.store.put_case(case))
        with patch("vf_logistics.tools.publish_decision", new=AsyncMock(return_value=OK_RECEIPT)):
            response = self.client.post("/api/v1/review/CASE-1/execute",
                                        json={"approval_id": approval_id}, headers=self._headers())
        assert response.status_code == 200 and response.get_json()["state"] == "RELEASED_BY_HUMAN"
        stored = self.stored()
        assert [e["execution_id"] for e in stored["verification"]["executions"]] == [claimed]
        assert stored["verification"]["executions"][0]["status"] == "sent"
        assert stored["verification"]["approvals"][0]["status"] == "EXECUTED"


class TestExecutedDecisionsReachTheLearningLoop(Base):
    """
    execute_approval is the only way a case with a verification record becomes
    RELEASED_BY_HUMAN or BLOCKED_BY_HUMAN, so it must drop the cached human
    history the learning loop scores from, as human_decide does.
    """

    def teardown_method(self):
        orchestrator._invalidate_shipper_feedback()
        super().teardown_method()

    def test_a_second_block_executed_here_counts_for_the_next_shipment(self):
        shipment = plywood()
        name = shipment["shipper_name"]
        run(self.store.put_case({
            "case_id": "B-0", "shipment_id": "B-0", "state": "BLOCKED_BY_HUMAN",
            "created_at": "2026-10-11T01:00:00+00:00",
            "shipment": shipment, "actions": [], "reviews": [],
        }))
        orchestrator._invalidate_shipper_feedback()
        # One block earns nothing yet, and reading it fills the cache.
        assert run(orchestrator.shipper_risk_adjustment(name)) == 0

        self.put()
        self.request_and_submit()
        run(evidence.reevaluate("CASE-1"))
        aid = run(evidence.approve(
            "CASE-1", "block", REVIEWER, actor_auth="password",
        ))["approval"]["approval_id"]
        with patch("vf_logistics.tools.publish_decision", new=AsyncMock(return_value=OK_RECEIPT)):
            result = run(evidence.execute_approval("CASE-1", aid, REVIEWER, actor_auth="password"))
        assert result["state"] == "BLOCKED_BY_HUMAN"

        # A stale cache answers 0 here, and the shipper's next borderline
        # shipment could then auto-clear without the second block's +15.
        assert run(orchestrator.shipper_risk_adjustment(name)) == 15
