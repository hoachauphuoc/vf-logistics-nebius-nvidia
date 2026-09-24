"""
Integration tests for Flask route handlers.

Tests security headers, CORS, auth enforcement, error handling,
rate limiting, request validation, and pagination.
"""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from vf_logistics.app import app


class FlaskTestBase(unittest.TestCase):
    """Base class with Flask test client."""

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()


class TestSecurityHeaders(FlaskTestBase):
    def test_root_returns_all_security_headers(self):
        r = self.client.get("/")
        self.assertEqual(r.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(r.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")
        self.assertIn("camera=()", r.headers.get("Permissions-Policy", ""))
        csp = r.headers.get("Content-Security-Policy", "")
        self.assertIn("default-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("frame-src 'self'", csp)

    def test_health_returns_security_headers(self):
        r = self.client.get("/health")
        self.assertIn("X-Frame-Options", r.headers)
        self.assertIn("X-Content-Type-Options", r.headers)

    def test_api_returns_security_headers(self):
        r = self.client.get("/api/v1/config")
        self.assertEqual(r.headers.get("X-Frame-Options"), "DENY")


class TestPrimaryUi(FlaskTestBase):
    """
    Where `/` sends a browser.

    The console and the API are separate Cloud Run services, so making the
    console primary means pointing at it rather than serving it. Both directions
    are asserted: without CONSOLE_URL the behaviour must be exactly what it was,
    because a deployment that has not been given one must not break.
    """

    def test_root_serves_the_bundled_dashboard_without_a_console_url(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CONSOLE_URL", None)
            r = self.client.get("/")
        self.assertEqual(200, r.status_code)
        self.assertIn(b"<html", r.data.lower())

    def test_root_redirects_to_the_console_when_configured(self):
        with patch.dict(os.environ, {"CONSOLE_URL": "https://console.example"}):
            r = self.client.get("/")
        self.assertEqual(302, r.status_code)
        self.assertEqual("https://console.example", r.headers["Location"])

    def test_the_redirect_is_temporary(self):
        """
        301 is cached by browsers indefinitely, so a wrong or retired CONSOLE_URL
        would be unrecoverable for anyone who had already visited.
        """
        with patch.dict(os.environ, {"CONSOLE_URL": "https://console.example"}):
            r = self.client.get("/")
        self.assertNotEqual(301, r.status_code)

    def test_legacy_dashboard_stays_reachable_even_with_a_console_url(self):
        """
        The bundled dashboard is the thing to open when the console itself is the
        suspect, so it must not depend on the console being healthy.
        """
        with patch.dict(os.environ, {"CONSOLE_URL": "https://console.example"}):
            r = self.client.get("/legacy")
        self.assertEqual(200, r.status_code)
        self.assertIn(b"<html", r.data.lower())


class TestCORS(FlaskTestBase):
    def test_cors_allows_configured_origin(self):
        r = self.client.get("/", headers={"Origin": "http://localhost:5000"})
        self.assertEqual(r.headers.get("Access-Control-Allow-Origin"), "http://localhost:5000")

    def test_cors_blocks_unknown_origin(self):
        r = self.client.get("/", headers={"Origin": "https://evil.com"})
        acao = r.headers.get("Access-Control-Allow-Origin")
        self.assertNotEqual(acao, "https://evil.com")


class TestAuthEnforcement(FlaskTestBase):
    """All routes should be accessible in dev mode (IAP_ENABLED=false)."""

    def test_health_no_auth(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)

    def test_config_viewer_accessible(self):
        r = self.client.get("/api/v1/config")
        self.assertEqual(r.status_code, 200)

    def test_governance_agent_viewer_accessible(self):
        r = self.client.get("/api/v1/governance/agent")
        self.assertEqual(r.status_code, 200)

    def test_governance_boundaries_accessible(self):
        r = self.client.get("/api/v1/governance/boundaries")
        self.assertEqual(r.status_code, 200)

    def test_prefilter_rules_accessible(self):
        r = self.client.get("/api/v1/governance/prefilter-rules")
        self.assertEqual(r.status_code, 200)

    def test_metrics_accessible(self):
        r = self.client.get("/metrics")
        self.assertEqual(r.status_code, 200)

    def test_agents_accessible(self):
        r = self.client.get("/agents")
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.data)
        self.assertIn("agents", data)
        self.assertEqual(len(data["agents"]), 4)

    def test_model_config_accessible(self):
        r = self.client.get("/api/v1/config/model")
        self.assertEqual(r.status_code, 200)


class TestErrorHandling(FlaskTestBase):
    def test_404_for_unknown_route(self):
        r = self.client.get("/api/v1/nonexistent")
        self.assertEqual(r.status_code, 404)


class TestRequestValidation(FlaskTestBase):
    def test_governance_publish_requires_author(self):
        r = self.client.post(
            "/api/v1/governance/publish",
            json={"permissions": {}},
            content_type="application/json",
        )
        self.assertIn(r.status_code, [400, 422])

    def test_prefilter_rules_put_ignores_a_body_supplied_author(self):
        """
        The author on a rule change is the authenticated identity, never a body
        field.

        This replaces an earlier test that asserted a missing `author` in the body
        was a 400. That contract was the problem rather than the behaviour worth
        protecting: pre-filter rules decide which shipments skip screening
        entirely, so an audit record naming whoever the caller typed is worth
        exactly as much as their honesty. The assertion now is that a supplied
        author does not reach the record.
        """
        recorded: dict[str, object] = {}

        async def _capture(_self, entry, tenant_id=None):
            if entry.get("action") == "update_prefilter_rules":
                recorded.update(entry["detail"])

        with patch("vf_logistics.store.MemoryStore.add_audit", new=_capture):
            r = self.client.put(
                "/api/v1/governance/prefilter-rules",
                json={"blacklist_companies": ["acme"], "author": "not-me@evil.com"},
                content_type="application/json",
            )

        self.assertEqual(r.status_code, 200)
        self.assertIn("author", recorded)
        self.assertNotEqual(
            recorded["author"],
            "not-me@evil.com",
            "a body-supplied author reached the audit record",
        )

    def test_prefilter_rules_put_rejects_an_invalid_list(self):
        """A bad value is a 400, and the valid keys alongside it are not applied."""
        r = self.client.put(
            "/api/v1/governance/prefilter-rules",
            json={"blacklist_companies": "not-a-list"},
            content_type="application/json",
        )
        self.assertIn(r.status_code, [400, 422])


class TestPagination(FlaskTestBase):
    def test_cases_returns_json(self):
        r = self.client.get("/api/v1/cases?limit=2")
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.data)
        self.assertIn("items", data)

    def test_audit_returns_json(self):
        r = self.client.get("/api/v1/audit?limit=2")
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.data)
        self.assertIn("items", data)

    def test_events_returns_json(self):
        r = self.client.get("/api/v1/events?limit=2")
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.data)
        self.assertIn("items", data)

    def test_metrics_summary_returns_json(self):
        r = self.client.get("/api/v1/metrics/summary")
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.data)
        self.assertIn("counts", data)

    def test_orchestrator_state_returns_json(self):
        r = self.client.get("/api/v1/orchestrator/state?limit=1&drain=0")
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.data)
        self.assertIn("cases", data)


class TestHealthEndpoint(FlaskTestBase):
    def test_health_response_structure(self):
        r = self.client.get("/health")
        data = json.loads(r.data)
        self.assertEqual(data["status"], "healthy")
        self.assertIn("version", data)
        self.assertIn("store", data)
        self.assertIn("worker", data)
        self.assertEqual(data["service"], "VF Logistics Fraud Detection")


if __name__ == "__main__":
    unittest.main()
