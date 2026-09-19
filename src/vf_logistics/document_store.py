"""
Document archive on Cloud Storage.

The extracted record is what the agents reason over, but an audit needs the
original document, not a transcription of it. Every uploaded file is archived
and the case keeps the `gs://` URI, so any decision can be traced back to the
paperwork it was based on.

Degrades gracefully: if the bucket is missing or the service account cannot
write, ingestion still proceeds and the case records why the archive failed.
Losing the archive should not lose the shipment.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any

PROJECT_ID = os.getenv("PROJECT_ID", "project-93ded24f-21c3-4f1b-a7d")
BUCKET = os.getenv("DOCUMENT_BUCKET", "").strip()

_client = None
_client_error: str | None = None


def _get_client():
    global _client, _client_error
    if _client is not None or _client_error is not None:
        return _client
    try:
        from google.cloud import storage

        _client = storage.Client(project=PROJECT_ID)
    except Exception as exc:  # noqa: BLE001
        _client_error = f"{type(exc).__name__}: {exc}"
    return _client


async def archive(
    document_bytes: bytes, filename: str, mime_type: str, case_id: str
) -> dict[str, Any]:
    """Upload the original document. Returns a receipt, never raises."""
    if not BUCKET:
        return {
            "archived": False,
            "reason": "DOCUMENT_BUCKET not configured",
        }

    client = _get_client()
    if client is None:
        return {"archived": False, "reason": _client_error or "storage client unavailable"}

    stamp = datetime.now(timezone.utc).strftime("%Y/%m/%d")
    safe_name = os.path.basename(filename or "document")
    blob_name = f"shipping-documents/{stamp}/{case_id}/{safe_name}"

    def _upload() -> None:
        bucket = client.bucket(BUCKET)
        blob = bucket.blob(blob_name)
        blob.upload_from_string(document_bytes, content_type=mime_type)

    try:
        await asyncio.to_thread(_upload)
        return {
            "archived": True,
            "uri": f"gs://{BUCKET}/{blob_name}",
            "bytes": len(document_bytes),
            "content_type": mime_type,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "archived": False,
            "reason": f"{type(exc).__name__}: {exc}",
            "intended_uri": f"gs://{BUCKET}/{blob_name}",
        }


async def fetch(uri: str) -> tuple[bytes | None, str | None]:
    """
    Read an archived document back by gs:// URI.

    Used by the review endpoint so a human sees the original paperwork rather
    than trusting the transcription of it. Returns (None, None) on any failure;
    the caller turns that into a 502 rather than a stack trace.
    """
    if not uri.startswith("gs://"):
        return None, None

    client = _get_client()
    if client is None:
        return None, None

    path = uri[len("gs://"):]
    bucket_name, _, blob_name = path.partition("/")
    if not blob_name:
        return None, None

    def _download() -> tuple[bytes, str | None]:
        blob = client.bucket(bucket_name).blob(blob_name)
        data = blob.download_as_bytes()
        return data, blob.content_type

    try:
        return await asyncio.to_thread(_download)
    except Exception:  # noqa: BLE001
        return None, None


async def list_objects(prefix: str, limit: int = 50) -> list[str]:
    """List object names under a prefix. Empty list on any failure."""
    if not BUCKET:
        return []

    client = _get_client()
    if client is None:
        return []

    def _list() -> list[str]:
        blobs = client.list_blobs(BUCKET, prefix=prefix, max_results=limit)
        return [b.name for b in blobs]

    try:
        return await asyncio.to_thread(_list)
    except Exception:  # noqa: BLE001
        return []


def status() -> dict[str, Any]:
    return {
        "bucket": BUCKET or None,
        "configured": bool(BUCKET),
        "client_error": _client_error,
    }
