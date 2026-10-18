"""
Fault injection for the separate service vf-app-faulttest. Never loaded by vf-app.

Two open items of review 2026-10-18 need a real Cloud Run fault: a process killed right after the
broker accepted a decision, and a real gateway 504 on Execute while the work finished. The service
vf-app-faulttest runs the same image as vf-app with FLASK_APP_MODULE pointing here; this module
wraps the real app and installs one fault, chosen by FAULT:

  kill_after_publish   the gunicorn worker ends with os._exit at the record of a publish the broker
                       accepted, once (FAULT_MARKER), so a Resume after the lease meets what a crash
                       leaves: the decision on the topic and no record of it
  slow_after_execute   a finished POST .../execute is held back FAULT_SLOW_SECONDS before its answer,
                       so a service --timeout shorter than that makes Cloud Run's own frontend answer
                       504 although the work is done

It refuses to load without FAULT_TEST_ALLOWED=true, on the service vf-app, and for any other FAULT: a
fault switch that could reach production is the one thing this module must never be.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterable
from typing import Any

from vf_logistics import tools
from vf_logistics.app import app as flask_app

FAULTS = ("kill_after_publish", "slow_after_execute")
MARKER = os.getenv("FAULT_MARKER", "/tmp/vf_fault_fired")

# The audit function the kill fault wraps; looked up at call time so a test can replace it.
real_audit: Callable[..., Any] = tools._audit


def refusal() -> str | None:
    """Why this module must not load here, or None."""
    if os.getenv("FAULT_TEST_ALLOWED", "").strip().lower() != "true":
        return "FAULT_TEST_ALLOWED is not true"
    if os.getenv("K_SERVICE", "").strip() == "vf-app":
        return "this is the production service vf-app"
    if os.getenv("FAULT", "").strip() not in FAULTS:
        return f"FAULT must be one of {', '.join(FAULTS)}"
    return None


async def _killed_at_the_record(
    case_id: str, action: str, detail: dict[str, Any], status: str = "done", tenant_id: str | None = None,
) -> dict[str, Any]:
    accepted = action == "publish_decision" and bool(detail.get("message_id")) and not detail.get("via")
    if accepted and not os.path.exists(MARKER):
        with open(MARKER, "w", encoding="utf-8") as marker:
            marker.write(str(detail.get("message_id")))
        os._exit(17)
    result: dict[str, Any] = await real_audit(case_id, action, detail, status, tenant_id)
    return result


class SlowAfterExecute:
    """WSGI middleware: the app answers in full, then a POST .../execute waits before it is sent."""

    def __init__(self, inner: Any, seconds: float) -> None:
        self.inner = inner
        self.seconds = seconds

    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> Iterable[bytes]:
        captured: list[tuple[Any, Any, Any]] = []

        def capture(status: str, headers: list[tuple[str, str]], exc_info: Any = None) -> Callable[[bytes], None]:
            captured.append((status, headers, exc_info))
            return lambda _data: None

        result = self.inner(environ, capture)
        try:
            body = b"".join(result)
        finally:
            close = getattr(result, "close", None)
            if close is not None:
                close()
        if environ.get("REQUEST_METHOD") == "POST" and str(environ.get("PATH_INFO", "")).endswith("/execute"):
            time.sleep(self.seconds)
        status, headers, exc_info = captured[0]
        start_response(status, headers, exc_info)
        return [body]


def install() -> Any:
    """The WSGI app to serve, with the chosen fault in place; raises where it must not run."""
    global real_audit
    reason = refusal()
    if reason:
        raise RuntimeError(f"fault injection refused: {reason}")
    if os.environ["FAULT"].strip() == "kill_after_publish":
        real_audit = tools._audit
        setattr(tools, "_audit", _killed_at_the_record)
        return flask_app
    return SlowAfterExecute(flask_app, float(os.getenv("FAULT_SLOW_SECONDS", "30")))


app = install()
