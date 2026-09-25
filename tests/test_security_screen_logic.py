"""
The parts of the security screen that are logic, not a mocked GCP call.

`tests/test_decision_paths.py` excluded this module wholesale on the grounds that you
"mock a GCP service and you test the mock". That is exactly right for `_sanitize_once`,
which is one HTTP POST and a response parse -- patching the client and asserting the
patch came back proves nothing -- and for `_access_token`, which needs a fake
`google.auth` injected into `sys.modules`. Neither is tested here, deliberately.

It is NOT right for the rest, and the same file's own criterion is why: "a line which
can release a controlled consignment deserves a test". These do:

  `_windows`            pure arithmetic over a string; no GCP anywhere in it
  `screen("   ")`       an early return that contacts nothing
  the failure paths     whether the screen FAILS CLOSED when every window errors, which
                        is a security property rather than a transport detail
  `extract_pdf_text`    pypdf, not GCP; one unreadable page must not lose the others

Constraint that shapes every test below: the module's tuning constants are read at
IMPORT time (`model_armor.py:37-51`), so `monkeypatch.setenv` does nothing after import.
The function bodies read them as globals at call time, so `patch.object` works. Note
`ENDPOINT` is derived from `LOCATION` at import, so patching `LOCATION` does not move
the endpoint -- which does not matter here, because nothing in this file makes a request.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics import model_armor  # noqa: E402


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestWindowing(unittest.TestCase):
    """
    `_windows` exists for a measured reason recorded in its own docstring: the filter
    returned NO_MATCH_FOUND on a 1,150-character bill of lading carrying an injection
    it flagged at MEDIUM_AND_ABOVE when the same 275 characters were sent alone. The
    signal is diluted by surrounding legitimate text.

    Untested until now because both existing fixtures are short -- INJECTED is about
    188 characters and INNOCENT_BOL about 218, against a 400-character threshold -- so
    every existing test took the single-window path at line 134 and never entered the
    loop.
    """

    def test_short_text_is_one_window_and_is_not_copied(self):
        text = "a" * 100
        self.assertEqual(model_armor._windows(text), [text])

    def test_the_whole_document_is_always_the_first_window(self):
        """
        Deliberate, and the comment at line 137 says why: it is the cheapest path to a
        match. If the whole document trips the filter there is no reason to pay for
        eight more calls, and `screen` returns on the first MATCH_FOUND.
        """
        text = "b" * 1000
        windows = model_armor._windows(text)
        self.assertGreater(len(windows), 1)
        self.assertEqual(windows[0], text, "windows[0] must be the entire document")

    def test_the_window_count_is_capped(self):
        """
        MAX_WINDOWS + 1 entries, not MAX_WINDOWS -- the +1 is the whole document. A
        1MB PDF must not become a thousand billable calls.
        """
        text = "c" * 100_000
        windows = model_armor._windows(text)
        self.assertEqual(len(windows), model_armor.MAX_WINDOWS + 1)

    def test_windows_overlap_so_a_payload_cannot_be_split_in_half(self):
        with patch.object(model_armor, "WINDOW_CHARS", 10), \
             patch.object(model_armor, "WINDOW_OVERLAP", 4), \
             patch.object(model_armor, "MAX_WINDOWS", 8):
            windows = model_armor._windows("0123456789abcdefghij")
        # step = 10 - 4 = 6, so the second and third windows share four characters.
        self.assertEqual(windows[1], "0123456789")
        self.assertEqual(windows[2], "6789abcdef")
        self.assertTrue(
            windows[1][-4:] == windows[2][:4],
            "consecutive windows must overlap by WINDOW_OVERLAP characters",
        )

    def test_whitespace_only_chunks_are_skipped(self):
        with patch.object(model_armor, "WINDOW_CHARS", 5), \
             patch.object(model_armor, "WINDOW_OVERLAP", 0), \
             patch.object(model_armor, "MAX_WINDOWS", 20):
            windows = model_armor._windows("abcde     fghij")
        self.assertNotIn("     ", windows, "a window of pure whitespace costs a call "
                                           "and cannot contain an injection")


class TestNothingToScreen(unittest.TestCase):
    """
    The one path that reports success without contacting anything.

    Neighbour of an existing test (`test_screen_layers.py:140` covers an unconfigured
    template) but a different branch: that one has TEMPLATE empty, this one has TEMPLATE
    set and the text empty.
    """

    def test_empty_text_is_available_without_a_single_call(self):
        with patch.object(model_armor, "TEMPLATE", "a-template"), \
             patch.object(model_armor, "_access_token") as token, \
             patch.object(model_armor, "_sanitize_once", new_callable=AsyncMock) as once:
            verdict = run(model_armor.screen("   ", "test"))

        self.assertTrue(verdict["available"])
        self.assertEqual(verdict["detail"], "no text to screen")
        self.assertFalse(verdict["blocked"])
        self.assertEqual(verdict["windows_screened"], 0)
        token.assert_not_called()
        once.assert_not_called()

    def test_empty_text_does_not_ask_for_a_person(self):
        """
        `requires_human` is absent rather than False -- it is only ever added by the
        three paths that need it. An empty document is not suspicious, so nothing is
        flagged, and a caller reading `verdict.get("requires_human")` gets None.
        """
        with patch.object(model_armor, "TEMPLATE", "a-template"):
            verdict = run(model_armor.screen("", "test"))
        self.assertNotIn("requires_human", verdict)


class TestFailClosed(unittest.TestCase):
    """
    The property that matters most in this module and was covered nowhere: when the
    screen cannot reach a verdict, does it ask for a person or does it wave the
    shipment through?

    Existing coverage stops one branch short. `test_screen_layers.py:126` proves the
    no-credentials path sets `requires_human` -- that is the return at line 214-217,
    reached before any window is attempted. Below is the other shape: credentials are
    fine, requests are attempted, and every one of them fails.
    """

    def _screen_with(self, sanitize, text="x" * 50):
        with patch.object(model_armor, "TEMPLATE", "a-template"), \
             patch.object(model_armor, "_access_token", return_value="tok"), \
             patch.object(model_armor, "_sanitize_once", sanitize):
            return run(model_armor.screen(text, "test"))

    def test_every_window_raising_asks_for_a_person(self):
        verdict = self._screen_with(
            AsyncMock(side_effect=RuntimeError("connection reset"))
        )
        self.assertTrue(
            verdict["requires_human"],
            "an unreachable screen must fail closed, not report a clean document",
        )
        self.assertFalse(verdict["available"])
        self.assertFalse(verdict["blocked"])
        self.assertIn("RuntimeError", verdict["detail"])

    def test_a_raised_window_is_not_counted_as_screened(self):
        """
        The asymmetry between the two failure branches, and it is not cosmetic:
        `windows_screened` is set at line 229, AFTER the try/except, so an exception
        skips it entirely. A window that threw was never screened and the count must
        not imply otherwise.
        """
        verdict = self._screen_with(AsyncMock(side_effect=RuntimeError("boom")))
        self.assertEqual(verdict["windows_screened"], 0)

    def test_every_window_returning_an_error_asks_for_a_person(self):
        verdict = self._screen_with(
            AsyncMock(return_value={"error": "HTTP 503: upstream unavailable"})
        )
        self.assertTrue(verdict["requires_human"])
        self.assertFalse(verdict["available"])
        self.assertIn("503", verdict["detail"])

    def test_an_errored_window_IS_counted_as_screened(self):
        """
        The other half of the asymmetry. Line 229 runs before the error check at 231,
        so a window that answered -- even with an error -- increments the count while
        `available` stays False. Worth pinning because the two numbers disagreeing is
        the signal that the screen answered but could not conclude.
        """
        verdict = self._screen_with(
            AsyncMock(return_value={"error": "HTTP 429: rate limited"})
        )
        self.assertEqual(verdict["windows_screened"], 1)
        self.assertFalse(verdict["available"])

    def test_the_detail_carries_at_most_three_errors(self):
        """
        `"; ".join(errors[:3])` at line 257. A 1MB PDF failing on nine windows must not
        put nine stack-trace fragments into a field a reviewer reads.
        """
        with patch.object(model_armor, "WINDOW_CHARS", 10), \
             patch.object(model_armor, "WINDOW_OVERLAP", 0), \
             patch.object(model_armor, "MAX_WINDOWS", 8):
            verdict = self._screen_with(
                AsyncMock(return_value={"error": "E"}), text="y" * 200,
            )
        self.assertLessEqual(verdict["detail"].count("E"), 3)

    def test_one_surviving_window_is_enough_to_report_available(self):
        """
        Partial failure, and the concatenation at line 266 that reports it. Not
        fail-closed -- one clean answer is a real answer -- but the reviewer is told
        some windows errored rather than being shown a bare all-clear.
        """
        outcomes = [
            {"error": "HTTP 503: first window died"},
            {"match_state": "NO_MATCH_FOUND", "confidence": None, "filter_match": None},
        ]
        with patch.object(model_armor, "WINDOW_CHARS", 10), \
             patch.object(model_armor, "WINDOW_OVERLAP", 0), \
             patch.object(model_armor, "MAX_WINDOWS", 8):
            verdict = self._screen_with(
                AsyncMock(side_effect=outcomes), text="z" * 15,
            )
        self.assertTrue(verdict["available"])
        self.assertFalse(verdict["blocked"])
        self.assertNotIn("requires_human", verdict)
        self.assertIn("errored", verdict["detail"])


class TestPdfTextExtraction(unittest.TestCase):
    """
    pypdf, not GCP, so the exclusion reason does not apply.

    The existing document tests drive real PDFs through `orchestrator.ingest_document`,
    which covers the happy path and the corrupt-file path. Neither reaches the
    per-page swallow at line 87-88, and that branch carries a promise the comment
    states outright: one bad page must not lose the rest.
    """

    def _reader_with_pages(self, *page_behaviours):
        pages = []
        for behaviour in page_behaviours:
            page = MagicMock()
            if isinstance(behaviour, Exception):
                page.extract_text.side_effect = behaviour
            else:
                page.extract_text.return_value = behaviour
            pages.append(page)
        reader = MagicMock()
        reader.pages = pages
        return reader

    def test_one_unreadable_page_does_not_lose_the_others(self):
        reader = self._reader_with_pages(
            "PAGE ONE TEXT",
            RuntimeError("malformed content stream"),
            "PAGE THREE TEXT",
        )
        with patch("pypdf.PdfReader", return_value=reader):
            text, error = model_armor.extract_pdf_text(b"%PDF-1.4 fake")

        self.assertIsNone(error, "a single bad page is not a document-level failure")
        self.assertIn("PAGE ONE TEXT", text)
        self.assertIn("PAGE THREE TEXT", text,
                      "the page AFTER the failure must still be read -- this is the "
                      "whole point of continuing rather than breaking")

    def test_a_page_returning_None_becomes_empty_string_not_a_crash(self):
        reader = self._reader_with_pages("REAL TEXT", None)
        with patch("pypdf.PdfReader", return_value=reader):
            text, error = model_armor.extract_pdf_text(b"%PDF-1.4 fake")
        self.assertIsNone(error)
        self.assertEqual(text.strip(), "REAL TEXT")

    def test_a_document_level_failure_is_reported_with_its_type(self):
        with patch("pypdf.PdfReader", side_effect=ValueError("not a pdf")):
            text, error = model_armor.extract_pdf_text(b"nonsense")
        self.assertEqual(text, "")
        self.assertIn("ValueError", error)


if __name__ == "__main__":
    unittest.main()
