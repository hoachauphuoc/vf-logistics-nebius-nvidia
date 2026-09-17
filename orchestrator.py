"""
Autonomous orchestrator.

This is the Taskmaster layer. It monitors an event stream, drives each shipment
through a conditional multi-agent workflow without human involvement, and
executes real actions on the outcome.

State machine:

  INGESTED
     |  fraud_detection agent
     v
  FRAUD_SCORED
     |-- risk < FRAUD_CLEAR_BELOW ---------------> AUTO_CLEARED   release_shipment
     |
     |-- risk >= FRAUD_CLEAR_BELOW
     v  compliance agent
  COMPLIANCE_SCREENED
     |-- cleared and risk < INVESTIGATE_AT -----> HELD_FOR_REVIEW assign_analyst
     |
     |-- blocked / review required, or risk >= INVESTIGATE_AT
     v  investigation agent (extended thinking)
  INVESTIGATED
     v
  ESCALATED   hold_shipment + draft_sar + notify_webhook

  Any step failing 3 times ends in DEAD_LETTER.

Every transition is persisted before the next one starts, so a case survives an
instance restart and is picked up wherever it left off.

Track: The Taskmaster - Autonomous Workflow Automation
Hackathon: All Things Agentic 2026
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import document_render
import document_store
import governance
import model_armor
import shipper_registry
import tools
import untrusted
import verifier
import config as model_config
from agents import (
    analyze_shipment,
    extract_shipment,
    investigate_case,
    screen_shipment,
)
from store import get_store, new_id, utcnow

# Objects the service writes itself. Notifications for this prefix are ignored,
# or the pipeline would process its own archived output in a loop.
ARCHIVE_PREFIX = "shipping-documents/"

# --- Decision thresholds. Env-overridable so the policy is not buried in code.
FRAUD_CLEAR_BELOW = int(os.getenv("FRAUD_CLEAR_BELOW", "40"))
INVESTIGATE_AT = int(os.getenv("INVESTIGATE_AT", "70"))
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "3"))
POLL_SECONDS = float(os.getenv("POLL_SECONDS", "1.5"))
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "3"))

# How the pipeline gets driven.
#
#   ondemand (default) - no background loop. Cases advance inside request
#     handlers: the Pub/Sub push handler drives its own case to completion, and
#     the dashboard's state poll drains a step at a time. This is the only mode
#     that works with --min-instances=0 and CPU throttling, because Cloud Run
#     freezes the container once a response is sent. It is also the only mode
#     that costs nothing when nobody is using the system.
#
#   poll - the original always-on worker loop. Requires
#     --no-cpu-throttling --min-instances=1, which bills around the clock.
#     Kept for recording a demo where a visibly self-running worker matters.
WORKER_MODE = os.getenv("WORKER_MODE", "ondemand").lower()

# Guards on synchronous draining, so a request can never hang indefinitely.
MAX_CHAIN_STEPS = int(os.getenv("MAX_CHAIN_STEPS", "6"))
CHAIN_BUDGET_SECONDS = float(os.getenv("CHAIN_BUDGET_SECONDS", "120"))

# States the worker will pick up. Terminal states are absent by design.
ACTIONABLE = ("INGESTED", "SPECIALISTS_DONE", "INVESTIGATED")

# States where the agent has finished its own work. Several of these still need
# a person to act, which is what AWAITING_HUMAN tracks: "the agent is done" and
# "the case is closed" are different facts and conflating them is how work gets
# silently dropped.
TERMINAL = (
    "AUTO_CLEARED",
    "HELD_FOR_REVIEW",
    "ESCALATED",
    "PENDING_HUMAN",
    "RELEASED_BY_HUMAN",
    "BLOCKED_BY_HUMAN",
    "DEAD_LETTER",
)

# Cases sitting in a human's queue. Nothing leaves these states without a named
# reviewer making a decision.
AWAITING_HUMAN = ("PENDING_HUMAN", "HELD_FOR_REVIEW", "ESCALATED")


# --------------------------------------------------------------------------
# Event feed
# --------------------------------------------------------------------------

async def emit(case_id: str, kind: str, message: str, **extra: Any) -> None:
    await get_store().add_event(
        {
            "event_id": new_id("evt"),
            "case_id": case_id,
            "kind": kind,
            "message": message,
            "at": utcnow(),
            **extra,
        }
    )


# --------------------------------------------------------------------------
# Ingestion
# --------------------------------------------------------------------------

async def ingest_shipment(
    shipment: dict[str, Any],
    source: str = "event",
    provenance: dict[str, Any] | None = None,
    intake_step: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Accept a shipment event and create the case the worker will pick up.

    Idempotent on shipment_id: re-delivery of the same Pub/Sub message returns
    the existing case instead of starting a second workflow for it.

    `source` records how the shipment arrived (event, simulator, document).
    `provenance` carries the Cloud Storage receipt when it came from a document.
    `intake_step` is the document agent's hop, prepended so the case trace opens
    with the extraction rather than starting at fraud scoring with no record of
    where the data came from.
    """
    store = get_store()
    shipment_id = str(shipment.get("shipment_id") or new_id("SHIP"))
    case_id = f"CASE-{shipment_id}"

    existing = await store.get_case(case_id)
    if existing:
        return existing

    case = {
        "case_id": case_id,
        "shipment_id": shipment_id,
        "shipment": shipment,
        "state": "INGESTED",
        "claimed": False,
        "attempts": 0,
        "not_before": None,
        "risk_score": None,
        "compliance_status": None,
        "source": source,
        "provenance": provenance or {},
        "steps": [intake_step] if intake_step else [],
        "actions": [],        # receipts from tools.py
        "decision": None,
        "created_at": utcnow(),
        "updated_at": utcnow(),
    }
    # Every case must be reviewable against paperwork. A case that arrived as a
    # structured event has none, so the event is rendered into a bill of lading
    # and archived alongside document-sourced cases. It is flagged `generated`
    # so the reviewer is never shown a reconstruction as if it were an original.
    # Document-sourced cases are skipped: ingest_document archives the real file
    # a moment later, and rendering one here would only be overwritten.
    if source != "document" and not case["provenance"].get("uri"):
        rendered = document_render.render_bill_of_lading(shipment, case_id, source)
        if rendered:
            filename = f"{shipment_id}-bill-of-lading.pdf"
            receipt = await document_store.archive(
                rendered, filename, "application/pdf", case_id
            )
            case["provenance"] = {
                **case["provenance"],
                "filename": filename,
                "generated": True,
                "rendered_from": source,
                **receipt,
            }

    await store.put_case(case)
    await emit(
        case_id,
        "ingested",
        f"Shipment {shipment_id} received via {source}, case opened",
        source=source,
    )
    return case


