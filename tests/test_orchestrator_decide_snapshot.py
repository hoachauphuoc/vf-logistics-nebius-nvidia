"""
Two reader/writer edges of the orchestrator that no test reached: the refusals at the top of a human
decision (and the SAR a block signs), and the board snapshot's per-agent spend and marker handling.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(__file__))
from test_evidence_eval_approve import Base, run  # noqa: E402
from vf_logistics import orchestrator  # noqa: E402


class TestHumanDecisionRefusals(Base):
    def decide(self, action="block", reviewer="ana", note="sanctioned consignee", auth="password"):
        return run(orchestrator.human_decide("CASE-1", action, reviewer, note, actor_auth=auth))

    def test_an_unknown_action_is_refused_and_named(self):
        self.put()
        assert self.decide(action="shrug") == {"ok": False, "error": "unknown action 'shrug'"}

    def test_a_blank_reviewer_is_refused(self):
        self.put()
        for reviewer in ("", "   "):
            assert self.decide(reviewer=reviewer) == {"ok": False, "error": "reviewer is required"}

    def test_a_block_without_a_note_is_refused_and_leaves_the_case_waiting(self):
        self.put()
        for action in ("block", "request_info"):
            result = self.decide(action=action, note="  ")
            assert result == {"ok": False, "error": f"a note is required when action is '{action}'"}
        assert self.stored()["state"] == "HELD_FOR_REVIEW"

    def test_a_release_needs_no_note_but_does_need_a_password_session(self):
        self.put()
        result = self.decide(action="release", note="", auth="one_click")
        assert result == {"ok": False, "error": "Releasing a shipment needs a password sign-in."}
        assert self.stored()["state"] == "HELD_FOR_REVIEW"

    def test_a_missing_case_is_not_found(self):
        assert run(orchestrator.human_decide("NOPE", "block", "ana", "n")) == {"ok": False, "error": "case not found"}

    def test_a_case_not_waiting_for_review_says_its_state(self):
        self.put(state="AUTO_CLEARED")
        result = self.decide()
        assert result["ok"] is False
        assert "case is in state AUTO_CLEARED, which is not awaiting review" in result["error"]


class TestBlockingHoldsTheShipmentAndSignsTheSar(Base):
    def test_a_block_holds_the_shipment_and_signs_a_drafted_sar(self):
        sar = {"action": "draft_sar", "status": "done", "detail": {"requires_human_signoff": True, "reference": "SAR-9"}}
        self.put(actions=[sar])
        held = {"action": "hold_shipment", "status": "done"}
        with patch.object(orchestrator.tools, "hold_shipment", new=AsyncMock(return_value=held)) as hold:
            result = run(orchestrator.human_decide("CASE-1", "block", "ana", "sanctioned consignee", actor_auth="password"))
        assert result["ok"] is True and result["state"] == "BLOCKED_BY_HUMAN"
        assert result["review"]["sar_signed"] == "SAR-9"
        assert "Blocked by ana: sanctioned consignee" in hold.call_args.args[2]
        stored = self.stored()
        signed = stored["actions"][0]["detail"]
        assert (signed["requires_human_signoff"], signed["signed_by"]) == (False, "ana")
        assert held in stored["actions"]
        assert stored["decision"]["decided_by"] == "human"
        assert stored["claimed"] is False

    def test_asking_for_information_takes_no_tool_action_and_makes_no_decision(self):
        self.put()
        with patch.object(orchestrator.tools, "hold_shipment", new=AsyncMock()) as hold, \
                patch.object(orchestrator.tools, "release_shipment", new=AsyncMock()) as release:
            result = run(orchestrator.human_decide("CASE-1", "request_info", "ana", "need the certificate", actor_auth="password"))
        assert result["ok"] is True and result["state"] == "PENDING_HUMAN"
        hold.assert_not_called()
        release.assert_not_called()
        assert self.stored().get("decision") is None


class TestSnapshotSpendByAgent(Base):
    def snapshot(self):
        return run(orchestrator.snapshot())

    def test_steps_are_added_up_per_agent_and_the_cost_is_rounded_once(self):
        steps = [
            {"agent": "fraud", "input_tokens": 100, "output_tokens": 10, "cost_usd": 0.0000004},
            {"agent": "fraud", "input_tokens": 50, "output_tokens": 5, "cost_usd": 0.0000004},
            {"agent": "debate", "input_tokens": 7, "output_tokens": 3, "cost_usd": 0.5},
            {"input_tokens": None, "output_tokens": None, "cost_usd": None},
        ]
        self.put(steps=steps)
        by_agent = self.snapshot()["tokens_by_agent"]
        assert by_agent["fraud"] == {"calls": 2, "input": 150, "output": 15, "cost_usd": 0.000001}
        assert by_agent["debate"]["cost_usd"] == 0.5
        assert by_agent["unknown"] == {"calls": 1, "input": 0, "output": 0, "cost_usd": 0.0}

    def test_a_case_with_no_steps_adds_nothing(self):
        self.put(steps=None)
        assert self.snapshot()["tokens_by_agent"] == {}

    def test_storage_markers_are_not_cases_on_the_board(self):
        self.put("CASE-1")
        self.put("MARK-1", is_marker=True)
        ids = [c["case_id"] for c in self.snapshot()["cases"]]
        assert ids == ["CASE-1"]
