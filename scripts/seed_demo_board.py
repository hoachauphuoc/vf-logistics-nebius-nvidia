"""
Seed the demo board with a specific outcome mix.

The bulk simulator draws profiles at random, so it cannot hit a target like
"4 auto-cleared, 3 awaiting human, 2 escalated" on demand. This script posts
individually shaped shipments to /api/v1/events/shipment and, after each one,
recounts the board via /api/v1/orchestrator/state.

Counting from the board rather than from the POST response is deliberate: the
response state and the stored state can differ, because a case that the
response reports as cleared may still be advanced afterwards. The board is the
thing the demo shows, so the board is the thing that gets counted.

Routing rules being steered (orchestrator.py, SPECIALISTS_DONE):
  AUTO_CLEARED     risk < 40, compliance CLEARED, inside delegation ceiling
  HELD_FOR_REVIEW  40 <= risk < 70, compliance CLEARED
  ESCALATED        compliance BLOCKED/REVIEW_REQUIRED, or risk >= 70

Cargo choice matters as much as pricing. Wood and agricultural goods draw
phytosanitary and ISPM 15 findings from the compliance agent, which returns
REVIEW_REQUIRED and forces an investigation no matter how low the fraud score
is - a rubberwood consignment escalated at risk 12. The auto-clear and review
pools are therefore restricted to manufactured, non-agricultural cargo.

Two further artefacts had to be designed out, both of which escalated cases on
the shape of the generated record rather than on its risk:

  * `receiver_country` must be stated per lane, not derived by splitting the
    destination on ", ". "PSA Singapore" contains no comma, so the derived
    country became "PSA Singapore" - a terminal operator, not a country - and
    compliance flagged incorrect destination documentation.
  * Cargo and receiver must be industry-compatible. Ceramics consigned to an
    apparel importer reads as a trade inconsistency, so receivers are
    industry-neutral trading names.

Buckets are filled in the order auto-cleared, then held, then escalated. The
fragile aim is auto-clear, and when it misses it misses towards escalation, so
leaving escalation last lets a stray case count towards a quota still open
instead of overshooting one already closed. Overshoot is still possible, so the
final tally is compared for equality rather than quietly accepted; there is no
API to delete a single case, so the only remedy is to reset and run again.
"""

from __future__ import annotations

import json
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = "https://vf-fraud-detection-304507056252.asia-southeast1.run.app"
EVENT_URL = f"{BASE}/api/v1/events/shipment"
STATE_URL = f"{BASE}/api/v1/orchestrator/state"

# Filled in this order; see module docstring. Override on the command line:
#   python tools_seed_demo_board.py 4 2 2
# A BLOCKED document case sits in the same "Awaiting human" column as a held
# case but is not a HELD_FOR_REVIEW state, so a board that needs to read 4/3/2
# on screen with one blocked case is seeded as 4/2/2 and blocked last.
ORDER = ["AUTO_CLEARED", "HELD_FOR_REVIEW", "ESCALATED"]
TARGETS = {"AUTO_CLEARED": 4, "HELD_FOR_REVIEW": 3, "ESCALATED": 2}
MAX_ATTEMPTS = 30

# Country is stated rather than parsed off the destination: see module docstring.
# (origin, destination, destination_country, avg_route_cost)
LANES = [
    ("Cat Lai Port, Ho Chi Minh City, Vietnam", "PSA Singapore", "Singapore", 1_200),
    ("Hai Phong Port, Vietnam", "PSA Singapore", "Singapore", 1_350),
]

# Manufactured, non-agricultural, non-wood: nothing here attracts a
# phytosanitary or ISPM 15 finding.
SAFE_CARGO = [
    ("Woven cotton garments, retail packed", "6205.20"),
    ("Ceramic tableware", "6912.00"),
    ("Rubber footwear soles", "6406.20"),
    ("Polyester knitted fabric rolls", "6006.32"),
]

# Dual-use goods, which is the point: these are meant to escalate.
SENSITIVE_CARGO = [
    ("Frequency converters, industrial", "8504.40"),
    ("High-precision pressure transducers", "9026.20"),
]

SHIPPERS = ["Saigon Textile", "Truong Hai", "Minh Phuong", "An Khang", "Viet Tien"]
# Industry-neutral on purpose: a sector-specific importer such as an apparel
# house reads as a trade inconsistency when consigned unrelated cargo.
RECEIVERS = ["Pacific Sourcing", "Meridian Trade", "Northgate Imports", "Kowloon Supply"]
SUFFIX = ["Co Ltd", "JSC", "Pte Ltd", "Trading Co"]


