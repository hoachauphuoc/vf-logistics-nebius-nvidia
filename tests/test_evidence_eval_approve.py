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

    def test_a_request_with_documents_still_missing_stays_open_after_evaluation(self):
        """N04: only a full set closes a request (see TestN04WhenARequestIsClosed)."""
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
        result = run(evidence.approve("CASE-1", "release", REVIEWER, note="Reviewed", actor_auth="password"))
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
            run(evidence.approve("CASE-1", "release", REVIEWER, note="Reviewed", actor_auth="password"))
        assert raised.value.status == 409
        assert self.stored()["state"] != "APPROVED"

    def test_a_case_in_the_wrong_state_is_refused(self):
        self.put(state="AWAITING_EVIDENCE")
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.approve("CASE-1", "release", REVIEWER, note="Reviewed", actor_auth="password"))
        assert raised.value.status == 409

    def test_an_invalid_action_is_refused(self):
        self._prepare()
        with pytest.raises(evidence.EvidenceError):
            run(evidence.approve("CASE-1", "request_info", REVIEWER, actor_auth="password"))

    def test_a_stale_approval_is_superseded_by_new_evidence(self):
        """Approve, then new evidence arrives: the approval is no longer valid."""
        self._prepare()
        run(evidence.approve("CASE-1", "release", REVIEWER, note="Reviewed", actor_auth="password"))
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

    def _prepare_unresolved(self):
        self.put()
        self.request_and_submit(extracted={})
        run(evidence.reevaluate("CASE-1"))
        ev = self.stored()["verification"]["evaluations"][-1]
        ev["unresolved"] = ev.get("unresolved") or ["certificate_of_origin"]
        case = self.stored()
        case["verification"]["evaluations"][-1] = ev
        run(self.store.put_case(case))

    def test_n04_release_with_unresolved_evidence_needs_a_note(self):
        self._prepare_unresolved()
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.approve("CASE-1", "release", REVIEWER, note="", actor_auth="password"))
        assert raised.value.status == 400
        assert self.stored()["state"] != "APPROVED"

    def test_n04_release_with_unresolved_evidence_and_a_note_is_allowed(self):
        self._prepare_unresolved()
        result = run(evidence.approve(
            "CASE-1", "release", REVIEWER, note="Verified by phone", actor_auth="password",
        ))
        assert result["state"] == "APPROVED"

    def test_n04_block_with_unresolved_evidence_needs_no_note(self):
        self._prepare_unresolved()
        result = run(evidence.approve("CASE-1", "block", REVIEWER, note="", actor_auth="password"))
        assert result["state"] == "APPROVED"

    def test_the_review_entry_is_appended(self):
        self._prepare()
        run(evidence.approve("CASE-1", "release", REVIEWER, note="All clear", actor_auth="password"))
        case = self.stored()
        review = case["reviews"][-1]
        assert review["action"] == "release"
        assert review["approval_id"] is not None


DOCS3 = ["certificate_of_origin", "producer_declaration", "input_purchase_invoices"]


def _submit_per_type(links, extracted_by_type):
    for dt, ext in extracted_by_type.items():
        mock = {
            "agent": "evidence_extraction", "model": "test", "result": ext,
            "latency_ms": 10, "input_tokens": 10, "output_tokens": 10,
            "parse_error": False, "at": "2026-10-12T08:00:00Z",
        }
        with patch("vf_logistics.agents.document_agent.extract_evidence", new=AsyncMock(return_value=mock)), \
                patch("vf_logistics.model_armor.screen", new=AsyncMock(return_value={"blocked": False})), \
                patch("vf_logistics.model_armor.extract_pdf_text", return_value=("text", None)), \
                patch("vf_logistics.document_store.archive", new=AsyncMock(return_value={"archived": True, "uri": "gs://t/d"})):
            run(evidence.receive_evidence(links[dt], tiny_pdf(), f"{dt}.pdf", "application/pdf"))


