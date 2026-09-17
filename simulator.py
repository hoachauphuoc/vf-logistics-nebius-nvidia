"""
Simulated shipment event source.

The autonomous pipeline normally consumes Pub/Sub messages produced by the
shipment system. For a self-contained demo we inject a scripted batch instead,
chosen so that all three branches of the state machine fire on camera:

  * SHIP-CLEAN  - clean paperwork, market-rate pricing, established shipper
                  -> expected AUTO_CLEARED
  * SHIP-MID    - some pricing softness and a thin history, paperwork complete
                  -> expected HELD_FOR_REVIEW
  * SHIP-DIRTY  - grossly underpriced, brand new shell-like counterparty,
                  dual-use goods, sanctioned-adjacent routing
                  -> expected ESCALATED

Nothing here is special-cased downstream: the agents score these on their
merits, and the orchestrator branches on the scores it is given.

All monetary amounts are USD.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any


def _iso(offset_minutes: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)).isoformat()


def bulk_shipments(count: int, run_tag: str) -> list[dict[str, Any]]:
    """
    Generate `count` shipments spread across the risk spectrum.

    Used to show the pipeline is not a three-record toy. The mix is weighted the
    way a real book of business looks: most shipments are unremarkable, a
    minority are worth a screen, and a small tail is genuinely bad. Field values
    are randomised so the agents are scoring different shipments rather than the
    same one repeatedly.

    A note on volume: each case costs one Gemini call minimum and three for a
    full escalation, so this endpoint is capped low on purpose. The default of
    10 is about 20 model calls and finishes in roughly a minute, which is enough
    to show the worker draining a queue. Raising it to 1,000 would mean ~2,000
    calls and over an hour without demonstrating anything the 10 does not.

    Be aware that on this deployment the dominant cost is the always-on Cloud
    Run instance, not the model calls.
    """
    lanes = [
        ("Ho Chi Minh City, Vietnam", "Singapore", 1_200, "Cat Lai -> PSA, direct"),
        ("Hai Phong, Vietnam", "Busan, South Korea", 1_680, "Hai Phong -> Busan, direct"),
        ("Da Nang, Vietnam", "Kaohsiung, Taiwan", 1_450, "Da Nang -> Kaohsiung, direct"),
        ("Ho Chi Minh City, Vietnam", "Los Angeles, USA", 3_400, "Cat Lai -> LA, via Yokohama"),
        ("Hai Phong, Vietnam", "Rotterdam, Netherlands", 4_100, "Hai Phong -> Rotterdam, via Singapore"),
    ]

    benign_cargo = [
        ("Woven cotton garments, retail packed", "6205.20"),
        ("Flat-pack rubberwood furniture", "9403.30"),
        ("Roasted coffee beans, 60kg sacks", "0901.21"),
        ("Rubber footwear soles", "6406.20"),
        ("Ceramic tableware", "6912.00"),
    ]

    sensitive_cargo = [
        ("Frequency converters, industrial", "8504.40"),
        ("High-precision pressure transducers", "9026.20"),
        ("Numerically controlled lathe parts", "8458.11"),
    ]

    out: list[dict[str, Any]] = []
    for i in range(count):
        origin, dest, base_cost, route = random.choice(lanes)

        # 60% clean, 30% suspicious, 10% clearly bad. At a batch size of 10 this
        # reliably produces at least one of each rather than ten clean ones.
        #
        # `weight_range` and `value_per_kg` are per profile on purpose. They used to
        # be shared - weight 300-2600 kg at 8-70 USD/kg, a median around 56,000 USD -
        # which is more than twice the 25,000 USD ceiling the delegation boundary
        # grants for auto-release. So even a flawless shipment breached delegation on
        # value alone and no case could ever clear autonomously. A clean consignment
        # now sits inside the boundary by construction (at most 1,200 kg x 18 USD/kg
        # = 21,600 USD), which is what a low-value routine shipment looks like. The
        # ceiling itself is untouched: the control is the point, not the obstacle.
        roll = random.random()
        if roll < 0.60:
            profile = "clean"
            cargo, hs = random.choice(benign_cargo)
            cost = round(base_cost * random.uniform(0.95, 1.15), 2)
            tx = random.randint(80, 900)
            tax_id = f"0{random.randint(100000000, 999999999)}"
            transit = "None"
            weight_range, value_per_kg = (300, 1_200), (8, 18)
        elif roll < 0.90:
            profile = "suspicious"
            cargo, hs = random.choice(benign_cargo)
            cost = round(base_cost * random.uniform(0.55, 0.75), 2)
            tx = random.randint(3, 15)
            tax_id = f"0{random.randint(100000000, 999999999)}"
            transit = "None"
            weight_range, value_per_kg = (300, 2_600), (8, 70)
        else:
            profile = "bad"
            cargo, hs = random.choice(sensitive_cargo)
            cost = round(base_cost * random.uniform(0.06, 0.20), 2)
            tx = random.randint(1, 2)
            tax_id = "not provided"
            transit = "Port Klang, Malaysia; Jebel Ali, UAE"
            route += ", two unscheduled transhipments added after booking"
            weight_range, value_per_kg = (800, 2_600), (30, 70)

        weight = random.randint(*weight_range)
        value = round(weight * random.uniform(*value_per_kg), 2)

        # One entity per party, reused for name and company. Drawing them
        # independently produced a different shipper name than shipper company on
        # nearly every record, which the compliance agent correctly read as
        # mismatched entity documentation - so almost every generated case
        # escalated on a data-generation artefact rather than on its own risk.
        # The hand-written fixtures below already keep name and company equal.
        shipper_entity = f"{random.choice(SHIPPERS)} {random.choice(SUFFIX)}"
        receiver_entity = f"{random.choice(RECEIVERS)} {random.choice(SUFFIX)}"

        out.append(
            {
                "shipment_id": f"VF-{run_tag}-{i + 1:04d}",
                "origin": origin,
                "destination": dest,
                "weight_kg": weight,
                "declared_value": value,
                "shipping_cost": cost,
                "avg_route_cost": base_cost,
                "shipper_name": shipper_entity,
                "shipper_company": shipper_entity,
                "shipper_country": "Vietnam",
                "shipper_tax_id": tax_id,
                "receiver_name": receiver_entity,
                "receiver_company": receiver_entity,
                "receiver_country": dest.split(", ")[-1],
                "cargo_description": cargo,
                "hs_code": hs,
                "shipper_tx_count": tx,
                "status": "pending",
                "route_details": route,
                "transit_points": transit,
                "created_at": _iso(-random.randint(0, 240)),
                # Recorded for post-run analysis only. The agents never see this
                # field, so it cannot leak the answer into their scoring.
                "_generated_profile": profile,
            }
        )

    return out


SHIPPERS = [
    "Saigon Textile", "Truong Hai", "Bao Tin", "Minh Phuong", "An Khang",
    "Dai Duong", "Phu Cuong", "Hoang Long", "Tan Thanh", "Viet Tien",
]

RECEIVERS = [
    "Orchard Apparel", "Daehan Home", "Pacific Sourcing", "Northgate Imports",
    "Meridian Trade", "Kowloon Supply", "Baltic Retail",
]
# "Al-Rasheed Technical" is deliberately excluded from this pool. It carries the
# sanctions-adjacent keywords the compliance agent is meant to catch, so leaving
# it in the general draw handed roughly one in eight *clean* shipments a
# watchlist-linked receiver. The agent escalated those correctly, which made the
# signal look meaningless. It now appears only in the fixture that intends it.

SUFFIX = ["Co Ltd", "JSC", "Pte Ltd", "Inc", "Trading Co", "Group"]


def scripted_shipments(run_tag: str) -> list[dict[str, Any]]:
    """Three shipments with genuinely different risk profiles."""
    return [
        {
            # The carton count has to agree with the weight and the value, or
            # compliance is right to question it. At 1,640 cartons this record
            # described 0.5 kg and USD 5.85 a carton, and the agent intermittently
            # returned REVIEW_REQUIRED for undervaluation - which escalated the
            # case despite a fraud score of 5, making the headline auto-clear demo
            # a coin flip. 164 cartons is 5 kg and USD 58.50 a carton, or USD 11.71
            # a kilo: unremarkable for wholesale cotton garments.
            "shipment_id": f"VF-{run_tag}-CLEAN",
            "origin": "Ho Chi Minh City, Vietnam",
            "destination": "Singapore",
            "weight_kg": 820,
            "declared_value": 9_600,
            "shipping_cost": 1_260,
            "avg_route_cost": 1_200,
            "shipper_name": "Saigon Textile Export JSC",
            "shipper_company": "Saigon Textile Export JSC",
            "shipper_country": "Vietnam",
            "shipper_tax_id": "0301234567",
            "receiver_name": "Orchard Apparel Pte Ltd",
            "receiver_company": "Orchard Apparel Pte Ltd",
            "receiver_country": "Singapore",
            "cargo_description": "Woven cotton garments, 164 cartons, retail packed",
            "hs_code": "6205.20",
            "shipper_tx_count": 412,
            "status": "pending",
            "route_details": "Cat Lai Port -> Singapore PSA, direct sailing",
            "transit_points": "None",
            "created_at": _iso(),
        },
        {
            # Paperwork is deliberately complete and the cargo is unambiguously
            # benign, so compliance should clear it. The risk sits purely in the
            # commercials: priced well under the route average by a shipper with
            # a thin history. That combination is what the middle branch exists
            # for - cleared by compliance, still too risky to release
            # automatically, so a human gets it.
            "shipment_id": f"VF-{run_tag}-MID",
            "origin": "Hai Phong, Vietnam",
            "destination": "Busan, South Korea",
            "weight_kg": 1_450,
            "declared_value": 24_400,
            "shipping_cost": 1_220,
            "avg_route_cost": 1_680,
            "shipper_name": "Truong Hai Furniture Co Ltd",
            "shipper_company": "Truong Hai Furniture Co Ltd",
            "shipper_country": "Vietnam",
            "shipper_tax_id": "0209988776",
            "receiver_name": "Daehan Home Retail Inc",
            "receiver_company": "Daehan Home Retail Inc",
            "receiver_country": "South Korea",
            "cargo_description": (
                "New flat-pack wooden office furniture, 480 cartons, "
                "kiln-dried rubberwood, fumigation certificate attached"
            ),
            "hs_code": "9403.30",
            "shipper_tx_count": 9,
            "status": "pending",
            "route_details": "Hai Phong -> Busan, direct sailing, no transhipment",
            "transit_points": "None",
            "created_at": _iso(-3),
        },
        {
            "shipment_id": f"VF-{run_tag}-DIRTY",
            "origin": "Da Nang, Vietnam",
            "destination": "Karachi, Pakistan",
            "weight_kg": 2_300,
            "declared_value": 164_000,
            "shipping_cost": 392,
            "avg_route_cost": 2_720,
            "shipper_name": "Bao Tin Global Trading",
            "shipper_company": "Bao Tin Global Trading (registered 11 days ago)",
            "shipper_country": "Vietnam",
            "shipper_tax_id": "not provided",
            "receiver_name": "Al-Rasheed Technical Imports",
            "receiver_company": "Al-Rasheed Technical Imports",
            "receiver_country": "Pakistan",
            "cargo_description": (
                "High-precision pressure transducers and frequency converters, "
                "end use stated as agricultural"
            ),
            "hs_code": "8504.40",
            "shipper_tx_count": 1,
            "status": "pending",
            "route_details": (
                "Da Nang -> Port Klang -> Jebel Ali -> Karachi, "
                "two unscheduled transhipments added after booking"
            ),
            "transit_points": "Port Klang, Malaysia; Jebel Ali, UAE",
            "created_at": _iso(-7),
        },
    ]
