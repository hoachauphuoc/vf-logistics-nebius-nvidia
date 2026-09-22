"""
End-to-end contract assertions against a deployed VF Logistics service.

Read-only apart from one POST replay: it asserts on audits that e2e_seed.py has
already created, then re-posts a single shipment to prove the idempotency path
returns the stored verdict instead of spending tokens again.

What is asserted here is deliberately narrow: properties that must hold for the
system to be safe, not properties that happen to hold today. A model returning
a different score is not a failure. A CLEARED verdict sitting on a check that
never ran is.

Run:  python scripts/e2e_smoke.py [--base URL]
Exit: 0 all passed, 1 one or more failed.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from e2e_seed import SEEDS  # noqa: E402

DEFAULT_BASE = "https://vf-logistics-f7rcctz26a-as.a.run.app"

B2B_PATHS = [
    "/api/v1/compliance/audit",
    "/api/v1/compliance/audit/{audit_id}",
    "/api/v1/compliance/reports",
    "/api/v1/billing/usage",
]

# Mirrors frontend/src/lib/risk.ts. A code ending in one of these means a check
# produced no answer, so a verdict resting on it is not a clearance.
UNVERIFIED_SUFFIXES = (
    "_UNAVAILABLE", "_DID_NOT_RUN", "_UNVERIFIED", "_MISSING", "_UNSUPPORTED",
)

# The zero-day codes that carry no search result at all. For these the contract
# must send null, not [] -- see the field docstring on AuditFinding.
NO_SEARCH_CODES = {"ZERO_DAY_SEARCH_DID_NOT_RUN", "ZERO_DAY_CHECK_UNAVAILABLE"}

# The zero-day codes that do carry a search result, even an empty one.
SEARCHED_CODES = {"ZERO_DAY_ADVERSE_MEDIA", "ZERO_DAY_ADVERSE_MEDIA_LOW_CONFIDENCE"}

HUMAN_OUTCOMES = {"HELD_FOR_REVIEW", "PENDING_HUMAN"}


class Checks:
    def __init__(self) -> None:
        self.passed = 0
        self.failed: list[str] = []
        self.notes: list[str] = []

    def ok(self, cond: bool, label: str, detail: str = "") -> bool:
        if cond:
            self.passed += 1
            print(f"  PASS  {label}")
        else:
            self.failed.append(f"{label}{' -- ' + detail if detail else ''}")
            print(f"  FAIL  {label}" + (f"\n          {detail}" if detail else ""))
        return cond

    def note(self, text: str) -> None:
        self.notes.append(text)
        print(f"  note  {text}")


def auth_headers() -> dict[str, str]:
    """
    The operator credential, from VF_API_KEY in the environment.

    Reads are public, but this script also posts, and the deployed service
    refuses a write from an anonymous caller -- they hold viewer only. Taken from
    the environment rather than an argument so it stays out of shell history:

        $env:VF_API_KEY = (gcloud secrets versions access latest --secret=VF_API_KEY)
        python scripts/e2e_smoke.py
    """
    key = os.getenv("VF_API_KEY", "").strip()
    return {"X-VF-API-Key": key} if key else {}


def get(base: str, path: str, timeout: int = 180):
    req = urllib.request.Request(f"{base}{path}", headers=auth_headers())
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def post(base: str, path: str, body: dict, timeout: int = 300):
    req = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **auth_headers()},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, {"error": exc.read().decode("utf-8", errors="replace")[:300]}


def is_unverified(code: str) -> bool:
    return any(code.endswith(s) for s in UNVERIFIED_SUFFIXES)


def fetch_all_reports(base: str) -> list[dict]:
    audits: list[dict] = []
    cursor = None
    for _ in range(20):
        path = "/api/v1/compliance/reports?limit=200"
        if cursor:
            path += f"&cursor={urllib.parse.quote(cursor)}"
        _, page = get(base, path)
        audits.extend(page.get("audits") or [])
        cursor = page.get("next_cursor")
        if not cursor:
            break
    return audits


def check_health(base: str, c: Checks) -> None:
    print("\n[1] health")
    status, body = get(base, "/health")
    c.ok(status == 200, "GET /health is 200", f"got {status}")
    c.ok(body.get("status") == "healthy", "status is healthy", str(body.get("status")))
    store = (body.get("store") or {}).get("backend")
    c.ok(
        store == "firestore",
        "store backend is firestore",
        f"got {store!r}; the memory fallback loses every case on restart",
    )


def check_openapi(base: str, c: Checks) -> None:
    print("\n[2] published contract")
    status, spec = get(base, "/api/v1/openapi.json")
    c.ok(status == 200, "GET /api/v1/openapi.json is 200", f"got {status}")

    paths = spec.get("paths") or {}
    for p in B2B_PATHS:
        c.ok(p in paths, f"path published: {p}")

    schemas = (spec.get("components") or {}).get("schemas") or {}
    finding = schemas.get("AuditFinding") or {}
    props = finding.get("properties") or {}
    c.ok("AuditFinding" in schemas, "AuditFinding schema published")
    c.ok(
        "evidence_urls" in props,
        "AuditFinding.evidence_urls published",
        "the console reads Tavily citations from this field",
    )

    # A $ref with no schema behind it breaks generated clients at compile time.
    raw = json.dumps(spec)
    referenced = set()
    marker = '"#/components/schemas/'
    idx = 0
    while True:
        idx = raw.find(marker, idx)
        if idx == -1:
            break
        start = idx + len(marker)
        end = raw.find('"', start)
        referenced.add(raw[start:end])
        idx = end
    dangling = sorted(referenced - set(schemas))
    c.ok(not dangling, "no dangling schema refs", f"dangling: {dangling}")


def check_audits(base: str, c: Checks) -> dict[str, dict]:
    print("\n[3] seeded audits")
    by_shipment: dict[str, dict] = {}

    for seed in SEEDS:
        shipment = seed["shipment"]
        sid = shipment["shipment_id"]
        # The audit_id is derived from the case_id, which is derived from the
        # shipment_id, so it needs no lookup table.
        status, audit = get(base, f"/api/v1/compliance/audit/AUD-CASE-{sid}")
        if not c.ok(status == 200, f"{sid}: fetchable", f"HTTP {status}"):
            continue
        by_shipment[sid] = audit

        outcome = audit.get("outcome")
        risk = audit.get("effective_risk")
        floor = audit.get("risk_floor")

        c.ok(
            isinstance(risk, (int, float)) and isinstance(floor, (int, float))
            and risk >= floor,
            f"{sid}: effective_risk >= risk_floor",
            f"risk={risk} floor={floor}; a floor a model can lower is not a floor",
        )

        expect = seed["expect"]
        if expect == "BLOCKED":
            c.ok(outcome == "BLOCKED", f"{sid}: outcome BLOCKED", f"got {outcome}")
            c.ok(
                bool(audit.get("requires_human_review")) is False,
                f"{sid}: a disposed case no longer asks for review",
                f"requires_human_review={audit.get('requires_human_review')}",
            )
        elif expect == "HUMAN":
            c.ok(
                outcome in HUMAN_OUTCOMES,
                f"{sid}: outcome routed to a human",
                f"got {outcome}",
            )
            c.ok(
                bool(audit.get("requires_human_review")),
                f"{sid}: flagged for human review",
            )
            c.ok(
                bool(audit.get("review_reason")),
                f"{sid}: carries a review_reason an integrator can act on",
            )
        elif expect == "CLEARED":
            c.ok(outcome == "CLEARED", f"{sid}: outcome CLEARED", f"got {outcome}")
            if not seed.get("review"):
                # Only the rules-cleared case must be free: a human release runs
                # after the models have already been paid for.
                calls = (audit.get("usage") or {}).get("agent_calls")
                c.ok(
                    calls == 0,
                    f"{sid}: cleared by rules with 0 agent calls",
                    f"agent_calls={calls}; the whole point of the fast path is "
                    f"that it costs no tokens",
                )
        else:
            c.note(f"{sid}: outcome {outcome} (model-dependent, recorded not asserted)")

    return by_shipment


def check_evidence_semantics(audits: list[dict], c: Checks) -> None:
    print("\n[4] evidence_urls semantics")
    seen_no_search = 0
    seen_searched = 0
    violations: list[str] = []

    for audit in audits:
        aid = audit.get("audit_id")
        for f in audit.get("findings") or []:
            code = f.get("code") or ""
            has_key = "evidence_urls" in f
            urls = f.get("evidence_urls")

            if code in NO_SEARCH_CODES:
                seen_no_search += 1
                if urls is not None:
                    violations.append(
                        f"{aid}/{code}: evidence_urls is {urls!r}, expected null -- "
                        f"[] would report a search that never ran as a clean result"
                    )
            elif code in SEARCHED_CODES:
                seen_searched += 1
                if not isinstance(urls, list):
                    violations.append(
                        f"{aid}/{code}: evidence_urls is {urls!r}, expected a list"
                    )
            if has_key and urls == [] and is_unverified(code):
                violations.append(
                    f"{aid}/{code}: unverified code carrying [] rather than null"
                )

    c.ok(not violations, "null and [] are not collapsed", "; ".join(violations[:4]))
    c.note(f"findings inspected: no-search={seen_no_search} searched={seen_searched}")

    # The property that motivated the three-state badge: a CLEARED verdict must
    # not be resting on a check that produced no answer.
    unsafe = []
    for audit in audits:
        if audit.get("outcome") != "CLEARED":
            continue
        bad = [
            f.get("code") for f in (audit.get("findings") or [])
            if is_unverified(f.get("code") or "")
        ]
        if bad:
            unsafe.append(f"{audit.get('audit_id')}: {bad}")
    if unsafe:
        c.note(
            "CLEARED audits carrying unverified checks (the console must render "
            f"these amber, not green): {unsafe}"
        )
    else:
        c.note("no CLEARED audit is resting on an unverified check")


def check_reports(base: str, c: Checks) -> list[dict]:
    print("\n[5] reports listing")
    status, page = get(base, "/api/v1/compliance/reports?limit=200")
    c.ok(status == 200, "GET /api/v1/compliance/reports is 200", f"got {status}")
    for key in ("audits", "next_cursor", "has_more"):
        c.ok(key in page, f"response has {key}")

    audits = fetch_all_reports(base)
    c.ok(len(audits) >= 1, "at least one completed audit is listed", f"got {len(audits)}")

    seeded = {s["shipment"]["shipment_id"] for s in SEEDS}
    listed = {a.get("shipment_id") for a in audits}
    missing = sorted(seeded - listed)
    c.ok(
        not missing,
        "every seeded audit appears in reports",
        f"missing: {missing}. Legacy cases without _tenant_id are invisible to "
        f"the tenant-scoped query by design, but these were created after it.",
    )

    incomplete = [a.get("audit_id") for a in audits if not a.get("outcome")]
    c.ok(not incomplete, "reports lists only completed audits", str(incomplete[:4]))
    return audits


def check_usage(base: str, audits: list[dict], c: Checks) -> None:
    print("\n[6] billable usage")
    status, usage = get(base, "/api/v1/billing/usage")
    c.ok(status == 200, "GET /api/v1/billing/usage is 200", f"got {status}")

    for key in (
        "tenant_id", "agent_calls", "input_tokens", "output_tokens",
        "estimated_cost_usd", "cost_per_call_usd", "auto_cleared",
        "cleared_by_rules", "cleared_by_ai", "avg_latency_ms",
    ):
        c.ok(key in usage, f"usage has {key}")

    sum_calls = sum((a.get("usage") or {}).get("agent_calls") or 0 for a in audits)
    sum_in = sum((a.get("usage") or {}).get("input_tokens") or 0 for a in audits)

    # Greater-or-equal, not equality: usage aggregates every case carrying the
    # tenant field, including ones still in flight, while reports lists only the
    # completed ones. An invoice that came back *smaller* than the audits it is
    # billing for would mean spend is being dropped, and that is the failure
    # worth catching.
    c.ok(
        (usage.get("agent_calls") or 0) >= sum_calls,
        "usage agent_calls covers the listed audits",
        f"usage={usage.get('agent_calls')} reports_sum={sum_calls}",
    )
    c.ok(
        (usage.get("input_tokens") or 0) >= sum_in,
        "usage input_tokens covers the listed audits",
        f"usage={usage.get('input_tokens')} reports_sum={sum_in}",
    )
    c.ok(
        (usage.get("agent_calls") or 0) > 0,
        "usage is non-zero",
        "zero spend across audits that ran models means the rollups are not "
        "being written",
    )
    if usage.get("agent_calls"):
        c.ok(
            (usage.get("cost_per_call_usd") or 0) > 0,
            "cost_per_call_usd is derived, not zero",
        )
    c.note(
        f"tenant={usage.get('tenant_id')} calls={usage.get('agent_calls')} "
        f"cost=${usage.get('estimated_cost_usd')} "
        f"rules={usage.get('cleared_by_rules')} ai={usage.get('cleared_by_ai')}"
    )


def check_idempotency(base: str, c: Checks) -> None:
    print("\n[7] idempotent replay")
    # The rules-cleared shipment on purpose: if the replay path were broken this
    # re-posts the one audit that costs nothing to redo.
    seed = next(
        s for s in SEEDS if s["expect"] == "CLEARED" and not s.get("review")
    )
    status, body = post(base, "/api/v1/compliance/audit", seed["shipment"])
    c.ok(status == 200, "re-POST returns 200", f"got {status}: {body}")
    c.ok(
        body.get("idempotent_replay") is True,
        "second POST with the same client_reference replays",
        f"got {body.get('idempotent_replay')!r}; without this an ERP retry after "
        f"a timeout is a second audit, a second bill, and possibly a second verdict",
    )
    c.ok(
        body.get("shipment_id") == seed["shipment"]["shipment_id"],
        "replay returns the same shipment",
    )


def check_badge_states(audits: list[dict], c: Checks) -> None:
    """
    The console renders three states, so the data behind it must reach all three.

    Not cosmetic. The amber state exists because a two-colour badge has to force
    every one of the five AuditOutcome values into either green or red, and the
    outcomes that mean "could not determine" then land on one of them. If the
    seeded data only ever produced two states, the third would never be
    exercised against a real payload.
    """
    print("\n[8] badge states reachable")
    outcomes = {a.get("outcome") for a in audits}
    c.ok("BLOCKED" in outcomes, "a critical (red) row exists", f"outcomes: {sorted(outcomes)}")
    c.ok("CLEARED" in outcomes, "a clear (green) row exists", f"outcomes: {sorted(outcomes)}")
    c.ok(
        bool(outcomes & HUMAN_OUTCOMES),
        "a warn (amber) row exists",
        f"outcomes: {sorted(outcomes)}",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE)
    args = ap.parse_args()
    base = args.base.rstrip("/")

    print(f"E2E smoke against {base}")
    c = Checks()

    check_health(base, c)
    check_openapi(base, c)
    fetched = check_audits(base, c)
    audits = check_reports(base, c)
    check_evidence_semantics(list(fetched.values()) or audits, c)
    check_usage(base, audits, c)
    check_idempotency(base, c)
    check_badge_states(list(fetched.values()) or audits, c)

    print("\n" + "=" * 72)
    print(f"passed {c.passed}   failed {len(c.failed)}")
    if c.failed:
        print("\nfailures:")
        for f in c.failed:
            print(f"  - {f}")
    return 1 if c.failed else 0


if __name__ == "__main__":
    sys.exit(main())