class TestN06NotStated(Base):
    def _thin_evidence(self):
        self.put()
        out = run(evidence.request_evidence("CASE-1", REVIEWER, documents=DOCS3))
        links = {link["doc_type"]: link["token"] for link in out["links"]}
        _submit_per_type(links, {
            "certificate_of_origin": {"origin_country": "Vietnam"},
            "producer_declaration": {"producer_name": "not stated"},
            "input_purchase_invoices": {"supplier_name": "not stated"},
        })
        return run(evidence.reevaluate("CASE-1"))

    def test_not_stated_documents_do_not_count_as_provided(self):
        ev = self._thin_evidence()["evaluation"]
        assert ev["status"] == "missing"
        assert set(ev["unresolved"]) == {"producer_declaration", "input_purchase_invoices"}

    def test_n04_release_of_that_case_is_an_exception_with_a_recorded_reason(self):
        self._thin_evidence()
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.approve("CASE-1", "release", REVIEWER, note="", actor_auth="password"))
        assert raised.value.status == 400
        result = run(evidence.approve(
            "CASE-1", "release", REVIEWER, note="Confirmed by phone", actor_auth="password",
        ))
        exc = result["approval"]["exception"]
        assert exc["reason"] == "Confirmed by phone"
        assert set(exc["unresolved"]) == {"producer_declaration", "input_purchase_invoices"}
        assert exc["approved_by"] == REVIEWER


class TestN07LegacyDecide(Base):
    def _decide(self, action, auth, **case):
        from vf_logistics import orchestrator
        self.put(**case)
        return run(orchestrator.human_decide(
            "CASE-1", action, REVIEWER, "reviewed", actor_auth=auth,
        ))

    def test_a_case_with_a_verification_record_cannot_be_released_through_decide(self):
        # Version 0: a request exists but no evidence has arrived yet.
        self.put()
        run(evidence.request_evidence("CASE-1", REVIEWER, documents=["certificate_of_origin"]))
        case = self.stored()
        case["state"] = "HELD_FOR_REVIEW"
        run(self.store.put_case(case))
        assert case["verification"]["evidence_version"] == 0
        from vf_logistics import orchestrator
        result = run(orchestrator.human_decide(
            "CASE-1", "release", REVIEWER, "reviewed", actor_auth="one_click",
        ))
        assert result["ok"] is False
        assert "/approve" in result["error"]
        result = run(orchestrator.human_decide(
            "CASE-1", "release", REVIEWER, "reviewed", actor_auth="password",
        ))
        assert result["ok"] is False
        assert "/approve" in result["error"]
        assert self.stored()["state"] == "HELD_FOR_REVIEW"

    def test_release_without_a_password_is_refused_on_a_plain_case(self):
        result = self._decide("release", "one_click")
        assert result["ok"] is False
        assert "password" in result["error"].lower()


class TestN06EveryRequiredField(Base):
    def _eval(self, invoice, declaration=None):
        self.put()
        out = run(evidence.request_evidence("CASE-1", REVIEWER, documents=DOCS3))
        links = {link["doc_type"]: link["token"] for link in out["links"]}
        _submit_per_type(links, {
            "certificate_of_origin": {"origin_country": "Vietnam", "producer_name": "Saigon Plywood"},
            "producer_declaration": declaration or {"producer_name": "Saigon Plywood", "input_origins": ["Vietnam"]},
            "input_purchase_invoices": invoice,
        })
        return run(evidence.reevaluate("CASE-1"))["evaluation"]

    def test_an_invoice_with_a_supplier_but_no_origin_is_not_provided(self):
        ev = self._eval({
            "supplier_name": "VN Timber", "goods_origin_country": "not stated",
            "supplier_country": "unknown",
        })
        assert ev["status"] == "missing"
        assert ev["unresolved"] == ["input_purchase_invoices"]

    def test_an_invoice_with_an_origin_but_no_supplier_is_not_provided(self):
        ev = self._eval({"supplier_name": "n/a", "goods_origin_country": "Vietnam"})
        assert "input_purchase_invoices" in ev["unresolved"]

    def test_a_complete_invoice_is_provided(self):
        ev = self._eval({"supplier_name": "VN Timber", "goods_origin_country": "Vietnam"})
        assert ev["status"] == "provided"

    def test_an_incomplete_invoice_still_raises_a_contradiction(self):
        """Unproven is not hidden: China-origin goods on a nameless invoice still flag."""
        ev = self._eval({"supplier_name": "not stated", "goods_origin_country": "China"})
        assert "input_purchase_invoices" in ev["unresolved"]
        assert ev["contradictions"], ev

    def test_a_not_stated_producer_is_not_a_mismatch(self):
        ev = self._eval(
            {"supplier_name": "VN Timber", "goods_origin_country": "Vietnam"},
            declaration={"producer_name": "not stated"},
        )
        assert not any(c.get("kind") == "producer" for c in ev["contradictions"])


