"""
Does the model-switch cost guard hold against the live API?

    $env:VF_API_KEY = (gcloud secrets versions access latest --secret=VF_API_KEY)
    python scripts/check_model_switch_guard.py

`POST /api/v1/config/model` repoints the model used by fraud detection and compliance --
the two agents that run on EVERY shipment -- and the change takes effect on the next one
with nothing in the audit trail. config.set_model() refuses a switch that would raise the
per-token rate beyond MODEL_SWITCH_MAX_RATE_MULTIPLE of the cheapest priced model unless
`confirm_higher_cost` is passed.

Unit tests cover set_model() itself. This checks the two things they cannot:

1. THE FLASK BOUNDARY. set_model RAISES CostlierModel rather than returning False, and an
   exception escaping a route handler is a 500, not a 409. That distinction is the point --
   a 500 says the system is broken, a 409 says confirm and retry.

2. THE RATCHET, end to end. The guard used to compare against the INCUMBENT model, so
   Nano -> Super (4.0x) then Super -> Ultra (3.3x) both passed a 5.0 limit and two ordinary
   requests put Ultra on the hot path. Step 3 below walks that exact path and expects a
   refusal, because the baseline is now the cheapest model rather than the current one.

Nano is restored at the end whatever happens.
"""

import json
import subprocess
import urllib.error
import urllib.request

BACKEND = "https://vf-logistics-f7rcctz26a-as.a.run.app"
NANO = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
SUPER = "nvidia/nemotron-3-super-120b-a12b"
ULTRA = "nvidia/Nemotron-3-Ultra-550b-a55b"


def api_key() -> str:
    out = subprocess.run(
        ["gcloud", "secrets", "versions", "access", "latest",
         "--secret=VF_API_KEY", "--project=vf-fraud-detection-phuochoa"],
        capture_output=True, text=True, shell=True,
    )
    return out.stdout.strip()


KEY = api_key()


def call(body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        BACKEND + "/api/v1/config/model",
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json", "X-VF-API-Key": KEY},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"_raw": raw[:300]}


def current() -> str:
    """
    The model in force, read from `current_model`.

    Not `model`. The GET response nests the rate card under `pricing` and names the
    selection `current_model`, and reading the wrong key made a clean run report every
    state as "?" and then fail on a restore that had actually worked.
    """
    req = urllib.request.Request(
        BACKEND + "/api/v1/config/model", headers={"X-VF-API-Key": KEY},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode()).get("current_model", "?")


def main() -> int:
    failures = []
    print(f"starting model: {current()}\n")

    print("1. Ultra WITHOUT confirmation -- expect 409, not 500 and not 200")
    code, body = call({"model": ULTRA})
    print(f"   -> {code}")
    if code == 409:
        print(f"   rate_multiple  {body.get('rate_multiple')}")
        print(f"   limit          {body.get('limit')}")
        print(f"   confirm_with   {json.dumps(body.get('confirm_with'))}")
        print(f"   error          {str(body.get('error'))[:110]}")
    else:
        print(f"   body: {json.dumps(body)[:300]}")
        failures.append(
            f"expected 409, got {code}"
            + (" -- the exception crossed the Flask boundary as a 500"
               if code == 500 else "")
        )
    if current() == ULTRA:
        failures.append("a REFUSED switch took effect anyway")
    print(f"   model still: {current()}\n")

    print("2. Super WITHOUT confirmation -- 4.0x, under the 5.0 limit, expect 200")
    code, body = call({"model": SUPER})
    print(f"   -> {code}  model={body.get('model')}  "
          f"multiple={body.get('rate_multiple_vs_previous')}")
    if code != 200:
        failures.append(f"Super should be permitted, got {code}")
    print(f"   model now: {current()}\n")

    print("3. Ultra from Super -- the RATCHET. Relative maths would allow this at 3.3x")
    code, body = call({"model": ULTRA})
    print(f"   -> {code}")
    if code != 409:
        failures.append(
            f"RATCHET NOT CLOSED: Ultra reachable from Super with {code}"
        )
    else:
        print(f"   rate_multiple {body.get('rate_multiple')} "
              "(absolute, against the cheapest model)")
    print(f"   model still: {current()}\n")

    print("4. Ultra WITH confirmation -- expect 200")
    code, body = call({"model": ULTRA, "confirm_higher_cost": True})
    print(f"   -> {code}  model={body.get('model')}")
    if code != 200:
        failures.append(f"confirmed switch should succeed, got {code}")
    print(f"   model now: {current()}\n")

    print("5. An unpriced model -- expect 400, the old contract, not an exception")
    code, body = call({"model": "definitely/not-real"})
    print(f"   -> {code}  error={str(body.get('error'))[:70]}")
    if code != 400:
        failures.append(f"unknown model should be 400, got {code}")

    print("\nrestoring Nano")
    code, _ = call({"model": NANO})
    restored = current()
    print(f"   -> {code}  model={restored}")
    if restored != NANO:
        failures.append(f"FAILED TO RESTORE: still on {restored}")

    print("\n" + "=" * 62)
    if failures:
        for f in failures:
            print(f"  FAIL  {f}")
        return 1
    print("  all five behaved as designed, and Nano is restored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
