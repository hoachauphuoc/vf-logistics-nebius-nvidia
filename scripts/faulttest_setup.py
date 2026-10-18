"""
Write the settings of the separate service vf-app-faulttest (review 2026-10-18, open items 1 and 2).

Creates, in a folder git ignores (default orchestrator/runs/faulttest), a fresh API key and session
secret for this service only, and env.yaml for `gcloud run deploy --env-vars-file`. Nothing is
printed: the secrets go from the file to the deploy and are deleted with the folder afterwards.

  python scripts/faulttest_setup.py --project <id> [--fault kill_after_publish|slow_after_execute]
"""

from __future__ import annotations

import argparse
import json
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TENANT = "faulttest"
OPERATOR = "op@faulttest.test"
FAULTS = ("kill_after_publish", "slow_after_execute")


def settings(project: str, fault: str, api_key: str, session_secret: str) -> dict[str, str]:
    """The service's environment: the fault, its own topic and ledger, its own tenant and secrets."""
    if fault not in FAULTS:
        raise ValueError(f"fault must be one of {', '.join(FAULTS)}")
    return {
        "FLASK_APP_MODULE": "vf_logistics.faulttest:app",
        "FAULT_TEST_ALLOWED": "true",
        "FAULT": fault,
        "FAULT_SLOW_SECONDS": "30",
        "PROJECT_ID": project,
        "STORE_BACKEND": "firestore",
        "WORKER_MODE": "ondemand",
        "IAP_ENABLED": "false",
        "ANONYMOUS_ROLE": "none",
        "MULTI_TENANT": "true",
        "VF_TENANT_MEMBERS": json.dumps({OPERATOR: {TENANT: "operator"}, "service": {TENANT: "operator"}}),
        "VF_API_KEY": api_key,
        "VF_SESSION_SECRET": session_secret,
        "DECISIONS_TOPIC": "faulttest-decisions",
        "SENT_LEDGER_SUBSCRIPTION": "faulttest-sent-ledger",
    }


def write(folder: Path, project: str, fault: str) -> Path:
    """Write api_key.txt, session_secret.txt and env.yaml; reuse the secrets if they exist."""
    folder.mkdir(parents=True, exist_ok=True)
    key_file, secret_file = folder / "api_key.txt", folder / "session_secret.txt"
    if not key_file.exists():
        key_file.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    if not secret_file.exists():
        secret_file.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    env = settings(project, fault, key_file.read_text(encoding="utf-8").strip(), secret_file.read_text(encoding="utf-8").strip())
    out = folder / "env.yaml"
    # JSON strings are valid YAML scalars, so every value is quoted exactly once.
    out.write_text("".join(f"{name}: {json.dumps(value)}\n" for name, value in env.items()), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the vf-app-faulttest settings")
    parser.add_argument("--project", required=True)
    parser.add_argument("--fault", default="kill_after_publish", choices=FAULTS)
    parser.add_argument("--out", default=str(ROOT / "orchestrator" / "runs" / "faulttest"))
    args = parser.parse_args(argv)
    path = write(Path(args.out), args.project, args.fault)
    print(f"wrote {path} (FAULT={args.fault}); the secrets are in the same folder, not printed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
