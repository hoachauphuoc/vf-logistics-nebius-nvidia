"""
Requests for documents, and the signed link a shipper answers them through.

Plan 1 of the 12/10 restructure proposal, step 2. A reviewer who cannot decide a case
from what is in front of them used to press "Request info" and write a sentence; the
case then sat in PENDING_HUMAN with nothing recording who was asked for what, or
whether it came. Here the request is a record of its own, inside the case:

    case["verification"] = {
        "evidence_version": 0,   # rises when new evidence arrives (step 3)
        "resume_state": None,    # where the case goes back to when no request is open
        "requests": [ {request_id, finding_codes, documents, owner, status, ...} ],
        "documents": [], "evaluations": [], "approvals": [], "executions": [],
    }

Embedded rather than stored apart so it shares the case's optimistic lock and its
tenant: a request and the state change it causes are one write, and cannot land
half-way. The cost is the 1 MiB Firestore document limit, so what is stored here is
metadata and extracted facts, never document bytes (those go to document_store).

THE LINK IS NOT IN THE CASE

The case JSON is readable by a viewer. A link stored in it would hand every viewer
the ability to submit "evidence" for that case, so the case keeps only a
fingerprint of each link issued and the link itself leaves exactly once, in the
response to the reviewer who asked. Lose it and the reviewer issues a new one,
which retires the old (the request's `link_seq` is in the token and compared on use).

THE CHANNEL IS A SANDBOX

Nothing is emailed. "sent" means a link was issued to a reviewer, who passes it on;
the request records that and no more. The console says so wherever it shows the
status, because a status that read "sent" with no sending would be the AI-written
claim the proposal asked this loop not to make.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import time
from typing import Any

from vf_logistics import auth, dossier, tenant
from vf_logistics.store import OptimisticLockError, get_store, new_id, utcnow

AWAITING_EVIDENCE = "AWAITING_EVIDENCE"

# States a reviewer can ask for documents from: the ones that wait on a person, and
# AWAITING_EVIDENCE itself so a second request can be added to an open one.
REQUESTABLE_STATES = ("PENDING_HUMAN", "HELD_FOR_REVIEW", "ESCALATED", AWAITING_EVIDENCE)

OPEN_STATUSES = ("OPEN", "SENT")
LINK_TTL_S = 7 * 24 * 3600
MAX_TOKEN_CHARS = 1024
MAX_FIELD_CHARS = 200
MAX_NOTE_CHARS = 1000
MAX_FINDING_CODES = 20

# Domain separation: the key that signs these links is derived from the console
# session secret but is not it, so a console session token can never be replayed as
# an evidence link, nor a link as a session.
_KEY_CONTEXT = b"evidence-response\x00"


class EvidenceError(Exception):
    """A refusal with the HTTP status the route should answer with."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


# --------------------------------------------------------------------------
# The record
# --------------------------------------------------------------------------

def empty_verification() -> dict[str, Any]:
    return {
        "evidence_version": 0,
        "resume_state": None,
        "requests": [],
        "documents": [],
        "evaluations": [],
        "approvals": [],
        "executions": [],
    }


def verification_of(case: dict[str, Any]) -> dict[str, Any]:
    """The case's verification record, created in place if the case predates it."""
    record = case.get("verification")
    if not isinstance(record, dict):
        record = empty_verification()
        case["verification"] = record
    for key, value in empty_verification().items():
        record.setdefault(key, value)
    return record


def open_requests(case: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        r for r in verification_of(case)["requests"]
        if isinstance(r, dict) and r.get("status") in OPEN_STATUSES
    ]


def find_request(case: dict[str, Any], request_id: str) -> dict[str, Any] | None:
    for r in verification_of(case)["requests"]:
        if isinstance(r, dict) and r.get("request_id") == request_id:
            return r
    return None


# --------------------------------------------------------------------------
# The link
# --------------------------------------------------------------------------

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _key() -> bytes:
    secret = auth.console_session_secret()
    if secret is None:
        raise EvidenceError(
            "This service has no VF_SESSION_SECRET (or one under 32 characters), so it "
            "cannot sign a link for a shipper to answer through.",
            503,
        )
    return hmac.new(secret.encode("utf-8"), _KEY_CONTEXT, hashlib.sha256).digest()


