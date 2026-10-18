"""
Measure a real-model run: cost, model time, tokens, and whether what the model extracted is in
the document it read.

Real models cannot be measured offline, so this is run by the operator against a deployed
service, with the operator's key. Each sample document is uploaded (it spends tokens and adds
cases to the board; it never resets the board), the case is read back, and per case it reports:

  cost_usd, model_seconds, tokens, agent_calls, tavily_searches   from the case itself
  fields_grounded / fields_checked   extracted fields whose value appears in the document's own
                                     text. A field that does not is a hallucination.
  missed                             identifiers present in the document (tax id, HS code) that
                                     the model did not extract

  $env:VF_API_KEY = "<operator key>"
  python scripts/measure_live_run.py --base https://<service-url> --yes-upload --out measure.json

Grounded means "the text is in the document", not "the value is right for the business": a
fraudulent document can be extracted faithfully. Run it twice and compare to see run-to-run drift.
"""

from __future__ import annotations

import argparse
import http.client
import io
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vf_logistics.verifier import is_placeholder_text  # noqa: E402

GROUNDED_FIELDS = (
    "shipper_company", "shipper_tax_id", "receiver_company", "cargo_description",
    "hs_code", "declared_value", "origin", "destination",
)
# Identifiers that can be found in the source by their shape alone.
IDENTIFIERS = {"shipper_tax_id": r"\b\d{10}\b", "hs_code": r"\b\d{4}\.\d{2}\b"}
SAMPLE_DOCS = (
    "clean_bol.pdf", "unknown_shipper_bol.pdf", "identity_spoof_bol.pdf", "over_ceiling_bol.pdf",
    "dual_use_bol.pdf", "dirty_bol.pdf", "injected_bol.pdf",
)


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def _candidates(value: Any) -> list[str]:
    """The ways a document may write a value: a number as 9600, 9,600 or 9,600.00."""
    if isinstance(value, bool):
        return [_norm(value)]
    if isinstance(value, (int, float)):
        return [_norm(f"{value:,.2f}"), _norm(f"{value:,.0f}"), _norm(value)]
    return [_norm(value)]


def _grounded(value: Any, source: str) -> bool:
    haystack = f" {_norm(source)} "
    return any(c and f" {c} " in haystack for c in _candidates(value))


def measure_case(case: dict[str, Any], source_text: str) -> dict[str, Any]:
    """What one case cost, and how much of what the model extracted is in its source text."""
    shipment = case.get("shipment") or {}
    checked, ungrounded = 0, []
    for name in GROUNDED_FIELDS:
        value = shipment.get(name)
        if value in (None, "") or (isinstance(value, str) and is_placeholder_text(value)):
            continue
        checked += 1
        if not _grounded(value, source_text):
            ungrounded.append(name)
    extracted = " ".join(_norm(v) for v in shipment.values() if v not in (None, ""))
    missed = [
        name for name, pattern in IDENTIFIERS.items()
        if re.search(pattern, source_text) and _norm(re.search(pattern, source_text).group(0)) not in extracted  # type: ignore[union-attr]
    ]
    return {
        "case_id": case.get("case_id"),
        "state": case.get("state"),
        "cost_usd": case.get("_estimated_cost_usd"),
        "model_seconds": round((case.get("_sum_latency_ms") or 0) / 1000, 3),
        "tokens": (case.get("_input_tokens") or 0) + (case.get("_output_tokens") or 0),
        "agent_calls": case.get("_agent_calls"),
        "tavily_searches": case.get("_tavily_searches"),
        "fields_checked": checked,
        "fields_grounded": checked - len(ungrounded),
        "ungrounded": ungrounded,
        "missed": missed,
    }


