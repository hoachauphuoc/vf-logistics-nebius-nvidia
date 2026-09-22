"""
The document upload contract: which files are accepted, and what happens to the
ones that are not.

Written because this path had no tests at all, which is how it came to rest on an
undeclared dependency. `_to_image()` rasterises an uploaded PDF and reaches
Pillow through pypdfium2's `bitmap.to_pil()`, but nothing in src/ imports PIL by
name -- so Pillow was present in the deployed image only as a transitive of
fpdf2, an unrelated package used for *generating* bills of lading. Removing or
replacing fpdf2 would have dropped Pillow from the lock and broken every PDF
upload in production while PNG, JPG and WebP carried on working.

The tests below therefore do two jobs. They pin the accepted-type list that the
415 response and the upload UI both quote, and they actually exercise the PDF
branch, which had never run outside the container.
"""

from __future__ import annotations

import io
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics import untrusted  # noqa: E402
from vf_logistics.agents.document_agent import (  # noqa: E402
    PDF_PAGES_READ,
    SUPPORTED_MIME,
    DocumentConversionError,
    _note_unread_pages,
    _to_image,
    extract_shipment,
    get_agent_info,
    mime_for,
)

# The five the service accepts. Written out rather than derived from
# SUPPORTED_MIME so that widening the set is a deliberate edit to this list --
# a new format needs a converter and its own screening story, and should not
# arrive as an incidental consequence of a dict change elsewhere.
EXPECTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}


