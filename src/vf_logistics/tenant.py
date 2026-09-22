"""
Tenant resolution and the isolation policy.

Why this is one module rather than a parameter threaded through everything
-------------------------------------------------------------------------
A tenant filter that has to be remembered in twenty-two store methods is a
filter that will be forgotten in one of them, and the one that is forgotten is a
cross-tenant data leak rather than a bug report. So the policy lives here: what a
valid tenant id is, how it is resolved from a request, and -- most importantly --
what happens when it is absent.

The default is refusal
----------------------
`require_tenant()` raises rather than returning a fallback. There is no "default
tenant" and no empty-string tenant, because both would silently pool one
customer's shipments into a bucket another customer can read. A missing tenant is
a programming error in an authenticated path, and it must fail loudly at the
point of the mistake.

`MULTI_TENANT`
--------------
Off by default. When off, everything is scoped to a single implicit tenant, which
is exactly what the deployment is today -- one organisation auditing its own
shipments -- and existing behaviour is unchanged. When on, every read and write
must carry a tenant and the store refuses anything that does not.

The flag is not a licence to skip the work: the store stamps and filters on
tenant in both modes, so the code path that runs in production is the same one the
tests exercise. The flag governs only whether an absent tenant is an error or is
resolved to the single implicit one.

The guard that matters
----------------------
`assert_isolation_is_enforceable()` refuses to let the process serve multi-tenant
traffic on top of permissive auth. auth.py grants GOVERNANCE_ADMIN to every
request when IAP_ENABLED is not "true", which is correct for local development and
catastrophic with real tenants: a caller who can assert any identity can assert
any tenant, and the isolation below becomes decoration. Failing to boot is the
only safe response, because the alternative is a service that looks isolated and
is not.
"""

from __future__ import annotations

import os
import re

# Conservative on purpose. A tenant id ends up in Firestore document paths and in
# composite index keys, so slashes, dots and whitespace are excluded rather than
# escaped -- an id that needs escaping is an id that will eventually be used
# unescaped somewhere.
_VALID_TENANT = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")

# The single implicit tenant used when multi-tenancy is off. Named rather than
# blank so it is obvious in stored documents which mode wrote them, and so
# turning multi-tenancy on later does not leave a population of records whose
# owner is an empty string.
SINGLE_TENANT_ID = "default"


class TenantError(Exception):
    """A tenant was required and was missing, malformed, or not permitted."""


class TenantIsolationError(Exception):
    """The process cannot enforce the isolation it is configured to promise."""


def multi_tenant_enabled() -> bool:
    return os.getenv("MULTI_TENANT", "false").strip().lower() in ("1", "true", "yes")


def normalise(tenant_id: str | None) -> str | None:
    """Lower-case and trim, returning None for anything empty."""
    if tenant_id is None:
        return None
    cleaned = str(tenant_id).strip().lower()
    return cleaned or None


def validate(tenant_id: str) -> str:
    """Return the id, or raise if it is not a shape we will put in a query."""
    cleaned = normalise(tenant_id)
    if not cleaned or not _VALID_TENANT.match(cleaned):
        raise TenantError(
            f"invalid tenant id {tenant_id!r}: expected 2-63 characters of "
            "lowercase letters, digits, hyphen or underscore, starting with a "
            "letter or digit"
        )
    return cleaned


def resolve(tenant_id: str | None) -> str:
    """
    The tenant a store operation belongs to.

    With multi-tenancy off, an absent tenant resolves to the single implicit one.
    With it on, an absent tenant raises -- see the module docstring for why there
    is no fallback.
    """
    cleaned = normalise(tenant_id)
    if cleaned:
        return validate(cleaned)

    if multi_tenant_enabled():
        raise TenantError(
            "tenant_id is required when MULTI_TENANT is enabled. There is no "
            "default tenant: resolving one would pool a customer's records into "
            "a bucket another customer can read."
        )
    return SINGLE_TENANT_ID


def require_tenant(tenant_id: str | None) -> str:
    """resolve(), but never falls back even with multi-tenancy off.

    For paths that are meaningless without a known tenant -- billing rollups,
    usage attribution -- where silently attributing spend to "default" would
    produce a plausible and wrong invoice.
    """
    cleaned = normalise(tenant_id)
    if not cleaned:
        raise TenantError("tenant_id is required for this operation")
    return validate(cleaned)


def assert_isolation_is_enforceable() -> None:
    """
    Refuse to promise isolation the process cannot deliver.

    Called at import time from app.py. Three conditions have to coincide for this
    to raise, and when they do the service would be serving real tenants while
    granting every anonymous caller governance_admin:

      * MULTI_TENANT is on, so the service claims to isolate tenants
      * the store is Firestore, so the data is real rather than a test fixture
      * IAP_ENABLED is not "true", so a caller could assert any identity -- and
        therefore any tenant

    Raising here is deliberately worse-behaved than logging a warning. A warning
    in a startup log is a thing nobody reads until after the incident.

    Note the early return below: this guard is silent when MULTI_TENANT is off,
    which is exactly how the deployed single-tenant service came to run Firestore
    with IAP off and no key. auth.assert_write_access_is_guarded() covers that
    case and does not consult MULTI_TENANT; both are called from app.py.
    """
    if not multi_tenant_enabled():
        return

    backend = os.getenv("STORE_BACKEND", "firestore").strip().lower()
    iap_on = os.getenv("IAP_ENABLED", "false").strip().lower() == "true"

    if backend == "firestore" and not iap_on:
        raise TenantIsolationError(
            "MULTI_TENANT is enabled with STORE_BACKEND=firestore but "
            "IAP_ENABLED is not 'true'. auth.py grants GOVERNANCE_ADMIN to every "
            "request when IAP is off, so any caller could assert any tenant and "
            "the isolation would be decoration. Set IAP_ENABLED=true and "
            "configure Identity-Aware Proxy, or run with STORE_BACKEND=memory "
            "for local development."
        )


def tenant_from_email(email: str) -> str | None:
    """
    Derive a tenant from an email domain.

    A deliberately simple default for a first multi-tenant deployment: one
    customer organisation per email domain. It is wrong for two situations that
    will arrive -- a customer with several domains, and a consultant who audits
    for several customers -- and both need an explicit user-to-tenant mapping
    rather than a cleverer regex. Stated here so the limit is known before it is
    discovered.

    Free-mail domains return None rather than becoming a shared tenant that every
    gmail user can read.
    """
    cleaned = (email or "").strip().lower()
    if "@" not in cleaned:
        return None

    domain = cleaned.rsplit("@", 1)[1]
    if domain in _FREE_MAIL:
        return None

    # example.co.uk -> example; example.com -> example
    label = domain.split(".")[0]
    candidate = re.sub(r"[^a-z0-9_-]", "-", label)
    try:
        return validate(candidate)
    except TenantError:
        return None


_FREE_MAIL = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com",
    "live.com", "icloud.com", "proton.me", "protonmail.com", "zohomail.com",
    "qq.com", "163.com", "yandex.ru", "mail.ru",
})
