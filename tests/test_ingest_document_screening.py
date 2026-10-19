"""
Document intake, by what the screening decided: a blocked document never reaches the vision model and waits
for a person; a PDF whose text layer could not be read is flagged rather than trusted; a scan is screened
after transcription; a clean one flows on; a document with no booking number gets a synthetic id.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(__file__))
from test_evidence_eval_approve import Base, run  # noqa: E402
from vf_logistics import orchestrator  # noqa: E402

ARCHIVED = {"archived": True, "uri": "gs://t/doc"}
TRANSCRIPTION = {
    "result": {"shipment_id": "BL-77", "shipper_name": "Saigon Plywood", "declared_value": 1000},
    "model": "m", "latency_ms": 120, "input_tokens": 10, "output_tokens": 5, "at": "2026-10-12T03:00:00Z",
}
CLEAN = {"blocked": False, "available": True, "provider": "armor"}


class DocumentBase(Base):
    def ingest(self, filename="bl.pdf", mime="application/pdf", text=("some text", None), screens=(CLEAN,), response=None):
        extract = AsyncMock(return_value=response or TRANSCRIPTION)
        screen = AsyncMock(side_effect=list(screens))
        with patch.object(orchestrator, "extract_shipment", new=extract), \
                patch.object(orchestrator.model_armor, "extract_pdf_text", return_value=text), \
                patch.object(orchestrator.model_armor, "screen", new=screen), \
                patch.object(orchestrator.document_store, "archive", new=AsyncMock(return_value=ARCHIVED)):
            result = run(orchestrator.ingest_document(b"%PDF", filename, mime))
        self.extract, self.screen = extract, screen
        return result


class TestABlockedDocument(DocumentBase):
    BLOCKED = {"blocked": True, "available": True, "detail": "prompt injection", "confidence": "HIGH"}

    def test_it_never_reaches_the_vision_model_and_waits_for_a_person(self):
        result = self.ingest(screens=(self.BLOCKED,))
        assert (result["accepted"], result["blocked"], result["state"]) == (True, True, "PENDING_HUMAN")
        self.extract.assert_not_called()
        case = self.stored(result["case_id"])
        assert case["requires_human"] is True
        assert case["input_security"]["model_invoked"] is False
        assert case["proposed_outcome"] is None
        assert "no model was invoked" in case["gate_denials"][0]["reason"]
        assert case["provenance"]["filename"] == "bl.pdf"

    def test_the_security_event_says_no_tokens_were_spent(self):
        with patch.object(orchestrator, "emit", new=AsyncMock()) as emit:
            self.ingest(screens=(self.BLOCKED,))
        security = [c for c in emit.call_args_list if c.args[1] == "security"]
        assert "No tokens spent" in security[0].args[2]


class TestAPdfWhoseTextCouldNotBeRead(DocumentBase):
    def test_it_is_still_read_but_flagged_for_a_person(self):
        result = self.ingest(text=("", "encrypted"), screens=(CLEAN,))
        assert result["accepted"] is True
        case = self.stored(result["case_id"])
        assert case["requires_human"] is True
        assert case["input_security"]["screened_before_model"] is False
        assert "could not read PDF text layer: encrypted" in case["input_security"]["model_armor"]["detail"]

    def test_the_event_names_the_unavailable_screen(self):
        with patch.object(orchestrator, "emit", new=AsyncMock()) as emit:
            self.ingest(text=("", "encrypted"), screens=(CLEAN,))
        message = [c for c in emit.call_args_list if c.args[1] == "security"][0].args[2]
        assert "Model Armor unavailable" in message


class TestAScan(DocumentBase):
    def test_a_scan_is_screened_after_transcription(self):
        result = self.ingest(filename="scan.jpg", mime="image/jpeg", screens=(CLEAN,))
        assert result["accepted"] is True
        assert self.screen.call_args.kwargs["stage"] == "after_transcription"
        case = self.stored(result["case_id"])
        assert case["input_security"]["screened_before_model"] is False
        assert not case.get("requires_human")

    def test_a_scan_the_screen_blocks_is_flagged_after_the_fact(self):
        result = self.ingest(filename="scan.jpg", mime="image/jpeg", screens=({"blocked": True, "detail": "x"},))
        case = self.stored(result["case_id"])
        assert case["requires_human"] is True


class TestACleanTextPdf(DocumentBase):
    def test_it_is_screened_before_the_model_and_not_flagged(self):
        result = self.ingest(screens=(CLEAN,))
        assert result["accepted"] is True and result["shipment_id"] == "BL-77"
        assert self.screen.call_args.kwargs["stage"] == "before_model"
        case = self.stored(result["case_id"])
        assert case["input_security"]["screened_before_model"] is True
        assert case["input_security"]["model_invoked"] is True
        assert not case.get("requires_human")

    def test_a_transcription_that_failed_is_refused_with_its_reason(self):
        result = self.ingest(response={"parse_error": True, "error": "unreadable page", "latency_ms": 5})
        assert result == {"accepted": False, "error": "unreadable page", "latency_ms": 5}

    def test_an_empty_transcription_gets_the_default_reason(self):
        result = self.ingest(response={"result": {}, "latency_ms": 5})
        assert result["error"] == "document could not be transcribed"

    def test_a_document_with_no_booking_number_gets_a_synthetic_one(self):
        raw = {**TRANSCRIPTION["result"], "shipment_id": "not stated"}
        result = self.ingest(response={**TRANSCRIPTION, "result": raw})
        assert result["shipment_id"].startswith("DOC-")
        assert result["case_id"] == f"CASE-{result['shipment_id']}"
