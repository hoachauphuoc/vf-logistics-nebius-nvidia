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

class MemoryStore:
    """Process-local store. Fine for a single Cloud Run instance."""

    backend = "memory"

    def __init__(self) -> None:
        self._cases: dict[str, dict[str, Any]] = {}
        self._events: list[dict[str, Any]] = []
        self._audit: list[dict[str, Any]] = []
        self._boundaries: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    # -- delegation boundaries --------------------------------------------

    async def put_boundary(self, boundary: dict[str, Any]) -> None:
        with self._lock:
            self._boundaries[boundary["boundary_id"]] = boundary

    async def active_boundary(self) -> dict[str, Any] | None:
        with self._lock:
            active = [
                b for b in self._boundaries.values() if b.get("status") == "ACTIVE"
            ]
            if not active:
                return None
            return dict(max(active, key=lambda b: b.get("version", 0)))

    async def list_boundaries(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            ordered = sorted(
                self._boundaries.values(),
                key=lambda b: b.get("version", 0),
                reverse=True,
            )
            return [dict(b) for b in ordered[:limit]]

    async def put_case(
        self,
        case: dict[str, Any],
        expected_version: int | None = None,
    ) -> None:
        """
        Store a case with optimistic locking.

        Args:
            case: The case document to store.
            expected_version: If provided, the update only succeeds if the
                current version matches. Pass None for new cases.

        Raises:
            OptimisticLockError: If expected_version does not match current.
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

            # Increment version on every write
            new_version = (existing or {}).get("_version", 0) + 1 if existing else 1
            case["_version"] = new_version
            case["_updated_at"] = utcnow()
            self._cases[case_id] = case

    async def get_case(self, case_id: str) -> dict[str, Any] | None:
        with self._lock:
            case = self._cases.get(case_id)
            return dict(case) if case else None

    async def list_cases(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            cases = sorted(
                self._cases.values(),
                key=lambda c: c.get("created_at", ""),
                reverse=True,
            )
            return [dict(c) for c in cases[:limit]]

    async def query_cases(
        self,
        states: tuple[str, ...] | None = None,
        cursor: str | None = None,
        limit: int = 50,
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
        with self._lock:
            cases = [c for c in self._cases.values() if not c.get("is_marker")]
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

    async def count_by_state(self, states: tuple[str, ...]) -> dict[str, int]:
        """Exact counts across the whole collection, not just a fetched window."""
        with self._lock:
            counts = {s: 0 for s in states}
            for c in self._cases.values():
                if c.get("is_marker"):
                    continue
                state = c.get("state")
                if state in counts:
                    counts[state] += 1
            return counts

    async def sum_rollups(self) -> dict[str, Any]:
        """
        Global token/latency/cost totals from the per-case rollup fields
        (`_agent_calls`, `_input_tokens`, ...) written by the orchestrator on
        every step, not from summing a fetched page - so the number is
        correct at any collection size.
        """
        with self._lock:
            calls = 0
            input_tokens = 0
            output_tokens = 0
            cost = 0.0
            latency_sum = 0
            for c in self._cases.values():
                if c.get("is_marker"):
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

    async def count_by_cleared_by(self) -> dict[str, int]:
        """
        Count cases by cleared_by field (rules vs ai).
        Returns counts for Cost-Aware Hybrid Architecture KPI tiles.
        """
        with self._lock:
            counts = {"rules": 0, "ai": 0, "unknown": 0, "total_auto_cleared": 0}
            for c in self._cases.values():
                if c.get("is_marker"):
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

    async def claim_next_pending(self, states: tuple[str, ...]) -> dict[str, Any] | None:
        """
        Atomically hand out one case that is ready for work and mark it claimed,
        so two concurrent workers can never pick up the same case.
        """
        now = utcnow()
        now_dt = datetime.now(timezone.utc)
        with self._lock:
            for case in sorted(
                self._cases.values(), key=lambda c: c.get("created_at", "")
            ):
                if not is_claimable(case, states, now, now_dt):
                    continue
                case["claimed"] = True
                case["claimed_at"] = now
                return dict(case)
        return None

    async def release_case(self, case_id: str) -> None:
        with self._lock:
            if case_id in self._cases:
                self._cases[case_id]["claimed"] = False

    async def add_event(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._events.append(event)
            del self._events[:-500]  # bound memory growth

    async def list_events(self, limit: int = 80) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(e) for e in reversed(self._events[-limit:])]

    async def query_events(
        self, cursor: str | None = None, limit: int = 80
    ) -> tuple[list[dict[str, Any]], str | None]:
        with self._lock:
            events = list(reversed(self._events))
            if cursor:
                events = [e for e in events if e.get("at", "") < cursor]
            page = [dict(e) for e in events[:limit]]
            next_cursor = (
                page[-1].get("at")
                if len(page) == limit and page[-1].get("at")
                else None
            )
            return page, next_cursor

    async def add_audit(self, entry: dict[str, Any]) -> None:
        """Append an audit entry. Audit entries are immutable once written."""
        with self._lock:
            # Ensure audit_id exists and is unique
            if "audit_id" not in entry:
                entry["audit_id"] = new_id("AUD")
            entry["_immutable"] = True
            entry["_created_at"] = utcnow()
            self._audit.append(entry)
            # Bounded so a long-running demo process does not grow memory
            # without limit. This is a memory-backend-only limit: it does
            # NOT apply to FirestoreStore, where the audit log is genuinely
            # unbounded and immutable. Do not rely on MemoryStore for a
            # production audit trail past this cap.
            del self._audit[:-5000]

    async def update_audit(self, audit_id: str, updates: dict[str, Any]) -> None:
        """Blocked: audit entries are immutable."""
        raise AuditImmutabilityError("update", audit_id)

    async def delete_audit(self, audit_id: str) -> None:
        """Blocked: audit entries are immutable."""
        raise AuditImmutabilityError("delete", audit_id)

    async def list_audit(self, limit: int = 80) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(a) for a in reversed(self._audit[-limit:])]

    async def query_audit(
        self,
        case_id: str | None = None,
        action: str | None = None,
        status: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Audit entries newest-first with exact field filters and a cursor,
        so a search for an older case is not silently limited to whatever a
        fixed-size window happened to include."""
        with self._lock:
            entries = list(reversed(self._audit))
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

    async def reset(self) -> int:
        """Clear cases and events but preserve audit log (immutable)."""
        with self._lock:
            n = len(self._cases)
            self._cases.clear()
            self._events.clear()
            # AUDIT LOG IS DELIBERATELY NOT CLEARED - immutability guarantee
            # Boundaries deliberately survive a reset: clearing the board is a
            # demo convenience, revoking published authority is not.
            return n

    async def backfill_rollups(self) -> dict[str, int]:
        """No-op: MemoryStore cases are process-local and always written by
        the current code, so they never lack the rollup fields the way a
        case created before those fields existed would."""
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

    # -- delegation boundaries --------------------------------------------

    async def put_boundary(self, boundary: dict[str, Any]) -> None:
        await asyncio.to_thread(
            self._boundaries.document(boundary["boundary_id"]).set, boundary
        )

    async def active_boundary(self) -> dict[str, Any] | None:
        def _q() -> dict[str, Any] | None:
            docs = list(
                self._boundaries.where(
                    filter=self._fs.FieldFilter("status", "==", "ACTIVE")
                )
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

    async def list_boundaries(self, limit: int = 20) -> list[dict[str, Any]]:
        def _q() -> list[dict[str, Any]]:
            docs = (
                self._boundaries.order_by(
                    "version", direction=self._fs.Query.DESCENDING
                )
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
    ) -> None:
        """
        Store a case with optimistic locking using Firestore transactions.

        Args:
            case: The case document to store.
            expected_version: If provided, the update only succeeds if the
                current version matches. Pass None for new cases.

        Raises:
            OptimisticLockError: If expected_version does not match current.
        """
        case_id = case["case_id"]

        def _put_with_version() -> None:
            ref = self._cases.document(case_id)

            if expected_version is None:
                # New case or unconditional write
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

                case["_version"] = current_version + 1
                case["_updated_at"] = utcnow()
                t.set(doc_ref, case)

            _update_if_version_matches(txn, ref)

        await asyncio.to_thread(_put_with_version)

    async def get_case(self, case_id: str) -> dict[str, Any] | None:
        snap = await asyncio.to_thread(self._cases.document(case_id).get)
        return snap.to_dict() if snap.exists else None

    async def list_cases(self, limit: int = 100) -> list[dict[str, Any]]:
        def _q() -> list[dict[str, Any]]:
            docs = (
                self._cases.order_by(
                    "created_at", direction=self._fs.Query.DESCENDING
                )
                .limit(limit)
                .stream()
            )
            return [d.to_dict() for d in docs]

        return await asyncio.to_thread(_q)

    async def query_cases(
        self,
        states: tuple[str, ...] | None = None,
        cursor: str | None = None,
        limit: int = 50,
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

        def _q() -> tuple[list[dict[str, Any]], str | None]:
            q = self._cases
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

    async def count_by_state(self, states: tuple[str, ...]) -> dict[str, int]:
        """
        Exact counts across the whole collection using count() aggregation
        (one per state - Firestore has no GROUP BY). Aggregation queries are
        billed as a single read regardless of how many documents match, so
        this is cheap even at 100k+ cases; callers should still cache it
        briefly rather than call it on every poll.
        """

        def _q() -> dict[str, int]:
            counts: dict[str, int] = {}
            for state in states:
                agg = (
                    self._cases.where(
                        filter=self._fs.FieldFilter("state", "==", state)
                    )
                    .count()
                    .get()
                )
                counts[state] = agg[0][0].value
            return counts

        return await asyncio.to_thread(_q)

    async def sum_rollups(self) -> dict[str, Any]:
        """
        Global token/latency/cost totals via sum() aggregation over the
        per-case rollup fields written by the orchestrator on every step.
        sum() cannot reach into the `steps[]` array, which is exactly why
        those totals are denormalized onto the case document at write time.
        """

        def _q() -> dict[str, Any]:
            agg_input = self._cases.sum("_input_tokens").get()
            agg_output = self._cases.sum("_output_tokens").get()
            agg_calls = self._cases.sum("_agent_calls").get()
            agg_cost = self._cases.sum("_estimated_cost_usd").get()
            agg_latency = self._cases.sum("_sum_latency_ms").get()

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

    async def count_by_cleared_by(self) -> dict[str, int]:
        """
        Count cases by cleared_by field (rules vs ai).
        Returns counts for Cost-Aware Hybrid Architecture KPI tiles.
        
        Firestore aggregation cannot GROUP BY multiple fields, so we run
        separate count() queries for each cleared_by value.
        """

        def _q() -> dict[str, int]:
            counts = {"rules": 0, "ai": 0, "unknown": 0, "total_auto_cleared": 0}
            
            # Total AUTO_CLEARED
            total_agg = (
                self._cases.where(
                    filter=self._fs.FieldFilter("state", "==", "AUTO_CLEARED")
                )
                .count()
                .get()
            )
            counts["total_auto_cleared"] = total_agg[0][0].value
            
            # Cleared by rules
            rules_agg = (
                self._cases.where(
                    filter=self._fs.FieldFilter("state", "==", "AUTO_CLEARED")
                )
                .where(filter=self._fs.FieldFilter("cleared_by", "==", "rules"))
                .count()
                .get()
            )
            counts["rules"] = rules_agg[0][0].value
            
            # Cleared by AI
            ai_agg = (
                self._cases.where(
                    filter=self._fs.FieldFilter("state", "==", "AUTO_CLEARED")
                )
                .where(filter=self._fs.FieldFilter("cleared_by", "==", "ai"))
                .count()
                .get()
            )
            counts["ai"] = ai_agg[0][0].value
            
            # Unknown = total - rules - ai
            counts["unknown"] = counts["total_auto_cleared"] - counts["rules"] - counts["ai"]
            
            return counts

        return await asyncio.to_thread(_q)

    async def claim_next_pending(self, states: tuple[str, ...]) -> dict[str, Any] | None:
        """
        Claim inside a Firestore transaction. This is what makes the worker
        safe against duplicate Pub/Sub delivery and against more than one
        Cloud Run instance being alive during a rollout.

        Readiness is decided in Python rather than in the query. Expressing
        "unclaimed OR lease expired" plus a state filter plus ordering would
        need a hand-built composite index, and the whole point of this service
        is that it runs against a bare Firestore database with no setup step.
        """
        now = utcnow()
        now_dt = datetime.now(timezone.utc)

        def _claim() -> dict[str, Any] | None:
            candidates = list(self._cases.limit(60).stream())
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

    async def release_case(self, case_id: str) -> None:
        await asyncio.to_thread(
            self._cases.document(case_id).update, {"claimed": False}
        )

    # -- append-only feeds -------------------------------------------------

    async def add_event(self, event: dict[str, Any]) -> None:
        await asyncio.to_thread(self._events.document(event["event_id"]).set, event)

    async def list_events(self, limit: int = 80) -> list[dict[str, Any]]:
        def _q() -> list[dict[str, Any]]:
            docs = (
                self._events.order_by("at", direction=self._fs.Query.DESCENDING)
                .limit(limit)
                .stream()
            )
            return [d.to_dict() for d in docs]

        return await asyncio.to_thread(_q)

    async def query_events(
        self, cursor: str | None = None, limit: int = 80
    ) -> tuple[list[dict[str, Any]], str | None]:
        def _q() -> tuple[list[dict[str, Any]], str | None]:
            q = self._events.order_by("at", direction=self._fs.Query.DESCENDING)
            if cursor:
                q = q.start_after({"at": cursor})
            docs = list(q.limit(limit).stream())
            items = [d.to_dict() for d in docs]
            next_cursor = items[-1].get("at") if len(items) == limit else None
            return items, next_cursor

        return await asyncio.to_thread(_q)

    async def add_audit(self, entry: dict[str, Any]) -> None:
        """Append an audit entry. Audit entries are immutable once written."""
        if "audit_id" not in entry:
            entry["audit_id"] = new_id("AUD")
        entry["_immutable"] = True
        entry["_created_at"] = utcnow()
        await asyncio.to_thread(self._audit.document(entry["audit_id"]).set, entry)

    async def update_audit(self, audit_id: str, updates: dict[str, Any]) -> None:
        """Blocked: audit entries are immutable."""
        raise AuditImmutabilityError("update", audit_id)

    async def delete_audit(self, audit_id: str) -> None:
        """Blocked: audit entries are immutable."""
        raise AuditImmutabilityError("delete", audit_id)

    async def list_audit(self, limit: int = 80) -> list[dict[str, Any]]:
        def _q() -> list[dict[str, Any]]:
            docs = (
                self._audit.order_by("at", direction=self._fs.Query.DESCENDING)
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
    ) -> tuple[list[dict[str, Any]], str | None]:
        """
        Audit entries newest-first with exact field filters, queried on the
        server via composite indexes (see firestore.indexes.json) instead of
        filtering a fixed-size fetched window - the earlier approach made a
        search for an older case return an empty result that looked like
        missing data rather than an under-sized window.

        At most one of case_id/action/status is expected per call; combining
        more than one would need a wider composite index than is declared.
        """

        def _q() -> tuple[list[dict[str, Any]], str | None]:
            q = self._audit
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

    async def reset(self) -> int:
        """
        Clear cases and events but preserve audit log (immutable).

        Exists so a demo run starts from a clean board; without it, terminal
        cases from earlier runs stay on the dashboard forever.
        """

        def _wipe() -> int:
            removed = 0
            # AUDIT LOG IS DELIBERATELY NOT CLEARED - immutability guarantee
            for coll in (self._cases, self._events):
                while True:
                    batch = list(coll.limit(300).stream())
                    if not batch:
                        break
                    writer = self._db.batch()
                    for doc in batch:
                        writer.delete(doc.reference)
                    writer.commit()
                    removed += len(batch)
            return removed

        return await asyncio.to_thread(_wipe)

    async def backfill_rollups(self) -> dict[str, int]:
        """
        One-off migration: compute `_agent_calls`/`_input_tokens`/
        `_output_tokens`/`_estimated_cost_usd`/`_sum_latency_ms` from
        `steps[]` for every case written before those rollup fields
        existed, so `sum_rollups()`/`global_metrics()` reflect full
        history rather than silently reading 0 for pre-migration cases.
        Idempotent: a case that already has `_agent_calls` is left alone.
        """
        from vf_logistics import config as model_config  # local import: store.py has no other

        def _run() -> dict[str, int]:
            updated = 0
            skipped = 0
            for doc in self._cases.stream():
                case = doc.to_dict() or {}
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
                    pricing = model_config.pricing_for(step.get("model"))
                    cost += (
                        it * pricing["input"] + ot * pricing["output"]
                    ) / 1_000_000

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

    requested = os.getenv("STORE_BACKEND", "firestore").lower()
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