def _pdf_bytes(*sizes: tuple[int, int]) -> bytes:
    """A PDF with one page per (width, height) in points."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument.new()
    for width, height in sizes:
        pdf.new_page(width, height)
    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


def _png_bytes(size: tuple[int, int] = (8, 8)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


class MimeDetectionTests(unittest.TestCase):
    def test_every_supported_extension_maps_to_a_mime_type(self):
        self.assertEqual(set(SUPPORTED_MIME), EXPECTED_EXTENSIONS)
        for ext in EXPECTED_EXTENSIONS:
            self.assertIsNotNone(mime_for(f"bill-of-lading{ext}"), ext)

    def test_jpg_and_jpeg_agree(self):
        self.assertEqual(mime_for("scan.jpg"), mime_for("scan.jpeg"))
        self.assertEqual(mime_for("scan.jpg"), "image/jpeg")

    def test_extension_matching_ignores_case(self):
        """
        Scanners and phone cameras produce uppercase extensions routinely, so a
        case-sensitive check would reject ordinary files.
        """
        for name in ("SCAN.PDF", "Scan.Pdf", "photo.WEBP", "photo.JPEG"):
            self.assertIsNotNone(mime_for(name), name)

    def test_unsupported_types_are_refused(self):
        """
        These are the plausible near-misses: raster formats the vision model
        cannot be handed, and office documents that would need a converter.
        """
        for name in (
            "scan.tiff", "scan.tif", "scan.gif", "scan.bmp", "photo.heic",
            "contract.docx", "manifest.xlsx", "packet.zip", "notes.txt",
        ):
            self.assertIsNone(mime_for(name), name)

    def test_a_filename_without_an_extension_is_refused(self):
        for name in ("document", "", "   ", ".pdf.exe", "pdf"):
            self.assertIsNone(mime_for(name), repr(name))

    def test_a_bare_dotfile_is_not_mistaken_for_a_type(self):
        # splitext(".pdf") yields ("", ".pdf") -- an extension with no stem. It
        # is a hidden file, not a document, and must not be accepted.
        self.assertIsNone(mime_for(".pdf"))

    def test_advertised_types_match_what_is_accepted(self):
        """
        get_agent_info() feeds /api/v1/config and the `supported` list in the 415
        response, which is what the UI shows the user. If it drifts from
        SUPPORTED_MIME the service tells people to send a file it then rejects.
        """
        self.assertEqual(set(get_agent_info()["supported_types"]), EXPECTED_EXTENSIONS)


class PdfRasterisationTests(unittest.TestCase):
    """
    The PDF branch. Not skipped when pypdfium2 is absent: a skip here restores
    exactly the blind spot these tests exist to close, so a missing rasteriser
    must fail the suite.
    """

    def test_a_pdf_becomes_a_png(self):
        out, mime, pages = _to_image(_pdf_bytes((400, 400)), "application/pdf")
        self.assertEqual(mime, "image/png")
        self.assertEqual(pages, 1)
        self.assertTrue(out.startswith(b"\x89PNG"), "not PNG-encoded")

    def test_rasterisation_is_200_dpi(self):
        """
        A 400x400pt page at 200 DPI is ~1111px. Asserted because resolution is
        the difference between a legible scan and an unreadable one, and a
        silent drop to 72 DPI would degrade every extraction without erroring.
        """
        out, _, _ = _to_image(_pdf_bytes((400, 400)), "application/pdf")
        from PIL import Image

        width, height = Image.open(io.BytesIO(out)).size
        expected = round(400 * 200 / 72)
        self.assertAlmostEqual(width, expected, delta=2)
        self.assertAlmostEqual(height, expected, delta=2)

    def test_images_pass_through_untouched(self):
        original = _png_bytes()
        for mime in ("image/png", "image/jpeg", "image/webp"):
            out, out_mime, pages = _to_image(original, mime)
            self.assertIs(out, original, f"{mime} was re-encoded")
            self.assertEqual(out_mime, mime)
            self.assertEqual(pages, 1)

    def test_a_multi_page_pdf_reports_its_full_page_count(self):
        """
        The count is the whole point: only page 1 is rendered, so a caller that
        cannot see the other pages existed cannot report the loss.
        """
        _, _, pages = _to_image(
            _pdf_bytes((400, 400), (800, 200), (400, 400)), "application/pdf"
        )
        self.assertEqual(pages, 3)

    def test_only_the_first_page_is_rendered(self):
        """Page 1 is 400x400pt and page 2 is 800x200pt, so the output size says
        which one the model would have been given."""
        out, _, _ = _to_image(_pdf_bytes((400, 400), (800, 200)), "application/pdf")
        from PIL import Image

        width, height = Image.open(io.BytesIO(out)).size
        self.assertAlmostEqual(width, height, delta=2, msg="rendered page 2, not page 1")

    def test_an_unreadable_pdf_is_reported_as_a_conversion_failure(self):
        with self.assertRaises(DocumentConversionError) as caught:
            _to_image(b"this is not a PDF at all", "application/pdf")
        self.assertIn("could not read the PDF", str(caught.exception))

    def test_a_missing_rasteriser_names_itself(self):
        """
        The regression guard for the undeclared-Pillow gap. A None entry in
        sys.modules makes the import raise ImportError, which is what an image
        built without pypdfium2 or Pillow would do.

        The assertion is on the *content* of the message: "PDF support is
        missing from this deployment" and "this PDF is corrupt" call for
        completely different fixes, and before this they were the same 500.
        """
        for absent in ("pypdfium2", "PIL"):
            with self.subTest(module=absent):
                # Built before the patch: _pdf_bytes needs the very module the
                # patch removes.
                document = _pdf_bytes((400, 400))
                with patch.dict(sys.modules, {absent: None}):
                    with self.assertRaises(DocumentConversionError) as caught:
                        _to_image(document, "application/pdf")
                message = str(caught.exception)
                self.assertIn("not installed", message)
                self.assertIn("pypdfium2", message)
                self.assertIn("Pillow", message)
                # Names the types that still work, so the operator reading it
                # knows upload is degraded rather than down.
                self.assertIn(".png", message)


class UnreadPageNoteTests(unittest.TestCase):
    def test_the_note_records_the_page_count(self):
        parsed = {"extraction_notes": []}
        _note_unread_pages(parsed, 4)
        self.assertIn("4 pages", parsed["extraction_notes"][0])

    def test_the_note_comes_first(self):
        """
        Prepended so it survives sanitise_shipment's 20-note cap. See the
        truncation test below for why that matters.
        """
        parsed = {"extraction_notes": ["weight illegible", "no tax id"]}
        _note_unread_pages(parsed, 2)
        self.assertEqual(len(parsed["extraction_notes"]), 3)
        self.assertIn("only page", parsed["extraction_notes"][0])
        self.assertEqual(parsed["extraction_notes"][1:], ["weight illegible", "no tax id"])

    def test_the_note_survives_note_truncation(self):
        """
        sanitise_shipment keeps only the first 20 notes. A model that returned 25
        legibility remarks would have pushed an appended page-loss note off the
        end -- and dropped input outranks the twenty-first remark.
        """
        parsed = {"extraction_notes": [f"remark {i}" for i in range(25)]}
        _note_unread_pages(parsed, 3)
        notes = untrusted.sanitise_shipment(parsed)["extraction_notes"]
        self.assertEqual(len(notes), 20)
        self.assertIn("only page", notes[0])

    def test_the_count_is_written_in_the_right_number(self):
        """
        The noun is pluralised; the verb is not. "Any detail" is the subject, so
        it stays "is absent" at every count -- asserted because an earlier
        version agreed the verb with the page count instead and shipped
        "2 pages are absent" into a reviewer-facing note.
        """
        two, four = {"extraction_notes": []}, {"extraction_notes": []}
        _note_unread_pages(two, 2)
        _note_unread_pages(four, 4)
        self.assertIn("remaining 1 page is absent", two["extraction_notes"][0])
        self.assertIn("remaining 3 pages is absent", four["extraction_notes"][0])
    def test_a_missing_or_malformed_notes_key_is_tolerated(self):
        """The notes come back from a model, so the key may be absent, null, or
        a bare string rather than a list."""
        for notes in ({}, {"extraction_notes": None}, {"extraction_notes": ""}):
            parsed = dict(notes)
            _note_unread_pages(parsed, 2)
            self.assertEqual(len(parsed["extraction_notes"]), 1)

        single = {"extraction_notes": "only remark"}
        _note_unread_pages(single, 2)
        self.assertEqual(single["extraction_notes"][1], "only remark")

    def test_a_failed_parse_is_tolerated(self):
        # parse_model_json returns None for unparseable output; the note helper
        # runs before envelope() and must not turn that into a second error.
        _note_unread_pages(None, 3)


class ExtractShipmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_conversion_failure_becomes_an_envelope_not_an_exception(self):
        """
        ingest_document turns a parse_error envelope into `accepted: false` with
        the reason attached, which is recorded on the case and shown to the
        uploader. An exception escaping extract_shipment would instead be an
        unhandled 500 carrying no reason.
        """
        with patch("vf_logistics.nebius_client.complete_vision_json") as model:
            response = await extract_shipment(b"not a pdf", "broken.pdf")

        model.assert_not_called()  # no tokens spent on a file that never converted
        self.assertTrue(response["parse_error"])
        self.assertIn("could not read the PDF", response["error"])
        self.assertEqual(response["result"], {})
        self.assertEqual(response["source_filename"], "broken.pdf")

    async def test_a_multi_page_upload_carries_the_page_count_through(self):
        reply = '{"shipment_id": "BL-1", "extraction_notes": ["stamp smudged"]}'
        with patch(
            "vf_logistics.nebius_client.complete_vision_json",
            new=AsyncMock(return_value=(reply, 10, 20)),
        ):
            response = await extract_shipment(
                _pdf_bytes((400, 400), (400, 400), (400, 400)), "packet.pdf"
            )

        self.assertFalse(response["parse_error"])
        self.assertEqual(response["source_pages"], 3)
        self.assertEqual(response["source_pages_read"], PDF_PAGES_READ)
        notes = response["result"]["extraction_notes"]
        self.assertIn("3 pages", notes[0])
        self.assertIn("stamp smudged", notes)

    async def test_a_single_page_upload_gets_no_note(self):
        """The note is a warning. Adding it to every upload would make it
        meaningless, and downstream agents read notes as evidence."""
        reply = '{"shipment_id": "BL-2", "extraction_notes": []}'
        with patch(
            "vf_logistics.nebius_client.complete_vision_json",
            new=AsyncMock(return_value=(reply, 10, 20)),
        ):
            response = await extract_shipment(_pdf_bytes((400, 400)), "single.pdf")

        self.assertEqual(response["source_pages"], 1)
        self.assertEqual(response["result"]["extraction_notes"], [])

    async def test_an_image_upload_is_sent_as_its_own_type(self):
        """A PNG must not be relabelled application/pdf on the way to the model,
        which is what the old `or "application/pdf"` fallback did on any path
        that lost the mime."""
        reply = '{"shipment_id": "BL-3"}'
        sender = AsyncMock(return_value=(reply, 1, 1))
        with patch("vf_logistics.nebius_client.complete_vision_json", new=sender):
            await extract_shipment(_png_bytes(), "scan.png")

        self.assertEqual(sender.await_args.kwargs["mime_type"], "image/png")


class UploadRouteTests(unittest.TestCase):
    """
    The validation ladder in /api/v1/events/document, in the order the route
    applies it. None of these reach a model.
    """

    def setUp(self):
        self.env = patch.dict(os.environ, {
            "STORE_BACKEND": "memory",
            "IAP_ENABLED": "false",
            "MAX_DOCUMENT_MB": "1",  # keeps the oversize case cheap
        })
        self.env.start()
        self.addCleanup(self.env.stop)

        from vf_logistics import app as app_mod

        app_mod.app.config["TESTING"] = True
        # The route is rate limited to 10/min against in-memory storage shared
        # across the session, so a full-suite run could 429 these instead of
        # exercising them.
        self._limiter_was = app_mod.limiter.enabled
        app_mod.limiter.enabled = False
        self.addCleanup(setattr, app_mod.limiter, "enabled", self._limiter_was)
        self.client = app_mod.app.test_client()

    def _post(self, data):
        return self.client.post(
            "/api/v1/events/document",
            data=data,
            content_type="multipart/form-data",
        )

    def test_no_file_is_a_400(self):
        response = self._post({})
        self.assertEqual(response.status_code, 400)
        self.assertIn("file", response.get_json()["error"])

    def test_the_form_field_must_be_named_file(self):
        """The UI and any API client have to agree on the field name; a wrong
        one must say so rather than look like an empty upload."""
        response = self._post({"document": (io.BytesIO(b"%PDF-1.4"), "a.pdf")})
        self.assertEqual(response.status_code, 400)

    def test_an_unsupported_type_is_a_415_that_says_what_is_accepted(self):
        """
        The `supported` list is the remedy, not decoration -- it is what the
        console shows the user after a rejected file. Asserted non-empty and
        complete so it cannot quietly become an empty array.
        """
        response = self._post({"file": (io.BytesIO(b"PK\x03\x04"), "contract.docx")})
        self.assertEqual(response.status_code, 415)

        body = response.get_json()
        self.assertIn("contract.docx", body["error"])
        self.assertEqual(set(body["supported"]), EXPECTED_EXTENSIONS)

    def test_an_empty_file_is_a_400(self):
        response = self._post({"file": (io.BytesIO(b""), "empty.pdf")})
        self.assertEqual(response.status_code, 400)
        self.assertIn("empty", response.get_json()["error"].lower())

    def test_a_file_over_the_cap_is_a_413(self):
        oversize = b"%PDF-1.4" + b"\x00" * (2 * 1024 * 1024)
        response = self._post({"file": (io.BytesIO(oversize), "huge.pdf")})
        self.assertEqual(response.status_code, 413)
        self.assertIn("1MB", response.get_json()["error"])

    def test_the_cap_is_configurable(self):
        """MAX_DOCUMENT_MB is read per request, so an operator raising it does
        not need a redeploy. Verified by moving it under a fixed payload."""
        payload = b"%PDF-1.4" + b"\x00" * (2 * 1024 * 1024)
        with patch.dict(os.environ, {"MAX_DOCUMENT_MB": "5"}):
            response = self._post({"file": (io.BytesIO(payload), "ok.pdf")})
        # Past the size gate: it now fails on conversion instead, which is a
        # different and later failure.
        self.assertNotEqual(response.status_code, 413)


class ProvenanceTests(unittest.IsolatedAsyncioTestCase):
    """
    Where the page count ends up on the stored case.

    Its first home was the agent envelope, which turned out to be the wrong
    one: ingest_shipment persists a fixed subset of the envelope, so
    `source_pages` was silently dropped exactly as the pre-existing
    `source_mime` already was. Verified against the case now, not against the
    envelope, because the envelope told a comforting and untrue story.
    """

    async def test_the_page_count_reaches_the_stored_case(self):
        os.environ["STORE_BACKEND"] = "memory"
        from vf_logistics import orchestrator

        reply = (
            '{"shipment_id": "BL-PROV-1", "shipper_company": "Acme", '
            '"extraction_notes": []}'
        )
        with patch(
            "vf_logistics.nebius_client.complete_vision_json",
            new=AsyncMock(return_value=(reply, 10, 20)),
        ):
            result = await orchestrator.ingest_document(
                _pdf_bytes((400, 400), (400, 400)), "packet.pdf", "application/pdf"
            )

        self.assertTrue(result["accepted"], result.get("error"))

        case = await orchestrator.get_store().get_case(result["case_id"])
        provenance = case["provenance"]
        self.assertEqual(provenance["pages"], 2)
        self.assertEqual(provenance["pages_read"], PDF_PAGES_READ)
        self.assertEqual(provenance["filename"], "packet.pdf")

    async def test_the_note_reaches_the_stored_case(self):
        """
        The note is what a reviewer reads, so it has to survive sanitisation and
        persistence -- not merely be returned by the agent.
        """
        os.environ["STORE_BACKEND"] = "memory"
        from vf_logistics import orchestrator

        reply = (
            '{"shipment_id": "BL-PROV-2", "shipper_company": "Acme", '
            '"extraction_notes": ["seal number smudged"]}'
        )
        with patch(
            "vf_logistics.nebius_client.complete_vision_json",
            new=AsyncMock(return_value=(reply, 10, 20)),
        ):
            result = await orchestrator.ingest_document(
                _pdf_bytes((400, 400), (400, 400), (400, 400)),
                "three.pdf",
                "application/pdf",
            )

        case = await orchestrator.get_store().get_case(result["case_id"])
        notes = case["steps"][0]["result"]["extraction_notes"]
        self.assertIn("3 pages", notes[0])
        self.assertIn("seal number smudged", notes)

    async def test_a_conversion_failure_is_refused_rather_than_raised(self):
        """
        End to end: a file that cannot be rasterised must come back as a refusal
        carrying the reason. Raising instead would be an unhandled 500, which is
        what this path did before.
        """
        os.environ["STORE_BACKEND"] = "memory"
        from vf_logistics import orchestrator

        with patch("vf_logistics.nebius_client.complete_vision_json") as model:
            result = await orchestrator.ingest_document(
                b"\x00", "broken.pdf", "application/pdf"
            )

        model.assert_not_called()
        self.assertFalse(result["accepted"])
        self.assertIn("could not read the PDF", result["error"])


if __name__ == "__main__":
    unittest.main()
