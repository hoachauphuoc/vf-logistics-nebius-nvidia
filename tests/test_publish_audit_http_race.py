"""
Two operators reconcile the same audit gap at the same moment through the HTTP route (review 2026-10-19, N01).
Both requests are made to read the gap before either writes, which is the interleaving the review reproduced;
the trail must still hold one publish_decision row, and the gap must end cleared.
"""

from __future__ import annotations

import asyncio
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
from test_console_session import TEST_KEY, mint  # noqa: E402
from test_publish_audit_gap import AuditGapBase  # noqa: E402
from vf_logistics import evidence, tools  # noqa: E402

ANA = "ana@forwarder.example"
BAO = "bao@forwarder.example"


def run(coro):
    return asyncio.run(coro)


class TestTwoOperatorsReconcileAtOnce(AuditGapBase):
    def setup_method(self):
        super().setup_method()
        from vf_logistics import app as app_mod

        self.operators = patch.dict(os.environ, {"OPERATOR_EMAILS": f"{ANA},{BAO}"})
        self.operators.start()
        self.app_mod = app_mod
        self.was = app_mod.limiter.enabled
        app_mod.limiter.enabled = False

    def teardown_method(self):
        self.app_mod.limiter.enabled = self.was
        self.operators.stop()
        super().teardown_method()

    def post(self, email):
        headers = {"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint(email, amr="password")}
        return self.app_mod.app.test_client().post("/api/v1/audit/reconcile", json={}, headers=headers)

    def both_at_once(self):
        """Both requests read the gap, and find no row for it, before either writes."""
        real_gaps = evidence.unreconciled_publish_audits

        async def slow_gaps(tenant_id=None):
            gaps = await real_gaps(tenant_id)
            await asyncio.sleep(0.2)
            return gaps

        async def nothing_yet(case_id, key, tenant_id):
            await asyncio.sleep(0.05)
            return None

        with patch.object(evidence, "unreconciled_publish_audits", new=slow_gaps), \
                patch.object(tools, "_earlier_publish", new=nothing_yet), \
                ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(self.post, [ANA, BAO]))

    def test_the_trail_holds_one_row_for_the_send(self):
        self.executed_with_the_audit_down()
        responses = self.both_at_once()
        assert all(r.status_code in (200, 409) for r in responses), [r.get_json() for r in responses]
        rows = self.publish_rows()
        assert len(rows) == 1
        assert rows[0]["detail"]["reconciled_by"] in (ANA, BAO)

    def test_only_one_request_reports_that_it_wrote_the_row(self):
        self.executed_with_the_audit_down()
        responses = self.both_at_once()
        written = sum((r.get_json() or {}).get("reconciled", 0) for r in responses if r.status_code == 200)
        assert written == 1

    def test_the_gap_ends_cleared_and_a_later_reconcile_adds_nothing(self):
        self.executed_with_the_audit_down()
        self.both_at_once()
        after = self.post(ANA)
        assert after.status_code == 200
        assert after.get_json()["pending"] == 0
        assert run(evidence.unreconciled_publish_audits()) == []
        assert len(self.publish_rows()) == 1
