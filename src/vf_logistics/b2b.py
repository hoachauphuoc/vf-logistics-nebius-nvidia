"""
Translation between the internal case document and the published B2B contract.

Kept out of app.py on purpose. The mapping is where a contract quietly breaks --
an internal state gets renamed, a field moves, and a customer's integration
starts receiving something it was not built for. A function is testable; the same
logic spread through a route handler is not.

The narrowing is the point
--------------------------
The internal state machine has ten states, several of them intermediate. An ERP
should not have to know that SPECIALISTS_DONE exists, and must not break when we
add a state or rename one. So the published vocabulary is five outcomes, and this
module owns the mapping. An internal state with no mapping becomes ERROR rather
than being passed through, because leaking an unmapped string into a customer's
switch statement is worse than telling them something went wrong.
"""

from __future__ import annotations

from typing import Any

from vf_logistics import orchestrator
from vf_logistics.schemas import (
    AuditFinding,
    AuditLineage,
    AuditOutcome,
    AuditUsage,
    ComplianceAuditResponse,
)

# Internal state -> published outcome.
#
# RELEASED_BY_HUMAN and AUTO_CLEARED both map to CLEARED: one was released by a
# reviewer and the other by the agent within its delegated authority, and from
# the integrator's side both mean the same operational thing -- the shipment may
# move. Who authorised it is in the case trace and the audit log, where an
# auditor looks; it is not a branch an ERP needs.
#
# ESCALATED maps to PENDING_HUMAN rather than to an outcome of its own. It means a
# person is handling it, which is the same instruction to a calling system.
_OUTCOME_MAP: dict[str, AuditOutcome] = {
    "AUTO_CLEARED": AuditOutcome.CLEARED,
    "RELEASED_BY_HUMAN": AuditOutcome.CLEARED,
    "BLOCKED_BY_HUMAN": AuditOutcome.BLOCKED,
    "HELD_FOR_REVIEW": AuditOutcome.HELD_FOR_REVIEW,
    "PENDING_HUMAN": AuditOutcome.PENDING_HUMAN,
    "ESCALATED": AuditOutcome.PENDING_HUMAN,
    "DEAD_LETTER": AuditOutcome.ERROR,
}

# Taken from the orchestrator rather than restated here. Restating them is how
# this module would drift from the state machine, and it already did: an earlier
# version of this file guessed the names from schemas.CaseState, which declares
# INTAKE and PENDING_ANALYSIS -- states that do not exist -- and omits INGESTED,
# which every new case starts in. The result was that a live case read as
# complete and published as ERROR. Importing the real tuple makes that class of
# mistake impossible, and assert_states_are_mapped() below catches the rest.
_IN_FLIGHT = frozenset(orchestrator.ACTIONABLE)

_HUMAN_REVIEW_OUTCOMES = frozenset({
    AuditOutcome.HELD_FOR_REVIEW, AuditOutcome.PENDING_HUMAN,
})


def unmapped_terminal_states() -> set[str]:
    """
    Terminal states with no published outcome.

    Asserted in the test suite. A state added to the orchestrator without a
    mapping here would reach customers as ERROR, which is a silent contract
    break -- the shipment was decided, and we told the integrator we failed.
    """
    return set(orchestrator.TERMINAL) - set(_OUTCOME_MAP)


def audit_id_for(case_id: str) -> str:
    """
    Derive the audit id from the case id.

    Derived rather than randomly generated so it is stable across replays: an
    integrator retrying a timed-out POST must receive the same audit_id, not a
    new one pointing at the same case.
    """
    return f"AUD-{case_id}"


def is_complete(case: dict[str, Any]) -> bool:
    return str(case.get("state") or "") not in _IN_FLIGHT


def outcome_for(case: dict[str, Any]) -> AuditOutcome:
    state = str(case.get("state") or "")
    if state in _IN_FLIGHT:
        return AuditOutcome.PENDING_HUMAN
    return _OUTCOME_MAP.get(state, AuditOutcome.ERROR)


def _review_reason(case: dict[str, Any], outcome: AuditOutcome) -> str | None:
    """
    Why a human has this shipment, in words an integrator can act on.

    Ordered by how actionable each cause is. A model that failed its schema is
    named first because it is the only cause the integrator might mistake for a
    risk signal -- it is not one; it means a check did not run and nobody should
    read the absence of a finding as a clean result.
    """
    if outcome not in _HUMAN_REVIEW_OUTCOMES:
        return None

    failed = case.get("_model_failure_agents") or []
    if failed:
        return (
            f"Model output from {', '.join(failed)} could not be validated after "
            f"retries. This is not a risk finding: those checks did not complete, "
            f"so their silence is not a clearance."
        )

    denials = case.get("gate_denials") or []
    if denials:
        reason = denials[0].get("reason") or "governance gate denied the action"
        return f"Agent authority insufficient: {reason}"

    findings = (case.get("validation") or {}).get("findings") or []
    serious = [
        f for f in findings if f.get("severity") in ("HIGH", "CRITICAL")
    ]
    if serious:
        return (
            f"{len(serious)} high-severity deterministic finding(s): "
            + "; ".join(f["code"] for f in serious[:4])
        )

    risk = case.get("risk_score")
    return f"Effective risk {risk} is above the automatic clearance threshold"


