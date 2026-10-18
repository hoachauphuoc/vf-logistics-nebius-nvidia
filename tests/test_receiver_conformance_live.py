"""
The receiver Floorline ships, run through the conformance script over real HTTP (N01).

The check a receiving team runs against its own endpoint is run here against ours, so that
"applied once" is shown by the same script on every test run and not only by unit tests. Only the
Google signature check is replaced (a local run has no Google-signed token); the route, the store
and the apply-once transaction are the real ones.
"""

from __future__ import annotations

import os
import sys
import threading
from unittest.mock import patch

from werkzeug.serving import make_server

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import receiver_conformance as rc  # noqa: E402
from test_evidence_eval_approve import Base  # noqa: E402


class TestOurOwnReceiverMeetsTheContract(Base):
    def setup_method(self):
        super().setup_method()
        from vf_logistics import app as app_mod

        self.app_mod = app_mod
        self.limiter_was = app_mod.limiter.enabled
        app_mod.limiter.enabled = False
        self.signed = patch("vf_logistics.decision_receiver.verify_push_token", return_value="push@example.test")
        self.signed.start()
        self.server = make_server("127.0.0.1", 0, app_mod.app, threaded=True)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def teardown_method(self):
        self.server.shutdown()
        self.signed.stop()
        self.app_mod.limiter.enabled = self.limiter_was
        super().teardown_method()

    def _check(self, **kwargs):
        return rc.check(
            self.base + "/api/v1/receiver/decision",
            applied_url=self.base + "/api/v1/receiver/applied/{key}",
            count_field="applied_once", **kwargs,
        )

    def test_every_obligation_passes_over_http(self):
        rows = self._check(concurrency=8)
        assert {result for _, result, _ in rows} == {"PASS"}, rows
        assert rc.exit_code(rows) == 0

    def test_the_decision_is_applied_once_although_it_arrived_many_times(self):
        rows = self._check(concurrency=8)
        key_row = next(detail for name, _, detail in rows if name == "applied once")
        assert "after 10 deliveries" in key_row
        from vf_logistics import store as store_mod

        applied = list(store_mod.get_store()._applied.values())
        assert [a["deliveries"] for a in applied if a["case_id"].startswith("CONF-") and "-NOKEY" not in a["case_id"]] == [10]
