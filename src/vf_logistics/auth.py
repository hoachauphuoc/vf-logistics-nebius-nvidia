"""
Authentication and authorization middleware for VF Logistics.

Implements Google IAP (Identity-Aware Proxy) JWT verification for Cloud Run,
with RBAC (Role-Based Access Control) for fine-grained permissions.

IAP Flow:
1. User authenticates via Google IAP (configured in GCP Console)
2. IAP adds X-Goog-IAP-JWT-Assertion header with signed JWT
3. This middleware verifies the JWT signature using Google's public keys
4. User email and roles are extracted and attached to the request context

Roles:
- viewer: Read-only access to dashboard and case details
- reviewer: Can approve/reject cases in review queue
- operator: Can run simulations, reset board, trigger processing
- governance_admin: Can modify delegation boundaries and permissions
"""

from __future__ import annotations

import base64
import binascii
import functools
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from flask import g, jsonify, request

from vf_logistics import tenant

# IAP audience is the Cloud Run service URL
IAP_AUDIENCE = os.getenv("IAP_AUDIENCE", "")

# The header a machine caller presents its shared secret in. Deliberately not
# Authorization: that header is reserved here for a future IAP or OIDC bearer
# token, and two credential kinds sharing one header is how a fallback path gets
# taken by accident.
API_KEY_HEADER = "X-VF-API-Key"

# The identity handed out when no credential is presented. Named rather than
# inlined so a caller can recognise an unearned identity -- see
# AuthContext.is_development_identity -- instead of matching a magic string.
DEV_IDENTITY_EMAIL = "dev@localhost"

# The identity a valid API key presents as. Deliberately not an email address:
# it is a machine, and an audit record naming a person who did not act is worse
# than one naming the service that did.
#
# Still correct, and still used -- for a script, a cron job, or /internal/execute.
# What changed is that it is no longer the ONLY thing a keyed request can present
# as: when the console also forwards a signed console session, the acting person's
# address is recorded instead. See _console_session_email().
SERVICE_IDENTITY_EMAIL = "service:api-key"

# The header the console forwards its signed session token in.
#
# Not a bare email header, because a bare email is an assertion and this must be
# evidence. The token is the same one the browser holds in an HttpOnly cookie,
# signed by the console with VF_SESSION_SECRET, and verified here against the same
# secret -- so stealing the API key is not by itself enough to write a false name
# into the audit trail.
CONSOLE_SESSION_HEADER = "X-VF-Session"

# The furthest ahead a console session's `exp` may be before it is rejected as
# nonsense. The console mints 12-hour sessions; 48 hours leaves room to lengthen
# that without touching this, while still being thousands of years short of what a
# millisecond-versus-second unit error would produce.
MAX_SESSION_LIFETIME_SECONDS = 48 * 60 * 60


def console_session_secret() -> str | None:
    """
    The HMAC secret shared with the console.

    None when unset or too short to be worth trusting, and every caller treats
    None as "cannot verify", never as "accept without verifying". A service with no
    secret configured simply keeps attributing console writes to the API key, which
    is the behaviour that existed before this feature -- degraded, not unsafe.
    """
    value = os.getenv("VF_SESSION_SECRET", "")
    return value if len(value) >= 32 else None