def _findings(case: dict[str, Any]) -> list[AuditFinding]:
    out = []
    for f in (case.get("validation") or {}).get("findings") or []:
        measured = f.get("measured") or {}
        out.append(AuditFinding(
            code=str(f.get("code") or "UNKNOWN"),
            severity=str(f.get("severity") or "INFO"),
            detail=str(f.get("detail") or ""),
            floor=int(f.get("floor") or 0),
            # Populated by the sanctions screening check. Empty for findings
            # derived from arithmetic, which have no list record behind them.
            source_entity_ids=[
                str(x) for x in (measured.get("source_entity_ids") or [])
            ],
            # .get, not `or []`: check_zero_day writes this key only when a
            # search produced results, and the absence of the key is the record
            # that no search ran. Defaulting to an empty list here would turn
            # "not searched" into "searched, found nothing" -- the same
            # conflation the searched/risk_found split exists to prevent, and it
            # would be reintroduced at the last hop before the customer sees it.
            evidence_urls=(
                [str(u) for u in measured["evidence_urls"]]
                if "evidence_urls" in measured
                else None
            ),
        ))
    return out


def _lineage(case: dict[str, Any]) -> AuditLineage:
    """
    Assemble the provenance from the steps the orchestrator recorded.

    prompt_hashes and model_versions are keyed by agent, so a verdict can be
    traced to the exact prompt version and model that produced each part of it.
    Both come off the steps rather than being recomputed, because recomputing
    would fingerprint today's prompt rather than the one that actually ran.
    """
    prompt_hashes: dict[str, str] = {}
    model_versions: dict[str, str] = {}
    for step in case.get("steps") or []:
        agent = str(step.get("agent") or "")
        if not agent:
            continue
        if step.get("prompt_sha256"):
            prompt_hashes[agent] = step["prompt_sha256"]
        if step.get("model"):
            model_versions[agent] = step["model"]

    sanctions = case.get("sanctions_snapshot") or {}
    return AuditLineage(
        audit_id=audit_id_for(str(case.get("case_id") or "")),
        prompt_hashes=prompt_hashes,
        model_versions=model_versions,
        sanctions_synced_at=sanctions.get("synced_at"),
        sanctions_list_age_days=sanctions.get("age_days"),
        ruleset_version=(case.get("boundary") or {}).get("version"),
    )


def _usage(case: dict[str, Any]) -> AuditUsage:
    return AuditUsage(
        input_tokens=int(case.get("_input_tokens") or 0),
        output_tokens=int(case.get("_output_tokens") or 0),
        estimated_cost_usd=round(float(case.get("_estimated_cost_usd") or 0.0), 8),
        agent_calls=int(case.get("_agent_calls") or 0),
        latency_ms=case.get("_sum_latency_ms"),
    )


def to_audit_response(
    case: dict[str, Any], *, idempotent_replay: bool = False
) -> ComplianceAuditResponse:
    """Render a case as the published audit result."""
    reconciled = case.get("reconciliation") or {}
    outcome = outcome_for(case)

    # risk_floor is read from the reconciliation when present and the validation
    # otherwise. The fast paths -- a blacklist auto-reject, a whitelist
    # auto-clear -- skip the AI entirely and never call reconcile(), so those
    # cases have a floor but no reconciliation, and defaulting to 0 there would
    # publish a floor of 0 on a shipment blocked by a floor of 100.
    floor = reconciled.get("risk_floor")
    if floor is None:
        floor = (case.get("validation") or {}).get("risk_floor") or 0

    return ComplianceAuditResponse(
        audit_id=audit_id_for(str(case.get("case_id") or "")),
        case_id=str(case.get("case_id") or ""),
        shipment_id=str(
            (case.get("shipment") or {}).get("shipment_id")
            or case.get("shipment_id") or ""
        ),
        client_reference=case.get("client_reference"),
        outcome=outcome,
        effective_risk=float(case.get("risk_score") or 0),
        model_risk=(
            None if reconciled.get("model_risk") is None
            else float(reconciled["model_risk"])
        ),
        risk_floor=float(floor),
        score_disputed=bool(reconciled.get("score_disputed")),
        findings=_findings(case),
        requires_human_review=outcome in _HUMAN_REVIEW_OUTCOMES,
        review_reason=_review_reason(case, outcome),
        lineage=_lineage(case),
        usage=_usage(case),
        created_at=str(case.get("created_at") or ""),
        completed_at=(
            str(case.get("_updated_at") or "") if is_complete(case) else None
        ),
        idempotent_replay=idempotent_replay,
    )


def shipment_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Turn a validated audit request into the shipment dict the pipeline expects.

    None-valued optional fields are dropped rather than passed through. The
    deterministic checks distinguish an absent field from a present-but-empty one
    -- _is_missing() in verifier.py treats "n/a", "none" and "not stated" as
    absent markers -- and handing them an explicit None would add noise to a
    distinction they already make correctly.

    client_reference and webhook_url are removed: they are transport concerns and
    have no business reaching a risk assessment, which also keeps them out of the
    text the model sees.
    """
    drop = {"client_reference", "webhook_url"}
    return {
        k: v for k, v in payload.items()
        if v is not None and k not in drop
    }
