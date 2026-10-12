"""
The operator's day: what is waiting on whom, and whether the work got done.

Two read models over the case store, for the console's Today and Outcomes
screens (Plan 2 of the restructure proposal of 12/10/2026).

WHY ON THE SERVER

Both screens could be drawn in the browser from `/review/queue`, and both would
then be wrong in the way this project has already been wrong once: the queue is
paginated at 40, so a count taken from the loaded page is "at least N", and a
median over one page of resolved cases is a median of whatever happened to be
newest. Grouping and aggregating here, over the whole tenant, makes the numbers
the screens show the numbers the store holds -- and the rules that decide which
group a case is in live in one place that the tests can pin.

WHAT IS MEASURED AND WHAT IS NOT

Every figure is computed from something the system recorded when it happened:
review entries (`case.reviews`), per-case rollups (`_estimated_cost_usd`,
`_sum_latency_ms`), the audit trail's refusals, and operator activity
(store.add_activity -- the time a reviewer actually had a case page open in
front of them). Nothing is estimated. Where a quantity is not recorded -- the
time a shipper took to send documents, until evidence responses are recorded as
events of their own -- it is reported as None with the reason, never as 0.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta
from typing import Any

from vf_logistics.store import get_store, utcnow

# Cases a person still has to act on. AWAITING_EVIDENCE and APPROVED do not exist
# yet; they are the verification loop's states (Plan 1) and are listed so the
# worklist groups them correctly the day they appear, without a second change.
WORK_STATES = (
    "PENDING_HUMAN", "HELD_FOR_REVIEW", "ESCALATED", "AWAITING_EVIDENCE", "APPROVED",
)

# Cases that are finished, and how.
RESOLVED_STATES = ("AUTO_CLEARED", "RELEASED_BY_HUMAN", "BLOCKED_BY_HUMAN")

# What a case is waiting for, in the order the Today screen shows them.
BUCKETS = (
    "awaiting_documents",   # someone asked for paperwork; nothing to decide until it comes
    "awaiting_review",      # a reviewer must read the findings and decide
    "awaiting_sign_off",    # the agent escalated it; the escalation needs a person's signature
    "awaiting_execution",   # decided, not yet carried out (verification loop, Plan 1)
)

# How many cases one call reads at most, so a very large tenant costs a bounded
# number of reads. Past it the response says `truncated` rather than presenting
# a partial count as the whole.
SCAN_LIMIT = 2000
PAGE = 200
# Items returned per bucket. Counts cover every scanned case; the list is a page.
ITEMS_PER_BUCKET = 50


# --------------------------------------------------------------------------
# One case
# --------------------------------------------------------------------------

def _reviews(case: dict[str, Any]) -> list[dict[str, Any]]:
    reviews = case.get("reviews")
    return [r for r in reviews if isinstance(r, dict)] if isinstance(reviews, list) else []


def last_review(case: dict[str, Any]) -> dict[str, Any] | None:
    reviews = _reviews(case)
    return reviews[-1] if reviews else None


def information_rounds(case: dict[str, Any]) -> int:
    """How many times a reviewer had to ask for more before the case could move."""
    return sum(1 for r in _reviews(case) if r.get("action") == "request_info")


def bucket_for(case: dict[str, Any]) -> str | None:
    """
    Which group of the Today screen a case belongs to, or None when nobody owes
    it anything.

    PENDING_HUMAN means two different things, and the distinction is the point of
    the screen: a reviewer who pressed "Request info" is waiting on the shipper,
    and nothing a colleague does will move that case until documents arrive; a
    case parked by the delegation boundary or an injection screen is waiting on a
    reviewer. The last review entry says which.
    """
    state = case.get("state")
    if state == "AWAITING_EVIDENCE":
        return "awaiting_documents"
    if state == "APPROVED":
        return "awaiting_execution"
    if state == "ESCALATED":
        return "awaiting_sign_off"
    if state == "PENDING_HUMAN":
        last = last_review(case)
        if last is not None and last.get("action") == "request_info":
            return "awaiting_documents"
        return "awaiting_review"
    if state == "HELD_FOR_REVIEW":
        return "awaiting_review"
    return None


def owner_of(case: dict[str, Any]) -> dict[str, Any]:
    """
    Who holds the case: the last person who acted on it, else the queue the agent
    routed it to, else nobody.

    A person beats a queue because a reviewer who asked for documents is the one
    who will read them. "Unassigned" is said plainly; a blank owner column reads as
    a rendering fault.
    """
    last = last_review(case)
    if last is not None and isinstance(last.get("reviewer"), str) and last["reviewer"].strip():
        return {"kind": "person", "name": last["reviewer"].strip()}
    for receipt in reversed(case.get("actions") or []):
        if isinstance(receipt, dict) and receipt.get("action") == "assign_analyst":
            queue = (receipt.get("detail") or {}).get("queue")
            if isinstance(queue, str) and queue:
                return {"kind": "queue", "name": queue}
    return {"kind": "unassigned", "name": None}


def _sla_hours(case: dict[str, Any]) -> int | None:
    for receipt in reversed(case.get("actions") or []):
        if isinstance(receipt, dict) and receipt.get("action") == "assign_analyst":
            hours = (receipt.get("detail") or {}).get("sla_hours")
            if isinstance(hours, (int, float)) and not isinstance(hours, bool) and hours > 0:
                return int(hours)
    return None


def waiting_since(case: dict[str, Any]) -> str | None:
    """
    When the case started waiting for what it is waiting for now.

    The last review's timestamp when that review put it in its current state --
    a request for information starts the wait for documents -- otherwise when the
    case was last written, which is when the agent left it there.
    """
    last = last_review(case)
    if last is not None and last.get("state_after") == case.get("state") and last.get("at"):
        return str(last["at"])
    return case.get("updated_at") or case.get("created_at")


def _findings(case: dict[str, Any]) -> list[dict[str, Any]]:
    findings = (case.get("validation") or {}).get("findings")
    return [f for f in findings if isinstance(f, dict)] if isinstance(findings, list) else []


def next_action(case: dict[str, Any]) -> dict[str, str] | None:
    """
    The one thing to do next, as a stable code and a sentence.

    The code is for the console to key on; the sentence is drawn from the case's
    own facts -- the note the reviewer wrote, the action the boundary refused, the
    floor the model scored under -- so it says something a generic label cannot.
    """
    bucket = bucket_for(case)
    if bucket is None:
        return None

    if bucket == "awaiting_documents":
        note = str((last_review(case) or {}).get("note") or "").strip()
        asked = f" Asked for: {note[:160]}" if note else ""
        return {
            "code": "chase_documents",
            "text": f"Chase the shipper for the requested documents.{asked}",
        }

    if bucket == "awaiting_execution":
        return {"code": "execute_approval", "text": "Carry out the approved decision."}

    if bucket == "awaiting_sign_off":
        sar = any(
            isinstance(a, dict) and a.get("action") == "draft_sar" and a.get("status") == "done"
            for a in case.get("actions") or []
        )
        return {
            "code": "sign_off_escalation",
            "text": (
                "Read the investigation and sign off the escalation, or overturn it."
                + (" A SAR draft is waiting for a signature." if sar else "")
            ),
        }

    denials = case.get("gate_denials") or []
    if denials:
        refused = ", ".join(
            str(d.get("action")) for d in denials if isinstance(d, dict) and d.get("action")
        )
        return {
            "code": "decide_refused_action",
            "text": f"The delegation boundary refused {refused or 'the agent'}; decide it yourself.",
        }

    security = case.get("input_security") or {}
    if isinstance(security, dict) and security.get("blocked"):
        return {
            "code": "check_injection",
            "text": "The document was stopped by the injection screen; check it before anything else.",
        }

    rec = case.get("reconciliation") or {}
    if rec.get("score_disputed") is True:
        return {
            "code": "settle_dispute",
            "text": (
                f"The model scored {rec.get('model_risk')} under the rules floor of "
                f"{rec.get('risk_floor')}; read the findings that set the floor."
            ),
        }

    findings = _findings(case)
    if findings:
        top = max(findings, key=lambda f: f.get("floor") or 0)
        more = f" and {len(findings) - 1} more" if len(findings) > 1 else ""
        return {
            "code": "review_findings",
            "text": f"Check {top.get('code')}{more}, then release, block or ask for documents.",
        }

    return {"code": "review_case", "text": "Review the case and decide it."}


def _parse(ts: Any) -> datetime | None:
    if not isinstance(ts, str) or not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def work_item(case: dict[str, Any]) -> dict[str, Any]:
    """The row the Today screen draws for one case. A projection, never the whole case."""
    since = waiting_since(case)
    sla = _sla_hours(case)
    due_at = None
    started = _parse(since)
    if started is not None and sla is not None:
        due_at = (started + timedelta(hours=sla)).isoformat()
    findings = _findings(case)
    top = max(findings, key=lambda f: f.get("floor") or 0) if findings else None
    return {
        "case_id": case.get("case_id"),
        "shipment_id": case.get("shipment_id"),
        "state": case.get("state"),
        "bucket": bucket_for(case),
        "risk_score": case.get("risk_score"),
        "owner": owner_of(case),
        "next_action": next_action(case),
        "waiting_since": since,
        "sla_hours": sla,
        "due_at": due_at,
        "information_rounds": information_rounds(case),
        "finding_count": len(findings),
        "top_finding": top.get("code") if top else None,
        "created_at": case.get("created_at"),
    }


def _sort_key(item: dict[str, Any]) -> tuple[str, int, str]:
    # Soonest due first; no SLA sorts after any SLA. Then the riskiest; then oldest.
    due = item.get("due_at") or "9999"
    risk = item.get("risk_score")
    score = int(risk) if isinstance(risk, (int, float)) and not isinstance(risk, bool) else -1
    return (due, -score, item.get("waiting_since") or "")


def group_work(cases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Cases into BUCKETS, each with its full count and its most urgent items first."""
    grouped: dict[str, list[dict[str, Any]]] = {b: [] for b in BUCKETS}
    for case in cases:
        bucket = bucket_for(case)
        if bucket is not None:
            grouped[bucket].append(work_item(case))
    out: dict[str, dict[str, Any]] = {}
    for bucket in BUCKETS:
        items = sorted(grouped[bucket], key=_sort_key)
        out[bucket] = {"count": len(items), "items": items[:ITEMS_PER_BUCKET]}
    return out


