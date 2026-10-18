"""
Drive the two real Cloud Run faults on vf-app-faulttest (review 2026-10-18, open items 1 and 2).

Run by the operator with Application Default Credentials and the folder the setup wrote
(--secrets, default orchestrator/runs/faulttest: api_key.txt and session_secret.txt):

  python scripts/faulttest_run.py kill --base <url> --project <id>         service on FAULT=kill_after_publish
  python scripts/faulttest_run.py gateway504 --base <url> --project <id>   FAULT=slow_after_execute, --timeout 10
  python scripts/faulttest_run.py cleanup --project <id> --yes             deletes the faulttest tenant's documents

Each run seeds its own case in the tenant `faulttest` (Firestore of the project; the production
board is single-tenant and never reads it), releases it through the exception route as
op@faulttest.test with a session minted from the faulttest secret, and reads the outcome from the
case and from the count subscription on the faulttest topic. It never touches the default tenant or
the case-decisions topic.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

TENANT = "faulttest"
OPERATOR = "op@faulttest.test"
DOCS3 = ["certificate_of_origin", "producer_declaration", "input_purchase_invoices"]


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def mint_session(email: str, secret: str, *, amr: str = "password", ttl_seconds: int = 3600, now: float | None = None) -> str:
    """A console session token, the same wire format the console's login mints."""
    payload = {"email": email, "exp": (now if now is not None else time.time()) + ttl_seconds, "amr": amr}
    body = b64url(json.dumps(payload).encode("utf-8"))
    signature = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
    return f"{body}.{b64url(signature)}"


def shipment(case_id: str) -> dict[str, Any]:
    """Plywood, Vietnam to the US: a watched lane, so the papers are needed and missing ones are an exception."""
    return {
        "shipment_id": case_id, "shipper_name": "Saigon Plywood Co.", "shipper_tax_id": "VN0300000001",
        "shipper_tx_count": 40, "shipper_country": "Vietnam", "receiver_country": "United States",
        "origin": "Hai Phong Port, Vietnam", "destination": "Long Beach, United States",
        "hs_code": "4412.33", "cargo_description": "Hardwood plywood, 18 mm",
        "declared_value": 28000.0, "weight_kg": 22000.0, "currency": "USD",
        "shipping_cost": 3000.0, "avg_route_cost": 3000.0, "transport_mode": "sea",
    }


async def seed_case(case_id: str) -> dict[str, Any]:
    """A case held for review whose three papers were asked for and never came, in the faulttest tenant."""
    from vf_logistics import evidence
    from vf_logistics import store as store_mod
    from vf_logistics.verifier import validate

    ship = shipment(case_id)
    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    await store_mod.get_store().put_case({
        "case_id": case_id, "shipment_id": case_id, "state": "HELD_FOR_REVIEW",
        "created_at": now, "updated_at": now, "shipment": ship, "validation": validate(ship),
        "actions": [], "reviews": [], "risk_score": 45,
        "reconciliation": {"risk_floor": 45, "effective_risk": 50, "model_risk": 50},
    }, tenant_id=TENANT)
    out = await evidence.request_evidence(case_id, OPERATOR, documents=DOCS3, tenant_id=TENANT)
    await evidence.cancel_request(
        case_id, out["request"]["request_id"], OPERATOR, "fault test: the shipper did not answer",
        actor_auth="password", tenant_id=TENANT,
    )
    result = await evidence.reevaluate(case_id, tenant_id=TENANT)
    return {"state": result["state"], "unresolved": list(result["evaluation"]["unresolved"])}


def kill_verdict(after_kill: str, publish_rows: int, final: str, keys: list[str], key: str) -> list[tuple[str, bool, str]]:
    count = keys.count(key)
    return [
        ("the worker died after the broker accepted, before any record", after_kill == "EXECUTING" and publish_rows == 0,
         f"state after the kill {after_kill}, publish rows {publish_rows}"),
        ("the Resume after the lease completed the decision", final == "RELEASED_BY_HUMAN", f"final state {final}"),
        ("the decision is on the topic once", count == 1, f"{count} message(s) under {key}"),
    ]


