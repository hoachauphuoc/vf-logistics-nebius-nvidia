"""
The analysis runtime's call to the executor (executor_client.py), over a fake
network.

What is pinned here is the receipt, because the receipt is what tools.py writes
into the audit trail as the publish's status. The module's own rule: an action
that did not happen must not look like one that did. So every way the hop can
fail -- no executor, no identity token, a refusal, a crash, a transport error, an
executor that ran and could not publish -- must come back as something other than
"done", and an unauthenticated request must never be sent at all.

The HTTP layer is real httpx over a MockTransport, so status codes, JSON parsing
and headers behave as they do on the wire. test_internal_execute.py covers the
executor's side of the same call.

Class names use the `Test*` prefix: see test_console_session.py for why.
"""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest.mock import patch

import httpx

from vf_logistics import executor_client, membership

EXECUTOR = "https://executor.example"
KEY = "executor-test-key-0123456789"

_RealAsyncClient = httpx.AsyncClient


def _run(coro):
    return asyncio.run(coro)


class _ExecutorCase(unittest.TestCase):
    """EXECUTOR_URL set, a token available, and every request recorded."""

    def setUp(self):
        self.requests: list[httpx.Request] = []
        self.reply = httpx.Response(200, json={
            "executed": True, "status": "done", "message_id": "m-1",
            "error": None, "executed_by": "executor identity",
        })
        self.token_audiences: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if isinstance(self.reply, Exception):
                raise self.reply
            return self.reply

        def client(**kwargs):
            return _RealAsyncClient(transport=httpx.MockTransport(handler), **kwargs)

        def token(audience):
            self.token_audiences.append(audience)
            return self.token

        self.token: str | None = "oidc-token"
        for patcher in (
            patch.object(executor_client, "EXECUTOR_URL", EXECUTOR),
            patch.object(executor_client, "_fetch_id_token", token),
            patch.object(executor_client.httpx, "AsyncClient", client),
            patch.dict(os.environ, {"VF_API_KEY": KEY}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def call(self, tenant_id: str | None = "acme", payload: dict | None = None) -> dict:
        return _run(executor_client.request_protected_action(
            "publish_decision", "CASE-1", payload or {"decision": "HOLD"}, tenant_id=tenant_id,
        ))


class TestWhatIsSent(_ExecutorCase):
    def test_the_request_carries_token_key_tenant_and_the_action(self):
        outcome = self.call(payload={"decision": "HOLD", "risk": 0.9})

        self.assertEqual(len(self.requests), 1)
        sent = self.requests[0]
        self.assertEqual(str(sent.url), f"{EXECUTOR}/internal/execute")
        self.assertEqual(sent.method, "POST")
        self.assertEqual(sent.headers["Authorization"], "Bearer oidc-token")
        self.assertEqual(sent.headers["X-VF-API-Key"], KEY)
        self.assertEqual(sent.headers[membership.TENANT_HEADER], "acme")
        self.assertEqual(json.loads(sent.content), {
            "action": "publish_decision", "case_id": "CASE-1",
            "payload": {"decision": "HOLD", "risk": 0.9}, "tenant_id": "acme",
        })
        self.assertEqual(outcome["status"], "done")
        self.assertTrue(outcome["delegated"])
        self.assertEqual(outcome["message_id"], "m-1")

    def test_the_token_is_minted_for_the_executor_audience(self):
        """Cloud Run rejects a token minted for any other audience."""
        self.call()
        self.assertEqual(self.token_audiences, [EXECUTOR])

    def test_the_key_is_read_per_call_so_a_rotation_reaches_the_next_publish(self):
        self.call()
        with patch.dict(os.environ, {"VF_API_KEY": "rotated-key-0123456789"}):
            self.call()
        self.assertEqual(
            [r.headers["X-VF-API-Key"] for r in self.requests],
            [KEY, "rotated-key-0123456789"],
        )

    def test_no_key_and_no_tenant_send_no_header_rather_than_an_empty_one(self):
        with patch.dict(os.environ, {"VF_API_KEY": "  "}):
            self.call(tenant_id=None)
        headers = self.requests[0].headers
        self.assertNotIn("X-VF-API-Key", headers)
        self.assertNotIn(membership.TENANT_HEADER, headers)
        self.assertIsNone(json.loads(self.requests[0].content)["tenant_id"])


class TestNothingIsSentWithoutAnIdentity(_ExecutorCase):
    def test_no_executor_configured_is_skipped_not_attempted(self):
        with patch.object(executor_client, "EXECUTOR_URL", ""):
            self.assertFalse(executor_client.configured())
            outcome = self.call()
        self.assertEqual(outcome["status"], "skipped")
        self.assertFalse(outcome["delegated"])
        self.assertEqual((self.requests, self.token_audiences), ([], []))

    def test_no_token_means_no_request(self):
        """The executor is --no-allow-unauthenticated; an anonymous call is never made."""
        self.token = None
        outcome = self.call()
        self.assertEqual(outcome["status"], "failed")
        self.assertFalse(outcome["delegated"])
        self.assertEqual(self.requests, [])


class TestFailuresAreReportedAsFailures(_ExecutorCase):
    def test_the_executors_own_verdict_wins_over_a_200(self):
        """
        The executor answers 200 when it ran but the publish did not happen
        (no topic, IAM refused). Its body says so, and that is what is reported.
        """
        self.reply = httpx.Response(200, json={
            "executed": False, "status": "failed", "message_id": None,
            "error": "PermissionDenied: pubsub.topics.publish",
        })
        outcome = self.call()
        self.assertEqual(outcome["status"], "failed")
        self.assertFalse(outcome["executed"])
        self.assertIn("PermissionDenied", outcome["error"])

    def test_a_refusal_names_the_two_likely_causes(self):
        for code in (401, 403):
            with self.subTest(code=code):
                self.reply = httpx.Response(code, json={"error": "forbidden"})
                outcome = self.call()
                self.assertEqual(outcome["status"], "failed")
                self.assertEqual(outcome["http_status"], code)
                self.assertIn("run.invoker", outcome["reason"])
                self.assertIn("VF_API_KEY", outcome["reason"])

    def test_an_executor_error_is_a_failure_with_its_reason(self):
        for code, body in (
            (409, {"error": "tenant_id in the body does not match the selected organisation"}),
            (404, {"error": "case not found"}),
            (500, {"error": "Internal server error"}),
        ):
            with self.subTest(code=code):
                self.reply = httpx.Response(code, json=body)
                outcome = self.call()
                self.assertEqual(outcome["status"], "failed")
                self.assertTrue(outcome["delegated"])
                self.assertEqual(outcome["http_status"], code)
                self.assertEqual(outcome["error"], body["error"])

    def test_a_non_json_error_page_is_kept_short(self):
        self.reply = httpx.Response(502, text="<html>" + "x" * 5000 + "</html>")
        outcome = self.call()
        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(outcome["http_status"], 502)
        self.assertEqual(len(outcome["raw"]), 400)

    def test_a_json_body_that_is_not_an_object_is_wrapped_not_merged(self):
        self.reply = httpx.Response(200, json=["unexpected"])
        outcome = self.call()
        self.assertEqual(outcome["body"], ["unexpected"])
        self.assertTrue(outcome["delegated"])

    def test_a_transport_error_is_a_failure_with_its_type(self):
        self.reply = httpx.ConnectError("connection refused")
        outcome = self.call()
        self.assertEqual(outcome["status"], "failed")
        self.assertTrue(outcome["delegated"])
        self.assertIn("ConnectError", outcome["reason"])


class TestTheAuditRecordsTheExecutorsAnswer(_ExecutorCase):
    """tools.publish_decision writes the receipt's status into the audit trail."""

    def setUp(self):
        super().setUp()
        from vf_logistics import store as store_mod

        saved = store_mod._store
        self.addCleanup(setattr, store_mod, "_store", saved)
        store_mod._store = store_mod.MemoryStore()
        self.store = store_mod._store

    def publish(self) -> dict:
        from vf_logistics import tools

        return _run(tools.publish_decision("CASE-1", {"decision": "HOLD"}, tenant_id=None))

    def test_a_publish_the_executor_could_not_make_is_audited_as_failed(self):
        self.reply = httpx.Response(200, json={"executed": False, "status": "failed"})
        entry = self.publish()
        self.assertEqual(entry["status"], "failed")
        self.assertEqual(entry["detail"]["via"], "executor identity")
        audit = _run(self.store.list_audit())
        self.assertEqual([(a["case_id"], a["status"]) for a in audit], [("CASE-1", "failed")])

    def test_an_unreachable_executor_is_audited_as_failed(self):
        self.reply = httpx.ConnectError("connection refused")
        self.assertEqual(self.publish()["status"], "failed")

    def test_a_publish_the_executor_made_is_audited_as_done(self):
        entry = self.publish()
        self.assertEqual(entry["status"], "done")
        self.assertEqual(entry["detail"]["executor"]["message_id"], "m-1")


class TestMintingTheIdentityToken(unittest.TestCase):
    """_fetch_id_token: the metadata server on Cloud Run, google-auth elsewhere, else None."""

    def test_the_metadata_server_is_asked_for_the_audience(self):
        seen: dict = {}

        def get(url, params=None, headers=None, timeout=None):
            seen.update(url=url, params=params, headers=headers)
            return httpx.Response(200, text="  metadata-token\n")

        with patch.object(executor_client.httpx, "get", get), \
                patch("google.oauth2.id_token.fetch_id_token") as fallback:
            token = executor_client._fetch_id_token(EXECUTOR)

        self.assertEqual(token, "metadata-token")
        self.assertEqual(seen["url"], executor_client.METADATA_TOKEN_URL)
        self.assertEqual(seen["params"]["audience"], EXECUTOR)
        # Without this header the metadata server refuses the request.
        self.assertEqual(seen["headers"], {"Metadata-Flavor": "Google"})
        fallback.assert_not_called()

    def test_off_cloud_run_it_falls_back_to_google_auth(self):
        for metadata in (
            httpx.ConnectError("metadata.google.internal: name not known"),
            httpx.Response(404, text="not found"),
            httpx.Response(200, text="   "),
        ):
            with self.subTest(metadata=metadata):
                def get(*args, _answer=metadata, **kwargs):
                    if isinstance(_answer, Exception):
                        raise _answer
                    return _answer

                with patch.object(executor_client.httpx, "get", get), \
                        patch("google.oauth2.id_token.fetch_id_token",
                              return_value="adc-token") as fallback:
                    token = executor_client._fetch_id_token(EXECUTOR)
                self.assertEqual(token, "adc-token")
                self.assertEqual(fallback.call_args.args[1], EXECUTOR)

    def test_no_identity_anywhere_is_none(self):
        def get(*args, **kwargs):
            raise httpx.ConnectError("no metadata server")

        with patch.object(executor_client.httpx, "get", get), \
                patch("google.oauth2.id_token.fetch_id_token",
                      side_effect=RuntimeError("no default credentials")):
            self.assertIsNone(executor_client._fetch_id_token(EXECUTOR))


if __name__ == "__main__":
    unittest.main()
