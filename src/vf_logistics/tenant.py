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
traffic with no way to know who a caller is. Every tenant is resolved from a
verified identity through the membership registry (membership.py), so with no
identity source a multi-tenant Firestore service could only refuse everyone --
or, if that refusal were ever weakened, serve them. Failing to boot is the safe
response.

Tenant ids are never derived from an email address. tenant_from_email() did
that -- one tenant per domain's first label -- and it made acme.com and acme.net
one customer (review finding T02). Membership is declared, not inferred.
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

    Called at import time from app.py. Raises when the service would hold real
    tenants' data with no way to tell its callers apart:

      * MULTI_TENANT is on, so the service claims to isolate tenants
      * the store is Firestore, so the data is real rather than a test fixture
      * there is no identity source: IAP_ENABLED is not "true", and there is no
        console session secret (VF_SESSION_SECRET, 32+ characters) to verify the
        signed sessions the console forwards

    The console's signed session counts because it is how this deployment
    actually identifies people -- IAP cannot be enabled on a project with no
    organisation -- and it is verified here with the same HMAC the console mints
    it with. Which tenant each identity may enter is then the membership
    registry's decision, checked by membership.assert_registry_is_usable().

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
    sessions_on = len(os.getenv("VF_SESSION_SECRET", "")) >= 32

    if backend == "firestore" and not (iap_on or sessions_on):
        raise TenantIsolationError(
            "MULTI_TENANT is enabled with STORE_BACKEND=firestore but there is no "
            "identity source: IAP_ENABLED is not 'true' and VF_SESSION_SECRET is "
            "unset or under 32 characters. Without one the service cannot tell "
            "which organisation a caller belongs to. Configure IAP or the console "
            "session secret, or run with STORE_BACKEND=memory for local development."
        )
