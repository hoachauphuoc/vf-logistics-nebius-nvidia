"""
Zero-day radar: adverse-media screening for entities the official list has not
caught up with.

The gap this closes
-------------------
The sanctions index refreshes weekly, so a company designated on Tuesday is
invisible to it until the following Sunday. That window is not a corner case --
it is when a designated party is most motivated to ship, and a screening system
that reports CLEAN during it is reporting on a list rather than on reality.

So when the official list says CLEAN and the shipment still looks like it is
worth a second look, this agent searches recent news itself.

Why the model decides whether to search
---------------------------------------
Two existing call sites search unconditionally: compliance_agent.py fires two
Tavily queries on every single shipment. That is the wrong shape here for a
reason that is not only cost. An unconditional search on clean traffic produces a
stream of irrelevant results that a model then has to reason its way past, and
the false-positive rate on the HS work went UP when the model was given more
material to be cautious about. A search that fires when there is a reason to
search produces evidence; one that always fires produces noise.

The gate is deterministic and outside the model
-----------------------------------------------
`should_screen()` decides, not the agent. A model deciding when to spend money is
a model whose cost is unbounded by anything except its own judgement, and the
budget here is 50 dollars of inference credit. The model's autonomy is over the
search QUERY and the verdict, which is where judgement actually helps.

Why `searched` is a required field on the verdict
-------------------------------------------------
tavily_client returns an empty list for a missing API key, a timeout, a 429 and a
genuinely empty result. Collapsing those into "no adverse media found" would clear
a shipment on a search that never ran, so the schema separates "I looked and found
nothing" from "I could not look" and the orchestrator treats them differently.
"""

from __future__ import annotations

import json
import os
from typing import Any

from vf_logistics import config as model_config
from vf_logistics import nebius_client, tavily_client, verifier
from ._common import Timer, envelope, parse_model_json

DEFAULT_MODEL = os.getenv("ZERO_DAY_MODEL", "").strip()

# Two rounds, against the debate agent's four. One round to search, one to read
# the results and render a verdict, and nothing this agent does benefits from
# iterating further -- it is not building an argument, it is checking a name.
MAX_TOOL_ROUNDS = 2

# How far back the news search looks. Anything older than this is the official
# list's job, and duplicating it here would spend tokens re-finding designations
# the deterministic check already has.
NEWS_WINDOW_DAYS = int(os.getenv("ZERO_DAY_NEWS_DAYS", "45"))


def get_model_id() -> str:
    return DEFAULT_MODEL or model_config.get_model()


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "tavily_zero_day_search",
            "description": (
                "Search the web in real time for recent news, allegations or "
                "mentions of sanctions evasion, smuggling, or shell-company "
                "activity involving a specific logistics entity. Use this to "
                "check a counterparty that is absent from the official sanctions "
                "list but whose shipment carries risk indicators."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Search query aimed at negative news. Name the entity "
                            "in quotes and add the specific concern, e.g. "
                            "'\"ABC Logistics LLC\" sanctions evasion'."
                        ),
                    },
                    "search_depth": {
                        "type": "string",
                        "enum": ["basic", "advanced"],
                        "description": (
                            "Use 'advanced' for an entity you cannot corroborate "
                            "at all, 'basic' for a routine check."
                        ),
                    },
                },
                "required": ["query", "search_depth"],
            },
        },
    },
]


