"""
State store for the autonomous orchestrator.

Two interchangeable backends behind one interface:

  * firestore (default) - durable, survives Cloud Run instance restarts, so a
    long-running case can be picked up by a different instance than the one
    that ingested it.
  * memory - process-local dict. Selected with STORE_BACKEND=memory. Exists so
    the demo is always runnable even if Firestore is not provisioned.

Data integrity guarantees:
  * Optimistic locking - every case has a _version field; updates fail if the
    version changed since read (prevents lost updates from concurrent workers).
  * Immutable audit - audit_log entries can only be appended, never modified
    or deleted. The reset() function deliberately skips the audit collection.
  * Transactions - read-modify-write patterns use Firestore transactions to
    prevent race conditions.

Collections / keys:
  cases      - one document per shipment moving through the pipeline
  events     - append-only feed of what the orchestrator did, for the dashboard
  audit_log  - append-only record of actions taken on behalf of the operator

Track: The Taskmaster - Autonomous Workflow Automation
Hackathon: All Things Agentic 2026
"""

from __future__ import annotations

import asyncio
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any


def utcnow() -> str:
    """ISO-8601 UTC timestamp. Avoids the deprecated datetime.utcnow()."""
    return datetime.now(timezone.utc).isoformat()


# A claim is a lease, not a permanent lock. If the instance holding a case dies
# mid-step - a crash, a scale-down, or a revision rollout - the lease expires
# and another worker picks the case up. Without this a redeploy strands
# in-flight cases forever.
from vf_logistics import tenant

CLAIM_LEASE_SECONDS = int(os.getenv("CLAIM_LEASE_SECONDS", "180"))


def _lease_expired(case: dict[str, Any], now_dt: datetime) -> bool:
    claimed_at = case.get("claimed_at")
    if not claimed_at:
        return True
    try:
        held = datetime.fromisoformat(claimed_at)
    except (TypeError, ValueError):
        return True
    if held.tzinfo is None:
        held = held.replace(tzinfo=timezone.utc)
    return (now_dt - held).total_seconds() > CLAIM_LEASE_SECONDS


def is_claimable(case: dict[str, Any], states: tuple[str, ...], now: str, now_dt: datetime) -> bool:
    """Shared predicate so both backends agree on what is ready for work."""
    if case.get("state") not in states:
        return False
    if case.get("not_before") and case["not_before"] > now:
        return False  # still backing off after a failure
    if case.get("claimed") and not _lease_expired(case, now_dt):
        return False  # someone else is actively working it
    return True


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


class OptimisticLockError(Exception):
    """Raised when a case was modified by another process since it was read."""

    def __init__(self, case_id: str, expected_version: int, actual_version: int):
        self.case_id = case_id
        self.expected_version = expected_version
        self.actual_version = actual_version
        super().__init__(
            f"Case {case_id} version conflict: expected {expected_version}, "
            f"found {actual_version}. Reload and retry."
        )


class AuditImmutabilityError(Exception):
    """Raised when attempting to modify or delete an audit entry."""

    def __init__(self, operation: str, audit_id: str):
        self.operation = operation
        self.audit_id = audit_id
        super().__init__(
            f"Audit entries are immutable: cannot {operation} entry {audit_id}"
        )


# --------------------------------------------------------------------------
# In-memory backend
# --------------------------------------------------------------------------

# Tenant ownership, stamped on every document this module writes and checked on
# every document it returns. Underscore-prefixed to match the other
# store-managed fields (_version, _updated_at) -- these are ours, not the
# caller's.
TENANT_FIELD = "_tenant_id"


def _stamp_tenant(doc: dict[str, Any], tenant_id: str | None) -> str:
    """
    Record which tenant owns a document. Returns the resolved tenant.

    Every write in this module goes through here, so there is one place to read
    to know that nothing is stored unowned. A document without an owner is one
    that a tenant-filtered query can never return, which would look like data
    loss rather than like the bug it is.
    """
    resolved = tenant.resolve(tenant_id)
    doc[TENANT_FIELD] = resolved
    return resolved


def _owned_by(doc: dict[str, Any] | None, tenant_id: str) -> bool:
    """
    Whether a document belongs to this tenant.

    Documents written before tenant stamping existed have no owner field. They
    are treated as belonging to the single implicit tenant rather than to nobody,
    because the alternative is that an upgrade makes every existing case
    invisible. That is only sound while those records predate multi-tenancy --
    which they do by definition, since multi-tenancy is what introduced the
    field.
    """
    if doc is None:
        return False
    owner = doc.get(TENANT_FIELD) or tenant.SINGLE_TENANT_ID
    return owner == tenant_id


def _within_window(
    created_at: Any, since: str | None, until: str | None
) -> bool:
    """
    Whether a timestamp falls in the half-open window [since, until).

    Half-open so that consecutive periods neither double-count nor drop a case:
    a case created at exactly the month boundary belongs to the later month and
    to only one of them. Closed-closed bounds would bill the boundary twice.

    Compared lexicographically, which is valid because every timestamp in this
    store comes from utcnow() -- a fixed-width ISO-8601 string at UTC, where
    string order is chronological order. It would NOT be valid across mixed
    offsets, so nothing here should ever store a local-time timestamp.

    A document with no `created_at` is EXCLUDED from a bounded query and included
    in an unbounded one. Excluding it is the conservative answer: a case whose age
    is unknown cannot be asserted to fall inside a billing period, and silently
    billing it to whichever period happens to be queried would be worse than
    leaving it out of both.
    """
    if since is None and until is None:
        return True
    if not isinstance(created_at, str) or not created_at:
        return False
    if since is not None and created_at < since:
        return False
    if until is not None and created_at >= until:
        return False
    return True


