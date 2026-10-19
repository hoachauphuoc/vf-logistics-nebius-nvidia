"""
The small guards in auth.py: how an actor is described in the audit trail, what the IAP token check does with
a token it cannot trust (nothing), and the two decorators that refuse before the route runs -- a bare
authentication check, and the password-only narrowing for the actions a one-click session must never take.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask, g

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics import auth  # noqa: E402
from vf_logistics.auth import AuthContext  # noqa: E402


class TestHowAnActorGotIn:
    def test_a_session_reports_its_sign_in_method(self):
        ctx = AuthContext("a@x.com", set(), via_session=True, session_method=auth.PASSWORD_SESSION)
        assert ctx.actor_auth == "password"

    def test_a_session_with_no_method_is_unknown_rather_than_trusted(self):
        assert AuthContext("a@x.com", set(), via_session=True).actor_auth == auth.UNKNOWN_SESSION

    def test_a_key_an_iap_identity_and_nothing_are_told_apart(self):
        assert AuthContext("svc", set(), via_api_key=True).actor_auth == "api_key"
        assert AuthContext("a@x.com", set(), iap_subject="sub-1").actor_auth == "iap"
        assert AuthContext("anon", set()).actor_auth == "anonymous"


class TestIapToken:
    def test_a_token_that_verifies_returns_its_claims(self):
        with patch("google.oauth2.id_token.verify_token", return_value={"email": "a@x.com"}) as verify:
            assert auth._verify_iap_jwt("tok") == {"email": "a@x.com"}
        assert verify.call_args.args[0] == "tok"
        assert verify.call_args.kwargs["certs_url"] == "https://www.gstatic.com/iap/verify/public_key"

    def test_a_token_that_does_not_verify_is_nothing_not_an_error(self):
        with patch("google.oauth2.id_token.verify_token", side_effect=ValueError("expired")):
            assert auth._verify_iap_jwt("tok") is None

    def test_a_missing_token_is_nothing(self):
        with patch("google.oauth2.id_token.verify_token", side_effect=ValueError("empty")):
            assert auth._verify_iap_jwt("") is None


@pytest.fixture
def client():
    app = Flask(__name__)

    @app.route("/open")
    @auth.require_auth
    def open_route():
        return "ran"

    @app.route("/sensitive")
    @auth.require_password_session
    def sensitive():
        return "ran"

    return app.test_client()


class TestRequireAuth:
    def test_a_refused_request_never_reaches_the_route(self, client):
        refusal = ({"error": "no"}, 401)
        with patch.object(auth, "authenticate_request", return_value=refusal):
            response = client.get("/open")
        assert response.status_code == 401
        assert b"ran" not in response.data

    def test_an_authenticated_request_runs_the_route(self, client):
        with patch.object(auth, "authenticate_request", return_value=None):
            assert client.get("/open").data == b"ran"

    def test_the_view_records_the_role_it_demands(self):
        assert auth.require_auth(lambda: None)._required_role == "authenticated"


class TestRequirePasswordSession:
    def run(self, client, ctx, authenticate=None):
        def put_context():
            g.auth_context = ctx
            return None

        with patch.object(auth, "authenticate_request", side_effect=authenticate or put_context):
            return client.get("/sensitive")

    def test_a_one_click_session_is_refused_and_told_why(self, client):
        ctx = AuthContext("a@x.com", set(), via_session=True, session_method=auth.ONE_CLICK_SESSION)
        response = self.run(client, ctx)
        body = response.get_json()
        assert response.status_code == 403
        assert body["required_auth"] == "password"
        assert body["session_method"] == "one_click"

    def test_a_session_of_unknown_method_is_refused_too(self, client):
        ctx = AuthContext("a@x.com", set(), via_session=True, session_method=None)
        assert self.run(client, ctx).status_code == 403

    def test_a_password_session_passes(self, client):
        ctx = AuthContext("a@x.com", set(), via_session=True, session_method=auth.PASSWORD_SESSION)
        assert self.run(client, ctx).data == b"ran"

    def test_a_caller_with_the_key_alone_and_no_session_passes(self, client):
        assert self.run(client, AuthContext("svc", set(), via_api_key=True)).data == b"ran"

    def test_an_unauthenticated_request_is_turned_away_by_the_authentication_it_triggers(self, client):
        refusal = ({"error": "no"}, 401)
        response = self.run(client, None, authenticate=lambda: refusal)
        assert response.status_code == 401

    def test_the_view_publishes_that_it_needs_a_password_session(self):
        assert auth.require_password_session(MagicMock())._requires_password_session is True
