"""
Data lineage and per-tenant cost attribution (Modules 1 and 5).

The question this module exists to answer
----------------------------------------
A customs authority asks why a shipment was flagged. "The AI said so" is not an
answer a business can give, and neither is a risk score. The answer has to name
the sanctions list record that matched, when that list was pulled, which model
version ran, and which prompt version it ran on -- and all of it has to still be
true three years later, after the prompt has been rewritten and the model
replaced.

So every decision writes a record that is immutable and self-contained enough to
be re-read long after the code that produced it is gone.

Why the sensitive payload is NOT in the audit record
---------------------------------------------------
The obvious design is to put everything in one place: raw model response,
document snapshot, shipment data, all in the immutable audit log, retained for
five years. That design has a defect that only shows up at the worst moment.

`store.update_audit()` and `delete_audit()` raise AuditImmutabilityError on both
backends -- deliberately, because an audit trail you can edit is not one. But a
customer terminating their contract is entitled to have their commercial data
removed, and a supplier's prices and counterparty relationships sitting in an
undeletable log is a problem with no clean exit.

The split here resolves it:

  * audit_log (immutable, retained)   -- ids, hashes, model versions, program
                                         codes, risk scores, token counts. Enough
                                         to prove what happened and reconstruct
                                         the reasoning chain. Contains no
                                         commercial secret and no personal data.
  * cases (deletable)                 -- prompts, raw model replies, the shipment
                                         itself. Cleared by reset() per tenant.
  * GCS via document_store (deletable) -- the original uploaded document.

The audit record points at the other two by id and hash. Deleting them leaves the
audit trail intact and still verifiable: a hash proves the evidence existed and
that a produced copy is genuine, even when the copy itself is gone. What is lost
is the ability to re-read the evidence, which is the correct thing to lose.

State that distinction to a customer's auditor plainly. "We keep the proof and
delete the payload" is defensible. Discovering the difference during an erasure
request is not.
"""

from __future__ import annotations

import hashlib
from typing import Any

from vf_logistics import config as model_config

# Lineage schema version, written onto every record.
#
# Not decoration: a record read in 2029 was written by code nobody has looked at
# for years, and a reader needs to know which shape to expect before parsing it.
# Bump this when a field changes meaning -- adding a field does not need a bump,
# repurposing one does.
LINEAGE_VERSION = 1


def sha256_of(text: str | None) -> str | None:
    """Hex digest, or None for absent text. Never the digest of an empty string,
    which would be a real-looking hash of nothing."""
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cost_usd(model: str | None, input_tokens: int, output_tokens: int) -> float:
    """
    Dollar cost of one model call.

    Priced per model rather than at whatever the registry currently serves,
    because the pipeline deliberately mixes them -- the investigation agent runs
    on Super while fraud and compliance run on Nano, and Super is five times the
    input rate. Pricing everything at the selected model's rate would misreport
    the bill in whichever direction the selection happened to point.
    """
    pricing = model_config.pricing_for(model)
    return (
        (input_tokens or 0) * pricing["input"]
        + (output_tokens or 0) * pricing["output"]
    ) / 1_000_000


def step_lineage(case: dict[str, Any]) -> list[dict[str, Any]]:
    """
    One lineage entry per model call on the case.

    Carries the prompt hash rather than the prompt, and the response hash rather
    than the response. Both hashes are enough to prove later that a produced copy
    is the one that ran, which is what an auditor needs, without the audit log
    holding the customer's commercial data forever.
    """
    entries = []
    for step in case.get("steps") or []:
        input_tokens = int(step.get("input_tokens") or 0)
        output_tokens = int(step.get("output_tokens") or 0)
        model = step.get("model")
        entries.append({
            "agent": step.get("agent"),
            "model": model,
            "prompt_sha256": step.get("prompt_sha256"),
            # Hashed here rather than in envelope() because raw_response has
            # already been truncated to 4000 chars by the time it reaches the
            # step. The hash therefore fingerprints the stored excerpt, not the
            # full reply, and says so.
            "raw_response_excerpt_sha256": sha256_of(step.get("raw_response")),
            "parse_error": bool(step.get("parse_error")),
            "schema_error": bool(step.get("schema_error")),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost_usd(model, input_tokens, output_tokens), 8),
            "latency_ms": step.get("latency_ms"),
            "at": step.get("at"),
        })
    return entries


def source_entity_ids(case: dict[str, Any]) -> list[str]:
    """
    Sanctions list record ids behind the findings on this case.

    This is the field that turns "flagged as high risk" into "matched OFAC SDN
    entry 12345". Deterministic findings from arithmetic -- a freight ratio, a
    value density -- have no list record behind them and contribute nothing here,
    which is correct: there is no external authority to cite for arithmetic.
    """
    ids: list[str] = []
    for finding in (case.get("validation") or {}).get("findings") or []:
        for value in (finding.get("measured") or {}).get("source_entity_ids") or []:
            text = str(value)
            if text not in ids:
                ids.append(text)
    return ids