class TestN05OnlyInsideTheVerificationLoop(Base):
    """Re-evaluate is for a case that is in the verification loop, and only then."""

    OUTSIDE = [
        "AUTO_CLEARED", "RELEASED_BY_HUMAN", "BLOCKED_BY_HUMAN", "APPROVED",
        "EXECUTING", "EXECUTION_FAILED", "INGESTED", "DEAD_LETTER",
    ]
    INSIDE = ["AWAITING_EVIDENCE", "HELD_FOR_REVIEW", "ESCALATED", "PENDING_HUMAN"]

    def _put_in_state(self, state):
        """A case with a request and one earlier evaluation, parked in `state`."""
        self.put()
        run(evidence.request_evidence("CASE-1", REVIEWER, documents=["certificate_of_origin"]))
        case = self.stored()
        case["state"] = state
        case["verification"]["evaluations"].append({
            "evaluation_id": "eveval-seed", "evidence_version": 0, "status": "missing",
            "risk_floor": 45, "findings": [], "clarified": [], "unresolved": [],
            "contradictions": [],
        })
        run(self.store.put_case(case))
        return self.stored()

    @pytest.mark.parametrize("state", OUTSIDE)
    def test_a_case_outside_the_loop_is_refused_and_left_untouched(self, state):
        before = self._put_in_state(state)
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.reevaluate("CASE-1"))
        assert raised.value.status == 409
        assert state in str(raised.value)
        after = self.stored()
        assert after["state"] == state
        assert after["_version"] == before["_version"]
        assert len(after["verification"]["evaluations"]) == 1

    @pytest.mark.parametrize("state", INSIDE)
    def test_a_case_inside_the_loop_is_evaluated(self, state):
        self._put_in_state(state)
        result = run(evidence.reevaluate("CASE-1"))
        assert result["state"] in ("HELD_FOR_REVIEW", "ESCALATED")
        assert len(self.stored()["verification"]["evaluations"]) == 2

    def test_a_case_that_never_asked_for_documents_is_refused_and_not_changed(self):
        # N05: "never requested" is outside the loop too. Before this, the call went
        # through, wrote an empty verification record and locked the legacy /decide.
        self.put()
        before = self.stored()
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.reevaluate("CASE-1"))
        assert raised.value.status == 409
        assert "requested" in str(raised.value).lower()
        after = self.stored()
        assert "verification" not in after
        assert after["state"] == "HELD_FOR_REVIEW"
        assert after["_version"] == before["_version"]

    def test_a_refused_reevaluate_leaves_the_plain_review_path_open(self):
        from vf_logistics import orchestrator
        self.put()
        with pytest.raises(evidence.EvidenceError):
            run(evidence.reevaluate("CASE-1"))
        result = run(orchestrator.human_decide(
            "CASE-1", "release", REVIEWER, "reviewed", actor_auth="password",
        ))
        assert result["ok"] is True


