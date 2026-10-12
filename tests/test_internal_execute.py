"""
/internal/execute acts only in the organisation it checked the role in.

WHY THIS FILE EXISTS

Re-review finding R02 (on 923d36f): the route checked the operator role in the
organisation the authentication step selected, then took `tenant_id` from the
body for any "service identity" -- which included the API key with a console
session acting for a person. With the service an operator in A and a viewer in
B, and Alice an operator in A only, the review reached the publish function with
B's tenant id in both of these:

  * the service selecting A in the header and naming B in the body
  * the key with Alice's session, selecting A and naming B

The publish function is replaced by a mock in every test here, so nothing is
sent anywhere, and each refusal asserts the mock was not called.

Class names use the `Test*` prefix: see test_console_session.py for why.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics import membership, tenant  # noqa: E402
from vf_logistics import store as store_mod  # noqa: E402
from test_console_session import TEST_KEY, TEST_SECRET, mint  # noqa: E402

ALICE = "alice@acme.com"
A, B = "acme", "beta-shipping"
ROUTE = "/internal/execute"

# The review's configuration.
REVIEW_REGISTRY = {
    "service": {A: "operator", B: "viewer"},
    ALICE: {A: "operator"},
}
# The service entitled to act in B, for the one request that must succeed.
ENTITLED_REGISTRY = {
    "service": {A: "operator", B: "operator"},
    ALICE: {A: "operator"},
}

BASE_ENV = {
    "STORE_BACKEND": "memory",
    "VF_API_KEY": TEST_KEY,
    "VF_SESSION_SECRET": TEST_SECRET,
    "IAP_ENABLED": "false",
    "ANONYMOUS_ROLE": "viewer",
    # Global lists: decide nothing under MULTI_TENANT; make the single-tenant
    # session refusal a refusal of a real admin rather than of a viewer.
    "ADMIN_EMAILS": "admin@forwarder.example",
}

RECEIPT = {"status": "done", "detail": {"message_id": "m-1"}}


class _ExecuteCase(unittest.TestCase):
    multi_tenant = True
    registry = REVIEW_REGISTRY

    def setUp(self):
        from vf_logistics import app as app_mod

        env = {**BASE_ENV, "MULTI_TENANT": "true" if self.multi_tenant else "false"}
        if self.multi_tenant:
            env[membership.MEMBERS_ENV] = json.dumps(self.registry)
        self.env = patch.dict(os.environ, env)
        self.env.start()
        self.addCleanup(self.env.stop)

        store_mod._store = None
        self.addCleanup(setattr, store_mod, "_store", None)
        store = store_mod.get_store()
        if self.multi_tenant:
            asyncio.run(store.put_case({"case_id": "C-A"}, tenant_id=A))
            asyncio.run(store.put_case({"case_id": "C-B"}, tenant_id=B))
        else:
            asyncio.run(store.put_case({"case_id": "C-1"}, tenant_id=tenant.SINGLE_TENANT_ID))

        limiter_was = app_mod.limiter.enabled
        app_mod.limiter.enabled = False
        self.addCleanup(setattr, app_mod.limiter, "enabled", limiter_was)

        self.publish = AsyncMock(return_value=RECEIPT)
        patcher = patch("vf_logistics.tools.publish_decision_direct", self.publish)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = app_mod.app.test_client()

    def execute(self, *, header: str | None, body_tenant: str | None, case_id: str,
                session_for: str | None = None):
        headers = {"X-VF-API-Key": TEST_KEY}
        if header is not None:
            headers[membership.TENANT_HEADER] = header
        if session_for is not None:
            headers["X-VF-Session"] = mint(session_for, amr="password")
        body: dict = {"action": "publish_decision", "case_id": case_id, "payload": {"d": 1}}
        if body_tenant is not None:
            body["tenant_id"] = body_tenant
        return self.client.post(ROUTE, json=body, headers=headers)

    def assertRefused(self, response, status: int):
        self.assertEqual(response.status_code, status, response.get_data(as_text=True))
        self.publish.assert_not_called()


class TestTheReviewsRequestsAreRefused(_ExecuteCase):
    def test_the_service_selecting_b_where_it_is_a_viewer(self):
        self.assertRefused(self.execute(header=B, body_tenant=None, case_id="C-B"), 403)

    def test_the_service_selecting_a_and_naming_b_in_the_body(self):
        self.assertRefused(self.execute(header=A, body_tenant=B, case_id="C-B"), 409)

    def test_alices_session_selecting_a_and_naming_b(self):
        response = self.execute(header=A, body_tenant=B, case_id="C-B", session_for=ALICE)
        self.assertRefused(response, 403)

    def test_alices_session_is_refused_even_in_her_own_organisation(self):
        """Nothing a person does in the console reaches the executor."""
        response = self.execute(header=A, body_tenant=A, case_id="C-A", session_for=ALICE)
        self.assertRefused(response, 403)

    def test_alice_selecting_b_where_she_is_not_a_member(self):
        response = self.execute(header=B, body_tenant=None, case_id="C-B", session_for=ALICE)
        self.assertRefused(response, 403)

    def test_a_case_of_another_organisation_is_not_found(self):
        """Selected A, operator there, but C-B is B's: one answer for foreign and absent."""
        foreign = self.execute(header=A, body_tenant=A, case_id="C-B")
        absent = self.execute(header=A, body_tenant=A, case_id="C-nowhere")
        self.assertRefused(foreign, 404)
        self.assertRefused(absent, 404)
        self.assertEqual(foreign.get_json(), absent.get_json())

    def test_no_case_id_is_not_found(self):
        self.assertRefused(self.execute(header=A, body_tenant=None, case_id=""), 404)


