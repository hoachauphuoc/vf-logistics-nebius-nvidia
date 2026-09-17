"""
Governance: delegation boundaries, the execution gate, and the agent gateway.

The design question this answers is not "can the agent decide?" but "who decided
that the agent may decide this?"

An agent here never acquires authority by reasoning well. Authority is granted by
a human publishing a **Delegation Boundary**: a versioned, machine-readable
statement of exactly which actions the agent may take and within what limits.
The agent then operates autonomously *inside* that boundary and stops at its
edge.

That distinction is what keeps this both autonomous and governable. The human
does not approve shipments one at a time - that would just be a slow human
process with extra steps. The human approves *policy*, once, and thousands of
cases execute against it without supervision. Only cases that fall outside the
published boundary come back to a person.

Three properties are deliberate:

* **Fail closed.** With no ACTIVE boundary the agent is SUSPENDED and nothing
  executes. A fresh deployment can analyse but cannot act until a human has
  published authority. The absence of policy is never read as permission.

* **One publish at a time.** Publishing a new version marks the previous one
  SUPERSEDED. Every executed action records the boundary version that permitted
  it, so any past decision can be reconstructed against the policy in force at
  the time rather than the policy in force now.

* **The gateway is the only door.** `tools.py` is not called from the workflow
  any more. Everything goes through `AgentGateway.execute`, which refuses
  anything the gate has not explicitly allowed.
"""

from __future__ import annotations

import os
from typing import Any

import tools
from store import get_store, new_id, utcnow

# Actions that change the world and therefore require delegated authority.
PROTECTED_ACTIONS = {
    "release_shipment",
    "hold_shipment",
    "assign_analyst",
    "draft_sar",
    "notify_webhook",
    "publish_decision",
}

# Conditions that always route to a human regardless of what a boundary permits.
# A boundary can narrow authority; it cannot waive these.
NON_WAIVABLE_HUMAN_TRIGGERS = {
    "injection_detected": "Document contained suspected prompt injection",
    "forbidden_field_attempted": "Document tried to set a decision field directly",
}

DEFAULT_BOUNDARY_AUTHOR = os.getenv("BOUNDARY_BOOTSTRAP_AUTHOR", "").strip()


# --------------------------------------------------------------------------
# Delegation boundaries
# --------------------------------------------------------------------------

def proposed_boundary(reason: str = "Initial delegation proposal") -> dict[str, Any]:
    """
    A starting boundary for a human to narrow and publish.

    Intentionally conservative. The agent may release only low-value, low-risk,
    fully-documented shipments on plain lanes, and may never auto-release
    anything touching dual-use goods or an enhanced due diligence destination.
    Everything else it may only *propose*.
    """
    return {
        "allowed_actions": sorted(PROTECTED_ACTIONS - {"release_shipment"}),
        "auto_release": {
            "permitted": True,
            "max_declared_value_usd": 25_000,
            "max_effective_risk": 39,
            "require_zero_deterministic_findings": True,
            "forbidden_hs_prefixes": sorted(
                ["8504", "9026", "8458", "8542", "9030", "2844", "8411"]
            ),
            "forbidden_destinations": sorted(
                ["pakistan", "iran", "north korea", "syria", "russia", "belarus"]
            ),
        },
        "require_human_when": [
            "score_disputed",
            "injection_detected",
            "forbidden_field_attempted",
            "compliance_blocked",
            "exposure_claim_unsupported",
        ],
        "sar_filing": {
            # The agent may prepare a filing. It may never submit one.
            "may_draft": True,
            "may_file": False,
        },
        "reason": reason,
    }


