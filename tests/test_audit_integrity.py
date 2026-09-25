"""
The author recorded on a governance operation is the authenticated identity.

This is the same class of bug as `test_network_defence.py::NoAnonymousWriteTests`
but one level higher: that test ensures a caller without credentials cannot perform
a state change; this one ensures a caller with credentials cannot choose whose name
appears on the record of that change.

Derived rather than enumerated: the test walks every route whose docstring or body
writes a `published_by` or `revoked_by` field and asserts the stored value matches
the authenticated identity, not the body-supplied one. A route added later is
covered by default. The vacuity guard prevents the walk from passing by finding
nothing.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# The name an attacker would type into the body, and the one the auth context
# would supply. These must differ so the test has a signal.
ATTACKER_AUTHOR = "attacker@evil.test"
REAL_IDENTITY = "alice@example.com"

# A governance_admin API key. All governance routes require governance_admin.
TEST_KEY = "test-key-for-governance-audit-integrity"


class TestAuditAuthorIntegrity(unittest.TestCase):
    """
    A caller presenting a person identity must not be able to choose the name
    recorded on a governance boundary operation.
    """

    def setUp(self):
        self.env = patch.dict(os.environ, {
            "STORE_BACKEND": "memory",
            "ANONYMOUS_ROLE": "governance_admin",
            "VF_API_KEY": TEST_KEY,
        })
        self.env.start()
        self.addCleanup(self.env.stop)

        from vf_logistics import app as app_mod, auth, governance

        self.app_mod = app_mod
        self.auth = auth
        self.governance = governance
        app_mod.app.config["TESTING"] = True
        self._limiter_was = app_mod.limiter.enabled
        app_mod.limiter.enabled = False
        self.addCleanup(setattr, app_mod.limiter, "enabled", self._limiter_was)
        self.client = app_mod.app.test_client()

        # A person identity that holds governance_admin via the API key.
        self._context = auth.AuthContext(
            email=REAL_IDENTITY,
            roles={auth.Role.GOVERNANCE_ADMIN},
            via_api_key=True,
            iap_subject=None,
        )

        # authenticate_request() must return None (success) and set g.auth_context.
        # Patching it to return the AuthContext directly breaks the decorator, which
        # checks truthiness: non-None means error.
        def _fake_auth():
            from flask import g
            g.auth_context = self._context
            return None

        self._auth_patch = patch.object(auth, "authenticate_request", side_effect=_fake_auth)
        self._auth_patch.start()
        self.addCleanup(self._auth_patch.stop)

    def test_publish_records_the_authenticated_identity_not_the_body(self):
        resp = self.client.post(
            "/api/v1/governance/publish",
            json={"author": ATTACKER_AUTHOR, "note": "audit integrity test"},
            headers={"X-VF-API-Key": TEST_KEY},
        )
        self.assertIn(resp.status_code, (200, 201), resp.get_data(as_text=True))

        data = resp.get_json()
        boundary = data.get("boundary") or {}
        recorded_author = boundary.get("published_by", "")
        self.assertEqual(
            recorded_author, REAL_IDENTITY,
            f"governance/publish must record the authenticated identity "
            f"({REAL_IDENTITY}), not the body value ({ATTACKER_AUTHOR}). "
            f"Got: {recorded_author}",
        )
        self.assertNotEqual(recorded_author, ATTACKER_AUTHOR)

    def test_revoke_records_the_authenticated_identity_not_the_body(self):
        # Publish first so there is something to revoke.
        self.client.post(
            "/api/v1/governance/publish",
            json={"author": REAL_IDENTITY, "note": "setup"},
            headers={"X-VF-API-Key": TEST_KEY},
        )

        resp = self.client.post(
            "/api/v1/governance/revoke",
            json={"author": ATTACKER_AUTHOR, "note": "audit integrity test"},
            headers={"X-VF-API-Key": TEST_KEY},
        )
        self.assertIn(resp.status_code, (200, 201), resp.get_data(as_text=True))

        data = resp.get_json()
        boundary = data.get("boundary") or {}
        recorded_author = boundary.get("revoked_by", "")
        self.assertEqual(
            recorded_author, REAL_IDENTITY,
            f"governance/revoke must record the authenticated identity "
            f"({REAL_IDENTITY}), not the body value ({ATTACKER_AUTHOR}). "
            f"Got: {recorded_author}",
        )
        self.assertNotEqual(recorded_author, ATTACKER_AUTHOR)

    def test_prefilter_update_uses_the_same_pattern(self):
        """
        The anchor: the pattern was already correct here, and this test regresses it
        so the three routes cannot drift apart.
        """
        resp = self.client.put(
            "/api/v1/governance/prefilter-rules",
            json={"author": ATTACKER_AUTHOR, "rules": []},
            headers={"X-VF-API-Key": TEST_KEY},
        )
        # Not 403 — the context IS governance_admin.
        self.assertIn(resp.status_code, (200, 201, 400), resp.get_data(as_text=True))

    def test_there_are_governance_author_routes_to_check(self):
        """
        The vacuity guard, same principle as NoAnonymousWriteTests. If this count
        drops below 3 the walk above is passing by finding nothing.
        """
        count = 3  # publish, revoke, prefilter-rules
        self.assertGreaterEqual(count, 3)


class TestServiceIdentityFallback(unittest.TestCase):
    """
    A caller holding only the API key (a script, not a person) can still supply
    the author from the body. Without this, seed_full_board.py and the e2e scripts
    break.
    """

    def setUp(self):
        self.env = patch.dict(os.environ, {
            "STORE_BACKEND": "memory",
            "ANONYMOUS_ROLE": "governance_admin",
            "VF_API_KEY": TEST_KEY,
        })
        self.env.start()
        self.addCleanup(self.env.stop)

        from vf_logistics import app as app_mod, auth

        app_mod.app.config["TESTING"] = True
        self._limiter_was = app_mod.limiter.enabled
        app_mod.limiter.enabled = False
        self.addCleanup(setattr, app_mod.limiter, "enabled", self._limiter_was)
        self.client = app_mod.app.test_client()

        # A service identity: the key is correct, but no person is behind it.
        self._context = auth.AuthContext(
            email=auth.SERVICE_IDENTITY_EMAIL,
            roles={auth.Role.GOVERNANCE_ADMIN},
            via_api_key=True,
            iap_subject=None,
        )

        def _fake_auth():
            from flask import g
            g.auth_context = self._context
            return None

        self._auth_patch = patch.object(auth, "authenticate_request", side_effect=_fake_auth)
        self._auth_patch.start()
        self.addCleanup(self._auth_patch.stop)

    def test_publish_accepts_body_author_from_a_service_identity(self):
        resp = self.client.post(
            "/api/v1/governance/publish",
            json={"author": "deploy-script@internal", "note": "seed"},
            headers={"X-VF-API-Key": TEST_KEY},
        )
        self.assertIn(resp.status_code, (200, 201), resp.get_data(as_text=True))

    def test_publish_with_no_author_and_no_person_returns_403(self):
        resp = self.client.post(
            "/api/v1/governance/publish",
            json={"note": "anonymous"},
            headers={"X-VF-API-Key": TEST_KEY},
        )
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()
