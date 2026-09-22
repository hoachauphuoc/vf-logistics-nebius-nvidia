"""
Create the Firestore composite indexes the billing queries need.

    python infra/monitoring/create_billing_indexes.py

TWO INDEXES PER AGGREGATED FIELD, NOT ONE

This has now been learned twice, in the same direction, and the second time was worse
because the first lesson had been written down inaccurately.

`sum_rollups()` has two call shapes and Firestore needs a different index for each.
Every `sum()` over a filtered query requires the aggregated field in the index
alongside the filtered ones, so:

    unbounded  filters _tenant_id            ->  (_tenant_id ASC, <field> ASC)
    windowed   filters _tenant_id, created_at -> (_tenant_id ASC, created_at ASC, <field> ASC)

The three-field index does NOT satisfy the two-field query. An index prefix has to
match the query's filters, and the unbounded query never constrains `created_at`.

HOW THIS WAS GOT WRONG THE SECOND TIME

The first round created the three-field indexes for the five original sums, and the
docstring in store.py then recorded that "none of them are needed for the unbounded
call". That read as "the unbounded call needs no indexes". It does need them -- it needs
the two-field ones, which already existed from when unbounded billing was first built,
so nothing broke and the false statement went unchallenged.

Adding `_tavily_searches` proved it: the windowed indexes were created, the windowed
tests passed, and the *unbounded* `GET /billing/usage` returned 500 in production with
"The query requires an index" naming `(_tenant_id, _tavily_searches)`. Both shapes are
now created together so a new aggregation cannot repeat this.

THE TRADE-OFF, STATED

Two indexes per field means two extra index entries written per case per field. The
alternative is to fetch the window's documents and sum in Python, which needs one index
but reads every document in the period -- giving up the property the aggregation exists
for, that the total is correct and cheap at any collection size. For a figure that goes
on an invoice, the aggregation is worth the write amplification.

Idempotent: an index that already exists is reported and skipped.
"""

from __future__ import annotations

import subprocess
import sys

PROJECT = "vf-fraud-detection-phuochoa"
DATABASE = "(default)"
COLLECTION = "cases"

# The tenant scope is on every query; the period bound is only on the windowed one.
TENANT_FIELD = "_tenant_id"
PERIOD_FIELD = "created_at"
SCOPE_FIELDS = [TENANT_FIELD, PERIOD_FIELD]

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


def create(fields: list[str]) -> tuple[bool, str]:
    """
    Create one index over `fields`, in order. Returns (created, message).

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
    for field in fields:
        args.append(f"--field-config=field-path={field},order=ascending")

    result = subprocess.run(args, capture_output=True, text=True, shell=True)
    output = (result.stdout + result.stderr).strip()

    if result.returncode == 0:
        return True, "created"
    if "ALREADY_EXISTS" in output or "already exists" in output:
        return True, "already exists"
    return False, output[:400]


def main() -> int:
    total = len(AGGREGATED_FIELDS) * 2
    print(f"{total} indexes on {COLLECTION}: two per aggregated field.")
    print(f"  unbounded  (_tenant_id, <field>)")
    print(f"  windowed   (_tenant_id, created_at, <field>)")
    print("Each takes a few minutes. Queries fail with FAILED_PRECONDITION until done.")
    print()

    failures = 0
    for field in AGGREGATED_FIELDS:
        for shape, fields in (
            ("unbounded", [TENANT_FIELD, field]),
            ("windowed ", [TENANT_FIELD, PERIOD_FIELD, field]),
        ):
            ok, message = create(fields)
            print(f"  {'+' if ok else '!'} {shape} {field}: {message}")
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