async def publish_boundary(
    permissions: dict[str, Any], author: str, note: str
) -> dict[str, Any]:
    """
    Make a boundary official.

    This is the only function in the codebase that grants an agent authority,
    and it takes a human's name as a required argument for that reason.
    """
    store = get_store()
    current = await store.active_boundary()

    version = (current.get("version", 0) + 1) if current else 1
    boundary = {
        "boundary_id": f"BOUNDARY-v{version}",
        "version": version,
        "status": "ACTIVE",
        "permissions": permissions,
        "published_by": author,
        "note": note,
        "published_at": utcnow(),
        "supersedes": current.get("boundary_id") if current else None,
    }

    if current:
        current["status"] = "SUPERSEDED"
        current["superseded_at"] = utcnow()
        current["superseded_by"] = boundary["boundary_id"]
        await store.put_boundary(current)

    await store.put_boundary(boundary)
    await store.add_audit({
        "audit_id": new_id("audit"),
        "case_id": "-",
        "action": "publish_delegation_boundary",
        "status": "done",
        "detail": {
            "boundary_id": boundary["boundary_id"],
            "version": version,
            "published_by": author,
            "note": note,
            "superseded": boundary["supersedes"],
        },
        "at": utcnow(),
    })
    return boundary


async def agent_readiness() -> dict[str, Any]:
    """READY only against an active published boundary. Otherwise SUSPENDED."""
    boundary = await get_store().active_boundary()
    if not boundary:
        return {
            "state": "SUSPENDED",
            "reason": (
                "No delegation boundary has been published. The agent may "
                "analyse and propose, but cannot execute protected actions."
            ),
            "boundary": None,
        }

    drift = await drift_check(boundary)
    if drift["material"]:
        return {
            "state": "SUSPENDED",
            "reason": (
                "Material drift from the behaviour this boundary was published "
                f"for: {drift['reason']} A human should review and re-publish."
            ),
            "boundary": boundary,
            "drift": drift,
        }

    return {
        "state": "READY",
        "reason": f"Operating under {boundary['boundary_id']} "
                  f"published by {boundary.get('published_by')}",
        "boundary": boundary,
        "drift": drift,
    }


# --------------------------------------------------------------------------
# Drift detection
# --------------------------------------------------------------------------

# A boundary is published against an expectation of how the traffic behaves. If
# the traffic changes shape, the boundary no longer means what its author
# intended, even though nothing about it has changed.
DRIFT_MIN_SAMPLE = int(os.getenv("DRIFT_MIN_SAMPLE", "8"))
DRIFT_MAX_AUTO_RELEASE_RATE = float(os.getenv("DRIFT_MAX_AUTO_RELEASE_RATE", "0.85"))
DRIFT_MAX_VETO_RATE = float(os.getenv("DRIFT_MAX_VETO_RATE", "0.60"))
DRIFT_MAX_INJECTION_RATE = float(os.getenv("DRIFT_MAX_INJECTION_RATE", "0.20"))


async def drift_check(boundary: dict[str, Any]) -> dict[str, Any]:
    """
    Compare recent behaviour against what the boundary was published for.

    Three signals, each of which means the author's assumptions no longer hold:

    * **Auto-release rate too high.** Either the traffic really did get cleaner,
      or something upstream is feeding the agent shipments that trivially pass.
      Both deserve a human look before more cargo is released.
    * **Veto rate too high.** The agents and the deterministic checks are
      disagreeing routinely, which means the model is no longer scoring the way
      it did when this boundary was written.
    * **Injection rate too high.** Someone is probing the document intake path.

    Suspending on drift is not a fault condition. It is the system declining to
    keep exercising authority granted for circumstances that no longer apply.
    """
    cases = [
        c for c in await get_store().list_cases(60)
        if not c.get("is_marker") and c.get("state") != "OBJECT_PROCESSED"
    ]

    sample = len(cases)
    metrics = {
        "sample": sample,
        "auto_release_rate": 0.0,
        "veto_rate": 0.0,
        "injection_rate": 0.0,
        "boundary_version": boundary.get("version"),
    }

    if sample < DRIFT_MIN_SAMPLE:
        return {
            "material": False,
            "reason": f"only {sample} recent case(s); below the {DRIFT_MIN_SAMPLE} "
                      "needed to judge drift.",
            "metrics": metrics,
        }

    auto = sum(1 for c in cases if c.get("state") == "AUTO_CLEARED")
    vetoed = sum(
        1 for c in cases
        if (c.get("reconciliation") or {}).get("source") == "deterministic floor"
    )
    injected = sum(
        1 for c in cases
        if ((c.get("input_security") or {}).get("injection_screening") or {}).get("blocked")
        or ((c.get("input_security") or {}).get("model_armor") or {}).get("blocked")
    )

    metrics["auto_release_rate"] = round(auto / sample, 3)
    metrics["veto_rate"] = round(vetoed / sample, 3)
    metrics["injection_rate"] = round(injected / sample, 3)

    reasons = []
    if metrics["auto_release_rate"] > DRIFT_MAX_AUTO_RELEASE_RATE:
        reasons.append(
            f"{metrics['auto_release_rate']:.0%} of recent cases were auto-released "
            f"(limit {DRIFT_MAX_AUTO_RELEASE_RATE:.0%})."
        )
    if metrics["veto_rate"] > DRIFT_MAX_VETO_RATE:
        reasons.append(
            f"deterministic checks overrode the agent on "
            f"{metrics['veto_rate']:.0%} of cases (limit {DRIFT_MAX_VETO_RATE:.0%})."
        )
    if metrics["injection_rate"] > DRIFT_MAX_INJECTION_RATE:
        reasons.append(
            f"{metrics['injection_rate']:.0%} of documents were flagged for prompt "
            f"injection (limit {DRIFT_MAX_INJECTION_RATE:.0%})."
        )

    return {
        "material": bool(reasons),
        "reason": " ".join(reasons) or "within expected behaviour.",
        "metrics": metrics,
    }


