"""
Who the audit trail names, and what a forwarded console session may and may not
change.

WHY THIS FILE EXISTS

A compliance product is sold on its audit trail, and this one could not name a
person. Every write from the console was recorded as `service:api-key`, because
the console's server-side proxy attaches one platform-wide API key to every
forwarded request and there was no other identity in the system -- no login, no
user record, no session. "Who released this shipment" had no answer.

The console now signs a session and forwards it. These tests hold the line on the
properties that make that safe: a session says WHO is acting; this service -- not
the token -- decides what that person may do; and a session can only ever narrow
what the console's key grants, never widen it.

THE BOUNDARY THESE TESTS GUARD

Attribution and authorisation used to be the same fact. `is_service_identity`
tested `email == SERVICE_IDENTITY_EMAIL`, so the moment a keyed request began
carrying a person's address, it would have stopped counting as a service identity
-- and `/internal/execute`'s permission to name a tenant would have silently
vanished with it. `via_api_key` separates them. Several tests below exist only to
keep them separate.

WHAT CHANGED, AND WHY SOME OF THESE TESTS WERE REWRITTEN

This file used to pin "a session never changes a role" and "a session that fails
to verify falls back to the key". Together those meant every signed-in person, of
any job, held GOVERNANCE_ADMIN -- the role hierarchy was decorative. The role now
comes from ADMIN_EMAILS / OPERATOR_EMAILS / REVIEWER_EMAILS on this service,
looked up by the verified email. With the session deciding the role, falling back
to the key on a bad session would turn an expired token into admin, so a session
that fails to verify is now refused with 401. Those tests were rewritten to say
so; none was deleted.

CLASS NAMING

`Test*` prefix rather than this suite's usual `*Tests` suffix. The suffix works
elsewhere because those classes subclass `unittest.TestCase`, which pytest
collects by type regardless of name. These do too -- but this project sets
`python_files` and `python_functions` in its pytest config and does NOT set
`python_classes`, so the default `Test*` prefix is what applies to anything
collected by name. A previous file in this suite silently collected zero tests and
reported success. The prefix is load-bearing.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics import auth  # noqa: E402

TEST_KEY = "test-api-key-do-not-ship-0123456789"

# 32 characters is the minimum console_session_secret() will accept; this is
# longer, so a test that shortens it is testing the floor deliberately.
TEST_SECRET = "test-session-secret-do-not-ship-0123456789abcdef"

PERSON = "reviewer@forwarder.example"


def b64url(raw: bytes) -> str:
    """Unpadded base64url, matching what frontend/src/lib/session.ts emits."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def mint(
    email: str = PERSON,
    *,
    secret: str = TEST_SECRET,
    ttl_seconds: int = 3600,
    exp: float | None = None,
    amr: str | None = "password",
) -> str:
    """
    Build a console session token the way the console does.

    Deliberately a reimplementation rather than an import: the TypeScript minter
    and the Python verifier are two codebases that must agree on a wire format, and
    a test that shared code with one of them would not notice the other drifting.

    `amr` defaults to a password sign-in, which is what the console's login form
    mints; pass "one_click" for the judge button, or None to omit the claim the way
    a token minted before it existed does.
    """
    payload: dict[str, object] = {
        "email": email,
        "exp": exp if exp is not None else time.time() + ttl_seconds,
    }
    if amr is not None:
        payload["amr"] = amr
    body = b64url(json.dumps(payload).encode("utf-8"))
    signature = hmac.new(
        secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256
    ).digest()
    return f"{body}.{b64url(signature)}"


def context_for(headers: dict[str, str], **env: str):
    """
    Run authenticate_request() under the given headers and return the context.

    Returns (context, error). `error` is the response tuple authenticate_request
    hands back on refusal, so a test can tell "authenticated as nobody" from
    "refused outright".
    """
    from vf_logistics.app import app

    base_env = {
        "VF_API_KEY": TEST_KEY,
        "VF_SESSION_SECRET": TEST_SECRET,
        "IAP_ENABLED": "false",
        "MULTI_TENANT": "false",
    }
    base_env.update(env)

    with patch.dict(os.environ, base_env):
        with app.test_request_context("/", headers=headers):
            error = auth.authenticate_request()
            return auth.get_auth_context(), error


