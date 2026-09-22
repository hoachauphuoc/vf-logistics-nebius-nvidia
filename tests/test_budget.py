"""
The per-tenant spend ceiling.

WHAT THIS CLOSES

Before this, nothing in the service read accumulated spend and refused to proceed.
The existing protections were per-request and per-identity: the rate limiter keys on
`id:<email>` or `ip:<addr>` and never on a tenant, its storage is `memory://` so
every limit is per-instance and resets on deploy, and `MAX_BATCH_ITEMS` bounds one
request rather than one customer. A tenant staying under every published limit could
drive model calls indefinitely. The first hard stop was the Nebius account balance.

WHAT THESE TESTS DELIBERATELY DO NOT CLAIM

The ceiling is SOFT, and two tests below assert the softness rather than papering
over it. Spend is cached for a few seconds, and a call's cost is unknown until it
returns, so the check can only ask "was this tenant already over?". A test asserting
a hard cap would be asserting something the design does not provide.

CLASS NAMING

`Test*` prefix, because this project sets `python_files` and `python_functions` in
its pytest config but not `python_classes`, so the default prefix is what applies to
collection by name. A file in this suite once collected zero tests and reported
success.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics import budget  # noqa: E402
from vf_logistics import nebius_client  # noqa: E402
from vf_logistics.store import MemoryStore, utcnow  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def case(cid: str, cost: float) -> dict:
    """A case carrying only the rollup fields sum_rollups() reads."""
    return {
        "case_id": cid,
        "state": "AUTO_CLEARED",
        "created_at": utcnow(),
        "_agent_calls": 2,
        "_input_tokens": 1000,
        "_output_tokens": 500,
        "_estimated_cost_usd": cost,
        "_sum_latency_ms": 100,
    }


class BudgetTestBase(unittest.TestCase):
    def setUp(self):
        import vf_logistics.store as store_mod

        self.store_mod = store_mod
        self.store = MemoryStore()
        store_mod._store = self.store
        budget.forget()
        budget.set_current_tenant(None)

    def tearDown(self):
        self.store_mod._store = None
        budget.forget()
        budget.set_current_tenant(None)

    def spend(self, tenant: str, cost: float, cid: str = "C-1") -> None:
        _run(self.store.put_case(case(cid, cost), tenant_id=tenant))
        budget.forget(tenant)


class TestCeilingConfiguration(BudgetTestBase):
    """Reading VF_TENANT_SPEND_CEILING_USD, including the ways it can be wrong."""

    def _ceiling(self, value: str):
        with patch.dict(os.environ, {"VF_TENANT_SPEND_CEILING_USD": value}):
            return budget.ceiling_usd()

    def test_unset_means_no_ceiling(self):
        """
        The pre-existing behaviour, and therefore the right default: switching a
        ceiling on for a running deployment must be a deliberate act rather than a
        side effect of deploying this code.
        """
        self.assertIsNone(self._ceiling(""))
        self.assertIsNone(self._ceiling("   "))

    def test_a_number_is_read(self):
        self.assertEqual(self._ceiling("25"), 25.0)
        self.assertEqual(self._ceiling("0.5"), 0.5)

    def test_garbage_is_treated_as_no_ceiling_not_as_zero(self):
        """
        Zero would refuse every model call in the service. A typo in an environment
        variable must not be able to take the product offline.
        """
        for bad in ("abc", "25 dollars", "$25", "1e", "--5"):
            with self.subTest(value=bad):
                self.assertIsNone(self._ceiling(bad))

    def test_zero_and_negative_are_treated_as_no_ceiling(self):
        for bad in ("0", "0.0", "-1", "-0.5"):
            with self.subTest(value=bad):
                self.assertIsNone(self._ceiling(bad))


class TestEnforcement(BudgetTestBase):
    """assert_within_budget() across under, at and over the ceiling."""

    def test_no_ceiling_never_raises(self):
        self.spend("acme", 999.0)
        budget.set_current_tenant("acme")
        with patch.dict(os.environ, {"VF_TENANT_SPEND_CEILING_USD": ""}):
            _run(budget.assert_within_budget())  # must not raise

    def test_under_the_ceiling_passes(self):
        self.spend("acme", 1.0)
        budget.set_current_tenant("acme")
        with patch.dict(os.environ, {"VF_TENANT_SPEND_CEILING_USD": "10"}):
            _run(budget.assert_within_budget())

    def test_over_the_ceiling_raises(self):
        self.spend("acme", 11.0)
        budget.set_current_tenant("acme")
        with patch.dict(os.environ, {"VF_TENANT_SPEND_CEILING_USD": "10"}):
            with self.assertRaises(budget.BudgetExceeded):
                _run(budget.assert_within_budget())

    def test_exactly_at_the_ceiling_raises(self):
        """
        The boundary is inclusive. An off-by-one here means the ceiling is one
        model call higher than it says, which is the kind of thing nobody notices
        until the invoice.
        """
        self.spend("acme", 10.0)
        budget.set_current_tenant("acme")
        with patch.dict(os.environ, {"VF_TENANT_SPEND_CEILING_USD": "10"}):
            with self.assertRaises(budget.BudgetExceeded):
                _run(budget.assert_within_budget())

    def test_the_error_names_the_numbers(self):
        """
        An operator seeing this in a log needs to know how far over, not only that
        something was refused.
        """
        self.spend("acme", 12.5)
        budget.set_current_tenant("acme")
        with patch.dict(os.environ, {"VF_TENANT_SPEND_CEILING_USD": "10"}):
            try:
                _run(budget.assert_within_budget())
                self.fail("expected BudgetExceeded")
            except budget.BudgetExceeded as exc:
                self.assertEqual(exc.tenant_id, "acme")
                self.assertAlmostEqual(exc.spent_usd, 12.5, places=6)
                self.assertEqual(exc.ceiling_usd, 10.0)
                self.assertIn("12.5", str(exc))
                self.assertIn("10.00", str(exc))


class TestPerTenantIsolation(BudgetTestBase):
    """
    One customer's overspend must not stop another's shipments.

    This is the property that makes the ceiling usable at all. A global cap would
    mean the noisiest tenant decides when everyone else stops being screened.
    """

    def test_one_tenant_over_does_not_block_another(self):
        self.spend("acme", 50.0, cid="C-ACME")
        self.spend("globex", 1.0, cid="C-GLOBEX")

        with patch.dict(os.environ, {"VF_TENANT_SPEND_CEILING_USD": "10"}):
            budget.set_current_tenant("acme")
            with self.assertRaises(budget.BudgetExceeded):
                _run(budget.assert_within_budget())

            budget.set_current_tenant("globex")
            _run(budget.assert_within_budget())  # must not raise

    def test_spend_is_read_per_tenant_not_globally(self):
        self.spend("acme", 6.0, cid="C-ACME")
        self.spend("globex", 6.0, cid="C-GLOBEX")

        # 12 in total, 6 each. A global read would put both over a ceiling of 10.
        with patch.dict(os.environ, {"VF_TENANT_SPEND_CEILING_USD": "10"}):
            for who in ("acme", "globex"):
                with self.subTest(tenant=who):
                    budget.set_current_tenant(who)
                    _run(budget.assert_within_budget())

    def test_spend_so_far_is_scoped(self):
        self.spend("acme", 3.0, cid="C-ACME")
        self.spend("globex", 7.0, cid="C-GLOBEX")

        self.assertAlmostEqual(_run(budget.spend_so_far("acme")), 3.0, places=6)
        self.assertAlmostEqual(_run(budget.spend_so_far("globex")), 7.0, places=6)


class TestTenantContext(BudgetTestBase):
    """How the tenant reaches the check, and what happens when it does not."""

    def test_unset_falls_back_to_the_single_tenant(self):
        """
        Falling back rather than raising. A model call reaching the check with no
        tenant in context is a wiring bug, and taking the service down over it is a
        worse outcome than charging the only tenant that exists when multi-tenancy
        is off.
        """
        from vf_logistics import tenant as tenant_mod

        budget.set_current_tenant(None)
        self.assertEqual(budget.current_tenant(), tenant_mod.SINGLE_TENANT_ID)

    def test_the_tenant_is_normalised(self):
        budget.set_current_tenant("ACME-Freight")
        self.assertEqual(budget.current_tenant(), "acme-freight")

    def test_concurrent_tasks_do_not_share_a_tenant(self):
        """
        The reason a ContextVar is used rather than a module global. asyncio copies
        the context into each task at creation, so two cases advancing at once must
        not see each other's tenant -- which would bill one customer for another's
        model calls.
        """
        seen: dict[str, str] = {}

        async def work(name: str) -> None:
            budget.set_current_tenant(name)
            # Yield, so the other task definitely interleaves between the set and
            # the read. Without an await this would pass even with a global.
            await asyncio.sleep(0)
            seen[name] = budget.current_tenant()

        async def both() -> None:
            await asyncio.gather(work("acme"), work("globex"))

        _run(both())
        self.assertEqual(seen, {"acme": "acme", "globex": "globex"})


class TestFailureModes(BudgetTestBase):
    """What happens when the store cannot answer."""

    def test_a_store_failure_fails_open(self):
        """
        Deliberately the wrong direction, and the docstring in budget.py says so: a
        Firestore blip must not stop a customer's shipments being screened. The
        ceiling is a cost control, not a safety control.
        """
        class Broken:
            async def sum_rollups(self, tenant_id=None):
                raise RuntimeError("firestore unavailable")

        self.store_mod._store = Broken()
        budget.forget()

        self.assertEqual(_run(budget.spend_so_far("acme")), 0.0)

        budget.set_current_tenant("acme")
        with patch.dict(os.environ, {"VF_TENANT_SPEND_CEILING_USD": "10"}):
            _run(budget.assert_within_budget())  # allowed, not refused


class TestCaching(BudgetTestBase):
    """The cache, and the overshoot it admits to."""

    def test_a_repeat_read_inside_the_ttl_does_not_hit_the_store(self):
        counter = {"reads": 0}
        real = self.store.sum_rollups

        async def counted(tenant_id=None):
            counter["reads"] += 1
            return await real(tenant_id=tenant_id)

        self.store.sum_rollups = counted  # type: ignore[method-assign]
        self.spend("acme", 1.0)

        _run(budget.spend_so_far("acme"))
        _run(budget.spend_so_far("acme"))
        _run(budget.spend_so_far("acme"))
        self.assertEqual(
            counter["reads"], 1, "the cache should collapse three reads into one"
        )

    def test_forget_invalidates_one_tenant_only(self):
        self.spend("acme", 1.0, cid="C-ACME")
        self.spend("globex", 1.0, cid="C-GLOBEX")
        _run(budget.spend_so_far("acme"))
        _run(budget.spend_so_far("globex"))

        # More spend appears for both, but only acme is invalidated.
        _run(self.store.put_case(case("C-ACME-2", 5.0), tenant_id="acme"))
        _run(self.store.put_case(case("C-GLOBEX-2", 5.0), tenant_id="globex"))
        budget.forget("acme")

        self.assertAlmostEqual(_run(budget.spend_so_far("acme")), 6.0, places=6)
        self.assertAlmostEqual(
            _run(budget.spend_so_far("globex")), 1.0, places=6,
            msg="globex was not invalidated and should still read its cached total",
        )

    def test_the_ttl_is_short_enough_to_bound_the_overshoot(self):
        """
        Not a behavioural test -- a bound on the design. The overshoot a tenant can
        achieve is whatever they can spend inside one TTL window, so this number
        being small is the whole mitigation. If someone raises it to a minute, the
        ceiling becomes decorative.
        """
        self.assertLessEqual(budget.CACHE_TTL_SECONDS, 10.0)


class TestWiredIntoEveryModelCall(unittest.TestCase):
    """
    The check must sit at the chokepoint, not at the call sites.

    There are nine agent call sites and three client entry points. All three go
    through `_with_retry`, so that is the only place where forgetting one is
    impossible. These tests fail if someone moves the check out of it.
    """

    def test_with_retry_asserts_the_budget(self):
        source = inspect.getsource(nebius_client._with_retry)
        self.assertIn("assert_within_budget", source)

    def test_the_check_is_before_the_retry_loop(self):
        """
        Once per logical call, not once per attempt. A retry is the same billable
        intent, and refusing halfway through a backoff sequence would abandon a call
        that has already been paid for.
        """
        source = inspect.getsource(nebius_client._with_retry)
        self.assertLess(
            source.index("assert_within_budget"),
            source.index("for attempt in range"),
            "the budget check must run before the retry loop, not inside it",
        )

    def test_every_client_entry_point_routes_through_with_retry(self):
        for name in ("complete_json", "complete_with_tools", "complete_vision_json"):
            with self.subTest(entry=name):
                source = inspect.getsource(getattr(nebius_client, name))
                self.assertIn("_with_retry", source)

    def test_the_orchestrator_declares_the_tenant(self):
        """
        The ContextVar is useless unless something sets it. These are the three
        entry points that run models: one transition, one document intake, one
        debate.
        """
        from vf_logistics import orchestrator

        for func in (
            orchestrator.advance,
            orchestrator.ingest_document,
            orchestrator.deep_review,
        ):
            with self.subTest(func=func.__name__):
                self.assertIn("set_current_tenant", inspect.getsource(func))


class TestStatusReport(BudgetTestBase):
    """The reporting shape, including that it does not overclaim."""

    def test_status_reports_spend_and_headroom(self):
        self.spend("acme", 4.0)
        with patch.dict(os.environ, {"VF_TENANT_SPEND_CEILING_USD": "10"}):
            report = _run(budget.status("acme"))

        self.assertEqual(report["tenant_id"], "acme")
        self.assertAlmostEqual(report["spent_usd"], 4.0, places=6)
        self.assertEqual(report["ceiling_usd"], 10.0)
        self.assertAlmostEqual(report["remaining_usd"], 6.0, places=6)
        self.assertFalse(report["over_ceiling"])
        self.assertEqual(report["enforcement"], "soft")

    def test_remaining_is_clamped_at_zero(self):
        """A negative headroom in a dashboard reads as a bug, not as an overshoot."""
        self.spend("acme", 14.0)
        with patch.dict(os.environ, {"VF_TENANT_SPEND_CEILING_USD": "10"}):
            report = _run(budget.status("acme"))

        self.assertEqual(report["remaining_usd"], 0.0)
        self.assertTrue(report["over_ceiling"])

    def test_status_says_none_when_no_ceiling_is_configured(self):
        """
        The honest answer for an unconfigured deployment. Reporting a ceiling that
        is not being enforced would be worse than reporting none.
        """
        self.spend("acme", 4.0)
        with patch.dict(os.environ, {"VF_TENANT_SPEND_CEILING_USD": ""}):
            report = _run(budget.status("acme"))

        self.assertIsNone(report["ceiling_usd"])
        self.assertIsNone(report["remaining_usd"])
        self.assertFalse(report["over_ceiling"])
        self.assertEqual(report["enforcement"], "none")


if __name__ == "__main__":
    unittest.main()