def _iso(minutes_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _entity(pool: list[str]) -> str:
    # Name and company are kept identical: drawing them independently reads as
    # mismatched entity documentation and escalates on an artefact.
    return f"{random.choice(pool)} {random.choice(SUFFIX)}"


def build_shipment(target: str, shipment_id: str) -> dict:
    """Shape a shipment whose risk profile aims at `target`."""
    origin, dest, dest_country, base_cost = random.choice(LANES)
    shipper = _entity(SHIPPERS)
    receiver = _entity(RECEIVERS)
    route = f"Port of Loading: {origin}; Port of Discharge: {dest}; direct sailing"

    if target == "AUTO_CLEARED":
        # Routine consignment: market-rate freight, long trading history, no
        # transhipment, value well inside the delegation ceiling.
        cargo, hs = random.choice(SAFE_CARGO)
        weight = random.randint(300, 800)
        value = round(weight * random.uniform(8, 14), 2)
        cost = round(base_cost * random.uniform(0.98, 1.12), 2)
        tx = random.randint(200, 900)
        tax_id = f"0{random.randint(100_000_000, 999_999_999)}"
        transit = "None"

    elif target == "HELD_FOR_REVIEW":
        # Compliance-clean cargo, but under-market freight and a thin trading
        # history: above the auto-release bar, below the investigation bar.
        cargo, hs = random.choice(SAFE_CARGO)
        weight = random.randint(900, 1_800)
        value = round(weight * random.uniform(14, 22), 2)
        cost = round(base_cost * random.uniform(0.60, 0.72), 2)
        tx = random.randint(4, 11)
        tax_id = f"0{random.randint(100_000_000, 999_999_999)}"
        transit = "None"

    else:  # ESCALATED
        cargo, hs = random.choice(SENSITIVE_CARGO)
        weight = random.randint(1_200, 2_600)
        value = round(weight * random.uniform(40, 70), 2)
        cost = round(base_cost * random.uniform(0.06, 0.16), 2)
        tx = random.randint(1, 2)
        tax_id = "not provided"
        transit = "Port Klang, Malaysia; Jebel Ali, UAE"
        route += ", two unscheduled transhipments added after booking"

    return {
        "shipment_id": shipment_id,
        "origin": origin,
        "destination": dest,
        "weight_kg": weight,
        "declared_value": value,
        "shipping_cost": cost,
        "avg_route_cost": base_cost,
        "shipper_name": shipper,
        "shipper_company": shipper,
        "shipper_country": "Vietnam",
        "shipper_tax_id": tax_id,
        "receiver_name": receiver,
        "receiver_company": receiver,
        "receiver_country": dest_country,
        "cargo_description": cargo,
        "hs_code": hs,
        "shipper_tx_count": tx,
        "status": "pending",
        "route_details": route,
        "transit_points": transit,
        "created_at": _iso(random.randint(0, 240)),
    }


def post_shipment(shipment: dict) -> None:
    body = json.dumps(shipment).encode("utf-8")
    req = urllib.request.Request(
        EVENT_URL, data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        resp.read()


def board_counts() -> dict[str, int]:
    """Terminal-state tallies as the board itself reports them."""
    with urllib.request.urlopen(STATE_URL, timeout=120) as resp:
        state = json.loads(resp.read().decode("utf-8"))

    counts = {k: 0 for k in TARGETS}
    pending = 0
    for case in state.get("cases") or []:
        st = case.get("state")
        if st in counts:
            counts[st] += 1
        else:
            pending += 1
    counts["_pending"] = pending
    return counts


def settled_counts(timeout_s: int = 180, interval_s: int = 5) -> dict[str, int]:
    """
    Counts taken only once no case is mid-flight.

    Reading the board the instant a POST returns is not safe: the response can
    arrive while the case is still short of a terminal state, the unfinished
    case is invisible to the tally, and the next iteration aims at a bucket that
    is about to fill itself. That is how a target of three became four - two
    cases aimed at the same remaining slot, both landing in it.
    """
    waited = 0
    counts = board_counts()
    while counts["_pending"] and waited < timeout_s:
        time.sleep(interval_s)
        waited += interval_s
        counts = board_counts()
    return counts


def next_target(counts: dict[str, int]) -> str | None:
    for bucket in ORDER:
        if counts[bucket] < TARGETS[bucket]:
            return bucket
    return None


def main() -> int:
    if len(sys.argv) == 4:
        try:
            for bucket, value in zip(ORDER, sys.argv[1:]):
                TARGETS[bucket] = int(value)
        except ValueError:
            print("usage: tools_seed_demo_board.py [auto_cleared held escalated]")
            return 2
    elif len(sys.argv) != 1:
        print("usage: tools_seed_demo_board.py [auto_cleared held escalated]")
        return 2

    print("Targets: " + "  ".join(f"{k}={TARGETS[k]}" for k in ORDER), flush=True)

    run_tag = datetime.now(timezone.utc).strftime("%H%M%S")
    seq = 0
    attempts = 0

    counts = settled_counts()
    print(f"Starting board: {counts}", flush=True)

    while attempts < MAX_ATTEMPTS:
        target = next_target(counts)
        if target is None:
            break

        seq += 1
        attempts += 1
        shipment_id = f"VF-{run_tag}-{seq:04d}"
        print(f"  -> posting {shipment_id} aimed {target} ...", flush=True)

        try:
            post_shipment(build_shipment(target, shipment_id))
        except urllib.error.URLError as exc:
            print(f"     ! request failed: {exc}", flush=True)
            continue

        counts = settled_counts()
        print(
            "     board: "
            + "  ".join(f"{k}={counts[k]}/{TARGETS[k]}" for k in ORDER)
            + f"  (pending {counts['_pending']})",
            flush=True,
        )

        # Stop as soon as a bucket passes its target. Nothing later can undo it,
        # so continuing would only spend model calls on an outcome already wrong.
        over = [k for k in ORDER if counts[k] > TARGETS[k]]
        if over:
            print(f"     ! overshot {', '.join(over)}; stopping", flush=True)
            break

    print("\nFinal mix:")
    for k in ORDER:
        print(f"  {k:16s} {counts[k]}/{TARGETS[k]}  {'OK' if counts[k] == TARGETS[k] else 'MISMATCH'}")

    off = [k for k in ORDER if counts[k] != TARGETS[k]]
    if off:
        print(f"\nNot matching target: {', '.join(off)} after {attempts} attempts.")
        print("Reset the board and rerun if an over-filled bucket needs shrinking.")
        return 1

    print(f"\nAll targets met in {attempts} attempts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
