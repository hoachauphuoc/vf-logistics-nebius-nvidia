"""
Actions the orchestrator takes on behalf of the operator.

This module is the difference between an agent that produces an opinion and an
agent that does the job. Each function performs a real state change, writes an
auditable record, and returns a receipt the case document keeps.

Track: The Taskmaster - Autonomous Workflow Automation
Hackathon: All Things Agentic 2026
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

import executor_client
from store import get_store, new_id, utcnow

# Optional outbound webhook (Slack / Teams / Google Chat / any HTTP endpoint).
# Left unset in the demo: the notify action then records the payload it would
# have sent rather than silently doing nothing.
NOTIFY_WEBHOOK_URL = os.getenv("NOTIFY_WEBHOOK_URL", "").strip()

# Optional Pub/Sub topic that downstream systems subscribe to for decisions.
DECISIONS_TOPIC = os.getenv("DECISIONS_TOPIC", "case-decisions").strip()
PROJECT_ID = os.getenv("PROJECT_ID", "project-93ded24f-21c3-4f1b-a7d")


async def _audit(
    case_id: str, action: str, detail: dict[str, Any], status: str = "done"
) -> dict[str, Any]:
    entry = {
        "audit_id": new_id("audit"),
        "case_id": case_id,
        "action": action,
        "status": status,
        "detail": detail,
        "at": utcnow(),
    }
    await get_store().add_audit(entry)
    return entry


# --------------------------------------------------------------------------
# Shipment disposition
# --------------------------------------------------------------------------

async def release_shipment(case_id: str, shipment_id: str, reason: str) -> dict[str, Any]:
    """Clear the shipment to continue to delivery."""
    return await _audit(
        case_id,
        "release_shipment",
        {
            "shipment_id": shipment_id,
            "reason": reason,
            "disposition": "RELEASED_FOR_DELIVERY",
        },
    )


async def hold_shipment(case_id: str, shipment_id: str, reason: str) -> dict[str, Any]:
    """Freeze the shipment so it cannot move while under investigation."""
    return await _audit(
        case_id,
        "hold_shipment",
        {
            "shipment_id": shipment_id,
            "reason": reason,
            "disposition": "HELD_DO_NOT_SHIP",
        },
    )


async def assign_analyst(case_id: str, queue: str, priority: str) -> dict[str, Any]:
    """Route the case into a human review queue with a priority."""
    return await _audit(
        case_id,
        "assign_analyst",
        {"queue": queue, "priority": priority, "sla_hours": 24 if priority == "HIGH" else 72},
    )


# --------------------------------------------------------------------------
# Regulatory paperwork
# --------------------------------------------------------------------------

async def draft_sar(
    case_id: str, shipment_id: str, narrative: str, exposure: str
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
    )


# --------------------------------------------------------------------------
# Outbound notification
# --------------------------------------------------------------------------

async def notify_webhook(
    case_id: str, title: str, body: str, severity: str
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
        )

    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.post(NOTIFY_WEBHOOK_URL, json=payload)
        return await _audit(
            case_id,
            "notify_webhook",
            {**payload, "http_status": resp.status_code},
            status="done" if resp.is_success else "failed",
        )
    except Exception as exc:  # noqa: BLE001 - a failed alert must not kill the case
        return await _audit(
            case_id, "notify_webhook", {**payload, "error": str(exc)}, status="failed"
        )


# --------------------------------------------------------------------------
# Publish the decision for downstream systems
# --------------------------------------------------------------------------

async def publish_decision(case_id: str, decision: dict[str, Any]) -> dict[str, Any]:
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
    body = {"case_id": case_id, **decision, "at": utcnow()}

    if executor_client.configured():
        outcome = await executor_client.request_protected_action(
            "publish_decision", case_id, body
        )
        return await _audit(
            case_id,
            "publish_decision",
            {**body, "via": "executor identity", "executor": outcome},
            status=outcome.get("status", "failed"),
        )

    return await publish_decision_direct(case_id, body)


async def publish_decision_direct(
    case_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """
    Publish with the ambient identity.

    Called directly in single-service mode, and called by the executor service on
    behalf of the analysis service in the split-identity deployment.
    """
    try:
        import asyncio

        from google.cloud import pubsub_v1

        def _publish() -> str:
            publisher = pubsub_v1.PublisherClient()
            topic = publisher.topic_path(PROJECT_ID, DECISIONS_TOPIC)
            future = publisher.publish(topic, json.dumps(body).encode("utf-8"))
            return future.result(timeout=15)

        message_id = await asyncio.to_thread(_publish)
        return await _audit(
            case_id, "publish_decision", {**body, "message_id": message_id}
        )
    except Exception as exc:  # noqa: BLE001
        return await _audit(
            case_id,
            "publish_decision",
            {**body, "error": f"{type(exc).__name__}: {exc}"},
            status="failed",
        )
