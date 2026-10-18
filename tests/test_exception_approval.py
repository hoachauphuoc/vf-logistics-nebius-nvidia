"""
A release over unresolved or contradicting evidence is an operation of its own (N04):
it names every item it waives and gives a reason, and the approval records both.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_evidence_eval_approve import DOCS3, PAPERS, Base, _submit_per_type  # noqa: E402
from vf_logistics import evidence  # noqa: E402

REVIEWER = "reviewer@forwarder.example"
REASON = "Certificate misread; checked the original"
WAIVED = ["contradiction:certificate_country"]


def run(coro):
    return asyncio.run(coro)


class TestTheExceptionOperation(Base):
    def _full_set(self, **override):
        self.put()
        out = run(evidence.request_evidence("CASE-1", REVIEWER, documents=DOCS3))
        links = {link["doc_type"]: link["token"] for link in out["links"]}
        _submit_per_type(links, {**PAPERS, **override})
        return run(evidence.reevaluate("CASE-1"))

    def _contradicted(self):
        result = self._full_set(
            certificate_of_origin={"producer_name": "Saigon Plywood Co", "origin_country": "China"},
        )
        assert result["evaluation"]["status"] == "contradicted"

    def test_it_records_what_it_waives_and_why(self):
        self._contradicted()
        result = run(evidence.approve_exception(
            "CASE-1", REVIEWER, REASON, WAIVED, actor_auth="password",
        ))
        assert result["state"] == "APPROVED"
        exception = result["approval"]["exception"]
        assert exception["operation"] == "exception"
        assert exception["waived"] == WAIVED
        assert exception["reason"] == REASON
        assert exception["approved_by"] == REVIEWER
        assert [c["kind"] for c in exception["contradictions"]] == ["certificate_country"]
        assert result["approval"]["evaluation_id"] is not None

    def test_it_refuses_a_list_that_does_not_match_what_is_open(self):
        self._contradicted()
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.approve_exception(
                "CASE-1", REVIEWER, REASON, ["something_else"], actor_auth="password",
            ))
        assert raised.value.status == 400
        assert "every waived item" in raised.value.message
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.approve_exception("CASE-1", REVIEWER, REASON, [], actor_auth="password"))
        assert raised.value.status == 400
        assert "what it waives" in raised.value.message
        assert self.stored()["state"] == "ESCALATED"
        assert self.stored()["verification"]["approvals"] == []

    def test_it_needs_a_reason(self):
        self._contradicted()
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.approve_exception("CASE-1", REVIEWER, "   ", WAIVED, actor_auth="password"))
        assert raised.value.status == 400
        assert "reason" in raised.value.message
        assert self.stored()["verification"]["approvals"] == []

    def test_it_needs_a_password_sign_in(self):
        self._contradicted()
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.approve_exception("CASE-1", REVIEWER, REASON, WAIVED, actor_auth="one_click"))
        assert raised.value.status == 403
        assert self.stored()["verification"]["approvals"] == []

    def test_it_refuses_when_there_is_nothing_to_waive(self):
        assert self._full_set()["evaluation"]["status"] == "provided"
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.approve_exception(
                "CASE-1", REVIEWER, REASON, ["certificate_of_origin"], actor_auth="password",
            ))
        assert raised.value.status == 409
        assert "nothing to waive" in raised.value.message
        assert self.stored()["verification"]["approvals"] == []

    def test_the_normal_approval_refuses_an_exception_and_points_to_the_operation(self):
        self._contradicted()
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.approve("CASE-1", "release", REVIEWER, note=REASON, actor_auth="password"))
        assert raised.value.status == 403
        assert "exception operation" in raised.value.message
        assert self.stored()["state"] != "APPROVED"
        assert self.stored()["verification"]["approvals"] == []
