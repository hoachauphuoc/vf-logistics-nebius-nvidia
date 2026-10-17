"""
The evaluation a reviewer reads says WHY a received paper is unresolved when the reader only
saw part of it (review VI, N06-B).
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(__file__))
from test_evidence_eval_approve import DOCS3, PAPERS, Base, tiny_pdf  # noqa: E402
from vf_logistics import evidence  # noqa: E402

REVIEWER = "reviewer@forwarder.example"


def run(coro):
    return asyncio.run(coro)


class TestTheEvaluationSaysWhatWasNotRead(Base):
    def _submit_read_in_part(self, links):
        for doc_type, extracted in PAPERS.items():
            mock = {
                "agent": "evidence_extraction", "model": "test", "result": extracted,
                "latency_ms": 10, "input_tokens": 10, "output_tokens": 10,
                "parse_error": False, "at": "2026-10-12T08:00:00Z",
                "source_pages": 2, "source_pages_read": 1,
            }
            with patch("vf_logistics.agents.document_agent.extract_evidence", new=AsyncMock(return_value=mock)), \
                    patch("vf_logistics.model_armor.screen", new=AsyncMock(return_value={"blocked": False})), \
                    patch("vf_logistics.model_armor.extract_pdf_text", return_value=("text", None)), \
                    patch("vf_logistics.document_store.archive", new=AsyncMock(return_value={"archived": True, "uri": "gs://t/d"})):
                run(evidence.receive_evidence(links[doc_type], tiny_pdf(), f"{doc_type}.pdf", "application/pdf"))

    def test_a_received_paper_read_in_part_is_unresolved_and_says_why(self):
        self.put()
        out = run(evidence.request_evidence("CASE-1", REVIEWER, documents=DOCS3))
        links = {link["doc_type"]: link["token"] for link in out["links"]}
        self._submit_read_in_part(links)
        evaluation = run(evidence.reevaluate("CASE-1"))["evaluation"]
        assert evaluation["status"] == "missing"
        assert sorted(evaluation["unresolved"]) == sorted(DOCS3)
        assert sorted(u["doc_type"] for u in evaluation["unread"]) == sorted(DOCS3)
        assert {(u["pages"], u["pages_read"]) for u in evaluation["unread"]} == {(2, 1)}
