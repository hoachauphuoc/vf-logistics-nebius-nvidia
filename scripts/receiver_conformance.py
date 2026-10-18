"""
Conformance check for a system that receives Floorline's decisions (N01).

Floorline publishes each executed decision at least once, always under the same
idempotency_key, and cannot see what a downstream system does with it. This check is run BY
the receiving team against its own endpoint (a Pub/Sub push URL, or anything that takes the
same JSON) and says, per obligation of docs/RECEIVER_CONTRACT.md, PASS, FAIL or UNVERIFIED:

  python scripts/receiver_conformance.py https://wms.example/push \\
      --header "Authorization: Bearer <token>" \\
      --applied-url "https://wms.example/applied/{key}" --count-field result.applied

Exit code: 0 all pass, 1 something failed, 2 nothing failed but "applied once" could not be
read (give --applied-url, or show the count some other way). Each run uses a fresh key and a
case id that starts with CONF-, so a receiver can recognise and discard the test records.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import threading
import urllib.error
import urllib.request
import uuid
from typing import Any

PASS, FAIL, UNVERIFIED = "PASS", "FAIL", "UNVERIFIED"


def envelope(key: str | None, case_id: str, tenant: str | None = None) -> dict[str, Any]:
    """A Pub/Sub push body carrying one decision, with or without its idempotency_key."""
    attributes: dict[str, str] = {}
    if key:
        attributes["idempotency_key"] = key
    if tenant:
        attributes["tenant_id"] = tenant
    data = {"case_id": case_id, "outcome": "RELEASED_BY_HUMAN", "approval_id": case_id.lower()}
    return {
        "message": {
            "data": base64.b64encode(json.dumps(data).encode()).decode(),
            "attributes": attributes,
            "messageId": uuid.uuid4().hex,
        },
        "subscription": "projects/conformance/subscriptions/conformance",
    }


def _post(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> int:
    """The HTTP status of a push, 0 when the receiver did not answer."""
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - the operator's own URL
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except (urllib.error.URLError, OSError):
        return 0


def _get_json(url: str, headers: dict[str, str], timeout: float) -> Any:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return json.loads(response.read())
    except Exception:  # noqa: BLE001 - an unreadable count is reported, not raised
        return None


def _dig(document: Any, path: str) -> Any:
    for part in path.split("."):
        if not isinstance(document, dict) or part not in document:
            return None
        document = document[part]
    return document


def _acknowledged(status: int) -> bool:
    return 200 <= status < 300


def check(
    url: str, *, headers: dict[str, str] | None = None, applied_url: str | None = None,
    count_field: str = "applied", concurrency: int = 8, tenant: str | None = None,
    timeout: float = 10.0,
) -> list[tuple[str, str, str]]:
    """Run the obligations against `url` and return (name, PASS|FAIL|UNVERIFIED, detail) rows."""
    headers = headers or {}
    run_id = uuid.uuid4().hex[:12]
    key, case_id = f"conf-{run_id}", f"CONF-{run_id}"
    rows: list[tuple[str, str, str]] = []

    def verdict(name: str, ok: bool, detail: str) -> None:
        rows.append((name, PASS if ok else FAIL, detail))

    first = _post(url, envelope(key, case_id, tenant), headers, timeout)
    verdict("acknowledges a first delivery", _acknowledged(first), f"HTTP {first or 'no answer'}")
    repeat = _post(url, envelope(key, case_id, tenant), headers, timeout)
    verdict("acknowledges a repeat of the same key", _acknowledged(repeat), f"HTTP {repeat or 'no answer'}")

    statuses: list[int] = []
    lock = threading.Lock()

    def deliver() -> None:
        status = _post(url, envelope(key, case_id, tenant), headers, timeout)
        with lock:
            statuses.append(status)

    workers = [threading.Thread(target=deliver) for _ in range(concurrency)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    refused = [s for s in statuses if not _acknowledged(s)]
    verdict(
        f"acknowledges {concurrency} concurrent repeats", not refused and len(statuses) == concurrency,
        f"{len(statuses) - len(refused)} of {concurrency} acknowledged",
    )

    keyless = _post(url, envelope(None, f"{case_id}-NOKEY", tenant), headers, timeout)
    verdict(
        "refuses a message without an idempotency_key", keyless != 0 and not _acknowledged(keyless),
        f"HTTP {keyless or 'no answer'}; a message that cannot be deduplicated must not be applied",
    )

    if not applied_url:
        rows.append(("applied once", UNVERIFIED, "no --applied-url: the check cannot see how many times the key was applied"))
        return rows
    count = _dig(_get_json(applied_url.format(key=key), headers, timeout), count_field)
    if count is None:
        rows.append(("applied once", FAIL, f"could not read {count_field!r} for the key from {applied_url}"))
    else:
        verdict("applied once", count == 1, f"applied {count} time(s) after {2 + concurrency} deliveries of one key")
    return rows


def exit_code(rows: list[tuple[str, str, str]]) -> int:
    if any(result == FAIL for _, result, _ in rows):
        return 1
    return 2 if any(result == UNVERIFIED for _, result, _ in rows) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check that a receiver of Floorline's decisions meets docs/RECEIVER_CONTRACT.md")
    parser.add_argument("url", help="the receiver's push URL")
    parser.add_argument("--header", action="append", default=[], metavar="'Name: value'", help="a header sent with every request (repeatable)")
    parser.add_argument("--applied-url", help="URL template that returns how many times a key was applied; {key} is replaced")
    parser.add_argument("--count-field", default="applied", help="dotted path of that count in the JSON answer")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--tenant", help="send a tenant_id attribute")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args(argv)
    headers = {}
    for line in args.header:
        name, _, value = line.partition(":")
        headers[name.strip()] = value.strip()
    rows = check(
        args.url, headers=headers, applied_url=args.applied_url, count_field=args.count_field,
        concurrency=args.concurrency, tenant=args.tenant, timeout=args.timeout,
    )
    for name, result, detail in rows:
        print(f"[{result}] {name} - {detail}")
    return exit_code(rows)


if __name__ == "__main__":
    sys.exit(main())