def _b64url_decode(text: str) -> bytes:
    """Decode unpadded base64url. Raises on anything malformed."""
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _console_session_email() -> str | None:
    """
    The verified email from a forwarded console session, or None.

    None covers every failure indistinguishably: header absent, no secret
    configured, malformed token, bad signature, expired, no email. A caller cannot
    tell a forged session from an expired one and does not need to -- in both cases
    the request falls back to being attributed to the API key rather than being
    refused, because the key is what authorised it.

    MUST MATCH frontend/src/lib/session.ts, which mints these:

        token   = b64url(json_payload) + "." + b64url(hmac_sha256(secret, body))
        payload = {"email": str, "exp": int}   # exp is epoch SECONDS

    The HMAC covers the base64url body text, not the decoded JSON, so neither side
    has to agree on key order or whitespace when re-serialising.
    """
    secret = console_session_secret()
    if not secret:
        return None

    raw = request.headers.get(CONSOLE_SESSION_HEADER)
    if not raw:
        return None

    token = raw.strip()
    body, _, signature = token.partition(".")
    if not body or not signature:
        return None

    try:
        expected = hmac.new(
            secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256
        ).digest()
        # compare_digest for the same reason the API key uses it: a plain ==
        # returns early and leaks how much of the signature matched.
        if not hmac.compare_digest(_b64url_decode(signature), expected):
            return None

        claims = json.loads(_b64url_decode(body))
    except (ValueError, binascii.Error, TypeError):
        return None

    if not isinstance(claims, dict):
        return None

    # Read only AFTER the signature check. An expiry taken from an unverified
    # payload is an attacker-chosen expiry, and the same goes for the email.
    expires = claims.get("exp")
    if not isinstance(expires, (int, float)):
        return None

    now = time.time()
    if expires <= now:
        return None

    # An upper bound as well as a lower one, because the likeliest cross-language
    # mistake in this format is a unit error: JavaScript's Date.now() is in
    # MILLISECONDS and this field is in SECONDS. A millisecond expiry reads as a
    # date tens of thousands of years out, so without this check the bug would not
    # fail -- it would produce sessions that never expire, which is the worst
    # possible way for it to go wrong. The console's own TTL is 12 hours.
    if expires > now + MAX_SESSION_LIFETIME_SECONDS:
        return None

    email = claims.get("email")
    if not isinstance(email, str) or not email.strip():
        return None
    return email.strip().lower()


class Role(str, Enum):
    """User roles for RBAC."""
    VIEWER = "viewer"
    REVIEWER = "reviewer"
    OPERATOR = "operator"
    GOVERNANCE_ADMIN = "governance_admin"


# Role hierarchy: higher roles include lower role permissions
ROLE_HIERARCHY = {
    Role.VIEWER: {Role.VIEWER},
    Role.REVIEWER: {Role.VIEWER, Role.REVIEWER},
    Role.OPERATOR: {Role.VIEWER, Role.REVIEWER, Role.OPERATOR},
    Role.GOVERNANCE_ADMIN: {Role.VIEWER, Role.REVIEWER, Role.OPERATOR, Role.GOVERNANCE_ADMIN},
}


def iap_enabled() -> bool:
    """
    Whether IAP JWT verification is in force.

    Read per call rather than captured at import. The previous module-level
    constant could not be changed by a test, which is why no test ever covered
    the authenticated path -- patching os.environ after import had no effect, so
    the suite only ever exercised the bypass.
    """
    return os.getenv("IAP_ENABLED", "false").strip().lower() == "true"


def api_key() -> str:
    """
    The shared secret a machine caller must present, or "" when none is set.

    Read per call so a rotated key takes effect on the next request rather than
    on the next deploy -- the whole reason for putting it in Secret Manager.
    """
    return os.getenv("VF_API_KEY", "").strip()


def anonymous_role() -> Role | None:
    """
    The role granted to a caller presenting no credential at all.

    Defaults to VIEWER, which is what makes "reads are public, writes need a
    key" work without anyone having to enumerate the write routes: every read
    route is require_viewer and every write route requires reviewer or above, so
    the existing hierarchy already draws the line. A hand-maintained list of
    write paths would drift the first time a route was added.

    `none` refuses anonymous callers outright. It is the stronger posture and is
    deliberately not the default, because the console's read-only screens are
    meant to be openable without a login.
    """
    raw = os.getenv("ANONYMOUS_ROLE", "viewer").strip().lower()
    if raw in ("none", "off", ""):
        return None
    try:
        return Role(raw)
    except ValueError:
        # An unrecognised value is a configuration error, and guessing which
        # role was meant is how a typo becomes an escalation. Fall back to the
        # least privilege the setting can express.
        return Role.VIEWER


