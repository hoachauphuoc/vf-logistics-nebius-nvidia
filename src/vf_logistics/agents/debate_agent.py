"""
Multi-Agent Debate: Nemotron Super reviews Nano's assessment using function calling.

This implements the "Deep Review" feature where a Senior Auditor (Super 120B)
reviews and can challenge the Junior Analyst's (Nano 30B) fraud assessment.
Super has access to tools:
  - request_nano_reevaluation: Ask Nano to re-score with specific focus
  - search_tavily: Run additional web searches for context
  - render_final_verdict: Submit final CONFIRM or DISAGREE verdict

Only Nemotron Super supports function calling. Nano uses context injection.
"""

from __future__ import annotations

import json
import os
from typing import Any

from vf_logistics import nebius_client
from vf_logistics import tavily_client
from ._common import Timer, utcnow

# Output ceiling per round. 1,500 against a measured maximum of 403 output tokens.
#
# Low because this agent mostly emits tool calls rather than prose, and its verdict is
# a short structured judgement. Still 3.7x the largest observed reply.
MAX_OUTPUT_TOKENS = 1500

# Nemotron 3 Ultra, the one place in the pipeline it earns its rate.
#
# Ultra is 1.00/3.00 per million against Super's 0.30/0.90 -- 3.3x -- and it is
# deliberately NOT used on fraud_detection or compliance, which run on every case. The
# reason there is architectural rather than financial: verifier.py computes a
# deterministic risk floor, and an agent may raise risk but never lower it below that
# floor, so a stronger model cannot move the outcome in the direction that matters.
#
# The debate is the exception. It runs only when `score_disputed` is set -- measured at
# 2 calls across 20 cases -- and what it produces is not a score that the floor will
# override, it is a reasoned CONFIRM/DISAGREE on whether the floor and the model can be
# reconciled without a person. That judgement is the outcome. At this volume the whole
# switch costs about $0.007 per 20 cases.
#
# Worth being honest that this is a quality bet, not a measured improvement: nothing
# here yet demonstrates Ultra resolves more disputes than Super. scripts/compare_debate_models.py
# measures exactly that, and DEBATE_MODEL reverses the decision without a deploy.
MODEL_ID = os.getenv("DEBATE_MODEL", "nvidia/Nemotron-3-Ultra-550b-a55b")


DEBATE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "request_nano_reevaluation",
            "description": (
                "Request the Junior Analyst (Nano) to re-evaluate the shipment "
                "with specific focus areas. Use this when you suspect the original "
                "score missed something important."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "focus_areas": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Specific aspects to focus on: 'pricing' (cost anomalies), "
                            "'identity' (shipper/receiver verification), 'route' "
                            "(path anomalies), 'documents' (paperwork issues), "
                            "'timing' (timestamp anomalies)"
                        ),
                    },
                    "hypothesis": {
                        "type": "string",
                        "description": "Your hypothesis about what Nano might have missed",
                    },
                },
                "required": ["focus_areas", "hypothesis"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_tavily",
            "description": (
                "Search the web for additional information about entities, "
                "companies, or fraud patterns. Use this to verify claims or "
                "gather external intelligence."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (e.g., 'Thanh Phat Trading sanctions Vietnam')",
                    },
                    "search_depth": {
                        "type": "string",
                        "enum": ["basic", "advanced"],
                        "description": "basic=3 results, advanced=5 results",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_final_verdict",
            "description": (
                "Submit your final verdict after reviewing all evidence. "
                "You MUST call this function to conclude the debate."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "verdict": {
                        "type": "string",
                        "enum": ["CONFIRM", "DISAGREE"],
                        "description": "CONFIRM=agree with Nano, DISAGREE=found issues Nano missed",
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "Your confidence in this verdict (0.0-1.0)",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "Detailed explanation of your verdict",
                    },
                    "recommended_action": {
                        "type": "string",
                        "enum": ["release", "hold", "escalate"],
                        "description": "What should happen to this shipment",
                    },
                    "adjusted_risk_score": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 100,
                        "description": "Your adjusted risk score if you disagree with Nano's score",
                    },
                },
                "required": ["verdict", "confidence", "rationale", "recommended_action"],
            },
        },
    },
]


