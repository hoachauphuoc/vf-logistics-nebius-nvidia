"""
Document intake agent - Nebius Token Factory vision model (MiniCPM-V-4.5).

Reads a real shipping document (bill of lading, commercial invoice, packing
list) and returns the structured shipment record the rest of the pipeline
already understands. This is what turns the system from "somebody typed a
shipment into a form" into "a document landed and the workflow started".

NVIDIA has no vision model on Token Factory, so this agent uses MiniCPM-V-4.5
(OpenBMB), the catalog's OCR/PDF-focused vision model, reached through the
same OpenAI-compatible endpoint the other three agents use for text. No
separate OCR or Document AI step is needed: the bytes go straight to the
model.

Track: Best Apps and Agents
Hackathon: Nebius x NVIDIA Global AI Hackathon
"""

from __future__ import annotations

import io
import os
from typing import Any

from vf_logistics import nebius_client
from ._common import Timer, envelope, parse_model_json
from vf_logistics import config as model_config

# Output ceiling. 2,000 against a measured legitimate maximum of 377 output tokens.
#
# NOW MEASURED. This was 8,000 and explicitly a guess -- the 20-case run that produced
# every other ceiling here was event-sourced, so no vision call appeared in it. Six real
# transcriptions through scripts/test_documents.py against the deployed service:
#
#     1,151 in / 322 out     1,151 in / 261 out     1,151 in / 273 out
#     1,151 in / 377 out     1,151 in / 376 out     1,151 in / 329 out
#
# Max 377, median ~326, and the input is identical every time because the prompt is fixed
# and the image is resized. 8,000 was 21x the real maximum, far looser than the 2-3x the
# other agents run at, and loose on the most expensive model in the pipeline --
# MiniCPM-V's input rate is 11x Nano's, so a runaway here is the costliest available.
#
# 2,000 keeps 5.3x headroom. The output is structurally bounded in a way the other agents'
# is not: a fixed set of shipment fields rather than reasoning, so there is no legitimate
# path to a long reply. Truncation would reject the document rather than corrupt a case,
# because invalid JSON fails parse_model_json and the upload is refused outright.
MAX_OUTPUT_TOKENS = 2000


class DocumentConversionError(RuntimeError):
    """
    An upload could not be turned into an image for the vision model.

    Distinct from a transcription failure, because the model never ran. Carried
    as its own type so the caller can report the reason: a rasteriser missing
    from the deployment and a corrupt PDF need different fixes, and both used to
    arrive as an opaque 500 with neither reason visible.
    """

def get_model_id():
    return model_config.get_vision_model()

# Anything the pipeline reasons over has to come out of here, because a field
# the extractor drops becomes a compliance gap further downstream.
EXTRACTION_PROMPT = """
You are a document intake agent for VF Logistics. You read shipping paperwork
and transcribe it into a structured record. You are a transcriber, not an
analyst: do not score risk, do not editorialise, do not infer facts the
document does not support.

Extract exactly this JSON shape:

{
  "shipment_id": "carrier booking or B/L number as printed",
  "origin": "port or city of loading, with country",
  "destination": "port or city of discharge, with country",
  "weight_kg": number,
  "declared_value": number,
  "shipping_cost": number,
  "currency": "the currency code printed on the document",
  "shipper_name": "string",
  "shipper_company": "string",
  "shipper_country": "string",
  "shipper_tax_id": "string",
  "receiver_name": "string",
  "receiver_company": "string",
  "receiver_country": "string",
  "cargo_description": "goods description as printed",
  "hs_code": "string",
  "route_details": "routing including any transhipment",
  "transit_points": "string, or None",
  "status": "pending",
  "extraction_notes": ["anything illegible, missing, altered or internally inconsistent"],
  "extraction_confidence": 0.0
}

Rules that matter:

- Amounts must be plain numbers with no currency symbol, thousands separator or
  units. Report the currency separately in `currency`.
- If the document states amounts in a currency other than USD, still transcribe
  the printed figures and set `currency` to what is printed. Do not convert.
- For any field genuinely absent from the document, use the string "not stated"
  for text fields and 0 for numeric fields. Never invent a plausible value: a
  missing tax ID is a compliance signal, and inventing one destroys that signal.
- Put every legibility problem, missing mandatory field, alteration, or internal
  contradiction into `extraction_notes`. Downstream agents treat these as
  evidence.
- `extraction_confidence` is your own confidence in the transcription, 0 to 1.
"""

SUPPORTED_MIME = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

# Only the first page of a PDF is rasterised (see _to_image). Kept as a named
# constant so the transcription note and the tests quote the same number rather
# than two literals that can drift apart.
PDF_PAGES_READ = 1


def mime_for(filename: str) -> str | None:
    ext = os.path.splitext(filename or "")[1].lower()
    return SUPPORTED_MIME.get(ext)


