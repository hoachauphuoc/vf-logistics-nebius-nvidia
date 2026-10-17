"""
A paper the reader only partly read (pages_read < pages) is not provided (review VI, N06-B):
it cannot prove what its other pages say. What it does say is still read for contradictions.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from test_evidence_eval_approve import DOCS3, PAPERS  # noqa: E402
from test_origin_inputs import plywood  # noqa: E402
from vf_logistics.verifier import check_origin_evidence  # noqa: E402


def _docs(pages=None, pages_read=None, **override):
    docs = []
    for doc_type, extracted in {**PAPERS, **override}.items():
        doc = {"doc_type": doc_type, "extracted": extracted}
        if pages is not None:
            doc["pages"] = pages
        if pages_read is not None:
            doc["pages_read"] = pages_read
        docs.append(doc)
    return docs


def test_papers_read_in_part_are_unproven_and_listed():
    result = check_origin_evidence(plywood(), _docs(pages=2, pages_read=1))
    assert result["status"] == "missing"
    assert result["present"] == []
    assert sorted(u["doc_type"] for u in result["unread"]) == sorted(DOCS3)
    assert {(u["pages"], u["pages_read"]) for u in result["unread"]} == {(2, 1)}


def test_only_the_partly_read_paper_is_missing():
    docs = _docs()
    first = docs[0]["doc_type"]
    docs[0] = {**docs[0], "pages": 3, "pages_read": 1}
    result = check_origin_evidence(plywood(), docs)
    assert result["missing"] == [first]
    assert [u["doc_type"] for u in result["unread"]] == [first]


def test_a_fully_read_paper_is_unchanged():
    result = check_origin_evidence(plywood(), _docs(pages=2, pages_read=2))
    assert result["status"] == "provided"
    assert result["unread"] == []


def test_records_that_do_not_say_how_much_was_read_behave_as_before():
    for pages, pages_read in ((None, None), (2, None), (None, 1), ("2", "1"), (2.0, 1.0), (True, False)):
        result = check_origin_evidence(plywood(), _docs(pages=pages, pages_read=pages_read))
        assert result["status"] == "provided", (pages, pages_read)
        assert result["unread"] == [], (pages, pages_read)


def test_what_a_partly_read_paper_says_is_still_read_for_contradictions():
    docs = _docs(certificate_of_origin={"producer_name": "Saigon Plywood Co", "origin_country": "China"})
    docs = [
        {**d, "pages": 2, "pages_read": 1} if d["doc_type"] == "certificate_of_origin" else d
        for d in docs
    ]
    result = check_origin_evidence(plywood(), docs)
    assert result["status"] == "contradicted"
    assert [c["kind"] for c in result["contradictions"]] == ["certificate_country"]
    assert "certificate_of_origin" in result["missing"]


def test_pages_are_read_from_the_record_never_from_the_extraction():
    certificate = {**PAPERS["certificate_of_origin"], "pages": 9, "pages_read": 1}
    result = check_origin_evidence(plywood(), _docs(certificate_of_origin=certificate))
    assert result["status"] == "provided"
    assert result["unread"] == []