class MemoryStore:
    """Process-local store. Fine for a single Cloud Run instance."""

    backend = "memory"

    def __init__(self) -> None:
        self._cases: dict[str, dict[str, Any]] = {}
        self._events: list[dict[str, Any]] = []
        self._audit: list[dict[str, Any]] = []
        self._boundaries: dict[str, dict[str, Any]] = {}
        self._prefilter: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    # -- pre-filter rules --------------------------------------------------
    #
    # Keyed by tenant with no document id of its own: there is exactly one live
    # rule set per tenant, and giving it an id would invite a second.
    #
    # These rules decide which shipments skip AI screening altogether, so they
    # are not display configuration -- they are a control. They used to live in
    # verifier.py module globals, which meant one tenant's edit silently
    # rewrote every tenant's screening until the next container start.

    async def get_prefilter_rules(
        self, tenant_id: str | None = None
    ) -> dict[str, Any] | None:
        """The tenant's stored rules, or None if they have never saved any."""
        scope = tenant.resolve(tenant_id)
        with self._lock:
            stored = self._prefilter.get(scope)
            return dict(stored) if stored else None

    async def put_prefilter_rules(
        self, rules: dict[str, Any], tenant_id: str | None = None
    ) -> None:
        scope = tenant.resolve(tenant_id)
        with self._lock:
            self._prefilter[scope] = dict(rules)

    # -- delegation boundaries --------------------------------------------

    async def put_boundary(
        self, boundary: dict[str, Any], tenant_id: str | None = None
    ) -> None:
        with self._lock:
            _stamp_tenant(boundary, tenant_id)
            self._boundaries[boundary["boundary_id"]] = boundary

    async def active_boundary(
        self, tenant_id: str | None = None
    ) -> dict[str, Any] | None:
        # Boundaries are tenant-scoped because "Compliance Admin configures risk
        # rules" is a per-customer role: one customer's delegated auto-release
        # ceiling has no business governing another's shipments.
        scope = tenant.resolve(tenant_id)
        with self._lock:
            active = [
                b for b in self._boundaries.values()
                if b.get("status") == "ACTIVE" and _owned_by(b, scope)
            ]
            if not active:
                return None
            return dict(max(active, key=lambda b: b.get("version", 0)))

    async def list_boundaries(
        self, limit: int = 20, tenant_id: str | None = None
    ) -> list[dict[str, Any]]:
        scope = tenant.resolve(tenant_id)
        with self._lock:
            ordered = sorted(
                (b for b in self._boundaries.values() if _owned_by(b, scope)),
                key=lambda b: b.get("version", 0),
                reverse=True,
            )
            return [dict(b) for b in ordered[:limit]]

    async def put_case(
        self,
        case: dict[str, Any],
        expected_version: int | None = None,
        tenant_id: str | None = None,
    ) -> None:
        """
        Store a case with optimistic locking.

        Args:
            case: The case document to store.
            expected_version: If provided, the update only succeeds if the
                current version matches. Pass None for new cases.
            tenant_id: Owner. Taken from the case document when already stamped,
                so a read-modify-write cycle cannot silently re-home a case into
                whichever tenant happens to be making the request.

        Raises:
            OptimisticLockError: If expected_version does not match current.
            TenantError: On an attempt to write into another tenant's case.
        """
        with self._lock:
            case_id = case["case_id"]
            existing = self._cases.get(case_id)

            if expected_version is not None:
                current_version = (existing or {}).get("_version", 0)
                if current_version != expected_version:
                    raise OptimisticLockError(
                        case_id, expected_version, current_version
                    )

            # An existing case keeps its owner. Without this an update that
            # happened to be made in another tenant's request context would move
            # the case across the boundary -- a write that silently steals a
            # record rather than failing.
            if existing is not None and existing.get(TENANT_FIELD):
                owner = existing[TENANT_FIELD]
                requested = tenant.normalise(tenant_id) or case.get(TENANT_FIELD)
                if requested and requested != owner:
                    raise tenant.TenantError(
                        f"case {case_id} belongs to tenant {owner!r}; refusing to "
                        f"write it as {requested!r}"
                    )
                case[TENANT_FIELD] = owner
            else:
                _stamp_tenant(case, tenant_id or case.get(TENANT_FIELD))

            # Increment version on every write
            new_version = (existing or {}).get("_version", 0) + 1 if existing else 1
            case["_version"] = new_version
            case["_updated_at"] = utcnow()
            self._cases[case_id] = case

    async def get_case(
        self, case_id: str, tenant_id: str | None = None
    ) -> dict[str, Any] | None:
        scope = tenant.resolve(tenant_id)
        with self._lock:
            case = self._cases.get(case_id)
            # None rather than a 403 on a foreign case. A distinct "exists but is
            # not yours" response confirms the id is real, which lets a caller
            # enumerate another tenant's case ids.
            if not _owned_by(case, scope):
                return None
            return dict(case) if case else None

    async def list_cases(
        self, limit: int = 100, tenant_id: str | None = None
    ) -> list[dict[str, Any]]:
        scope = tenant.resolve(tenant_id)
        with self._lock:
            cases = sorted(
                (c for c in self._cases.values() if _owned_by(c, scope)),
                key=lambda c: c.get("created_at", ""),
                reverse=True,
            )
            return [dict(c) for c in cases[:limit]]

    async def find_case_by_client_reference(
        self, client_reference: str, tenant_id: str | None = None
    ) -> dict[str, Any] | None:
        """
        The case an integrator's own reference already produced, if any.

        Backs idempotency on POST /api/v1/compliance/audit. An ERP whose request
        timed out will retry it, and without this the retry runs the whole
        pipeline again: two audits, two sets of tokens billed, and two possibly
        different verdicts for one shipment.

        Newest-first so that if a reference was somehow reused, the latest audit
        wins rather than an arbitrary one.
        """
        if not client_reference:
            return None
        scope = tenant.resolve(tenant_id)
        with self._lock:
            matches = [
                c for c in self._cases.values()
                if c.get("client_reference") == client_reference
                and _owned_by(c, scope)
            ]
            if not matches:
                return None
            matches.sort(key=lambda c: c.get("created_at", ""), reverse=True)
            return dict(matches[0])

    async def query_cases(
        self,
        states: tuple[str, ...] | None = None,
        cursor: str | None = None,
        limit: int = 50,
        tenant_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """
        Cases newest-first, optionally filtered by state, with cursor
        pagination so a caller can walk the whole collection rather than
        only ever seeing the newest `limit` rows (the bug this replaces:
        filtering *after* truncating to a fixed window silently drops older
        matching cases once enough newer ones exist).

        The cursor is the `created_at` value of the last row returned.
        Timestamps come from `utcnow()` (microsecond ISO-8601), so a
        same-instant collision that would require a tie-break secondary key
        is not a realistic risk for this workload.
        """
        scope = tenant.resolve(tenant_id)
        with self._lock:
            cases = [
                c for c in self._cases.values()
                if not c.get("is_marker") and _owned_by(c, scope)
            ]
            if states:
                cases = [c for c in cases if c.get("state") in states]
            cases.sort(key=lambda c: c.get("created_at", ""), reverse=True)
            if cursor:
                cases = [c for c in cases if c.get("created_at", "") < cursor]
            page = [dict(c) for c in cases[:limit]]
            next_cursor = (
                page[-1].get("created_at")
                if len(page) == limit and page[-1].get("created_at")
                else None
            )
            return page, next_cursor

    async def count_by_state(
        self, states: tuple[str, ...], tenant_id: str | None = None
    ) -> dict[str, int]:
        """Exact counts across the whole collection, not just a fetched window."""
        scope = tenant.resolve(tenant_id)
        with self._lock:
            counts = {s: 0 for s in states}
            for c in self._cases.values():
                if c.get("is_marker") or not _owned_by(c, scope):
                    continue
                state = c.get("state")
                if state in counts:
                    counts[state] += 1
            return counts

    async def sum_rollups(
        self,
        tenant_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        """
        Global token/latency/cost totals from the per-case rollup fields
        (`_agent_calls`, `_input_tokens`, ...) written by the orchestrator on
        every step, not from summing a fetched page - so the number is
        correct at any collection size.

        Tenant-scoped, which makes this the basis for per-customer billing: an
        unscoped total would bill every customer for the whole platform's spend.

        `since` and `until` bound the window by `created_at`, half-open: since <=
        created_at < until. Both are ISO-8601 UTC strings as produced by utcnow(),
        compared lexicographically -- which is correct for that format and is what
        the Firestore implementation does too, so the two agree.

        WITHOUT A WINDOW THERE IS NO INVOICE. This function previously had no time
        filter at all, so it could only ever report lifetime-to-date totals, and
        nothing snapshotted them. A month's usage was therefore not computable even
        in principle: not from this number, and not from a difference of two, because
        the earlier one was never stored.

        The window is on the case's CREATION, not on when each step ran. A case that
        starts on the last day of a month and is decided on the first of the next
        bills entirely to the month it arrived in. That is a deliberate choice --
        per-step attribution would need a timestamp on every step and a different
        aggregation shape -- and it is the convention an invoice has to state.
        """
        scope = tenant.resolve(tenant_id)
        with self._lock:
            calls = 0
            input_tokens = 0
            output_tokens = 0
            cost = 0.0
            latency_sum = 0
            for c in self._cases.values():
                if c.get("is_marker") or not _owned_by(c, scope):
                    continue
                if not _within_window(c.get("created_at"), since, until):
                    continue
                calls += c.get("_agent_calls", 0)
                input_tokens += c.get("_input_tokens", 0)
                output_tokens += c.get("_output_tokens", 0)
                cost += c.get("_estimated_cost_usd", 0.0)
                latency_sum += c.get("_sum_latency_ms", 0)
            return {
                "agent_calls": calls,
                "total_input_tokens": input_tokens,
                "total_output_tokens": output_tokens,
                "estimated_cost_usd": round(cost, 6),
                "avg_latency_ms": int(latency_sum / calls) if calls else 0,
            }

    async def count_by_cleared_by(
        self, tenant_id: str | None = None
    ) -> dict[str, int]:
        """
        Count cases by cleared_by field (rules vs ai).
        Returns counts for Cost-Aware Hybrid Architecture KPI tiles.
        """
        scope = tenant.resolve(tenant_id)
        with self._lock:
            counts = {"rules": 0, "ai": 0, "unknown": 0, "total_auto_cleared": 0}
            for c in self._cases.values():
                if c.get("is_marker") or not _owned_by(c, scope):
                    continue
                if c.get("state") == "AUTO_CLEARED":
                    counts["total_auto_cleared"] += 1
                    cleared_by = c.get("cleared_by")
                    if cleared_by == "rules":
                        counts["rules"] += 1
                    elif cleared_by == "ai":
                        counts["ai"] += 1
                    else:
                        counts["unknown"] += 1
            return counts

    async def claim_next_pending(
        self, states: tuple[str, ...], tenant_id: str | None = None
    ) -> dict[str, Any] | None:
        """
        Atomically hand out one case that is ready for work and mark it claimed,
        so two concurrent workers can never pick up the same case.

        `tenant_id=None` here means "any tenant", not "the default tenant", and
        this is the only method where that is the intended contract: the
        background worker serves every customer, and scoping it to one would
        leave the others' cases unprocessed forever. Callers that want a specific
        tenant pass one, and every request handler does.

        The comment here used to claim this was "the one place" normalise() was
        correct, which stopped being true of the codebase rather than of this
        method: release_case() also used normalise() and was silently accepting
        "any tenant" on a write. It now uses resolve(). If a second method ever
        needs all-tenant reach, it should say so here as explicitly as this one
        does, because normalise() in a scoping position is indistinguishable at a
        glance from a missing check.
        """
        scope = tenant.normalise(tenant_id)
        now = utcnow()
        now_dt = datetime.now(timezone.utc)
        with self._lock:
            for case in sorted(
                self._cases.values(), key=lambda c: c.get("created_at", "")
            ):
                if scope and not _owned_by(case, scope):
                    continue
                if not is_claimable(case, states, now, now_dt):
                    continue
                case["claimed"] = True
                case["claimed_at"] = now
                return dict(case)
        return None

    async def release_case(
        self, case_id: str, tenant_id: str | None = None
    ) -> None:
        # resolve(), not normalise(). normalise() returns None for an absent
        # tenant and never raises, which made `scope` falsy and skipped the
        # ownership check below entirely -- so under multi-tenancy a caller with
        # no tenant could un-claim any case in any tenant and stall that
        # customer's pipeline. resolve() raises instead, which is the same
        # fail-closed shape every other method here uses.
        scope = tenant.resolve(tenant_id)
        with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                return
            # A foreign case is left claimed rather than released. Releasing it
            # would let one tenant interfere with another's pipeline.
            if not _owned_by(case, scope):
                return
            case["claimed"] = False

    async def add_event(
        self, event: dict[str, Any], tenant_id: str | None = None
    ) -> None:
        with self._lock:
            _stamp_tenant(event, tenant_id or event.get(TENANT_FIELD))
            self._events.append(event)
            del self._events[:-500]  # bound memory growth

    async def list_events(
        self, limit: int = 80, tenant_id: str | None = None
    ) -> list[dict[str, Any]]:
        scope = tenant.resolve(tenant_id)
        with self._lock:
            owned = [e for e in self._events if _owned_by(e, scope)]
            return [dict(e) for e in reversed(owned[-limit:])]

    async def query_events(
        self, cursor: str | None = None, limit: int = 80,
        tenant_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        scope = tenant.resolve(tenant_id)
        with self._lock:
            events = [e for e in reversed(self._events) if _owned_by(e, scope)]
            if cursor:
                events = [e for e in events if e.get("at", "") < cursor]
            page = [dict(e) for e in events[:limit]]
            next_cursor = (
                page[-1].get("at")
                if len(page) == limit and page[-1].get("at")
                else None
            )
            return page, next_cursor

    async def add_audit(
        self, entry: dict[str, Any], tenant_id: str | None = None
    ) -> None:
        """Append an audit entry. Audit entries are immutable once written."""
        with self._lock:
            # Ensure audit_id exists and is unique
            if "audit_id" not in entry:
                entry["audit_id"] = new_id("AUD")
            _stamp_tenant(entry, tenant_id or entry.get(TENANT_FIELD))
            entry["_immutable"] = True
            entry["_created_at"] = utcnow()
            self._audit.append(entry)
            # Bounded so a long-running demo process does not grow memory
            # without limit. This is a memory-backend-only limit: it does
            # NOT apply to FirestoreStore, where the audit log is genuinely
            # unbounded and immutable. Do not rely on MemoryStore for a
            # production audit trail past this cap.
            del self._audit[:-5000]

    async def update_audit(
        self, audit_id: str, updates: dict[str, Any],
        tenant_id: str | None = None,
    ) -> None:
        """Blocked: audit entries are immutable."""
        raise AuditImmutabilityError("update", audit_id)

    async def delete_audit(
        self, audit_id: str, tenant_id: str | None = None
    ) -> None:
        """Blocked: audit entries are immutable."""
        raise AuditImmutabilityError("delete", audit_id)

    async def list_audit(
        self, limit: int = 80, tenant_id: str | None = None
    ) -> list[dict[str, Any]]:
        scope = tenant.resolve(tenant_id)
        with self._lock:
            owned = [a for a in self._audit if _owned_by(a, scope)]
            return [dict(a) for a in reversed(owned[-limit:])]

    async def query_audit(
        self,
        case_id: str | None = None,
        action: str | None = None,
        status: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
        tenant_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Audit entries newest-first with exact field filters and a cursor,
        so a search for an older case is not silently limited to whatever a
        fixed-size window happened to include."""
        scope = tenant.resolve(tenant_id)
        with self._lock:
            entries = [a for a in reversed(self._audit) if _owned_by(a, scope)]
            if case_id:
                entries = [a for a in entries if a.get("case_id") == case_id]
            if action:
                entries = [a for a in entries if a.get("action") == action]
            if status:
                entries = [a for a in entries if a.get("status") == status]
            if cursor:
                entries = [a for a in entries if a.get("at", "") < cursor]
            page = [dict(a) for a in entries[:limit]]
            next_cursor = (
                page[-1].get("at")
                if len(page) == limit and page[-1].get("at")
                else None
            )
            return page, next_cursor

    async def reset(self, tenant_id: str | None = None) -> int:
        """
        Clear cases and events but preserve audit log (immutable).

        Tenant-scoped: an unscoped reset would let one customer clear another's
        board. `tenant_id=None` with multi-tenancy off clears the single implicit
        tenant, which is the existing behaviour.
        """
        scope = tenant.resolve(tenant_id)
        with self._lock:
            doomed = [
                cid for cid, c in self._cases.items() if _owned_by(c, scope)
            ]
            for cid in doomed:
                del self._cases[cid]
            self._events[:] = [
                e for e in self._events if not _owned_by(e, scope)
            ]
            # AUDIT LOG IS DELIBERATELY NOT CLEARED - immutability guarantee
            # Boundaries deliberately survive a reset: clearing the board is a
            # demo convenience, revoking published authority is not.
            return len(doomed)

    async def backfill_rollups(self, tenant_id: str | None = None) -> dict[str, int]:
        """No-op: MemoryStore cases are process-local and always written by
        the current code, so they never lack the rollup fields the way a
        case created before those fields existed would.

        `tenant_id` is accepted and unused here only because there is nothing to
        migrate; the Firestore implementation honours it."""
        return {"updated": 0, "skipped": len(self._cases)}


# --------------------------------------------------------------------------
# Firestore backend
# --------------------------------------------------------------------------

class FirestoreStore:
    """
    Durable backend. All google-cloud-firestore calls are blocking, so they are
    pushed onto a thread with asyncio.to_thread to keep the event loop free for
    the concurrent Gemini calls.
    """

    backend = "firestore"

    def __init__(self, project: str) -> None:
        from google.cloud import firestore  # imported lazily so memory mode
                                            # never needs the dependency

        self._fs = firestore
        self._db = firestore.Client(project=project)
        self._cases = self._db.collection("cases")
        self._events = self._db.collection("events")
        self._audit = self._db.collection("audit_log")
        self._boundaries = self._db.collection("delegation_boundaries")
        self._prefilter = self._db.collection("prefilter_rules")

    # -- delegation boundaries --------------------------------------------

    # Every query below adds a tenant filter. The helper keeps the pattern in one
    # place so a new query cannot be written without one -- a missing filter here
    # is not a slow query, it is another customer's data in the response.
    def _scoped(self, collection, scope: str):
        return collection.where(
            filter=self._fs.FieldFilter(TENANT_FIELD, "==", scope)
        )

    # -- pre-filter rules --------------------------------------------------

    async def get_prefilter_rules(
        self, tenant_id: str | None = None
    ) -> dict[str, Any] | None:
        """
        The tenant's stored rules, or None if they have never saved any.

        Addressed by document id rather than by a scoped query, and the id *is*
        the tenant. That makes the read a single get with no index, and makes it
        impossible to end up with two live rule sets for one tenant -- which a
        query-based version would allow and then resolve arbitrarily.
        """
        scope = tenant.resolve(tenant_id)
        snap = await asyncio.to_thread(self._prefilter.document(scope).get)
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        # Defence in depth: the id already scopes this, but a document whose
        # stamp disagrees with its own id means something wrote across tenants
        # and the rules are not safe to screen against.
        if not _owned_by(data, scope):
            return None
        return data

    async def put_prefilter_rules(
        self, rules: dict[str, Any], tenant_id: str | None = None
    ) -> None:
        scope = tenant.resolve(tenant_id)
        payload = dict(rules)
        _stamp_tenant(payload, scope)
        await asyncio.to_thread(self._prefilter.document(scope).set, payload)

    async def put_boundary(
        self, boundary: dict[str, Any], tenant_id: str | None = None
    ) -> None:
        _stamp_tenant(boundary, tenant_id or boundary.get(TENANT_FIELD))
        await asyncio.to_thread(
            self._boundaries.document(boundary["boundary_id"]).set, boundary
        )

    async def active_boundary(
        self, tenant_id: str | None = None
    ) -> dict[str, Any] | None:
        scope = tenant.resolve(tenant_id)

        def _q() -> dict[str, Any] | None:
            docs = list(
                self._scoped(self._boundaries, scope)
                .where(filter=self._fs.FieldFilter("status", "==", "ACTIVE"))
                .limit(10)
                .stream()
            )
            if not docs:
                return None
            # Highest version wins if a partial publish ever left two ACTIVE.
            return max(
                (d.to_dict() for d in docs), key=lambda b: b.get("version", 0)
            )

        return await asyncio.to_thread(_q)

    async def list_boundaries(
        self, limit: int = 20, tenant_id: str | None = None
    ) -> list[dict[str, Any]]:
        scope = tenant.resolve(tenant_id)

        def _q() -> list[dict[str, Any]]:
            docs = (
                self._scoped(self._boundaries, scope)
                .order_by("version", direction=self._fs.Query.DESCENDING)
                .limit(limit)
                .stream()
            )
            return [d.to_dict() for d in docs]

        return await asyncio.to_thread(_q)

    # -- cases -------------------------------------------------------------

    async def put_case(
        self,
        case: dict[str, Any],
        expected_version: int | None = None,
        tenant_id: str | None = None,
    ) -> None:
        """
        Store a case with optimistic locking using Firestore transactions.

        Args:
            case: The case document to store.
            expected_version: If provided, the update only succeeds if the
                current version matches. Pass None for new cases.
            tenant_id: Owner. An existing case keeps the owner already on the
                stored document, so an update made in another tenant's request
                context raises instead of silently re-homing the case.

        Raises:
            OptimisticLockError: If expected_version does not match current.
            TenantError: On an attempt to write into another tenant's case.
        """
        case_id = case["case_id"]
        requested = tenant.normalise(tenant_id) or case.get(TENANT_FIELD)

        def _put_with_version() -> None:
            ref = self._cases.document(case_id)

            if expected_version is None:
                # New case or unconditional write
                _stamp_tenant(case, requested)
                case["_version"] = 1
                case["_updated_at"] = utcnow()
                ref.set(case)
                return

            # Optimistic locking with transaction
            txn = self._db.transaction()

            @self._fs.transactional
            def _update_if_version_matches(t, doc_ref):  # type: ignore[no-untyped-def]
                snap = doc_ref.get(transaction=t)
                if not snap.exists:
                    raise OptimisticLockError(case_id, expected_version, 0)

                current = snap.to_dict()
                current_version = current.get("_version", 0)

                if current_version != expected_version:
                    raise OptimisticLockError(
                        case_id, expected_version, current_version
                    )

                # Checked inside the transaction so it cannot race a concurrent
                # write that changes the owner.
                owner = current.get(TENANT_FIELD)
                if owner:
                    if requested and requested != owner:
                        raise tenant.TenantError(
                            f"case {case_id} belongs to tenant {owner!r}; "
                            f"refusing to write it as {requested!r}"
                        )
                    case[TENANT_FIELD] = owner
                else:
                    _stamp_tenant(case, requested)

                case["_version"] = current_version + 1
                case["_updated_at"] = utcnow()
                t.set(doc_ref, case)

            _update_if_version_matches(txn, ref)

        await asyncio.to_thread(_put_with_version)

    async def get_case(
        self, case_id: str, tenant_id: str | None = None
    ) -> dict[str, Any] | None:
        scope = tenant.resolve(tenant_id)
        snap = await asyncio.to_thread(self._cases.document(case_id).get)
        if not snap.exists:
            return None
        doc = snap.to_dict()
        # None rather than a distinct "exists but is not yours": a different
        # response for a foreign id confirms the id is real and lets a caller
        # enumerate another tenant's case ids.
        return doc if _owned_by(doc, scope) else None

    async def list_cases(
        self, limit: int = 100, tenant_id: str | None = None
    ) -> list[dict[str, Any]]:
        scope = tenant.resolve(tenant_id)

        def _q() -> list[dict[str, Any]]:
            docs = (
                self._scoped(self._cases, scope)
                .order_by("created_at", direction=self._fs.Query.DESCENDING)
                .limit(limit)
                .stream()
            )
            return [d.to_dict() for d in docs]

        return await asyncio.to_thread(_q)

    async def find_case_by_client_reference(
        self, client_reference: str, tenant_id: str | None = None
    ) -> dict[str, Any] | None:
        """
        The case an integrator's own reference already produced, if any.

        Backs idempotency on POST /api/v1/compliance/audit; see the MemoryStore
        docstring for why that matters.

        Needs a composite index on (_tenant_id, client_reference, created_at desc)
        -- see infra/firestore.indexes.json. Without it Firestore rejects the
        query rather than running it slowly, which is the better failure: a
        silently slow idempotency check on the hot path would be worse than a loud
        one.

        Scoped by tenant so one customer's reference cannot collide with another's
        and return their audit.
        """
        if not client_reference:
            return None
        scope = tenant.resolve(tenant_id)

        def _q() -> dict[str, Any] | None:
            docs = (
                self._scoped(self._cases, scope)
                .where(
                    filter=self._fs.FieldFilter(
                        "client_reference", "==", client_reference
                    )
                )
                .order_by("created_at", direction=self._fs.Query.DESCENDING)
                .limit(1)
                .stream()
            )
            for d in docs:
                return d.to_dict()
            return None

        return await asyncio.to_thread(_q)

    async def query_cases(
        self,
        states: tuple[str, ...] | None = None,
        cursor: str | None = None,
        limit: int = 50,
        tenant_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """
        Cases newest-first, optionally filtered by state, queried and
        ordered on the server via a composite index (see
        firestore.indexes.json) rather than fetching a fixed window and
        filtering in Python. That earlier approach is what let cases
        silently fall out of the review queue once enough newer cases
        existed - this replaces it.

        The cursor is the `created_at` of the last row returned; see the
        MemoryStore docstring for why no tie-break key is needed here.
        """
        scope = tenant.resolve(tenant_id)

        def _q() -> tuple[list[dict[str, Any]], str | None]:
            q = self._scoped(self._cases, scope)
            if states:
                q = q.where(
                    filter=self._fs.FieldFilter("state", "in", list(states))
                )
            q = q.order_by("created_at", direction=self._fs.Query.DESCENDING)
            if cursor:
                q = q.start_after({"created_at": cursor})
            docs = list(q.limit(limit).stream())
            items = [d.to_dict() for d in docs]
            next_cursor = (
                items[-1].get("created_at") if len(items) == limit else None
            )
            return items, next_cursor

        return await asyncio.to_thread(_q)

    async def count_by_state(
        self, states: tuple[str, ...], tenant_id: str | None = None
    ) -> dict[str, int]:
        """
        Exact counts across the whole collection using count() aggregation
        (one per state - Firestore has no GROUP BY). Aggregation queries are
        billed as a single read regardless of how many documents match, so
        this is cheap even at 100k+ cases; callers should still cache it
        briefly rather than call it on every poll.
        """
        scope = tenant.resolve(tenant_id)

        def _q() -> dict[str, int]:
            counts: dict[str, int] = {}
            for state in states:
                agg = (
                    self._scoped(self._cases, scope)
                    .where(filter=self._fs.FieldFilter("state", "==", state))
                    .count()
                    .get()
                )
                counts[state] = agg[0][0].value
            return counts

        return await asyncio.to_thread(_q)

    async def sum_rollups(
        self,
        tenant_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        """
        Global token/latency/cost totals via sum() aggregation over the
        per-case rollup fields written by the orchestrator on every step.
        sum() cannot reach into the `steps[]` array, which is exactly why
        those totals are denormalized onto the case document at write time.

        Tenant-scoped, which makes this the basis for per-customer billing: an
        unscoped total would bill every customer for the whole platform's spend.

        `since` and `until` bound the window by `created_at`, half-open:
        since <= created_at < until. Same semantics as the memory backend, which is
        the point -- the two are compared for parity by the test suite, and a
        billing figure that depended on which backend answered would be worse than
        no figure.

        REQUIRES FIVE COMPOSITE INDEXES, one per aggregation:

            (_tenant_id ASC, created_at ASC, _input_tokens ASC)
            (_tenant_id ASC, created_at ASC, _output_tokens ASC)
            (_tenant_id ASC, created_at ASC, _agent_calls ASC)
            (_tenant_id ASC, created_at ASC, _estimated_cost_usd ASC)
            (_tenant_id ASC, created_at ASC, _sum_latency_ms ASC)

        An index on (_tenant_id, created_at) alone is NOT enough, which was learned
        the hard way: Firestore requires the AGGREGATED field to be in the index as
        well as the filtered ones, so the first attempt failed with
        FAILED_PRECONDITION naming `_input_tokens` -- the first of the five sums to
        run. Create them with infra/monitoring/create_billing_indexes.py.

        None of them are needed for the unbounded call, so an existing deployment
        keeps working until the first windowed request -- which means a missing index
        surfaces exactly when an invoice is being cut. Create them before then.
        """
        scope = tenant.resolve(tenant_id)

        def _q() -> dict[str, Any]:
            base = self._scoped(self._cases, scope)
            # Applied to the shared `base` before any aggregation is built, so all
            # five sums see the same window. Adding it per-aggregation would be five
            # chances for one of them to report lifetime totals inside a period
            # report, which reads as a plausible number and is wrong.
            if since is not None:
                base = base.where(
                    filter=self._fs.FieldFilter("created_at", ">=", since)
                )
            if until is not None:
                base = base.where(
                    filter=self._fs.FieldFilter("created_at", "<", until)
                )

            agg_input = base.sum("_input_tokens").get()
            agg_output = base.sum("_output_tokens").get()
            agg_calls = base.sum("_agent_calls").get()
            agg_cost = base.sum("_estimated_cost_usd").get()
            agg_latency = base.sum("_sum_latency_ms").get()

            calls = agg_calls[0][0].value or 0
            latency_sum = agg_latency[0][0].value or 0
            return {
                "agent_calls": calls,
                "total_input_tokens": agg_input[0][0].value or 0,
                "total_output_tokens": agg_output[0][0].value or 0,
                "estimated_cost_usd": round(agg_cost[0][0].value or 0.0, 6),
                "avg_latency_ms": int(latency_sum / calls) if calls else 0,
            }

        return await asyncio.to_thread(_q)

    async def count_by_cleared_by(
        self, tenant_id: str | None = None
    ) -> dict[str, int]:
        """
        Count cases by cleared_by field (rules vs ai).
        Returns counts for Cost-Aware Hybrid Architecture KPI tiles.
        
        Firestore aggregation cannot GROUP BY multiple fields, so we run
        separate count() queries for each cleared_by value.
        """
        scope = tenant.resolve(tenant_id)

        def _q() -> dict[str, int]:
            counts = {"rules": 0, "ai": 0, "unknown": 0, "total_auto_cleared": 0}
            cleared = self._scoped(self._cases, scope).where(
                filter=self._fs.FieldFilter("state", "==", "AUTO_CLEARED")
            )

            counts["total_auto_cleared"] = cleared.count().get()[0][0].value
            counts["rules"] = (
                cleared.where(
                    filter=self._fs.FieldFilter("cleared_by", "==", "rules")
                ).count().get()[0][0].value
            )
            counts["ai"] = (
                cleared.where(
                    filter=self._fs.FieldFilter("cleared_by", "==", "ai")
                ).count().get()[0][0].value
            )
            # Unknown = total - rules - ai
            counts["unknown"] = (
                counts["total_auto_cleared"] - counts["rules"] - counts["ai"]
            )
            return counts

        return await asyncio.to_thread(_q)

    async def claim_next_pending(
        self, states: tuple[str, ...], tenant_id: str | None = None
    ) -> dict[str, Any] | None:
        """
        Claim inside a Firestore transaction. This is what makes the worker
        safe against duplicate Pub/Sub delivery and against more than one
        Cloud Run instance being alive during a rollout.

        Readiness is decided in Python rather than in the query. Expressing
        "unclaimed OR lease expired" plus a state filter plus ordering would
        need a hand-built composite index, and the whole point of this service
        is that it runs against a bare Firestore database with no setup step.

        `tenant_id=None` means "any tenant" here, not "the default tenant", and
        this is the only method where that is the intended contract -- see the
        MemoryStore implementation for why, and for what changed about the claim
        that it was "the one place".

        Note one asymmetry with MemoryStore that matters for the all-tenant case:
        _scoped() is skipped entirely when scope is None, so this reaches
        documents that have no `_tenant_id` at all. A scoped call does not, since
        a Firestore equality filter does not match a missing field. That is the
        right way round -- the worker must be able to drain legacy unstamped
        cases -- but it means a per-tenant caller will not see them.
        """
        scope = tenant.normalise(tenant_id)
        now = utcnow()
        now_dt = datetime.now(timezone.utc)

        def _claim() -> dict[str, Any] | None:
            source = self._cases if scope is None else self._scoped(self._cases, scope)
            candidates = list(source.limit(60).stream())
            candidates.sort(key=lambda d: (d.to_dict() or {}).get("created_at", ""))

            for doc in candidates:
                data = doc.to_dict() or {}
                if not is_claimable(data, states, now, now_dt):
                    continue

                txn = self._db.transaction()

                @self._fs.transactional
                def _take(t, ref):  # type: ignore[no-untyped-def]
                    snap = ref.get(transaction=t)
                    cur = snap.to_dict()
                    if not cur:
                        return None
                    # Re-check under the transaction: another worker may have
                    # taken it between the query and here.
                    if cur.get("claimed") and not _lease_expired(cur, now_dt):
                        return None
                    t.update(ref, {"claimed": True, "claimed_at": now})
                    cur["claimed"] = True
                    cur["claimed_at"] = now
                    return cur

                taken = _take(txn, doc.reference)
                if taken:
                    return taken
            return None

        return await asyncio.to_thread(_claim)

    async def release_case(
        self, case_id: str, tenant_id: str | None = None
    ) -> None:
        scope = tenant.normalise(tenant_id)
        if scope:
            # Read first so one tenant cannot un-claim another's case and
            # interfere with their pipeline.
            snap = await asyncio.to_thread(self._cases.document(case_id).get)
            if not snap.exists or not _owned_by(snap.to_dict(), scope):
                return
        await asyncio.to_thread(
            self._cases.document(case_id).update, {"claimed": False}
        )

    # -- append-only feeds -------------------------------------------------

    async def add_event(
        self, event: dict[str, Any], tenant_id: str | None = None
    ) -> None:
        _stamp_tenant(event, tenant_id or event.get(TENANT_FIELD))
        await asyncio.to_thread(self._events.document(event["event_id"]).set, event)

    async def list_events(
        self, limit: int = 80, tenant_id: str | None = None
    ) -> list[dict[str, Any]]:
        scope = tenant.resolve(tenant_id)

        def _q() -> list[dict[str, Any]]:
            docs = (
                self._scoped(self._events, scope)
                .order_by("at", direction=self._fs.Query.DESCENDING)
                .limit(limit)
                .stream()
            )
            return [d.to_dict() for d in docs]

        return await asyncio.to_thread(_q)

    async def query_events(
        self, cursor: str | None = None, limit: int = 80,
        tenant_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        scope = tenant.resolve(tenant_id)

        def _q() -> tuple[list[dict[str, Any]], str | None]:
            q = self._scoped(self._events, scope).order_by(
                "at", direction=self._fs.Query.DESCENDING
            )
            if cursor:
                q = q.start_after({"at": cursor})
            docs = list(q.limit(limit).stream())
            items = [d.to_dict() for d in docs]
            next_cursor = items[-1].get("at") if len(items) == limit else None
            return items, next_cursor

        return await asyncio.to_thread(_q)

    async def add_audit(
        self, entry: dict[str, Any], tenant_id: str | None = None
    ) -> None:
        """Append an audit entry. Audit entries are immutable once written."""
        if "audit_id" not in entry:
            entry["audit_id"] = new_id("AUD")
        _stamp_tenant(entry, tenant_id or entry.get(TENANT_FIELD))
        entry["_immutable"] = True
        entry["_created_at"] = utcnow()
        await asyncio.to_thread(self._audit.document(entry["audit_id"]).set, entry)

    async def update_audit(
        self, audit_id: str, updates: dict[str, Any],
        tenant_id: str | None = None,
    ) -> None:
        """Blocked: audit entries are immutable."""
        raise AuditImmutabilityError("update", audit_id)

    async def delete_audit(
        self, audit_id: str, tenant_id: str | None = None
    ) -> None:
        """Blocked: audit entries are immutable."""
        raise AuditImmutabilityError("delete", audit_id)

    async def list_audit(
        self, limit: int = 80, tenant_id: str | None = None
    ) -> list[dict[str, Any]]:
        scope = tenant.resolve(tenant_id)

        def _q() -> list[dict[str, Any]]:
            docs = (
                self._scoped(self._audit, scope)
                .order_by("at", direction=self._fs.Query.DESCENDING)
                .limit(limit)
                .stream()
            )
            return [d.to_dict() for d in docs]

        return await asyncio.to_thread(_q)

    async def query_audit(
        self,
        case_id: str | None = None,
        action: str | None = None,
        status: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
        tenant_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """
        Audit entries newest-first with exact field filters, queried on the
        server via composite indexes (see firestore.indexes.json) instead of
        filtering a fixed-size fetched window - the earlier approach made a
        search for an older case return an empty result that looked like
        missing data rather than an under-sized window.

        At most one of case_id/action/status is expected per call; combining
        more than one would need a wider composite index than is declared.
        Each declared index now carries _tenant_id as its leading field.
        """
        scope = tenant.resolve(tenant_id)

        def _q() -> tuple[list[dict[str, Any]], str | None]:
            q = self._scoped(self._audit, scope)
            if case_id:
                q = q.where(filter=self._fs.FieldFilter("case_id", "==", case_id))
            elif action:
                q = q.where(filter=self._fs.FieldFilter("action", "==", action))
            elif status:
                q = q.where(filter=self._fs.FieldFilter("status", "==", status))
            q = q.order_by("at", direction=self._fs.Query.DESCENDING)
            if cursor:
                q = q.start_after({"at": cursor})
            docs = list(q.limit(limit).stream())
            items = [d.to_dict() for d in docs]
            next_cursor = items[-1].get("at") if len(items) == limit else None
            return items, next_cursor

        return await asyncio.to_thread(_q)

    async def reset(self, tenant_id: str | None = None) -> int:
        """
        Clear cases and events but preserve audit log (immutable).

        Exists so a demo run starts from a clean board; without it, terminal
        cases from earlier runs stay on the dashboard forever.

        Tenant-scoped, because an unscoped wipe here would let one customer
        clear another customer's board -- which is the same class of mistake as
        reading their data, with worse consequences.
        """
        scope = tenant.resolve(tenant_id)

        def _wipe() -> int:
            removed = 0
            # AUDIT LOG IS DELIBERATELY NOT CLEARED - immutability guarantee
            for coll in (self._cases, self._events):
                while True:
                    batch = list(
                        self._scoped(coll, scope).limit(300).stream()
                    )
                    if not batch:
                        break
                    writer = self._db.batch()
                    for doc in batch:
                        writer.delete(doc.reference)
                    writer.commit()
                    removed += len(batch)
            return removed

        return await asyncio.to_thread(_wipe)

    async def backfill_rollups(self, tenant_id: str | None = None) -> dict[str, int]:
        """
        One-off migration: compute `_agent_calls`/`_input_tokens`/
        `_output_tokens`/`_estimated_cost_usd`/`_sum_latency_ms` from
        `steps[]` for every case written before those rollup fields
        existed, so `sum_rollups()`/`global_metrics()` reflect full
        history rather than silently reading 0 for pre-migration cases.
        Idempotent: a case that already has `_agent_calls` is left alone.

        Scoped to one tenant. The signature accepted `tenant_id` and ignored it,
        which made this the one write path that reached every customer's
        documents: an operator running the migration for their own tenant
        rewrote fields on every tenant in the collection.

        Filtered in Python via _owned_by rather than with _scoped(). The two do
        not agree about a document that has no `_tenant_id`: _scoped() builds an
        equality filter, and a Firestore equality filter does not match documents
        missing the field, while _owned_by adopts them into the single implicit
        tenant. Scoping the query would therefore have skipped exactly the
        documents this migration exists to fix -- a case old enough to lack
        `_agent_calls` is old enough to lack `_tenant_id` too -- and reported
        "updated: 0" as a success.

        The cost is that this reads the whole collection. For a migration an
        operator runs by hand that is the right trade, and it is why this is not
        a request-path method. Note the scoping still holds where it matters: a
        run under a real tenant id leaves unstamped legacy records alone, because
        _owned_by reports their owner as the implicit tenant, not as the caller's.
        """
        # Local import, kept local: lineage's own tenant_usage() reads the store back
        # through get_store(), so a module-level import here would be a cycle waiting
        # for someone to move that call out of its function.
        from vf_logistics import lineage

        scope = tenant.resolve(tenant_id)

        def _run() -> dict[str, int]:
            updated = 0
            skipped = 0
            for doc in self._cases.stream():
                case = doc.to_dict() or {}
                if not _owned_by(case, scope):
                    skipped += 1
                    continue
                if case.get("is_marker") or "_agent_calls" in case:
                    skipped += 1
                    continue

                calls = 0
                input_tokens = 0
                output_tokens = 0
                cost = 0.0
                latency_sum = 0
                for step in case.get("steps", []) or []:
                    calls += 1
                    it = step.get("input_tokens", 0) or 0
                    ot = step.get("output_tokens", 0) or 0
                    input_tokens += it
                    output_tokens += ot
                    latency = step.get("latency_ms")
                    if isinstance(latency, int):
                        latency_sum += latency
                    # One pricing implementation. See lineage.cost_usd() -- this
                    # was the fourth inline copy of the same arithmetic.
                    cost += lineage.cost_usd(step.get("model"), it, ot)

                doc.reference.update(
                    {
                        "_agent_calls": calls,
                        "_input_tokens": input_tokens,
                        "_output_tokens": output_tokens,
                        "_estimated_cost_usd": round(cost, 6),
                        "_sum_latency_ms": latency_sum,
                    }
                )
                updated += 1
            return {"updated": updated, "skipped": skipped}

        return await asyncio.to_thread(_run)


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------

_store: MemoryStore | FirestoreStore | None = None
_init_note = ""


def store_backend() -> str:
    """
    The configured backend name, defaulting to firestore.

    Named so "is this real data or a fixture" has one answer. app.py used to read
    STORE_BACKEND with a default of "" while this module defaulted to firestore,
    so with the variable unset the store wrote to Firestore while app.py believed
    it was not in production -- and _safe_error returned raw exception text to
    clients as a result.

    tenant.py and auth.py still read the variable directly rather than calling
    this, because importing store from either would be circular. They use the
    same "firestore" default, which is the part that has to agree.
    """
    return os.getenv("STORE_BACKEND", "firestore").strip().lower()


def get_store():
    """
    Return the process-wide store, building it on first use.

    Firestore is preferred, but a failure here must not take the demo down, so
    we fall back to the in-memory backend and record why on the health
    endpoint rather than crashing the container at boot.
    """
    global _store, _init_note
    if _store is not None:
        return _store

    requested = store_backend()
    project = os.getenv("PROJECT_ID", "project-93ded24f-21c3-4f1b-a7d")

    if requested == "memory":
        _store = MemoryStore()
        _init_note = "memory backend requested via STORE_BACKEND"
        return _store

    try:
        _store = FirestoreStore(project)
        _init_note = "firestore connected"
    except Exception as exc:  # noqa: BLE001 - degrade, never fail to boot
        _store = MemoryStore()
        _init_note = f"firestore unavailable ({type(exc).__name__}: {exc}); using memory"

    return _store


def store_status() -> dict[str, str]:
    store = get_store()
    return {"backend": store.backend, "detail": _init_note}