class TestTheEntitledServiceIsServed(_ExecuteCase):
    registry = ENTITLED_REGISTRY

    def test_publishes_in_the_selected_organisation(self):
        response = self.execute(header=B, body_tenant=B, case_id="C-B")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertTrue(response.get_json()["executed"])
        self.publish.assert_called_once()
        self.assertEqual(self.publish.call_args.kwargs["tenant_id"], B)

    def test_the_body_may_leave_the_tenant_out(self):
        response = self.execute(header=A, body_tenant=None, case_id="C-A")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(self.publish.call_args.kwargs["tenant_id"], A)

    def test_header_and_body_disagreeing_is_still_refused(self):
        self.assertRefused(self.execute(header=A, body_tenant=B, case_id="C-B"), 409)

    def test_no_header_with_two_organisations_is_told_to_choose(self):
        response = self.execute(header=None, body_tenant=B, case_id="C-B")
        self.assertRefused(response, 403)
        self.assertEqual(sorted(response.get_json()["choices"]), [A, B])


class TestSingleTenant(_ExecuteCase):
    """The deployed mode: one implicit organisation, the same three checks."""

    multi_tenant = False

    def test_the_key_publishes_its_own_case(self):
        response = self.execute(header=None, body_tenant=tenant.SINGLE_TENANT_ID, case_id="C-1")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(self.publish.call_args.kwargs["tenant_id"], tenant.SINGLE_TENANT_ID)

    def test_the_body_cannot_name_another_tenant(self):
        self.assertRefused(self.execute(header=None, body_tenant="other", case_id="C-1"), 409)

    def test_a_session_is_refused(self):
        response = self.execute(header=None, body_tenant=None, case_id="C-1",
                                session_for="admin@forwarder.example")
        self.assertRefused(response, 403)


class TestTheClientSelectsTheOrganisation(unittest.TestCase):
    """executor_client sends the tenant the way every caller selects one."""

    def test_sends_x_vf_tenant_matching_the_body(self):
        from vf_logistics import executor_client

        sent: dict = {}

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, json=None, headers=None):
                sent.update(url=url, json=json, headers=headers)

                class R:
                    status_code = 200
                    is_success = True
                    text = ""

                    @staticmethod
                    def json():
                        return {"executed": True, "status": "done", "message_id": "m"}

                return R()

        with patch.object(executor_client, "EXECUTOR_URL", "https://executor.example"), \
                patch.object(executor_client, "_fetch_id_token", return_value="tok"), \
                patch.object(executor_client.httpx, "AsyncClient", FakeClient), \
                patch.dict(os.environ, {"VF_API_KEY": TEST_KEY}):
            asyncio.run(executor_client.request_protected_action(
                "publish_decision", "C-B", {"d": 1}, tenant_id=B,
            ))
        self.assertEqual(sent["headers"][membership.TENANT_HEADER], B)
        self.assertEqual(sent["json"]["tenant_id"], B)
        self.assertEqual(sent["headers"]["X-VF-API-Key"], TEST_KEY)


if __name__ == "__main__":
    unittest.main()