# --------------------------------------------------------------------------
# Document intake
# --------------------------------------------------------------------------

async def ingest_document(
    document_bytes: bytes, filename: str, mime_type: str | None = None
) -> dict[str, Any]:
    """
    Turn an uploaded shipping document into a running case.

    Model Armor screens the document before Gemini sees it, whenever that is
    possible. For a PDF with a text layer, pypdf extracts the text with no model
    involved, Model Armor screens that, and a blocked document is never sent for
    transcription at all - no tokens spent, no model exposed. For a scan there is
    no text layer to pre-screen, so transcription happens first and the result is
    screened before it reaches any downstream agent. The case records which of
    the two it got, because they are not the same assurance.
    """
    pre_screen: dict[str, Any] | None = None
    raw_text = ""

    if (mime_type or "").endswith("pdf") or filename.lower().endswith(".pdf"):
        raw_text, extract_error = model_armor.extract_pdf_text(document_bytes)
        if raw_text:
            pre_screen = await model_armor.screen(raw_text, stage="before_model")
        elif extract_error:
            pre_screen = {
                "provider": "google-cloud-model-armor",
                "stage": "before_model",
                "blocked": False,
                "available": False,
                "detail": f"could not read PDF text layer: {extract_error}",
                "requires_human": True,
            }

    # A document that tried to manipulate the model never reaches the model.
    if pre_screen and pre_screen.get("blocked"):
        shipment = {
            "shipment_id": new_id("BLOCKED"),
            "status": "pending",
            "cargo_description": "not transcribed: document blocked by Model Armor",
        }
        case = await ingest_shipment(
            shipment,
            source="document",
            provenance={"filename": filename},
            intake_step={
                "agent": "model_armor",
                "latency_ms": None,
                "model": "google-cloud-model-armor",
                "parse_error": False,
                "at": utcnow(),
                "result": {
                    "summary": (
                        "Document blocked before any model processing. "
                        f"{pre_screen.get('detail')}"
                    ),
                    "model_armor": pre_screen,
                },
            },
        )
        receipt = await document_store.archive(
            document_bytes, filename, mime_type or "application/pdf", case["case_id"]
        )
        case["provenance"] = {"filename": filename, **receipt}
        case["input_security"] = {"model_armor": pre_screen, "model_invoked": False}
        case["requires_human"] = True
        case["state"] = "PENDING_HUMAN"
        case["proposed_outcome"] = None
        case["gate_denials"] = [{
            "action": "document_intake",
            "reason": "DENIED: Model Armor flagged prompt injection; no model was invoked",
        }]
        await get_store().put_case(case)
        await emit(
            case["case_id"],
            "security",
            f"Model Armor blocked {filename} before any model processing "
            f"({pre_screen.get('confidence') or 'match found'}). No tokens spent.",
            agent="model_armor",
        )
        return {
            "accepted": True,
            "blocked": True,
            "case_id": case["case_id"],
            "state": case["state"],
            "security": case["input_security"],
            "error": None,
        }

    response = await extract_shipment(document_bytes, filename, mime_type)
    raw = response.get("result") or {}

    if response.get("parse_error") or not raw:
        return {
            "accepted": False,
            "error": response.get("error") or "document could not be transcribed",
            "latency_ms": response.get("latency_ms"),
        }

    # The document is attacker-controlled. Enforce the schema before any of this
    # reaches a field the orchestrator reads.
    sanitised = untrusted.sanitise_shipment(raw)
    shipment = sanitised["shipment"]
    notes = sanitised["extraction_notes"]

    screening = untrusted.screen_text(
        untrusted.searchable_text(shipment, notes)
    )

    # No pre-screen was possible (a scan): screen the transcription instead,
    # before it reaches the fraud or compliance agents.
    post_screen = None
    if pre_screen is None:
        post_screen = await model_armor.screen(
            untrusted.searchable_text(shipment, notes), stage="after_transcription"
        )

    shipment.setdefault("status", "pending")
    if str(shipment.get("shipment_id") or "").strip() in ("", "not stated", "N/A"):
        # A document with no readable booking number is still a shipment that
        # needs screening, so give it a synthetic id rather than dropping it.
        shipment["shipment_id"] = new_id("DOC")

    # Supply the one fact the document is not allowed to assert about itself.
    # Deliberately after sanitisation, so the file cannot present its own
    # history, and before the agents run, so they score the enriched record.
    # An unknown or mismatched counterparty writes nothing and leaves the
    # unverified-history floor in verifier.py standing.
    counterparty = shipper_registry.enrich(shipment)

    case_id = f"CASE-{shipment['shipment_id']}"
    receipt = await document_store.archive(
        document_bytes,
        filename,
        response.get("source_mime", "application/pdf"),
        case_id,
    )

    intake_step = {
        "agent": "document_intake",
        "latency_ms": response.get("latency_ms"),
        "model": response.get("model"),
        "input_tokens": response.get("input_tokens", 0),
        "output_tokens": response.get("output_tokens", 0),
        "parse_error": False,
        "at": response.get("at"),
        "result": {
            "summary": (
                f"Transcribed {filename} into a shipment record "
                f"(confidence {sanitised['extraction_confidence']})"
            ),
            "currency": shipment.get("currency"),
            "extraction_notes": notes,
            "extraction_confidence": sanitised["extraction_confidence"],
            "dropped_fields": sanitised["dropped_fields"],
            "forbidden_fields_attempted": sanitised["forbidden_fields_attempted"],
            "injection_screening": screening,
            "model_armor": pre_screen or post_screen,
            "counterparty": counterparty,
        },
    }

    case = await ingest_shipment(
        shipment,
        source="document",
        provenance={"filename": filename, **receipt},
        intake_step=intake_step,
    )

    armor = pre_screen or post_screen or {}
    case["input_security"] = {
        "injection_screening": screening,
        "model_armor": armor,
        "model_invoked": True,
        "screened_before_model": bool(pre_screen and pre_screen.get("available")),
        "dropped_fields": sanitised["dropped_fields"],
        "forbidden_fields_attempted": sanitised["forbidden_fields_attempted"],
    }
    if (
        screening["blocked"]
        or sanitised["forbidden_fields_attempted"]
        or armor.get("blocked")
        or armor.get("requires_human")
    ):
        case["requires_human"] = True
        await get_store().put_case(case)
        reasons = sorted({f["type"] for f in screening["findings"]})
        if armor.get("blocked"):
            reasons.append("Model Armor match")
        if armor.get("requires_human"):
            reasons.append(f"Model Armor unavailable ({armor.get('detail')})")
        if sanitised["forbidden_fields_attempted"]:
            reasons.append("forbidden field override")
        await emit(
            case["case_id"],
            "security",
            "Document flagged for mandatory human review: " + "; ".join(reasons),
            agent="input_security",
        )
    else:
        await get_store().put_case(case)

    await emit(
        case["case_id"],
        "document_extracted",
        f"Read {filename} in {response.get('latency_ms')}ms"
        + (f"; {len(notes)} transcription issue(s) noted" if notes else ""),
        agent="document_intake",
    )

    return {
        "accepted": True,
        "case_id": case["case_id"],
        "shipment_id": case["shipment_id"],
        "state": case["state"],
        "extracted": shipment,
        "archive": receipt,
        "security": case["input_security"],
        "latency_ms": response.get("latency_ms"),
    }


