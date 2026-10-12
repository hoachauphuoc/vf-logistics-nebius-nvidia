"""
The shared sign-in attempt counter behind the console's login route.

WHY THIS FILE EXISTS

Finding A04 of the authorization review of bd6a210: the console counted sign-in
attempts in a Map inside each Node process, so the configured limit was a
per-instance limit. The console now asks POST /internal/login-throttle, and the
store keeps one ledger for every instance. These tests pin the ledger's
semantics and who may consult it.

Class names use the `Test*` prefix: see test_console_session.py for why.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics import membership  # noqa: E402
from vf_logistics import store as store_mod  # noqa: E402
from test_console_session import TEST_KEY, TEST_SECRET, mint  # noqa: E402

ENV = {
    "VF_API_KEY": TEST_KEY,
    "VF_SESSION_SECRET": TEST_SECRET,
    "IAP_ENABLED": "false",
    "MULTI_TENANT": "false",
    "ANONYMOUS_ROLE": "viewer",
    "STORE_BACKEND": "memory",
    "ADMIN_EMAILS": "admin@forwarder.example",
}
ROUTE = "/internal/login-throttle"


def _check(key: str = "acct:judge@x.example", limit: int = 5, window: int = 60) -> dict:
    return {"key": key, "limit": limit, "window_seconds": window}


class TestTheLedger(unittest.TestCase):
    def setUp(self):
        self.store = store_mod.MemoryStore()

    def hit(self, key: str = "k", window: int = 60, limit: int = 3) -> bool:
        return asyncio.run(self.store.hit_rate_limit(key, window, limit))

    def test_allows_the_limit_then_refuses(self):
        self.assertEqual([self.hit() for _ in range(5)], [False, False, False, True, True])

    def test_a_refused_attempt_is_not_recorded(self):
        """Otherwise a locked-out user retrying would extend their own lockout forever."""
        clock = [1000.0]
        with patch.object(store_mod.time, "time", side_effect=lambda: clock[0]):
            for _ in range(3):
                self.hit()
            for _ in range(10):
                clock[0] += 1
                self.assertTrue(self.hit())
            clock[0] = 1000.0 + 61
            self.assertFalse(self.hit(), "waiting out the window must be enough")

    def test_keys_are_independent(self):
        for _ in range(3):
            self.hit("acct:a")
        self.assertTrue(self.hit("acct:a"))
        self.assertFalse(self.hit("acct:b"))

    def test_the_stored_id_does_not_carry_the_email(self):
        self.hit("acct:judge@x.example")
        self.assertTrue(self.store._throttle)
        for doc_id in self.store._throttle:
            self.assertNotIn("judge", doc_id)


class TestTheRoute(unittest.TestCase):
    def setUp(self):
        from vf_logistics import app as app_mod

        self.env = patch.dict(os.environ, ENV)
        self.env.start()
        self.addCleanup(self.env.stop)
        store_mod._store = None
        self.addCleanup(setattr, store_mod, "_store", None)
        self.client = app_mod.app.test_client()

    def post(self, body: dict, headers: dict | None = None):
        return self.client.post(ROUTE, json=body, headers=headers or {"X-VF-API-Key": TEST_KEY})

    def test_the_service_identity_counts_and_is_told_when_limited(self):
        answers = [self.post({"checks": [_check(limit=2)]}).get_json()["limited"] for _ in range(3)]
        self.assertEqual(answers, [False, False, True])

    def test_any_check_over_its_limit_limits_the_attempt(self):
        for _ in range(2):
            self.post({"checks": [_check("acct:a", limit=2)]})
        body = self.post({"checks": [_check("acct:a", limit=2), _check("ip:1.2.3.4", limit=20)]}).get_json()
        self.assertTrue(body["limited"])
        self.assertEqual(body["results"], [True, False])

    def test_nobody_but_the_key_alone_may_ask(self):
        """
        A signed-in admin holds operator, so the role alone would let them probe
        or burn someone else's allowance. Without the key there is nothing to ask
        with; with the wrong one, the same.
        """
        cases = {
            "anonymous": ({}, 401),
            "a wrong key": ({"X-VF-API-Key": "not-the-key"}, 401),
            "admin with a password session": (
                {"X-VF-API-Key": TEST_KEY,
                 "X-VF-Session": mint("admin@forwarder.example", amr="password")},
                403,
            ),
            "the key with a session that does not verify": (
                {"X-VF-API-Key": TEST_KEY, "X-VF-Session": "forged"},
                403,
            ),
        }
        for label, (headers, want) in cases.items():
            with self.subTest(caller=label):
                response = self.client.post(ROUTE, json={"checks": [_check()]}, headers=headers)
                self.assertEqual(response.status_code, want, response.get_data(as_text=True))

    def test_no_key_configured_refuses_everyone(self):
        with patch.dict(os.environ, {"VF_API_KEY": ""}):
            response = self.post({"checks": [_check()]}, headers={"X-VF-API-Key": ""})
        self.assertEqual(response.status_code, 401)

    def test_malformed_bodies_are_refused(self):
        for label, body in {
            "no checks": {},
            "empty list": {"checks": []},
            "too many": {"checks": [_check()] * 5},
            "limit as a string": {"checks": [_check(limit="5")]},
            "limit as a bool": {"checks": [_check(limit=True)]},
            "window too long": {"checks": [_check(window=86400)]},
            "empty key": {"checks": [_check(key="")]},
        }.items():
            with self.subTest(body=label):
                self.assertEqual(self.post(body).status_code, 400)

    def test_it_is_exempt_from_the_per_identity_default_limit(self):
        """
        Every console sign-in reaches this as the one service identity. Counted
        against the 200-per-minute default, all sign-ins would share one bucket.
        """
        from vf_logistics import app as app_mod

        was = app_mod.limiter.enabled
        app_mod.limiter.enabled = True
        self.addCleanup(setattr, app_mod.limiter, "enabled", was)
        statuses = {
            self.post({"checks": [_check(f"ip:10.0.{i // 250}.{i % 250}", limit=5)]}).status_code
            for i in range(210)
        }
        self.assertEqual(statuses, {200})


class TestUnderMultiTenancy(unittest.TestCase):
    """
    Re-review finding R04: with MULTI_TENANT on and the service a member of two
    organisations, the console's key-only call was told to choose a tenant (403)
    before the route ran, and the console fell back to per-instance counting.
    """

    REGISTRY = {"service": {"acme": "operator", "beta-shipping": "viewer"}}

    def setUp(self):
        from vf_logistics import app as app_mod

        self.env = patch.dict(os.environ, {
            **ENV,
            "MULTI_TENANT": "true",
            membership.MEMBERS_ENV: json.dumps(self.REGISTRY),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        store_mod._store = None
        self.addCleanup(setattr, store_mod, "_store", None)
        self.app = app_mod.app

    def test_the_key_alone_counts_without_choosing_an_organisation(self):
        response = self.app.test_client().post(
            ROUTE, json={"checks": [_check()]}, headers={"X-VF-API-Key": TEST_KEY},
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertFalse(response.get_json()["limited"])

    def test_a_tenant_header_changes_nothing(self):
        """One ledger whatever organisation a caller names, or a header would buy an allowance."""
        client = self.app.test_client()
        answers = []
        for choice in [None, "acme", "beta-shipping", "gamma"]:
            headers = {"X-VF-API-Key": TEST_KEY}
            if choice:
                headers[membership.TENANT_HEADER] = choice
            response = client.post(ROUTE, json={"checks": [_check(limit=2)]}, headers=headers)
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            answers.append(response.get_json()["limited"])
        self.assertEqual(answers, [False, False, True, True])

    def test_two_console_instances_spend_one_allowance(self):
        """Two clients, one store: what two Cloud Run instances share in Firestore."""
        first, second = self.app.test_client(), self.app.test_client()
        answers = [
            (first if i % 2 == 0 else second).post(
                ROUTE, json={"checks": [_check(limit=5)]}, headers={"X-VF-API-Key": TEST_KEY},
            ).get_json()["limited"]
            for i in range(7)
        ]
        self.assertEqual(answers, [False] * 5 + [True, True])

    def test_a_session_is_still_refused(self):
        response = self.app.test_client().post(
            ROUTE,
            json={"checks": [_check()]},
            headers={"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint("a@acme.com", amr="password")},
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
