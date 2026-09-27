"""
Authentication and authorization middleware for VF Logistics.

Three ways a request is authenticated, in the order authenticate_request() tries
them: the console's API key (optionally with a signed console session naming the
person), a Google IAP JWT, or nothing (the ANONYMOUS_ROLE floor).

Roles:
- viewer: Read-only access to dashboard and case details
- reviewer: Can approve/reject cases in review queue
- operator: Can run simulations, reset board, trigger processing
- governance_admin: Can modify delegation boundaries and permissions

Who holds which role is configuration on THIS service, never a claim in a token:
ADMIN_EMAILS, OPERATOR_EMAILS and REVIEWER_EMAILS list the people, and a
verified console session or IAP identity is looked up in them. See
_api_key_context() for why the console's session can narrow what its key grants
but never widen it.
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
from typing import Any, Callable

from flask import Response, g, jsonify, request

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
    configured, malformed token, bad signature, expired, no email. This function
    does not decide what a failure MEANS -- _api_key_context() does, and it now
    refuses a keyed request whose session fails, because the session is what
    decides that request's role.

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

# Derived from the hierarchy rather than written out, so a role added there cannot
# be ranked inconsistently here: a role's rank is how many roles it includes.
ROLE_RANK = {role: len(included) - 1 for role, included in ROLE_HIERARCHY.items()}
ROLES_BY_RANK = sorted(ROLE_HIERARCHY, key=ROLE_RANK.__getitem__)

# What a valid API key grants on its own. Stated once because it is also the
# ceiling a console session is narrowed under: see _api_key_context().
API_KEY_GRANT = Role.GOVERNANCE_ADMIN

# Which environment variable lists the people holding which role. Applies to a
# verified console session and to an IAP identity alike -- the two ways this
# service learns WHICH person is calling.
ROLE_ASSIGNMENT_VARS: tuple[tuple[str, Role], ...] = (
    ("ADMIN_EMAILS", Role.GOVERNANCE_ADMIN),
    ("OPERATOR_EMAILS", Role.OPERATOR),
    ("REVIEWER_EMAILS", Role.REVIEWER),
)


def highest_role(roles: set[Role]) -> Role:
    """The most privileged role in a set; VIEWER for an empty one."""
    return max(roles, key=ROLE_RANK.__getitem__, default=Role.VIEWER)


def narrow_roles(person: set[Role], ceiling: Role) -> set[Role]:
    """
    A person's roles, capped at `ceiling`.

    Roles at or below the ceiling are kept; any above it collapse to the ceiling
    itself. The result is never empty -- a listed person is at least a viewer.
    """
    limit = ROLE_RANK[ceiling]
    kept = {r for r in person if ROLE_RANK[r] <= limit}
    if any(ROLE_RANK[r] > limit for r in person):
        kept.add(ceiling)
    return kept or {Role.VIEWER}


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
    # True when a verified console session named the person, so `roles` came from
    # the role lists rather than from the key alone. Read by whoami.
    via_session: bool = False

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


def _verify_iap_jwt(token: str) -> dict[str, Any] | None:
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
        return dict(claims)
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "IAP JWT verification failed (token length %d, audience %s)",
            len(token or ""),
            IAP_AUDIENCE,
            exc_info=True,
        )
        return None


def _email_list(variable: str) -> set[str]:
    """
    One role list, normalised.

    Trimmed and lowercased because the list is typed by a person and compared
    against a machine-normalised address: "a@x.com, b@x.com" used to leave
    " b@x.com" unmatchable, and a capitalised entry never matched the lowercased
    session email. Either failure silently demoted the person it named.
    """
    return {
        entry.strip().lower()
        for entry in os.getenv(variable, "").split(",")
        if entry.strip()
    }


def role_sources(email: str) -> dict[str, str]:
    """Which list grants each of this person's roles, for whoami to explain."""
    normalised = (email or "").strip().lower()
    if not normalised:
        return {}
    return {
        role.value: variable
        for variable, role in ROLE_ASSIGNMENT_VARS
        if normalised in _email_list(variable)
    }