def build_decision_record(
    case: dict[str, Any],
    action: str,
    *,
    outcome: str | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    """
    The immutable record of one audit decision.

    `actor` names who or what decided. Defaults to the agent, because the common
    case is an automated decision -- but a human release must record the human,
    or the trail cannot distinguish a reviewer's judgement from the agent's.
    """
    from vf_logistics.store import new_id, utcnow

    steps = step_lineage(case)
    validation = case.get("validation") or {}
    reconciled = case.get("reconciliation") or {}
    sanctions = case.get("sanctions_snapshot") or {}

    return {
        "audit_id": new_id("AUD"),
        "lineage_version": LINEAGE_VERSION,
        "at": utcnow(),
        "action": action,
        "actor": actor or "agent",
        "status": "recorded",

        "case_id": case.get("case_id"),
        "shipment_id": (
            (case.get("shipment") or {}).get("shipment_id")
            or case.get("shipment_id")
        ),
        "client_reference": case.get("client_reference"),

        "outcome": outcome or case.get("state"),
        "risk_score": case.get("risk_score"),
        "model_risk": reconciled.get("model_risk"),
        "risk_floor": (
            reconciled.get("risk_floor")
            if reconciled.get("risk_floor") is not None
            else validation.get("risk_floor")
        ),
        "score_disputed": bool(reconciled.get("score_disputed")),

        # Finding codes, not the full findings. The code plus the source entity
        # id is what an auditor cites; the human-readable detail can be
        # regenerated from them and may contain shipment specifics.
        "finding_codes": [
            f.get("code") for f in validation.get("findings") or []
        ],
        "source_entity_ids": source_entity_ids(case),

        # Which list was screened and how stale it was. A verdict is only as good
        # as the list behind it, and a weekly refresh means this can legitimately
        # read 7 -- that belongs in the record rather than in a footnote.
        "sanctions_list_version": sanctions.get("version"),
        "sanctions_synced_at": sanctions.get("synced_at"),
        "sanctions_list_age_days": sanctions.get("age_days"),
        "sanctions_source": sanctions.get("source"),

        "ruleset_version": (case.get("boundary") or {}).get("version"),
        "model_failures": case.get("_model_failure_agents") or [],

        "steps": steps,
        "usage": {
            "agent_calls": len(steps),
            "input_tokens": sum(s["input_tokens"] for s in steps),
            "output_tokens": sum(s["output_tokens"] for s in steps),
            "cost_usd": round(sum(s["cost_usd"] for s in steps), 8),
        },

        # Where the deleted-on-request payload lived. Retained as references so
        # the audit trail stays readable after an erasure: it can still say what
        # evidence existed and prove a produced copy is genuine.
        "evidence_refs": {
            "case_document": case.get("case_id"),
            "document_archive": (case.get("document") or {}).get("archive_path"),
            "note": (
                "Prompts, raw model replies and the shipment record live on the "
                "case document and are deleted with it. The hashes above remain "
                "sufficient to verify a produced copy."
            ),
        },
    }


async def record_decision(
    case: dict[str, Any],
    action: str,
    *,
    outcome: str | None = None,
    actor: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Write the decision record. Returns it, so a caller can surface the id."""
    from vf_logistics.store import get_store

    record = build_decision_record(case, action, outcome=outcome, actor=actor)
    await get_store().add_audit(record, tenant_id=tenant_id)
    return record


# --------------------------------------------------------------------------
# Module 5: per-tenant usage, for billing
# --------------------------------------------------------------------------

async def tenant_usage(
    tenant_id: str,
    since: str | None = None,
    until: str | None = None,
) -> dict[str, Any]:
    """
    Billable usage for one tenant, optionally for one billing period.

    Uses require_tenant() rather than resolve(): an absent tenant here would
    silently attribute spend to "default" and produce an invoice that is
    plausible and wrong, which is worse than an error.

    `since` and `until` bound the window by case creation, half-open. With neither,
    the answer is lifetime-to-date, which is what this returned before a window
    existed and is still the right default for a dashboard.

    `period` is echoed in the response so a caller cannot mistake a lifetime total
    for a month's. That mistake is the reason it is echoed rather than assumed:
    these numbers end up on an invoice, and "which period is this" must be answerable
    from the response alone.

    NOT WINDOWED: `auto_cleared`, `cleared_by_rules` and `cleared_by_ai` come from
    count_by_cleared_by(), which has no time filter. They are lifetime counts even
    inside a windowed call, and that is stated in the response rather than quietly
    tolerated -- see `counts_are_lifetime`. They drive the unit-economics ratio, not
    the invoice, so bounding them was not worth a second index; presenting them as
    period figures would have been wrong.
    """
    from vf_logistics import tenant as tenant_mod
    from vf_logistics.store import get_store

    scope = tenant_mod.require_tenant(tenant_id)
    store = get_store()

    rollups = await store.sum_rollups(tenant_id=scope, since=since, until=until)
    cleared = await store.count_by_cleared_by(tenant_id=scope)

    calls = int(rollups.get("agent_calls") or 0)
    cost = float(rollups.get("estimated_cost_usd") or 0.0)

    return {
        "tenant_id": scope,
        "period": {
            "since": since,
            "until": until,
            # "lifetime" rather than null, so a reader does not have to infer the
            # meaning of two absent bounds.
            "kind": "lifetime" if since is None and until is None else "window",
        },
        "agent_calls": calls,
        "input_tokens": int(rollups.get("total_input_tokens") or 0),
        "output_tokens": int(rollups.get("total_output_tokens") or 0),
        "estimated_cost_usd": round(cost, 6),
        "cost_per_call_usd": round(cost / calls, 8) if calls else 0.0,
        "auto_cleared": cleared.get("total_auto_cleared", 0),
        # The unit-economics number. Cleared by rules costs nothing in tokens, so
        # the ratio is what decides whether a customer is profitable: a tenant
        # whose traffic the deterministic checks handle is nearly free to serve,
        # and one whose traffic all reaches the models is not.
        "cleared_by_rules": cleared.get("rules", 0),
        "cleared_by_ai": cleared.get("ai", 0),
        "counts_are_lifetime": True,
        "avg_latency_ms": rollups.get("avg_latency_ms", 0),
    }