async def extract_shipment(
    document_bytes: bytes, filename: str, mime_type: str | None = None
) -> dict[str, Any]:
    """
    Transcribe a shipping document into a structured shipment record.

    Returns the standard agent envelope; `result` is the shipment dict that can
    be handed straight to the orchestrator.
    """
    mime = mime_type or mime_for(filename) or "application/pdf"

    try:
        image_bytes, image_mime, page_count = _to_image(document_bytes, mime)
    except DocumentConversionError as exc:
        # Returned as an error envelope rather than raised. ingest_document
        # turns a parse_error envelope into an `accepted: false` response
        # carrying the reason, which is recorded and shown to the uploader; an
        # exception escaping here would surface as a 500 with no reason at all.
        return envelope(
            agent="document_intake",
            model=get_model_id(),
            result=None,
            error=str(exc),
            raw="",
            latency_ms=0,
            legacy_key="extraction",
            prompt=None,
            source_filename=filename,
            source_mime=mime,
        )

    with Timer() as timer:
        text, input_tokens, output_tokens = await nebius_client.complete_vision_json(
            model=get_model_id(),
            system_prompt=EXTRACTION_PROMPT,
            document_bytes=image_bytes,
            mime_type=image_mime,
            user_text="Transcribe this shipping document into the required JSON record.",
            temperature=0.0,  # transcription, not generation
            max_tokens=MAX_OUTPUT_TOKENS,
        )

    parsed, error = parse_model_json(text)
    if page_count > PDF_PAGES_READ:
        _note_unread_pages(parsed, page_count)

    return envelope(
        agent="document_intake",
        model=get_model_id(),
        result=parsed,
        error=error,
        raw=text,
        latency_ms=timer.ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        legacy_key="extraction",
        # For the caller, not for the persisted step: ingest_shipment stores a
        # fixed subset of this envelope, so these are read by ingest_document
        # and written onto the case's provenance instead. Reported as numbers
        # because the note in extraction_notes is prose, and prose in a
        # free-text list is not something a query or a test can assert on.
        source_pages=page_count,
        source_pages_read=min(page_count, PDF_PAGES_READ),
        # The document bytes are the real input here; the text instruction is
        # short and fixed, so recording it alone would be misleading.
        prompt=(
            "Transcribe this shipping document into the required JSON record. "
            f"[+ {len(image_bytes)} bytes of {image_mime} image data]"
        ),
        source_filename=filename,
        source_mime=mime,
    )


def _to_image(document_bytes: bytes, mime: str) -> tuple[bytes, str, int]:
    """
    MiniCPM-V-4.5, like most vision models on Token Factory, takes an image,
    not a PDF. PDFs are rasterised to a PNG of their first page with pypdfium2
    (Apache 2.0 / BSD-3 licensed); images pass through unchanged.

    Returns the image bytes, the image's MIME type, and how many pages the
    source had -- 1 for anything that was already an image. The page count is
    returned rather than discarded because only the first page is rendered, and
    a caller that cannot see how many pages went unread has no way to stop
    reporting a partial transcription as a complete one.
    """
    if mime != "application/pdf":
        return document_bytes, mime, 1

    try:
        import pypdfium2 as pdfium

        # Imported explicitly even though it is used only through pypdfium2's
        # bitmap.to_pil() below. pypdfium2 does not depend on Pillow, so
        # to_pil() is the one call in this file that can fail purely because of
        # what the image was built with -- naming the import makes that
        # dependency visible to the dependency files and to this guard, instead
        # of leaving it to be inferred from a method call.
        from PIL import Image  # noqa: F401
    except ImportError as exc:
        raise DocumentConversionError(
            "PDF upload requires pypdfium2 and Pillow, which are not installed "
            "in this deployment. Image uploads (.png, .jpg, .jpeg, .webp) are "
            "unaffected."
        ) from exc

    try:
        pdf = pdfium.PdfDocument(document_bytes)
        page_count = len(pdf)
        if page_count < 1:
            raise DocumentConversionError("the PDF contains no pages")
        bitmap = pdf[0].render(scale=200 / 72)  # 200 DPI
        buf = io.BytesIO()
        bitmap.to_pil().save(buf, format="PNG")
    except DocumentConversionError:
        raise
    except Exception as exc:
        # A password-protected, truncated or malformed PDF lands here. Reported
        # as a conversion failure so it reads as "this file could not be
        # opened" rather than as a transcription the model got wrong.
        raise DocumentConversionError(
            f"could not read the PDF ({type(exc).__name__}: {exc})"
        ) from exc

    return buf.getvalue(), "image/png", page_count


def _note_unread_pages(parsed: dict[str, Any] | None, page_count: int) -> None:
    """
    Record on the transcription that pages went unread.

    Only page 1 is rasterised, so a multi-page packet is transcribed from its
    first page alone. EXTRACTION_PROMPT specifies extraction_notes as the
    channel for anything missing and downstream agents treat those notes as
    evidence, so an unrecorded dropped page presents a partial reading as a
    complete one -- the same failure the prompt forbids when it bans inventing
    an absent tax ID.

    Prepended, not appended: sanitise_shipment truncates the list to 20 entries,
    and missing input outranks the twentieth legibility remark for the place
    that survives. Mutates in place because the caller passes `parsed` straight
    to envelope().
    """
    if not isinstance(parsed, dict):
        return

    notes = parsed.get("extraction_notes")
    if isinstance(notes, list):
        existing = list(notes)
    elif isinstance(notes, str) and notes.strip():
        # Some replies return a single note as a bare string rather than a list.
        existing = [notes]
    else:
        existing = []

    unread = page_count - PDF_PAGES_READ
    # Only the noun is pluralised. The verb stays singular because the subject
    # is "Any detail", not the page count -- "any detail on the remaining 2
    # pages is absent" is correct, and agreeing the verb with "pages" instead
    # reads as a typo in something a reviewer is meant to trust.
    noun = "page" if unread == 1 else "pages"
    parsed["extraction_notes"] = [
        f"Source PDF had {page_count} pages; only page {PDF_PAGES_READ} was "
        f"transcribed. Any detail on the remaining {unread} {noun} is absent "
        f"from this record.",
        *existing,
    ]


def get_agent_info() -> dict[str, Any]:
    return {
        "name": "VF Logistics Document Intake Agent",
        "version": "1.0.0",
        "model": get_model_id(),
        "capabilities": [
            "pdf_transcription",
            "scanned_image_transcription",
            "shipment_field_extraction",
            "missing_field_detection",
        ],
        "supported_types": sorted(SUPPORTED_MIME),
    }
