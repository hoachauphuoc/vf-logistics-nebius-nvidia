"""
A failure behind a route must come back as a JSON 500 that the client can act on, and in production must not
leak the exception text. Every route below reads or writes through the worker, so one patch of that bridge
stands in for the store, the model or the network being down.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_console_session import TEST_KEY  # noqa: E402
from test_evidence_eval_approve import Base  # noqa: E402

KEY = {"X-VF-API-Key": TEST_KEY}

ROUTES = [
    ("GET", "/api/v1/orchestrator/state", None),
    ("GET", "/api/v1/cases", None),
    ("GET", "/api/v1/audit", None),
    ("GET", "/api/v1/events", None),
    ("GET", "/api/v1/metrics/summary", None),
    ("GET", "/api/v1/worklist", None),
    ("GET", "/api/v1/outcomes", None),
    ("POST", "/api/v1/simulate/bulk", {"count": 1}),
    ("GET", "/api/v1/governance/agent", None),
    ("GET", "/api/v1/governance/drift", None),
    ("GET", "/api/v1/governance/boundaries", None),
    ("POST", "/api/v1/security/screen", {"text": "x"}),
    ("GET", "/api/v1/governance/prefilter-rules", None),
    ("PUT", "/api/v1/governance/prefilter-rules", {"rules": []}),
    ("GET", "/api/v1/review/queue", None),
    ("POST", "/api/v1/orchestrator/reset", {}),
    ("GET", "/api/v1/orchestrator/case/CASE-1", None),
    ("GET", "/api/v1/orchestrator/case/CASE-1/dossier", None),
    ("GET", "/api/v1/orchestrator/case/CASE-1/dossier.json", None),
    ("GET", "/api/v1/compliance/audit/A-1", None),
    ("GET", "/api/v1/billing/usage", None),
]


class CrashBase(Base):
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

    def crash(self, method, url, body):
        with patch.object(self.app_mod, "_on_worker", side_effect=RuntimeError("store down")):
            return self.client.open(url, method=method, json=body, headers=KEY)


@pytest.mark.parametrize("method,url,body", ROUTES)
class TestAFailureBehindTheRoute:
    def test_it_is_a_json_500_that_carries_the_reason_outside_production(self, method, url, body):
        case = CrashBase()
        case.setup_method()
        try:
            with patch.object(case.app_mod, "_IS_PRODUCTION", False):
                response = case.crash(method, url, body)
            assert response.status_code == 500
            assert response.get_json() == {"error": "store down"}
        finally:
            case.teardown_method()

    def test_in_production_the_reason_is_not_leaked(self, method, url, body):
        case = CrashBase()
        case.setup_method()
        try:
            with patch.object(case.app_mod, "_IS_PRODUCTION", True):
                response = case.crash(method, url, body)
            assert response.status_code == 500
            assert response.get_json() == {"error": "Internal server error"}
        finally:
            case.teardown_method()
