"""
Cross-identity call from the analysis runtime to the executor runtime.

The analysis service account holds `aiplatform.user` and can read and write
Firestore, but it deliberately does **not** hold `pubsub.publisher`. So when the
workflow decides a decision should be published to the outside world, it cannot
do that itself. It has to ask the executor service, which runs under a different
service account that does hold that permission.

This is the part of the design that is not a promise. If the analysis runtime
were subverted - by a prompt injection in a document, or by a bug - and tried to
publish directly, Google IAM refuses it. The boundary is enforced by the platform
rather than by this codebase behaving well.

The call itself is authenticated with a Google-issued OIDC identity token, and
the executor service is deployed with `--no-allow-unauthenticated`, so it is not
reachable by anyone who has not been granted `run.invoker` on it.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

from vf_logistics import membership

# Set on the analysis service only. Empty means "no executor configured", in
# which case protected egress simply does not happen and says so.
EXECUTOR_URL = os.getenv("EXECUTOR_URL", "").strip().rstrip("/")

METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/"
    "service-accounts/default/identity"
)


def _fetch_id_token(audience: str) -> str | None:
    """
    Mint an OIDC identity token for the executor's audience.

    Uses the metadata server, which is only available on Cloud Run. Locally this
    returns None and the caller degrades to reporting that egress was skipped
    rather than crashing.
    """
    try:
        resp = httpx.get(
            METADATA_TOKEN_URL,
            params={"audience": audience, "format": "full"},
            headers={"Metadata-Flavor": "Google"},
            timeout=5,
        )
        if resp.status_code == 200 and resp.text.strip():
            return resp.text.strip()
    except Exception:  # noqa: BLE001
        pass

    # Fall back to the google-auth library, which also works with local ADC.
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import id_token

        token: str | None = id_token.fetch_id_token(Request(), audience)
        return token
    except Exception:  # noqa: BLE001
        return None


def configured() -> bool:
    return bool(EXECUTOR_URL)


async def request_protected_action(
    action: str, case_id: str, payload: dict[str, Any],
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """
    Ask the executor identity to perform an action this identity may not.

    Returns a receipt-shaped dict either way. A refusal or a transport failure is
    reported, never swallowed: an action that did not happen must not look like
    one that did.

    `tenant_id` selects the organisation the executor acts in, sent the way every
    other caller selects one: X-VF-Tenant, which the executor resolves against
    the service's OWN memberships and in which it then checks the operator role.
    It is repeated in the body, and the executor refuses the two disagreeing.

    Re-review finding R02: this used to travel in the body alone, and the
    executor honoured it after checking the role in whichever tenant the header
    had selected -- so a service that was an operator in one organisation could
    publish into another where it was only a viewer. And with no header at all, a
    service in two organisations was refused with "choose one" before anything ran.

    The executor also requires the shared API key alone (no console session).
    Two reasons the OIDC token by itself was not enough: the same app.py serves
    /internal/execute on the public analysis service as well as on the executor,
    so "unreachable by a customer" was not true of every deployment of this route;
    and IAM tells the executor that *a* permitted identity called, not which
    organisation it may act in.

    Without the tenant the executor writes its audit receipt with no owner, which
    under multi-tenancy raises rather than misfiling -- so the publish would
    succeed and the receipt recording it would not exist.
    """
    if not EXECUTOR_URL:
        return {
            "delegated": False,
            "status": "skipped",
            "reason": "EXECUTOR_URL not configured; no executor identity available",
        }

    token = await asyncio.to_thread(_fetch_id_token, EXECUTOR_URL)
    if not token:
        return {
            "delegated": False,
            "status": "failed",
            "reason": "could not mint an OIDC identity token for the executor",
        }

    headers = {"Authorization": f"Bearer {token}"}
    # Read per call, not captured at import, so a rotated key reaches the next
    # publish rather than the next deploy.
    shared_key = os.getenv("VF_API_KEY", "").strip()
    if shared_key:
        headers["X-VF-API-Key"] = shared_key
    if tenant_id:
        headers[membership.TENANT_HEADER] = tenant_id

    try:
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.post(
                f"{EXECUTOR_URL}/internal/execute",
                json={
                    "action": action,
                    "case_id": case_id,
                    "payload": payload,
                    "tenant_id": tenant_id,
                },
                headers=headers,
            )
    except Exception as exc:  # noqa: BLE001
        return {
            "delegated": True,
            "status": "failed",
            "reason": f"{type(exc).__name__}: {exc}",
        }

    if resp.status_code in (401, 403):
        return {
            "delegated": True,
            "status": "failed",
            "reason": (
                "executor refused the call: the analysis identity lacks "
                "run.invoker, or VF_API_KEY is unset or does not match the "
                "executor's"
            ),
            "http_status": resp.status_code,
        }

    try:
        body = resp.json()
    except ValueError:
        body = {"raw": resp.text[:400]}

    return {
        "delegated": True,
        "status": "done" if resp.is_success else "failed",
        "http_status": resp.status_code,
        **(body if isinstance(body, dict) else {"body": body}),
    }