PAPERS = {
    "certificate_of_origin": {"producer_name": "Saigon Plywood Co", "origin_country": "Vietnam"},
    "producer_declaration": {"producer_name": "Saigon Plywood Co", "input_origins": ["Vietnam"]},
    "input_purchase_invoices": {
        "supplier_name": "Mekong Veneer", "supplier_country": "Vietnam",
        "goods_origin_country": "Vietnam", "producer_name": "Saigon Plywood Co",
    },
}


class TestN04WhenARequestIsClosed(Base):
    """A request for three documents closes when all three are in, and not before."""

    def _ask_and_submit(self, k):
        self.put()
        out = run(evidence.request_evidence("CASE-1", REVIEWER, documents=DOCS3))
        self.links = {link["doc_type"]: link["token"] for link in out["links"]}
        self.request_id = out["request"]["request_id"]
        _submit_per_type(self.links, {dt: PAPERS[dt] for dt in DOCS3[:k]})

    def _request(self):
        return self.stored()["verification"]["requests"][0]

    @pytest.mark.parametrize("k", [0, 1, 2, 3])
    def test_re_evaluating_k_of_3_documents(self, k):
        self._ask_and_submit(k)
        ev = run(evidence.reevaluate("CASE-1"))["evaluation"]
        req = self._request()
        assert sorted(req.get("received_docs") or {}) == sorted(DOCS3[:k])
        assert ev["unresolved"] == DOCS3[k:]
        assert ev["status"] == ("provided" if k == 3 else "missing")
        # Only a full set closes the request; a partial one stays open so the shipper's
        # remaining per-document links keep working.
        assert req["status"] == ("RECEIVED" if k == 3 else "SENT")
        assert "reconciled_at" not in req  # the closed state is RECEIVED; there is no later one

    def test_a_partial_re_evaluate_does_not_unlock_a_decision_until_the_request_is_closed(self):
        self._ask_and_submit(2)
        result = run(evidence.reevaluate("CASE-1"))
        assert result["state"] in ("HELD_FOR_REVIEW", "ESCALATED")
        assert self._request()["status"] == "SENT"
        for action in ("release", "block"):
            with pytest.raises(evidence.EvidenceError) as raised:
                run(evidence.approve("CASE-1", action, REVIEWER, note="ok", actor_auth="password"))
            assert raised.value.status == 409
            # The message has to say what to do, not only what is wrong.
            assert "cancel" in raised.value.message.lower()
            assert "documents" in raised.value.message.lower()
        assert self.stored()["state"] == result["state"]

    def test_cancelling_the_request_is_the_way_out_and_a_release_then_needs_a_reason(self):
        self._ask_and_submit(2)
        run(evidence.reevaluate("CASE-1"))
        run(evidence.cancel_request("CASE-1", self.request_id, REVIEWER,
                                    "Shipper cannot find the invoice", actor_auth="password"))
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.approve("CASE-1", "release", REVIEWER, note="", actor_auth="password"))
        assert raised.value.status == 400  # the missing invoice is an exception that needs a note
        result = run(evidence.approve("CASE-1", "release", REVIEWER,
                                      note="Invoice seen on site", actor_auth="password"))
        assert result["approval"]["exception"]["unresolved"] == ["input_purchase_invoices"]

    def test_the_last_document_after_a_partial_re_evaluate_needs_a_fresh_one(self):
        self._ask_and_submit(2)
        run(evidence.reevaluate("CASE-1"))
        _submit_per_type(self.links, {"input_purchase_invoices": PAPERS["input_purchase_invoices"]})
        assert self._request()["status"] == "RECEIVED"
        # All three are in, but the evaluation on file predates the third.
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.approve("CASE-1", "block", REVIEWER, actor_auth="password"))
        assert raised.value.status == 409
        run(evidence.reevaluate("CASE-1"))
        assert run(evidence.approve("CASE-1", "block", REVIEWER, actor_auth="password"))["state"] == "APPROVED"


