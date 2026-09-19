"""
Model Armor gate.

Google Cloud Model Armor screens text for prompt injection and jailbreak attempts.
It sits in front of the document intake path, where untrusted paperwork would
otherwise reach a model whose output moves physical cargo.

Ordering matters, and it is the reason this module extracts text without a model.
The control plane requires that a blocked document produce **no model processing
at all** - not "the model looked at it and we discarded the answer". For a PDF
that is achievable: pypdf pulls the text layer deterministically, Model Armor
screens that, and Gemini is only invoked if the document passes.

Scanned images have no text layer, so no pre-screen is possible without OCR. For
those the order is necessarily reversed: Gemini transcribes, and the transcription
is screened before it reaches any downstream agent. That is a weaker guarantee and
is reported as such on the case rather than glossed over.

Fails closed on the security decision but open on availability: if Model Armor
cannot be reached, the document is not silently trusted - the case is flagged for
human review and the reason is recorded.
"""

from __future__ import annotations

import asyncio
import io
import os
from typing import Any

import httpx

PROJECT_ID = os.getenv("PROJECT_ID", "project-93ded24f-21c3-4f1b-a7d")
LOCATION = os.getenv("MODEL_ARMOR_LOCATION", "asia-southeast1")
TEMPLATE = os.getenv("MODEL_ARMOR_TEMPLATE", "vf-document-intake").strip()

# Model Armor is served from regional endpoints with this distinct host form.
ENDPOINT = f"https://modelarmor.{LOCATION}.rep.googleapis.com/v1"

# Model Armor caps request size; documents are truncated for screening only. The
# full text still goes to extraction if the screen passes.
MAX_SCREEN_CHARS = int(os.getenv("MODEL_ARMOR_MAX_CHARS", "20000"))

# Windowed screening parameters. See _windows() for why this is necessary.
WINDOW_CHARS = int(os.getenv("MODEL_ARMOR_WINDOW_CHARS", "400"))
WINDOW_OVERLAP = int(os.getenv("MODEL_ARMOR_WINDOW_OVERLAP", "120"))
MAX_WINDOWS = int(os.getenv("MODEL_ARMOR_MAX_WINDOWS", "8"))


def configured() -> bool:
    return bool(TEMPLATE)


def _access_token() -> str | None:
    try:
        import google.auth
        import google.auth.transport.requests

        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        creds.refresh(google.auth.transport.requests.Request())
        return creds.token
    except Exception:  # noqa: BLE001
        return None


def extract_pdf_text(document_bytes: bytes) -> tuple[str, str | None]:
    """
    Pull the text layer out of a PDF with no model involved.

    Returns (text, error). Empty text with no error means a PDF with no text
    layer - a scan - which the caller must handle differently.
    """
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(document_bytes))
        chunks = []
        for page in reader.pages[:30]:
            try:
                chunks.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001 - one bad page must not lose the rest
                continue
        return "\n".join(chunks).strip(), None
    except Exception as exc:  # noqa: BLE001
        return "", f"{type(exc).__name__}: {exc}"


async def _sanitize_once(text: str, token: str) -> dict[str, Any]:
    """One sanitizeUserPrompt call. Returns the parsed filter outcome."""
    url = (
        f"{ENDPOINT}/projects/{PROJECT_ID}/locations/{LOCATION}"
        f"/templates/{TEMPLATE}:sanitizeUserPrompt"
    )
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json={"userPromptData": {"text": text[:MAX_SCREEN_CHARS]}},
        )

    if not resp.is_success:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}

    result = (resp.json() or {}).get("sanitizationResult") or {}
    pi = (
        (result.get("filterResults") or {})
        .get("pi_and_jailbreak", {})
        .get("piAndJailbreakFilterResult", {})
    )
    return {
        "match_state": result.get("filterMatchState"),
        "confidence": pi.get("confidenceLevel"),
        "filter_match": pi.get("matchState"),
    }


def _windows(text: str) -> list[str]:
    """
    Split into overlapping windows.

    Measured behaviour, not a precaution: the prompt-injection filter returned
    NO_MATCH_FOUND on a 1,150-character bill of lading containing an injection
    that it flagged at MEDIUM_AND_ABOVE when the same 275 characters were sent on
    their own. The signal is diluted by surrounding legitimate document text, so
    the document is screened in pieces as well as whole. Windows overlap so a
    payload straddling a boundary is not split in half.
    """
    if len(text) <= WINDOW_CHARS:
        return [text]

    windows = [text]  # the whole thing first, cheapest path to a match
    step = WINDOW_CHARS - WINDOW_OVERLAP
    for start in range(0, len(text), step):
        chunk = text[start: start + WINDOW_CHARS]
        if chunk.strip():
            windows.append(chunk)
        if len(windows) >= MAX_WINDOWS + 1:
            break
    return windows


async def screen(text: str, stage: str) -> dict[str, Any]:
    """
    Ask Model Armor whether this text is trying to manipulate a model.

    `stage` records where in the pipeline the screen happened, because
    "screened before the model ran" and "screened after transcription" are
    materially different assurances and the case should say which it got.
    """
    verdict: dict[str, Any] = {
        "provider": "google-cloud-model-armor",
        "stage": stage,
        "template": TEMPLATE,
        "location": LOCATION,
        "blocked": False,
        "available": False,
        "match_state": None,
        "confidence": None,
        "detail": None,
        "windows_screened": 0,
    }

    if not TEMPLATE:
        verdict["detail"] = "MODEL_ARMOR_TEMPLATE not configured"
        return verdict

    if not text or not text.strip():
        verdict["available"] = True
        verdict["detail"] = "no text to screen"
        return verdict

    token = await asyncio.to_thread(_access_token)
    if not token:
        verdict["detail"] = "could not obtain credentials for Model Armor"
        verdict["requires_human"] = True
        return verdict

    windows = _windows(text)
    errors: list[str] = []

    for index, window in enumerate(windows):
        try:
            outcome = await _sanitize_once(window, token)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{type(exc).__name__}: {exc}")
            continue

        verdict["windows_screened"] = index + 1

        if outcome.get("error"):
            errors.append(outcome["error"])
            continue

        verdict["available"] = True

        if outcome.get("match_state") == "MATCH_FOUND":
            verdict["blocked"] = True
            verdict["match_state"] = "MATCH_FOUND"
            verdict["confidence"] = outcome.get("confidence")
            verdict["detail"] = (
                f"prompt injection matched at {outcome.get('confidence')} "
                # windows[0] is the whole document and windows[1:] are the
                # sliding passes, so this index and `windows_screened` count
                # different things: one names which sliding window matched, the
                # other how many calls were made in total. Both are stated, in
                # those terms, because reporting "window 3 of 5" next to
                # "windows_screened: 4" reads like an off-by-one bug.
                + ("on the whole document" if index == 0
                   else f"in sliding window {index} of {len(windows) - 1}")
                + f" ({index + 1} pass(es) screened)"
            )
            return verdict

    if not verdict["available"]:
        verdict["detail"] = "; ".join(errors[:3]) or "no successful screen"
        verdict["requires_human"] = True
        return verdict

    verdict["match_state"] = "NO_MATCH_FOUND"
    verdict["detail"] = (
        f"no prompt injection detected across {verdict['windows_screened']} "
        f"window(s)"
        + (f"; {len(errors)} window(s) errored" if errors else "")
    )
    return verdict


def status() -> dict[str, Any]:
    return {
        "configured": configured(),
        "template": TEMPLATE or None,
        "location": LOCATION,
        "gate_position": (
            "before model processing for PDFs with a text layer; "
            "after transcription for scans"
        ),
    }
