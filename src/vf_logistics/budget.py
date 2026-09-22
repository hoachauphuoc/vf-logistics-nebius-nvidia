"""
A per-tenant spend ceiling, checked before a model call rather than after.

WHY THIS EXISTS

Nothing in this service stopped one customer running up an unbounded model bill.
The protections that existed were per-request and per-identity:

  - `limiter` keys on `id:<email>` or `ip:<addr>` (app.py) -- never on a tenant, so
    a customer with ten users got ten independent buckets.
  - its storage is `memory://`, so every limit is per-instance and resets on deploy.
  - `MAX_BATCH_ITEMS`, `MAX_BULK_COUNT`, `MAX_CHAIN_STEPS` bound ONE request.

None of those aggregate across a tenant, and no code path anywhere read
accumulated `_estimated_cost_usd` and refused to proceed. Staying under every
published limit, `/api/v1/fraud/batch` at 10/min x 25 items is 250 model calls per
minute per user per instance. The first hard stop was the Nebius account balance.

THIS IS A SOFT CEILING, AND CALLING IT ANYTHING ELSE WOULD BE A LIE

Two reasons it can be overshot, both accepted deliberately:

  1. The spend figure is cached for a few seconds. Reading it from the store before
     every model call would add a Firestore aggregation query to every hop, which
     is both slow and itself billable. So concurrent calls inside one TTL window
     all see the same pre-breach total.
  2. A call's cost is not known until it returns. The check can only ever ask
     "was the tenant already over?", never "will this call put them over?".

The overshoot is therefore bounded by what a tenant can spend in one TTL window,
not by zero. What this buys is the difference between a bill that stops and a bill
that does not -- which is the whole point. A genuinely hard cap needs a reservation
protocol (debit an estimate before the call, reconcile after), and that is a larger
change than the gap it closes.

WHY THE TENANT ARRIVES BY CONTEXTVAR

The chokepoint every model call passes through is `nebius_client._with_retry`, and
it has no tenant argument -- nor should it, since threading one through
`complete_json`, `complete_vision_json`, `complete_with_tools` and all nine agent
call sites would mean nine chances to forget. A ContextVar set once per case in the
orchestrator reaches all of them. asyncio copies the context into each task at
creation, so concurrent cases do not see each other's tenant.
"""

from __future__ import annotations

import logging
import os
import time
from contextvars import ContextVar
from typing import Any

from vf_logistics import tenant as tenant_mod

log = logging.getLogger(__name__)

# The tenant whose budget the current unit of work spends against.
#
# Default None means "not set", which is distinct from "the default tenant" -- see
# current_tenant() for why that distinction is kept.
_current_tenant: ContextVar[str | None] = ContextVar(
    "vf_budget_tenant", default=None
)

# How long a spend total is reused. Short enough to bound the overshoot, long
# enough that a chain of six agent hops on one case does not run six aggregation
# queries. Matches the 5s used by the orchestrator's metrics cache in spirit.
CACHE_TTL_SECONDS = 5.0

# tenant -> (read_at_monotonic, spend_usd)
_cache: dict[str, tuple[float, float]] = {}


class BudgetExceeded(RuntimeError):
    """
    A tenant is over its spend ceiling.

    Carries the numbers so the message an operator sees says how far over, rather
    than only that something was refused.
    """

    def __init__(self, tenant_id: str, spent_usd: float, ceiling_usd: float):
        self.tenant_id = tenant_id
        self.spent_usd = spent_usd
        self.ceiling_usd = ceiling_usd
        super().__init__(
            f"tenant {tenant_id!r} has spent ${spent_usd:.4f} of its "
            f"${ceiling_usd:.2f} ceiling; refusing further model calls"
        )


def ceiling_usd() -> float | None:
    """
    The ceiling, or None for no ceiling.

    Unset means unlimited, which is the pre-existing behaviour and is therefore the
    safe default for an upgrade: switching this on for an existing deployment
    should be a deliberate act, not a side effect of deploying.

    A malformed value is treated as unset rather than as zero. Zero would refuse
    every model call in the service, and a typo in an environment variable should
    not be able to take the product offline.
    """
    raw = os.getenv("VF_TENANT_SPEND_CEILING_USD", "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        log.warning(
            "VF_TENANT_SPEND_CEILING_USD=%r is not a number; treating as no ceiling",
            raw,
        )
        return None
    if value <= 0:
        log.warning(
            "VF_TENANT_SPEND_CEILING_USD=%r is not positive; treating as no ceiling",
            raw,
        )
        return None
    return value


