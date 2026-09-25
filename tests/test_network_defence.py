"""
The network defence layer: who may write, how much they may spend, and how big a
request may be.

Written because the gap these tests close was not hypothetical. The deployed
service had IAP unset and `allUsers` holding `run.invoker`, so
`authenticate_request()` handed GOVERNANCE_ADMIN to every anonymous caller. An
unauthenticated `POST /api/v1/orchestrator/reset` returned 200 and cleared 307
cases from the production Firestore store. `tenant.assert_isolation_is_enforceable()`
was supposed to refuse that configuration but returns early when `MULTI_TENANT` is
false, so it never evaluated IAP.

Worse, a test asserted the vulnerability. `test_routes.py` was docstring'd "All
routes should be accessible in dev mode" and checked 200 on nine protected routes,
so the suite went green *because* auth was bypassed.

The central test here is therefore `NoAnonymousWriteTests`, and it is deliberately
a walk over `app.url_map` rather than a list of paths. A hand-written list is the
thing that drifts: the tenant work in this project shipped with six real holes
because the audit set was typed out by hand instead of derived. A route added
tomorrow is covered by this file today.
"""

from __future__ import annotations

import io
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics import auth  # noqa: E402

TEST_KEY = "test-api-key-do-not-ship-0123456789"

# Paths a walk cannot meaningfully probe, with the reason each is exempt. Kept
# short and justified: every entry is a hole this file is choosing not to cover,
# so an unexplained addition here is how the gate gets quietly disabled.
SKIP_PREFIXES = (
    "/static/",  # Flask's own static handler, no application logic
)

# POST routes that change nothing and spend nothing, so the anonymous read floor
# is the right level for them despite the HTTP method.
#
# Both were checked rather than assumed. `governance/simulate` makes no external
# call at all -- it reads the board and computes what a boundary change would do,
# which is a read wearing a POST because it takes a body too large for a query
# string. It is the Governance screen's preview, and requiring a credential would
# break a read-only panel for no gain.
#
# `security/screen` is deliberately NOT here: it calls Model Armor, which is
# metered, so it was raised to operator instead.
READ_ONLY_POSTS = frozenset({
    "/api/v1/governance/simulate",
})


def _plausible_args(rule) -> dict[str, str]:
    """
    Fill a rule's URL parameters with values shaped like the real thing.

    The value never needs to exist: an auth decorator runs before the handler
    looks anything up, so a 403 arrives whether or not the id is real. Using a
    case-id shape rather than "x" only keeps any converter on the rule happy.
    """
    return {name: "CASE-PROBE-1" for name in rule.arguments}


class NoAnonymousWriteTests(unittest.TestCase):
    """
    The completeness gate. Every state-changing route must refuse a caller who
    presents no credential.
    """

    def setUp(self):
        # Overrides conftest's autouse fixture, which grants admin so that
        # business-logic tests can post things. These tests are about the floor,
        # so they set it back to the deployed default.
        self.env = patch.dict(os.environ, {
            "STORE_BACKEND": "memory",
            "ANONYMOUS_ROLE": "viewer",
            "VF_API_KEY": TEST_KEY,
        })
        self.env.start()
        self.addCleanup(self.env.stop)

        from vf_logistics import app as app_mod

        self.app_mod = app_mod
        app_mod.app.config["TESTING"] = True
        self._limiter_was = app_mod.limiter.enabled
        app_mod.limiter.enabled = False
        self.addCleanup(setattr, app_mod.limiter, "enabled", self._limiter_was)
        self.client = app_mod.app.test_client()

    def _write_rules(self):
        for rule in self.app_mod.app.url_map.iter_rules():
            methods = (rule.methods or set()) - {"HEAD", "OPTIONS"}
            writes = methods & {"POST", "PUT", "PATCH", "DELETE"}
            if not writes:
                continue
            if any(str(rule.rule).startswith(p) for p in SKIP_PREFIXES):
                continue
            if str(rule.rule) in READ_ONLY_POSTS:
                continue
            for method in sorted(writes):
                yield rule, method

    def test_there_are_write_routes_to_check(self):
        """
        Guards the guard. If the walk found nothing, every assertion below would
        pass vacuously -- which is exactly how a completeness test stops being
        one.
        """
        self.assertGreater(len(list(self._write_rules())), 15)

    def test_no_write_route_answers_an_anonymous_caller(self):
        allowed = []
        for rule, method in self._write_rules():
            path = str(rule.rule)
            for name, value in _plausible_args(rule).items():
                path = path.replace(f"<{name}>", value)
                for conv in ("string:", "int:", "path:"):
                    path = path.replace(f"<{conv}{name}>", value)

            response = self.client.open(path, method=method, json={})
            if response.status_code not in (401, 403):
                allowed.append(f"{method} {path} -> {response.status_code}")

        self.assertEqual(
            allowed, [],
            "These state-changing routes served a caller with no credential:\n  "
            + "\n  ".join(allowed),
        )

    def test_reset_specifically_is_refused(self):
        """
        Named separately from the walk because this is the one that happened. A
        walk failure is a list; this is the regression.
        """
        response = self.client.post("/api/v1/orchestrator/reset")
        self.assertIn(response.status_code, (401, 403))

    def test_reads_still_answer_anonymously(self):
        """
        The other half of the contract, and the reason the floor is viewer rather
        than none: the console's read-only screens are meant to open without a
        login. A change that locked these down would pass every test above.
        """
        for path in (
            "/api/v1/cases", "/api/v1/audit", "/api/v1/metrics/summary",
            "/api/v1/governance/boundaries", "/api/v1/governance/agent",
            "/metrics", "/health",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)


class ApiKeyTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "STORE_BACKEND": "memory",
            "ANONYMOUS_ROLE": "viewer",
            "VF_API_KEY": TEST_KEY,
        })
        self.env.start()
        self.addCleanup(self.env.stop)

        from vf_logistics import app as app_mod

        app_mod.app.config["TESTING"] = True
        self._limiter_was = app_mod.limiter.enabled
        app_mod.limiter.enabled = False
        self.addCleanup(setattr, app_mod.limiter, "enabled", self._limiter_was)
        self.client = app_mod.app.test_client()

    def test_the_right_key_opens_a_write(self):
        response = self.client.post(
            "/api/v1/orchestrator/reset", headers={"X-VF-API-Key": TEST_KEY}
        )
        self.assertEqual(response.status_code, 200)

    def test_a_wrong_key_is_401_not_a_silent_downgrade(self):
        """
        A bad key must not fall through to the anonymous floor.

        Falling through would turn a failed authentication into a successful
        anonymous read, so a rotation mistake would present as "permission
        denied" on writes with nothing pointing at the key. Asserted on a read,
        where the downgrade would otherwise be invisible.
        """
        response = self.client.get(
            "/api/v1/cases", headers={"X-VF-API-Key": "wrong"}
        )
        self.assertEqual(response.status_code, 401)

    def test_an_absent_key_is_not_an_error_on_a_read(self):
        self.assertEqual(self.client.get("/api/v1/cases").status_code, 200)

    def test_the_key_is_compared_in_constant_time(self):
        """
        Asserts the mechanism, not the timing.

        A timing measurement in a unit test is flaky by construction, so this
        checks that hmac.compare_digest is what does the comparing -- which is
        the property that matters and the one a refactor would quietly drop.
        """
        import inspect

        source = inspect.getsource(auth._api_key_context)
        self.assertIn("compare_digest", source)
        self.assertNotIn("supplied == expected", source)

    def test_no_key_configured_means_no_key_accepted(self):
        """A caller cannot authenticate against an unset secret."""
        with patch.dict(os.environ, {"VF_API_KEY": ""}):
            response = self.client.post(
                "/api/v1/orchestrator/reset", headers={"X-VF-API-Key": ""}
            )
            self.assertIn(response.status_code, (401, 403))

    def test_the_service_identity_is_not_the_development_identity(self):
        """
        Both lack an IAP subject, but only one is unearned. Code that refuses to
        run on an unauthenticated identity must not also refuse the console.
        """
        with self.client.application.test_request_context(
            "/", headers={"X-VF-API-Key": TEST_KEY}
        ):
            auth.authenticate_request()
            ctx = auth.get_auth_context()
            self.assertTrue(ctx.is_service_identity)
            self.assertFalse(ctx.is_development_identity)


