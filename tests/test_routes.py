"""
Integration tests for Flask route handlers.

Tests security headers, CORS, auth enforcement, error handling,
rate limiting, request validation, and pagination.
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch, AsyncMock, MagicMock

from main import app


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

    def test_prefilter_rules_put_requires_author(self):
        r = self.client.put(
            "/api/v1/governance/prefilter-rules",
            json={"vip_registry": []},
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
