"""
Self-check for the counterparty book.

shipper_registry.py is the module that decides whether a shipment may clear
without a human, so its failure modes matter more than its happy path. This
script asserts the three that do: a legitimate shipper is recognised through
ordinary formatting noise, a real tax number under the wrong company name is
reported as a mismatch rather than waved through, and neither the mismatch nor
the unknown path ever writes trading history that nobody vouched for.

There is no pytest in this project's requirements, deliberately - this runs with
plain `python scripts/check_registry.py` and exits non-zero on failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The module under test lives at the repository root, which is not on the path
# when this file is run directly from scripts/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import shipper_registry as sr  # noqa: E402

# (tax id, company) -> expected status.
CASES: list[tuple[tuple[object, object], str]] = [
    (("0301234567", "Saigon Textile Export JSC"), "verified"),

    # Formatting differences must not read as a different counterparty: the tax
    # id is normalised to digits and legal-form suffixes are dropped.
    (("03-0123-4567", "saigon textile export jsc."), "verified"),
    (("0311204558", "MINH PHUONG CERAMICS COMPANY LIMITED"), "verified"),

    # The security case. A forged document carrying a real customer's tax number
    # must not inherit that customer's clean history.
    (("0301234567", "Bao Tin Global Trading"), "identity_mismatch"),

    # Unusable identifiers, including the placeholders a transcription leaves
    # behind for a blank field on the page.
    ((None, "Saigon Textile Export JSC"), "unknown"),
    (("not stated", "Saigon Textile Export JSC"), "unknown"),
    (("________________", "Saigon Textile Export JSC"), "unknown"),
    (("9999999999", "Anything"), "unknown"),
]


def main() -> int:
    failures = 0

    for (tax_id, company), expected in CASES:
        got = sr.lookup(tax_id, company)["status"]
        if got != expected:
            failures += 1
            print(f"FAIL tax={tax_id!r} company={company!r}: "
                  f"expected {expected}, got {got}")
        else:
            print(f"ok   {expected:<18} tax={tax_id!r} company={company!r}")

    # A verified match is the only thing allowed to supply history.
    shipment = {"shipper_tax_id": "0301234567",
                "shipper_company": "Saigon Textile Export JSC"}
    sr.enrich(shipment)
    if shipment.get("shipper_tx_count") != 412:
        failures += 1
        print(f"FAIL verified match should set tx_count 412, got {shipment}")
    else:
        print("ok   verified match supplies tx_count 412")

    # A mismatch must not invent history, and must not be silently upgraded.
    shipment = {"shipper_tax_id": "0301234567",
                "shipper_company": "Bao Tin Global Trading",
                "shipper_tx_count": 999}
    result = sr.enrich(shipment)
    if result["status"] != "identity_mismatch" or shipment["shipper_tx_count"] != 999:
        failures += 1
        print(f"FAIL mismatch path wrote history: {result} {shipment}")
    else:
        print("ok   mismatch supplies nothing")

    # An unknown counterparty leaves the record exactly as it arrived, so the
    # unverified-history floor in verifier.py still applies.
    shipment: dict[str, object] = {}
    result = sr.enrich(shipment)
    if result["status"] != "unknown" or "shipper_tx_count" in shipment:
        failures += 1
        print(f"FAIL unknown path touched the record: {result} {shipment}")
    else:
        print("ok   unknown supplies nothing")

    print(f"\n{len(CASES) + 3} checks, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
