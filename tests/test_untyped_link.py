"""
A request-level link carries no document type. With several documents requested it cannot say
which paper an upload is, so it is refused instead of filing the upload under whichever is still
missing (review VI, N03). With one document requested there is nothing to confuse.
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_evidence_eval_approve import DOCS3, PAPERS, Base, tiny_pdf  # noqa: E402
from vf_logistics import evidence  # noqa: E402

REVIEWER = "reviewer@forwarder.example"


def run(coro):
    return asyncio.run(coro)


def _receive(token, extracted):
    mock = {
        "agent": "evidence_extraction", "model": "test", "result": extracted,
        "latency_ms": 10, "input_tokens": 10, "output_tokens": 10,
        "parse_error": False, "at": "2026-10-12T08:00:00Z",
    }
    with patch("vf_logistics.agents.document_agent.extract_evidence", new=AsyncMock(return_value=mock)), \
            patch("vf_logistics.model_armor.screen", new=AsyncMock(return_value={"blocked": False})), \
            patch("vf_logistics.model_armor.extract_pdf_text", return_value=("text", None)), \
            patch("vf_logistics.document_store.archive", new=AsyncMock(return_value={"archived": True, "uri": "gs://t/d"})):
        return run(evidence.receive_evidence(token, tiny_pdf(), "doc.pdf", "application/pdf"))


class TestARequestLevelLink(Base):
    def test_with_several_documents_requested_it_is_refused(self):
        self.put()
        out = run(evidence.request_evidence("CASE-1", REVIEWER, documents=DOCS3))
        with pytest.raises(evidence.EvidenceError) as raised:
            _receive(out["token"], PAPERS["input_purchase_invoices"])
        assert raised.value.status == 400
        assert "which document" in raised.value.message
        assert self.stored()["verification"]["documents"] == []

    def test_a_typed_link_still_files_the_upload_under_its_own_type(self):
        self.put()
        out = run(evidence.request_evidence("CASE-1", REVIEWER, documents=DOCS3))
        links = {link["doc_type"]: link["token"] for link in out["links"]}
        _receive(links["input_purchase_invoices"], PAPERS["input_purchase_invoices"])
        stored = self.stored()["verification"]["documents"]
        assert [d["doc_type"] for d in stored] == ["input_purchase_invoices"]

    def test_with_one_document_requested_the_request_level_link_still_works(self):
        self.put()
        out = run(evidence.request_evidence("CASE-1", REVIEWER, documents=["certificate_of_origin"]))
        _receive(out["token"], PAPERS["certificate_of_origin"])
        stored = self.stored()["verification"]["documents"]
        assert [d["doc_type"] for d in stored] == ["certificate_of_origin"]
