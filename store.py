"""
State store for the autonomous orchestrator.

Two interchangeable backends behind one interface:

  * firestore (default) - durable, survives Cloud Run instance restarts, so a
    long-running case can be picked up by a different instance than the one
    that ingested it.
  * memory - process-local dict. Selected with STORE_BACKEND=memory. Exists so
    the demo is always runnable even if Firestore is not provisioned.

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

    async def put_case(self, case: dict[str, Any]) -> None:
        with self._lock:
            self._cases[case["case_id"]] = case

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

    async def add_audit(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self._audit.append(entry)
            del self._audit[:-500]

    async def list_audit(self, limit: int = 80) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(a) for a in reversed(self._audit[-limit:])]

    async def reset(self) -> int:
        with self._lock:
            n = len(self._cases)
            self._cases.clear()
            self._events.clear()
            self._audit.clear()
            # Boundaries deliberately survive a reset: clearing the board is a
            # demo convenience, revoking published authority is not.
            return n


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

    async def put_case(self, case: dict[str, Any]) -> None:
        await asyncio.to_thread(self._cases.document(case["case_id"]).set, case)

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

    async def add_audit(self, entry: dict[str, Any]) -> None:
        await asyncio.to_thread(self._audit.document(entry["audit_id"]).set, entry)

    async def list_audit(self, limit: int = 80) -> list[dict[str, Any]]:
        def _q() -> list[dict[str, Any]]:
            docs = (
                self._audit.order_by("at", direction=self._fs.Query.DESCENDING)
                .limit(limit)
                .stream()
            )
            return [d.to_dict() for d in docs]

        return await asyncio.to_thread(_q)

    async def reset(self) -> int:
        """
        Clear every collection.

        Exists so a demo run starts from a clean board; without it, terminal
        cases from earlier runs stay on the dashboard forever.
        """

        def _wipe() -> int:
            removed = 0
            for coll in (self._cases, self._events, self._audit):
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
