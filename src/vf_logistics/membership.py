"""
Organisation membership: which tenant a principal may act in, and with what role.

WHY THIS MODULE EXISTS

Findings T02 and T03 of the authorization review of bd6a210.

T02. tenant_from_email() made a tenant out of the first label of the email domain,
so person@acme.com and person@acme.net were both "acme", and person@yahoo.co.jp
was "yahoo" because the free-mail list only knew yahoo.com. Membership was
granted by string processing.

T03. Every console request -- the API key plus a signed session -- was put in
SINGLE_TENANT_ID whatever email the session named, MULTI_TENANT or not, so two
companies' users landed in one tenant.

The fix is the one tenant_from_email()'s own docstring asked for: an explicit,
declared mapping. A principal is a member of the tenants it is listed under and of
nothing else. An unlisted principal is a member of nothing and is refused; there
is no fallback, because any fallback is somebody else's data.

THE REGISTRY

VF_TENANT_MEMBERS, a JSON object (keep it in Secret Manager -- it is the access
list):

    {
      "alice@acme.com":     {"acme": "governance_admin"},
      "ops@acme.net":       {"acme": "operator"},
      "auditor@firm.com":   {"acme": "reviewer", "beta-shipping": "viewer"},
      "iap:1234567890":     {"beta-shipping": "operator"},
      "service":            {"acme": "operator", "beta-shipping": "operator"}
    }

Principals:
  * a console session is keyed by its verified email -- the console's operator
    list (VF_OPERATORS) is the identity provider, and the email is its stable id
  * an IAP identity is keyed by "iap:<sub>", the provider's stable subject, so a
    changed email address cannot inherit or lose a membership
  * the platform API key is "service"

Read only when MULTI_TENANT is on. With it off the single implicit tenant and the
global role lists apply exactly as before, so the deployed single-tenant service
is unaffected.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache

from vf_logistics import tenant

MEMBERS_ENV = "VF_TENANT_MEMBERS"
SERVICE_PRINCIPAL = "service"

# The role names auth.Role defines. Repeated rather than imported because auth
# imports this module; tests/test_membership.py holds the two sets equal.
VALID_ROLES = frozenset({"viewer", "reviewer", "operator", "governance_admin"})

# The header a caller uses to choose among their own memberships.
TENANT_HEADER = "X-VF-Tenant"


class MembershipConfigError(ValueError):
    """VF_TENANT_MEMBERS is not a registry this module can enforce."""


# Why a membership was refused, for a console to act on rather than parse the
# message (re-review finding R03). The status alone cannot tell "choose one"
# from "the one you chose is not yours": both are 403.
REASON_CHOICE_REQUIRED = "tenant_choice_required"
REASON_NOT_MEMBER_OF_REQUESTED = "not_member_of_requested"
REASON_NO_MEMBERSHIP = "no_membership"
REASON_INVALID_CHOICE = "invalid_choice"


class MembershipError(Exception):
    """This principal may not act in the tenant it asked for (or in any)."""

    def __init__(
        self,
        message: str,
        status: int = 403,
        choices: list[str] | None = None,
        reason: str = REASON_NO_MEMBERSHIP,
    ):
        super().__init__(message)
        self.status = status
        self.choices = choices or []
        self.reason = reason


def normalise_principal(principal: str) -> str:
    return (principal or "").strip().lower()


@lru_cache(maxsize=4)
def _parse(raw: str) -> dict[str, dict[str, str]]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MembershipConfigError(f"{MEMBERS_ENV} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise MembershipConfigError(f"{MEMBERS_ENV} must be a JSON object of principals")

    registry: dict[str, dict[str, str]] = {}
    for principal, grants in data.items():
        key = normalise_principal(str(principal))
        if not key:
            raise MembershipConfigError(f"{MEMBERS_ENV} has an empty principal")
        if not isinstance(grants, dict) or not grants:
            raise MembershipConfigError(
                f"{MEMBERS_ENV}[{principal!r}] must be a non-empty object of tenant: role"
            )
        parsed: dict[str, str] = {}
        for tenant_id, role in grants.items():
            try:
                cleaned = tenant.validate(str(tenant_id))
            except tenant.TenantError as exc:
                raise MembershipConfigError(f"{MEMBERS_ENV}[{principal!r}]: {exc}") from exc
            if role not in VALID_ROLES:
                raise MembershipConfigError(
                    f"{MEMBERS_ENV}[{principal!r}][{tenant_id!r}] is {role!r}; "
                    f"expected one of {sorted(VALID_ROLES)}"
                )
            parsed[cleaned] = role
        if key in registry:
            raise MembershipConfigError(f"{MEMBERS_ENV} lists {principal!r} twice")
        registry[key] = parsed
    return registry


def registry() -> dict[str, dict[str, str]]:
    """The parsed registry. Raises MembershipConfigError if it is malformed."""
    return _parse(os.getenv(MEMBERS_ENV, "").strip() or "{}")


def memberships(principal: str) -> dict[str, str]:
    """{tenant: role} for this principal; empty when it is a member of nothing."""
    return dict(registry().get(normalise_principal(principal), {}))


def resolve(principal: str, requested: str | None = None) -> tuple[str, str]:
    """
    The (tenant, role) this request acts as.

    `requested` is the caller's choice among their OWN memberships, sent as
    X-VF-Tenant. It can only select; it can never add. A tenant the principal is
    not listed under is refused with the same 403 whether or not it exists, so the
    header cannot be used to discover other customers' tenant ids.
    """
    granted = memberships(principal)
    if not granted:
        raise MembershipError(
            "This identity is not a member of any organisation on this service.",
            reason=REASON_NO_MEMBERSHIP,
        )

    choice = (requested or "").strip()
    if choice:
        try:
            wanted = tenant.validate(choice)
        except tenant.TenantError as exc:
            raise MembershipError(
                str(exc), status=400, choices=sorted(granted), reason=REASON_INVALID_CHOICE,
            ) from exc
        if wanted not in granted:
            # Also what a stale choice looks like -- a cookie left by whoever
            # signed in on this browser before -- so the choices go with it.
            raise MembershipError(
                "This identity is not a member of the requested organisation.",
                choices=sorted(granted),
                reason=REASON_NOT_MEMBER_OF_REQUESTED,
            )
        return wanted, granted[wanted]

    if len(granted) == 1:
        only = next(iter(granted))
        return only, granted[only]

    raise MembershipError(
        f"This identity belongs to several organisations; choose one with {TENANT_HEADER}.",
        choices=sorted(granted),
        reason=REASON_CHOICE_REQUIRED,
    )


def assert_registry_is_usable() -> None:
    """
    Refuse to boot multi-tenant with no registry, or a malformed one.

    Called at import from app.py beside tenant.assert_isolation_is_enforceable().
    With MULTI_TENANT on and no registry every request would be refused, which is
    safe but indistinguishable from an outage; a malformed one would fail on the
    first request instead of at deploy. Both are better found at boot.
    """
    if not tenant.multi_tenant_enabled():
        return
    try:
        parsed = registry()
    except MembershipConfigError as exc:
        raise tenant.TenantIsolationError(str(exc)) from exc
    if not parsed:
        raise tenant.TenantIsolationError(
            f"MULTI_TENANT is enabled but {MEMBERS_ENV} names no members. Every "
            "request would be refused: list each principal's organisations and roles."
        )