@dataclass
class AuthContext:
    """Authenticated user context attached to request."""
    email: str
    roles: set[Role]
    iap_subject: str | None = None
    tenant_id: str | None = None
    # HOW this context was authorised, as distinct from WHO it names.
    #
    # Added because those two were previously the same fact: is_service_identity
    # tested `email == SERVICE_IDENTITY_EMAIL`, so the moment a keyed request began
    # carrying a real person's address for the audit trail, it would silently have
    # stopped counting as a service identity -- and /internal/execute's permission
    # to name a tenant would have vanished with it. Attribution must be free to
    # change without moving an authorisation boundary.
    via_api_key: bool = False

    def has_role(self, required: Role) -> bool:
        """Check if user has the required role (including inherited)."""
        for user_role in self.roles:
            if required in ROLE_HIERARCHY.get(user_role, set()):
                return True
        return False

    @property
    def is_development_identity(self) -> bool:
        """
        True when this context was granted by the IAP bypass rather than earned.

        Exposed so code that must not run on an unauthenticated identity can say
        so, instead of every caller having to know that email == "dev@localhost"
        is load-bearing.
        """
        return self.iap_subject is None and self.email == DEV_IDENTITY_EMAIL

    @property
    def is_service_identity(self) -> bool:
        """
        True when this context was earned by presenting a valid API key.

        Distinct from is_development_identity even though both have no IAP
        subject: a key holder is authenticated, and code that refuses to run on
        an unearned identity must not also refuse the console.

        Keyed off via_api_key rather than the email, so it stays true when the
        console forwards a signed session and `email` becomes the acting person.
        The key is what authorised the request either way.
        """
        return self.iap_subject is None and self.via_api_key

    @property
    def acts_for_a_person(self) -> bool:
        """
        True when a human is on the other end of this request.

        The audit trail's reason for existing is answering "who decided this", and
        this is how a caller asks whether that question has an answer at all. False
        for a script holding the API key, for the anonymous floor, and for
        /internal/execute.
        """
        return self.email not in (SERVICE_IDENTITY_EMAIL, DEV_IDENTITY_EMAIL)


def _verify_iap_jwt(token: str) -> dict | None:
    """
    Verify Google IAP JWT and return claims.

    Returns None if verification fails.
    """
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        claims = id_token.verify_token(
            token,
            google_requests.Request(),
            audience=IAP_AUDIENCE,
            certs_url="https://www.gstatic.com/iap/verify/public_key",
        )
        return claims
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "IAP JWT verification failed (token length %d, audience %s)",
            len(token or ""),
            IAP_AUDIENCE,
            exc_info=True,
        )
        return None


def _get_user_roles(email: str) -> set[Role]:
    """
    Get roles for a user email.

    In production, this would query Firestore or a role management service.
    For now, uses environment-based configuration.
    """
    # Admin emails from environment (comma-separated)
    admin_emails = os.getenv("ADMIN_EMAILS", "").split(",")
    operator_emails = os.getenv("OPERATOR_EMAILS", "").split(",")
    reviewer_emails = os.getenv("REVIEWER_EMAILS", "").split(",")

    roles = {Role.VIEWER}  # Everyone gets viewer by default

    if email in admin_emails:
        roles.add(Role.GOVERNANCE_ADMIN)
    if email in operator_emails:
        roles.add(Role.OPERATOR)
    if email in reviewer_emails:
        roles.add(Role.REVIEWER)

    return roles


def get_auth_context() -> AuthContext | None:
    """Get the current request's auth context, or None if not authenticated."""
    return getattr(g, "auth_context", None)


def _presented_api_key() -> str | None:
    """The API key this request presented, or None if it presented none."""
    supplied = request.headers.get(API_KEY_HEADER)
    return supplied.strip() if supplied else None


def _api_key_context() -> AuthContext | None:
    """
    The service context for a request carrying the correct API key.

    Returns None when no key was presented, so the caller can fall through to
    IAP or to the anonymous identity. A *wrong* key is a different answer and is
    handled by the caller: falling through on a bad key would silently downgrade
    a failed authentication into an anonymous read, and the operator would see
    "permission denied" on a write with no hint that their key was simply wrong.
    """
    expected = api_key()
    supplied = _presented_api_key()
    if not expected or not supplied:
        return None

    # compare_digest, not ==. String equality on a secret returns as soon as it
    # finds a differing byte, which leaks the length of the matching prefix to
    # anyone able to time the response.
    if not hmac.compare_digest(supplied, expected):
        return None

    # The key authorises; a forwarded session says who is acting. When the console
    # sends both, the audit trail gets the person's address instead of
    # "service:api-key" -- which is the difference between an audit trail that can
    # answer "who released this shipment" and one that cannot.
    #
    # Roles are NOT taken from the session. A session proves identity, not
    # entitlement, and deriving permissions from it would let the console decide its
    # own authorisation. What the key grants is what the caller gets.
    acting = _console_session_email()

    return AuthContext(
        email=acting or SERVICE_IDENTITY_EMAIL,
        roles={Role.GOVERNANCE_ADMIN},
        iap_subject=None,
        # The single implicit tenant, so a keyed request walks the same
        # tenant-scoped store path as an IAP one rather than a separate branch.
        tenant_id=tenant.SINGLE_TENANT_ID,
        via_api_key=True,
    )


