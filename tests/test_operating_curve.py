"""
scripts/operating_curve.py: the rules arm re-scored at every review threshold.

The sweep is pinned on hand-built rows, where the right answer can be counted by
eye, and the script is run once end to end, because "re-runnable with one
command" is only true for as long as something runs it.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "operating_curve.py"


@pytest.fixture(scope="module")
def curve_script():
    spec = importlib.util.spec_from_file_location("_operating_curve", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_operating_curve"] = module
    spec.loader.exec_module(module)
    return module


def row(floor: int, attack: bool) -> dict:
    return {"risk_floor": floor, "expected_flagged": attack}


ROWS = [
    row(0, True), row(50, True), row(80, True), row(100, True),
    row(0, False), row(0, False), row(50, False), row(80, False),
]


def test_one_cut_per_distinct_floor_on_either_split(curve_script):
    """A floor of 0 is not a cut: holding everything at or above it holds everything."""
    assert curve_script.cut_points({"dev": ROWS, "holdout": [row(65, False)]}) == [50, 65, 80, 100]


def test_each_point_counts_what_its_threshold_would_hold(curve_script):
    points = curve_script.sweep(ROWS, [50, 80, 100], review_threshold=40)
    assert [(p["tp"], p["fp"], p["fn"], p["tn"]) for p in points] == [
        (3, 2, 1, 2),   # floor >= 50
        (2, 1, 2, 3),   # floor >= 80
        (1, 0, 3, 4),   # floor >= 100
    ]
    assert [p["thresholds"] for p in points] == [[1, 50], [51, 80], [81, 100]]
    # 40 lies in 1..50, so it holds exactly what 50 would.
    assert [p["current"] for p in points] == [True, False, False]
    assert points[0]["recall"] == 0.75 and points[0]["false_positive_rate"] == 0.5
    assert points[2]["precision"] == 1.0


def test_a_threshold_that_holds_nothing_has_no_precision_rather_than_zero(curve_script):
    points = curve_script.sweep([row(0, True), row(0, False), row(50, False)], [50], 40)
    assert points[0]["precision"] == 0.0
    points = curve_script.sweep([row(0, True), row(0, False)], [50], 40)
    assert points[0]["precision"] is None and points[0]["held_per_true_case"] is None


def test_the_script_runs_end_to_end(curve_script, tmp_path, monkeypatch, capsys):
    out = tmp_path / "rules.json"
    monkeypatch.setattr(sys, "argv", ["operating_curve.py", "--out", str(out)])
    assert curve_script.main() == 0
    assert f"wrote {out}" in capsys.readouterr().out

    curve = json.loads(out.read_text(encoding="utf-8"))
    assert set(curve["splits"]) == {"dev", "holdout"}
    for split in curve["splits"].values():
        assert sum(p["current"] for p in split["points"]) == 1
    # Aggregates only: nothing in the file is a case.
    assert '"case_id":' not in out.read_text(encoding="utf-8")
    assert list(tmp_path.iterdir()) == [out]


def test_it_refuses_to_write_when_flags_are_not_the_floor(curve_script, tmp_path, monkeypatch, capsys):
    """
    The sweep re-scores the floor alone. If the benchmark ever holds a case for
    another reason, a curve over the floor would describe a different detector
    from the one measured, so nothing is written.
    """
    rows = [
        {"case_id": "a", "risk_floor": 50, "expected_flagged": True, "flagged": True},
        {"case_id": "b", "risk_floor": 0, "expected_flagged": False, "flagged": True},
    ]
    monkeypatch.setattr(curve_script, "run_rules", lambda split, workdir: ({}, rows))
    out = tmp_path / "rules.json"
    monkeypatch.setattr(sys, "argv", ["operating_curve.py", "--out", str(out)])
    assert curve_script.main() == 2
    assert "REFUSING" in capsys.readouterr().out
    assert not out.exists()
