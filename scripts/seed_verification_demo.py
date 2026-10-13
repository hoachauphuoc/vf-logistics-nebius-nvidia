"""
Seed two plywood cases for the verification-loop demo (Plan 1, step 8).

Run: python scripts/seed_verification_demo.py [--api URL]

Creates VF-DEMO-PLY-A and VF-DEMO-PLY-B on the live board. Does not reset
the board or touch existing cases.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import requests

DEFAULT_API = os.getenv(
    "VF_API_BASE",
    "https://vf-app-350828852747.asia-southeast1.run.app",
)

CASES = [
    {
        "shipment_id": "VF-DEMO-PLY-A",
        "shipper_name": "Saigon Plywood Co., Ltd.",
        "shipper_company": "Saigon Plywood Co., Ltd.",
        "shipper_tax_id": "VN0300999001",
        "shipper_country": "Vietnam",
        "receiver_name": "US Hardwood Imports LLC",
        "receiver_company": "US Hardwood Imports LLC",
        "receiver_country": "United States",
        "origin": "Hai Phong Port, Vietnam",
        "destination": "Long Beach, United States",
        "hs_code": "4412.33",
        "cargo_description": "Hardwood plywood, 18 mm, declared Vietnam origin",
        "declared_value": 28000.0,
        "weight_kg": 22000.0,
        "currency": "USD",
        "shipping_cost": 3200.0,
        "transport_mode": "sea",
        "route_details": "Hai Phong to Long Beach via direct sea freight",
        "shipper_tx_count": 35,
    },
    {
        "shipment_id": "VF-DEMO-PLY-B",
        "shipper_name": "Saigon Plywood Co., Ltd.",
        "shipper_company": "Saigon Plywood Co., Ltd.",
        "shipper_tax_id": "VN0300999001",
        "shipper_country": "Vietnam",
        "receiver_name": "US Hardwood Imports LLC",
        "receiver_company": "US Hardwood Imports LLC",
        "receiver_country": "United States",
        "origin": "Hai Phong Port, Vietnam",
        "destination": "Long Beach, United States",
        "hs_code": "4412.33",
        "cargo_description": "Hardwood plywood, 18 mm, declared Vietnam origin",
        "declared_value": 28000.0,
        "weight_kg": 22000.0,
        "currency": "USD",
        "shipping_cost": 3200.0,
        "transport_mode": "sea",
        "route_details": "Hai Phong to Long Beach via direct sea freight",
        "shipper_tx_count": 35,
    },
]


def seed(api: str) -> None:
    for shipment in CASES:
        url = f"{api}/api/v1/events/shipment"
        print(f"  Submitting {shipment['shipment_id']}... ", end="", flush=True)
        response = requests.post(url, json=shipment, timeout=120)
        if response.status_code in (200, 201):
            body = response.json()
            print(f"OK  state={body.get('state')}  risk={body.get('risk_score')}")
        else:
            print(f"FAILED {response.status_code}: {response.text[:200]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=DEFAULT_API, help="Base URL")
    args = parser.parse_args()
    print(f"Seeding 2 plywood demo cases on {args.api}")
    seed(args.api)
    print("Done. Both should show ORIGIN_INPUTS_UNVERIFIED on the Today screen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