def authenticate_request() -> tuple[dict, int] | None:
    """
    Authenticate the current request.

    Three credentials are accepted, in this order:

      1. An API key in X-VF-API-Key. This is how the console's server-side proxy
         acts: the browser never holds the key, so a write is reachable from the
         console and not by curling the service directly.
      2. An IAP JWT, when IAP is configured.
      3. Nothing, which yields the ANONYMOUS_ROLE identity -- VIEWER by default.

    A fourth header, X-VF-Session, is not a credential and does not appear in that
    order. It changes only WHO a keyed request is recorded as, never WHAT it may
    do: see _api_key_context(). A request presenting a session and no key is
    anonymous, exactly as if the session were absent.

    Returns an error response tuple on failure, None on success, and sets
    g.auth_context either way it succeeds.

    What changed and why: this function used to grant GOVERNANCE_ADMIN to every
    caller whenever IAP was off, and that is not a hypothetical. The deployed
    service had IAP unset and allUsers holding run.invoker, so an anonymous
    POST to /api/v1/orchestrator/reset returned 200 and cleared 307 cases from
    Firestore. The guard that was supposed to prevent this --
    tenant.assert_isolation_is_enforceable() -- returns early when MULTI_TENANT
    is false, so it never evaluated IAP at all.
    """
    # 1. API key. Checked before IAP so a machine caller never depends on IAP
    #    being configured, and before the anonymous branch so a key holder is
    #    never silently demoted to a reader.
    supplied_key = _presented_api_key()
    if supplied_key:
        context = _api_key_context()
        if context is None:
            # Presented a key and it did not match. Said plainly rather than
            # falling through, so a rotation mistake reads as a rotation mistake.
            return jsonify({
                "error": "Invalid API key",
                "detail": f"The {API_KEY_HEADER} header was present but not valid.",
            }), 401
        g.auth_context = context
        return None

    # 2. IAP JWT.
    if iap_enabled():
        token = request.headers.get("X-Goog-IAP-JWT-Assertion")
        if not token:
            return jsonify({"error": "Missing IAP JWT header"}), 401

        claims = _verify_iap_jwt(token)
        if not claims:
            return jsonify({"error": "Invalid IAP JWT"}), 401

        email = claims.get("email", "")
        if not email:
            return jsonify({"error": "No email in IAP claims"}), 401

        # An explicit claim wins over the domain heuristic, so an identity
        # provider that knows the real tenant can say so. tenant_from_email()
        # documents why the heuristic is only a default.
        claimed_tenant = (
            claims.get("tenant_id")
            or claims.get("https://vflogistics.io/tenant_id")
        )
        tenant_id = tenant.normalise(claimed_tenant) or tenant.tenant_from_email(email)

        if tenant.multi_tenant_enabled() and not tenant_id:
            # Refusing is the only safe answer. Serving the request would mean
            # choosing a tenant for someone whose tenant we could not determine,
            # and any choice is potentially another customer's data.
            return jsonify({
                "error": "Could not determine a tenant for this identity",
                "detail": (
                    "No tenant_id claim was present and the email domain did not "
                    "resolve to one. A free-mail address cannot be mapped to a "
                    "tenant."
                ),
            }), 403

        g.auth_context = AuthContext(
            email=email,
            roles=_get_user_roles(email),
            iap_subject=claims.get("sub"),
            tenant_id=tenant_id or tenant.SINGLE_TENANT_ID,
        )
        return None

    # 3. No credential. The role floor decides what this caller may do, and
    #    ANONYMOUS_ROLE defaults to VIEWER -- so reads answer and writes 403.
    floor = anonymous_role()
    if floor is None:
        return jsonify({
            "error": "Authentication required",
            "detail": f"Present a valid {API_KEY_HEADER} header.",
        }), 401

    g.auth_context = AuthContext(
        email=DEV_IDENTITY_EMAIL,
        roles={floor},
        iap_subject=None,
        # The single implicit one rather than None, so an unauthenticated request
        # exercises the same tenant-scoped store path production uses instead of
        # a separate untested branch.
        tenant_id=tenant.SINGLE_TENANT_ID,
    )
    return None