def _get_user_roles(email: str) -> set[Role]:
    """
    The roles this service assigns to a person, from ROLE_ASSIGNMENT_VARS.

    Everyone is a viewer; a listed person also holds the listed role. Unlisted is
    therefore viewer, not an error, which makes adding a sign-in account a
    read-only change until someone deliberately grants it more.
    """
    roles = {Role.VIEWER}
    normalised = (email or "").strip().lower()
    for variable, role in ROLE_ASSIGNMENT_VARS:
        if normalised and normalised in _email_list(variable):
            roles.add(role)
    return roles


def get_auth_context() -> AuthContext | None:
    """Get the current request's auth context, or None if not authenticated."""
    return getattr(g, "auth_context", None)


def _presented_api_key() -> str | None:
    """The API key this request presented, or None if it presented none."""
    supplied = request.headers.get(API_KEY_HEADER)
    return supplied.strip() if supplied else None


class InvalidConsoleSession(Exception):
    """A keyed request carried an X-VF-Session header that did not verify."""


def _api_key_context() -> AuthContext | None:
    """
    The context for a request carrying the correct API key.

    Returns None when no key was presented, so the caller can fall through to
    IAP or to the anonymous identity. A *wrong* key is a different answer and is
    handled by the caller: falling through on a bad key would silently downgrade
    a failed authentication into an anonymous read, and the operator would see
    "permission denied" on a write with no hint that their key was simply wrong.

    Two shapes of keyed request:

      * Key alone -- a script, the seeding tools, a B2B integrator. The key is
        the whole credential and grants API_KEY_GRANT, as it always has.

      * Key plus a console session -- a person signed in to the console, whose
        server-side proxy holds the key and forwards the session it verified. The
        session names the person; their roles are then looked up in this
        service's own role lists, and capped at what the key grants.

    WHY THE SESSION NOW DECIDES THE ROLE, AND WHY THAT IS NOT "THE CONSOLE
    DECIDING ITS OWN AUTHORISATION"

    Before this, every signed-in person -- and, because the console attached the
    key to anonymous reads too, every visitor -- held GOVERNANCE_ADMIN. The role
    hierarchy existed on paper only. The earlier rule "roles are not taken from
    the session" was right about the danger and wrong about the remedy: what must
    never happen is a TOKEN asserting a role. Nothing here reads a role from the
    token. The token contributes a verified email, and the mapping from email to
    role is configuration on this service. The console can prove who someone is;
    it cannot make them anything.

    A session can therefore only NARROW the key. It cannot widen it: the ceiling
    is API_KEY_GRANT whatever the lists say.

    WHY A SESSION THAT FAILS TO VERIFY IS REFUSED

    It used to fall back to the key's own identity. With the session deciding the
    role, that fallback would turn an expired or forged session into
    GOVERNANCE_ADMIN -- the escalation this design exists to prevent. The console
    forwards only a session it has verified itself, so one that fails here means
    forgery or a secret the two halves do not share, and both should be loud.
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

    # A blank header carries no claim at all, so it is the same as none.
    presented = (request.headers.get(CONSOLE_SESSION_HEADER) or "").strip()
    if not presented:
        return AuthContext(
            email=SERVICE_IDENTITY_EMAIL,
            roles={API_KEY_GRANT},
            iap_subject=None,
            # The single implicit tenant, so a keyed request walks the same
            # tenant-scoped store path as an IAP one rather than a separate branch.
            tenant_id=tenant.SINGLE_TENANT_ID,
            via_api_key=True,
        )

    acting = _console_session_email()
    if acting is None:
        if console_session_secret() is None:
            raise InvalidConsoleSession(
                "This service has no VF_SESSION_SECRET (or one under 32 characters), "
                "so it cannot verify the X-VF-Session header. The console and the "
                "API must be configured with the same secret."
            )
        raise InvalidConsoleSession(
            "The X-VF-Session header did not verify: it is expired, malformed, or "
            "signed with a different secret. Sign in again."
        )

    return AuthContext(
        email=acting,
        roles=narrow_roles(_get_user_roles(acting), API_KEY_GRANT),
        iap_subject=None,
        tenant_id=tenant.SINGLE_TENANT_ID,
        via_api_key=True,
        via_session=True,
    )


def authenticate_request() -> tuple[Response, int] | None:
    """
    Authenticate the current request.

    Three credentials are accepted, in this order:

      1. An API key in X-VF-API-Key. This is how the console's server-side proxy
         acts: the browser never holds the key, so a write is reachable from the
         console and not by curling the service directly.
      2. An IAP JWT, when IAP is configured.
      3. Nothing, which yields the ANONYMOUS_ROLE identity -- VIEWER by default.

    A fourth header, X-VF-Session, is not a credential on its own: a request
    presenting a session and no key is anonymous, exactly as if the session were
    absent. Alongside a valid key it names the person, and that person's role is
    looked up in this service's role lists -- see _api_key_context(). A session
    that fails to verify alongside a valid key is refused with 401.

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
        try:
            context = _api_key_context()
        except InvalidConsoleSession as exc:
            return jsonify({"error": "Invalid console session", "detail": str(exc)}), 401
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
    decorated._required_role = "authenticated"  # type: ignore[attr-defined]
    return decorated


