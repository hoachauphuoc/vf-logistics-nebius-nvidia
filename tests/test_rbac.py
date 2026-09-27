"""
Role-based access, end to end: who gets which role, and whether the routes honour it.

WHY THIS FILE EXISTS

Until this change the role hierarchy was decorative. Every request through the
console carried the API key, the key granted GOVERNANCE_ADMIN, and a console
session changed only the name on the audit record -- so a signed-in person of any
job, and an anonymous visitor reading through the console, held every role. The
Access Control screen drew a hierarchy nobody was subject to.

Roles now come from ADMIN_EMAILS / OPERATOR_EMAILS / REVIEWER_EMAILS on this
service, looked up by the email a verified console session (or IAP) names, and
capped at what the key grants. These tests pin that, at the level of real routes
where it matters, and walk the route table so the policy the Access Control
screen reports cannot drift from the decorators that enforce it.

Class names use the `Test*` prefix: see test_console_session.py for why that is
load-bearing in this suite.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from flask import Flask, jsonify  # noqa: E402

from vf_logistics import auth  # noqa: E402
from test_console_session import TEST_KEY, TEST_SECRET, mint  # noqa: E402

ADMIN = "admin@forwarder.example"
OPERATOR = "ops@forwarder.example"
REVIEWER = "reviewer@forwarder.example"
STRANGER = "somebody@forwarder.example"

ROLE_ENV = {
    "VF_API_KEY": TEST_KEY,
    "VF_SESSION_SECRET": TEST_SECRET,
    "IAP_ENABLED": "false",
    "MULTI_TENANT": "false",
    "ANONYMOUS_ROLE": "viewer",
    "ADMIN_EMAILS": ADMIN,
    "OPERATOR_EMAILS": OPERATOR,
    "REVIEWER_EMAILS": REVIEWER,
}


def _matrix_app() -> Flask:
    """One route per role, so the matrix tests the decorators and nothing else."""
    app = Flask("rbac-matrix")

    @app.route("/viewer")
    @auth.require_viewer
    def viewer_route():
        return jsonify(ok=True)

    @app.route("/reviewer", methods=["POST"])
    @auth.require_reviewer
    def reviewer_route():
        return jsonify(ok=True)

    @app.route("/operator", methods=["POST"])
    @auth.require_operator
    def operator_route():
        return jsonify(ok=True)

    @app.route("/admin", methods=["POST"])
    @auth.require_governance_admin
    def admin_route():
        return jsonify(ok=True)

    return app


def _session(email: str) -> dict[str, str]:
    return {"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint(email)}


class TestRoleMatrix(unittest.TestCase):
    """Every identity against every role, through the real decorators."""

    ROUTES = (("GET", "/viewer"), ("POST", "/reviewer"), ("POST", "/operator"), ("POST", "/admin"))

    # Expected status per route, in ROUTES order.
    EXPECTED = {
        "anonymous": (200, 403, 403, 403),
        "key only": (200, 200, 200, 200),
        "listed admin": (200, 200, 200, 200),
        "listed operator": (200, 200, 200, 403),
        "listed reviewer": (200, 200, 403, 403),
        "unlisted person": (200, 403, 403, 403),
        "forged session": (401, 401, 401, 401),
    }

    HEADERS = {
        "anonymous": {},
        "key only": {"X-VF-API-Key": TEST_KEY},
        "listed admin": _session(ADMIN),
        "listed operator": _session(OPERATOR),
        "listed reviewer": _session(REVIEWER),
        "unlisted person": _session(STRANGER),
        "forged session": {
            "X-VF-API-Key": TEST_KEY,
            "X-VF-Session": mint(ADMIN, secret="not-the-real-secret-0123456789abcdef"),
        },
    }

    def test_matrix(self):
        client = _matrix_app().test_client()
        with patch.dict(os.environ, ROLE_ENV):
            for identity, expected in self.EXPECTED.items():
                for (method, path), want in zip(self.ROUTES, expected):
                    with self.subTest(identity=identity, route=path):
                        response = client.open(path, method=method, headers=self.HEADERS[identity])
                        self.assertEqual(response.status_code, want)

    def test_a_refusal_names_the_role_it_wanted(self):
        """The console turns this into 'requires the operator role', so it must say which."""
        client = _matrix_app().test_client()
        with patch.dict(os.environ, ROLE_ENV):
            body = client.post("/operator", headers=_session(REVIEWER)).get_json()
        self.assertEqual(body["required_role"], "operator")
        self.assertEqual(body["user_roles"], ["reviewer", "viewer"])


class TestRoleLists(unittest.TestCase):
    """How the three lists are read."""

    def test_entries_are_trimmed_and_case_folded(self):
        """
        A list typed as "Admin@X.com, other@y.com" used to match neither the
        lowercased session email nor anything after the first comma's space.
        """
        env = dict(ROLE_ENV, ADMIN_EMAILS=" Admin@Forwarder.Example , other@y.example ")
        with patch.dict(os.environ, env):
            self.assertIn(auth.Role.GOVERNANCE_ADMIN, auth._get_user_roles(ADMIN))
            self.assertIn(auth.Role.GOVERNANCE_ADMIN, auth._get_user_roles("OTHER@y.example"))

    def test_empty_entries_grant_nothing(self):
        """A trailing comma must not make the empty string a listed person."""
        env = dict(ROLE_ENV, ADMIN_EMAILS=f"{ADMIN},,")
        with patch.dict(os.environ, env):
            self.assertEqual(auth._get_user_roles(""), {auth.Role.VIEWER})

    def test_iap_identities_use_the_same_lists(self):
        """
        IAP was the only path that read these lists, and no test ran it end to end.
        The console session path now reads them too; both must agree.
        """
        from vf_logistics.app import app

        env = dict(ROLE_ENV, IAP_ENABLED="true")
        claims = {"email": "Reviewer@Forwarder.Example", "sub": "iap-subject-1"}
        with patch.dict(os.environ, env), patch.object(auth, "_verify_iap_jwt", return_value=claims):
            with app.test_request_context("/", headers={"X-Goog-IAP-JWT-Assertion": "token"}):
                self.assertIsNone(auth.authenticate_request())
                ctx = auth.get_auth_context()
        self.assertTrue(ctx.has_role(auth.Role.REVIEWER))
        self.assertFalse(ctx.has_role(auth.Role.OPERATOR))


class TestWhoami(unittest.TestCase):
    """GET /api/v1/auth/whoami reports what the decorators will enforce."""

    def _whoami(self, headers: dict[str, str]) -> dict:
        from vf_logistics.app import app

        with patch.dict(os.environ, ROLE_ENV):
            response = app.test_client().get("/api/v1/auth/whoami", headers=headers)
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def test_anonymous(self):
        me = self._whoami({})
        self.assertEqual(me["authenticated_by"], "anonymous")
        self.assertEqual(me["role"], "viewer")
        self.assertEqual(me["role_source"], "ANONYMOUS_ROLE")
        self.assertFalse(me["acts_for_a_person"])

    def test_listed_reviewer(self):
        me = self._whoami(_session(REVIEWER))
        self.assertEqual(me["authenticated_by"], "console_session")
        self.assertEqual(me["email"], REVIEWER)
        self.assertEqual(me["role"], "reviewer")
        self.assertEqual(me["grants"], ["viewer", "reviewer"])
        self.assertEqual(me["role_source"], "REVIEWER_EMAILS")

    def test_unlisted_person_is_told_why(self):
        me = self._whoami(_session(STRANGER))
        self.assertEqual(me["role"], "viewer")
        self.assertIn("not listed", me["role_source"])

    def test_key_only(self):
        me = self._whoami({"X-VF-API-Key": TEST_KEY})
        self.assertEqual(me["authenticated_by"], "api_key")
        self.assertEqual(me["role"], "governance_admin")


class TestRoutePolicy(unittest.TestCase):
    """The policy the Access Control screen shows is the one the routes enforce."""

    # Public on purpose. Each is either liveness, a schema, a static list of
    # capabilities, or a page for a standalone backend.
    PUBLIC = {
        "/", "/legacy", "/health", "/agents",
        "/api/v1/agents", "/api/v1/openapi.json",
    }

    # A POST that only reads: it replays history against a proposed boundary and
    # changes nothing, which is why a viewer may run it.
    READ_ONLY_POSTS = {"/api/v1/governance/simulate"}

    def setUp(self):
        from vf_logistics.app import app

        self.rows = auth.route_policy(app)

    def test_every_route_declares_a_role_or_is_knowingly_public(self):
        """
        If a decorator above require_* stopped using functools.wraps, the role would
        still be enforced but vanish from the policy -- and the screen would call an
        enforced route public. This catches that as well as a missing decorator.
        """
        for row in self.rows:
            with self.subTest(path=row["path"]):
                if row["path"] in self.PUBLIC:
                    self.assertIsNone(row["required_role"])
                else:
                    self.assertIn(row["required_role"], [r.value for r in auth.Role])

    def test_every_write_needs_more_than_viewer(self):
        for row in self.rows:
            writes = set(row["methods"]) & {"POST", "PUT", "PATCH", "DELETE"}
            if not writes or row["path"] in self.READ_ONLY_POSTS:
                continue
            with self.subTest(path=row["path"]):
                self.assertNotIn(row["required_role"], (None, "viewer"))

    def test_policy_reflects_the_decorators(self):
        by_path = {(r["path"], tuple(r["methods"])): r["required_role"] for r in self.rows}
        self.assertEqual(by_path[("/api/v1/review/queue", ("GET",))], "viewer")
        self.assertEqual(by_path[("/api/v1/review/<case_id>/decide", ("POST",))], "reviewer")
        self.assertEqual(by_path[("/api/v1/review/<case_id>/document", ("GET",))], "reviewer")
        self.assertEqual(by_path[("/api/v1/billing/usage", ("GET",))], "operator")
        self.assertEqual(by_path[("/api/v1/governance/publish", ("POST",))], "governance_admin")

    def test_policy_endpoint_reports_list_sizes_not_members(self):
        from vf_logistics.app import app

        with patch.dict(os.environ, ROLE_ENV):
            body = app.test_client().get("/api/v1/auth/policy").get_json()
        self.assertEqual(body["roles"], ["viewer", "reviewer", "operator", "governance_admin"])
        self.assertEqual(body["anonymous_role"], "viewer")
        assignment = {a["variable"]: a for a in body["role_assignment"]}
        self.assertEqual(assignment["ADMIN_EMAILS"]["accounts"], 1)
        self.assertNotIn(ADMIN, str(body), "the policy must not publish who holds a role")


class TestReviewQueueIsReadable(unittest.TestCase):
    """The queue is viewer, the original document and the decision are not."""

    def test_anonymous_can_read_the_queue_but_not_the_document(self):
        from vf_logistics.app import app

        client = app.test_client()
        with patch.dict(os.environ, ROLE_ENV):
            self.assertEqual(client.get("/api/v1/review/queue").status_code, 200)
            self.assertEqual(client.get("/api/v1/review/CASE-1/document").status_code, 403)
            self.assertEqual(client.get("/api/v1/billing/usage").status_code, 403)


if __name__ == "__main__":
    unittest.main()
