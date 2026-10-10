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


def test_workload_is_arithmetic_on_recall_and_false_alarms():
    """
    At 0.2% fraud, recall 1.0 and a 10% false-alarm rate: 2 real cases and 99.8
    honest ones held per 1,000, so one real case in fifty held.
    """
    rows = evaluation.workload({"recall": 1.0, "false_positive_rate": 0.1}, (0.002,))
    assert rows == [{
        "prevalence": 0.002,
        "held_per_1000": 101.8,
        "true_per_1000": 2.0,
        "missed_per_1000": 0.0,
        "precision_at_prevalence": round(2.0 / 101.8, 4),
        "held_per_true_case": 50.9,
    }]
    assert evaluation.workload({"recall": 0.0, "false_positive_rate": 0.0})[0]["held_per_true_case"] is None


def test_every_report_carries_its_workload_at_the_measured_rate():
    for entry in evaluation.pipeline_results():
        assert [w["prevalence"] for w in entry["workload"]] == list(evaluation.PREVALENCES)


def test_the_public_case_reports_are_served_as_pairs_with_their_sources():
    """
    Every pair names its regulator's page, and pairs that are identical at booking
    are never counted as separated -- a different verdict on them is variance.
    """
    by_id = {e["id"]: e for e in evaluation.pipeline_results()}
    for report_id in ("public_rules_all", "public_full_all"):
        pairs = by_id[report_id]["pairs"]
        assert len(pairs) == 19
        for pair in pairs:
            assert pair["source_url"].startswith("https://")
            if pair["identical_inputs"]:
                assert not pair["separated"]
        assert by_id[report_id]["sanctions_index"]["source"] == "OFAC SDN + UN SC Consolidated"
