"""
Evaluate the verification loop against data/verification_cases.json.

Runs each case through the full loop (request -> submit -> reevaluate -> approve
-> execute) using STORE_BACKEND=memory, and measures the five metrics from the
restructuring proposal:

  1. Number of request rounds (should be 1 for all)
  2. Resolution rate for legitimate cases
  3. Improper executions (target: 0 in this test set)
  4. Cost per resolved case (median, p95)
  5. Latency (median, p95)

Usage: python scripts/run_verification_eval.py [--output data/eval_results/verification_eval.json]
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
import time
from unittest.mock import AsyncMock, patch

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

ENV = {
    "VF_API_KEY": "eval-key-32-characters-long-xxxx",
    "VF_SESSION_SECRET": "eval-secret-32-characters-long-x",
    "IAP_ENABLED": "false",
    "MULTI_TENANT": "false",
    "ANONYMOUS_ROLE": "viewer",
    "STORE_BACKEND": "memory",
    "REVIEWER_EMAILS": "eval@reviewer.example",
}


def run(coro):
    return asyncio.run(coro)


def tiny_pdf():
    try:
        from fpdf import FPDF
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=10)
        pdf.cell(text="DEMO EVIDENCE DOCUMENT")
        return bytes(pdf.output())
    except ImportError:
        return b"%PDF-1.0 fake"


REVIEWER = "eval@reviewer.example"


def evaluate_case(case_spec):
    from vf_logistics import evidence, store as store_mod
    from vf_logistics.verifier import validate

    store_mod._store = None
    store = store_mod.get_store()

    shipment = case_spec["shipment"]
    case_id = shipment["shipment_id"]
    result = {
        "id": case_spec["id"],
        "group": case_spec["group"],
        "expected": case_spec["expected_outcome"],
        "request_rounds": 0,
        "resolved": False,
        "final_state": None,
        "improper_execution": False,
        "cost_usd": 0.0,
        "latency_ms": 0,
        "error": None,
    }

    try:
        # Ingest the case
        case = {
            "case_id": case_id, "shipment_id": case_id, "state": "HELD_FOR_REVIEW",
            "created_at": "2026-10-13T00:00:00+00:00", "updated_at": "2026-10-13T00:00:00+00:00",
            "shipment": shipment, "validation": validate(shipment), "actions": [], "reviews": [],
            "risk_score": 45, "reconciliation": {"risk_floor": 45, "effective_risk": 50, "model_risk": 50},
        }
        run(store.put_case(case))

        t0 = time.monotonic()
        evidence_data = case_spec.get("evidence")

        if evidence_data is None:
            # No evidence to submit -- case stays held
            result["final_state"] = "HELD_FOR_REVIEW"
            result["resolved"] = False
        else:
            # Request evidence (1 doc per type that we have)
            doc_types = list(evidence_data.keys())
            out = run(evidence.request_evidence(case_id, REVIEWER, documents=doc_types))
            result["request_rounds"] = 1

            # Submit each document
            for dt in doc_types:
                extracted = evidence_data[dt]
                mock_extraction = {
                    "agent": "evidence_extraction", "model": "nemotron-nano",
                    "result": extracted,
                    "latency_ms": 50, "input_tokens": 200, "output_tokens": 100,
                    "parse_error": False, "at": "2026-10-13T01:00:00Z",
                }
                with patch("vf_logistics.agents.document_agent.extract_evidence", new=AsyncMock(return_value=mock_extraction)):
                    with patch("vf_logistics.model_armor.screen", new=AsyncMock(return_value={"blocked": False})):
                        with patch("vf_logistics.model_armor.extract_pdf_text", return_value=("text", None)):
                            with patch("vf_logistics.document_store.archive", new=AsyncMock(return_value={"archived": True, "uri": f"gs://eval/{case_id}/{dt}"})):
                                run(evidence.receive_evidence(out["token"], tiny_pdf(), f"{dt}.pdf", "application/pdf"))

            # Reevaluate
            run(evidence.reevaluate(case_id))

            # E01: decide based on evaluation status, NOT on expected_outcome.
            stored_mid = run(store.get_case(case_id))
            record = (stored_mid or {}).get("verification") or {}
            evals = record.get("evaluations") or []
            latest_eval = evals[-1] if evals else {}
            eval_status = latest_eval.get("status", "missing")
            eval_contradictions = latest_eval.get("contradictions") or []
            eval_unresolved = latest_eval.get("unresolved") or []

            if eval_status == "provided" and not eval_contradictions:
                action = "release"
            elif eval_contradictions or eval_status == "contradicted":
                action = "block"
            else:
                # missing or unresolved -- do not approve, stay in review
                action = None

            if action:
                approve_result = run(evidence.approve(
                    case_id, action, REVIEWER, actor_auth="password",
                    note="Eval-based decision" if eval_unresolved else "",
                ))
                approval_id = approve_result["approval"]["approval_id"]

                ok_receipt = {"detail": {"message_id": f"msg-eval-{case_id}"}, "status": "done"}
                with patch("vf_logistics.tools.publish_decision", new=AsyncMock(return_value=ok_receipt)):
                    exec_result = run(evidence.execute_approval(
                        case_id, approval_id, REVIEWER, actor_auth="password",
                    ))

                result["final_state"] = exec_result["state"]
                result["resolved"] = exec_result["state"] in ("RELEASED_BY_HUMAN", "BLOCKED_BY_HUMAN")
            else:
                stored_after = run(store.get_case(case_id))
                result["final_state"] = stored_after.get("state")
                result["resolved"] = False

            # Check for improper execution
            if result["final_state"] != case_spec["expected_outcome"]:
                result["improper_execution"] = True

        elapsed = time.monotonic() - t0
        result["latency_ms"] = round(elapsed * 1000)

        stored = run(store.get_case(case_id))
        result["cost_usd"] = stored.get("_estimated_cost_usd") or 0.0

    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["final_state"] = "ERROR"

    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/eval_results/verification_eval.json")
    args = parser.parse_args()

    cases_path = os.path.join(os.path.dirname(__file__), "..", "data", "verification_cases.json")
    with open(cases_path) as f:
        cases = json.load(f)

    with patch.dict(os.environ, ENV):
        results = []
        for case_spec in cases:
            r = evaluate_case(case_spec)
            status = "OK" if not r["error"] else f"ERR: {r['error']}"
            print(f"  {r['id']:15s} {r['group']:15s} -> {r['final_state'] or 'N/A':25s} {status}")
            results.append(r)

    # Aggregate
    resolved = [r for r in results if r["resolved"]]
    legitimate = [r for r in results if r["group"] == "legitimate"]
    legitimate_resolved = [r for r in legitimate if r["resolved"]]
    improper = [r for r in results if r["improper_execution"]]
    costs = [r["cost_usd"] for r in resolved if r["cost_usd"] > 0]
    latencies = [r["latency_ms"] for r in resolved if r["latency_ms"] > 0]

    summary = {
        "total_cases": len(results),
        "resolved": len(resolved),
        "resolution_rate_legitimate": f"{len(legitimate_resolved)}/{len(legitimate)}" if legitimate else "N/A",
        "improper_executions": len(improper),
        "improper_details": [{"id": r["id"], "expected": r["expected"], "actual": r["final_state"]} for r in improper],
        "request_rounds_median": statistics.median([r["request_rounds"] for r in results]) if results else 0,
        "cost_usd_median": round(statistics.median(costs), 6) if costs else 0,
        "cost_usd_p95": round(sorted(costs)[int(len(costs) * 0.95)] if len(costs) > 1 else (costs[0] if costs else 0), 6),
        "latency_ms_median": round(statistics.median(latencies)) if latencies else 0,
        "latency_ms_p95": round(sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) > 1 else (latencies[0] if latencies else 0)),
        "cases": results,
    }

    print("\n--- Summary ---")
    print(f"  Total: {summary['total_cases']}")
    print(f"  Resolved: {summary['resolved']}")
    print(f"  Legitimate resolved: {summary['resolution_rate_legitimate']}")
    print(f"  Improper executions: {summary['improper_executions']} (target: 0)")
    print(f"  Cost median: ${summary['cost_usd_median']}")
    print(f"  Latency median: {summary['latency_ms_median']}ms")

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\n  Written to {args.output}")
    return 1 if summary["improper_executions"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