# --------------------------------------------------------------------------
# One step of the workflow
# --------------------------------------------------------------------------

async def _record_step(
    case: dict[str, Any], agent: str, response: dict[str, Any]
) -> dict[str, Any]:
    result = response.get("result") or {}
    case["steps"].append(
        {
            "agent": agent,
            "latency_ms": response.get("latency_ms"),
            "model": response.get("model"),
            "parse_error": response.get("parse_error", False),
            "at": response.get("at"),
            "result": result,
            "input_tokens": response.get("input_tokens", 0),
            "output_tokens": response.get("output_tokens", 0),
        }
    )
    return result


def _as_int(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


async def _decide(
    case: dict[str, Any],
    outcome: str,
    rationale: str,
    actions: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    """
    Record a Decision Pack and attempt to execute it through the gateway.

    This is the seam between analysis and authority. The workflow decides what
    *should* happen and says why; whether any of it actually happens is decided
    by `governance.check` against the published delegation boundary, not here.

    If every protected action is permitted, the outcome becomes official. If any
    is denied, the outcome remains a proposal and the case goes to PENDING_HUMAN
    with the denial reasons attached, so the reviewer sees what the agent wanted
    to do and why it was not allowed to.
    """
    case_id = case["case_id"]

    case["decision_pack"] = {
        "proposed_outcome": outcome,
        "rationale": rationale,
        "proposed_actions": [name for name, _ in actions],
        "packs": synthesise_packs(case),
        "evidence": {
            "effective_risk": case.get("risk_score"),
            "model_risk": case.get("model_risk_score"),
            "risk_floor": (case.get("reconciliation") or {}).get("risk_floor"),
            "compliance_status": case.get("compliance_status"),
            "deterministic_findings": (case.get("validation") or {}).get("findings", []),
        },
        "proposed_at": utcnow(),
    }

    receipts = []
    denials = []
    for index, (name, kwargs) in enumerate(actions):
        receipt = await governance.execute(name, case, **kwargs)
        receipts.append(receipt)
        if receipt.get("status") == "denied":
            denials.append({
                "action": name,
                "reason": receipt.get("detail", {}).get("gate_reason"),
                "human_triggers": receipt.get("detail", {}).get("human_triggers", []),
            })
            # Stop the pack here instead of running the rest of it. Every action
            # after the substantive one is conditional on the outcome becoming
            # official, and publish_decision is always last - so letting the loop
            # continue announced `outcome: AUTO_CLEARED` on the case-decisions
            # topic for a shipment the boundary had just refused to release and
            # which was on its way to a human. A subscriber had no way to tell
            # that apart from a real release. The remaining actions are recorded
            # as skipped rather than dropped, so the trace says what was not
            # attempted and why.
            for skipped, _ in actions[index + 1:]:
                receipts.append({
                    "action": skipped,
                    "case_id": case_id,
                    "at": utcnow(),
                    "status": "skipped",
                    "detail": {"reason": f"not attempted: {name} was denied"},
                })
            break

    case["actions"].extend(receipts)

    if denials:
        case["state"] = "PENDING_HUMAN"
        case["proposed_outcome"] = outcome
        case["gate_denials"] = denials
        case["decision"] = None  # nothing is official until a human acts
        await emit(
            case_id,
            "gate_denied",
            f"Proposed {outcome} not executed: " + denials[0]["reason"],
            outcome="PENDING_HUMAN",
        )
        return case

    case["decision"] = {
        "outcome": outcome,
        "rationale": rationale,
        "executed_under_boundary": next(
            (
                r.get("detail", {}).get("boundary_version")
                for r in receipts
                if r.get("detail", {}).get("boundary_version") is not None
            ),
            None,
        ),
    }
    case["state"] = outcome
    await emit(case_id, "decision", rationale[:180], outcome=outcome)
    return case


async def advance(case: dict[str, Any]) -> dict[str, Any]:
    """Run exactly one transition for a case and persist the outcome."""
    store = get_store()
    state = case["state"]
    case_id = case["case_id"]

    if state == "INGESTED":
        # The two screening disciplines are independent, so they run concurrently.
        # Sequentially this was two round trips of roughly seven seconds each;
        # in parallel a case reaches a decision in about half the wall time for
        # the same number of model calls.
        await emit(
            case_id,
            "agent_start",
            "Fraud detection and compliance screening running in parallel",
            agent="specialists",
        )

        fraud_resp, compliance_resp = await asyncio.gather(
            analyze_shipment(case["shipment"]),
            screen_shipment(case["shipment"]),
        )

        fraud_result = await _record_step(case, "fraud_detection", fraud_resp)
        compliance_result = await _record_step(case, "compliance", compliance_resp)

        # Deterministic grounding validation. The agents' scores are claims; this
        # is the part of the system that checks them against arithmetic and
        # code-resident lists before anything acts on them.
        validation = verifier.validate(case["shipment"])
        reconciled = verifier.reconcile(fraud_result.get("risk_score"), validation)

        case["validation"] = validation
        case["reconciliation"] = reconciled
        case["model_risk_score"] = reconciled["model_risk"]
        case["risk_score"] = reconciled["effective_risk"]
        case["risk_level"] = fraud_result.get("risk_level") or "UNKNOWN"
        case["compliance_status"] = compliance_result.get("compliance_status") or "UNKNOWN"
        case["compliance_score"] = _as_int(compliance_result.get("compliance_score"), 50)
        case["state"] = "SPECIALISTS_DONE"

        if reconciled["source"] == "deterministic floor":
            await emit(
                case_id,
                "veto",
                f"Model scored {reconciled['model_risk']}; deterministic floor is "
                f"{reconciled['risk_floor']} from {validation['finding_count']} "
                f"hard finding(s). Effective risk {reconciled['effective_risk']}.",
                agent="verifier",
                risk_score=reconciled["effective_risk"],
            )
        else:
            await emit(
                case_id,
                "agent_done",
                f"Fraud {case['risk_score']}/100, compliance "
                f"{case['compliance_status']} "
                f"({fraud_resp.get('latency_ms')}ms / "
                f"{compliance_resp.get('latency_ms')}ms in parallel); "
                f"deterministic checks agree",
                agent="specialists",
                risk_score=case["risk_score"],
            )

    elif state == "SPECIALISTS_DONE":
        risk = case.get("risk_score") or 0
        reconciled = case.get("reconciliation") or {}
        may_auto_clear = reconciled.get("auto_clear_permitted", True)
        status = (case.get("compliance_status") or "").upper()

        clean = (
            risk < FRAUD_CLEAR_BELOW
            and may_auto_clear
            and status not in ("BLOCKED", "REVIEW_REQUIRED")
        )
        needs_investigation = (
            status in ("BLOCKED", "REVIEW_REQUIRED") or risk >= INVESTIGATE_AT
        )

        if clean:
            case = await _decide(
                case,
                "AUTO_CLEARED",
                f"Fraud risk {risk}/100 is below the {FRAUD_CLEAR_BELOW} "
                f"threshold, compliance returned {case.get('compliance_status')}, "
                f"and deterministic validation raised nothing.",
                [
                    ("release_shipment", {
                        "shipment_id": case["shipment_id"],
                        "reason": f"Fraud risk {risk} below threshold "
                                  f"{FRAUD_CLEAR_BELOW}, no deterministic findings",
                    }),
                    ("publish_decision", {
                        "decision": {"outcome": "AUTO_CLEARED", "effective_risk": risk}
                    }),
                ],
            )
        elif not needs_investigation:
            case = await _decide(
                case,
                "HELD_FOR_REVIEW",
                f"Compliance cleared the shipment but effective risk {risk}/100 is "
                f"above the auto-clear threshold, so a human reviewer is assigned.",
                [
                    ("assign_analyst", {"queue": "trade-review", "priority": "NORMAL"}),
                    ("publish_decision", {
                        "decision": {"outcome": "HELD_FOR_REVIEW", "effective_risk": risk}
                    }),
                ],
            )
        else:
            await emit(
                case_id,
                "agent_start",
                f"Compliance {status} at risk {risk}, opening deep investigation "
                "with extended thinking",
                agent="investigation",
            )
            response = await investigate_case(_investigation_payload(case))
            result = await _record_step(case, "investigation", response)

            case["investigation"] = result
            case["state"] = "INVESTIGATED"
            await emit(
                case_id,
                "agent_done",
                f"Investigation complete in {response.get('latency_ms')}ms: "
                f"{result.get('fraud_pattern') or 'pattern inconclusive'}",
                agent="investigation",
            )

    elif state == "INVESTIGATED":
        inv = case.get("investigation") or {}
        narrative = str(inv.get("summary") or "No narrative returned.")
        exposure = str(inv.get("exposure_estimate") or "unquantified")

        # Check the figure the agent put on the case before it reaches a filing.
        exposure_flag = verifier.check_exposure_claim(case["shipment"], inv)
        if exposure_flag:
            case.setdefault("validation", {}).setdefault("findings", []).append(
                exposure_flag
            )
            await emit(
                case_id,
                "veto",
                exposure_flag["detail"],
                agent="verifier",
            )

        case = await _decide(
            case,
            "ESCALATED",
            f"Investigation identified "
            f"{inv.get('fraud_pattern') or 'suspicious activity'} with estimated "
            f"exposure {exposure}. Shipment held, SAR drafted for human signoff.",
            [
                ("hold_shipment", {
                    "shipment_id": case["shipment_id"],
                    "reason": "Escalated after deep investigation",
                }),
                ("draft_sar", {
                    "shipment_id": case["shipment_id"],
                    "narrative": narrative,
                    "exposure": exposure,
                }),
                ("notify_webhook", {
                    "title": f"Escalation: {case['shipment_id']}",
                    "body": narrative,
                    "severity": "CRITICAL",
                }),
                ("assign_analyst", {"queue": "financial-crime", "priority": "HIGH"}),
                ("publish_decision", {
                    "decision": {
                        "outcome": "ESCALATED",
                        "fraud_pattern": inv.get("fraud_pattern"),
                        "exposure_estimate": exposure,
                    }
                }),
            ],
        )

    case["updated_at"] = utcnow()
    case["claimed"] = False
    await store.put_case(case)
    return case


def _investigation_payload(case: dict[str, Any]) -> dict[str, Any]:
    """Build the nested case envelope the investigation agent expects."""
    shipment = case.get("shipment", {})
    fraud_step = next(
        (s for s in case.get("steps", []) if s["agent"] == "fraud_detection"), {}
    )
    compliance_step = next(
        (s for s in case.get("steps", []) if s["agent"] == "compliance"), {}
    )
    fraud_result = fraud_step.get("result", {})
    compliance_result = compliance_step.get("result", {})

    triggers = []
    for flag in fraud_result.get("flags", []) or []:
        triggers.append(flag if isinstance(flag, str) else str(flag.get("description") or flag))
    for factor in compliance_result.get("risk_factors", []) or []:
        triggers.append(str(factor))

    return {
        "case_id": case["case_id"],
        "trigger_reason": "; ".join(triggers[:6]) or "Elevated fraud and compliance risk",
        "risk_score": case.get("risk_score"),
        "primary_shipment": shipment,
        "primary_entity": {
            "name": shipment.get("shipper_name"),
            "company": shipment.get("shipper_company"),
            "country": shipment.get("shipper_country"),
            "tax_id": shipment.get("shipper_tax_id"),
            "transaction_count": shipment.get("shipper_tx_count"),
        },
        "historical_alerts": compliance_result.get("regulatory_issues", []),
        "total_volume": shipment.get("declared_value"),
        "avg_transaction": shipment.get("avg_route_cost"),
        "anomaly_count_30d": len(fraud_result.get("flags", []) or []),
    }


async def sweep_bucket(prefix: str, limit: int) -> dict[str, Any]:
    """
    Process documents already on the stage.

    Objects whose case already exists are skipped rather than reprocessed, which
    is what makes repeated sweeps safe to run.
    """
    names = await document_store.list_objects(prefix, limit * 3)
    store = get_store()

    processed: list[dict[str, Any]] = []
    skipped: list[str] = []

    for name in names:
        if len(processed) >= limit:
            break
        if name.startswith(ARCHIVE_PREFIX) or name.endswith("/"):
            continue

        marker = await store.get_case(f"CASE-DOCOBJ-{_object_key(name)}")
        if marker:
            skipped.append(name)
            continue

        result = await ingest_from_storage(document_store.BUCKET, name)
        processed.append({
            "object": name,
            "case_id": result.get("case_id"),
            "blocked": result.get("blocked", False),
            "accepted": result.get("accepted", False),
        })

    return {
        "prefix": prefix,
        "processed": processed,
        "processed_count": len(processed),
        "skipped_already_seen": skipped,
    }


def _object_key(name: str) -> str:
    """A stable, id-safe key for an object path."""
    import hashlib

    return hashlib.sha1(name.encode("utf-8")).hexdigest()[:16]


async def ingest_from_storage(bucket: str, name: str) -> dict[str, Any]:
    """
    Read an object off the stage and run it through document intake.

    A marker case is written under the object's hash so a repeated notification
    or sweep does not process the same file twice. Pub/Sub delivers at least
    once, so this is not optional.
    """
    store = get_store()
    marker_id = f"CASE-DOCOBJ-{_object_key(name)}"

    existing = await store.get_case(marker_id)
    if existing:
        return {
            "accepted": False,
            "duplicate": True,
            "case_id": existing.get("linked_case_id") or marker_id,
            "reason": f"gs://{bucket}/{name} has already been processed",
        }

    data, content_type = await document_store.fetch(f"gs://{bucket}/{name}")
    if data is None:
        return {"accepted": False, "error": f"could not read gs://{bucket}/{name}"}

    filename = name.rsplit("/", 1)[-1]
    result = await ingest_document(data, filename, content_type)

    # Write the marker only after intake, so a failed read can be retried.
    await store.put_case({
        "case_id": marker_id,
        "shipment_id": marker_id,
        "state": "OBJECT_PROCESSED",
        "claimed": False,
        "attempts": 0,
        "not_before": None,
        "is_marker": True,
        "object": f"gs://{bucket}/{name}",
        "linked_case_id": result.get("case_id"),
        "steps": [],
        "actions": [],
        "created_at": utcnow(),
        "updated_at": utcnow(),
    })

    result["source_object"] = f"gs://{bucket}/{name}"
    return result


# --------------------------------------------------------------------------
# Human review
# --------------------------------------------------------------------------

HUMAN_ACTIONS = {
    "release": ("RELEASED_BY_HUMAN", "release_shipment"),
    "block": ("BLOCKED_BY_HUMAN", "hold_shipment"),
    "request_info": ("PENDING_HUMAN", None),
}


async def human_decide(
    case_id: str, action: str, reviewer: str, note: str
) -> dict[str, Any]:
    """
    Apply a named human's decision to a case.

    Deliberately not routed through the delegation boundary: a boundary
    constrains what the *agent* may do on its own, and a human reviewer is the
    authority the boundary derives from. What the human cannot do is act
    anonymously - `reviewer` is required, and a note is required for anything
    other than a plain release, because a refusal that nobody has to justify is
    not a control.
    """
    store = get_store()

    if action not in HUMAN_ACTIONS:
        return {"ok": False, "error": f"unknown action '{action}'"}
    if not reviewer.strip():
        return {"ok": False, "error": "reviewer is required"}
    if action != "release" and not note.strip():
        return {"ok": False, "error": f"a note is required when action is '{action}'"}

    case = await store.get_case(case_id)
    if not case:
        return {"ok": False, "error": "case not found"}
    if case.get("state") not in AWAITING_HUMAN:
        return {
            "ok": False,
            "error": f"case is in state {case.get('state')}, which is not awaiting review",
        }

    new_state, tool_action = HUMAN_ACTIONS[action]

    receipts = []
    if tool_action == "release_shipment":
        receipts.append(await tools.release_shipment(
            case_id, case["shipment_id"], f"Released by {reviewer}: {note or 'no note'}"
        ))
    elif tool_action == "hold_shipment":
        receipts.append(await tools.hold_shipment(
            case_id, case["shipment_id"], f"Blocked by {reviewer}: {note}"
        ))

    # Any SAR draft on this case now carries a signature.
    signed = None
    for existing in case.get("actions", []):
        if existing.get("action") == "draft_sar" and existing.get("status") == "done":
            existing.setdefault("detail", {})["requires_human_signoff"] = False
            existing["detail"]["signed_by"] = reviewer
            existing["detail"]["signed_at"] = utcnow()
            signed = existing["detail"].get("reference")

    review = {
        "action": action,
        "reviewer": reviewer,
        "note": note,
        "at": utcnow(),
        "state_before": case.get("state"),
        "state_after": new_state,
        "agent_proposed": case.get("proposed_outcome") or (
            (case.get("decision") or {}).get("outcome")
        ),
        "sar_signed": signed,
    }

    case.setdefault("reviews", []).append(review)
    case["actions"].extend(receipts)
    case["state"] = new_state
    case["updated_at"] = utcnow()
    case["claimed"] = False

    if action != "request_info":
        case["decision"] = {
            "outcome": new_state,
            "rationale": f"{reviewer} chose to {action}. {note}".strip(),
            "decided_by": "human",
        }

    await store.put_case(case)
    await store.add_audit({
        "audit_id": new_id("audit"),
        "case_id": case_id,
        "action": f"human_{action}",
        "status": "done",
        "detail": review,
        "at": utcnow(),
    })
    await emit(
        case_id,
        "human_decision",
        f"{reviewer} chose {action}"
        + (f" (agent had proposed {review['agent_proposed']})"
           if review["agent_proposed"] else ""),
        outcome=new_state,
    )

    return {"ok": True, "case_id": case_id, "state": new_state, "review": review}


async def review_queue(limit: int = 40) -> list[dict[str, Any]]:
    """Cases waiting on a person, newest first."""
    cases = await get_store().list_cases(120)
    return [c for c in cases if c.get("state") in AWAITING_HUMAN][:limit]


def synthesise_packs(case: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Collapse everything known about a case into four Decision Packs.

    A reviewer does not want six raw agent payloads and a validation blob; they
    want to know what each discipline concluded and where the disagreements are.
    The synthesiser is deliberately deterministic - it arranges evidence the
    agents and the verifier already produced rather than asking a model to
    summarise its own colleagues, which would add a fresh opportunity to
    confabulate at exactly the point a human is about to rely on it.
    """
    steps = {s["agent"]: s.get("result", {}) for s in case.get("steps", [])}
    fraud = steps.get("fraud_detection", {})
    compliance = steps.get("compliance", {})
    investigation = steps.get("investigation", {})
    intake = steps.get("document_intake", {})

    validation = case.get("validation") or {}
    reconciliation = case.get("reconciliation") or {}
    findings = validation.get("findings", [])

    def codes(*prefixes: str) -> list[dict[str, Any]]:
        return [
            f for f in findings
            if any(f.get("code", "").startswith(p) for p in prefixes)
        ]

    return [
        {
            "pack": "Integrity and pricing",
            "headline": (
                f"Effective risk {case.get('risk_score')}/100"
                + (f", agent said {reconciliation.get('model_risk')}"
                   if reconciliation.get("score_disputed") else "")
            ),
            "agent_view": {
                "risk_score": fraud.get("risk_score"),
                "risk_level": fraud.get("risk_level"),
                "flags": fraud.get("flags", []),
            },
            "deterministic_view": codes("FREIGHT", "VALUE_DENSITY"),
            "disagreement": reconciliation.get("score_disputed", False),
        },
        {
            "pack": "Sanctions and trade compliance",
            "headline": (
                f"{case.get('compliance_status') or 'not screened'}"
                + (f", score {case.get('compliance_score')}/100"
                   if case.get("compliance_score") is not None else "")
            ),
            "agent_view": {
                "compliance_status": compliance.get("compliance_status"),
                "sanctions_hits": compliance.get("sanctions_hits", []),
                "regulatory_issues": compliance.get("regulatory_issues", []),
            },
            "deterministic_view": codes("DUAL_USE", "HS_CODE", "HIGH_RISK", "MULTIPLE_DIVERSION", "ROUTE_"),
            "disagreement": False,
        },
        {
            "pack": "Exposure and counterparty",
            "headline": (
                investigation.get("exposure_estimate")
                or f"declared value {case.get('shipment', {}).get('declared_value')} USD"
            ),
            "agent_view": {
                "fraud_pattern": investigation.get("fraud_pattern"),
                "exposure_estimate": investigation.get("exposure_estimate"),
                "summary": investigation.get("summary"),
            },
            "deterministic_view": codes("SHIPPER", "RECENTLY_REGISTERED", "EXPOSURE_CLAIM"),
            "disagreement": any(
                f.get("code") == "EXPOSURE_CLAIM_UNSUPPORTED" for f in findings
            ),
        },
        {
            "pack": "Provenance and input safety",
            "headline": (
                "document blocked before model processing"
                if not (case.get("input_security") or {}).get("model_invoked", True)
                else f"source: {case.get('source', 'event')}"
            ),
            "agent_view": {
                "extraction_confidence": intake.get("extraction_confidence"),
                "extraction_notes": intake.get("extraction_notes", []),
            },
            "deterministic_view": [
                {
                    "code": "INPUT_SECURITY",
                    "severity": (
                        "CRITICAL"
                        if ((case.get("input_security") or {}).get("model_armor") or {}).get("blocked")
                        else "MEDIUM"
                    ),
                    "detail": (
                        (((case.get("input_security") or {}).get("model_armor") or {}).get("detail"))
                        or "no input security findings"
                    ),
                }
            ] + codes("MISSING", "SHIPPER_TAX_ID", "CARGO_DESCRIPTION"),
            "disagreement": False,
        },
    ]


# --------------------------------------------------------------------------
# Failure handling
# --------------------------------------------------------------------------

async def _fail(case: dict[str, Any], exc: Exception) -> None:
    """Back off and retry, or dead-letter after MAX_ATTEMPTS."""
    store = get_store()
    case["attempts"] = case.get("attempts", 0) + 1
    case["last_error"] = f"{type(exc).__name__}: {exc}"
    case["claimed"] = False
    case["updated_at"] = utcnow()

    if case["attempts"] >= MAX_ATTEMPTS:
        case["state"] = "DEAD_LETTER"
        await store.put_case(case)
        await emit(
            case["case_id"],
            "dead_letter",
            f"Gave up after {case['attempts']} attempts: {case['last_error']}",
        )
        return

    # 5s, 10s, 20s. The earlier 2s base burned all three attempts inside a few
    # seconds, which dead-lettered cases faster than any transient fault could
    # clear.
    backoff = 5 * (2 ** (case["attempts"] - 1))
    from datetime import datetime, timedelta, timezone

    case["not_before"] = (
        datetime.now(timezone.utc) + timedelta(seconds=backoff)
    ).isoformat()
    await store.put_case(case)
    await emit(
        case["case_id"],
        "retry",
        f"Attempt {case['attempts']} failed, retrying in {backoff}s: {case['last_error']}",
    )


# --------------------------------------------------------------------------
# Worker
# --------------------------------------------------------------------------

_worker_task = None
_stats: dict[str, Any] = {
    "started_at": None,
    "ticks": 0,
    "advanced": 0,
    "failed": 0,
    "last_tick_error": None,
    "tick_errors": 0,
}


async def tick() -> int:
    """
    Advance up to MAX_CONCURRENT cases by one step each.

    Also usable as an HTTP-driven fallback if the always-on background loop is
    ever unavailable, which is why it is a plain awaitable returning a count.
    """
    _stats["ticks"] += 1
    claimed = []
    store = get_store()

    for _ in range(MAX_CONCURRENT):
        case = await store.claim_next_pending(ACTIONABLE)
        if not case:
            break
        claimed.append(case)

    if not claimed:
        return 0

    async def _run(case: dict[str, Any]) -> None:
        try:
            await advance(case)
            _stats["advanced"] += 1
        except Exception as exc:  # noqa: BLE001 - one bad case must not stop the worker
            _stats["failed"] += 1
            logging.exception("case %s failed to advance", case.get("case_id"))
            await _fail(case, exc)

    await asyncio.gather(*(_run(c) for c in claimed))
    return len(claimed)


async def advance_until_terminal(case: dict[str, Any]) -> dict[str, Any]:
    """
    Drive one case from wherever it is to a terminal state, in this request.

    This is what makes scale-to-zero viable: a single Pub/Sub delivery wakes the
    container once and the whole workflow completes before the response is sent,
    instead of needing one wake-up per agent hop.

    Bounded twice over - by step count and by wall clock - so a pathological
    case cannot hold a request open forever. A case that runs out of budget is
    simply left where it is, and the next trigger picks it up.
    """
    started = time.monotonic()
    steps = 0

    while (
        case.get("state") in ACTIONABLE
        and steps < MAX_CHAIN_STEPS
        and time.monotonic() - started < CHAIN_BUDGET_SECONDS
    ):
        try:
            case = await advance(case)
            _stats["advanced"] += 1
        except Exception as exc:  # noqa: BLE001
            _stats["failed"] += 1
            logging.exception("case %s failed to advance", case.get("case_id"))
            await _fail(case, exc)
            break
        steps += 1

    return case


async def drain(max_cases: int = 1) -> dict[str, Any]:
    """
    Claim up to `max_cases` pending cases and run each to completion.

    Used by the request-driven mode. Kept deliberately small by default: the
    dashboard calls this on every poll, and a large batch would make a single
    poll take a minute.
    """
    store = get_store()
    handled: list[str] = []

    for _ in range(max_cases):
        case = await store.claim_next_pending(ACTIONABLE)
        if not case:
            break
        done = await advance_until_terminal(case)
        handled.append(done.get("case_id", "?"))

    return {"drained": len(handled), "case_ids": handled}


async def worker_loop() -> None:
    """
    The background loop. Runs for the lifetime of the container.

    Errors are recorded on _stats rather than only suppressed: a loop that
    silently swallows failures looks identical to a loop with nothing to do,
    which makes a stalled pipeline impossible to diagnose from outside.
    """
    _stats["started_at"] = utcnow()
    while True:
        try:
            moved = await tick()
        except Exception as exc:  # noqa: BLE001 - never let the loop die
            moved = 0
            _stats["tick_errors"] += 1
            _stats["last_tick_error"] = f"{type(exc).__name__}: {exc}"
            logging.exception("orchestrator tick failed")
        await asyncio.sleep(0.1 if moved else POLL_SECONDS)


def start_worker(loop: asyncio.AbstractEventLoop) -> None:
    """
    Schedule the background loop, but only in poll mode.

    run_coroutine_threadsafe is used rather than loop.create_task because this
    is called from the Flask/gunicorn thread, and create_task is not
    thread-safe. It also queues correctly if the target loop has not finished
    starting yet.
    """
    global _worker_task
    if WORKER_MODE != "poll":
        return
    if _worker_task and not _worker_task.done():
        return
    _worker_task = asyncio.run_coroutine_threadsafe(worker_loop(), loop)


def worker_status() -> dict[str, Any]:
    running = bool(_worker_task and not _worker_task.done())
    return {
        "mode": WORKER_MODE,
        "running": running,
        "drives_pipeline": (
            "background loop" if WORKER_MODE == "poll" else "request handlers"
        ),
        **_stats,
        "thresholds": {
            "fraud_clear_below": FRAUD_CLEAR_BELOW,
            "investigate_at": INVESTIGATE_AT,
            "max_attempts": MAX_ATTEMPTS,
            "max_concurrent": MAX_CONCURRENT,
            "max_chain_steps": MAX_CHAIN_STEPS,
        },
    }


# --------------------------------------------------------------------------
# Dashboard projection
# --------------------------------------------------------------------------

async def snapshot(limit: int = 60) -> dict[str, Any]:
    store = get_store()
    all_cases, events, audit = await asyncio.gather(
        store.list_cases(limit + 40), store.list_events(80), store.list_audit(80)
    )

    # Storage dedupe markers are bookkeeping, not cases. They must not appear on
    # the board or be counted in the metrics.
    cases = [c for c in all_cases if not c.get("is_marker")][:limit]

    counts: dict[str, int] = {}
    latencies: list[int] = []
    total_input_tokens = 0
    total_output_tokens = 0
    estimated_cost = 0.0
    tokens_by_agent: dict[str, dict[str, int]] = {}
    
    for case in cases:
        counts[case["state"]] = counts.get(case["state"], 0) + 1
        for step in case.get("steps", []) or []:
            if isinstance(step.get("latency_ms"), int):
                latencies.append(step["latency_ms"])
            # Aggregate token usage
            input_t = step.get("input_tokens", 0) or 0
            output_t = step.get("output_tokens", 0) or 0
            total_input_tokens += input_t
            total_output_tokens += output_t

            # Price each step at its own model's rate. Investigation runs on
            # Flash-Lite at half the Flash rate, so a single project-wide rate
            # would overstate the bill and hide the reason for the split.
            step_pricing = model_config.pricing_for(step.get("model"))
            estimated_cost += (
                input_t * step_pricing["input"] + output_t * step_pricing["output"]
            ) / 1_000_000
            
            agent = step.get("agent", "unknown")
            if agent not in tokens_by_agent:
                tokens_by_agent[agent] = {"calls": 0, "input": 0, "output": 0}
            tokens_by_agent[agent]["calls"] += 1
            tokens_by_agent[agent]["input"] += input_t
            tokens_by_agent[agent]["output"] += output_t

    in_flight = sum(1 for c in cases if c["state"] not in TERMINAL)
    awaiting_human = sum(1 for c in cases if c["state"] in AWAITING_HUMAN)

    readiness = await governance.agent_readiness()

    estimated_cost = round(estimated_cost, 6)

    return {
        "cases": cases,
        "events": events,
        "audit": audit,
        "counts": counts,
        "in_flight": in_flight,
        "awaiting_human": awaiting_human,
        "agent": readiness,
        "agent_calls": len(latencies),
        "avg_latency_ms": int(sum(latencies) / len(latencies)) if latencies else 0,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "tokens_by_agent": tokens_by_agent,
        "estimated_cost_usd": estimated_cost,
        "worker": worker_status(),
        "at": utcnow(),
    }