def set_current_tenant(tenant_id: str | None) -> None:
    """
    Declare whose budget the work about to be done spends against.

    Called by the orchestrator at each point where it starts working a case. Safe
    to call with None, which restores "not set".
    """
    _current_tenant.set(tenant_mod.normalise(tenant_id) if tenant_id else None)


def current_tenant() -> str:
    """
    The tenant to charge, resolving "not set" to the single implicit tenant.

    Falling back rather than raising is the right call at this seam: a model call
    that reaches here with no tenant in context is a wiring bug, and taking the
    service down over it would be a worse outcome than charging the default tenant
    -- which under MULTI_TENANT=false is the only tenant there is.

    Under MULTI_TENANT=true the same fallback is a real defect, because the spend
    would be counted against the wrong customer. So it is logged loudly there and
    silently here.
    """
    value = _current_tenant.get()
    if value:
        return value

    if tenant_mod.multi_tenant_enabled():
        log.warning(
            "model call with no tenant in context under MULTI_TENANT=true; "
            "charging %r -- this is a wiring bug, not a configuration choice",
            tenant_mod.SINGLE_TENANT_ID,
        )
    return tenant_mod.SINGLE_TENANT_ID


def forget(tenant_id: str | None = None) -> None:
    """
    Drop cached spend, so the next check re-reads the store.

    Called after a step records cost, so a tenant that crosses the ceiling mid-case
    is refused on the next hop rather than at the end of the TTL window. Without
    this the cache would be the only thing deciding when a breach is noticed.
    """
    if tenant_id is None:
        _cache.clear()
        return
    _cache.pop(tenant_mod.normalise(tenant_id) or tenant_mod.SINGLE_TENANT_ID, None)


async def spend_so_far(tenant_id: str) -> float:
    """
    Accumulated estimated model spend for a tenant, in USD.

    Read from the per-case rollup fields via the store's own tenant-scoped
    aggregation, so it is the same number `/api/v1/billing/usage` reports rather
    than a second implementation that could disagree with it.

    A store failure returns 0.0 and logs. That fails OPEN, which is the wrong
    direction on purpose: a Firestore blip must not stop a customer's shipments
    being screened. The ceiling is a cost control, not a safety control, and the
    cost of a few unmetered minutes is smaller than the cost of a stalled pipeline.
    """
    scope = tenant_mod.normalise(tenant_id) or tenant_mod.SINGLE_TENANT_ID

    cached = _cache.get(scope)
    now = time.monotonic()
    if cached is not None and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    try:
        from vf_logistics.store import get_store

        rollups: dict[str, Any] = await get_store().sum_rollups(tenant_id=scope)
        spend = float(rollups.get("estimated_cost_usd") or 0.0)
    except Exception:
        log.exception("could not read spend for tenant %r; allowing the call", scope)
        return 0.0

    _cache[scope] = (now, spend)
    return spend


async def assert_within_budget() -> None:
    """
    Raise BudgetExceeded if the current tenant is already over its ceiling.

    A no-op when no ceiling is configured, which is the default. Called from
    `nebius_client._with_retry`, the one function every model call passes through.
    """
    ceiling = ceiling_usd()
    if ceiling is None:
        return

    scope = current_tenant()
    spent = await spend_so_far(scope)
    if spent >= ceiling:
        # Logged here as well as raised, with a stable prefix.
        #
        # The exception propagates into an agent's own try/except, which formats it
        # however that agent formats errors -- so depending on that text for an alert
        # would be depending on an incidental string. This line is the contract:
        # a log-based metric matches "TENANT SPEND CEILING REACHED", and it must not
        # be reworded without updating the metric in Cloud Monitoring.
        log.error(
            "TENANT SPEND CEILING REACHED tenant=%s spent_usd=%.6f ceiling_usd=%.2f",
            scope,
            spent,
            ceiling,
        )
        raise BudgetExceeded(scope, spent, ceiling)


async def status(tenant_id: str | None = None) -> dict[str, Any]:
    """
    The ceiling and how much of it is used, for reporting.

    `remaining_usd` is clamped at zero rather than going negative: a tenant that
    overshot by the TTL window is at zero remaining, and a negative number in a
    dashboard reads as a bug rather than as an overshoot.
    """
    scope = tenant_mod.normalise(tenant_id) or current_tenant()
    ceiling = ceiling_usd()
    spent = await spend_so_far(scope)

    return {
        "tenant_id": scope,
        "spent_usd": round(spent, 6),
        "ceiling_usd": ceiling,
        "remaining_usd": None if ceiling is None else round(max(0.0, ceiling - spent), 6),
        "over_ceiling": ceiling is not None and spent >= ceiling,
        # Named so a reader of the API does not mistake this for a hard guarantee.
        # See the module docstring.
        "enforcement": "soft" if ceiling is not None else "none",
    }