DEBATE_PROMPT = """You are a Senior Fraud Auditor (AI) reviewing the assessment made by a Junior Analyst (AI).

YOUR ROLE:
1. Review the Junior Analyst's fraud score and compliance assessment critically
2. Challenge assumptions - the Junior may have missed important signals
3. Use your tools to gather more evidence or request re-evaluation if something seems off
4. Render a final verdict: CONFIRM (agree) or DISAGREE (found issues)

IMPORTANT GUIDELINES:
- You MUST use the render_final_verdict tool to conclude. Never just respond with text.
- If the risk score seems too low for the indicators present, use request_nano_reevaluation
- If you need more context about entities or companies, use search_tavily
- Consider: pricing anomalies, identity red flags, route manipulation, document issues
- The Junior Analyst is competent but not infallible. Your job is quality control.

WHEN TO DISAGREE:
- Shipping cost significantly below market average (>30% discount is suspicious)
- New shipper (low transaction count) with high-value cargo
- Route that doesn't make geographic sense
- Missing or incomplete documentation for high-value shipments
- Entity names that appear on sanctions or watchlists (search to verify)

OUTPUT:
After your analysis, you MUST call render_final_verdict with your conclusion."""


def _build_debate_context(case: dict[str, Any]) -> str:
    """Build the context prompt from case data for Super to review."""
    shipment = case.get("shipment", {})
    
    # Get Nano's original assessment
    fraud_step = None
    compliance_step = None
    for step in case.get("steps", []):
        if step.get("agent") == "fraud_detection":
            fraud_step = step
        elif step.get("agent") == "compliance":
            compliance_step = step
    
    fraud_result = (fraud_step or {}).get("result", {})
    compliance_result = (compliance_step or {}).get("result", {})
    
    context = f"""CASE UNDER REVIEW: {case.get('case_id', 'UNKNOWN')}

SHIPMENT DATA:
- Shipment ID: {shipment.get('shipment_id', 'N/A')}
- Origin: {shipment.get('origin', 'N/A')}
- Destination: {shipment.get('destination', 'N/A')}
- Weight: {shipment.get('weight_kg', 'N/A')} kg
- Declared Value: {shipment.get('declared_value', 'N/A')} USD
- Shipping Cost: {shipment.get('shipping_cost', 'N/A')} USD
- Shipper: {shipment.get('shipper_name', 'N/A')}
- Shipper Company: {shipment.get('shipper_company', 'N/A')}
- Receiver: {shipment.get('receiver_name', 'N/A')}
- Route: {shipment.get('route_details', 'N/A')}
- Average Route Cost: {shipment.get('avg_route_cost', 'N/A')} USD
- Shipper Transaction Count: {shipment.get('shipper_tx_count', 'N/A')}
- Cargo Description: {shipment.get('cargo_description', 'N/A')}
- HS Code: {shipment.get('hs_code', 'N/A')}

JUNIOR ANALYST (NANO) FRAUD ASSESSMENT:
- Risk Score: {case.get('model_risk_score', 'N/A')}/100
- Effective Risk (after deterministic checks): {case.get('risk_score', 'N/A')}/100
- Risk Level: {case.get('risk_level', 'N/A')}
- Flags: {json.dumps(fraud_result.get('flags', []), indent=2)}
- Recommendations: {json.dumps(fraud_result.get('recommendations', []), indent=2)}
- Confidence: {fraud_result.get('confidence', 'N/A')}

JUNIOR ANALYST (NANO) COMPLIANCE ASSESSMENT:
- Status: {case.get('compliance_status', 'N/A')}
- Score: {case.get('compliance_score', 'N/A')}/100
- Findings: {json.dumps(compliance_result.get('findings', []), indent=2)}

DETERMINISTIC VALIDATION:
{json.dumps(case.get('validation', {}), indent=2)}

YOUR TASK:
Review this assessment critically. Is the risk score appropriate? Did Nano miss anything?
Use your tools if needed, then call render_final_verdict with your conclusion."""
    
    return context