def require_role(required_role: Role) -> Callable:
    """
    Decorator: require a specific role for an endpoint.

    Also records the requirement on the view as `_required_role`, which is what
    route_policy() reads. functools.wraps copies a function's __dict__, so the
    attribute survives any wraps-based decorator stacked above this one (the rate
    limiter, async_route) -- and a test walks every route to prove it did.
    """
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
                    "required_role": required_role.value,
                    "user_roles": sorted(r.value for r in (ctx.roles if ctx else [])),
                }), 403

            return f(*args, **kwargs)
        decorated._required_role = required_role.value  # type: ignore[attr-defined]
        return decorated
    return decorator


def route_policy(flask_app: Any) -> list[dict[str, Any]]:
    """
    Every route with the role it actually enforces, read from the views.

    Introspected rather than written down, so the Access Control screen shows the
    policy the service runs and cannot show a hand-copied one that has drifted.
    `required_role` is None for a route with no role decorator -- a public one.
    """
    rows: list[dict[str, Any]] = []
    for rule in flask_app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        view = flask_app.view_functions.get(rule.endpoint)
        methods = sorted(m for m in (rule.methods or ()) if m not in ("HEAD", "OPTIONS"))
        rows.append({
            "path": rule.rule,
            "methods": methods,
            "required_role": getattr(view, "_required_role", None),
        })
    return sorted(rows, key=lambda r: (r["path"], r["methods"]))


def describe_identity(ctx: AuthContext) -> dict[str, Any]:
    """
    What this service believes about the caller, for GET /api/v1/auth/whoami.

    The console renders roles from this rather than guessing them, so a screen
    that disables a button is disabling it for the reason the backend would give.
    The backend still enforces every route itself; this is information, not a
    permission.
    """
    if ctx.via_session:
        method = "console_session"
    elif ctx.via_api_key:
        method = "api_key"
    elif ctx.iap_subject is not None:
        method = "iap"
    else:
        method = "anonymous"

    top = highest_role(ctx.roles)
    grants = sorted(
        {implied for held in ctx.roles for implied in ROLE_HIERARCHY.get(held, set())},
        key=ROLE_RANK.__getitem__,
    )

    if method in ("console_session", "iap"):
        sources = role_sources(ctx.email)
        source = sources.get(top.value) or (
            "not listed in " + ", ".join(v for v, _ in ROLE_ASSIGNMENT_VARS)
            + ", so viewer by default"
        )
    elif method == "api_key":
        source = "VF_API_KEY"
    else:
        source = "ANONYMOUS_ROLE"

    return {
        "email": ctx.email,
        "authenticated_by": method,
        "acts_for_a_person": ctx.acts_for_a_person,
        "role": top.value,
        "roles": sorted((r.value for r in ctx.roles), key=lambda v: ROLE_RANK[Role(v)]),
        "grants": [r.value for r in grants],
        "role_source": source,
        "tenant_id": ctx.tenant_id,
    }


# Convenience decorators for common role requirements
require_viewer = require_role(Role.VIEWER)
require_reviewer = require_role(Role.REVIEWER)
require_operator = require_role(Role.OPERATOR)
require_governance_admin = require_role(Role.GOVERNANCE_ADMIN)
