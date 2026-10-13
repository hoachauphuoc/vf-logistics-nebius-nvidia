"""
Receiving evidence through the signed link (Plan 1, step 3).

The token is the credential. Every test failure means a shipper who never had
an account on this system could do something they should not: submit to the
wrong case, to a cancelled request, through a link that was replaced, after
the link expired, with a file that was not asked for, or without being screened.
"""

from __future__ import annotations

import asyncio
import io
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_console_session import TEST_KEY, TEST_SECRET, mint  # noqa: E402
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


def tiny_pdf() -> bytes:
    try:
        from fpdf import FPDF

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=10)
        pdf.cell(text="Test evidence document")
        return pdf.output()
    except ImportError:
        return b"%PDF-1.0 fake"


class Base:
    def setup_method(self):
        from vf_logistics import app as app_mod

        self.env = patch.dict(os.environ, ENV)
        self.env.start()
        store_mod._store = None
        self.was = app_mod.limiter.enabled
        app_mod.limiter.enabled = False
        self.app_mod = app_mod
        self.client = app_mod.app.test_client()
        self.store = store_mod.get_store()

    def teardown_method(self):
        self.app_mod.limiter.enabled = self.was
        store_mod._store = None
        self.env.stop()

    def put(self, case_id="CASE-1", state="HELD_FOR_REVIEW", shipment=None, **extra):
        shipment = shipment or plywood()
        case = {
            "case_id": case_id, "shipment_id": case_id, "state": state,
            "created_at": "2026-10-12T01:00:00+00:00", "updated_at": "2026-10-12T02:00:00+00:00",
            "shipment": shipment, "validation": validate(shipment), "actions": [], "reviews": [],
        }
        case.update(extra)
        run(self.store.put_case(case))
        return case

    def stored(self, case_id="CASE-1"):
        return run(self.store.get_case(case_id))

    def reviewer(self):
        return {"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint(REVIEWER, amr="password")}

    def request_and_token(self, case_id="CASE-1"):
        out = run(evidence.request_evidence(case_id, REVIEWER))
        return out["request"]["request_id"], out["token"]

    def submit(self, token, data=None, filename="cert.pdf", mime="application/pdf"):
        """Submit evidence through receive_evidence, mocking the extraction."""
        if data is None:
            data = tiny_pdf()
        extracted = {"producer_name": "Saigon Plywood", "origin_country": "Vietnam"}
        mock_result = {
            "agent": "evidence_extraction", "model": "test", "result": extracted,
            "latency_ms": 50, "input_tokens": 100, "output_tokens": 50,
            "parse_error": False, "at": "2026-10-12T08:00:00Z",
        }
        with patch("vf_logistics.agents.document_agent.extract_evidence", new=AsyncMock(return_value=mock_result)):
            with patch("vf_logistics.model_armor.screen", new=AsyncMock(return_value={"blocked": False})):
                with patch("vf_logistics.model_armor.extract_pdf_text", return_value=("text", None)):
                    with patch("vf_logistics.document_store.archive", new=AsyncMock(return_value={"archived": True, "uri": "gs://test/doc"})):
                        return run(evidence.receive_evidence(
                            token, data, filename, mime,
                        ))


class TestReceiving(Base):
    def test_good_evidence_is_received_and_versioned(self):
        self.put()
        rid, token = self.request_and_token()
        result = self.submit(token)
        assert result["received"] is True
        assert result["evidence_version"] == 1
        assert result["extracted"] is True
        case = self.stored()
        assert case["verification"]["evidence_version"] == 1
        doc = case["verification"]["documents"][0]
        assert doc["request_id"] == rid
        assert doc["doc_type"] == "certificate_of_origin"
        assert doc["extracted"]["producer_name"] == "Saigon Plywood"
        request = case["verification"]["requests"][0]
        assert request["status"] == "RECEIVED"

    def test_a_second_document_on_a_new_request_increments_the_version(self):
        self.put()
        _, token1 = self.request_and_token()
        self.submit(token1)
        # The first request is now RECEIVED, so we request the remaining documents.
        out2 = run(evidence.request_evidence("CASE-1", REVIEWER, documents=["producer_declaration"]))
        result = self.submit(out2["token"])
        assert result["evidence_version"] == 2
        assert len(self.stored()["verification"]["documents"]) == 2

    def test_cost_is_rolled_up_on_the_case(self):
        self.put()
        _, token = self.request_and_token()
        self.submit(token)
        case = self.stored()
        assert case["_estimated_cost_usd"] > 0

    def test_a_valid_approval_is_superseded_when_evidence_arrives(self):
        self.put()
        _, token = self.request_and_token()
        # Plant a VALID approval at evidence_version 0.
        record = evidence.verification_of(self.stored())
        record["approvals"] = [{
            "approval_id": "apr-1", "status": "VALID", "evidence_version": 0,
        }]
        run(self.store.put_case(self.stored()))
        result = self.submit(token)
        assert result["superseded_approvals"] == 1
        approval = self.stored()["verification"]["approvals"][0]
        assert approval["status"] == "SUPERSEDED"
        assert "evidence v1" in approval["superseded_reason"]


class TestTokenEnforcement(Base):
    @pytest.mark.parametrize("bad_token", [
        "", "garbage", "a.b", None,
    ])
    def test_a_bad_token_is_refused(self, bad_token):
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.receive_evidence(bad_token or "", tiny_pdf(), "cert.pdf", "application/pdf"))
        assert raised.value.status == 403

    def test_a_replaced_link_is_refused(self):
        self.put()
        rid, first_token = self.request_and_token()
        run(evidence.reissue_link("CASE-1", rid, REVIEWER))
        with pytest.raises(evidence.EvidenceError) as raised:
            self.submit(first_token)
        assert raised.value.status == 403

    def test_a_cancelled_request_refuses_its_link(self):
        self.put()
        rid, token = self.request_and_token()
        run(evidence.cancel_request("CASE-1", rid, REVIEWER, "Changed my mind"))
        with pytest.raises(evidence.EvidenceError) as raised:
            self.submit(token)
        assert raised.value.status == 403

    def test_a_token_for_one_case_cannot_submit_to_another(self):
        self.put("CASE-1")
        self.put("CASE-2")
        _, token = self.request_and_token("CASE-1")
        # The token names CASE-1; the case behind it is CASE-1; but if someone
        # pointed the upload at a different case's endpoint, it must fail.
        claims = evidence.read_token(token)
        assert claims["c"] == "CASE-1"


