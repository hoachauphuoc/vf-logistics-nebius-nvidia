"""
What happens when a model is called that nobody priced.

`set_model()` refuses any id absent from `config.PRICING`, which reads like the hole
is closed. It is not: `_model_id` is initialised straight from the NEMOTRON_MODEL
environment variable and never passes through that check. So a deployment can be
pointed at an unpriced model -- `nvidia/Nemotron-3_5-Lightning` is servable on Token
Factory today and is absent from the table -- or simply at a typo, and every call is
then costed at the cheapest rate in the table.

That direction matters. Under-reporting protects the customer's invoice and endangers
the operator, because `budget.assert_within_budget()` reads these same figures: an
unpriced model makes the tenant spend ceiling leak while the month looks cheap. The
fix is not a guessed rate -- inventing one would be wrong with the authority of a
real number -- it is refusing to be quiet about it.
"""

from __future__ import annotations

import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics import config  # noqa: E402

UNPRICED = "nvidia/Nemotron-3_5-Lightning"


class TestAnUnpricedModelIsNotSilent(unittest.TestCase):
    def test_the_known_gap_is_still_a_gap(self):
        """
        Precondition. If Lightning gains a real rate, price it and delete this.
        """
        self.assertNotIn(
            UNPRICED, config.PRICING,
            "Lightning is now priced -- update pricing_for()'s docstring, which cites "
            "it as the live example, and remove this precondition",
        )

    def test_pricing_an_unknown_model_logs_at_error(self):
        with self.assertLogs("vf_logistics.config", level=logging.ERROR) as captured:
            config.pricing_for(UNPRICED)

        joined = "\n".join(captured.output)
        self.assertIn(UNPRICED, joined, "the log must name the model")
        self.assertIn(
            "too LOW", joined,
            "the log must state the direction of the error, because under-reporting "
            "is what makes the spend ceiling leak",
        )

    def test_a_typo_is_treated_the_same_as_an_unpriced_model(self):
        with self.assertLogs("vf_logistics.config", level=logging.ERROR):
            priced = config.pricing_for("nvidia/NVIDIA-Nemotron-3-Nano-30B-A3")

        # Still returns a usable rate rather than raising: a billing defect must not
        # take down shipment screening.
        self.assertIn("input", priced)
        self.assertIn("output", priced)

    def test_a_known_model_logs_nothing(self):
        with self.assertNoLogs("vf_logistics.config", level=logging.ERROR):
            priced = config.pricing_for("nvidia/nemotron-3-super-120b-a12b")
        self.assertEqual(priced["input"], 0.30)

    def test_no_model_at_all_is_not_an_error(self):
        """
        A step with no model recorded is ordinary -- the deterministic verifier and
        the prefilter both run without one. It must not be logged as a pricing fault.
        """
        with self.assertNoLogs("vf_logistics.config", level=logging.ERROR):
            config.pricing_for(None)
        with self.assertNoLogs("vf_logistics.config", level=logging.ERROR):
            config.pricing_for("")


class TestTheFallbackIsTheCheapestRate(unittest.TestCase):
    """
    Pinned because the choice is deliberate and the reasoning is not obvious.
    """

    def test_the_fallback_is_the_cheapest_entry_in_the_table(self):
        fallback = config.pricing_for(UNPRICED_FOR_COMPARISON := "definitely/not-real")
        cheapest = min(PRICING_INPUT := [v["input"] for v in config.PRICING.values()])
        self.assertEqual(
            fallback["input"], cheapest,
            "the fallback must stay the cheapest rate so an unpriced model never "
            "inflates a customer's invoice; the operator-side risk is handled by "
            "logging, not by guessing high",
        )
        del UNPRICED_FOR_COMPARISON, PRICING_INPUT


class TestStartupReportsUnpricedConfiguration(unittest.TestCase):
    def test_an_unpriced_selection_is_reported_at_import_time(self):
        original = config._model_id
        try:
            config._model_id = UNPRICED
            with self.assertLogs("vf_logistics.config", level=logging.ERROR) as captured:
                offenders = config.warn_on_unpriced_selection()
        finally:
            config._model_id = original

        self.assertIn(UNPRICED, offenders)
        self.assertIn("spend ceiling", "\n".join(captured.output))

    def test_it_does_not_refuse_to_start(self):
        """
        Contrast auth.assert_write_access_is_guarded(), which does halt the boot. That
        one prevents a breach; this one prevents a wrong number, and taking a working
        service offline over an accounting defect is the larger outage.
        """
        original = config._model_id
        try:
            config._model_id = UNPRICED
            with self.assertLogs("vf_logistics.config", level=logging.ERROR):
                config.warn_on_unpriced_selection()  # must not raise
        finally:
            config._model_id = original

    def test_the_default_configuration_is_fully_priced(self):
        with self.assertNoLogs("vf_logistics.config", level=logging.ERROR):
            offenders = config.warn_on_unpriced_selection()
        self.assertEqual(
            offenders, [],
            "the shipped defaults for NEMOTRON_MODEL and VISION_MODEL must both be "
            "in PRICING",
        )


if __name__ == "__main__":
    unittest.main()