SYSTEM_PROMPT = """\
You are a frontline trade-compliance auditor.

The entities on this shipment are NOT in the official sanctions database. That
database refreshes weekly, so a party designated in the last few days will not be
in it yet -- and the shipment in front of you carries risk indicators that are the
reason you were called.

Use tavily_zero_day_search to check the named counterparties for recent adverse
coverage: sanctions evasion, smuggling, export-control prosecution, shell-company
allegations. Search the specific entity names, not the industry.

Then judge what you found.

What counts as a finding
  A named report tying THIS entity to evasion, smuggling, a shell-company
  structure, or an export-control matter.

What does not
  An entity in a risky country. A company with a generic name. An industry-wide
  article that does not name this party. Coverage of a similarly-named but
  different company -- check the country and the sector before you accept a match.

Flagging honest freight has a real cost: the shipment is held, a person spends an
hour on it, and a customer is told their goods are suspected. Do not flag on
atmosphere.

Return only JSON, with these fields in this order:
{
  "entities_checked": ["the names you searched"],
  "reasoning": "one or two sentences naming the specific evidence, or naming what
                you searched and found nothing on",
  "evidence_urls": ["urls that support a finding, empty if none"],
  "searched": true if a search actually ran and returned results, false if it did
             not run or the tool reported a failure,
  "confidence": 0.0 to 1.0,
  "risk_found": true or false
}

`searched` and `risk_found` are separate and both required. "I searched and found
nothing" and "I could not search" are opposite facts; reporting the second as the
first would clear a shipment that nobody checked.\
"""


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------

def should_screen(
    shipment: dict[str, Any], validation: dict[str, Any] | None = None
) -> tuple[bool, str]:
    """
    Whether this shipment warrants a zero-day search.

    Returns (decision, reason) so the reason can go on the case whichever way it
    goes -- "we did not search, and here is why" is as much part of an audit trail
    as a finding.

    Deliberately NOT called when the official list already produced a HIT: the
    shipment is blocked on a designation, and spending tokens to find news about a
    party we have already matched adds nothing.
    """
    validation = validation or {}

    if validation.get("sanctions_screening") == "HIT":
        return False, "already matched against the official sanctions list"
    if validation.get("sanctions_screening") == "UNAVAILABLE":
        # The list could not be read, so there is no "absent from the list" to
        # act on. The UNAVAILABLE finding already routes this to a human.
        return False, "sanctions list unavailable, so absence from it is unknown"
    if validation.get("skip_ai"):
        return False, "shipment resolved by deterministic pre-filter"

    reasons: list[str] = []

    hs = "".join(ch for ch in str(shipment.get("hs_code") or "") if ch.isdigit())[:4]
    if hs in verifier.DUAL_USE_HS_PREFIXES:
        reasons.append(f"dual-use HS heading {hs}")

    destination = verifier._country(shipment.get("destination"))
    if destination in verifier.HIGH_RISK_DESTINATIONS:
        reasons.append(f"destination {destination}")

    haystack = " ".join(str(shipment.get(f) or "").lower() for f in (
        "route_details", "transit_points", "destination",
    ))
    for hub in verifier.DIVERSION_HUBS:
        if hub in haystack:
            reasons.append(f"routed via {hub}")
            break

    # A counterparty we have no history with is the case where public evidence is
    # the only evidence available.
    tx_count = shipment.get("shipper_tx_count")
    if tx_count is None:
        reasons.append("no trading history on record for this shipper")
    else:
        try:
            if int(tx_count) <= 1:
                reasons.append("first or second shipment for this shipper")
        except (TypeError, ValueError):
            reasons.append("unreadable trading history")

    if not reasons:
        return False, "no risk indicator present"
    return True, "; ".join(reasons)


def entities_to_check(shipment: dict[str, Any]) -> list[str]:
    """Counterparty names worth searching, de-duplicated and order-stable."""
    out: list[str] = []
    for field in (
        "shipper_company", "shipper_name",
        "receiver_company", "receiver_name", "consignee_name",
    ):
        value = str(shipment.get(field) or "").strip()
        if value and value.lower() not in ("n/a", "not stated", "none"):
            if value not in out:
                out.append(value)
    return out[:4]


# --------------------------------------------------------------------------
# The agent
# --------------------------------------------------------------------------

async def _run_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name != "tavily_zero_day_search":
        return {"error": f"unknown tool {name}"}

    query = str(args.get("query") or "").strip()
    depth = args.get("search_depth") or "basic"
    if not query:
        return {"error": "empty query", "results": [], "searched": False}

    results, status = await tavily_client.search_with_status(
        query, max_results=5 if depth == "advanced" else 3,
        search_depth=depth, topic="news", days=NEWS_WINDOW_DAYS,
    )
    out: dict[str, Any] = {
        "query": query,
        "search_depth": depth,
        "status": status,
        "result_count": len(results),
        "results": results,
        # Stated in the tool result so the model does not have to infer it from an
        # empty list -- the inference it would make is the wrong one.
        "searched": status == tavily_client.OK,
    }
    if status in tavily_client.FAILED_STATUSES:
        out["error"] = (
            f"search did not run ({status}). An empty result here is not evidence "
            "that the entity is clean."
        )
    return out