# --------------------------------------------------------------------------
# Execution gate
# --------------------------------------------------------------------------

def _human_triggers(case: dict[str, Any], permissions: dict[str, Any]) -> list[str]:
    """Which configured or non-waivable triggers this case has hit."""
    configured = set(permissions.get("require_human_when", []))
    hit: list[str] = []

    security = (case.get("input_security") or {}).get("injection_screening") or {}
    if security.get("blocked"):
        hit.append("injection_detected")
    if (case.get("input_security") or {}).get("forbidden_fields_attempted"):
        hit.append("forbidden_field_attempted")

    if (case.get("reconciliation") or {}).get("score_disputed"):
        hit.append("score_disputed")

    if str(case.get("compliance_status") or "").upper() == "BLOCKED":
        hit.append("compliance_blocked")

    codes = {
        f.get("code") for f in (case.get("validation") or {}).get("findings", [])
    }
    if "EXPOSURE_CLAIM_UNSUPPORTED" in codes:
        hit.append("exposure_claim_unsupported")

    # Non-waivable triggers count even if the boundary omits them.
    return [
        t for t in hit
        if t in configured or t in NON_WAIVABLE_HUMAN_TRIGGERS
    ]


def check(
    action: str, case: dict[str, Any], boundary: dict[str, Any] | None
) -> dict[str, Any]:
    """
    Deterministic execution gate. Fail closed.

    Returns {allowed, reason, boundary_version}. No model is consulted: whether
    an action is permitted is a policy lookup, not a judgement call.
    """
    if action not in PROTECTED_ACTIONS:
        return {"allowed": True, "reason": "not a protected action", "boundary_version": None}

    if not boundary:
        return {
            "allowed": False,
            "reason": "DENIED: no active delegation boundary (agent SUSPENDED)",
            "boundary_version": None,
        }

    perms = boundary.get("permissions") or {}
    version = boundary.get("version")

    if action not in set(perms.get("allowed_actions", [])) and action != "release_shipment":
        return {
            "allowed": False,
            "reason": f"DENIED: '{action}' is outside {boundary['boundary_id']}",
            "boundary_version": version,
        }

    triggers = _human_triggers(case, perms)
    if triggers:
        return {
            "allowed": False,
            "reason": "DENIED: case requires human review (" + ", ".join(triggers) + ")",
            "boundary_version": version,
            "human_triggers": triggers,
        }

    if action == "release_shipment":
        return _check_release(case, perms, boundary)

    if action == "draft_sar" and not perms.get("sar_filing", {}).get("may_draft", False):
        return {
            "allowed": False,
            "reason": f"DENIED: drafting filings not delegated under {boundary['boundary_id']}",
            "boundary_version": version,
        }

    return {
        "allowed": True,
        "reason": f"within {boundary['boundary_id']}",
        "boundary_version": version,
    }


