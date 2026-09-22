"""
Clear the board and seed 20 cases covering the reachable decision branches.

Why a new script rather than reusing the two that exist: `e2e_seed.py` seeds six
fixed cases and is idempotent by `client_reference`, which is right for asserting
a contract but means it will not produce a twenty-case board; `seed_demo_board.py`
steers three outcome buckets with hardcoded counts and no way to ask for a
specific finding.

This one is organised by *finding code* instead of by outcome, because the
finding is what a reviewer reads and what the risk floor is computed from. The 29
codes in verifier.py are not all reachable by shaping a shipment -- the three
`*_UNAVAILABLE` codes require an external dependency to fail, and the
`ZERO_DAY_*` and `HS_DESCRIPTION_*` families depend on what a model returns -- so
this script states an intent per case and then reports what actually happened.
That distinction is the point: a seeding script that asserts model-dependent
outcomes fails for the wrong reason, and one that asserts nothing tells you
nothing.

Destructive. It resets the tenant's board first, which cannot be undone.

    $env:VF_API_KEY = (gcloud secrets versions access latest --secret=VF_API_KEY)
    python scripts/seed_full_board.py --yes

Writes need an operator credential; anonymous callers hold viewer only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

DEFAULT_BASE = "https://vf-logistics-f7rcctz26a-as.a.run.app"

# Values that must match the deployed prefilter rules and reference data. Quoted
# from verifier.PrefilterRules.defaults() and data/sanctions_seed.json rather
# than invented, because a near-miss silently produces an ordinary case and the
# branch goes untested while the board still looks full.
SANCTIONED_COMPANY = "Shell Trading Ltd"      # SEED-0001, topic 'sanction'
SANCTIONED_TAX_ID = "9999999999"
BLACKLISTED_COMPANY = "Golden Star Trading"   # blacklist_companies
BLACKLISTED_TAX_ID = "1234567890"             # blacklist_tax_ids
VIP_COMPANY = "Vinamilk Joint Stock Company"  # vip_registry, with its real id
VIP_TAX_ID = "0100107518"
VIP_OTHER_TAX_ID = "0101245486"               # FPT's id, used under a wrong name


def _iso(minutes_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _base(**over) -> dict:
    """
    A consignment that on its own draws no finding.

    Every case below starts here and changes only the fields its branch needs, so
    a finding that appears is attributable to the edit rather than to whatever the
    generator happened to pick. Manufactured non-agricultural cargo: wood and
    produce draw phytosanitary and ISPM 15 findings from the compliance agent and
    escalate at any risk score, which would mask the branch under test.
    """
    shipment = {
        "origin": "Cat Lai Port, Ho Chi Minh City, Vietnam",
        # The country is stated as its own comma-separated part on purpose.
        # lane_baseline() derives the lane from _country(), which takes the text
        # after the last comma; a bare "PSA Singapore" therefore resolves to the
        # country "psa singapore", misses the (vietnam, singapore) lane entry of
        # 1200 USD, and falls back to the 1800 USD corridor default. Freight of
        # 1240 USD is 103% of the real baseline but only 69% of the fallback,
        # and 69% is under the 70% floor -- so the supposedly clean base case
        # carried a MEDIUM FREIGHT_ANOMALY, and so did every case built on it.
        "destination": "PSA Singapore, Singapore",
        "receiver_country": "Singapore",
        "shipper_country": "Vietnam",
        "shipper_name": "Truong Hai Trading Co",
        "shipper_company": "Truong Hai Trading Co",
        "shipper_tax_id": "0301447722",
        "receiver_name": "Pacific Sourcing Pte Ltd",
        "receiver_company": "Pacific Sourcing Pte Ltd",
        "cargo_description": "Woven cotton garments, retail packed",
        "hs_code": "6205.20",
        "weight_kg": 620,
        "declared_value": 7_400,
        "shipping_cost": 1_240,
        "currency": "USD",
        "route_details": (
            "Port of Loading: Cat Lai Port, Ho Chi Minh City; "
            "Port of Discharge: PSA Singapore; direct sailing"
        ),
        "transit_points": "None",
        "shipper_tx_count": 480,
        "status": "pending",
        "created_at": _iso(90),
    }
    shipment.update(over)
    return shipment


# (shipment_id, intent, expected finding codes, shipment)
#
# `expected` is what the case is built to trigger. It is reported against what
# actually appeared rather than asserted, because several of these depend on a
# model reply. A case whose expectation is empty is meant to be clean.
CASES: list[tuple[str, str, list[str], dict]] = [
    # ---- clean and fast-path clears -------------------------------------
    (
        "FULL-01-CLEAN", "ordinary consignment, nothing adverse", [],
        _base(),
    ),
    (
        "FULL-02-WHITELIST", "known VIP shipper with its registered tax id",
        ["WHITELIST_MATCH"],
        _base(
            shipper_name=VIP_COMPANY, shipper_company=VIP_COMPANY,
            shipper_tax_id=VIP_TAX_ID, shipper_tx_count=2_400,
        ),
    ),
    (
        "FULL-03-LOWVALUE", "domestic safe route under the low-value threshold",
        ["LOW_VALUE_DOMESTIC"],
        _base(
            # Both endpoints must normalise to exactly the entries in
            # rules.safe_routes: the check compares the (origin, destination)
            # tuple by equality, so a trailing ", Vietnam" on either side misses
            # ('ho chi minh city', 'hanoi') and the shipment is priced as an
            # ordinary consignment instead of auto-clearing.
            origin="Ho Chi Minh City", destination="Hanoi",
            receiver_country="Vietnam",
            receiver_name="An Khang Co Ltd", receiver_company="An Khang Co Ltd",
            cargo_description="Replacement sewing machine needles",
            hs_code="8452.30", weight_kg=4, declared_value=85,
            shipping_cost=12,
            route_details="Ho Chi Minh City to Hanoi; domestic road freight",
        ),
    ),
    (
        "FULL-04-CLEAN2", "second ordinary consignment on a different lane", [],
        _base(
            origin="Hai Phong Port, Vietnam",
            shipper_name="Viet Tien JSC", shipper_company="Viet Tien JSC",
            shipper_tax_id="0200338811",
            cargo_description="Ceramic tableware", hs_code="6912.00",
            weight_kg=900, declared_value=9_800, shipping_cost=1_390,
            shipper_tx_count=610,
        ),
    ),

    # ---- deterministic hard floors --------------------------------------
    (
        "FULL-05-SANCTIONS", "sanctioned counterparty in the seeded index",
        ["SANCTIONS_MATCH"],
        _base(
            receiver_name=SANCTIONED_COMPANY, receiver_company=SANCTIONED_COMPANY,
            receiver_country="Singapore",
            # Deliberately NOT SANCTIONED_TAX_ID: that value is also in
            # blacklist_tax_ids, so using it made this case fire BLACKLIST_TAX_ID
            # and never exercise the sanctions index at all -- the branch under
            # test was shadowed by a cheaper one that runs first.
            shipper_tax_id="0302556611",
            # 3900 USD would be 325% of the 1200 USD lane baseline, tripping the
            # over-invoicing arm of the freight check as an unintended finding.
            declared_value=184_000, weight_kg=2_100, shipping_cost=2_600,
        ),
    ),
    (
        "FULL-06-BLACKLIST", "shipper company on the prefilter blacklist",
        ["BLACKLIST_MATCH"],
        _base(
            shipper_name=BLACKLISTED_COMPANY, shipper_company=BLACKLISTED_COMPANY,
            declared_value=52_000, weight_kg=1_400, shipping_cost=1_900,
        ),
    ),
    (
        "FULL-07-BLACKTAX", "blacklisted tax id under an unremarkable name",
        ["BLACKLIST_TAX_ID"],
        _base(
            shipper_tax_id=BLACKLISTED_TAX_ID,
            declared_value=48_000, weight_kg=1_200, shipping_cost=1_750,
        ),
    ),
    (
        "FULL-08-VIPMISMATCH",
        "a registered VIP tax id presented under a different company",
        ["WHITELIST_IDENTITY_MISMATCH"],
        _base(
            shipper_name="Minh Phuong Logistics Co Ltd",
            shipper_company="Minh Phuong Logistics Co Ltd",
            shipper_tax_id=VIP_OTHER_TAX_ID,
            declared_value=66_000, weight_kg=1_500, shipping_cost=2_100,
        ),
    ),

    # ---- route and destination controls ---------------------------------
    (
        "FULL-09-HIGHRISK", "destination on the high-risk list",
        ["HIGH_RISK_DESTINATION"],
        _base(
            destination="Bandar Abbas, Iran", receiver_country="Iran",
            receiver_name="Persia Industrial Supply",
            receiver_company="Persia Industrial Supply",
            declared_value=143_000, weight_kg=1_800, shipping_cost=4_600,
            route_details=(
                "Port of Loading: Cat Lai; Port of Discharge: Bandar Abbas; "
                "transhipment at Jebel Ali"
            ),
            transit_points="Jebel Ali",
        ),
    ),
    (
        "FULL-10-DIVERSION", "two diversion hubs on one routing",
        ["MULTIPLE_DIVERSION_HUBS"],
        _base(
            destination="Karachi, Pakistan", receiver_country="Pakistan",
            receiver_name="Indus Trade House", receiver_company="Indus Trade House",
            declared_value=96_000, weight_kg=1_600, shipping_cost=3_100,
            route_details=(
                "Port of Loading: Cat Lai; transhipment at Singapore then Dubai; "
                "Port of Discharge: Karachi"
            ),
            transit_points="Singapore, Dubai",
        ),
    ),
    (
        "FULL-11-ROUTECHANGE", "routing amended after booking",
        ["ROUTE_CHANGED_AFTER_BOOKING"],
        _base(
            destination="Hong Kong", receiver_country="Hong Kong",
            receiver_name="Kowloon Supply Ltd", receiver_company="Kowloon Supply Ltd",
            declared_value=71_000, weight_kg=1_300, shipping_cost=2_050,
            route_details=(
                "Original routing Cat Lai to Hong Kong direct; "
                "route changed after booking to add transhipment at Kaohsiung"
            ),
            transit_points="Kaohsiung",
        ),
    ),

    # ---- classification controls ----------------------------------------
    (
        "FULL-12-DUALUSE", "dual-use HS heading",
        ["DUAL_USE_HS_CODE"],
        _base(
            cargo_description="Industrial frequency converters, 400V",
            hs_code="8504.40",
            declared_value=88_000, weight_kg=740, shipping_cost=1_620,
        ),
    ),
    (
        "FULL-13-HSMALFORMED", "HS code that is not a valid heading",
        ["HS_CODE_MALFORMED"],
        _base(
            cargo_description="Assorted textile accessories", hs_code="99",
            declared_value=23_000, weight_kg=800, shipping_cost=1_300,
        ),
    ),
    (
        "FULL-14-HSMISMATCH",
        "description and declared heading describe different goods",
        ["HS_DESCRIPTION_MISMATCH_DUAL_USE", "HS_DESCRIPTION_MISMATCH_LOW_CONFIDENCE"],
        _base(
            cargo_description=(
                "Flat-pack wooden office furniture, seats and chairs"
            ),
            hs_code="9403.60",
            declared_value=24_400, weight_kg=1_100, shipping_cost=1_180,
        ),
    ),

    # ---- pricing and density controls -----------------------------------
    (
        "FULL-15-FREIGHTMISSING", "no freight charge stated",
        ["FREIGHT_MISSING"],
        _base(
            shipping_cost=0,
            declared_value=34_000, weight_kg=1_000,
        ),
    ),
    (
        "FULL-16-FREIGHTANOMALY", "freight far below the lane baseline",
        ["FREIGHT_ANOMALY"],
        _base(
            shipping_cost=180,
            declared_value=41_000, weight_kg=1_500,
        ),
    ),
    (
        "FULL-17-DENSITYHIGH", "implausibly high value per kilogram",
        ["VALUE_DENSITY_HIGH"],
        _base(
            cargo_description="Precision optical assemblies",
            hs_code="9002.11",
            weight_kg=12, declared_value=268_000, shipping_cost=1_450,
        ),
    ),
    (
        "FULL-18-DENSITYLOW", "implausibly low value per kilogram",
        ["VALUE_DENSITY_LOW"],
        _base(
            cargo_description="Mixed baled textile offcuts",
            hs_code="6310.90",
            weight_kg=24_000, declared_value=2_600, shipping_cost=2_300,
        ),
    ),

    # ---- counterparty history controls ----------------------------------
    (
        "FULL-19-NOHISTORY", "counterparty with no prior shipments on file",
        ["SHIPPER_NO_HISTORY", "SHIPPER_HISTORY_UNVERIFIED"],
        _base(
            shipper_name="Hoang Lam Export Co Ltd",
            shipper_company="Hoang Lam Export Co Ltd",
            shipper_tax_id="0316998877",
            shipper_tx_count=0,
            created_at=_iso(30),
            declared_value=57_000, weight_kg=1_100, shipping_cost=1_560,
        ),
    ),
    (
        "FULL-20-THINHISTORY", "counterparty with only a handful of shipments",
        ["SHIPPER_THIN_HISTORY", "RECENTLY_REGISTERED_SHIPPER"],
        _base(
            shipper_name="Bao Tin Shipping JSC",
            shipper_company="Bao Tin Shipping JSC",
            shipper_tax_id="0317334455",
            shipper_tx_count=6,
            created_at=_iso(10),
            declared_value=31_500, weight_kg=900, shipping_cost=1_120,
        ),
    ),
]

# Reviewer decisions applied afterwards, so the board carries the two
# human-action states as well. BLOCKED is only reachable from a held state via a
# named reviewer -- there is no autonomous block -- and a release records who
# released it. Chosen to be defensible: the sanctions hit is blocked, the
# whitelisted VIP is released if it ended up held at all.
DECISIONS = [
    ("FULL-05-SANCTIONS", "block",
     "Counterparty matches a sanctions designation; shipment withheld pending "
     "licence review."),
    ("FULL-06-BLACKLIST", "block",
     "Shipper is on the internal blacklist; consignment refused."),
    ("FULL-16-FREIGHTANOMALY", "release",
     "Freight verified against the carrier's own quotation; the discount is a "
     "contracted volume rate, not an undervaluation."),
    ("FULL-20-THINHISTORY", "release",
     "Thin history confirmed as a genuinely new but verified exporter; "
     "documentation checked against the business registration."),
]

REVIEWER = "seed-operator"


def _headers(extra: dict | None = None) -> dict[str, str]:
    key = os.getenv("VF_API_KEY", "").strip()
    headers = dict(extra or {})
    if key:
        headers["X-VF-API-Key"] = key
    return headers


def _request(base: str, path: str, method: str, body: dict | None, timeout: int):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    extra = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(
        f"{base}{path}", data=data, headers=_headers(extra), method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"error": raw[:300]}


def post(base, path, body, timeout=300):
    return _request(base, path, "POST", body, timeout)


def get(base, path, timeout=180):
    return _request(base, path, "GET", None, timeout)


def settle(base: str, timeout_s: int = 240, interval_s: int = 5) -> list[dict]:
    """
    Wait until no case is mid-flight, then return the board.

    Reading immediately after a POST is not safe: the response can arrive while
    the case is still short of a terminal state, so a tally taken then misses it.
    """
    in_flight = {"INGESTED", "SPECIALISTS_DONE", "INVESTIGATED"}
    waited = 0
    while True:
        _, page = get(base, "/api/v1/cases?limit=100")
        cases = page.get("items") or []
        if not any(c.get("state") in in_flight for c in cases):
            return cases
        if waited >= timeout_s:
            print(f"  warn  still in flight after {waited}s; continuing")
            return cases
        time.sleep(interval_s)
        waited += interval_s


def detail(base: str, case_id: str) -> dict:
    """
    Fetch the full case.

    `/api/v1/cases` is a deliberately slim listing -- case_id, shipment_id, state,
    risk_score, compliance_status, source, claimed, created_at -- and carries
    neither `validation` nor `provenance`. Reading findings off the listing would
    report every case as having produced none, so the coverage table below would
    be uniformly and silently wrong.
    """
    status, body = get(base, f"/api/v1/orchestrator/case/{case_id}")
    return body if status == 200 else {}


def findings_of(case: dict) -> list[str]:
    validation = case.get("validation") or {}
    return sorted({
        f.get("code") for f in (validation.get("findings") or []) if f.get("code")
    })


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument(
        "--yes", action="store_true",
        help="Required. Resetting the board deletes every case and cannot be undone.",
    )
    ap.add_argument(
        "--report-only", action="store_true",
        help=(
            "Skip the reset, the seeding and the decisions; just re-read the board "
            "and print the coverage table. Seeding twenty cases costs real model "
            "calls, so a failure in the report must not force a reseed."
        ),
    )
    args = ap.parse_args()

    if not args.report_only and not args.yes:
        print("Refusing to reset without --yes. This deletes every case.")
        return 2

    if not os.getenv("VF_API_KEY", "").strip():
        print(
            "VF_API_KEY is not set. Writes need an operator credential; without "
            "one every POST below returns 403.\n"
            "  $env:VF_API_KEY = (gcloud secrets versions access latest "
            "--secret=VF_API_KEY)"
        )
        return 2

    print(f"target: {args.base}\n")

    if args.report_only:
        print("report-only: leaving the board exactly as it is\n")
    else:
        print("clearing the board")
        status, body = post(args.base, "/api/v1/orchestrator/reset", {}, 180)
        if status != 200:
            print(f"  reset failed: {status} {body}")
            return 1
        print(f"  cleared {body.get('cleared')} cases\n")

        print(f"seeding {len(CASES)} cases")
        print("-" * 74)
        posted: dict[str, str] = {}
        for n, (sid, intent, _expected, shipment) in enumerate(CASES, 1):
            payload = dict(shipment, shipment_id=sid)
            status, body = post(
                args.base, "/api/v1/events/shipment", payload, args.timeout
            )
            if status not in (200, 201, 202):
                print(f"[{n:2}/{len(CASES)}] {sid:22} POST {status} {str(body)[:90]}")
                continue
            case_id = body.get("case_id") or f"CASE-{sid}"
            posted[sid] = case_id
            print(f"[{n:2}/{len(CASES)}] {sid:22} {intent}")

        print("\nwaiting for the board to settle")
        settle(args.base)

        print(f"\napplying {len(DECISIONS)} reviewer decisions")
        for sid, action, note in DECISIONS:
            case_id = posted.get(sid)
            if not case_id:
                print(f"  skip  {sid}: was not created")
                continue
            status, body = post(
            args.base, f"/api/v1/review/{case_id}/decide",
            # The route reads `note`, not `reason`. Sending `reason` is silently
            # dropped, which leaves the reviewer's justification blank on a case
            # that reads as decided -- worse than an error, because it looks fine.
            {"action": action, "reviewer": REVIEWER, "note": note}, 180,
            )
            got = body.get("state") or body.get("error") or status
            print(f"  {sid:22} {action:8} -> {got}")

    # ---- coverage report -------------------------------------------------
    cases = settle(args.base)
    by_shipment = {c.get("shipment_id"): c for c in cases}

    print("\n" + "=" * 74)
    print("coverage: intended finding vs what the pipeline produced")
    print("=" * 74)

    produced: set[str] = set()
    full: dict[str, dict] = {}
    for sid, _intent, expected, _ship in CASES:
        listed = by_shipment.get(sid)
        if listed is None:
            print(f"  MISS  {sid:22} case absent from the board")
            continue
        case = detail(args.base, listed["case_id"]) or listed
        full[sid] = case
        got = findings_of(case)
        produced.update(got)
        # Named `summary`, not `detail`: assigning to a local called `detail`
        # anywhere in this function makes Python treat the name as local for the
        # whole of it, which shadows the module-level detail() called above and
        # raises UnboundLocalError before the loop ever reaches this line.
        if not expected:
            mark = "ok  " if not got else "note"
            summary = "clean" if not got else "+".join(got)
        elif any(e in got for e in expected):
            mark, summary = "ok  ", "+".join(got)
        else:
            # Reported, not failed: several of these depend on a model reply, and
            # a seeding script that fails on model variance fails for the wrong
            # reason.
            mark = "diff"
            summary = f"wanted {'|'.join(expected)}, got {'+'.join(got) or 'none'}"
        print(f"  {mark}  {sid:22} {case.get('state'):18} {summary[:60]}")

    print("\n" + "-" * 74)
    states: dict[str, int] = {}
    for case in cases:
        states[case.get("state", "?")] = states.get(case.get("state", "?"), 0) + 1
    print(f"board: {len(cases)} cases")
    for state, count in sorted(states.items(), key=lambda kv: -kv[1]):
        print(f"  {state:20} {count}")

    print(f"\ndistinct finding codes produced: {len(produced)}")
    for code in sorted(produced):
        print(f"  {code}")

    archived = sum(1 for c in full.values() if (c.get("provenance") or {}).get("archived"))
    print(f"\nbills of lading archived: {archived}/{len(full)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