async def conduct_debate(
    case: dict[str, Any], max_tool_rounds: int = 3
) -> dict[str, Any]:
    """
    Conduct a multi-agent debate on a case.
    
    Super reviews Nano's assessment and can use tools to:
    - Request Nano to re-evaluate with specific focus
    - Search Tavily for additional context
    - Render a final verdict
    
    Returns a dict with debate_trace, verdict, and token usage.
    """
    context = _build_debate_context(case)
    
    messages = [
        {"role": "system", "content": DEBATE_PROMPT},
        {"role": "user", "content": context},
    ]
    
    debate_trace: list[dict[str, Any]] = []
    final_verdict: dict[str, Any] | None = None
    total_input_tokens = 0
    total_output_tokens = 0
    
    with Timer() as timer:
        for round_num in range(max_tool_rounds + 1):  # +1 for final verdict round
            response = await nebius_client.complete_with_tools(
                model=MODEL_ID,
                messages=messages,
                tools=DEBATE_TOOLS,
                temperature=0.3,
                max_tokens=MAX_OUTPUT_TOKENS,
            )
            
            input_tokens, output_tokens = nebius_client._usage(response)
            total_input_tokens += input_tokens
            total_output_tokens += output_tokens
            
            assistant_message = response.choices[0].message
            
            # Check for tool calls
            tool_calls = getattr(assistant_message, "tool_calls", None) or []
            
            if not tool_calls:
                # No tool calls - model gave direct response (shouldn't happen with good prompt)
                # Force a default verdict
                debate_trace.append({
                    "round": round_num + 1,
                    "type": "no_tool_call",
                    "content": assistant_message.content or "",
                    "at": utcnow(),
                })
                if not final_verdict:
                    final_verdict = {
                        "verdict": "CONFIRM",
                        "confidence": 0.5,
                        "rationale": "Senior Auditor did not use tools. Defaulting to CONFIRM.",
                        "recommended_action": "hold",
                    }
                break
            
            # Process each tool call
            tool_results_for_message = []
            for tool_call in tool_calls:
                tool_name = tool_call.function.name
                try:
                    tool_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    tool_args = {}
                
                # Execute tool
                tool_result = await _execute_tool(tool_name, tool_args, case)
                
                trace_entry = {
                    "round": round_num + 1,
                    "tool": tool_name,
                    "arguments": tool_args,
                    "result": tool_result,
                    "at": utcnow(),
                }
                debate_trace.append(trace_entry)
                
                # Check if this is the final verdict
                if tool_name == "render_final_verdict":
                    final_verdict = tool_args
                    break
                
                tool_results_for_message.append({
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(tool_result),
                })
            
            if final_verdict:
                break
            
            # Add assistant message with tool calls and tool results to conversation
            messages.append({
                "role": "assistant",
                "content": assistant_message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ],
            })
            
            for tool_result_msg in tool_results_for_message:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_result_msg["tool_call_id"],
                    "content": tool_result_msg["content"],
                })
    
    # If we exhausted rounds without a verdict, force one
    if not final_verdict:
        final_verdict = {
            "verdict": "CONFIRM",
            "confidence": 0.4,
            "rationale": f"Senior Auditor did not render verdict after {max_tool_rounds} rounds. Defaulting to CONFIRM with low confidence.",
            "recommended_action": "hold",
        }
        debate_trace.append({
            "round": max_tool_rounds + 1,
            "type": "forced_verdict",
            "verdict": final_verdict,
            "at": utcnow(),
        })
    
    return {
        "agent": "debate",
        "model": MODEL_ID,
        "latency_ms": timer.ms,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "at": utcnow(),
        # The context Super was given to review. Carried out so the case trace
        # can show what the Senior Auditor actually saw, the same way the
        # single-call agents surface their prompt via envelope().
        "prompt": _truncate_context(context),
        "result": {
            "debate_trace": debate_trace,
            "verdict": final_verdict,
            "rounds_used": len(set(t.get("round", 0) for t in debate_trace)),
        },
    }