class TestSessionNamesThePerson(unittest.TestCase):
    """The feature itself: a signed session turns into an attributable email."""

    def test_key_plus_session_is_recorded_as_the_person(self):
        ctx, error = context_for(
            {"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint()}
        )
        self.assertIsNone(error)
        self.assertEqual(ctx.email, PERSON)

    def test_key_alone_is_still_recorded_as_the_service(self):
        """
        The unchanged path. A script, a cron job, or /internal/execute presents a
        key and no session, and naming a person who did not act would be worse
        than naming the machine that did.
        """
        ctx, error = context_for({"X-VF-API-Key": TEST_KEY})
        self.assertIsNone(error)
        self.assertEqual(ctx.email, auth.SERVICE_IDENTITY_EMAIL)

    def test_email_is_normalised(self):
        """A capitalised address must not open a second audit identity."""
        ctx, _ = context_for(
            {
                "X-VF-API-Key": TEST_KEY,
                "X-VF-Session": mint("Reviewer@Forwarder.Example"),
            }
        )
        self.assertEqual(ctx.email, PERSON)

    def test_acts_for_a_person_distinguishes_the_three_cases(self):
        person, _ = context_for(
            {"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint()}
        )
        service, _ = context_for({"X-VF-API-Key": TEST_KEY})
        anonymous, _ = context_for({}, ANONYMOUS_ROLE="viewer")

        self.assertTrue(person.acts_for_a_person)
        self.assertFalse(service.acts_for_a_person)
        self.assertFalse(anonymous.acts_for_a_person)


class TestSessionNeverWidensTheKey(unittest.TestCase):
    """
    A session is identity, not entitlement.

    The role a session ends up with is looked up on this service and capped at
    what the key grants. If any of these fail, a token has been handed the ability
    to decide its own authorisation, and a stolen session becomes a privilege
    escalation rather than a misattributed audit row.
    """

    def test_session_without_a_key_is_anonymous(self):
        """
        The session is not a credential. Presenting one alone must be exactly as
        good as presenting nothing.
        """
        with_session, _ = context_for(
            {"X-VF-Session": mint()}, ANONYMOUS_ROLE="viewer"
        )
        without, _ = context_for({}, ANONYMOUS_ROLE="viewer")

        self.assertEqual(with_session.email, without.email)
        self.assertEqual(with_session.roles, without.roles)
        self.assertEqual(with_session.email, auth.DEV_IDENTITY_EMAIL)

    def test_session_without_a_key_is_refused_when_anonymous_is_off(self):
        """With ANONYMOUS_ROLE=none a session alone must not open the door."""
        ctx, error = context_for({"X-VF-Session": mint()}, ANONYMOUS_ROLE="none")
        self.assertIsNone(ctx)
        self.assertIsNotNone(error)
        self.assertEqual(error[1], 401)

    def test_a_listed_admin_gets_exactly_what_the_key_grants(self):
        """
        Compared as effective permissions, not as raw sets: a listed person also
        holds the viewer role everyone holds, which changes nothing they can do.
        """
        def grants(ctx):
            return {i for held in ctx.roles for i in auth.ROLE_HIERARCHY[held]}

        keyed, _ = context_for({"X-VF-API-Key": TEST_KEY})
        with_session, _ = context_for(
            {"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint()}, ADMIN_EMAILS=PERSON
        )
        self.assertEqual(grants(with_session), grants(keyed))
        self.assertEqual(auth.highest_role(with_session.roles), auth.API_KEY_GRANT)

    def test_an_unlisted_person_is_narrowed_to_viewer(self):
        """
        The change this rewrite exists for. Signing in used to make anyone a
        governance admin; an account nobody granted anything is now a reader.
        """
        ctx, error = context_for({"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint()})
        self.assertIsNone(error)
        self.assertEqual(ctx.roles, {auth.Role.VIEWER})
        self.assertFalse(ctx.has_role(auth.Role.REVIEWER))

    def test_a_session_is_never_wider_than_the_key(self):
        """
        The cap itself, tested directly because today's key grants the top role
        and so cannot show it: a person listed above the ceiling gets the ceiling.
        """
        capped = auth.narrow_roles({auth.Role.GOVERNANCE_ADMIN}, auth.Role.OPERATOR)
        self.assertEqual(capped, {auth.Role.OPERATOR})
        kept = auth.narrow_roles({auth.Role.VIEWER, auth.Role.REVIEWER}, auth.Role.OPERATOR)
        self.assertEqual(kept, {auth.Role.VIEWER, auth.Role.REVIEWER})
        self.assertEqual(auth.narrow_roles(set(), auth.Role.OPERATOR), {auth.Role.VIEWER})

    def test_tenant_is_unchanged_by_a_session(self):
        """
        A session names a person, not a tenant. If it could set the tenant, one
        signed token would be a cross-customer read.
        """
        keyed, _ = context_for({"X-VF-API-Key": TEST_KEY})
        with_session, _ = context_for(
            {"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint()}
        )
        self.assertEqual(with_session.tenant_id, keyed.tenant_id)

    def test_service_identity_survives_attribution(self):
        """
        The boundary this whole design exists to protect.

        /internal/execute lets a service identity name a tenant. That permission
        must not appear or disappear because of who the audit trail happens to be
        naming.
        """
        keyed, _ = context_for({"X-VF-API-Key": TEST_KEY})
        with_session, _ = context_for(
            {"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint()}
        )
        self.assertTrue(keyed.is_service_identity)
        self.assertTrue(with_session.is_service_identity)
        self.assertFalse(with_session.is_development_identity)


class TestForgedSessionsAreRefused(unittest.TestCase):
    """
    Every malformed or untrusted session alongside a valid key is refused with 401.

    It used to fall back to the service identity, on the reasoning that the key
    authorised the request. That was safe only while the session could not affect
    the role. It now does, and the fallback identity is GOVERNANCE_ADMIN -- so a
    fallback would make an expired session strictly MORE powerful than a valid
    one. The console forwards only sessions it has verified, so one that fails
    here is forgery or a secret mismatch, and neither should pass quietly.
    """

    def _is_refused(self, token: str, **env: str) -> None:
        ctx, error = context_for(
            {"X-VF-API-Key": TEST_KEY, "X-VF-Session": token}, **env
        )
        self.assertIsNotNone(error, "a bad session must be refused, not tolerated")
        self.assertEqual(error[1], 401)
        self.assertIsNone(ctx)

    def test_wrong_secret_is_rejected(self):
        self._is_refused(mint(secret="another-secret-entirely-0123456789abcd"))

    def test_expired_session_is_rejected(self):
        self._is_refused(mint(exp=time.time() - 1))

    def test_tampered_email_is_rejected(self):
        """
        The attack this is really guarding: take a valid token, swap the email,
        keep the signature. The HMAC covers the body, so it must not verify.
        """
        token = mint()
        _, _, signature = token.partition(".")
        forged_body = b64url(
            json.dumps({"email": "ceo@forwarder.example", "exp": time.time() + 3600}).encode()
        )
        self._is_refused(f"{forged_body}.{signature}", ADMIN_EMAILS="ceo@forwarder.example")

    def test_unsigned_token_is_rejected(self):
        """A payload with no signature at all, in case a `.` check is missing."""
        body = b64url(json.dumps({"email": PERSON, "exp": time.time() + 3600}).encode())
        self._is_refused(body)
        self._is_refused(f"{body}.")

    def test_garbage_is_rejected_without_raising(self):
        for token in ("not-a-token", "a.b", "...", "%%%.%%%", "a." + "x" * 500):
            with self.subTest(token=token[:20]):
                self._is_refused(token)

    def test_a_blank_header_is_the_same_as_none(self):
        """An empty header names nobody, so the key alone decides, as it always did."""
        for token in ("", "   "):
            with self.subTest(token=repr(token)):
                ctx, error = context_for({"X-VF-API-Key": TEST_KEY, "X-VF-Session": token})
                self.assertIsNone(error)
                self.assertEqual(ctx.email, auth.SERVICE_IDENTITY_EMAIL)
                self.assertEqual(ctx.roles, {auth.API_KEY_GRANT})

    def test_missing_exp_is_rejected(self):
        """An unbounded session is not a session."""
        body = b64url(json.dumps({"email": PERSON}).encode())
        signature = hmac.new(
            TEST_SECRET.encode(), body.encode(), hashlib.sha256
        ).digest()
        self._is_refused(f"{body}.{b64url(signature)}")

    def test_missing_email_is_rejected(self):
        for payload in ({"exp": time.time() + 3600}, {"email": "", "exp": time.time() + 3600}):
            with self.subTest(payload=payload):
                body = b64url(json.dumps(payload).encode())
                signature = hmac.new(
                    TEST_SECRET.encode(), body.encode(), hashlib.sha256
                ).digest()
                self._is_refused(f"{body}.{b64url(signature)}")

    def test_non_object_payload_is_rejected(self):
        """A signed JSON array would crash a .get() on an unguarded path."""
        body = b64url(json.dumps(["reviewer@forwarder.example"]).encode())
        signature = hmac.new(
            TEST_SECRET.encode(), body.encode(), hashlib.sha256
        ).digest()
        self._is_refused(f"{body}.{b64url(signature)}")


class TestSecretConfiguration(unittest.TestCase):
    """What happens when VF_SESSION_SECRET is missing or too weak."""

    def test_no_secret_refuses_a_presented_session(self):
        """
        Fail closed, and say why. With no secret this service cannot tell who the
        session names, so it cannot choose their role -- and choosing the key's
        role instead would make every signed-in person an admin whenever the
        secret goes missing.
        """
        ctx, error = context_for(
            {"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint()},
            VF_SESSION_SECRET="",
        )
        self.assertIsNone(ctx)
        self.assertEqual(error[1], 401)
        self.assertIn("VF_SESSION_SECRET", error[0].get_json()["detail"])

    def test_short_secret_is_treated_as_absent(self):
        """
        A 12-character HMAC key is guessable, and quietly accepting one would mean
        the audit trail's names are only as good as a weak secret.
        """
        weak = "tooshort1234"
        self.assertIsNone(
            self._secret_under(weak), "a secret under 32 chars must not be used"
        )
        ctx, error = context_for(
            {"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint(secret=weak)},
            VF_SESSION_SECRET=weak,
        )
        self.assertIsNone(ctx)
        self.assertEqual(error[1], 401)

    @staticmethod
    def _secret_under(value: str):
        with patch.dict(os.environ, {"VF_SESSION_SECRET": value}):
            return auth.console_session_secret()

    def test_exactly_32_characters_is_accepted(self):
        """The documented floor is inclusive; an off-by-one here is silent."""
        self.assertIsNotNone(self._secret_under("x" * 32))
        self.assertIsNone(self._secret_under("x" * 31))


class TestWireFormatAgreement(unittest.TestCase):
    """
    The Python verifier and the TypeScript minter are separate implementations of
    one wire format. These pin the format itself, so a change on either side that
    breaks the other fails here rather than in production.
    """

    def test_signature_covers_the_encoded_body_not_the_decoded_json(self):
        """
        Signing the body text means neither side has to agree on key order or
        whitespace when re-serialising. Signing decoded JSON would make the two
        implementations agree only by luck.
        """
        token = mint()
        body, _, signature = token.partition(".")

        over_body = hmac.new(
            TEST_SECRET.encode(), body.encode(), hashlib.sha256
        ).digest()
        self.assertEqual(base64.urlsafe_b64decode(signature + "=="), over_body)

    def test_base64url_is_unpadded(self):
        """
        The minter strips `=`. The verifier re-pads. A verifier that required
        padding would reject every real token.
        """
        token = mint()
        self.assertNotIn("=", token)
        ctx, _ = context_for({"X-VF-API-Key": TEST_KEY, "X-VF-Session": token})
        self.assertEqual(ctx.email, PERSON)

    def test_exp_is_seconds_not_milliseconds(self):
        """
        The single most likely cross-language mistake, and it must FAIL CLOSED.

        JavaScript's Date.now() is milliseconds; this format is seconds. A
        millisecond `exp` reads as a date tens of thousands of years out, so
        without an upper bound the bug would not surface as a broken login -- it
        would silently mint sessions that never expire.
        """
        # Valid in seconds: accepted.
        ctx, _ = context_for(
            {"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint(exp=time.time() + 60)}
        )
        self.assertEqual(ctx.email, PERSON)

        # The same instant expressed in milliseconds: refused, not honoured.
        as_milliseconds = time.time() * 1000
        ctx2, error = context_for(
            {"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint(exp=as_milliseconds)}
        )
        self.assertIsNone(ctx2, "a millisecond exp must be rejected, not treated as the year 56000")
        self.assertEqual(error[1], 401)

    def test_expiry_beyond_the_ceiling_is_rejected(self):
        """A session cannot outlive the ceiling even with a valid signature."""
        beyond = time.time() + auth.MAX_SESSION_LIFETIME_SECONDS + 60
        ctx, error = context_for(
            {"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint(exp=beyond)}
        )
        self.assertIsNone(ctx)
        self.assertEqual(error[1], 401)

    def test_console_ttl_is_inside_the_ceiling(self):
        """
        The console mints 12-hour sessions. If the ceiling were ever lowered below
        that, every login would appear to succeed and then be unattributable.
        """
        twelve_hours = 12 * 60 * 60
        self.assertGreater(auth.MAX_SESSION_LIFETIME_SECONDS, twelve_hours)

    def test_whitespace_around_the_header_is_tolerated(self):
        ctx, _ = context_for(
            {"X-VF-API-Key": TEST_KEY, "X-VF-Session": f"  {mint()}  "}
        )
        self.assertEqual(ctx.email, PERSON)


class TestSignInMethod(unittest.TestCase):
    """
    The `amr` claim: how a session was signed in, read only from a signed token.

    It exists for one decision -- whether a session may clear the board -- and the
    property that matters is that it fails closed. Only an explicit, signed
    "password" counts as a password sign-in.
    """

    def _method(self, token: str) -> str | None:
        ctx, error = context_for({"X-VF-API-Key": TEST_KEY, "X-VF-Session": token})
        self.assertIsNone(error)
        return ctx.session_method

    def test_each_known_method_is_read(self):
        self.assertEqual(self._method(mint(amr="password")), auth.PASSWORD_SESSION)
        self.assertEqual(self._method(mint(amr="one_click")), auth.ONE_CLICK_SESSION)

    def test_a_missing_claim_is_unknown_not_password(self):
        """A token minted before the claim existed still names the person, nothing more."""
        ctx, error = context_for({"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint(amr=None)})
        self.assertIsNone(error)
        self.assertEqual(ctx.email, PERSON)
        self.assertEqual(ctx.session_method, auth.UNKNOWN_SESSION)

    def test_an_unrecognised_value_is_unknown(self):
        for value in ("admin", "PASSWORD", "", "password "):
            with self.subTest(value=value):
                self.assertEqual(self._method(mint(amr=value)), auth.UNKNOWN_SESSION)

    def test_the_claim_cannot_be_edited_without_the_secret(self):
        """Rewriting one_click to password in the body breaks the signature."""
        token = mint(amr="one_click")
        body, _, signature = token.partition(".")
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        claims["amr"] = "password"
        forged = f"{b64url(json.dumps(claims).encode())}.{signature}"
        ctx, error = context_for({"X-VF-API-Key": TEST_KEY, "X-VF-Session": forged})
        self.assertIsNone(ctx)
        self.assertEqual(error[1], 401)

    def test_actor_auth_names_the_credential(self):
        session_ctx, _ = context_for({"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint(amr="one_click")})
        key_ctx, _ = context_for({"X-VF-API-Key": TEST_KEY})
        anon_ctx, _ = context_for({}, ANONYMOUS_ROLE="viewer")
        self.assertEqual(session_ctx.actor_auth, "one_click")
        self.assertEqual(key_ctx.actor_auth, "api_key")
        self.assertIsNone(key_ctx.session_method)
        self.assertEqual(anon_ctx.actor_auth, "anonymous")


class TestReviewerAttribution(unittest.TestCase):
    """
    Who `POST /review/<id>/decide` records as the reviewer.

    This route used to read `reviewer` from the request body -- a free-text field the
    console asked the user to type. That is worse than recording nothing: it reads as
    accountability on the audit trail while being unverifiable, and nothing stopped a
    reviewer entering a colleague's name before releasing a shipment.

    The rule now is: a verified identity wins, and the body is consulted only when
    there is no person behind the request.
    """

    def _decide(self, headers: dict, body: dict) -> tuple[str | None, int]:
        """
        Call the route and capture the `reviewer` argument it forwards, and the status.

        Patches human_decide rather than asserting on a stored case, because the
        question here is precisely which value the route chooses -- not what the
        orchestrator then does with it.

        PERSON is listed in REVIEWER_EMAILS: deciding a case needs the reviewer
        role, and an unlisted person is now a viewer.
        """
        from vf_logistics.app import app

        captured: dict[str, object] = {}

        async def fake_human_decide(case_id, action, reviewer, note, tenant_id=None, actor_auth=None):
            captured["reviewer"] = reviewer
            captured["actor_auth"] = actor_auth
            return {"ok": True, "case_id": case_id, "state": "RELEASED_BY_HUMAN"}

        env = {
            "VF_API_KEY": TEST_KEY,
            "VF_SESSION_SECRET": TEST_SECRET,
            "IAP_ENABLED": "false",
            "MULTI_TENANT": "false",
            "REVIEWER_EMAILS": PERSON,
        }
        with patch.dict(os.environ, env):
            with patch(
                "vf_logistics.orchestrator.human_decide", side_effect=fake_human_decide
            ):
                client = app.test_client()
                response = client.post(
                    "/api/v1/review/CASE-1/decide", json=body, headers=headers
                )
        return captured.get("reviewer"), response.status_code  # type: ignore[return-value]

    def test_the_sign_in_method_travels_with_the_name(self):
        """
        A decision taken from the public one-click button must be distinguishable
        on the record from one taken with a password, so the method is handed to
        the orchestrator next to the reviewer.
        """
        from vf_logistics.app import app

        captured: dict[str, object] = {}

        async def fake_human_decide(case_id, action, reviewer, note, tenant_id=None, actor_auth=None):
            captured["actor_auth"] = actor_auth
            return {"ok": True, "case_id": case_id, "state": "RELEASED_BY_HUMAN"}

        env = {
            "VF_API_KEY": TEST_KEY, "VF_SESSION_SECRET": TEST_SECRET,
            "IAP_ENABLED": "false", "MULTI_TENANT": "false", "REVIEWER_EMAILS": PERSON,
        }
        for amr, expected in (("one_click", "one_click"), ("password", "password"), (None, "unknown")):
            with self.subTest(amr=amr):
                captured.clear()
                with patch.dict(os.environ, env), patch(
                    "vf_logistics.orchestrator.human_decide", side_effect=fake_human_decide
                ):
                    response = app.test_client().post(
                        "/api/v1/review/CASE-1/decide",
                        json={"action": "release", "note": "checked"},
                        headers={"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint(amr=amr)},
                    )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(captured["actor_auth"], expected)

    def _reviewer_passed_to_orchestrator(self, headers: dict, body: dict) -> str | None:
        return self._decide(headers, body)[0]

    def test_a_verified_session_supplies_the_reviewer(self):
        who = self._reviewer_passed_to_orchestrator(
            {"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint()},
            {"action": "release", "note": "checked"},
        )
        self.assertEqual(who, PERSON)

    def test_a_body_supplied_name_cannot_override_a_verified_session(self):
        """
        The central assertion of this class. A reviewer with a session must not be
        able to sign the audit trail with somebody else's name.
        """
        who = self._reviewer_passed_to_orchestrator(
            {"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint()},
            {"action": "release", "note": "checked", "reviewer": "someone.else@x.com"},
        )
        self.assertEqual(who, PERSON)

    def test_a_forged_session_is_refused_and_records_nobody(self):
        """
        A forged token used to fall back to the service identity, which let the
        body name the reviewer. It is now refused outright: no decision is made and
        nobody is written to the audit trail under any name.
        """
        who, status = self._decide(
            {
                "X-VF-API-Key": TEST_KEY,
                "X-VF-Session": mint(secret="wrong-secret-0123456789abcdefghij"),
            },
            {"action": "release", "note": "checked", "reviewer": "script@x.com"},
        )
        self.assertEqual(status, 401)
        self.assertIsNone(who)

    def test_an_unlisted_person_cannot_decide(self):
        """Signing in is not the reviewer role. A viewer's decide is a 403."""
        who, status = self._decide(
            {"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint("nobody@forwarder.example")},
            {"action": "release", "note": "checked"},
        )
        self.assertEqual(status, 403)
        self.assertIsNone(who)

    def test_a_keyed_script_may_still_name_a_reviewer(self):
        """
        Preserved on purpose. A caller with no person behind it has no verified
        identity to prefer, and refusing would break every existing integration and
        test that posts a decision with the key alone.
        """
        who = self._reviewer_passed_to_orchestrator(
            {"X-VF-API-Key": TEST_KEY},
            {"action": "release", "note": "checked", "reviewer": "batch-job"},
        )
        self.assertEqual(who, "batch-job")


class TestBothAuditRowsNameThePerson(unittest.TestCase):
    """
    human_decide writes TWO audit records on purpose -- a thin one saying a named
    human chose an action, and a lineage record saying what evidence was in front of
    them. Both must carry the name.

    Found in production: the thin row had no `actor` field at all. The reviewer was
    inside `detail.reviewer`, one level deeper than the column the audit list reads,
    so the row rendered with a blank actor -- on the single row type whose entire
    purpose is to say who decided.
    """

    def setUp(self):
        import vf_logistics.store as store_mod

        from vf_logistics.store import MemoryStore

        self.store_mod = store_mod
        self.store = MemoryStore()
        store_mod._store = self.store

    def tearDown(self):
        self.store_mod._store = None

    def test_the_thin_row_carries_the_actor(self):
        import asyncio

        from vf_logistics import orchestrator

        async def scenario():
            case = await orchestrator.ingest_shipment(
                {
                    "shipment_id": "SHP-AUDIT-1",
                    "origin": "Ho Chi Minh City, Vietnam",
                    "destination": "PSA Singapore, Singapore",
                    "weight_kg": 1200,
                    "declared_value": 40000,
                    "shipping_cost": 1800,
                    "cargo_description": "cotton fabric rolls",
                    "status": "pending",
                },
                source="event",
            )
            # request_info keeps the case where it is, so this exercises the audit
            # write without needing the case to reach a terminal state.
            case["state"] = "PENDING_HUMAN"
            await self.store.put_case(case)

            await orchestrator.human_decide(
                case["case_id"],
                "request_info",
                PERSON,
                "need the packing list",
            )
            return await self.store.list_audit(20)

        rows = asyncio.run(scenario())
        human_rows = [r for r in rows if str(r.get("action", "")).startswith("human_")]
        self.assertTrue(human_rows, "no human_* audit row was written")

        for row in human_rows:
            with self.subTest(action=row.get("action")):
                self.assertEqual(
                    row.get("actor"),
                    PERSON,
                    "every human audit row must name the person at the top level, "
                    "not only inside detail",
                )


if __name__ == "__main__":
    unittest.main()
