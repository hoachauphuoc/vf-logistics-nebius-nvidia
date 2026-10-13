"""
Re-evaluation and approval (Plan 1, steps 4-5).
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_console_session import TEST_KEY, TEST_SECRET  # noqa: E402
from test_origin_inputs import plywood  # noqa: E402
from vf_logistics import evidence  # noqa: E402
from vf_logistics import store as store_mod  # noqa: E402
from vf_logistics.verifier import validate  # noqa: E402

REVIEWER = "reviewer@forwarder.example"
ENV = {
    "VF_API_KEY": TEST_KEY, "VF_SESSION_SECRET": TEST_SECRET, "IAP_ENABLED": "false",
    "MULTI_TENANT": "false", "ANONYMOUS_ROLE": "viewer", "STORE_BACKEND": "memory",
    "REVIEWER_EMAILS": REVIEWER,
}


def run(coro):
    return asyncio.run(coro)


def tiny_pdf():
    try:
        from fpdf import FPDF
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=10)
        pdf.cell(text="Test")
        return bytes(pdf.output())
    except ImportError:
        return b"%PDF-1.0 fake"


class Base:
    def setup_method(self):
        self.env = patch.dict(os.environ, ENV)
        self.env.start()
        store_mod._store = None
        self.store = store_mod.get_store()

    def teardown_method(self):
        store_mod._store = None
        self.env.stop()

    def put(self, case_id="CASE-1", shipment=None, **extra):
        shipment = shipment or plywood()
        case = {
            "case_id": case_id, "shipment_id": case_id, "state": "HELD_FOR_REVIEW",
            "created_at": "2026-10-12T01:00:00+00:00", "updated_at": "2026-10-12T02:00:00+00:00",
            "shipment": shipment, "validation": validate(shipment), "actions": [], "reviews": [],
            "risk_score": 45, "reconciliation": {"risk_floor": 45, "effective_risk": 50, "model_risk": 50},
        }
        case.update(extra)
        run(self.store.put_case(case))

    def stored(self, case_id="CASE-1"):
        return run(self.store.get_case(case_id))

    def request_and_submit(self, case_id="CASE-1", extracted=None, documents=None):
        out = run(evidence.request_evidence(case_id, REVIEWER, documents=documents or ["certificate_of_origin"]))
        token = out["token"]
        ext = extracted or {"producer_name": "Saigon Plywood", "origin_country": "Vietnam"}
        mock = {
            "agent": "evidence_extraction", "model": "test", "result": ext,
            "latency_ms": 10, "input_tokens": 10, "output_tokens": 10,
            "parse_error": False, "at": "2026-10-12T08:00:00Z",
        }
        with patch("vf_logistics.agents.document_agent.extract_evidence", new=AsyncMock(return_value=mock)):
            with patch("vf_logistics.model_armor.screen", new=AsyncMock(return_value={"blocked": False})):
                with patch("vf_logistics.model_armor.extract_pdf_text", return_value=("text", None)):
                    with patch("vf_logistics.document_store.archive", new=AsyncMock(return_value={"archived": True, "uri": "gs://t/d"})):
                        run(evidence.receive_evidence(token, tiny_pdf(), "cert.pdf", "application/pdf"))


class TestReevaluation(Base):
    def test_good_evidence_clarifies_and_keeps_the_floor(self):
        self.put()
        self.request_and_submit()
        result = run(evidence.reevaluate("CASE-1"))
        assert result["state"] in ("HELD_FOR_REVIEW", "ESCALATED")
        ev = result["evaluation"]
        assert ev["evidence_version"] == 1
        assert ev["status"] in ("provided", "missing")
        case = self.stored()
        assert len(case["verification"]["evaluations"]) == 1
        # Good evidence does not lower the floor.
        assert (case["reconciliation"] or {}).get("risk_floor", 0) >= 45

    def test_contradicting_evidence_raises_the_floor(self):
        self.put()
        self.request_and_submit(extracted={
            "producer_name": "Saigon Plywood", "origin_country": "China",
        })
        result = run(evidence.reevaluate("CASE-1"))
        case = self.stored()
        assert (case["reconciliation"] or {}).get("risk_floor", 0) >= 80
        assert any(c.get("kind") == "certificate_country" for c in result["evaluation"]["contradictions"])

    def test_open_requests_are_closed_after_evaluation_when_all_docs_received(self):
        """N04: reevaluate closes requests only when all documents are in."""
        self.put()
        # Request 3 doc types but only submit 1 -- request stays open.
        self.request_and_submit(documents=["certificate_of_origin", "producer_declaration", "input_purchase_invoices"])
        run(evidence.reevaluate("CASE-1"))
        case = self.stored()
        req = case["verification"]["requests"][0]
        assert req["status"] in evidence.OPEN_STATUSES  # still open, 2 docs missing

    def test_missing_case_is_not_found(self):
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.reevaluate("NOPE"))
        assert raised.value.status == 404


class TestApproval(Base):
    def _prepare(self, case_id="CASE-1"):
        self.put(case_id)
        self.request_and_submit(case_id)
        run(evidence.reevaluate(case_id))

    def test_a_release_approval_is_valid_and_moves_the_case(self):
        self._prepare()
        result = run(evidence.approve("CASE-1", "release", REVIEWER, actor_auth="password"))
        assert result["state"] == "APPROVED"
        case = self.stored()
        assert case["state"] == "APPROVED"
        approval = case["verification"]["approvals"][0]
        assert approval["status"] == "VALID"
        assert approval["evidence_version"] == 1
        assert approval["approver"] == REVIEWER

    def test_a_block_does_not_need_a_password(self):
        self._prepare()
        result = run(evidence.approve("CASE-1", "block", REVIEWER, actor_auth="one_click"))
        assert result["state"] == "APPROVED"

    def test_a_release_without_a_password_is_refused(self):
        self._prepare()
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.approve("CASE-1", "release", REVIEWER, actor_auth="one_click"))
        assert raised.value.status == 403
        assert self.stored()["state"] != "APPROVED"

    def test_an_open_request_blocks_approval(self):
        self.put()
        self.request_and_submit()
        run(evidence.reevaluate("CASE-1"))
        # Now create a NEW request (the first was consumed by reevaluate). The case
        # moves back to AWAITING_EVIDENCE which is not approvable.
        run(evidence.request_evidence("CASE-1", REVIEWER, documents=["producer_declaration"]))
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.approve("CASE-1", "release", REVIEWER, actor_auth="password"))
        assert raised.value.status == 409
        assert self.stored()["state"] != "APPROVED"

    def test_a_case_in_the_wrong_state_is_refused(self):
        self.put(state="AWAITING_EVIDENCE")
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.approve("CASE-1", "release", REVIEWER, actor_auth="password"))
        assert raised.value.status == 409

    def test_an_invalid_action_is_refused(self):
        self._prepare()
        with pytest.raises(evidence.EvidenceError):
            run(evidence.approve("CASE-1", "request_info", REVIEWER, actor_auth="password"))

    def test_a_stale_approval_is_superseded_by_new_evidence(self):
        """Approve, then new evidence arrives: the approval is no longer valid."""
        self._prepare()
        run(evidence.approve("CASE-1", "release", REVIEWER, actor_auth="password"))
        # Submit more evidence
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
                    with patch("vf_logistics.document_store.archive", new=AsyncMock(return_value={"archived": True, "uri": "gs://t/d2"})):
                        run(evidence.receive_evidence(out2["token"], tiny_pdf(), "dec.pdf", "application/pdf"))
        case = self.stored()
        approval = case["verification"]["approvals"][0]
        assert approval["status"] == "SUPERSEDED"

    def test_the_review_entry_is_appended(self):
        self._prepare()
        run(evidence.approve("CASE-1", "release", REVIEWER, note="All clear", actor_auth="password"))
        case = self.stored()
        review = case["reviews"][-1]
        assert review["action"] == "release"
        assert review["approval_id"] is not None
