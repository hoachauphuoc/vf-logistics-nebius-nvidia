"""
GET /api/v1/evaluation: the committed reports, served as they were written.

What is pinned here is the contract the console's Evaluation panel reads, and the
two properties that make serving the results honest rather than decorative: every
entry says which split and which verifier produced it, and per-case rows (which
carry the corpus labels) are never served.
"""

from __future__ import annotations

import json

from vf_logistics import evaluation
from vf_logistics.app import app


def test_the_route_serves_the_committed_reports():
    response = app.test_client().get("/api/v1/evaluation")
    assert response.status_code == 200
    body = response.get_json()
    ids = {entry["id"] for entry in body["pipeline"]}
    # The before/after pair on the holdout split is the headline comparison.
    assert {"rules_holdout_before", "rules_holdout_after"} <= ids
    assert body["caveats"], "the caveats travel with the numbers"


def test_every_pipeline_entry_says_where_it_came_from():
    for entry in evaluation.pipeline_results():
        assert entry["split"] in ("dev", "holdout", "all")
        assert entry["verifier"]
        assert "detection" in entry


def test_the_tuning_claim_is_what_the_files_say():
    """The README quotes these two numbers; this is where they come from."""
    by_id = {e["id"]: e for e in evaluation.pipeline_results()}
    before = by_id["rules_holdout_before"]["detection"]["false_positive_rate"]
    after = by_id["rules_holdout_after"]["detection"]["false_positive_rate"]
    assert after < before


def test_per_case_rows_are_never_served(tmp_path):
    (tmp_path / "leak_cases.json").write_text(json.dumps([{"case_id": "x"}]))
    (tmp_path / "ok.json").write_text(json.dumps({"detection": {}, "split": "dev"}))
    ids = {e["id"] for e in evaluation.pipeline_results(tmp_path)}
    assert ids == {"ok"}


def test_hs_rows_are_dropped_and_sets_are_separated(tmp_path):
    (tmp_path / "base.json").write_text(json.dumps(
        {"arm": "base", "at": "t", "metrics": {"arm": "base"}, "rows": [{"secret": 1}]}
    ))
    (tmp_path / "holdout_base.json").write_text(json.dumps(
        {"arm": "base", "at": "t", "metrics": {"arm": "base"}, "rows": []}
    ))
    sets = evaluation.hs_results(tmp_path)
    assert len(sets["pairs"]) == 1 and len(sets["holdout"]) == 1
    assert "rows" not in sets["pairs"][0]