# --------------------------------------------------------------------------
# Whole tenant
# --------------------------------------------------------------------------

async def _scan(
    states: tuple[str, ...], tenant_id: str | None, since: str | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Every case in `states`, newest first, stopping at `since` or SCAN_LIMIT."""
    store = get_store()
    found: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        page, cursor = await store.query_cases(
            states=states, cursor=cursor, limit=PAGE, tenant_id=tenant_id,
        )
        for index, case in enumerate(page):
            # Newest first, so the first case older than the window ends the walk.
            if since and (case.get("created_at") or "") < since:
                return found, False
            found.append(case)
            if len(found) >= SCAN_LIMIT:
                more = cursor is not None or index < len(page) - 1
                return found, more
        if not cursor:
            return found, False


async def build_worklist(tenant_id: str | None) -> dict[str, Any]:
    cases, truncated = await _scan(WORK_STATES, tenant_id)
    buckets = group_work(cases)
    return {
        "buckets": buckets,
        "total": sum(b["count"] for b in buckets.values()),
        "scanned": len(cases),
        "truncated": truncated,
        "at": utcnow(),
    }


def percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile; None for no values, so an empty set is not a 0."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, min(len(ordered), math.ceil(q * len(ordered))))
    return ordered[rank - 1]


def _summary(values: list[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "median": percentile(values, 0.5),
        "p95": percentile(values, 0.95),
        "total": sum(values) if values else None,
    }


def resolved_at(case: dict[str, Any]) -> str | None:
    """When the case was finished: the deciding review for a person, else the last write."""
    if case.get("state") in ("RELEASED_BY_HUMAN", "BLOCKED_BY_HUMAN"):
        for review in reversed(_reviews(case)):
            if review.get("state_after") == case.get("state") and review.get("at"):
                return str(review["at"])
    return case.get("updated_at")


def resolution_kind(case: dict[str, Any]) -> str:
    state = case.get("state")
    if state == "RELEASED_BY_HUMAN":
        return "released_by_reviewer"
    if state == "BLOCKED_BY_HUMAN":
        return "blocked_by_reviewer"
    return "cleared_by_ai" if case.get("cleared_by") == "ai" else "cleared_by_rules"


def summarise_outcomes(
    resolved: list[dict[str, Any]],
    activity_ms: dict[str, int],
    held_by_state: dict[str, int],
    refused: int,
) -> dict[str, Any]:
    """The Outcomes screen's figures, from already-fetched inputs. Pure, for the tests."""
    by_kind = {k: 0 for k in (
        "cleared_by_rules", "cleared_by_ai", "released_by_reviewer", "blocked_by_reviewer",
    )}
    durations: list[float] = []
    costs: list[float] = []
    latencies: list[float] = []
    handling: list[float] = []
    rounds_total = 0
    cases_with_rounds = 0

    for case in resolved:
        by_kind[resolution_kind(case)] += 1
        start, end = _parse(case.get("created_at")), _parse(resolved_at(case))
        if start is not None and end is not None and end >= start:
            durations.append((end - start).total_seconds() * 1000)
        cost = case.get("_estimated_cost_usd")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            costs.append(float(cost))
        latency = case.get("_sum_latency_ms")
        if isinstance(latency, (int, float)) and not isinstance(latency, bool) and latency > 0:
            latencies.append(float(latency))
        rounds = information_rounds(case)
        rounds_total += rounds
        cases_with_rounds += 1 if rounds else 0
        active = activity_ms.get(str(case.get("case_id")))
        if active:
            handling.append(float(active))

    cost_summary = _summary(costs)
    cost_summary["mean"] = (sum(costs) / len(costs)) if costs else None
    human_resolved = by_kind["released_by_reviewer"] + by_kind["blocked_by_reviewer"]
    return {
        "resolved": {"total": len(resolved), "by": by_kind},
        "time_to_resolution_ms": _summary(durations),
        "human_handling_ms": {
            **_summary(handling),
            # Out of the cases a person decided: how many had a page open long
            # enough to be measured. Activity recording started with this screen,
            # so older cases have none, and that is a coverage figure, not a zero.
            "of_human_resolved": human_resolved,
        },
        "information_rounds": {
            "total": rounds_total,
            "cases_with_rounds": cases_with_rounds,
            "mean_per_resolved": (rounds_total / len(resolved)) if resolved else None,
        },
        "cost_per_resolved_usd": cost_summary,
        "model_latency_ms": _summary(latencies),
        "held_now": {"total": sum(held_by_state.values()), "by_state": held_by_state},
        "refused_actions": {"total": refused},
        "external_wait_ms": {
            "value": None,
            "reason": (
                "Not recorded: a request for information is recorded, but the moment "
                "the shipper's documents arrive is not an event of its own yet."
            ),
        },
    }


async def _refused_actions(tenant_id: str | None, since: str | None, until: str | None) -> int:
    """Actions the delegation boundary refused in the window, from the audit trail."""
    store = get_store()
    count = 0
    cursor: str | None = None
    scanned = 0
    while scanned < SCAN_LIMIT:
        page, cursor = await store.query_audit(
            status="denied", cursor=cursor, limit=PAGE, tenant_id=tenant_id,
        )
        for entry in page:
            at = entry.get("at") or ""
            if since and at < since:
                return count
            if until and at >= until:
                continue
            count += 1
        scanned += len(page)
        if not cursor:
            break
    return count


async def build_outcomes(
    tenant_id: str | None, since: str | None = None, until: str | None = None,
) -> dict[str, Any]:
    store = get_store()
    (resolved, truncated), held, refused, activity = await asyncio.gather(
        _scan(RESOLVED_STATES, tenant_id, since=since),
        store.count_by_state(WORK_STATES, tenant_id=tenant_id),
        _refused_actions(tenant_id, since, until),
        store.list_activity(tenant_id=tenant_id),
    )
    if until:
        resolved = [c for c in resolved if (c.get("created_at") or "") < until]
    activity_ms: dict[str, int] = {}
    for row in activity:
        case_id = str(row.get("case_id"))
        activity_ms[case_id] = activity_ms.get(case_id, 0) + int(row.get("active_ms") or 0)

    out = summarise_outcomes(resolved, activity_ms, held, refused)
    out.update({
        "window": {"since": since, "until": until},
        "scanned": len(resolved),
        "truncated": truncated,
        "at": utcnow(),
    })
    return out