def mint_token(scope: str, case_id: str, request_id: str, seq: int, now: float | None = None) -> tuple[str, int]:
    """A signed link token and its expiry (epoch seconds)."""
    expires = int((time.time() if now is None else now) + LINK_TTL_S)
    payload = json.dumps(
        {"v": 1, "t": scope, "c": case_id, "r": request_id, "s": seq, "e": expires},
        separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    body = _b64(payload)
    signature = _b64(hmac.new(_key(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{signature}", expires


def read_token(token: Any, now: float | None = None) -> dict[str, Any] | None:
    """
    The claims of a valid, unexpired token, else None.

    One answer for every failure -- malformed, forged, expired, wrong version -- so
    the route cannot be used to learn which of them it was.
    """
    if not isinstance(token, str) or not token or len(token) > MAX_TOKEN_CHARS:
        return None
    body, dot, signature = token.partition(".")
    if not dot or not body or not signature or "." in signature:
        return None
    try:
        expected = hmac.new(_key(), body.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_unb64(signature), expected):
            return None
        claims = json.loads(_unb64(body))
    except EvidenceError:
        return None
    except Exception:
        return None
    if not isinstance(claims, dict) or claims.get("v") != 1:
        return None
    expires = claims.get("e")
    if not isinstance(expires, int) or isinstance(expires, bool):
        return None
    if (time.time() if now is None else now) >= expires:
        return None
    for field in ("t", "c", "r"):
        if not isinstance(claims.get(field), str) or not claims[field]:
            return None
    if not isinstance(claims.get("s"), int) or isinstance(claims.get("s"), bool):
        return None
    return claims


def link_path(token: str) -> str:
    """Where the shipper opens it. The console turns this into an absolute address."""
    return f"/respond/{token}"


def _issue(
    request: dict[str, Any], scope: str, case_id: str, issued_by: str, now: str,
) -> tuple[str, int]:
    """Mint a new link for `request`, retiring the previous one. Mutates `request`."""
    request["link_seq"] = int(request.get("link_seq") or 0) + 1
    token, expires = mint_token(scope, case_id, request["request_id"], request["link_seq"])
    expires_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(expires))
    request["status"] = "SENT"
    request.setdefault("sent_at", now)
    request["link_expires_at"] = expires_at
    request.setdefault("outbox", []).append({
        "channel": "sandbox_link",
        "seq": request["link_seq"],
        "issued_at": now,
        "issued_by": issued_by,
        "expires_at": expires_at,
        # Enough to say which link was which, not enough to use one.
        "token_fingerprint": hashlib.sha256(token.encode("ascii")).hexdigest()[:12],
    })
    return token, expires


# --------------------------------------------------------------------------
# Operations
# --------------------------------------------------------------------------

def _clean_text(value: Any, limit: int, what: str, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise EvidenceError(f"{what} must be text")
    text = value.strip()
    if required and not text:
        raise EvidenceError(f"{what} is required")
    if len(text) > limit:
        raise EvidenceError(f"{what} must be {limit} characters or fewer")
    return text


def _string_list(value: Any, what: str, limit: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise EvidenceError(f"{what} must be a list of names")
    if len(value) > limit:
        raise EvidenceError(f"{what} may name at most {limit}")
    seen: list[str] = []
    for item in value:
        if item not in seen:
            seen.append(item)
    return seen


def _documents_each_finding_asks_for(case: dict[str, Any]) -> dict[str, list[str]]:
    """finding code -> the document types the verifier says would answer it."""
    out: dict[str, list[str]] = {}
    for finding in (case.get("validation") or {}).get("findings") or []:
        needed = (finding.get("measured") or {}).get("documents_needed")
        if isinstance(needed, list) and needed:
            out[str(finding.get("code"))] = [str(d) for d in needed]
    return out


def _received_types(case: dict[str, Any]) -> set[str]:
    return {
        str(d.get("doc_type")) for d in verification_of(case)["documents"] if isinstance(d, dict)
    }


async def _write(
    case: dict[str, Any], expected_version: Any, tenant_id: str | None,
) -> None:
    try:
        await get_store().put_case(case, expected_version=expected_version, tenant_id=tenant_id)
    except OptimisticLockError:
        raise EvidenceError(
            "The case changed while this was being done. Reload it and try again.", 409,
        ) from None


async def _audit(
    case_id: str, action: str, actor: str, actor_auth: str | None,
    detail: dict[str, Any], tenant_id: str | None,
) -> None:
    await get_store().add_audit({
        "audit_id": new_id("audit"),
        "case_id": case_id,
        "action": action,
        "status": "done",
        "actor": actor,
        "actor_auth": actor_auth,
        "detail": detail,
        "at": utcnow(),
    }, tenant_id=tenant_id)


def public_request(request: dict[str, Any]) -> dict[str, Any]:
    """A request as the console shows it. No token is ever in a stored request."""
    return {k: v for k, v in request.items() if k != "token"}


async def request_evidence(
    case_id: str,
    requested_by: str,
    *,
    finding_codes: Any = None,
    documents: Any = None,
    owner: Any = None,
    note: Any = None,
    actor_auth: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """
    Ask the shipper for documents on one or more findings of a case.

    Returns {"request", "token", "path", "state"}. The token is in the return value
    and nowhere else: the caller passes it to the reviewer once.
    """
    if not requested_by:
        raise EvidenceError("A request for documents is made by a named person")
    codes = _string_list(finding_codes, "finding_codes", MAX_FINDING_CODES)
    wanted = _string_list(documents, "documents", len(dossier.EVIDENCE_CATALOGUE))
    owner_name = _clean_text(owner, MAX_FIELD_CHARS, "owner") or requested_by
    note_text = _clean_text(note, MAX_NOTE_CHARS, "note")
    for doc in wanted:
        if doc not in dossier.EVIDENCE_CATALOGUE:
            raise EvidenceError(f"'{doc}' is not a document this service can ask for")

    store = get_store()
    stored = await store.get_case(case_id, tenant_id=tenant_id)
    if not stored:
        raise EvidenceError("case not found", 404)
    expected_version = stored.get("_version")
    case = copy.deepcopy(stored)

    state = case.get("state")
    if state not in REQUESTABLE_STATES:
        raise EvidenceError(f"A case in state {state} is not waiting on a person, so documents cannot be requested.", 409)

    asked = _documents_each_finding_asks_for(case)
    if not codes:
        codes = list(asked)
    if not codes:
        raise EvidenceError("No finding on this case asks for documents. Name the finding the request is for.")
    unknown = [c for c in codes if c not in asked]
    if unknown:
        raise EvidenceError(
            f"{', '.join(unknown)} is not a finding on this case that asks for documents."
        )

    record = verification_of(case)
    received = _received_types(case)
    if not wanted:
        # The minimum: what the chosen findings need, less what is already in hand.
        for code in codes:
            for doc in asked[code]:
                if doc not in wanted and doc not in received:
                    wanted.append(doc)
    if not wanted:
        raise EvidenceError("Everything those findings need has already been received.", 409)

    for existing in open_requests(case):
        if sorted(existing["documents"]) == sorted(wanted) and set(existing["finding_codes"]) == set(codes):
            raise EvidenceError(
                f"Those documents are already requested ({existing['request_id']}). "
                "Issue a new link on that request instead.",
                409,
            )

    now = utcnow()
    scope = tenant.resolve(tenant_id)
    request = {
        "request_id": new_id("evreq"),
        "finding_codes": codes,
        "documents": wanted,
        "owner": owner_name,
        "note": note_text,
        "status": "OPEN",
        "channel": "sandbox_link",
        "created_by": requested_by,
        "created_at": now,
        "sent_at": None,
        "received_at": None,
        "reconciled_at": None,
        "closed_at": None,
    }
    token, _ = _issue(request, scope, case_id, requested_by, now)
    record["requests"].append(request)

    if state != AWAITING_EVIDENCE:
        record["resume_state"] = state
    case["state"] = AWAITING_EVIDENCE
    case["updated_at"] = now
    case["claimed"] = False
    # Counted with the other requests for information, so Outcomes' "rounds" and the
    # worklist's "waiting since" read one history rather than two.
    labels = ", ".join(dossier.evidence_label(d) for d in wanted)
    case.setdefault("reviews", []).append({
        "action": "request_info",
        "reviewer": requested_by,
        "note": note_text or f"Requested: {labels}",
        "at": now,
        "state_before": state,
        "state_after": AWAITING_EVIDENCE,
        "request_id": request["request_id"],
    })

    await _write(case, expected_version, tenant_id)
    await _audit(case_id, "evidence_requested", requested_by, actor_auth, {
        "request_id": request["request_id"], "finding_codes": codes, "documents": wanted,
        "owner": owner_name, "channel": "sandbox_link",
    }, tenant_id)
    return {
        "request": public_request(request),
        "token": token,
        "path": link_path(token),
        "state": AWAITING_EVIDENCE,
    }


async def reissue_link(
    case_id: str,
    request_id: str,
    issued_by: str,
    *,
    actor_auth: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """A new link for an open request. The old one stops working."""
    store = get_store()
    stored = await store.get_case(case_id, tenant_id=tenant_id)
    if not stored:
        raise EvidenceError("case not found", 404)
    expected_version = stored.get("_version")
    case = copy.deepcopy(stored)
    request = find_request(case, request_id)
    if request is None:
        raise EvidenceError("request not found", 404)
    if request.get("status") not in OPEN_STATUSES:
        raise EvidenceError(f"That request is {str(request.get('status')).lower()}; no link can be issued for it.", 409)

    now = utcnow()
    token, _ = _issue(request, tenant.resolve(tenant_id), case_id, issued_by, now)
    case["updated_at"] = now
    await _write(case, expected_version, tenant_id)
    await _audit(case_id, "evidence_link_issued", issued_by, actor_auth, {
        "request_id": request_id, "seq": request["link_seq"],
    }, tenant_id)
    return {"request": public_request(request), "token": token, "path": link_path(token)}


async def cancel_request(
    case_id: str,
    request_id: str,
    cancelled_by: str,
    reason: Any,
    *,
    actor_auth: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """
    Withdraw an open request, with a reason.

    Without this a shipper who never answers leaves the case in AWAITING_EVIDENCE for
    good: the decision routes refuse a case in that state. When the last open request
    closes, the case goes back to the state it was in before the first was made.
    """
    why = _clean_text(reason, MAX_NOTE_CHARS, "reason", required=True)
    store = get_store()
    stored = await store.get_case(case_id, tenant_id=tenant_id)
    if not stored:
        raise EvidenceError("case not found", 404)
    expected_version = stored.get("_version")
    case = copy.deepcopy(stored)
    request = find_request(case, request_id)
    if request is None:
        raise EvidenceError("request not found", 404)
    if request.get("status") not in OPEN_STATUSES:
        raise EvidenceError(f"That request is already {str(request.get('status')).lower()}.", 409)

    now = utcnow()
    request["status"] = "CANCELLED"
    request["closed_at"] = now
    request["cancel_reason"] = why
    request["cancelled_by"] = cancelled_by
    record = verification_of(case)
    if case.get("state") == AWAITING_EVIDENCE and not open_requests(case):
        case["state"] = record.get("resume_state") or "HELD_FOR_REVIEW"
        record["resume_state"] = None
    case["updated_at"] = now

    await _write(case, expected_version, tenant_id)
    await _audit(case_id, "evidence_request_cancelled", cancelled_by, actor_auth, {
        "request_id": request_id, "reason": why, "state_after": case["state"],
    }, tenant_id)
    return {"request": public_request(request), "state": case["state"]}


# --------------------------------------------------------------------------
# Receiving evidence (step 3)
# --------------------------------------------------------------------------

MAX_EVIDENCE_MB = 20
SUPPORTED_EVIDENCE_MIME = frozenset({
    "application/pdf", "image/png", "image/jpeg", "image/webp",
})


def _supersede_approvals(record: dict[str, Any], new_version: int, now: str) -> list[str]:
    """
    Any VALID approval with an evidence_version lower than `new_version` is stale:
    the person approved on facts that are no longer current. Returns the ids that
    were superseded.
    """
    hit: list[str] = []
    for approval in record.get("approvals") or []:
        if isinstance(approval, dict) and approval.get("status") == "VALID":
            if (approval.get("evidence_version") or 0) < new_version:
                approval["status"] = "SUPERSEDED"
                approval["superseded_at"] = now
                approval["superseded_reason"] = f"evidence v{new_version} received"
                hit.append(str(approval.get("approval_id") or ""))
    return hit


async def receive_evidence(
    token: str,
    file_bytes: bytes,
    filename: str,
    mime_type: str,
    *,
    client_ip: str | None = None,
) -> dict[str, Any]:
    """
    Accept a document submitted through a signed link.

    This is the one public route in the loop. It has no session and no API key:
    the token IS the credential, and it is single-purpose (one case, one request,
    one sequence). Everything else is checked before any work happens.
    """
    if not isinstance(file_bytes, (bytes, bytearray)) or not file_bytes:
        raise EvidenceError("No file was submitted")
    if len(file_bytes) > MAX_EVIDENCE_MB * 1024 * 1024:
        raise EvidenceError(f"The file must be {MAX_EVIDENCE_MB} MB or smaller", 413)
    if mime_type not in SUPPORTED_EVIDENCE_MIME:
        raise EvidenceError(
            f"Only {', '.join(sorted(SUPPORTED_EVIDENCE_MIME))} are accepted", 415,
        )

    claims = read_token(token)
    if claims is None:
        raise EvidenceError("The link is invalid, expired, or has been replaced", 403)

    scope = claims["t"]
    case_id = claims["c"]
    request_id = claims["r"]
    token_seq = claims["s"]

    store = get_store()
    stored = await store.get_case(case_id, tenant_id=scope)
    if stored is None:
        raise EvidenceError("The link is invalid, expired, or has been replaced", 403)
    expected_version = stored.get("_version")
    case = copy.deepcopy(stored)

    request = find_request(case, request_id)
    if request is None or request.get("status") not in OPEN_STATUSES:
        raise EvidenceError("The link is invalid, expired, or has been replaced", 403)
    if request.get("link_seq") != token_seq:
        raise EvidenceError("The link is invalid, expired, or has been replaced", 403)

    record = verification_of(case)
    now = utcnow()

    # -- Model Armor screen (deterministic pre-screen + Google Model Armor) --
    from vf_logistics import model_armor

    text_layer = ""
    if mime_type == "application/pdf":
        text_layer, _ = model_armor.extract_pdf_text(file_bytes)
    armor_result = await model_armor.screen(text_layer or filename, stage="evidence_response")
    blocked = armor_result.get("blocked", False)

    # -- Archive the file --
    from vf_logistics import document_store

    archive = await document_store.archive(
        file_bytes, filename, mime_type, case_id,
        prefix=f"evidence/{request_id}",
    )

    # -- Extract facts --
    doc_type = request["documents"][0] if request.get("documents") else "unknown"
    extraction: dict[str, Any] | None = None
    extraction_cost = 0.0
    if not blocked:
        from vf_logistics.agents import document_agent
        from vf_logistics import lineage

        extraction = await document_agent.extract_evidence(doc_type, file_bytes, filename, mime_type)
        extraction_cost = lineage.cost_usd(
            extraction.get("model"),
            extraction.get("input_tokens", 0),
            extraction.get("output_tokens", 0),
        )

    # -- Write the document record --
    new_version = (record.get("evidence_version") or 0) + 1
    record["evidence_version"] = new_version
    doc_record: dict[str, Any] = {
        "document_id": new_id("evdoc"),
        "request_id": request_id,
        "evidence_version": new_version,
        "doc_type": doc_type,
        "filename": filename,
        "sha256": hashlib.sha256(file_bytes).hexdigest(),
        "uri": archive.get("uri"),
        "content_type": mime_type,
        "received_at": now,
        "blocked": blocked,
        "extracted": extraction.get("result") if extraction and not extraction.get("parse_error") else None,
        "extraction": {
            "model": extraction.get("model") if extraction else None,
            "cost_usd": extraction_cost,
            "parse_error": extraction.get("parse_error") if extraction else None,
        },
    }
    record["documents"].append(doc_record)

    # -- Update the request --
    request["status"] = "RECEIVED"
    request["received_at"] = now

    # -- Cost rollup --
    case["_estimated_cost_usd"] = (case.get("_estimated_cost_usd") or 0.0) + extraction_cost
    case["_sum_latency_ms"] = (case.get("_sum_latency_ms") or 0) + (extraction.get("latency_ms") or 0 if extraction else 0)

    # -- Supersede approvals --
    superseded = _supersede_approvals(record, new_version, now)

    case["updated_at"] = now

    await _write(case, expected_version, scope)
    await _audit(case_id, "evidence_received", "shipper (via link)", None, {
        "document_id": doc_record["document_id"],
        "request_id": request_id,
        "evidence_version": new_version,
        "sha256": doc_record["sha256"],
        "blocked": blocked,
        "superseded_approvals": superseded,
        "source_ip": client_ip,
    }, scope)

    return {
        "received": True,
        "document_id": doc_record["document_id"],
        "evidence_version": new_version,
        "blocked": blocked,
        "extracted": doc_record["extracted"] is not None,
        "superseded_approvals": len(superseded),
    }
