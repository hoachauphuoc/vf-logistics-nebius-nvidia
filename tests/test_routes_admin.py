"""
Three operator routes whose request handling no test reached: the runtime model switch (a cost
control: a model dearer than the limit needs saying so), the bucket sweep, and the rollup backfill.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_console_session import TEST_KEY  # noqa: E402
from test_evidence_eval_approve import Base  # noqa: E402

KEY = {"X-VF-API-Key": TEST_KEY}
NANO = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
SUPER = "nvidia/nemotron-3-super-120b-a12b"
ULTRA = "nvidia/Nemotron-3-Ultra-550b-a55b"


class RouteBase(Base):
    def setup_method(self):
        super().setup_method()
        from vf_logistics import app as app_mod

        self.app_mod = app_mod
        self.limiter_was = app_mod.limiter.enabled
        app_mod.limiter.enabled = False
        self.client = app_mod.app.test_client()

    def teardown_method(self):
        self.app_mod.limiter.enabled = self.limiter_was
        super().teardown_method()


@pytest.fixture(autouse=True)
def keep_the_model():
    from vf_logistics import config

    before = config.get_model()
    yield
    config.set_model(before, allow_costlier=True)


class TestSwitchingTheModel(RouteBase):
    def switch(self, body):
        return self.client.post("/api/v1/config/model", json=body, headers=KEY)

    def test_a_model_is_required(self):
        for body in ({}, {"model": "   "}):
            response = self.switch(body)
            assert response.status_code == 400
            assert response.get_json()["error"] == "model is required"

    def test_an_unknown_model_is_400_and_lists_what_exists(self):
        response = self.switch({"model": "made/up-model"})
        body = response.get_json()
        assert response.status_code == 400
        assert "Invalid model: made/up-model" in body["error"]
        assert NANO in body["available"]

    def test_a_model_within_the_limit_switches_and_reports_its_price(self):
        response = self.switch({"model": SUPER})
        body = response.get_json()
        assert response.status_code == 200
        assert (body["success"], body["model"]) == (True, SUPER)
        assert body["rate_multiple_vs_previous"] == 4.0
        assert body["pricing"]["input"] == 0.30
        from vf_logistics import config

        assert config.get_model() == SUPER

    def test_a_much_dearer_model_is_refused_with_what_to_send(self):
        from vf_logistics import config

        config.set_model(NANO, allow_costlier=True)
        response = self.switch({"model": ULTRA})
        body = response.get_json()
        assert response.status_code == 409
        assert body["model"] == ULTRA
        assert body["current_model"] == NANO
        assert body["rate_multiple"] > body["limit"]
        assert body["confirm_with"] == {"model": ULTRA, "confirm_higher_cost": True}
        assert config.get_model() == NANO

    def test_the_confirmation_lets_it_through(self):
        response = self.switch({"model": ULTRA, "confirm_higher_cost": True})
        assert response.status_code == 200
        from vf_logistics import config

        assert config.get_model() == ULTRA

    def test_the_older_flag_name_still_confirms(self):
        assert self.switch({"model": ULTRA, "allow_costlier": True}).status_code == 200

    def test_a_viewer_cannot_switch(self):
        assert self.client.post("/api/v1/config/model", json={"model": SUPER}).status_code in (401, 403)


class TestBucketSweep(RouteBase):
    def sweep(self, body=None, query=""):
        with patch.object(self.app_mod.orchestrator, "sweep_bucket", new=AsyncMock(return_value={"ingested": 2})) as sweep:
            response = self.client.post(f"/api/v1/ingest/bucket-sweep{query}", json=body or {}, headers=KEY)
        return response, sweep

    def test_the_defaults_are_the_inbox_and_ten_objects(self):
        response, sweep = self.sweep()
        assert (response.status_code, response.get_json()) == (200, {"ingested": 2})
        assert sweep.call_args.args == ("inbox/", 10)

    def test_a_prefix_and_limit_may_come_from_the_body_or_the_query(self):
        assert self.sweep({"prefix": "stage/", "limit": 3})[1].call_args.args == ("stage/", 3)
        assert self.sweep(query="?prefix=other/&limit=4")[1].call_args.args == ("other/", 4)

    def test_the_limit_is_kept_between_one_and_twenty_five(self):
        assert self.sweep({"limit": 500})[1].call_args.args[1] == 25
        assert self.sweep({"limit": -3})[1].call_args.args[1] == 1

    def test_a_limit_that_is_not_a_number_is_the_callers_mistake_not_a_server_error(self):
        response, sweep = self.sweep({"limit": "lots"})
        assert response.status_code == 400
        assert "limit must be a whole number" in response.get_json()["error"]
        sweep.assert_not_called()

    def test_an_anonymous_caller_is_refused(self):
        assert self.client.post("/api/v1/ingest/bucket-sweep", json={}).status_code in (401, 403)


class TestBackfillRollups(RouteBase):
    def test_it_runs_the_backfill_for_the_callers_tenant_and_returns_its_counts(self):
        from vf_logistics import store as store_mod

        with patch.object(store_mod.get_store(), "backfill_rollups", new=AsyncMock(return_value={"updated": 3, "skipped": 5})) as backfill:
            response = self.client.post("/api/v1/admin/backfill-rollups", headers=KEY)
        assert (response.status_code, response.get_json()) == (200, {"updated": 3, "skipped": 5})
        backfill.assert_called_once()

    def test_an_anonymous_caller_is_refused(self):
        assert self.client.post("/api/v1/admin/backfill-rollups").status_code in (401, 403)