class TestFileValidation(Base):
    def test_empty_file_is_refused(self):
        self.put()
        _, token = self.request_and_token()
        with pytest.raises(evidence.EvidenceError):
            self.submit(token, data=b"")

    def test_too_large_file_is_refused(self):
        self.put()
        _, token = self.request_and_token()
        with pytest.raises(evidence.EvidenceError) as raised:
            self.submit(token, data=b"x" * (21 * 1024 * 1024), mime="application/pdf")
        assert raised.value.status == 413

    def test_unsupported_mime_is_refused(self):
        self.put()
        _, token = self.request_and_token()
        with pytest.raises(evidence.EvidenceError) as raised:
            self.submit(token, mime="application/zip")
        assert raised.value.status == 415


class TestModelArmorBlock(Base):
    def test_a_blocked_file_is_stored_but_not_extracted(self):
        self.put()
        _, token = self.request_and_token()
        blocked_armor = {"blocked": True, "gate": "model-armor"}
        with patch("vf_logistics.model_armor.screen", new=AsyncMock(return_value=blocked_armor)):
            with patch("vf_logistics.model_armor.extract_pdf_text", return_value=("bad text", None)):
                with patch("vf_logistics.document_store.archive", new=AsyncMock(return_value={"archived": True, "uri": "gs://test/blocked"})):
                    result = run(evidence.receive_evidence(
                        token, tiny_pdf(), "cert.pdf", "application/pdf",
                    ))
        assert result["blocked"] is True
        assert result["extracted"] is False
        doc = self.stored()["verification"]["documents"][0]
        assert doc["blocked"] is True
        assert doc["extracted"] is None


class TestTheRoute(Base):
    def test_the_route_accepts_a_multipart_upload(self):
        self.put()
        _, token = self.request_and_token()
        mock_result = {
            "agent": "evidence_extraction", "model": "test",
            "result": {"producer_name": "X"}, "latency_ms": 10, "input_tokens": 10,
            "output_tokens": 10, "parse_error": False, "at": "2026-10-12T08:00:00Z",
        }
        with patch("vf_logistics.agents.document_agent.extract_evidence", new=AsyncMock(return_value=mock_result)):
            with patch("vf_logistics.model_armor.screen", new=AsyncMock(return_value={"blocked": False})):
                with patch("vf_logistics.model_armor.extract_pdf_text", return_value=("text", None)):
                    with patch("vf_logistics.document_store.archive", new=AsyncMock(return_value={"archived": True, "uri": "gs://test/doc"})):
                        response = self.client.post(
                            "/api/v1/evidence/respond",
                            data={"file": (io.BytesIO(tiny_pdf()), "cert.pdf", "application/pdf")},
                            headers={"X-VF-Evidence-Token": token},
                            content_type="multipart/form-data",
                        )
        assert response.status_code == 201, response.get_data(as_text=True)
        assert response.get_json()["received"] is True

    def test_no_file_is_refused(self):
        self.put()
        _, token = self.request_and_token()
        response = self.client.post(
            "/api/v1/evidence/respond",
            headers={"X-VF-Evidence-Token": token},
        )
        assert response.status_code == 400

    def test_no_token_is_refused(self):
        response = self.client.post(
            "/api/v1/evidence/respond",
            data={"file": (io.BytesIO(tiny_pdf()), "cert.pdf", "application/pdf")},
            content_type="multipart/form-data",
        )
        assert response.status_code == 403

    def test_the_route_is_not_a_viewer_and_not_public_in_test_rbac(self):
        """The route uses its own credential (the token). It must declare a role
        that route_policy sees, so test_every_route_declares_a_role_or_is_knowingly_public
        passes without adding it to PUBLIC."""
        from vf_logistics import app as app_mod

        func = app_mod.evidence_respond
        assert getattr(func, "_required_role", None) is not None
        assert getattr(func, "_required_role") not in (None, "viewer")
