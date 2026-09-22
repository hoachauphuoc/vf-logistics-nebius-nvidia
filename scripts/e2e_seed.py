"""
Seed the six end-to-end audits the smoke test asserts against.

Every shipment carries a `client_reference`, so this script is safe to re-run:
the POST handler looks the reference up before doing any work and replays the
stored verdict instead of spending tokens again. That matters here because the
whole point of seeding against the deployed service is to exercise the real
Nebius and Tavily calls once, not once per debugging round.

The six are chosen to reach different branches of verifier.py rather than to
look varied on a screen. Three are deterministic -- their outcome is fixed by a
risk floor that no model can lower -- and three depend on what the models return,
which is recorded rather than asserted.

Legacy cases in Firestore predate `_tenant_id` and are invisible to the
tenant-scoped queries by design (a Firestore equality filter does not match
documents missing the field), so the console has nothing to show until these
exist.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "https://vf-logistics-f7rcctz26a-as.a.run.app"

# Ho Chi Minh City <-> Hanoi is in verifier.DOMESTIC_SAFE_ROUTES; 6109 is not in
# DUAL_USE_HS_PREFIXES. Both matter for the LOW_VALUE_DOMESTIC fast path.
SEEDS: list[dict[str, object]] = [
    {
        "//": (
            "Sanctions designation. 'Shell Trading Ltd' with identifier "
            "9999999999 is SEED-0001 in sanctions_seed.json under topic "
            "'sanction', which floors the score at 100. Also the case that "
            "proves evidence_urls is null rather than []: a list hit "
            "short-circuits the zero-day search, so no search is recorded, and "
            "the contract must say 'not searched' instead of 'found nothing'.\n"
            "\n"
            "A floor of 100 does NOT make this BLOCKED on its own. _OUTCOME_MAP "
            "reaches AuditOutcome.BLOCKED only from state BLOCKED_BY_HUMAN, so "
            "the workflow escalates and a named reviewer blocks -- there is no "
            "autonomous block, which is the same delegation argument as the "
            "governance gate. The review below is therefore part of the flow "
            "being tested, not a shortcut around it."
        ),
        "expect": "BLOCKED",
        "deterministic": True,
        "review": {
            "action": "block",
            "reviewer": "e2e-compliance-officer",
            "note": "OFAC designation confirmed against SEED-0001; shipment refused.",
        },
        "shipment": {
            "shipment_id": "E2E-SANCTION-001",
            "client_reference": "e2e-seed-sanction-001",
            "origin": "Jebel Ali",
            "destination": "Karachi",
            "weight_kg": 8400,
            "declared_value": 184000,
            "shipping_cost": 7300,
            "currency": "USD",
            "shipper_name": "Omar Haddad",
            "shipper_company": "Shell Trading Ltd",
            "shipper_country": "United Arab Emirates",
            "shipper_tax_id": "9999999999",
            "receiver_name": "Bilal Qureshi",
            "receiver_company": "Indus Industrial Supply",
            "receiver_country": "Pakistan",
            "cargo_description": "Industrial pumps and spare impellers",
            "hs_code": "8413",
            "route_details": "Jebel Ali to Karachi, direct sailing",
        },
    },
    {
        "//": (
            "Export-control listing rather than a sanctions designation. "
            "'Anadolu Teknik Makina Sanayi' is SEED-0005 under topic "
            "'export.control', which is a weaker basis than a designation and "
            "routes to a human instead of blocking outright."
        ),
        "expect": "HUMAN",
        "deterministic": True,
        "shipment": {
            "shipment_id": "E2E-EXPORTCTL-002",
            "client_reference": "e2e-seed-exportctl-002",
            "origin": "Istanbul",
            "destination": "Minsk",
            "weight_kg": 3100,
            "declared_value": 96500,
            "shipping_cost": 4100,
            "currency": "USD",
            "shipper_name": "Kemal Aydin",
            "shipper_company": "Anadolu Teknik Makina Sanayi",
            "shipper_country": "Turkey",
            "shipper_tax_id": "4455667788",
            "receiver_name": "Viktar Siarhei",
            "receiver_company": "Belparts Industrial",
            "receiver_country": "Belarus",
            "cargo_description": "CNC machine tool components and tooling sets",
            "hs_code": "8458",
            "route_details": "Istanbul to Minsk via road freight",
        },
    },
    {
        "//": (
            "Zero-day adverse media. No sanctions hit, so the gate in "
            "zero_day_agent.should_screen() is reachable -- a hit would skip "
            "the search entirely. Three of its reasons fire at once: dual-use "
            "HS 8542, a diversion hub in the route, and shipper_tx_count 0. "
            "The counterparty is a real firm with genuine press coverage, so "
            "Tavily returns real citations and evidence_urls is a populated "
            "list rather than an empty one."
        ),
        "expect": "MODEL",
        "deterministic": False,
        "shipment": {
            "shipment_id": "E2E-ZERODAY-003",
            "client_reference": "e2e-seed-zeroday-003",
            "origin": "Shanghai",
            "destination": "Hong Kong",
            "weight_kg": 420,
            "declared_value": 268000,
            "shipping_cost": 9200,
            "currency": "USD",
            "shipper_name": "Wei Zhang",
            "shipper_company": "Semiconductor Manufacturing International Corporation",
            "shipper_country": "China",
            "shipper_tax_id": "3100002200",
            "shipper_tx_count": 0,
            "receiver_name": "Andrei Volkov",
            "receiver_company": "Ural Microsystems OOO",
            "receiver_country": "Russia",
            "cargo_description": "Electronic integrated circuits, 28nm logic wafers",
            "hs_code": "8542",
            "route_details": "Shanghai to Hong Kong, onward transhipment",
            "transit_points": "Hong Kong",
        },
    },
    {
        "//": (
            "Declared heading contradicts the goods. 8471 is automatic data "
            "processing machines; frequency converters are 8504. Both headings "
            "are dual-use, so the mismatch carries the DUAL_USE variant at "
            "floor 80. Depends on the HS agent actually classifying the "
            "description, so the outcome is recorded rather than asserted."
        ),
        "expect": "MODEL",
        "deterministic": False,
        "shipment": {
            "shipment_id": "E2E-HSMISMATCH-004",
            "client_reference": "e2e-seed-hsmismatch-004",
            "origin": "Rotterdam",
            "destination": "Tehran",
            "weight_kg": 2650,
            "declared_value": 143000,
            "shipping_cost": 6400,
            "currency": "USD",
            "shipper_name": "Joost van Dijk",
            "shipper_company": "Maasdelta Technical Trading BV",
            "shipper_country": "Netherlands",
            "shipper_tax_id": "8877665544",
            "receiver_name": "Reza Mohammadi",
            "receiver_company": "Pars Process Control",
            "receiver_country": "Iran",
            "cargo_description": (
                "Frequency converters, 690V variable speed drives for "
                "centrifuge motor control"
            ),
            "hs_code": "8471",
            "route_details": "Rotterdam to Bandar Abbas, road to Tehran",
        },
    },
    {
        "//": (
            "The cost-control path. Under the 100 USD threshold on a domestic "
            "safe route with a non-dual-use heading, so "
            "check_low_value_domestic returns skip_ai and the case clears on "
            "arithmetic alone -- agent_calls must be 0. Freight is small on "
            "purpose: the lane baseline is deliberately not applied below the "
            "threshold, because charging a parcel against a commercial lane "
            "rate made this path unreachable.\n"
            "\n"
            "The shipper matches shipper_registry._BOOK exactly -- tax ID "
            "0301234567 is on the books as 'Saigon Textile Export JSC' with 412 "
            "prior shipments. Naming the same tax ID under any other company is "
            "SHIPPER_IDENTITY_MISMATCH at floor 75, which is a HIGH finding, and "
            "a HIGH finding defeats skip_ai by design: a fast-track claim on a "
            "shipment that otherwise looks wrong does not get a free pass."
        ),
        "expect": "CLEARED",
        "deterministic": True,
        "shipment": {
            "shipment_id": "E2E-LOWVALUE-005",
            "client_reference": "e2e-seed-lowvalue-005",
            "origin": "Ho Chi Minh City",
            "destination": "Hanoi",
            "weight_kg": 12,
            "declared_value": 85,
            "shipping_cost": 6,
            "currency": "USD",
            "shipper_name": "Nguyen Van Minh",
            "shipper_company": "Saigon Textile Export JSC",
            "shipper_country": "Vietnam",
            "shipper_tax_id": "0301234567",
            "shipper_tx_count": 412,
            "receiver_name": "Tran Thi Lan",
            "receiver_company": "Hanoi Garment Retail",
            "receiver_country": "Vietnam",
            "cargo_description": "Cotton t-shirts, assorted sizes",
            "hs_code": "6109",
            "route_details": "Ho Chi Minh City to Hanoi, domestic road freight",
        },
    },
    {
        "//": (
            "An ordinary commercial consignment with nothing wrong with it: "
            "clean counterparties, an established trading history, a "
            "non-dual-use heading and freight in line with the lane. It still "
            "goes through the models, and MAX_TOOL_ROUNDS is 2, so a forced "
            "verdict can land above the review threshold on a shipment carrying "
            "no findings at all -- which is exactly the case a reviewer "
            "releases. The release is what produces a genuine green row in the "
            "console, via RELEASED_BY_HUMAN rather than AUTO_CLEARED."
        ),
        "expect": "CLEARED",
        "deterministic": True,
        "review": {
            "action": "release",
            "reviewer": "e2e-compliance-officer",
            "note": "No deterministic findings; model score not supported by evidence. Released.",
        },
        "shipment": {
            "shipment_id": "E2E-CLEAN-006",
            "client_reference": "e2e-seed-clean-006",
            "origin": "Ho Chi Minh City",
            "destination": "Osaka",
            "weight_kg": 5800,
            "declared_value": 74500,
            "shipping_cost": 3950,
            "currency": "USD",
            "shipper_name": "Le Quoc Thang",
            "shipper_company": "Mekong Furniture Export JSC",
            "shipper_country": "Vietnam",
            "shipper_tax_id": "0302998877",
            "shipper_tx_count": 137,
            "receiver_name": "Hiroshi Tanaka",
            "receiver_company": "Tanaka Interiors KK",
            "receiver_country": "Japan",
            "cargo_description": "Wooden dining chairs and tables, flat packed",
            "hs_code": "9401",
            "route_details": "Ho Chi Minh City to Osaka, direct sailing",
        },
    },
]


def post_audit(base: str, shipment: dict, timeout: int) -> tuple[int, dict]:
    return _post(base, "/api/v1/compliance/audit", shipment, timeout)


def post_review(base: str, case_id: str, review: dict, timeout: int) -> tuple[int, dict]:
    """
    Apply a named reviewer's decision.

    Part of the flow rather than a fixture shortcut: BLOCKED and the
    released-by-human form of CLEARED are only reachable through this endpoint,
    because the workflow proposes and a human disposes.
    """
    return _post(base, f"/api/v1/review/{case_id}/decide", review, timeout)


def _auth_headers() -> dict[str, str]:
    """
    The operator credential this script needs to write anything.

    Seeding creates cases, so it is an operator action and the deployed service
    refuses it without a key -- anonymous callers hold viewer only, which is the
    whole point of that change. Read from the environment rather than taken as an
    argument so the value does not end up in shell history or a CI log:

        $env:VF_API_KEY = (gcloud secrets versions access latest --secret=VF_API_KEY)
        python scripts/e2e_seed.py

    Absent locally against STORE_BACKEND=memory, where ANONYMOUS_ROLE grants what
    is needed. Absent against the deployed service, every POST here returns 403.
    """
    key = os.getenv("VF_API_KEY", "").strip()
    return {"X-VF-API-Key": key} if key else {}


def _post(base: str, path: str, payload: dict, timeout: int) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base}{path}",
        data=body,
        headers={"Content-Type": "application/json", **_auth_headers()},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"error": raw[:400]}


def _get(base: str, path: str, timeout: int = 180) -> tuple[int, dict]:
    req = urllib.request.Request(f"{base}{path}", headers=_auth_headers())
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()

    base = args.base.rstrip("/")
    print(f"seeding {len(SEEDS)} audits against {base}\n")

    results = []
    for i, seed in enumerate(SEEDS, 1):
        shipment = seed["shipment"]
        sid = shipment["shipment_id"]
        started = time.time()
        status, payload = post_audit(base, shipment, args.timeout)
        took = time.time() - started

        if status != 200:
            print(f"[{i}/{len(SEEDS)}] {sid}\n    HTTP {status}: "
                  f"{json.dumps(payload)[:300]}")
            results.append({"shipment_id": sid, "http": status, "payload": payload})
            continue

        outcome = payload.get("outcome")
        replay = payload.get("idempotent_replay")
        usage = payload.get("usage") or {}
        findings = payload.get("findings") or []
        codes = [f.get("code") for f in findings]

        print(f"[{i}/{len(SEEDS)}] {sid}")
        print(f"    outcome={outcome}  risk={payload.get('effective_risk')}"
              f"  floor={payload.get('risk_floor')}"
              f"  replay={replay}  {took:.1f}s")
        print(f"    agent_calls={usage.get('agent_calls')}"
              f"  cost=${usage.get('estimated_cost_usd')}")
        print(f"    findings={codes}")
        results.append({
            "shipment_id": sid,
            "audit_id": payload.get("audit_id"),
            "case_id": payload.get("case_id"),
            "outcome": outcome,
            "expect": seed["expect"],
            "deterministic": seed["deterministic"],
            "review": seed.get("review"),
            "codes": codes,
        })
        print()

    pending_reviews = [r for r in results if r.get("review") and r.get("case_id")]
    if pending_reviews:
        print("-" * 72)
        print(f"applying {len(pending_reviews)} reviewer decisions\n")
        for r in pending_reviews:
            status, body = post_review(base, r["case_id"], r["review"], args.timeout)
            action = r["review"]["action"]
            if status != 200 or not body.get("ok", True):
                print(f"  {r['shipment_id']}: {action} -> HTTP {status} "
                      f"{json.dumps(body)[:200]}")
                r["outcome"] = None
                continue
            # Re-read rather than trusting the decision response: the console
            # reads outcome off the audit, so that is what must have changed.
            _, after = _get(base, f"/api/v1/compliance/audit/{r['audit_id']}")
            r["outcome"] = after.get("outcome")
            print(f"  {r['shipment_id']}: {action} -> {r['outcome']}")
        print()

    print("=" * 72)
    for r in results:
        mark = "?"
        if r.get("outcome"):
            if r["expect"] == "MODEL":
                mark = "rec"
            elif r["expect"] == "HUMAN":
                mark = "ok" if r["outcome"] in ("HELD_FOR_REVIEW", "PENDING_HUMAN") else "BAD"
            else:
                mark = "ok" if r["outcome"] == r["expect"] else "BAD"
        print(f"  {mark:3}  {r['shipment_id']:22} expect={r['expect']:9} "
              f"got={r.get('outcome')}")
    ok = sum(1 for r in results if r.get("outcome"))
    print(f"\ncompleted: {ok}/{len(SEEDS)}")
    return 0 if ok == len(SEEDS) else 1


if __name__ == "__main__":
    sys.exit(main())
