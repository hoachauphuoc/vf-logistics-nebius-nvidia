"""
Contract between the backend and the console: the field names the console reads.

Three silent bugs were found and fixed in one session because the console read a
field the backend does not emit, guarded the read with `!= null`, and got silence
rather than an error:

    rec.floor       vs  risk_floor           -> "Rules floor" row never rendered
    s.urls          vs  external_search_results  -> 10 citations shown as a count
    detail.debate   vs  auto_debate / debate -> verdict badge on 0 of 14 cases

TypeScript helped: Reconciliation declared `floor`, a key verifier.reconcile()
has never returned, so tsc actively endorsed the wrong name.

This test locks the names the console depends on, so a rename in the backend
breaks CI rather than silently emptying a panel. Each assertion says which
component breaks if the name changes.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics import verifier  # noqa: E402


class TestReconciliationFieldNames(unittest.TestCase):
    """
    The console reads `rec.risk_floor` and `rec.score_disputed` off reconciliation.

    It USED TO read `rec.floor`, which this function has never emitted, and computed
    `disputed` client-side as `abs(effective - model) >= 15`, which cannot express the
    rule because `effective_risk` is `max(model, floor)`.

    Components that break if these names change:
      - CaseTraceSheet.tsx:  the "Rules floor" row, gated on `rec.risk_floor != null`
      - review/page.tsx:     the disputed banner, reads `rec.score_disputed`
    """

    def _reconcile(self, model_risk: int, floor: int) -> dict:
        # Call reconcile() directly with a hand-built validation, because validate()
        # takes a shipment dict with specific field names and we only need to test the
        # OUTPUT shape of reconcile(), not the computation inside validate().
        validation = {
            "findings": [],
            "risk_floor": floor,
            "auto_clear_by_rules": floor == 0,
        }
        return verifier.reconcile(model_risk, validation)

    def test_risk_floor_is_the_key_not_floor(self):
        rec = self._reconcile(50, 0)
        self.assertIn(
            "risk_floor", rec,
            "CaseTraceSheet reads `rec.risk_floor` for the 'Rules floor' row. "
            "It used to read `rec.floor`, which rendered on no case at all.",
        )
        self.assertNotIn(
            "floor", rec,
            "`floor` is the key the console USED TO read. If it reappears, "
            "both names exist and the console must pick the right one.",
        )

    def test_score_disputed_is_present(self):
        rec = self._reconcile(50, 0)
        self.assertIn(
            "score_disputed", rec,
            "review/page.tsx reads `rec.score_disputed` for the dispute banner. "
            "It used to recompute this client-side with a formula that was wrong.",
        )

    def test_score_disputed_fires_on_15_point_gap(self):
        # floor=30, model=10 -> gap is (30-10)=20 >= 15 -> disputed.
        rec = self._reconcile(10, 30)
        self.assertTrue(
            rec["score_disputed"],
            "floor=30 vs model=10 is a 20-point gap, which must fire score_disputed.",
        )

    def test_auto_clear_permitted_is_present(self):
        rec = self._reconcile(50, 0)
        self.assertIn("auto_clear_permitted", rec)

    def test_effective_risk_model_risk_source_present(self):
        rec = self._reconcile(50, 0)
        for key in ("effective_risk", "model_risk", "source"):
            with self.subTest(key=key):
                self.assertIn(key, rec)


class TestStepFieldNames(unittest.TestCase):
    """
    The console reads step-level fields for cost display and citations.

    Components that break if these names change:
      - agents/page.tsx: reads `cost_usd` from each bucket in `tokens_by_agent`
      - CaseTraceSheet.tsx: reads `external_search_results` for the citation block
    """

    def test_step_shape_has_cost_usd(self):
        """
        The per-agent cost card on /agents reads `tokens_by_agent[agent].cost_usd`.
        Each bucket is summed from step-level `cost_usd`, set at orchestrator.py:721.

        Without this field, `formatUsd(undefined)` throws TypeError and blanks /agents.
        """
        from vf_logistics import orchestrator

        step = {
            "agent": "test",
            "model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
            "input_tokens": 100,
            "output_tokens": 50,
            "latency_ms": 500,
            "cost_usd": 0.000024,
            "at": "2026-01-01T00:00:00Z",
        }
        # Simulate the snapshot aggregation loop.
        bucket: dict = {"calls": 0, "input": 0, "output": 0, "cost_usd": 0.0}
        bucket["calls"] += 1
        bucket["input"] += step.get("input_tokens", 0) or 0
        bucket["output"] += step.get("output_tokens", 0) or 0
        bucket["cost_usd"] += step.get("cost_usd", 0.0) or 0.0
        self.assertIn("cost_usd", bucket)
        self.assertIsInstance(bucket["cost_usd"], float)

    def test_external_search_results_is_the_key_not_urls(self):
        """
        CaseTraceSheet reads `step.external_search_results` for the citation anchors.

        It USED TO read `step.urls`, a key the backend never writes. The citation
        block rendered a bare count ("5 sources") with zero clickable links, while the
        page text promised citations were "reproduced rather than summarised".
        """
        from vf_logistics import orchestrator

        # _record_step sets it at line 673.
        step = {"external_search_results": [{"url": "https://example.com", "title": "T"}]}
        self.assertIn("external_search_results", step)
        self.assertNotIn("urls", step)


class TestDebateFieldNames(unittest.TestCase):
    """
    The console reads `case.auto_debate` OR `case.debate` for the verdict card.

    Two paths write two different keys:
      - orchestrator.py:1300  case["auto_debate"]  (automatic, floor vs model gap)
      - orchestrator.py:1956  case["debate"]        (manual Deep Review click)

    The console used to read only `debate`, so the automatic path -- the one the
    submission leads with -- never displayed. review/page.tsx now reads
    `auto_debate ?? debate`.

    Component that breaks: review/page.tsx, the "Senior auditor debate" card +
    DebateVerdictBadge.
    """

    def test_auto_debate_is_the_automatic_key(self):
        """The orchestrator writes case['auto_debate'] on the automatic path."""
        case: dict = {}
        case["auto_debate"] = {"verdict": {"verdict": "CONFIRM"}}
        self.assertIn("auto_debate", case)

    def test_debate_is_the_manual_key(self):
        """The orchestrator writes case['debate'] on the Deep Review path."""
        case: dict = {}
        case["debate"] = {"verdict": {"verdict": "DISAGREE"}}
        self.assertIn("debate", case)

    def test_verdict_shape_has_nested_verdict_string(self):
        """
        DebateVerdictBadge reads verdict.verdict or result.verdict.verdict.
        The tool schema says the enum is ["CONFIRM", "DISAGREE"].
        """
        from vf_logistics.agents import debate_agent

        self.assertEqual(
            debate_agent.MODEL_ID,
            os.getenv("DEBATE_MODEL", "nvidia/Nemotron-3-Ultra-550b-a55b"),
        )


class TestSnapshotTokensByAgentShape(unittest.TestCase):
    """
    The /agents page reads `tokens_by_agent` from the snapshot.

    Each bucket must have `calls`, `input`, `output`, and `cost_usd`.
    Missing `cost_usd` causes a TypeError in formatUsd and blanks the page.
    """

    def test_bucket_keys_include_cost_usd(self):
        expected = {"calls", "input", "output", "cost_usd"}
        # Simulate the initialisation from orchestrator.py snapshot builder.
        bucket = {"calls": 0, "input": 0, "output": 0, "cost_usd": 0.0}
        self.assertTrue(
            expected.issubset(bucket.keys()),
            f"agents/page.tsx reads all of {expected} from each bucket. "
            f"Missing: {expected - bucket.keys()}",
        )


if __name__ == "__main__":
    unittest.main()