async def screen_zero_day(
    shipment: dict[str, Any],
    *,
    model: str | None = None,
    max_tool_rounds: int = MAX_TOOL_ROUNDS,
    temperature: float = 0.1,
) -> dict[str, Any]:
    """
    Check counterparties for adverse media the official list has not caught.

    Returns the standard envelope. `screen_zero_day` does NOT decide whether it
    should run -- should_screen() does, outside the model, because a model
    deciding when to spend money has a cost bounded only by its own judgement.
    """
    model_id = model or get_model_id()
    names = entities_to_check(shipment)

    user_text = (
        "<<<BEGIN SHIPMENT RECORD>>>\n"
        f"Shipper: {shipment.get('shipper_company') or shipment.get('shipper_name') or 'not stated'}\n"
        f"Shipper country: {shipment.get('shipper_country') or 'not stated'}\n"
        f"Receiver: {shipment.get('receiver_company') or shipment.get('receiver_name') or 'not stated'}\n"
        f"Receiver country: {shipment.get('receiver_country') or 'not stated'}\n"
        f"Consignee: {shipment.get('consignee_name') or 'not stated'}\n"
        f"Route: {shipment.get('route_details') or 'not stated'}\n"
        f"Transit: {shipment.get('transit_points') or 'not stated'}\n"
        f"Goods: {shipment.get('cargo_description') or 'not stated'}\n"
        f"Declared HS heading: {shipment.get('hs_code') or 'not stated'}\n"
        "<<<END SHIPMENT RECORD>>>\n\n"
        f"Counterparties to check: {', '.join(names) or 'none identifiable'}\n\n"
        "Search for recent adverse coverage on these entities, then return the JSON."
    )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
    ]

    searches: list[dict[str, Any]] = []
    input_tokens = output_tokens = 0
    text = ""
    tool_error: str | None = None
    tool_forced = False

    with Timer() as timer:
        for _round in range(max_tool_rounds + 1):
            response = await nebius_client.complete_with_tools(
                model=model_id, messages=messages, tools=TOOLS,
                temperature=temperature,
            )
            used_in, used_out = nebius_client._usage(response)
            input_tokens += used_in
            output_tokens += used_out

            message = response.choices[0].message
            calls = getattr(message, "tool_calls", None)

            if not calls:
                text = message.content or ""
                break

            messages.append({
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {
                            "name": c.function.name,
                            "arguments": c.function.arguments,
                        },
                    }
                    for c in calls
                ],
            })

            for call in calls:
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError as exc:
                    # Reported rather than silently becoming {}. debate_agent.py
                    # degrades malformed arguments to an empty dict with no
                    # signal, which makes a broken tool call indistinguishable
                    # from one that found nothing.
                    args = {}
                    tool_error = f"malformed tool arguments: {exc}"

                result = await _run_tool(call.function.name, args)
                searches.append({
                    "query": result.get("query"),
                    "search_depth": result.get("search_depth"),
                    "status": result.get("status"),
                    "result_count": result.get("result_count", 0),
                    "urls": [r.get("url") for r in result.get("results") or []],
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result),
                })

        if not text:
            # The tool budget ran out before the model stopped searching, so no
            # verdict was ever produced.
            #
            # This is not a hypothetical. On a 200-case benchmark run, 73 of the 93
            # cases that reached this agent came back with no usable verdict and no
            # error -- the model had four counterparties to check, spent every
            # round searching them, and the loop exited with `text` still empty.
            # The agent was billing for three completions and returning nothing,
            # 78% of the time, and because interpret() maps an unparseable reply to
            # "unknown" it looked like a model quality problem rather than a
            # control-flow bug.
            #
            # Asking again with the tool withdrawn forces the decision. The search
            # results are already in `messages`, so nothing is re-fetched.
            forced = await nebius_client.complete_with_tools(
                model=model_id,
                messages=messages + [{
                    "role": "user",
                    "content": (
                        "No more searches. Using only what the searches above "
                        "returned, give your verdict now as JSON with the fields "
                        "in the order specified. If the searches found nothing "
                        "adverse, say so with risk_found false -- that is a valid "
                        "answer, not a failure."
                    ),
                }],
                tools=None,
                temperature=temperature,
            )
            used_in, used_out = nebius_client._usage(forced)
            input_tokens += used_in
            output_tokens += used_out
            text = forced.choices[0].message.content or ""
            tool_forced = True

    parsed, error = parse_model_json(text)

    # A verdict claiming it searched when no search returned results is corrected
    # rather than trusted. The model has an incentive to fill the field
    # optimistically, and this is the one field whose truth the caller can check.
    ran = any(s.get("status") == tavily_client.OK for s in searches)
    if isinstance(parsed, dict) and parsed.get("searched") and not ran:
        parsed["searched"] = False
        parsed.setdefault("reasoning", "")
        parsed["reasoning"] = (
            "[corrected: the model reported searching, but no search returned "
            "results] " + str(parsed["reasoning"])
        )

    out = envelope(
        agent="zero_day",
        model=model_id,
        result=parsed,
        error=error or tool_error,
        raw=text,
        latency_ms=timer.ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        legacy_key="zero_day_result",
        prompt=user_text,
    )
    out["searches"] = searches
    out["search_ran"] = ran
    # Recorded so a run can tell how often the tool budget was the binding
    # constraint. A high rate here means MAX_TOOL_ROUNDS is too low for the number
    # of counterparties being checked, which is a tuning fact, not an error.
    out["verdict_forced"] = tool_forced
    out["tool_rounds_used"] = len(searches)
    return out