def gateway_verdict(execute_status: int, final: str, retry_status: int, keys: list[str], key: str) -> list[tuple[str, bool, str]]:
    count = keys.count(key)
    return [
        ("Cloud Run answered Execute with 504", execute_status == 504, f"HTTP {execute_status}"),
        ("the work was done behind the 504", final == "RELEASED_BY_HUMAN", f"final state {final}"),
        ("a retry is refused, not sent again", retry_status == 409, f"HTTP {retry_status}"),
        ("the decision is on the topic once", count == 1, f"{count} message(s) under {key}"),
    ]


def exit_code(rows: list[tuple[str, bool, str]]) -> int:
    return 0 if all(ok for _, ok, _ in rows) else 1


def _secrets(folder: str) -> tuple[str, str]:
    base = Path(folder)
    return (base / "api_key.txt").read_text().strip(), (base / "session_secret.txt").read_text().strip()


def _api(base: str, method: str, path: str, headers: dict[str, str], body: Any = None, timeout: float = 120) -> tuple[int, Any]:
    """(HTTP status, JSON or None); 0 when the connection broke."""
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - the operator's own service
            raw = response.read()
            return int(response.status), json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        try:
            return int(exc.code), json.loads(exc.read() or b"null")
        except ValueError:
            return int(exc.code), None
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
        return 0, None


def _case(base: str, headers: dict[str, str], case_id: str) -> dict[str, Any]:
    """The case, read again until the service answers (a killed worker is being replaced)."""
    for _ in range(30):
        status, body = _api(base, "GET", f"/api/v1/orchestrator/case/{case_id}", headers)
        if status == 200 and isinstance(body, dict):
            return body
        time.sleep(4)
    raise SystemExit(f"the service did not return case {case_id}")


def _keys(project: str, subscription: str, wait_s: float = 90) -> list[str]:
    """Idempotency keys of the messages on the count subscription, acknowledged as read."""
    from google.api_core.exceptions import DeadlineExceeded
    from google.cloud import pubsub_v1

    subscriber = pubsub_v1.SubscriberClient()
    path = subscriber.subscription_path(project, subscription)
    keys: list[str] = []
    deadline = time.time() + wait_s
    while time.time() < deadline:
        try:
            response = subscriber.pull(subscription=path, max_messages=50, timeout=10)
        except DeadlineExceeded:
            continue
        for received in response.received_messages:
            keys.append(received.message.attributes.get("idempotency_key", ""))
        if response.received_messages:
            subscriber.acknowledge(subscription=path, ack_ids=[r.ack_id for r in response.received_messages])
    return keys


def _approve(base: str, headers: dict[str, str], case_id: str, unresolved: list[str]) -> str:
    status, body = _api(base, "POST", f"/api/v1/review/{case_id}/approve-exception", headers, {
        "reason": "fault test: releasing over papers that never came, recorded as an exception",
        "waived": unresolved,
    })
    if status != 200 or not isinstance(body, dict):
        raise SystemExit(f"approve-exception answered HTTP {status}: {body}")
    return str(body["approval"]["approval_id"])


def _prepare(args: argparse.Namespace, prefix: str) -> tuple[dict[str, str], str, str]:
    import asyncio

    api_key, secret = _secrets(args.secrets)
    headers = {"X-VF-API-Key": api_key, "X-VF-Session": mint_session(OPERATOR, secret), "X-VF-Tenant": TENANT}
    case_id = f"{prefix}-{int(time.time())}"
    seeded = asyncio.run(seed_case(case_id))
    print(f"seeded {case_id} in tenant {TENANT}: {seeded['state']}, unresolved {seeded['unresolved']}")
    approval_id = _approve(args.base, headers, case_id, seeded["unresolved"])
    print(f"approved as an exception: {approval_id}")
    return headers, case_id, approval_id


