"""
The billing period, and the two metering defects it sits next to.

WHAT WAS WRONG

1. NO BILLING PERIOD. `sum_rollups()` had no time filter, so it could only report
   lifetime-to-date totals, and nothing snapshotted them. A month's usage was not
   computable even in principle -- not from one call, and not from the difference of
   two, because the earlier figure was never stored.

2. THE VISION CALL WAS INVISIBLE TO BILLING. `intake_step` is built with real token
   counts and inserted straight into `steps` by ingest_shipment, bypassing
   `_record_step` -- the only other place the rollups are incremented. So the audit
   record priced it (it reads `steps[]`) while `/api/v1/billing/usage` did not (it
   reads the rollups). The two disagreed on every document-sourced case, and billing
   held the lower number. It was the worst call to lose: the vision model's input
   rate is the highest in the table, roughly 11x Nano's.

3. FOUR COPIES OF THE PRICING FORMULA. `lineage.cost_usd()`, which nothing called,
   plus inline copies in `_record_step`, in the debate rollup, and in
   `backfill_rollups`. A rate-card change had to be made correctly in four files.

CLASS NAMING

`Test*` prefix, because this project does not set `python_classes` in its pytest
config, so the default prefix governs collection by name.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics import lineage  # noqa: E402
from vf_logistics import orchestrator  # noqa: E402
from vf_logistics import store as store_mod  # noqa: E402
from vf_logistics.store import MemoryStore  # noqa: E402

TENANT = "acme-freight"


def _run(coro):
    return asyncio.run(coro)


def case_at(cid: str, created_at: str, cost: float, calls: int = 2) -> dict:
    return {
        "case_id": cid,
        "state": "AUTO_CLEARED",
        "cleared_by": "rules",
        "created_at": created_at,
        "_agent_calls": calls,
        "_input_tokens": 1000,
        "_output_tokens": 500,
        "_estimated_cost_usd": cost,
        "_sum_latency_ms": 100,
    }


class WindowTestBase(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        store_mod._store = self.store

    def tearDown(self):
        store_mod._store = None

    def seed(self):
        """Three cases in three different months, same tenant."""
        _run(self.store.put_case(
            case_at("C-JAN", "2026-01-15T10:00:00+00:00", 1.0), tenant_id=TENANT))
        _run(self.store.put_case(
            case_at("C-FEB", "2026-02-15T10:00:00+00:00", 2.0), tenant_id=TENANT))
        _run(self.store.put_case(
            case_at("C-MAR", "2026-03-15T10:00:00+00:00", 4.0), tenant_id=TENANT))


class TestBillingWindow(WindowTestBase):
    """sum_rollups() bounded by created_at."""

    def test_no_window_is_lifetime(self):
        self.seed()
        totals = _run(self.store.sum_rollups(tenant_id=TENANT))
        self.assertAlmostEqual(totals["estimated_cost_usd"], 7.0, places=6)

    def test_one_month_is_isolated(self):
        self.seed()
        feb = _run(self.store.sum_rollups(
            tenant_id=TENANT,
            since="2026-02-01T00:00:00+00:00",
            until="2026-03-01T00:00:00+00:00",
        ))
        self.assertAlmostEqual(feb["estimated_cost_usd"], 2.0, places=6)
        self.assertEqual(feb["agent_calls"], 2)

    def test_since_alone_is_open_ended(self):
        self.seed()
        totals = _run(self.store.sum_rollups(
            tenant_id=TENANT, since="2026-02-01T00:00:00+00:00"
        ))
        self.assertAlmostEqual(totals["estimated_cost_usd"], 6.0, places=6)

    def test_until_alone_is_open_ended(self):
        self.seed()
        totals = _run(self.store.sum_rollups(
            tenant_id=TENANT, until="2026-02-01T00:00:00+00:00"
        ))
        self.assertAlmostEqual(totals["estimated_cost_usd"], 1.0, places=6)

    def test_the_window_is_half_open(self):
        """
        since <= created_at < until. The property that matters: consecutive periods
        must partition the cases exactly, with no case counted twice and none
        dropped. Closed-closed bounds would bill the boundary case to both months.
        """
        boundary = "2026-02-01T00:00:00+00:00"
        _run(self.store.put_case(
            case_at("C-BOUNDARY", boundary, 5.0), tenant_id=TENANT))

        january = _run(self.store.sum_rollups(
            tenant_id=TENANT,
            since="2026-01-01T00:00:00+00:00",
            until=boundary,
        ))
        february = _run(self.store.sum_rollups(
            tenant_id=TENANT,
            since=boundary,
            until="2026-03-01T00:00:00+00:00",
        ))

        self.assertEqual(january["estimated_cost_usd"], 0.0, "boundary billed to Jan")
        self.assertAlmostEqual(february["estimated_cost_usd"], 5.0, places=6)

    def test_consecutive_windows_sum_to_the_lifetime_total(self):
        """The invoice property: the months must add up to everything."""
        self.seed()
        months = [
            ("2026-01-01T00:00:00+00:00", "2026-02-01T00:00:00+00:00"),
            ("2026-02-01T00:00:00+00:00", "2026-03-01T00:00:00+00:00"),
            ("2026-03-01T00:00:00+00:00", "2026-04-01T00:00:00+00:00"),
        ]
        summed = 0.0
        for since, until in months:
            part = _run(self.store.sum_rollups(
                tenant_id=TENANT, since=since, until=until))
            summed += part["estimated_cost_usd"]

        lifetime = _run(self.store.sum_rollups(tenant_id=TENANT))
        self.assertAlmostEqual(summed, lifetime["estimated_cost_usd"], places=6)

    def test_a_window_is_still_tenant_scoped(self):
        """
        Adding a time filter must not have widened the scope. A period query that
        reached another tenant's cases would be a cross-customer invoice.
        """
        _run(self.store.put_case(
            case_at("C-A", "2026-02-15T10:00:00+00:00", 3.0), tenant_id=TENANT))
        _run(self.store.put_case(
            case_at("C-B", "2026-02-15T10:00:00+00:00", 9.0), tenant_id="globex"))

        window = dict(
            since="2026-02-01T00:00:00+00:00", until="2026-03-01T00:00:00+00:00"
        )
        mine = _run(self.store.sum_rollups(tenant_id=TENANT, **window))
        theirs = _run(self.store.sum_rollups(tenant_id="globex", **window))

        self.assertAlmostEqual(mine["estimated_cost_usd"], 3.0, places=6)
        self.assertAlmostEqual(theirs["estimated_cost_usd"], 9.0, places=6)

    def test_a_case_with_no_created_at_is_excluded_from_a_window(self):
        """
        Conservative on purpose: a case whose age is unknown cannot be asserted to
        fall inside a billing period, and billing it to whichever period happens to
        be queried would be worse than leaving it out.
        """
        undated = case_at("C-UNDATED", "2026-02-15T10:00:00+00:00", 8.0)
        del undated["created_at"]
        _run(self.store.put_case(undated, tenant_id=TENANT))

        windowed = _run(self.store.sum_rollups(
            tenant_id=TENANT,
            since="2026-02-01T00:00:00+00:00",
            until="2026-03-01T00:00:00+00:00",
        ))
        lifetime = _run(self.store.sum_rollups(tenant_id=TENANT))

        self.assertEqual(windowed["estimated_cost_usd"], 0.0)
        self.assertAlmostEqual(
            lifetime["estimated_cost_usd"], 8.0, places=6,
            msg="an undated case must still appear in the unbounded total",
        )


class TestTenantUsagePeriod(WindowTestBase):
    """lineage.tenant_usage() threading the window through, and saying so."""

    def test_the_period_is_echoed(self):
        """
        These numbers end up on an invoice. "Which period is this" must be answerable
        from the response alone, not inferred from what the caller remembers asking.
        """
        self.seed()
        usage = _run(lineage.tenant_usage(
            TENANT,
            since="2026-02-01T00:00:00+00:00",
            until="2026-03-01T00:00:00+00:00",
        ))
        self.assertEqual(usage["period"]["since"], "2026-02-01T00:00:00+00:00")
        self.assertEqual(usage["period"]["until"], "2026-03-01T00:00:00+00:00")
        self.assertEqual(usage["period"]["kind"], "window")
        self.assertAlmostEqual(usage["estimated_cost_usd"], 2.0, places=6)

    def test_lifetime_is_labelled_lifetime(self):
        self.seed()
        usage = _run(lineage.tenant_usage(TENANT))
        self.assertEqual(usage["period"]["kind"], "lifetime")
        self.assertIsNone(usage["period"]["since"])
        self.assertAlmostEqual(usage["estimated_cost_usd"], 7.0, places=6)

    def test_the_clearance_counts_declare_that_they_are_not_windowed(self):
        """
        count_by_cleared_by() has no time filter, so these stay lifetime counts inside
        a windowed call. Stated in the response rather than quietly tolerated --
        presenting a lifetime count as a period figure would be the wrong kind of
        wrong.
        """
        self.seed()
        usage = _run(lineage.tenant_usage(
            TENANT,
            since="2026-02-01T00:00:00+00:00",
            until="2026-03-01T00:00:00+00:00",
        ))
        self.assertTrue(usage["counts_are_lifetime"])
        self.assertEqual(usage["auto_cleared"], 3, "all three, not just February's")

    def test_an_absent_tenant_still_raises(self):
        """The window must not have introduced a path that defaults the tenant."""
        from vf_logistics import tenant as tenant_mod

        for bad in (None, "", "   "):
            with self.subTest(tenant=bad):
                with self.assertRaises(tenant_mod.TenantError):
                    _run(lineage.tenant_usage(
                        bad, since="2026-02-01T00:00:00+00:00"
                    ))


class TestBackendParity(unittest.TestCase):
    """
    Both backends must accept the same window arguments.

    A billing figure that depended on which backend answered would be worse than no
    figure, and the Firestore path is the one that runs in production while every
    behavioural test above runs on memory.
    """

    def test_both_signatures_accept_since_and_until(self):
        from vf_logistics.store import FirestoreStore

        for cls in (MemoryStore, FirestoreStore):
            with self.subTest(backend=cls.__name__):
                params = inspect.signature(cls.sum_rollups).parameters
                self.assertIn("since", params)
                self.assertIn("until", params)
                self.assertIsNone(params["since"].default)
                self.assertIsNone(params["until"].default)

    def test_firestore_filters_on_created_at(self):
        """
        Source-level, because exercising it needs a live Firestore. Checks the filter
        is applied to the shared base query -- if it were applied per-aggregation,
        one of the five sums could silently report lifetime totals inside a period
        report.
        """
        from vf_logistics.store import FirestoreStore

        source = inspect.getsource(FirestoreStore.sum_rollups)
        self.assertIn('"created_at", ">="', source)
        self.assertIn('"created_at", "<"', source)
        self.assertLess(
            source.index('"created_at", ">="'),
            source.index('base.sum("_input_tokens")'),
            "the window must be applied before the aggregations are built",
        )

    def test_firestore_documents_the_index_requirement(self):
        """
        The requirement must be written down where the query is, and it must state the
        RULE rather than a list.

        This test used to assert that each of the five aggregated fields was named in
        the docstring, on the reasoning that "nobody creates four and assumes they are
        done". Enumerating them there turned out to be the weaker guarantee: the list
        was accurate and the *rule* beside it was wrong -- it said the unbounded call
        needed no indexes, which is false, and the Tavily sums shipped with only the
        windowed shape because of it. The unbounded GET /billing/usage then returned 500
        in production.

        So the enumeration moved to
        test_the_index_definitions_cover_both_query_shapes, which checks the real
        index definitions against the real aggregations instead of against prose. What
        is checked here is that the two shapes are both described.
        """
        from vf_logistics.store import FirestoreStore

        doc = inspect.getdoc(FirestoreStore.sum_rollups) or ""
        self.assertIn("index", doc.lower())
        self.assertIn("created_at", doc)
        self.assertIn(
            "(_tenant_id ASC, <field> ASC)", doc,
            "the unbounded index shape must be documented; omitting it is the mistake "
            "that put a 500 on the console's billing page",
        )
        self.assertIn("(_tenant_id ASC, created_at ASC, <field> ASC)", doc)

    def test_the_index_script_covers_every_aggregation(self):
        """
        The script and the query must not drift. If another aggregation is added to
        sum_rollups without a matching index, billing starts failing -- so the two lists
        are compared here rather than trusted.
        """
        import re
        from pathlib import Path

        from vf_logistics.store import FirestoreStore

        script = (
            Path(__file__).resolve().parents[1]
            / "infra" / "monitoring" / "create_billing_indexes.py"
        ).read_text(encoding="utf-8")

        source = inspect.getsource(FirestoreStore.sum_rollups)
        aggregated = set(re.findall(r'base\.sum\("([^"]+)"\)', source))
        self.assertTrue(aggregated, "no sum() aggregations found; the regex is stale")

        for field in aggregated:
            self.assertIn(
                f'"{field}"',
                script,
                f"{field} is aggregated but has no index in create_billing_indexes.py",
            )

    def test_the_index_definitions_cover_both_query_shapes(self):
        """
        Two indexes per aggregated field, and this is the test that was missing.

        The windowed query filters (_tenant_id, created_at); the unbounded one filters
        only _tenant_id. An index prefix has to match the query's filters, so the
        three-field index does NOT satisfy the unbounded query. The Tavily sums were
        added with only the windowed shape: every windowed test passed and the
        UNBOUNDED GET /billing/usage returned 500 in production, naming
        (_tenant_id, _tavily_searches). The windowed path was the tested one; the
        unbounded path was the one every console page calls.
        """
        import json
        import re
        from pathlib import Path

        from vf_logistics.store import FirestoreStore

        definitions = json.loads(
            (
                Path(__file__).resolve().parents[1] / "infra" / "firestore.indexes.json"
            ).read_text(encoding="utf-8")
        )
        indexes = definitions.get("indexes", definitions)

        shapes = {
            tuple(f["fieldPath"] for f in idx.get("fields", []))
            for idx in indexes
            if idx.get("collectionGroup") == "cases"
        }

        source = inspect.getsource(FirestoreStore.sum_rollups)
        aggregated = sorted(set(re.findall(r'base\.sum\("([^"]+)"\)', source)))
        self.assertTrue(aggregated, "no sum() aggregations found; the regex is stale")

        for field in aggregated:
            with self.subTest(field=field):
                self.assertIn(
                    ("_tenant_id", field), shapes,
                    f"{field} has no UNBOUNDED index (_tenant_id, {field}) -- "
                    f"GET /billing/usage with no period will 500",
                )
                self.assertIn(
                    ("_tenant_id", "created_at", field), shapes,
                    f"{field} has no WINDOWED index (_tenant_id, created_at, {field})",
                )


class TestVisionCallIsMetered(unittest.TestCase):
    """
    The document-intake step's tokens must reach the rollups, not only `steps`.
    """

    def setUp(self):
        self.store = MemoryStore()
        store_mod._store = self.store

    def tearDown(self):
        store_mod._store = None

    def _ingest_with_intake(self) -> dict:
        intake = {
            "agent": "document_intake",
            "latency_ms": 4200,
            "model": "openbmb/MiniCPM-V-4_5",
            "input_tokens": 3000,
            "output_tokens": 700,
        }
        return _run(orchestrator.ingest_shipment(
            {
                "shipment_id": "SHP-VISION-1",
                "origin": "Ho Chi Minh City, Vietnam",
                "destination": "PSA Singapore, Singapore",
                "weight_kg": 1200,
                "declared_value": 40000,
                "shipping_cost": 1800,
                "cargo_description": "cotton fabric rolls",
                "status": "pending",
            },
            source="document",
            intake_step=intake,
        ))

    def test_the_rollups_include_the_vision_tokens(self):
        case = self._ingest_with_intake()
        self.assertEqual(case["_input_tokens"], 3000)
        self.assertEqual(case["_output_tokens"], 700)
        self.assertEqual(case["_agent_calls"], 1)
        self.assertEqual(case["_sum_latency_ms"], 4200)

    def test_the_vision_cost_is_priced_at_the_vision_rate(self):
        """
        Not at Nano's. `pricing_for()` falls back to Nano for an unknown model, so a
        wrong model id here would produce a plausible number 11x too low.
        """
        case = self._ingest_with_intake()
        expected = lineage.cost_usd("openbmb/MiniCPM-V-4_5", 3000, 700)
        self.assertAlmostEqual(case["_estimated_cost_usd"], expected, places=10)
        self.assertGreater(
            case["_estimated_cost_usd"],
            lineage.cost_usd("nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B", 3000, 700),
            "the vision rate must be dearer than Nano's, or the wrong table was used",
        )

    def test_the_step_and_the_rollup_agree(self):
        """
        The defect was that they disagreed: the audit record reads `steps[]` and the
        billing endpoint reads the rollups, and only the first saw this call.
        """
        case = self._ingest_with_intake()
        step = case["steps"][0]
        self.assertAlmostEqual(
            step["cost_usd"], case["_estimated_cost_usd"], places=8
        )

    def test_billing_sees_it(self):
        """End to end: the number sum_rollups reports must include the vision call."""
        self._ingest_with_intake()
        totals = _run(self.store.sum_rollups())
        self.assertEqual(totals["total_input_tokens"], 3000)
        self.assertGreater(totals["estimated_cost_usd"], 0.0)

    def test_a_case_with_no_intake_step_has_no_rollups(self):
        """
        An event-sourced case must not acquire a phantom agent call. Setting
        `_agent_calls = 1` unconditionally would make every case look like it had run
        a model.
        """
        case = _run(orchestrator.ingest_shipment(
            {
                "shipment_id": "SHP-EVENT-1",
                "origin": "Ho Chi Minh City, Vietnam",
                "destination": "PSA Singapore, Singapore",
                "weight_kg": 1200,
                "declared_value": 40000,
                "shipping_cost": 1800,
                "cargo_description": "cotton fabric rolls",
                "status": "pending",
            },
            source="event",
        ))
        self.assertNotIn("_agent_calls", case)
        self.assertEqual(case["steps"], [])


class TestOnePricingImplementation(unittest.TestCase):
    """
    The formula must exist once.

    Four copies meant a rate-card change had to be made correctly in four files, and
    three of them were invisible from the one that looked canonical.
    """

    def test_the_orchestrator_calls_the_canonical_function(self):
        for func in (orchestrator._record_step, orchestrator.deep_review):
            with self.subTest(func=func.__name__):
                source = inspect.getsource(func)
                self.assertIn("lineage.cost_usd", source)

    def test_no_inline_division_by_a_million_remains(self):
        """
        `/ 1_000_000` is the signature of a hand-rolled copy of the rate arithmetic.
        It should appear in exactly one function in the codebase: cost_usd itself.
        """
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "src" / "vf_logistics"
        offenders: list[str] = []
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for number, line in enumerate(text.splitlines(), start=1):
                if "1_000_000" not in line:
                    continue
                # Field validators use le=1_000_000 as a weight bound, which is not
                # a price.
                if "le=1_000_000" in line:
                    continue
                if path.name == "lineage.py":
                    continue
                offenders.append(f"{path.name}:{number}")

        self.assertEqual(
            offenders, [], f"inline pricing arithmetic still present at {offenders}"
        )

    def test_cost_usd_uses_the_published_rate_table(self):
        from vf_logistics import config as model_config

        pricing = model_config.PRICING["nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"]
        expected = (1_000_000 * pricing["input"] + 1_000_000 * pricing["output"]) / 1_000_000
        self.assertAlmostEqual(
            lineage.cost_usd(
                "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B", 1_000_000, 1_000_000
            ),
            expected,
            places=10,
        )


if __name__ == "__main__":
    unittest.main()