def _check_release(
    case: dict[str, Any], perms: dict[str, Any], boundary: dict[str, Any]
) -> dict[str, Any]:
    """
    Releasing cargo is the one irreversible action, so it gets its own gate.

    Every condition here is evaluated against the shipment record and the
    deterministic findings, never against the agent's narrative.
    """
    rules = perms.get("auto_release") or {}
    version = boundary.get("version")

    def deny(reason: str) -> dict[str, Any]:
        return {"allowed": False, "reason": f"DENIED: {reason}", "boundary_version": version}

    if not rules.get("permitted", False):
        return deny("auto-release not delegated")

    shipment = case.get("shipment") or {}
    validation = case.get("validation") or {}
    reconciliation = case.get("reconciliation") or {}

    risk = case.get("risk_score")
    ceiling = rules.get("max_effective_risk")
    if ceiling is not None and (risk is None or risk > ceiling):
        return deny(f"effective risk {risk} exceeds delegated ceiling {ceiling}")

    if rules.get("require_zero_deterministic_findings", True):
        count = validation.get("finding_count", 0)
        if count:
            return deny(f"{count} deterministic finding(s) present")

    if not reconciliation.get("auto_clear_permitted", False):
        return deny("deterministic validation vetoed auto-clear")

    try:
        value = float(shipment.get("declared_value") or 0)
    except (TypeError, ValueError):
        value = 0.0
    max_value = rules.get("max_declared_value_usd")
    if max_value is not None and value > max_value:
        return deny(f"declared value {value:,.0f} USD exceeds delegated {max_value:,.0f} USD")

    hs = "".join(ch for ch in str(shipment.get("hs_code") or "") if ch.isdigit())[:4]
    if hs and hs in set(rules.get("forbidden_hs_prefixes", [])):
        return deny(f"HS prefix {hs} is excluded from auto-release")

    dest = str(shipment.get("destination") or "").lower()
    for blocked in rules.get("forbidden_destinations", []):
        if blocked in dest:
            return deny(f"destination '{blocked}' is excluded from auto-release")

    return {
        "allowed": True,
        "reason": f"within auto-release limits of {boundary['boundary_id']}",
        "boundary_version": version,
    }


# --------------------------------------------------------------------------
# Agent gateway
# --------------------------------------------------------------------------

_ACTION_IMPLS = {
    "release_shipment": tools.release_shipment,
    "hold_shipment": tools.hold_shipment,
    "assign_analyst": tools.assign_analyst,
    "draft_sar": tools.draft_sar,
    "notify_webhook": tools.notify_webhook,
    "publish_decision": tools.publish_decision,
}


async def execute(
    action: str, case: dict[str, Any], /, **kwargs: Any
) -> dict[str, Any]:
    """
    The only path from the workflow to a real-world action.

    A denial is recorded in the audit log exactly like a success. An action that
    was refused is as much a governance fact as one that was taken, and a system
    that silently drops denials cannot be audited.
    """
    # Readiness rather than the raw boundary: an agent suspended for material
    # drift holds a perfectly valid boundary and still must not act on it.
    readiness = await agent_readiness()
    boundary = readiness.get("boundary")

    if readiness["state"] != "READY":
        verdict = {
            "allowed": False,
            "reason": f"DENIED: agent is {readiness['state']}. {readiness['reason']}",
            "boundary_version": (boundary or {}).get("version"),
        }
    else:
        verdict = check(action, case, boundary)

    if not verdict["allowed"]:
        receipt = {
            "audit_id": new_id("audit"),
            "case_id": case.get("case_id"),
            "action": action,
            "status": "denied",
            "detail": {
                "gate_reason": verdict["reason"],
                "boundary_version": verdict.get("boundary_version"),
                "human_triggers": verdict.get("human_triggers", []),
                "requested_args": {
                    k: (str(v)[:200] if isinstance(v, str) else v)
                    for k, v in kwargs.items()
                },
            },
            "at": utcnow(),
        }
        await get_store().add_audit(receipt)
        return receipt

    impl = _ACTION_IMPLS.get(action)
    if impl is None:
        raise ValueError(f"unknown action {action}")

    receipt = await impl(case["case_id"], **kwargs)
    receipt.setdefault("detail", {})["boundary_version"] = verdict.get("boundary_version")
    receipt["gate_reason"] = verdict["reason"]
    return receipt
