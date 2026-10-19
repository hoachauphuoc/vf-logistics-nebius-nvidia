"""
Drift: the agent's authority is suspended when recent behaviour no longer matches the boundary it was granted
for -- too many auto-releases, too many deterministic overrides, too many injection attempts. Too few cases is
not drift, it is not knowing.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from test_evidence_eval_approve import Base, run  # noqa: E402
from vf_logistics import governance  # noqa: E402

BOUNDARY = {"version": 3}


class TestDrift(Base):
    def fill(self, count, **extra):
        for i in range(count):
            self.put(f"CASE-{i}", **extra)

    def check(self):
        return run(governance.drift_check(BOUNDARY))

    def test_too_few_cases_is_not_drift_and_says_how_many_are_needed(self):
        self.fill(governance.DRIFT_MIN_SAMPLE - 1)
        result = self.check()
        assert result["material"] is False
        assert result["reasons"] == []
        assert f"below the {governance.DRIFT_MIN_SAMPLE} needed" in result["reason"]
        assert result["metrics"]["boundary_version"] == 3

    def test_markers_and_processed_objects_are_not_cases(self):
        self.fill(2)
        self.put("MARK", is_marker=True)
        self.put("OBJ", state="OBJECT_PROCESSED")
        assert self.check()["metrics"]["sample"] == 2

    def test_ordinary_behaviour_is_within_expectations(self):
        self.fill(governance.DRIFT_MIN_SAMPLE)
        result = self.check()
        assert result["material"] is False
        assert result["reason"] == "within expected behaviour."
        assert result["metrics"]["auto_release_rate"] == 0.0

    def test_too_many_auto_releases_is_drift(self):
        self.fill(governance.DRIFT_MIN_SAMPLE, state="AUTO_CLEARED")
        result = self.check()
        assert result["material"] is True
        assert result["metrics"]["auto_release_rate"] == 1.0
        assert "100% of recent cases were auto-released" in result["reasons"][0]

    def test_too_many_deterministic_overrides_is_drift(self):
        self.fill(governance.DRIFT_MIN_SAMPLE, reconciliation={"source": "deterministic floor"})
        result = self.check()
        assert result["material"] is True
        assert result["metrics"]["veto_rate"] == 1.0
        assert "deterministic checks overrode the agent on 100% of cases" in result["reasons"][0]

    def test_too_many_flagged_documents_is_drift_whichever_screen_flagged_them(self):
        for i in range(governance.DRIFT_MIN_SAMPLE):
            screen = {"injection_screening": {"blocked": True}} if i % 2 else {"model_armor": {"blocked": True}}
            self.put(f"CASE-{i}", input_security=screen)
        result = self.check()
        assert result["material"] is True
        assert result["metrics"]["injection_rate"] == 1.0
        assert "flagged for prompt injection" in result["reasons"][0]

    def test_several_causes_are_all_listed_and_joined(self):
        self.fill(
            governance.DRIFT_MIN_SAMPLE, state="AUTO_CLEARED", reconciliation={"source": "deterministic floor"},
        )
        result = self.check()
        assert len(result["reasons"]) == 2
        assert result["reason"] == " ".join(result["reasons"])