def run_kill(args: argparse.Namespace) -> list[tuple[str, bool, str]]:
    headers, case_id, approval_id = _prepare(args, "FT-KILL")
    status, _ = _api(args.base, "POST", f"/api/v1/review/{case_id}/execute", headers, {"approval_id": approval_id})
    print(f"execute answered HTTP {status} (the worker is meant to die)")
    case = _case(args.base, headers, case_id)
    rows_status, rows = _api(args.base, "GET", f"/api/v1/audit?case_id={case_id}&action=publish_decision", headers)
    publish_rows = len((rows or {}).get("items") or []) if rows_status == 200 else -1
    after_kill = str(case.get("state"))
    executions = (case.get("verification") or {}).get("executions") or [{}]
    lease_ends = float(executions[-1].get("claim_expires_epoch") or 0)
    wait = max(0.0, lease_ends - time.time()) + 5
    print(f"state {after_kill}, publish rows {publish_rows}; waiting {wait:.0f}s for the lease")
    time.sleep(wait)
    status, body = _api(args.base, "POST", f"/api/v1/review/{case_id}/execute", headers, {"approval_id": approval_id})
    print(f"resume answered HTTP {status}")
    final = str(_case(args.base, headers, case_id).get("state"))
    return kill_verdict(after_kill, publish_rows, final, _keys(args.project, args.count_subscription), f"exec-{approval_id}")


def run_gateway504(args: argparse.Namespace) -> list[tuple[str, bool, str]]:
    headers, case_id, approval_id = _prepare(args, "FT-504")
    status, _ = _api(args.base, "POST", f"/api/v1/review/{case_id}/execute", headers, {"approval_id": approval_id})
    print(f"execute answered HTTP {status}")
    time.sleep(5)
    final = str(_case(args.base, headers, case_id).get("state"))
    retry, body = _api(args.base, "POST", f"/api/v1/review/{case_id}/execute", headers, {"approval_id": approval_id})
    print(f"retry answered HTTP {retry}: {body}")
    return gateway_verdict(status, final, retry, _keys(args.project, args.count_subscription), f"exec-{approval_id}")


def run_cleanup(args: argparse.Namespace) -> None:
    if not args.yes:
        raise SystemExit("cleanup deletes every document of the tenant faulttest; re-run with --yes")
    from google.cloud import firestore

    db = firestore.Client(project=args.project)
    removed = 0
    for collection in ("cases", "events", "audit_log", "applied_decisions", "operator_activity"):
        for doc in db.collection(collection).where(filter=firestore.FieldFilter("_tenant_id", "==", TENANT)).stream():
            doc.reference.delete()
            removed += 1
    print(f"removed {removed} document(s) of tenant {TENANT}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Real Cloud Run faults on vf-app-faulttest")
    parser.add_argument("command", choices=("kill", "gateway504", "cleanup"))
    parser.add_argument("--base", default="", help="the vf-app-faulttest URL")
    parser.add_argument("--project", default=os.getenv("PROJECT_ID", ""))
    parser.add_argument("--secrets", default=str(ROOT / "orchestrator" / "runs" / "faulttest"))
    parser.add_argument("--count-subscription", default="faulttest-count")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    if not args.project:
        parser.error("give --project or set PROJECT_ID")
    os.environ.update({"STORE_BACKEND": "firestore", "PROJECT_ID": args.project, "MULTI_TENANT": "true"})
    if args.command == "cleanup":
        run_cleanup(args)
        return 0
    if not args.base:
        parser.error("give --base")
    args.base = args.base.rstrip("/")
    rows = run_kill(args) if args.command == "kill" else run_gateway504(args)
    for name, ok, detail in rows:
        print(f"[{'PASS' if ok else 'FAIL'}] {name} - {detail}")
    return exit_code(rows)


if __name__ == "__main__":
    sys.exit(main())
