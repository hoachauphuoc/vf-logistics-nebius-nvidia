"""
Deep review: the opt-in debate on a case that is waiting for a person. It spends the dearest model, so it
refuses a case that is not waiting, records the debate and its cost on the case, and does not write over a
case that changed while the debate ran.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(__file__))
from test_evidence_eval_approve import Base, run  # noqa: E402
from vf_logistics import orchestrator  # noqa: E402
from vf_logistics.store import OptimisticLockError  # noqa: E402

VERDICT = {"verdict": "DISAGREE", "confidence": 0.8, "rationale": "r" * 300, "recommended_action": "block"}
DEBATE = {
    "model": "nvidia/Nemotron-3-Ultra-550b-a55b", "latency_ms": 900, "input_tokens": 1000, "output_tokens": 200,
    "at": "2026-10-12T03:00:00Z", "result": {"verdict": VERDICT, "rounds": 2},
}


class TestDeepReview(Base):
    def review(self, case_id="CASE-1", debate=DEBATE, error=None):
        mock = AsyncMock(side_effect=error) if error else AsyncMock(return_value=debate)
        with patch.object(orchestrator, "conduct_debate", new=mock):
            return run(orchestrator.deep_review(case_id)), mock

    def test_a_missing_case_is_not_found_and_no_debate_runs(self):
        result, mock = self.review("NOPE")
        assert result == {"ok": False, "error": "case not found"}
        mock.assert_not_called()

    def test_a_case_not_waiting_for_a_person_is_refused_and_says_its_state(self):
        self.put(state="AUTO_CLEARED")
        result, mock = self.review()
        assert result["ok"] is False
        assert "must be awaiting human review, current state: AUTO_CLEARED" in result["error"]
        mock.assert_not_called()

    def test_a_debate_is_recorded_on_the_case_with_its_cost(self):
        self.put()
        result, _ = self.review()
        assert result["ok"] is True
        assert result["verdict"] == VERDICT
        assert result["latency_ms"] == 900
        case = self.stored()
        assert case["debate"] == DEBATE["result"]
        assert case["steps"][-1]["agent"] == "debate"
        assert case["_agent_calls"] == 1
        assert (case["_input_tokens"], case["_output_tokens"]) == (1000, 200)
        assert case["_estimated_cost_usd"] > 0

    def test_the_verdict_is_announced_with_the_rationale_cut_short(self):
        self.put()
        with patch.object(orchestrator, "emit", new=AsyncMock()) as emit:
            self.review()
        kinds = [call.args[1] for call in emit.call_args_list]
        assert kinds == ["debate_start", "debate_verdict"]
        message = emit.call_args_list[1].args[2]
        assert "DISAGREE (confidence 80%)" in message
        assert "r" * 150 in message and "r" * 151 not in message

    def test_a_debate_with_no_verdict_still_succeeds_and_announces_none(self):
        self.put()
        with patch.object(orchestrator, "emit", new=AsyncMock()) as emit:
            result, _ = self.review(debate={**DEBATE, "result": {"verdict": None}})
        assert result["ok"] is True and result["verdict"] is None
        assert [call.args[1] for call in emit.call_args_list] == ["debate_start"]

    def test_a_debate_that_raises_is_reported_and_the_case_is_left_alone(self):
        self.put()
        before = self.stored()
        with patch.object(orchestrator, "emit", new=AsyncMock()) as emit:
            result, _ = self.review(error=RuntimeError("model down"))
        assert result == {"ok": False, "error": "model down"}
        assert emit.call_args_list[-1].args[1] == "debate_error"
        assert self.stored() == before

    def test_a_case_changed_while_the_debate_ran_is_not_overwritten(self):
        self.put()
        with patch.object(self.store, "put_case", new=AsyncMock(side_effect=OptimisticLockError("CASE-1", 1, 2))):
            result, _ = self.review()
        assert result == {"ok": False, "error": "case was modified concurrently, please retry"}
        assert "debate" not in self.stored()
