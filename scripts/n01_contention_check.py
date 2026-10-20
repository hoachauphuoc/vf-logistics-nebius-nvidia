"""
Race two or more audit reconciliations of one send on the real Firestore (review 2026-10-19, N01).

The unit tests prove the fixed audit id and the atomic create on MemoryStore and the emulator. This
drives the same code path (tools.record_publish_audit) concurrently against the project's Firestore
and requires exactly one writer to win and exactly one row to exist.

  python scripts/n01_contention_check.py --project <id> [--writers 12] [--keep]

Application Default Credentials are used. The rows go to the tenant `n01-contention`, which the
production board never reads, and are deleted afterwards unless --keep is given.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

TENANT = "n01-contention"


async def race(writers: int) -> tuple[list[bool], str, list[str]]:
    from vf_logistics import tools
    from vf_logistics.store import get_store

    stamp = int(time.time())
    case_id = f"N01-CONTENTION-{stamp}"
    detail = {
        "idempotency_key": f"key-{stamp}", "message_id": f"msg-{stamp}", "case_id": case_id, "action": "release",
    }
    results = await asyncio.gather(*(
        tools.record_publish_audit(case_id, dict(detail), f"writer-{i}@test.invalid", tenant_id=TENANT)
        for i in range(writers)
    ))
    rows, _ = await get_store().query_audit(case_id=case_id, action="publish_decision", tenant_id=TENANT)
    return list(results), case_id, [r["audit_id"] for r in rows]


async def cleanup(audit_ids: list[str]) -> None:
    from vf_logistics.store import get_store

    store = get_store()
    for audit_id in audit_ids:
        await asyncio.to_thread(store._audit.document(audit_id).delete)  # type: ignore[attr-defined]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--writers", type=int, default=12)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    os.environ["PROJECT_ID"] = args.project
    os.environ["GOOGLE_CLOUD_PROJECT"] = args.project
    os.environ["STORE_BACKEND"] = "firestore"
    os.environ["MULTI_TENANT"] = "false"

    results, case_id, audit_ids = asyncio.run(race(args.writers))
    winners = results.count(True)
    print(f"case {case_id}: {args.writers} writers, {winners} wrote the row, {len(audit_ids)} row(s) stored")
    ok = winners == 1 and len(audit_ids) == 1
    if not args.keep:
        asyncio.run(cleanup(audit_ids))
        print(f"deleted {len(audit_ids)} test row(s)")
    print("PASS: one writer, one row" if ok else "FAIL: expected exactly one writer and one row")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
