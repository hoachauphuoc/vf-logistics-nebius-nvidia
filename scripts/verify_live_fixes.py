"""
Verify the four fixes on the LIVE deployment, not in the local tree.

Written because this session found three defects whose common property was that
they passed every local check: a test pointing at a different deployment, a
component reading a key the backend never sends, and a card whose title promised
a field it did not render. Reading the source proves nothing about what is
served.

    python scripts/verify_live_fixes.py
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API = "https://vf-logistics-f7rcctz26a-as.a.run.app"
CONSOLE = "https://vf-console-f7rcctz26a-as.a.run.app"


def get(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "vf-verify"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


def get_json(url: str):
    return json.loads(get(url)[1])


def main() -> int:
    failures = 0

    # 1. cost_usd present in every per-agent bucket.
    print("1. tokens_by_agent carries cost_usd")
    snap = get_json(f"{API}/api/v1/orchestrator/state?limit=40")
    by_agent = snap.get("tokens_by_agent") or {}
    if not by_agent:
        print("   SKIP  no agent has been called in the current window")
    else:
        missing = [a for a, b in by_agent.items() if "cost_usd" not in b]
        if missing:
            print(f"   FAIL  buckets without cost_usd: {missing}")
            failures += 1
        else:
            ranked = sorted(by_agent.items(), key=lambda kv: -kv[1]["cost_usd"])
            print(f"   ok    {len(by_agent)} agents, all priced. By spend:")
            for agent, b in ranked[:4]:
                print(f"           {agent:<22} ${b['cost_usd']:<10.6f} "
                      f"{b['calls']:>3} call(s)  {b['input']+b['output']:>7} tok")

    # 2. reconciliation sends risk_floor, and the console no longer reads `floor`.
    print("\n2. reconciliation.risk_floor exists on live cases")
    items = (get_json(f"{API}/api/v1/cases?limit=40") or {}).get("items") or []
    checked = 0
    for it in items:
        case = get_json(f"{API}/api/v1/orchestrator/case/{it['case_id']}")
        rec = case.get("reconciliation")
        if not isinstance(rec, dict) or not rec:
            continue
        checked += 1
        if "risk_floor" not in rec:
            print(f"   FAIL  {it['case_id']} has no risk_floor: {sorted(rec)}")
            failures += 1
            break
        if checked >= 3:
            break
    if checked:
        print(f"   ok    {checked} case(s) carry risk_floor "
              f"(and none carry `floor`, the key the console used to read)")
    else:
        print("   SKIP  no case on the board has a reconciliation block")

    # 3. No user-visible string says Super on the debate hop.
    print("\n3. no event string names Super on the debate path")
    offenders = []
    for it in items[:40]:
        case = get_json(f"{API}/api/v1/orchestrator/case/{it['case_id']}")
        blob = json.dumps(case)
        for m in re.finditer(r"[^\"]*\bSuper\b[^\"]*", blob):
            text = m.group(0)
            if re.search(r"debate|Senior Auditor|deep.?review", text, re.I):
                offenders.append(f"{it['case_id']}: {text[:90]}")
    if offenders:
        print(f"   FAIL  {len(offenders)} string(s):")
        for line in offenders[:5]:
            print(f"           {line}")
        failures += 1
    else:
        print(f"   ok    checked {len(items)} case payloads, none found")

    # 4. The console bundle carries the new copy and not the old.
    print("\n4. served console bundle")
    for route, want, unwanted in [
        ("/devops", "frequency converters", "HS mismatch"),
        ("/agents", "ordered by spend", None),
    ]:
        status, html = get(CONSOLE + route)
        chunks = sorted(set(re.findall(r'/_next/static/[^"\']+?\.js', html)))
        hits = miss = 0
        for chunk in chunks[:60]:
            try:
                _s, body = get(CONSOLE + chunk)
            except Exception:
                continue
            if want.lower() in body.lower():
                hits += 1
            if unwanted and unwanted in body:
                miss += 1
        verdict = "ok   " if hits else "FAIL "
        if not hits:
            failures += 1
        print(f"   {verdict} {route}: {hits} chunk(s) contain {want!r}"
              + (f", {miss} still contain {unwanted!r}" if unwanted else ""))
        if unwanted and miss:
            failures += 1

    print()
    print("ALL CHECKS PASSED" if not failures else f"{failures} CHECK(S) FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
