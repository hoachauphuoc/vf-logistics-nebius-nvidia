"""
Create the Firestore composite indexes the windowed billing query needs.

    python infra/monitoring/create_billing_indexes.py

WHY FIVE INDEXES AND NOT ONE

This was measured, not predicted. `sum_rollups(since=..., until=...)` applies a range
filter on `created_at` to a tenant-scoped query and then runs FIVE separate `sum()`
aggregations over it. Firestore requires the aggregated field itself to be in the
index, so a range filter plus an aggregation needs:

    (_tenant_id ASC, created_at ASC, <aggregated field> ASC)

An index on (_tenant_id, created_at) alone is NOT enough. The first attempt created
exactly that, and the query failed with FAILED_PRECONDITION naming
`_input_tokens` -- the first of the five sums to run. Each of the five needs its own.

THE TRADE-OFF, STATED

Five indexes means five extra index entries written per case. The alternative is to
fetch the window's case documents and sum in Python, which needs only one index but
reads every document in the period -- and gives up the property the aggregation path
exists for, that the total is correct and cheap at any collection size. For a figure
that goes on an invoice, the aggregation is worth the write amplification.

Idempotent: an index that already exists is reported and skipped.
"""

from __future__ import annotations

import subprocess
import sys

PROJECT = "vf-fraud-detection-phuochoa"
DATABASE = "(default)"
COLLECTION = "cases"

# The tenant scope and the period bound are shared by every aggregation; the third
# field is the one being summed.
SCOPE_FIELDS = ["_tenant_id", "created_at"]

AGGREGATED_FIELDS = [
    "_input_tokens",
    "_output_tokens",
    "_agent_calls",
    "_estimated_cost_usd",
    "_sum_latency_ms",
    # Tavily, metered separately because it is billed in credits rather than dollars
    # and is the tighter ceiling: at a measured 4.5-5.3 searches per case, the free
    # tier's 1,000 a month runs out after roughly 200 cases while the same traffic
    # costs about seven cents of Nemotron.
    "_tavily_searches",
    "_tavily_cached",
    "_tavily_billable",
]


def create(aggregated: str) -> tuple[bool, str]:
    """
    Create one index. Returns (created, message).

    An "already exists" response is success, not failure -- this script is meant to
    be safe to re-run after a partial failure.
    """
    args = [
        "gcloud",
        "firestore",
        "indexes",
        "composite",
        "create",
        f"--collection-group={COLLECTION}",
        f"--database={DATABASE}",
        f"--project={PROJECT}",
        "--quiet",
    ]
    for field in [*SCOPE_FIELDS, aggregated]:
        args.append(f"--field-config=field-path={field},order=ascending")

    result = subprocess.run(args, capture_output=True, text=True, shell=True)
    output = (result.stdout + result.stderr).strip()

    if result.returncode == 0:
        return True, "created"
    if "ALREADY_EXISTS" in output or "already exists" in output:
        return True, "already exists"
    return False, output[:400]


def main() -> int:
    print(f"{len(AGGREGATED_FIELDS)} indexes on {COLLECTION}, each as")
    print(f"  ({', '.join(SCOPE_FIELDS)}, <field>)")
    print("Each takes a few minutes. Queries fail with FAILED_PRECONDITION until done.")
    print()

    failures = 0
    for field in AGGREGATED_FIELDS:
        ok, message = create(field)
        print(f"  {'+' if ok else '!'} {field}: {message}")
        if not ok:
            failures += 1

    print()
    if failures:
        print(f"{failures} index(es) failed. Re-run; existing ones are skipped.")
        return 1
    print("All indexes present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