def blocked_at_intake(case: dict[str, Any]) -> bool:
    """A document Model Armor stopped before any model read it: nothing was extracted to score."""
    return str(case.get("case_id") or "").startswith("CASE-BLOCKED-")


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Totals and medians over the measured cases."""
    checked = sum(r["fields_checked"] for r in rows)
    grounded = sum(r["fields_grounded"] for r in rows)
    return {
        "cases": len(rows),
        "total_cost_usd": round(sum(r["cost_usd"] or 0 for r in rows), 6),
        "median_cost_usd": statistics.median(r["cost_usd"] or 0 for r in rows) if rows else None,
        "median_model_seconds": statistics.median(r["model_seconds"] for r in rows) if rows else None,
        "fields_checked": checked,
        "fields_grounded": grounded,
        "grounded_rate": round(grounded / checked, 4) if checked else None,
        "cases_with_a_missed_identifier": sum(1 for r in rows if r["missed"]),
    }


def _headers() -> dict[str, str]:
    key = (os.getenv("VF_API_KEY") or "").strip()
    return {"X-VF-API-Key": key} if key else {}


def _upload(base: str, path: Path) -> tuple[dict[str, Any] | None, float]:
    """POST one PDF as multipart/form-data; returns (answer, seconds). None if the connection dropped."""
    boundary = uuid.uuid4().hex
    body = io.BytesIO()
    body.write(f"--{boundary}\r\n".encode())
    body.write(f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode())
    body.write(b"Content-Type: application/pdf\r\n\r\n")
    body.write(path.read_bytes())
    body.write(f"\r\n--{boundary}--\r\n".encode())
    request = urllib.request.Request(
        base + "/api/v1/events/document", data=body.getvalue(), method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", **_headers()},
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310 - the operator's own service
            return json.load(response), time.monotonic() - started
    except urllib.error.HTTPError as exc:
        try:
            return json.load(exc), time.monotonic() - started
        except ValueError:
            return None, time.monotonic() - started
    except (ConnectionResetError, TimeoutError, http.client.HTTPException, urllib.error.URLError):
        return None, time.monotonic() - started


def _get_case(base: str, case_id: str) -> dict[str, Any] | None:
    request = urllib.request.Request(f"{base}/api/v1/orchestrator/case/{case_id}", headers=_headers())
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            return json.load(response)
    except (urllib.error.URLError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure a real-model run against a deployed service")
    parser.add_argument("--base", default=os.getenv("VF_TEST_BASE", ""), help="the service URL (or set VF_TEST_BASE)")
    parser.add_argument("--yes-upload", action="store_true", help="confirm that the run spends tokens and adds cases")
    parser.add_argument("--docs", default=str(ROOT / "sample_docs"), help="folder with the sample PDFs")
    parser.add_argument("--out", help="write the rows and the summary as JSON to this file")
    args = parser.parse_args(argv)
    base = args.base.rstrip("/")
    if not base:
        parser.error("give --base or set VF_TEST_BASE")
    if not args.yes_upload:
        print("Uploading spends model tokens and adds cases to the board at " + base + ". Re-run with --yes-upload.")
        return 2
    if not _headers():
        print("VF_API_KEY is not set: an upload is a write and needs the operator key.")
        return 2

    from vf_logistics.model_armor import extract_pdf_text

    rows: list[dict[str, Any]] = []
    for name in SAMPLE_DOCS:
        path = Path(args.docs) / name
        answer, seconds = _upload(base, path)
        if not answer or not answer.get("case_id"):
            print(f"[BLOCKED/NO CASE] {name}: {answer.get('error') if answer else 'no answer'} ({seconds:.1f}s)")
            continue
        case = _get_case(base, answer["case_id"])
        if not case or not case.get("shipment"):
            print(f"[BLOCKED/NO CASE] {name}: no extracted shipment ({seconds:.1f}s)")
            continue
        if blocked_at_intake(case):
            print(f"[BLOCKED AT INTAKE] {name}: stopped before any model read it, as intended (not scored)")
            continue
        text, _ = extract_pdf_text(path.read_bytes())
        row = {**measure_case(case, text), "file": name, "wall_seconds": round(seconds, 2)}
        rows.append(row)
        print(
            f"[{row['state']}] {name}: ${row['cost_usd']:.4f}, model {row['model_seconds']}s, wall {row['wall_seconds']}s, "
            f"{row['fields_grounded']}/{row['fields_checked']} grounded"
            + (f", UNGROUNDED {row['ungrounded']}" if row["ungrounded"] else "")
            + (f", MISSED {row['missed']}" if row["missed"] else "")
        )
    summary = summarise(rows)
    print(json.dumps(summary, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps({"rows": rows, "summary": summary}, indent=2), encoding="utf-8")
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