class BootGuardTests(unittest.TestCase):
    """
    assert_write_access_is_guarded() across the configurations that matter,
    including the one that shipped.
    """

    def _raises(self, **env) -> bool:
        with patch.dict(os.environ, env):
            try:
                auth.assert_write_access_is_guarded()
                return False
            except auth.InsecureAuthConfiguration:
                return True

    def test_it_refuses_what_actually_shipped(self):
        self.assertTrue(self._raises(
            STORE_BACKEND="firestore", ANONYMOUS_ROLE="governance_admin",
            VF_API_KEY="", IAP_ENABLED="false",
        ))

    def test_a_key_is_not_an_excuse(self):
        """
        The non-obvious case. A caller presenting no key never reaches the key
        branch, so a configured key raises the ceiling for the console without
        lowering it for anyone -- "we set a key" is no answer to "anonymous
        callers are admins".
        """
        self.assertTrue(self._raises(
            STORE_BACKEND="firestore", ANONYMOUS_ROLE="governance_admin",
            VF_API_KEY="a-real-key", IAP_ENABLED="false",
        ))

    def test_iap_is_an_excuse(self):
        """With IAP on, authenticate_request never reaches the anonymous branch,
        so ANONYMOUS_ROLE is unreachable rather than merely unwise."""
        self.assertFalse(self._raises(
            STORE_BACKEND="firestore", ANONYMOUS_ROLE="governance_admin",
            VF_API_KEY="", IAP_ENABLED="true",
        ))

    def test_local_development_still_boots(self):
        self.assertFalse(self._raises(
            STORE_BACKEND="memory", ANONYMOUS_ROLE="governance_admin",
            VF_API_KEY="", IAP_ENABLED="false",
        ))

    def test_the_deployed_posture_boots(self):
        self.assertFalse(self._raises(
            STORE_BACKEND="firestore", ANONYMOUS_ROLE="viewer",
            VF_API_KEY="a-real-key", IAP_ENABLED="false",
        ))

    def test_reviewer_counts_as_a_writer(self):
        """
        grants_write_access is derived from ROLE_HIERARCHY, not from a list of
        role names, because every write route requires REVIEWER or above.
        """
        self.assertTrue(self._raises(
            STORE_BACKEND="firestore", ANONYMOUS_ROLE="reviewer",
            VF_API_KEY="", IAP_ENABLED="false",
        ))

    def test_write_access_is_derived_from_the_hierarchy(self):
        self.assertFalse(auth.grants_write_access(None))
        self.assertFalse(auth.grants_write_access(auth.Role.VIEWER))
        for role in (auth.Role.REVIEWER, auth.Role.OPERATOR, auth.Role.GOVERNANCE_ADMIN):
            self.assertTrue(auth.grants_write_access(role), role)

    def test_an_unrecognised_role_falls_to_least_privilege(self):
        """A typo must not become an escalation."""
        with patch.dict(os.environ, {"ANONYMOUS_ROLE": "governanceadmin"}):
            self.assertEqual(auth.anonymous_role(), auth.Role.VIEWER)


class RequestBoundsTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "STORE_BACKEND": "memory",
            "ANONYMOUS_ROLE": "governance_admin",
            "MAX_DOCUMENT_MB": "20",
        })
        self.env.start()
        self.addCleanup(self.env.stop)

        from vf_logistics import app as app_mod

        self.app_mod = app_mod
        app_mod.app.config["TESTING"] = True
        self._limiter_was = app_mod.limiter.enabled
        app_mod.limiter.enabled = False
        self.addCleanup(setattr, app_mod.limiter, "enabled", self._limiter_was)
        self.client = app_mod.app.test_client()

    def test_max_content_length_is_set_above_the_document_cap(self):
        """
        Above, not equal. Multipart framing and field names count toward
        Content-Length, so an exactly-equal ceiling rejects a file that is
        legally just under the documented limit.
        """
        ceiling = self.app_mod.app.config["MAX_CONTENT_LENGTH"]
        self.assertIsNotNone(ceiling)
        self.assertGreater(ceiling, 20 * 1024 * 1024)
        self.assertLess(ceiling, 25 * 1024 * 1024)

    def test_an_oversized_body_is_413_not_500(self):
        """
        The status is the point. Werkzeug raises RequestEntityTooLarge from
        inside request.files, which the route's `except Exception` was turning
        into a 500 -- telling the client "server error, retry" when the truthful
        answer was "too big, do not retry".
        """
        payload = b"x" * (23 * 1024 * 1024)
        response = self.client.post(
            "/api/v1/events/document",
            data={"file": (io.BytesIO(payload), "big.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.headers["content-type"].split(";")[0], "application/json")

    def test_a_batch_over_the_cap_is_refused(self):
        for path, field in (
            ("/api/v1/fraud/batch", "shipments"),
            ("/api/v1/investigation/report", "investigations"),
        ):
            with self.subTest(path=path):
                response = self.client.post(
                    path, json={field: [{} for _ in range(self.app_mod.MAX_BATCH_ITEMS + 1)]}
                )
                self.assertEqual(response.status_code, 413)
                self.assertEqual(
                    response.get_json()["max_items"], self.app_mod.MAX_BATCH_ITEMS
                )

    def test_a_batch_that_is_not_a_list_is_refused(self):
        response = self.client.post(
            "/api/v1/fraud/batch", json={"shipments": {"not": "a list"}}
        )
        self.assertEqual(response.status_code, 400)

    def test_errors_come_back_as_json(self):
        """Werkzeug's defaults are HTML, which an API client misreads as a
        different kind of failure than the one that happened."""
        for response in (
            self.client.get("/api/v1/does-not-exist"),
            self.client.put("/api/v1/cases"),
        ):
            self.assertEqual(
                response.headers["content-type"].split(";")[0], "application/json"
            )


class RateLimitTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "STORE_BACKEND": "memory",
            "ANONYMOUS_ROLE": "governance_admin",
        })
        self.env.start()
        self.addCleanup(self.env.stop)

        from vf_logistics import app as app_mod

        self.app_mod = app_mod
        app_mod.app.config["TESTING"] = True
        # Left ENABLED here on purpose -- this is the only class that wants it.
        app_mod.limiter.enabled = True
        self.addCleanup(setattr, app_mod.limiter, "enabled", True)
        app_mod.limiter.reset()
        self.addCleanup(app_mod.limiter.reset)
        self.client = app_mod.app.test_client()

    def test_a_limit_actually_fires(self):
        """
        No test asserted a 429 before this one, so the limiter was configuration
        nobody had confirmed was wired up.

        /orchestrator/reset is the probe rather than a model-calling route: it is
        capped at 5/min and touches only the memory store, so exhausting it costs
        nothing. Using /demo here made the test spend real Nebius tokens.
        """
        statuses = [
            self.client.post("/api/v1/orchestrator/reset").status_code
            for _ in range(8)
        ]
        self.assertIn(429, statuses, f"limiter never fired: {statuses}")

    def test_a_429_is_json(self):
        for _ in range(8):
            response = self.client.post("/api/v1/orchestrator/reset")
            if response.status_code == 429:
                self.assertEqual(
                    response.headers["content-type"].split(";")[0], "application/json"
                )
                self.assertIn("Rate limit", response.get_json()["error"])
                return
        self.fail("limiter never fired")

    def test_every_model_calling_route_has_an_explicit_limit(self):
        """
        Derived, like the write-route walk. The default 200/min is not a limit on
        a route that spends money -- it is a budget authorisation -- so each of
        these must carry its own, and a new expensive route must not inherit the
        default by omission.

        Read from the source rather than from the limiter's registry, because that
        registry is a private attribute whose name changed between flask-limiter
        3 and 4. The decorator in the file is the thing being asserted anyway.
        """
        import pathlib
        import re

        expensive = {
            "/api/v1/fraud/analyze", "/api/v1/fraud/batch",
            "/api/v1/compliance/screen", "/api/v1/compliance/entity",
            "/api/v1/investigation/case", "/api/v1/investigation/report",
            "/api/v1/events/document", "/api/v1/events/shipment",
            "/api/v1/simulate", "/api/v1/simulate/bulk",
            "/api/v1/governance/tavily-scan", "/api/v1/governance/verify-entity",
            "/api/v1/security/screen", "/api/v1/ingest/bucket-sweep",
            "/api/v1/review/<case_id>/deep-review", "/demo",
        }

        source = pathlib.Path(self.app_mod.__file__).read_text(encoding="utf-8")
        lines = source.split("\n")

        limited: set[str] = set()
        for i, line in enumerate(lines):
            match = re.match(r'@app\.route\("([^"]+)"', line.strip())
            if not match:
                continue
            # Walk the decorator block down to the function definition.
            for probe in lines[i + 1:i + 12]:
                stripped = probe.strip()
                if stripped.startswith("def ") or stripped.startswith("async def "):
                    break
                if "limiter.limit" in stripped:
                    limited.add(match.group(1))
                    break

        missing = sorted(p for p in expensive if p not in limited)
        self.assertEqual(
            missing, [],
            "These routes call a model or a metered API with no explicit rate "
            "limit, so they inherit the 200/min default:\n  " + "\n  ".join(missing),
        )


class DrainPrivilegeTests(unittest.TestCase):
    """
    GET /orchestrator/state advances the pipeline as a side effect, which is the
    same work the operator-only POST /orchestrator/drain does. Letting a viewer
    trigger it made the weaker requirement the effective one.
    """

    def setUp(self):
        self.env = patch.dict(os.environ, {
            "STORE_BACKEND": "memory",
            "ANONYMOUS_ROLE": "viewer",
            "VF_API_KEY": TEST_KEY,
        })
        self.env.start()
        self.addCleanup(self.env.stop)

        from vf_logistics import app as app_mod

        app_mod.app.config["TESTING"] = True
        self._limiter_was = app_mod.limiter.enabled
        app_mod.limiter.enabled = False
        self.addCleanup(setattr, app_mod.limiter, "enabled", self._limiter_was)
        self.client = app_mod.app.test_client()

    def test_an_anonymous_read_does_not_drain(self):
        body = self.client.get("/api/v1/orchestrator/state?drain=1").get_json()
        self.assertNotIn("drained_this_request", body)
        # Reported rather than silently ignored: a board that stops advancing with
        # no explanation is an hour of debugging.
        self.assertIn("drain_skipped", body)

    def test_an_anonymous_read_still_returns_the_projection(self):
        response = self.client.get("/api/v1/orchestrator/state?drain=0")
        self.assertEqual(response.status_code, 200)
        self.assertIn("cases", response.get_json())

    def test_a_keyed_read_may_drain(self):
        body = self.client.get(
            "/api/v1/orchestrator/state?drain=1", headers={"X-VF-API-Key": TEST_KEY}
        ).get_json()
        self.assertNotIn("drain_skipped", body)


class SecurityHeaderTests(unittest.TestCase):
    def setUp(self):
        from vf_logistics import app as app_mod

        app_mod.app.config["TESTING"] = True
        self._limiter_was = app_mod.limiter.enabled
        app_mod.limiter.enabled = False
        self.addCleanup(setattr, app_mod.limiter, "enabled", self._limiter_was)
        self.client = app_mod.app.test_client()

    def test_hsts_is_present(self):
        headers = self.client.get("/health").headers
        self.assertIn("Strict-Transport-Security", headers)
        self.assertIn("max-age=", headers["Strict-Transport-Security"])

    def test_hsts_does_not_claim_preload(self):
        """Preload is effectively irreversible and is not a decision to make in
        passing."""
        self.assertNotIn(
            "preload", self.client.get("/health").headers["Strict-Transport-Security"]
        )

    def test_csp_contains_base_uri_and_form_action(self):
        """
        Neither inherits from default-src, so omitting them is a gap even when
        default-src is restrictive. base-uri 'none' prevents injected <base> tags;
        form-action 'self' constrains where forms submit.
        """
        csp = self.client.get("/health").headers.get("Content-Security-Policy", "")
        self.assertIn("base-uri", csp)
        self.assertIn("form-action", csp)

    def test_csp_does_not_allow_star_in_script_src(self):
        csp = self.client.get("/health").headers.get("Content-Security-Policy", "")
        self.assertNotIn("script-src *", csp)
        self.assertNotIn("script-src '*'", csp)

    def test_document_content_type_is_pinned_to_the_upload_allow_list(self):
        """
        review/<id>/document reflects content_type from the GCS blob. An object
        placed directly into the bucket keeps whatever content-type it was
        uploaded with; reflecting text/html same-origin would be an XSS path.
        """
        from unittest.mock import AsyncMock, patch as mp

        from vf_logistics import document_store

        fake_case = {
            "provenance": {
                "uri": "gs://bucket/doc.pdf",
                "filename": "doc.pdf",
            },
        }
        with mp.object(document_store, "fetch", new_callable=AsyncMock) as fetch:
            fetch.return_value = (b"fake", "text/html")
            resp = self.client.get(
                "/api/v1/review/CASE-TEST-1/document",
            )
        if resp.status_code == 200:
            ct = resp.content_type or ""
            self.assertNotIn(
                "text/html", ct,
                "text/html from upstream must NOT be reflected same-origin",
            )


if __name__ == "__main__":
    unittest.main()
