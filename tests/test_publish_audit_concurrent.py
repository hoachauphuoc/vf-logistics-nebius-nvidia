"""
Two writers that both find no publish_decision row for one idempotency key must leave one row, not two
(review 2026-10-19, N01): the existence check and the write are separate steps, so the row has to be created
under an id derived from the key, and a second create must answer "already there".
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
from test_evidence_eval_approve import Base  # noqa: E402
from vf_logistics import tools  # noqa: E402

DETAIL = {"idempotency_key": "KEY-1", "message_id": "msg-1", "case_id": "CASE-1", "action": "release"}


def run(coro):
    return asyncio.run(coro)


class TestConcurrentReconciliation(Base):
    def rows(self, tenant_id=None):
        return [r for r in run(self.store.list_audit(limit=500, tenant_id=tenant_id)) if r.get("action") == "publish_decision"]

    def both_see_nothing(self):
        """The interleaving of the review: each writer reads before the other has written."""
        async def nothing_yet(case_id, key, tenant_id):
            await asyncio.sleep(0)
            return None

        return patch.object(tools, "_earlier_publish", new=nothing_yet)

    def test_two_reconciliations_of_one_send_leave_one_row_and_one_winner(self):
        async def both():
            return await asyncio.gather(
                tools.record_publish_audit("CASE-1", dict(DETAIL), "ana@x.com"),
                tools.record_publish_audit("CASE-1", dict(DETAIL), "bao@x.com"),
            )

        with self.both_see_nothing():
            results = run(both())
        assert sorted(results) == [False, True]
        assert len(self.rows()) == 1

    def test_the_row_keeps_the_first_writers_name(self):
        async def both():
            first = await tools.record_publish_audit("CASE-1", dict(DETAIL), "ana@x.com")
            with self.both_see_nothing():
                second = await tools.record_publish_audit("CASE-1", dict(DETAIL), "bao@x.com")
            return first, second

        assert run(both()) == (True, False)
        assert self.rows()[0]["detail"]["reconciled_by"] == "ana@x.com"

    def test_a_different_key_or_a_different_case_is_its_own_row(self):
        async def several():
            await tools.record_publish_audit("CASE-1", dict(DETAIL), "ana@x.com")
            await tools.record_publish_audit("CASE-1", {**DETAIL, "idempotency_key": "KEY-2"}, "ana@x.com")
            await tools.record_publish_audit("CASE-2", dict(DETAIL), "ana@x.com")

        with self.both_see_nothing():
            run(several())
        assert len(self.rows()) == 3

    def test_the_same_key_in_another_tenant_is_not_the_same_row(self):
        async def two_tenants():
            a = await tools.record_publish_audit("CASE-1", dict(DETAIL), "ana@x.com", tenant_id="acme-freight")
            b = await tools.record_publish_audit("CASE-1", dict(DETAIL), "ana@x.com", tenant_id="globex-logistics")
            return a, b

        with self.both_see_nothing():
            assert run(two_tenants()) == (True, True)

    def test_a_save_that_fails_leaves_the_gap_and_a_retry_writes_it_once(self):
        async def attempts():
            with patch.object(self.store, "add_audit_once", side_effect=RuntimeError("store down")):
                try:
                    await tools.record_publish_audit("CASE-1", dict(DETAIL), "ana@x.com")
                except RuntimeError:
                    pass
            return await tools.record_publish_audit("CASE-1", dict(DETAIL), "ana@x.com")

        assert run(attempts()) is True
        assert len(self.rows()) == 1
