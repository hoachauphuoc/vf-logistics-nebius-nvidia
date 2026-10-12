"""
Organisation membership, resolved on the server (findings T02 and T03).

WHY THIS FILE EXISTS

T02: tenant_from_email() turned the first label of a domain into a tenant, so
acme.com and acme.net were one tenant and yahoo.co.jp became "yahoo". T03: every
console request landed in SINGLE_TENANT_ID whatever email the session named. Both
are replaced by an explicit registry (membership.py). These tests pin the
registry's rules, then the three ways a request authenticates -- console session,
IAP, the API key alone -- against it, with MULTI_TENANT on.

With MULTI_TENANT off nothing here applies; TestSingleTenantIsUnchanged pins that,
because that is the mode the deployed service runs in.

Class names use the `Test*` prefix: see test_console_session.py for why.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics import auth, membership, tenant  # noqa: E402
from test_console_session import TEST_KEY, TEST_SECRET, mint  # noqa: E402

ALICE = "alice@acme.com"
ACME_NET = "ops@acme.net"
AUDITOR = "auditor@firm.example"
BOB = "bob@beta.example"
STRANGER = "person@acme.org"

REGISTRY = {
    ALICE: {"acme": "governance_admin"},
    ACME_NET: {"acme": "operator"},
    AUDITOR: {"acme": "reviewer", "beta-shipping": "viewer"},
    BOB: {"beta-shipping": "operator"},
    "iap:subject-42": {"beta-shipping": "reviewer"},
    "service": {"acme": "operator", "beta-shipping": "operator"},
}

MT_ENV = {
    "MULTI_TENANT": "true",
    "STORE_BACKEND": "memory",
    "VF_API_KEY": TEST_KEY,
    "VF_SESSION_SECRET": TEST_SECRET,
    "IAP_ENABLED": "false",
    "ANONYMOUS_ROLE": "viewer",
    membership.MEMBERS_ENV: json.dumps(REGISTRY),
    # The global lists must NOT decide anything in multi-tenant mode. Listing
    # BOB as a global admin proves it: his role in beta-shipping stays operator.
    "ADMIN_EMAILS": BOB,
}


def _context(headers: dict[str, str], **env: str):
    from vf_logistics.app import app

    with patch.dict(os.environ, {**MT_ENV, **env}):
        with app.test_request_context("/", headers=headers):
            error = auth.authenticate_request()
            return auth.get_auth_context(), error


def _console(email: str, tenant_choice: str | None = None) -> dict[str, str]:
    headers = {"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint(email, amr="password")}
    if tenant_choice is not None:
        headers[membership.TENANT_HEADER] = tenant_choice
    return headers


class TestTheRegistry(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {membership.MEMBERS_ENV: json.dumps(REGISTRY)})
        env.start()
        self.addCleanup(env.stop)

    def test_role_names_match_auth(self):
        self.assertEqual(membership.VALID_ROLES, {r.value for r in auth.Role})

    def test_similar_domains_are_distinct_unless_registered_together(self):
        """T02: acme.com and acme.net are the same tenant only because both are listed."""
        self.assertEqual(membership.resolve(ALICE), ("acme", "governance_admin"))
        self.assertEqual(membership.resolve(ACME_NET), ("acme", "operator"))
        with self.assertRaises(membership.MembershipError):
            membership.resolve(STRANGER)  # acme.org: same first label, not a member

    def test_free_mail_and_unknown_addresses_are_members_of_nothing(self):
        for address in ("person@yahoo.co.jp", "someone@gmail.com", ""):
            with self.subTest(address=address):
                with self.assertRaises(membership.MembershipError) as raised:
                    membership.resolve(address)
                self.assertEqual(raised.exception.status, 403)

    def test_a_person_in_several_organisations_must_choose(self):
        with self.assertRaises(membership.MembershipError) as raised:
            membership.resolve(AUDITOR)
        self.assertEqual(raised.exception.choices, ["acme", "beta-shipping"])
        self.assertEqual(membership.resolve(AUDITOR, "acme"), ("acme", "reviewer"))
        self.assertEqual(membership.resolve(AUDITOR, "beta-shipping"), ("beta-shipping", "viewer"))

    def test_a_choice_can_select_but_never_add(self):
        with self.assertRaises(membership.MembershipError) as raised:
            membership.resolve(BOB, "acme")
        self.assertEqual(raised.exception.status, 403)

    def test_a_foreign_tenant_and_a_missing_one_are_refused_alike(self):
        """So the header cannot be used to discover which tenant ids exist."""
        refusals = []
        for wanted in ("acme", "no-such-tenant"):
            with self.assertRaises(membership.MembershipError) as raised:
                membership.resolve(BOB, wanted)
            refusals.append((raised.exception.status, str(raised.exception)))
        self.assertEqual(refusals[0], refusals[1])

    def test_principals_are_case_and_space_insensitive(self):
        self.assertEqual(membership.resolve("  Alice@ACME.com "), ("acme", "governance_admin"))

    def test_every_refusal_says_why(self):
        """Re-review R03: the console acts on the reason; the status cannot tell them apart."""
        cases = {
            membership.REASON_CHOICE_REQUIRED: (AUDITOR, None),
            membership.REASON_NOT_MEMBER_OF_REQUESTED: (BOB, "acme"),
            membership.REASON_NO_MEMBERSHIP: (STRANGER, None),
            membership.REASON_INVALID_CHOICE: (BOB, "Not/A/Tenant"),
        }
        for reason, (principal, choice) in cases.items():
            with self.subTest(reason=reason):
                with self.assertRaises(membership.MembershipError) as raised:
                    membership.resolve(principal, choice)
                self.assertEqual(raised.exception.reason, reason)

    def test_a_stale_choice_comes_back_with_the_persons_own_choices(self):
        with self.assertRaises(membership.MembershipError) as raised:
            membership.resolve(AUDITOR, "gamma")
        self.assertEqual(raised.exception.choices, ["acme", "beta-shipping"])

    def test_malformed_registries_are_refused(self):
        for label, raw in {
            "not json": "{nope",
            "not an object": "[]",
            "unknown role": json.dumps({ALICE: {"acme": "owner"}}),
            "bad tenant id": json.dumps({ALICE: {"Acme/../x": "viewer"}}),
            "no tenants": json.dumps({ALICE: {}}),
            "duplicate after normalising": '{"a@x.com": {"acme": "viewer"}, "A@X.com": {"acme": "viewer"}}',
        }.items():
            with self.subTest(registry=label):
                with patch.dict(os.environ, {membership.MEMBERS_ENV: raw}):
                    with self.assertRaises(membership.MembershipConfigError):
                        membership.registry()


class TestBootGuard(unittest.TestCase):
    def test_multi_tenant_with_no_registry_refuses_to_boot(self):
        with patch.dict(os.environ, {"MULTI_TENANT": "true", membership.MEMBERS_ENV: ""}):
            with self.assertRaises(tenant.TenantIsolationError):
                membership.assert_registry_is_usable()

    def test_multi_tenant_with_a_malformed_registry_refuses_to_boot(self):
        with patch.dict(os.environ, {"MULTI_TENANT": "true", membership.MEMBERS_ENV: "{nope"}):
            with self.assertRaises(tenant.TenantIsolationError):
                membership.assert_registry_is_usable()

    def test_single_tenant_needs_no_registry(self):
        with patch.dict(os.environ, {"MULTI_TENANT": "false", membership.MEMBERS_ENV: ""}):
            membership.assert_registry_is_usable()


class TestConsoleSessions(unittest.TestCase):
    """T03: the console path, which used to put everyone in `default`."""

    def test_two_companies_get_two_tenants(self):
        alice, error_a = _context(_console(ALICE))
        bob, error_b = _context(_console(BOB))
        self.assertIsNone(error_a)
        self.assertIsNone(error_b)
        self.assertEqual(alice.tenant_id, "acme")
        self.assertEqual(bob.tenant_id, "beta-shipping")

    def test_the_role_is_the_organisation_role_not_the_global_list(self):
        bob, _ = _context(_console(BOB))
        self.assertTrue(bob.has_role(auth.Role.OPERATOR))
        self.assertFalse(bob.has_role(auth.Role.GOVERNANCE_ADMIN), "ADMIN_EMAILS leaked through")

    def test_choosing_selects_among_memberships_with_that_role(self):
        in_acme, _ = _context(_console(AUDITOR, "acme"))
        in_beta, _ = _context(_console(AUDITOR, "beta-shipping"))
        self.assertEqual((in_acme.tenant_id, in_beta.tenant_id), ("acme", "beta-shipping"))
        self.assertTrue(in_acme.has_role(auth.Role.REVIEWER))
        self.assertFalse(in_beta.has_role(auth.Role.REVIEWER))

    def test_choosing_another_companys_tenant_is_refused(self):
        ctx, error = _context(_console(BOB, "acme"))
        self.assertIsNone(ctx)
        self.assertEqual(error[1], 403)

    def test_an_unregistered_person_is_refused_not_defaulted(self):
        ctx, error = _context(_console(STRANGER))
        self.assertIsNone(ctx)
        self.assertEqual(error[1], 403)

    def test_several_memberships_and_no_choice_is_refused_with_the_choices(self):
        ctx, error = _context(_console(AUDITOR))
        self.assertIsNone(ctx)
        self.assertEqual(error[1], 403)
        self.assertEqual(error[0].get_json()["choices"], ["acme", "beta-shipping"])


class TestServiceAndIap(unittest.TestCase):
    def test_the_key_alone_uses_the_service_principal(self):
        ctx, error = _context({"X-VF-API-Key": TEST_KEY, membership.TENANT_HEADER: "acme"})
        self.assertIsNone(error)
        self.assertEqual(ctx.tenant_id, "acme")
        self.assertTrue(ctx.is_service_identity)

    def test_the_key_alone_may_not_reach_an_unlisted_tenant(self):
        ctx, error = _context({"X-VF-API-Key": TEST_KEY, membership.TENANT_HEADER: "gamma"})
        self.assertIsNone(ctx)
        self.assertEqual(error[1], 403)

    def test_iap_is_keyed_by_the_stable_subject_not_the_email_or_a_claim(self):
        """A tenant_id claim and an email domain both used to be read; neither is now."""
        claims = {"email": ALICE, "sub": "subject-42", "tenant_id": "acme"}
        with patch.object(auth, "_verify_iap_jwt", return_value=claims):
            ctx, error = _context({"X-Goog-IAP-JWT-Assertion": "t"}, IAP_ENABLED="true")
        self.assertIsNone(error)
        self.assertEqual(ctx.tenant_id, "beta-shipping")
        self.assertTrue(ctx.has_role(auth.Role.REVIEWER))
        self.assertFalse(ctx.has_role(auth.Role.OPERATOR))

    def test_an_iap_subject_nobody_registered_is_refused(self):
        claims = {"email": ALICE, "sub": "subject-unknown"}
        with patch.object(auth, "_verify_iap_jwt", return_value=claims):
            ctx, error = _context({"X-Goog-IAP-JWT-Assertion": "t"}, IAP_ENABLED="true")
        self.assertIsNone(ctx)
        self.assertEqual(error[1], 403)

    def test_an_anonymous_caller_has_no_tenant_and_is_refused(self):
        ctx, error = _context({})
        self.assertIsNone(ctx)
        self.assertEqual(error[1], 401)


class TestRoutesSeeTheResolvedTenant(unittest.TestCase):
    """End to end: a request in one tenant cannot read another's boundary."""

    def setUp(self):
        from vf_logistics import app as app_mod
        from vf_logistics import store as store_mod

        self.env = patch.dict(os.environ, MT_ENV)
        self.env.start()
        self.addCleanup(self.env.stop)
        store_mod._store = None
        self.addCleanup(setattr, store_mod, "_store", None)
        limiter_was = app_mod.limiter.enabled
        app_mod.limiter.enabled = False
        self.addCleanup(setattr, app_mod.limiter, "enabled", limiter_was)
        self.client = app_mod.app.test_client()

    def test_alice_publishes_in_acme_and_bob_sees_nothing(self):
        published = self.client.post(
            "/api/v1/governance/publish", json={"note": "acme policy"}, headers=_console(ALICE),
        )
        self.assertEqual(published.status_code, 201, published.get_data(as_text=True))
        bob_view = self.client.get("/api/v1/governance/boundaries", headers=_console(BOB)).get_json()
        alice_view = self.client.get("/api/v1/governance/boundaries", headers=_console(ALICE)).get_json()
        self.assertEqual(bob_view["boundaries"], [])
        self.assertEqual(len(alice_view["boundaries"]), 1)

    def test_whoami_lists_the_callers_own_memberships(self):
        me = self.client.get(
            "/api/v1/auth/whoami", headers=_console(AUDITOR, "acme"),
        ).get_json()
        self.assertEqual(me["tenant_id"], "acme")
        self.assertEqual(me["memberships"], {"acme": "reviewer", "beta-shipping": "viewer"})

    def test_first_sign_in_with_two_organisations_is_asked_to_choose(self):
        """Re-review R03: the refusal is what the console builds its chooser from."""
        response = self.client.get("/api/v1/auth/whoami", headers=_console(AUDITOR))
        self.assertEqual(response.status_code, 403)
        body = response.get_json()
        self.assertEqual(body["reason"], membership.REASON_CHOICE_REQUIRED)
        self.assertEqual(body["choices"], ["acme", "beta-shipping"])

    def test_a_choice_left_by_another_person_is_recoverable(self):
        """Bob's browser remembers acme from Alice; Bob is offered his own instead."""
        response = self.client.get("/api/v1/auth/whoami", headers=_console(BOB, "acme"))
        self.assertEqual(response.status_code, 403)
        body = response.get_json()
        self.assertEqual(body["reason"], membership.REASON_NOT_MEMBER_OF_REQUESTED)
        self.assertEqual(body["choices"], ["beta-shipping"])

    def test_internal_execute_cannot_name_a_tenant_other_than_the_selected_one(self):
        """Re-review R02: the body may repeat the selected tenant, never replace it."""
        response = self.client.post(
            "/internal/execute",
            json={"action": "publish_decision", "case_id": "C-1", "tenant_id": "gamma"},
            headers={"X-VF-API-Key": TEST_KEY, membership.TENANT_HEADER: "acme"},
        )
        self.assertEqual(response.status_code, 409, response.get_data(as_text=True))


class TestSingleTenantIsUnchanged(unittest.TestCase):
    """MULTI_TENANT off -- the deployed mode -- behaves exactly as before."""

    def test_console_sessions_still_resolve_to_default_with_the_global_lists(self):
        ctx, error = _context(_console(BOB), MULTI_TENANT="false")
        self.assertIsNone(error)
        self.assertEqual(ctx.tenant_id, tenant.SINGLE_TENANT_ID)
        self.assertTrue(ctx.has_role(auth.Role.GOVERNANCE_ADMIN))

    def test_anonymous_still_reads_as_the_floor(self):
        ctx, error = _context({}, MULTI_TENANT="false")
        self.assertIsNone(error)
        self.assertEqual(ctx.tenant_id, tenant.SINGLE_TENANT_ID)


if __name__ == "__main__":
    unittest.main()