class TestReleasingAgainstContradictingPapers(Base):
    """A release is the one decision that can send cargo on after the papers disagree
    with the declaration. It stays possible (the extractor is a model whose false alarm
    a reviewer must be able to dismiss) but never silently: it needs a reason, and the
    approval records what was contradicted."""

    def _full_set(self, **override):
        """All three papers in, with `override` replacing individual documents."""
        self.put()
        out = run(evidence.request_evidence("CASE-1", REVIEWER, documents=DOCS3))
        links = {link["doc_type"]: link["token"] for link in out["links"]}
        _submit_per_type(links, {**PAPERS, **override})
        return run(evidence.reevaluate("CASE-1"))

    def _contradicted(self):
        result = self._full_set(certificate_of_origin={"producer_name": "Saigon Plywood Co", "origin_country": "China"})
        assert result["evaluation"]["status"] == "contradicted"
        assert result["evaluation"]["unresolved"] == []
        return result

    def test_a_release_needs_a_note(self):
        self._contradicted()
        for empty in ("", "   "):
            with pytest.raises(evidence.EvidenceError) as raised:
                run(evidence.approve("CASE-1", "release", REVIEWER, note=empty, actor_auth="password"))
            assert raised.value.status == 400
            assert "contradict" in raised.value.message.lower()
        assert self.stored()["state"] == "ESCALATED"

    def test_a_release_with_a_note_is_recorded_as_an_exception_naming_the_contradiction(self):
        self._contradicted()
        result = run(evidence.approve(
            "CASE-1", "release", REVIEWER, note="Certificate misread; checked the original", actor_auth="password",
        ))
        exc = result["approval"]["exception"]
        assert exc["reason"] == "Certificate misread; checked the original"
        assert exc["approved_by"] == REVIEWER
        assert [c["kind"] for c in exc["contradictions"]] == ["certificate_country"]
        assert "China" in exc["contradictions"][0]["detail"]

    def test_a_block_needs_no_note(self):
        self._contradicted()
        result = run(evidence.approve("CASE-1", "block", REVIEWER, note="", actor_auth="password"))
        assert result["state"] == "APPROVED"
        assert "exception" not in result["approval"]

    def test_a_note_is_also_needed_when_unresolved_and_contradicted_together(self):
        self.put()
        out = run(evidence.request_evidence("CASE-1", REVIEWER, documents=DOCS3))
        links = {link["doc_type"]: link["token"] for link in out["links"]}
        _submit_per_type(links, {"certificate_of_origin": {"producer_name": "Saigon Plywood", "origin_country": "China"}})
        run(evidence.cancel_request("CASE-1", out["request"]["request_id"], REVIEWER, "no answer", actor_auth="password"))
        run(evidence.reevaluate("CASE-1"))
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.approve("CASE-1", "release", REVIEWER, note="", actor_auth="password"))
        message = raised.value.message.lower()
        assert raised.value.status == 400 and "unresolved" in message and "contradict" in message

    def test_good_papers_still_release_without_a_note(self):
        assert self._full_set()["evaluation"]["status"] == "provided"
        result = run(evidence.approve("CASE-1", "release", REVIEWER, note="", actor_auth="password"))
        assert result["state"] == "APPROVED"
        assert "exception" not in result["approval"]


def _submit_raw(token, mock_result=None, *, blocked=False, parse_error=False):
    """One upload through a link, with the screen and the extractor answering as told."""
    mock = {
        "agent": "evidence_extraction", "model": "test", "result": mock_result or {},
        "latency_ms": 10, "input_tokens": 10, "output_tokens": 10,
        "parse_error": parse_error, "at": "2026-10-14T08:00:00Z",
    }
    with patch("vf_logistics.agents.document_agent.extract_evidence", new=AsyncMock(return_value=mock)), \
            patch("vf_logistics.model_armor.screen", new=AsyncMock(return_value={"blocked": blocked})), \
            patch("vf_logistics.model_armor.extract_pdf_text", return_value=("text", None)), \
            patch("vf_logistics.document_store.archive", new=AsyncMock(return_value={"archived": True, "uri": "gs://t/d"})):
        return run(evidence.receive_evidence(token, tiny_pdf(), "doc.pdf", "application/pdf"))