def interpret(result: dict[str, Any]) -> dict[str, Any]:
    """
    Reduce a verdict to what a caller can act on.

    A reply that failed to parse, or that does not say whether it searched,
    becomes `verdict: "unknown"` rather than being read either way -- the same
    rule as hs_classifier_agent.interpret(), and for the same reason: coercing an
    unusable reply to "no risk found" clears exactly the shipments this agent
    exists to catch.
    """
    payload = result.get("result") or {}
    risk_found = payload.get("risk_found")
    searched = payload.get("searched")

    if not isinstance(risk_found, bool) or not isinstance(searched, bool):
        return {
            "verdict": "unknown",
            "searched": bool(result.get("search_ran")),
            "confidence": 0.0,
            "reasoning": (
                payload.get("reasoning") or result.get("error")
                or "no usable verdict returned"
            ),
            "evidence_urls": [],
            "entities_checked": [],
        }

    try:
        confidence = max(0.0, min(1.0, float(payload.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        confidence = 0.0

    return {
        "verdict": "risk_found" if risk_found else "no_risk_found",
        "searched": searched,
        "confidence": confidence,
        "reasoning": str(payload.get("reasoning") or "")[:400],
        "evidence_urls": [
            str(u) for u in (payload.get("evidence_urls") or [])[:6]
        ],
        "entities_checked": [
            str(e) for e in (payload.get("entities_checked") or [])[:6]
        ],
    }


def get_agent_info() -> dict[str, Any]:
    return {
        "name": "VF Logistics Zero-Day Radar",
        "version": "1.0.0",
        "model": get_model_id(),
        "purpose": (
            "Catch counterparties designated too recently to be in the weekly "
            "sanctions refresh, by searching recent adverse coverage when a "
            "shipment carries risk indicators."
        ),
        "capabilities": [
            "adverse_media_screening",
            "shell_company_detection",
            "real_time_tool_calling",
        ],
        "gate": (
            "Runs only when the official list says CLEAN and a deterministic "
            "risk indicator is present. The gate is code, not the model."
        ),
    }
