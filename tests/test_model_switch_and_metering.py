"""
Two things the cost work added that can be got wrong quietly.

1. THE MODEL SWITCH GUARD. `set_model()` validated against `PRICING` and nothing else,
   so every priced model was interchangeable by one authenticated POST -- including
   Ultra, which on the blended input+output rate is 13.3x Nano. That setting drives
   fraud_detection and compliance, the two agents that run on EVERY case, and the change
   takes effect on the next shipment with nothing recorded. The tenant spend ceiling
   would eventually notice, hours and a lot of money later, because that check is soft
   and cached for five seconds.

   The guard does not decide the switch is wrong. It requires it to be deliberate.

2. TAVILY METERING. Measured at 4.5-5.3 searches per case against $0.068 of model spend
   for 20 cases -- so at the free tier's 1,000 credits a month the external search, not
   Nemotron, is what limits throughput to roughly 200 cases. It appeared in no figure
   anywhere, because `estimated_cost_usd` is Nebius only. Live and cached are counted
   separately: a total alone would make the caching invisible, and an operator who
   cannot see the saving has no reason to keep the TTLs where they are.
"""

from __future__ import annotations

import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics import config  # noqa: E402

NANO = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
SUPER = "nvidia/nemotron-3-super-120b-a12b"
ULTRA = "nvidia/Nemotron-3-Ultra-550b-a55b"


class ModelSwitchTestCase(unittest.TestCase):
    def setUp(self):
        self._original = config._model_id
        config._model_id = NANO

    def tearDown(self):
        config._model_id = self._original


class TestTheRateMultiple(ModelSwitchTestCase):
    """
    Blended input+output, because the two rates do not scale together.

    Ultra is 16.7x Nano on input and 12.5x on output; quoting either alone misreports
    the switch. Weighted 1:1, close to the measured mix of 198,840 input against
    137,307 output tokens on a 20-case run.
    """

    def test_the_same_model_is_one_times_itself(self):
        self.assertAlmostEqual(config.rate_multiple(NANO), 1.0, places=6)

    def test_super_is_four_times_nano(self):
        # (0.30 + 0.90) / (0.06 + 0.24) = 4.0
        self.assertAlmostEqual(config.rate_multiple(SUPER), 4.0, places=6)

    def test_ultra_is_over_thirteen_times_nano(self):
        # (1.00 + 3.00) / (0.06 + 0.24) = 13.33
        self.assertAlmostEqual(config.rate_multiple(ULTRA), 13.333333, places=4)

    def test_an_unknown_model_is_infinitely_dear(self):
        """
        Refused rather than admitted. An unpriced model cannot be compared, and
        treating "unknown" as "cheap" is how an unpriced model ends up on the hot path
        billing at the cheapest rate in the table.
        """
        self.assertEqual(config.rate_multiple("definitely/not-real"), float("inf"))

    def test_the_comparison_can_be_made_against_an_explicit_baseline(self):
        self.assertAlmostEqual(config.rate_multiple(NANO, against=ULTRA), 0.075, places=4)


