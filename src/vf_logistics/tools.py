"""
Actions the orchestrator takes on behalf of the operator.

This module is the difference between an agent that produces an opinion and an
agent that does the job. Each function performs a real state change, writes an
auditable record, and returns a receipt the case document keeps.

Track: Best Apps and Agents
Hackathon: Nebius x NVIDIA Global AI Hackathon
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from vf_logistics import executor_client
from vf_logistics.config import gcp_project
from vf_logistics.store import get_store, new_id, utcnow

# Optional outbound webhook (Slack / Teams / Google Chat / any HTTP endpoint).
# Left unset in the demo: the notify action then records the payload it would
# have sent rather than silently doing nothing.
NOTIFY_WEBHOOK_URL = os.getenv("NOTIFY_WEBHOOK_URL", "").strip()

# Optional Pub/Sub topic that downstream systems subscribe to for decisions.
DECISIONS_TOPIC = os.getenv("DECISIONS_TOPIC", "case-decisions").strip()


async def _audit(
    case_id: str, action: str, detail: dict[str, Any], status: str = "done",
    tenant_id: str | None = None,
) -> dict[str, Any]:
    entry = {
        "audit_id": new_id("audit"),
        "case_id": case_id,
        "action": action,
        "status": status,
        "detail": detail,
        "at": utcnow(),
    }
    # Scoped so an action receipt lands in the tenant whose case it describes.
    # Every tool below funnels through here, which is why this is the one place
    # the tenant has to arrive -- an unscoped receipt would put one customer's
    # release or SAR draft into another customer's audit trail, and the audit
    # trail is the artefact a customs authority reads.
    await get_store().add_audit(entry, tenant_id=tenant_id)
    return entry


# --------------------------------------------------------------------------
# Shipment disposition
# --------------------------------------------------------------------------

async def release_shipment(
    case_id: str, shipment_id: str, reason: str, tenant_id: str | None = None,
) -> dict[str, Any]:
    """Clear the shipment to continue to delivery."""
    return await _audit(
        case_id,
        "release_shipment",
        {
            "shipment_id": shipment_id,
            "reason": reason,
            "disposition": "RELEASED_FOR_DELIVERY",
        },
        tenant_id=tenant_id,
    )


async def hold_shipment(
    case_id: str, shipment_id: str, reason: str, tenant_id: str | None = None,
) -> dict[str, Any]:
    """Freeze the shipment so it cannot move while under investigation."""
    return await _audit(
        case_id,
        "hold_shipment",
        {
            "shipment_id": shipment_id,
            "reason": reason,
            "disposition": "HELD_DO_NOT_SHIP",
        },
        tenant_id=tenant_id,
    )


async def assign_analyst(
    case_id: str, queue: str, priority: str, tenant_id: str | None = None,
) -> dict[str, Any]:
    """Route the case into a human review queue with a priority."""
    return await _audit(
        case_id,
        "assign_analyst",
        {"queue": queue, "priority": priority, "sla_hours": 24 if priority == "HIGH" else 72},
        tenant_id=tenant_id,
    )


# --------------------------------------------------------------------------
# Regulatory paperwork
# --------------------------------------------------------------------------

async def draft_sar(
    case_id: str, shipment_id: str, narrative: str, exposure: str,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """
    Draft a Suspicious Activity Report from the investigation narrative.

    Deliberately a draft, never a filing: a regulatory submission is not
    something an autonomous agent should complete without a human signature.
    """
    return await _audit(
        case_id,
        "draft_sar",
        {
            "shipment_id": shipment_id,
            "reference": f"SAR-DRAFT-{case_id}",
            "narrative": narrative[:2000],
            "estimated_exposure": exposure,
            "requires_human_signoff": True,
        },
        tenant_id=tenant_id,
    )


# --------------------------------------------------------------------------
# Outbound notification
# --------------------------------------------------------------------------

async def notify_webhook(
    case_id: str, title: str, body: str, severity: str,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """POST the alert to the configured webhook, if one is configured."""
    payload = {
        "case_id": case_id,
        "title": title,
        "body": body,
        "severity": severity,
        "at": utcnow(),
    }

    if not NOTIFY_WEBHOOK_URL:
        return await _audit(
            case_id,
            "notify_webhook",
            {**payload, "note": "NOTIFY_WEBHOOK_URL not set; payload recorded only"},
            status="skipped",
            tenant_id=tenant_id,
        )

    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.post(NOTIFY_WEBHOOK_URL, json=payload)
        return await _audit(
            case_id,
            "notify_webhook",
            {**payload, "http_status": resp.status_code},
            status="done" if resp.is_success else "failed",
            tenant_id=tenant_id,
        )
    except Exception as exc:  # noqa: BLE001 - a failed alert must not kill the case
        return await _audit(
            case_id, "notify_webhook", {**payload, "error": str(exc)},
            status="failed", tenant_id=tenant_id,
        )


# --------------------------------------------------------------------------
# Publish the decision for downstream systems
# --------------------------------------------------------------------------

async def _earlier_publish(
    case_id: str, key: str, tenant_id: str | None,
) -> dict[str, Any] | None:
    """
    The audit row of a publish with this idempotency key that went out, or None.

    A retry after an interrupted execution must not publish the decision a second
    time when the first publish was accepted and only its confirmation was lost.
    Only a row that carries a message id proves the publish; a failed one does not.
    """
    rows, _ = await get_store().query_audit(
        case_id=case_id, action="publish_decision", status="done", limit=200,
        tenant_id=tenant_id,
    )
    for row in rows:
        detail = row.get("detail") or {}
        if detail.get("idempotency_key") != key:
            continue
        delegated = detail.get("executor")
        message_id = detail.get("message_id") or (
            delegated.get("message_id") if isinstance(delegated, dict) else None
        )
        if message_id:
            return row
    return None


async def publish_decision(
    case_id: str, decision: dict[str, Any], tenant_id: str | None = None,
) -> dict[str, Any]:
    """
    Emit the final decision to Pub/Sub so ERP / WMS / billing can react.

    Best effort: if the topic does not exist the decision is still recorded in
    the audit log, which is what the dashboard and the reviewer read.

    Publishing is the one action here that reaches outside the system, so it is
    the one action the analysis identity is deliberately not permitted to
    perform. When an executor service is configured the call is delegated to it
    over an authenticated cross-identity hop; see executor_client. The direct
    path below is used in single-service deployments, and will be refused by IAM
    with a 403 if the running identity lacks pubsub.publisher, which is the
    intended outcome rather than something to work around.
    """
    key = decision.get("idempotency_key")
    if key:
        earlier = await _earlier_publish(case_id, str(key), tenant_id)
        if earlier is not None:
            return earlier

    body = {"case_id": case_id, **decision, "at": utcnow()}

    if executor_client.configured():
        outcome = await executor_client.request_protected_action(
            "publish_decision", case_id, body, tenant_id=tenant_id,
        )
        return await _audit(
            case_id,
            "publish_decision",
            {**body, "via": "executor identity", "executor": outcome},
            status=outcome.get("status", "failed"),
            tenant_id=tenant_id,
        )

    return await publish_decision_direct(case_id, body, tenant_id=tenant_id)


def _may_have_been_accepted(exc: BaseException) -> bool:
    """
    True when the broker may have taken the message although the call raised.

    A timeout, and the Google SDK's DeadlineExceeded and RetryError, say nothing about
    whether the message went out (N01). They are matched by class name down the MRO so
    this module needs no google.api_core import.
    """
    return isinstance(exc, TimeoutError) or any(
        cls.__name__ in ("DeadlineExceeded", "RetryError") for cls in type(exc).__mro__
    )


async def _save_publish_record(
    case_id: str, action: str, detail: dict[str, Any], status: str = "done",
    tenant_id: str | None = None, *, accepted: bool,
) -> dict[str, Any]:
    """
    Save the record of a publish; for a message the broker accepted, hand the receipt
    back unsaved when the store refuses it.

    Raising there turned a sent message into "nothing was sent": the execution failed and
    the retry published the decision a second time although its message id was known (N01).
    Without an accepted message the error goes on, and the caller records a failed send.
    """
    try:
        return await _audit(case_id, action, detail, status=status, tenant_id=tenant_id)
    except Exception:  # noqa: BLE001
        if not accepted:
            raise
        return {"case_id": case_id, "action": action, "status": status, "detail": detail, "at": utcnow()}


async def publish_decision_direct(
    case_id: str, body: dict[str, Any], tenant_id: str | None = None,
) -> dict[str, Any]:
    """
    Publish with the ambient identity.

    Called directly in single-service mode, and called by the executor service on
    behalf of the analysis service in the split-identity deployment.
    """
    try:
        # Filled once the broker has accepted the message (N01). A failure to SAVE its record
        # is not a failure to SEND: reading it as one lost the message id, and the retry
        # published the decision a second time.
        accepted: dict[str, Any] = {}
        import asyncio

        from google.cloud import pubsub_v1

        def _publish() -> str:
            # Resolved here, on the worker thread, because it can probe the metadata
            # server. No project means no topic path: refused and recorded as a failed
            # publish, rather than built against a project someone guessed.
            project = gcp_project()
            if not project:
                raise RuntimeError("no Google Cloud project to publish to: set PROJECT_ID")
            publisher = pubsub_v1.PublisherClient()
            topic = publisher.topic_path(project, DECISIONS_TOPIC)
            # The key is also a message attribute so a subscriber can drop a repeat
            # without parsing the body (N01). Attribute values must be strings.
            attributes = {}
            if body.get("idempotency_key"):
                attributes["idempotency_key"] = str(body["idempotency_key"])
            future = publisher.publish(topic, json.dumps(body).encode("utf-8"), **attributes)
            return future.result(timeout=15)

        message_id = await asyncio.to_thread(_publish)
        accepted["message_id"] = message_id
        return await _audit(
            case_id, "publish_decision", {**body, "message_id": message_id},
            tenant_id=tenant_id,
        )
    except asyncio.CancelledError as exc:
        # Cancelled while the broker was taking the message, or after it had (N01). The
        # record is saved shielded from the cancellation, so a Resume after the lease finds
        # the message id (or an unknown outcome) instead of reading "nothing was sent".
        try:
            await asyncio.shield(_save_publish_record(
                case_id, "publish_decision",
                {**body, **accepted, "error": f"{type(exc).__name__}: {exc}"},
                status="done" if accepted else "unknown",
                tenant_id=tenant_id, accepted=bool(accepted),
            ))
        except Exception:  # noqa: BLE001
            # Only possible without an accepted message (nothing went out): the store's
            # error must not replace the cancellation the caller is waiting for.
            pass
        raise
    except Exception as exc:  # noqa: BLE001
        return await _save_publish_record(
            case_id, "publish_decision",
            {**body, **accepted, "error": f"{type(exc).__name__}: {exc}"},
            # A timeout means the broker may have accepted the message, which is not the same
            # as "not sent" (N01). A retry carries the same idempotency key.
            # An accepted message is a sent one, whatever happened to its first record.
            status="done" if accepted else ("unknown" if _may_have_been_accepted(exc) else "failed"),
            accepted=bool(accepted),
            tenant_id=tenant_id,
        )