def _truncate_context(text: str, limit: int = 4000) -> str:
    if not text or len(text) <= limit:
        return text or ""
    return f"{text[:limit]}\n...[truncated, {len(text) - limit} more chars]"


async def _execute_tool(
    tool_name: str, args: dict[str, Any], case: dict[str, Any]
) -> dict[str, Any]:
    """Execute a debate tool and return result."""
    if tool_name == "request_nano_reevaluation":
        return await _nano_reevaluate(
            case, args.get("focus_areas", []), args.get("hypothesis", "")
        )
    elif tool_name == "search_tavily":
        return await _tavily_search(
            args.get("query", ""), args.get("search_depth", "basic")
        )
    elif tool_name == "render_final_verdict":
        # Just record it - the verdict is extracted from args in the main loop
        return {"recorded": True, **args}
    return {"error": f"Unknown tool: {tool_name}"}


async def _nano_reevaluate(
    case: dict[str, Any], focus_areas: list[str], hypothesis: str
) -> dict[str, Any]:
    """
    Re-run Nano with additional focus instructions.
    
    Adds a _debate_focus directive to the shipment context so Nano pays
    extra attention to the areas the Senior Auditor suspects.
    """
    from . import analyze_shipment
    
    # Add focus directive to shipment context
    shipment = case.get("shipment", {}).copy()
    shipment["_debate_focus"] = {
        "areas": focus_areas,
        "senior_hypothesis": hypothesis,
        "instruction": (
            "SENIOR AUDITOR REVIEW: Re-examine this shipment with special attention to: "
            f"{', '.join(focus_areas)}. "
            f"The Senior Auditor suspects: {hypothesis}. "
            "Be more critical in your assessment of these areas."
        ),
    }
    
    try:
        result = await analyze_shipment(shipment)
        return {
            "original_score": case.get("model_risk_score"),
            "new_score": result.get("result", {}).get("risk_score"),
            "new_risk_level": result.get("result", {}).get("risk_level"),
            "new_flags": result.get("result", {}).get("flags", []),
            "new_recommendations": result.get("result", {}).get("recommendations", []),
            "model": result.get("model"),
            "latency_ms": result.get("latency_ms"),
        }
    except Exception as e:
        return {"error": str(e), "original_score": case.get("model_risk_score")}


async def _tavily_search(query: str, depth: str) -> dict[str, Any]:
    """Execute Tavily search for additional context."""
    if not query.strip():
        return {"error": "Empty query", "results": []}

    # `depth` now reaches the API. It previously did not: the tool schema
    # advertised a basic/advanced enum to Super, and this function quietly
    # translated the choice into a result count while the client hardcoded
    # "basic". A model told it has a control it does not have reasons on that
    # basis, so the schema and the request now agree.
    depth = depth if depth in ("basic", "advanced") else "basic"
    max_results = 5 if depth == "advanced" else 3

    try:
        results, status = await tavily_client.search_with_status(
            query, max_results=max_results, search_depth=depth,
        )
        out = {
            "query": query,
            "depth": depth,
            "status": status,
            "result_count": len(results),
            "results": results[:max_results],
        }
        if status in tavily_client.FAILED_STATUSES:
            # Named in the tool result so Super sees that the search failed
            # rather than inferring a clean company from an empty list.
            out["error"] = (
                f"search did not run ({status}); absence of findings here is not "
                "evidence of absence"
            )
        return out
    except Exception as e:
        return {"error": str(e), "query": query, "results": []}