class TestTheSwitchGuard(ModelSwitchTestCase):
    def test_super_is_permitted_without_confirmation(self):
        """
        4.0x, under the 5.0 default. Super on every case is a reasonable cost/quality
        trade an operator should be able to make from the console.
        """
        self.assertTrue(config.set_model(SUPER))
        self.assertEqual(config.get_model(), SUPER)

    def test_ultra_is_refused_without_confirmation(self):
        with self.assertRaises(config.CostlierModel) as caught:
            config.set_model(ULTRA)
        self.assertEqual(caught.exception.model, ULTRA)
        self.assertEqual(caught.exception.current, NANO)
        self.assertGreater(caught.exception.multiple, 13)
        self.assertEqual(
            config.get_model(), NANO, "a refused switch must not take effect",
        )

    def test_ultra_is_permitted_with_confirmation(self):
        self.assertTrue(config.set_model(ULTRA, allow_costlier=True))
        self.assertEqual(config.get_model(), ULTRA)

    def test_a_refusal_is_logged_with_the_numbers(self):
        with self.assertLogs("vf_logistics.config", level=logging.ERROR) as cap:
            with self.assertRaises(config.CostlierModel):
                config.set_model(ULTRA)
        joined = "\n".join(cap.output)
        self.assertIn("MODEL SWITCH REFUSED", joined)
        self.assertIn(ULTRA, joined)
        self.assertIn("every", joined, "the log should say why this setting matters")

    def test_a_permitted_increase_is_still_logged(self):
        """
        A switch that raises the bill should be findable afterwards. The audit trail
        covers decisions, not configuration, so this log is the only record.
        """
        with self.assertLogs("vf_logistics.config", level=logging.WARNING) as cap:
            config.set_model(SUPER)
        self.assertIn("MODEL SWITCH", "\n".join(cap.output))

    def test_going_cheaper_needs_no_confirmation(self):
        config._model_id = ULTRA
        self.assertTrue(config.set_model(NANO))
        self.assertEqual(config.get_model(), NANO)

    def test_an_unpriced_model_is_still_rejected_the_old_way(self):
        """
        False, not an exception. The PRICING check predates the guard and callers
        already branch on its return value.
        """
        self.assertFalse(config.set_model("definitely/not-real"))
        self.assertEqual(config.get_model(), NANO)

    def test_the_limit_falls_between_super_and_ultra(self):
        """
        Pinned because it is the whole design of the threshold, and a later tweak to
        the default would silently change which switches need saying so.
        """
        limit = config.MAX_RATE_MULTIPLE_WITHOUT_OVERRIDE
        self.assertGreater(limit, config.rate_multiple(SUPER, against=NANO))
        self.assertLess(limit, config.rate_multiple(ULTRA, against=NANO))


class TestTheDebateAgentModel(unittest.TestCase):
    """
    The debate ran on Ultra by default until it was measured against Super.

    scripts/compare_debate_models.py --corpus debated 46 disputed cases from the labelled
    corpus on both models (data/model_comparison/debate_corpus.json). Ultra reached a
    verdict less often (80% against 87%), told fraud from honest trade no better, cost
    5.2x as much and took twice as long, so the default is Super. DEBATE_MODEL puts Ultra
    back without a deploy.
    """

    def test_the_debate_default_is_super(self):
        from vf_logistics.agents import debate_agent

        if os.getenv("DEBATE_MODEL"):
            self.skipTest("DEBATE_MODEL is set in this environment")
        self.assertEqual(debate_agent.MODEL_ID, SUPER)

    def test_ultra_is_priced_so_the_debate_is_billed_correctly_when_selected(self):
        self.assertIn(ULTRA, config.PRICING)
        self.assertEqual(config.pricing_for(ULTRA)["input"], 1.00)
        self.assertEqual(config.pricing_for(ULTRA)["output"], 3.00)

    def test_the_per_case_agents_are_not_on_ultra(self):
        """These two run on every shipment, so they must never default to the dearest model."""
        from vf_logistics.agents import compliance_agent, fraud_detection_agent

        for agent in (fraud_detection_agent, compliance_agent):
            self.assertNotEqual(
                agent.get_model_id(), ULTRA,
                f"{agent.__name__} runs on every case and must not default to Ultra",
            )

    def test_the_comparison_script_exists_and_says_how_to_reverse_the_decision(self):
        import pathlib

        script = (
            pathlib.Path(__file__).resolve().parents[1]
            / "scripts" / "compare_debate_models.py"
        )
        self.assertTrue(script.is_file())
        text = script.read_text(encoding="utf-8")
        self.assertIn("DEBATE_MODEL", text, "it must say how to reverse the decision")

    def test_the_measured_comparison_is_committed(self):
        """The default rests on a measurement, so the measurement has to be in the repo."""
        import json
        import pathlib

        path = (
            pathlib.Path(__file__).resolve().parents[1]
            / "data" / "model_comparison" / "debate_corpus.json"
        )
        report = json.loads(path.read_text(encoding="utf-8"))
        self.assertFalse(report["partial"])
        self.assertEqual(
            {report["results"]["super"]["model"], report["results"]["ultra"]["model"]},
            {SUPER, ULTRA},
        )


