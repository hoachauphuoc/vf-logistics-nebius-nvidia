"""
A board poll that also advances the pipeline must stay a fast, reliable read.

GET /api/v1/orchestrator/state?drain=1 runs one drain step before answering. It
used to wait up to 120 seconds for that step, while the console's proxy abandons a
read after 15 -- so any case whose model calls ran long (a Nebius timeout and one
retry is enough) turned every open board into "the API is unreachable", and past
120 seconds the read itself returned a 500. Found by watching the local board seed
the scripted batch.

The step now has a bounded wait, one step runs per tenant however many boards are
polling, and a failed step is reported on the snapshot instead of failing it.
"""

from __future__ import annotations

import asyncio
import os
import time
import unittest
from unittest.mock import patch

from vf_logistics import app as app_module
from vf_logistics import orchestrator

KEY = "test-api-key-do-not-ship-0123456789"


class TestDrainDuringAPoll(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        self.env = patch.dict(os.environ, {"VF_API_KEY": KEY, "ANONYMOUS_ROLE": "viewer"})
        self.env.start()
        self.wait = patch.object(app_module, "_DRAIN_WAIT_SECONDS", 0.3)
        self.wait.start()
        app_module._drain_in_flight.clear()

    def tearDown(self):
        self.wait.stop()
        self.env.stop()
        app_module._drain_in_flight.clear()

    def _poll(self):
        return self.client.get(
            "/api/v1/orchestrator/state?drain=1", headers={"X-VF-API-Key": KEY},
        )

    def test_a_slow_step_does_not_hold_the_read(self):
        async def slow_drain(max_cases=1, tenant_id=None):
            await asyncio.sleep(2)
            return {"drained": 1, "case_ids": ["CASE-SLOW"]}

        with patch.object(orchestrator, "drain", slow_drain):
            began = time.monotonic()
            response = self._poll()
            elapsed = time.monotonic() - began

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json().get("drain_in_progress"))
        self.assertLess(elapsed, 1.5, "the read waited for the whole drain")

    def test_overlapping_polls_share_one_step(self):
        calls = []

        async def slow_drain(max_cases=1, tenant_id=None):
            calls.append(tenant_id)
            await asyncio.sleep(1)
            return {"drained": 1, "case_ids": []}

        with patch.object(orchestrator, "drain", slow_drain):
            self._poll()
            self._poll()
            self._poll()
        self.assertEqual(len(calls), 1, "each poll started its own drain")

    def test_a_failed_step_is_reported_not_raised(self):
        async def broken_drain(max_cases=1, tenant_id=None):
            raise RuntimeError("model provider down")

        with patch.object(orchestrator, "drain", broken_drain):
            response = self._poll()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json().get("drain_error"), "RuntimeError")
        self.assertIn("cases", response.get_json())


if __name__ == "__main__":
    unittest.main()
