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
        # No counts, so no intervals to take the ends of -- not a range of zero width.
        "best_case": None,
        "worst_case": None,
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


# ---------------------------------------------------------------------------
# Intervals: every rate served with the uncertainty its sample size carries.
# ---------------------------------------------------------------------------


def test_wilson_reproduces_published_values():
    """
    Newcombe (1998), "Two-sided confidence intervals for the single proportion",
    Statistics in Medicine 17:857-872, Table II, score method -- an independent
    source, so this checks the formula rather than restating it. 11 of 12 is the
    HS classifier's holdout recall.
    """
    assert evaluation.wilson(81, 263) == (0.2553, 0.3662)
    assert evaluation.wilson(15, 148) == (0.0624, 0.1605)
    assert evaluation.wilson(0, 20) == (0.0, 0.1611)
    assert evaluation.wilson(1, 29) == (0.0061, 0.1718)
    assert evaluation.wilson(11, 12) == (0.6461, 0.9851)
    assert evaluation.wilson(0, 0) is None


def test_a_perfect_score_on_a_small_sample_still_has_a_range():
    """The reason for Wilson over p +/- z*se, which gives 15 of 15 no width at all."""
    assert evaluation.wilson(15, 15) == (0.7961, 1.0)
    assert evaluation.wilson(0, 12) == (0.0, 0.2425)


def test_intervals_are_built_from_counts_and_never_guessed():
    iv = evaluation.intervals({"tp": 11, "fp": 0, "fn": 1, "tn": 12, "recall": 0.9167})
    assert iv["recall"] == {"low": 0.6461, "high": 0.9851, "successes": 11, "n": 12}
    assert iv["precision"] == {"low": 0.7412, "high": 1.0, "successes": 11, "n": 11}
    assert iv["false_positive_rate"] == {"low": 0.0, "high": 0.2425, "successes": 0, "n": 12}

    # Rates without counts: there is no n to build an interval on, so none is invented.
    assert evaluation.intervals({"precision": 0.9, "recall": 0.9, "false_positive_rate": 0.1}) == {
        "precision": None, "recall": None, "false_positive_rate": None,
    }
    # Nothing held: precision is undefined, recall and the false-alarm rate are not.
    nothing_held = evaluation.intervals({"tp": 0, "fp": 0, "fn": 12, "tn": 12})
    assert nothing_held["precision"] is None
    assert nothing_held["recall"]["high"] > 0
    # A boolean is not a count.
    assert evaluation.intervals({"tp": True, "fp": 0, "fn": 1, "tn": 1})["recall"] is None


def test_every_served_rate_sits_inside_its_interval():
    for entry in evaluation.pipeline_results():
        d = entry["detection"]
        assert entry["intervals"]["recall"]["n"] == d["tp"] + d["fn"], entry["id"]
        assert entry["intervals"]["false_positive_rate"]["n"] == d["fp"] + d["tn"], entry["id"]
        for rate, iv in entry["intervals"].items():
            assert iv["low"] <= d[rate] <= iv["high"], (entry["id"], rate)
    for rows in evaluation.hs_results().values():
        for row in rows:
            for rate in ("recall", "false_positive_rate"):
                iv = row["intervals"][rate]
                assert iv["low"] <= row[rate] <= iv["high"], (row["arm"], rate)


def test_the_workload_range_is_the_interval_ends_plugged_in():
    """
    Best case: recall at the top of its interval and false alarms at the bottom of
    theirs; worst case the reverse. The point estimate sits strictly between.
    """
    entry = {e["id"]: e for e in evaluation.pipeline_results()}["rules_holdout_after"]
    iv = entry["intervals"]
    for row in entry["workload"]:
        best, worst = row["best_case"], row["worst_case"]
        assert (best["recall"], best["false_positive_rate"]) == (
            iv["recall"]["high"], iv["false_positive_rate"]["low"])
        assert (worst["recall"], worst["false_positive_rate"]) == (
            iv["recall"]["low"], iv["false_positive_rate"]["high"])
        assert best["held_per_true_case"] < row["held_per_true_case"] < worst["held_per_true_case"]
        assert (best["precision_at_prevalence"] > row["precision_at_prevalence"]
                > worst["precision_at_prevalence"])


# ---------------------------------------------------------------------------
# Operating curve: the rules arm at every threshold that changes the answer.
# ---------------------------------------------------------------------------


def test_the_operating_curve_is_served_with_both_splits():
    body = app.test_client().get("/api/v1/evaluation").get_json()
    curve = body["operating_curve"]["rules"]
    assert set(curve["splits"]) == {"dev", "holdout"}
    for split in curve["splits"].values():
        points = split["points"]
        assert sum(p["current"] for p in points) == 1
        for lower, higher in zip(points, points[1:]):
            # Raising the threshold can only release shipments, never hold more.
            assert higher["tp"] <= lower["tp"] and higher["fp"] <= lower["fp"]
            # The threshold ranges tile, so every threshold names exactly one point.
            assert higher["thresholds"][0] == lower["thresholds"][1] + 1
        for p in points:
            assert p["tp"] + p["fn"] == split["attacks"] and p["fp"] + p["tn"] == split["clean"]
            assert p["intervals"]["recall"]["n"] == split["attacks"]


def test_the_current_point_is_the_reported_holdout_figure():
    """
    The curve and the headline report sit on the same page; at the threshold in
    use they must be the same measurement, or one of them is stale.
    """
    curve = evaluation.operating_curves()["rules"]
    current = next(p for p in curve["splits"]["holdout"]["points"] if p["current"])
    lo, hi = current["thresholds"]
    assert lo <= curve["review_threshold"] <= hi
    reported = {e["id"]: e for e in evaluation.pipeline_results()}["rules_holdout_after"]["detection"]
    assert {k: current[k] for k in ("tp", "fp", "fn", "tn")} == {
        k: reported[k] for k in ("tp", "fp", "fn", "tn")
    }


def test_a_point_with_no_false_alarms_is_not_served_as_a_perfect_screen():
    """
    No clean holdout case held makes the point estimate one shipment held per real
    one. Of 86 clean cases that is a small sample, and the worst case says so.
    """
    curve = evaluation.operating_curves()["rules"]
    strict = [p for p in curve["splits"]["holdout"]["points"] if p["fp"] == 0]
    assert strict, "the curve reaches a threshold that holds no clean case"
    for p in strict:
        assert p["held_per_true_case"] == 1.0
        assert p["worst_case"]["held_per_true_case"] > 50


def test_the_curve_carries_no_case_rows(tmp_path):
    served = json.dumps(evaluation.operating_curves())
    assert '"case_id":' not in served and '"expected_flagged":' not in served

    (tmp_path / "rules.json").write_text(json.dumps({"prevalence": 0.002, "splits": {"dev": {"points": [
        {"threshold": 50, "tp": 1, "fp": 1, "fn": 1, "tn": 1, "recall": 0.5, "false_positive_rate": 0.5},
    ]}}}))
    (tmp_path / "not_a_curve.json").write_text(json.dumps({"detection": {}}))
    (tmp_path / "rows_cases.json").write_text(json.dumps([{"case_id": "x"}]))
    curves = evaluation.operating_curves(tmp_path)
    assert set(curves) == {"rules"}
    assert curves["rules"]["splits"]["dev"]["points"][0]["intervals"]["recall"]["n"] == 2