class TestTavilyMetering(unittest.TestCase):
    def test_the_memory_store_reports_tavily_alongside_the_model_spend(self):
        import asyncio

        from vf_logistics.store import MemoryStore

        backing = MemoryStore()

        async def go():
            await backing.put_case({
                "case_id": "C1", "shipment_id": "S1", "state": "INGESTED",
                "created_at": "2026-09-01T00:00:00+00:00",
                "_agent_calls": 2, "_input_tokens": 100, "_output_tokens": 50,
                "_estimated_cost_usd": 0.001, "_sum_latency_ms": 1000,
                "_tavily_searches": 5, "_tavily_cached": 2, "_tavily_billable": 3,
            })
            return await backing.sum_rollups()

        out = asyncio.run(go())
        self.assertEqual(out["tavily_searches"], 5)
        self.assertEqual(out["tavily_cached"], 2)
        self.assertEqual(
            out["tavily_billable"], 3,
            "billable is SUMMED, not derived from attempts minus hits: a request that "
            "never left the process because no API key was configured costs nothing "
            "either, so subtracting only cache hits over-reported the bill",
        )

    def test_a_case_with_no_api_key_reports_attempts_but_no_credits(self):
        """
        The failure the derived version got wrong.

        With TAVILY_API_KEY unset, _search returns NO_API_KEY without making a request.
        Attempts still happened -- the pipeline tried -- but no credit was spent, and
        `attempts - cache_hits` would have reported a full bill for zero requests.
        """
        import asyncio

        from vf_logistics.store import MemoryStore

        backing = MemoryStore()

        async def go():
            await backing.put_case({
                "case_id": "C2", "shipment_id": "S2", "state": "INGESTED",
                "created_at": "2026-09-01T00:00:00+00:00",
                "_tavily_searches": 3, "_tavily_cached": 0, "_tavily_billable": 0,
            })
            return await backing.sum_rollups()

        out = asyncio.run(go())
        self.assertEqual(out["tavily_searches"], 3)
        self.assertEqual(out["tavily_billable"], 0)

    def test_the_firestore_index_script_covers_the_tavily_sums(self):
        """
        The five-index lesson, which is now seven. Firestore needs the AGGREGATED field
        in the index, not just the filtered ones, and the failure arrives only on the
        first windowed request -- which is when an invoice is being cut.
        """
        import pathlib

        script = (
            pathlib.Path(__file__).resolve().parents[1]
            / "infra" / "monitoring" / "create_billing_indexes.py"
        ).read_text(encoding="utf-8")
        for field in ("_tavily_searches", "_tavily_cached"):
            self.assertIn(field, script)