class TestN04UnusableUploadsDoNotUseUpTheSlot(Base):
    """A paper the screen blocked, or the model could not read, is not evidence. It used to
    count as "received": the request closed, the link died, and that document type could
    never be sent again, leaving only a release-with-reason or a block."""

    def _ask(self):
        self.put()
        out = run(evidence.request_evidence("CASE-1", REVIEWER, documents=DOCS3))
        return {link["doc_type"]: link["token"] for link in out["links"]}

    @pytest.mark.parametrize("kind", ["blocked", "unreadable", "empty"])
    def test_an_unusable_upload_leaves_the_type_open_and_the_same_link_works_again(self, kind):
        links = self._ask()
        _submit_per_type(links, {"certificate_of_origin": PAPERS["certificate_of_origin"],
                                 "producer_declaration": PAPERS["producer_declaration"]})
        token = links["input_purchase_invoices"]
        first = _submit_raw(token, {} if kind == "empty" else PAPERS["input_purchase_invoices"],
                            blocked=kind == "blocked", parse_error=kind == "unreadable")
        assert first["received"] is True and first["usable"] is False
        assert first["still_missing"] == ["input_purchase_invoices"]
        req = self.stored()["verification"]["requests"][0]
        assert req["status"] == "SENT"
        assert "input_purchase_invoices" not in (req.get("received_docs") or {})
        # The same link takes a readable copy, and that one closes the request.
        second = _submit_raw(token, PAPERS["input_purchase_invoices"])
        assert second["usable"] is True and second["still_missing"] == []
        assert self.stored()["verification"]["requests"][0]["status"] == "RECEIVED"
        ev = run(evidence.reevaluate("CASE-1"))["evaluation"]
        assert ev["status"] == "provided"

    def test_a_usable_upload_is_still_refused_the_second_time(self):
        links = self._ask()
        _submit_raw(links["certificate_of_origin"], PAPERS["certificate_of_origin"])
        with pytest.raises(evidence.EvidenceError) as raised:
            _submit_raw(links["certificate_of_origin"], PAPERS["certificate_of_origin"])
        assert raised.value.status == 409

    def test_a_new_request_can_ask_again_for_a_type_whose_only_copy_was_unusable(self):
        links = self._ask()
        _submit_raw(links["certificate_of_origin"], {}, blocked=True)
        run(evidence.cancel_request("CASE-1", self.stored()["verification"]["requests"][0]["request_id"],
                                    REVIEWER, "start over", actor_auth="password"))
        out = run(evidence.request_evidence("CASE-1", REVIEWER))
        assert "certificate_of_origin" in out["request"]["documents"]


class TestReevaluateKeepsAnEscalation(Base):
    """An escalated case waits for a signature. A re-evaluate whose floor is under 70 used
    to put it back to merely HELD_FOR_REVIEW, dropping the escalation."""

    @pytest.mark.parametrize("start,expected", [("ESCALATED", "ESCALATED"), ("HELD_FOR_REVIEW", "HELD_FOR_REVIEW")])
    def test_the_state_the_case_was_in_before_the_request_is_kept(self, start, expected):
        self.put(state=start)
        out = run(evidence.request_evidence("CASE-1", REVIEWER, documents=DOCS3))
        _submit_per_type({l["doc_type"]: l["token"] for l in out["links"]}, PAPERS)
        result = run(evidence.reevaluate("CASE-1"))
        assert result["floor"] < 70
        assert result["state"] == expected
        assert self.stored()["state"] == expected

    def test_a_contradiction_still_escalates_a_held_case(self):
        self.put(state="HELD_FOR_REVIEW")
        out = run(evidence.request_evidence("CASE-1", REVIEWER, documents=DOCS3))
        _submit_per_type({l["doc_type"]: l["token"] for l in out["links"]},
                         {**PAPERS, "certificate_of_origin": {"producer_name": "Saigon Plywood Co", "origin_country": "China"}})
        assert run(evidence.reevaluate("CASE-1"))["state"] == "ESCALATED"
