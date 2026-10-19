"""
Two routes no test reached: Tavily entity verification, and the reviewer's view of the archived
document (whose content-type is pinned so a stray object cannot serve text/html on the console's origin).
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(__file__))
from test_console_session import TEST_KEY  # noqa: E402
from test_evidence_eval_approve import Base  # noqa: E402

KEY = {"X-VF-API-Key": TEST_KEY}


def run(coro):
    return asyncio.run(coro)


class RouteBase(Base):
    def setup_method(self):
        super().setup_method()
        from vf_logistics import app as app_mod

        self.app_mod = app_mod
        self.limiter_was = app_mod.limiter.enabled
        app_mod.limiter.enabled = False
        self.client = app_mod.app.test_client()

    def teardown_method(self):
        self.app_mod.limiter.enabled = self.limiter_was
        super().teardown_method()


def hit(title="", content="", url="https://example.test/x"):
    return {"title": title, "content": content, "url": url}


class TestVerifyEntity(RouteBase):
    def post(self, body, results):
        with patch("vf_logistics.tavily_client.search", new=AsyncMock(return_value=results)) as search:
            response = self.client.post("/api/v1/governance/verify-entity", json=body, headers=KEY)
        return response, search

    def test_a_value_is_required(self):
        response, search = self.post({"type": "company"}, [])
        assert response.status_code == 400
        assert "value is required" in response.get_json()["error"]
        search.assert_not_called()

    def test_no_results_is_not_verified(self):
        response, _ = self.post({"value": "Ghost Trading Co"}, [])
        body = response.get_json()
        assert (response.status_code, body["verified"], body["confidence"]) == (200, False, "none")
        assert "No web results" in body["summary"]

    def test_two_sources_naming_the_company_is_high_confidence(self):
        response, _ = self.post({"value": "Saigon Plywood"}, [
            hit(title="Saigon Plywood Co"), hit(content="about saigon plywood"), hit(title="unrelated"),
        ])
        body = response.get_json()
        assert (body["verified"], body["confidence"]) == (True, "high")
        assert "2 web sources" in body["summary"]
        assert len(body["results"]) == 3

    def test_one_source_is_medium_confidence(self):
        response, _ = self.post({"value": "Saigon Plywood"}, [hit(title="Saigon Plywood"), hit(title="other")])
        body = response.get_json()
        assert (body["verified"], body["confidence"]) == (True, "medium")

    def test_results_that_do_not_name_it_are_low_confidence_and_not_verified(self):
        response, _ = self.post({"value": "Saigon Plywood"}, [hit(title="Hanoi Steel"), hit(content="nothing relevant")])
        body = response.get_json()
        assert (body["verified"], body["confidence"]) == (False, "low")
        assert "none directly mention" in body["summary"]

    def test_a_snippet_is_cut_to_300_characters(self):
        response, _ = self.post({"value": "x"}, [hit(title="x", content="y" * 900)])
        assert len(response.get_json()["results"][0]["snippet"]) == 300

    def test_a_tax_id_is_searched_as_a_tax_id_in_the_given_country(self):
        _, search = self.post({"type": "tax_id", "value": "0301234567", "country": "Singapore"}, [])
        assert search.call_args.args[0] == '"0301234567" tax ID registration Singapore company'
        assert search.call_args.kwargs == {"max_results": 5}

    def test_a_company_is_searched_in_vietnam_by_default(self):
        _, search = self.post({"value": "Saigon Plywood"}, [])
        assert search.call_args.args[0] == '"Saigon Plywood" company vietnam registration OR business OR official'

    def test_a_search_that_raises_is_a_500_and_production_hides_the_cause(self):
        for production, shown in ((False, True), (True, False)):
            with patch("vf_logistics.tavily_client.search", new=AsyncMock(side_effect=RuntimeError("tavily down"))),                     patch.object(self.app_mod, "_IS_PRODUCTION", production):
                response = self.client.post("/api/v1/governance/verify-entity", json={"value": "x"}, headers=KEY)
            assert response.status_code == 500
            assert ("tavily down" in response.get_data(as_text=True)) is shown

    def test_an_anonymous_caller_is_refused(self):
        response = self.client.post("/api/v1/governance/verify-entity", json={"value": "x"})
        assert response.status_code in (401, 403)


class TestReviewDocument(RouteBase):
    def put_with(self, **provenance):
        self.put(case_id="CASE-D", provenance=provenance)

    def get(self, case_id="CASE-D", fetched=None):
        with patch.object(self.app_mod.document_store, "fetch", new=AsyncMock(return_value=fetched)) as fetch:
            response = self.client.get(f"/api/v1/review/{case_id}/document", headers=KEY)
        return response, fetch

    def test_an_unknown_case_is_404(self):
        response, fetch = self.get(case_id="NOPE")
        assert response.status_code == 404
        assert response.get_json()["error"] == "case not found"
        fetch.assert_not_called()

    def test_a_case_with_no_archived_document_says_why(self):
        self.put_with(reason="structured event")
        response, fetch = self.get()
        assert response.status_code == 404
        assert response.get_json()["reason"] == "structured event"
        fetch.assert_not_called()

    def test_a_document_that_cannot_be_read_is_502(self):
        self.put_with(uri="gs://bucket/a.pdf")
        response, _ = self.get(fetched=(None, None))
        assert response.status_code == 502

    def test_a_pdf_is_streamed_inline_with_its_type(self):
        self.put_with(uri="gs://bucket/a.pdf", filename="bill.pdf")
        response, fetch = self.get(fetched=(b"%PDF-1.4 body", "application/pdf"))
        assert response.status_code == 200
        assert response.data == b"%PDF-1.4 body"
        assert response.mimetype == "application/pdf"
        assert response.headers["Content-Disposition"] == 'inline; filename="bill.pdf"'
        fetch.assert_called_once_with("gs://bucket/a.pdf")

    def test_a_type_the_upload_route_never_accepts_is_served_as_a_download(self):
        self.put_with(uri="gs://bucket/a.html", filename="page.html")
        response, _ = self.get(fetched=(b"<script>alert(1)</script>", "text/html"))
        assert response.status_code == 200
        assert response.mimetype == "application/octet-stream"

    def test_the_filename_cannot_break_out_of_the_header(self):
        self.put_with(uri="gs://bucket/a.pdf", filename='x"; filename*=UTF-8\'\'evil.html\r\nX-Evil: 1')
        response, _ = self.get(fetched=(b"%PDF", "application/pdf"))
        disposition = response.headers["Content-Disposition"]
        assert '"' not in disposition[len('inline; filename="'):-1]
        assert "\r" not in disposition and "\n" not in disposition
        assert "X-Evil" not in response.headers

    def test_the_filename_is_cut_to_100_characters(self):
        self.put_with(uri="gs://bucket/a.pdf", filename="a" * 300 + ".pdf")
        response, _ = self.get(fetched=(b"%PDF", "application/pdf"))
        name = response.headers["Content-Disposition"].split('filename="', 1)[1].rstrip('"')
        assert len(name) == 100

    def test_an_anonymous_caller_is_refused(self):
        self.put_with(uri="gs://bucket/a.pdf")
        assert self.client.get("/api/v1/review/CASE-D/document").status_code in (401, 403)