class TestTheModelNameInStringsAPersonReads(unittest.TestCase):
    """
    3. THE MODEL NAME NOBODY VALIDATES.

    `orchestrator.py` hard-coded "Super" into the auto-debate event string and into the
    Deep Review start event, on a hop that runs `debate_agent.MODEL_ID` -- Ultra by
    default. `debate_agent.py`'s own docstring records that the identical
    comment-vs-constant drift had already been copied into the README, the architecture
    diagram and the Devpost submission before anyone noticed.

    Nothing caught it because a wrong string in an audit record is still a valid string.
    These tests catch it: the label has to come from the model id, so changing
    DEBATE_MODEL changes what the audit trail says, and no literal can go stale.
    """

    def test_model_label_names_each_tier(self):
        self.assertEqual(config.model_label(NANO), "NVIDIA Nemotron 3 Nano")
        self.assertEqual(config.model_label(SUPER), "NVIDIA Nemotron 3 Super")
        self.assertEqual(config.model_label(ULTRA), "NVIDIA Nemotron 3 Ultra")

    def test_an_unknown_model_falls_back_to_its_own_id_not_a_guess(self):
        """
        Deliberately the raw id rather than a default tier name. `Nemotron-3_5-Lightning`
        is servable on Token Factory today and is absent from PRICING, so this path is
        reachable in production -- and a raw id cannot be mistaken for a claim, whereas
        "Nemotron 3 Nano" printed over an Ultra call can.
        """
        unknown = "nvidia/Nemotron-3_5-Lightning"
        self.assertEqual(config.model_label(unknown), unknown)

    def test_model_label_does_not_log_an_unpriced_model_error(self):
        """
        Why this is not `pricing_for(model)["name"]`. That function logs at ERROR on an
        unknown id, which is correct when money is being computed and wrong when a label
        is being rendered -- it would fire a billing error every time an event line is
        written, duplicating the one the cost path already emits.
        """
        with self.assertLogs("vf_logistics.config", level="ERROR") as captured:
            config.pricing_for("nvidia/does-not-exist")
            logging.getLogger("vf_logistics.config").error("sentinel")
        self.assertTrue(
            any("UNPRICED MODEL" in line for line in captured.output),
            "pricing_for should still log -- this test's premise is that it does",
        )

        logger = logging.getLogger("vf_logistics.config")
        with self.assertLogs(logger, level="ERROR") as captured:
            config.model_label("nvidia/does-not-exist")
            logger.error("sentinel")
        self.assertEqual(
            [line for line in captured.output if "UNPRICED MODEL" in line], [],
            "model_label must not emit a billing error just to render a name",
        )

    def test_the_debate_label_follows_DEBATE_MODEL(self):
        """
        The guard that matters. If someone reverts to a literal, this fails.
        """
        from vf_logistics.agents import debate_agent

        if os.getenv("DEBATE_MODEL"):
            self.skipTest("DEBATE_MODEL is set in this environment")
        self.assertEqual(
            config.model_label(debate_agent.MODEL_ID),
            "NVIDIA Nemotron 3 Super",
            "DEBATE_MODEL defaults to Super, so the label the audit trail carries for "
            "the debate hop must read Super -- if this says Ultra, the string has been "
            "hard-coded again",
        )
        self.assertNotIn("Ultra", config.model_label(debate_agent.MODEL_ID))

    def test_no_source_file_hardcodes_a_model_name_onto_the_debate_path(self):
        """
        A grep as a test, because this drifted back three times.

        The debate's model is debate_agent.MODEL_ID, and the strings a person reads must
        not name a model on that path: a name written out in a comment or an event string
        goes stale the day DEBATE_MODEL changes, and the stale name is what gets copied
        into the README and the submission. (Ultra was the default until the measured
        comparison moved it to Super; before that, "Super" was written over an Ultra hop.)

        Lines that name BOTH Super and Ultra are comparing them and are allowed. So are
        lines that point at MODEL_ID or DEBATE_MODEL, or that say "by default".
        """
        import pathlib
        import re

        src = pathlib.Path(__file__).resolve().parents[1] / "src" / "vf_logistics"
        offenders = []
        for path in src.rglob("*.py"):
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if not re.search(r"debate|Senior Auditor|deep.?review", line, re.I):
                    continue
                if not re.search(r"\b(Super|Ultra)\b", line):
                    continue
                if re.search(r"\bSuper\b", line) and re.search(r"\bUltra\b", line):
                    continue
                if re.search(r"MODEL_ID|DEBATE_MODEL|by default|model_label", line):
                    continue
                offenders.append(f"{path.name}:{number}: {line.strip()}")
        self.assertEqual(
            offenders, [],
            "these lines name a model on the debate/Senior Auditor/deep-review path "
            "without naming both models or pointing at MODEL_ID:\n  "
            + "\n  ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