class InsecureAuthConfiguration(RuntimeError):
    """The process is configured to serve real data to unauthenticated writers."""


def grants_write_access(role: Role | None) -> bool:
    """
    Whether a role can reach any state-changing route.

    Derived from ROLE_HIERARCHY rather than compared against a list of role
    names, because every write route in app.py requires REVIEWER or above. A
    hand-written list of "privileged" roles would have to be revisited every time
    a role is added, and the revisit is the step that gets skipped.
    """
    if role is None:
        return False
    return Role.REVIEWER in ROLE_HIERARCHY.get(role, set())


def assert_write_access_is_guarded() -> None:
    """
    Refuse to boot when anonymous callers can write to real data.

    Called at import from app.py, beside tenant.assert_isolation_is_enforceable().
    It exists because that guard did not fire on the configuration that actually
    shipped: it returns early when MULTI_TENANT is false, so it never evaluated
    IAP, and the deployed service ran Firestore with IAP off and allUsers holding
    run.invoker. An anonymous POST to /api/v1/orchestrator/reset returned 200 and
    cleared 307 cases.

    So this guard checks the combination that was live, and deliberately does not
    depend on MULTI_TENANT:

      * the store is Firestore, so the data is real rather than a fixture
      * the anonymous role floor grants writes

    IAP being enabled is an escape, because authenticate_request() returns from
    the IAP branch either way -- with a context or a 401 -- so the anonymous
    branch is unreachable and ANONYMOUS_ROLE cannot be used by anyone.

    A configured VF_API_KEY is deliberately NOT an escape, which is the one
    non-obvious part. A caller presenting no key never enters the key branch; it
    falls through to the anonymous floor. So a key raises the ceiling for the
    console without lowering it for anybody, and "we set a key" is no answer to
    "anonymous callers are admins".

    Local development is unaffected: STORE_BACKEND=memory never trips it, so
    ANONYMOUS_ROLE=governance_admin remains a one-line way to work without auth
    against a throwaway store.
    """
    # Defaults to firestore to match store.py, which is what actually decides
    # where the data goes. app.py's own default was "", and two modules
    # disagreeing about whether this is production is how a guard reads the safe
    # branch while the store reads the real one.
    backend = os.getenv("STORE_BACKEND", "firestore").strip().lower()
    if backend != "firestore":
        return

    if iap_enabled():
        return

    if not grants_write_access(anonymous_role()):
        return

    raise InsecureAuthConfiguration(
        "STORE_BACKEND=firestore with ANONYMOUS_ROLE="
        f"{os.getenv('ANONYMOUS_ROLE', 'viewer')!r}, which grants write access, "
        "and IAP is off. Every anonymous caller could then reset the board, "
        "publish a delegation boundary or release held cargo -- setting "
        "VF_API_KEY does not prevent this, because a caller presenting no key "
        "never reaches the key check. Lower ANONYMOUS_ROLE to 'viewer' so reads "
        "stay public and writes are refused, or set it to 'none', or enable IAP."
    )


def require_auth(f: Callable) -> Callable:
    """Decorator: require authentication for an endpoint."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        error = authenticate_request()
        if error:
            return error
        return f(*args, **kwargs)
    return decorated


def require_role(required_role: Role) -> Callable:
    """Decorator: require a specific role for an endpoint."""
    def decorator(f: Callable) -> Callable:
        @functools.wraps(f)
        def decorated(*args, **kwargs):
            error = authenticate_request()
            if error:
                return error

            ctx = get_auth_context()
            if not ctx or not ctx.has_role(required_role):
                return jsonify({
                    "error": f"Insufficient permissions. Required role: {required_role.value}",
                    "user_roles": [r.value for r in (ctx.roles if ctx else [])],
                }), 403

            return f(*args, **kwargs)
        return decorated
    return decorator


# Convenience decorators for common role requirements
require_viewer = require_role(Role.VIEWER)
require_reviewer = require_role(Role.REVIEWER)
require_operator = require_role(Role.OPERATOR)
require_governance_admin = require_role(Role.GOVERNANCE_ADMIN)
