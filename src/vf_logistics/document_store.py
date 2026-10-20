"""
Document archive on Cloud Storage.

The extracted record is what the agents reason over, but an audit needs the
original document, not a transcription of it. Every uploaded file is archived
and the case keeps the `gs://` URI, so any decision can be traced back to the
paperwork it was based on.

Degrades gracefully: if the bucket is missing or the service account cannot
write, ingestion still proceeds and the case records why the archive failed.
Losing the archive should not lose the shipment.

One bucket serves every tenant. Under MULTI_TENANT every object the service
writes, and every object it will ingest, lives under tenants/<tenant_id>/ --
otherwise two tenants archiving the same shipment id and filename on the same
day write one object, and a sweep has no way to tell whose file it is reading.
With multi-tenancy off the layout has no tenant segment, as it always had.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any

from vf_logistics import tenant
from vf_logistics.config import gcp_project

BUCKET = os.getenv("DOCUMENT_BUCKET", "").strip()

TENANTS_PREFIX = "tenants/"

# What the service writes into its own space. Never ingested as new intake:
# the archive would run back through the pipeline forever, and an evidence
# upload read as a shipment opens a case nobody submitted.
ARCHIVE_PREFIX = "shipping-documents/"
EVIDENCE_PREFIX = "evidence/"
SYSTEM_PREFIXES = (ARCHIVE_PREFIX, EVIDENCE_PREFIX)

_client = None
_client_error: str | None = None


def _get_client() -> Any:
    global _client, _client_error
    if _client is not None or _client_error is not None:
        return _client
    try:
        from google.cloud import storage

        # None is accepted: object reads and writes name the bucket and need no
        # project, so the archive still works where no project can be resolved.
        _client = storage.Client(project=gcp_project())
    except Exception as exc:  # noqa: BLE001
        _client_error = f"{type(exc).__name__}: {exc}"
    return _client


def tenant_root(tenant_id: str | None) -> str:
    """
    The object-name prefix a tenant's objects live under.

    Empty with multi-tenancy off. With it on, tenant.resolve() raises rather than
    returning a shared root when the tenant is absent or malformed, and a valid id
    has no "/" or "." in it, so the segment cannot be escaped.
    """
    if not tenant.multi_tenant_enabled():
        return ""
    return f"{TENANTS_PREFIX}{tenant.resolve(tenant_id)}/"


def ingest_refusal(bucket: str | None, name: str, tenant_id: str | None) -> str | None:
    """
    Why a staged object may not be ingested into this tenant's board, or None.

    Fails closed: under MULTI_TENANT an object is ingested only when its name puts
    it in the caller's own space in the document bucket. An object whose tenant
    cannot be established -- another bucket, a name outside tenants/ -- is refused
    rather than attributed to whoever asked.
    """
    if not name or name.endswith("/"):
        return "not a document object"
    # GCS names are literal, but tools that present them as paths resolve these,
    # so a name containing one has no unambiguous location to judge it by.
    if any(segment in (".", "..") for segment in name.split("/")):
        return "dot segment in object name"
    try:
        root = tenant_root(tenant_id)
    except tenant.TenantError:
        return "no tenant to ingest into"
    if root:
        if not BUCKET or bucket != BUCKET:
            return "not the document bucket"
        if not name.startswith(root):
            return "outside the caller's tenant"
    rest = name
    if rest.startswith(TENANTS_PREFIX):
        rest = rest[len(TENANTS_PREFIX):].partition("/")[2]
    if rest.startswith(SYSTEM_PREFIXES):
        return "own archive output"
    return None


async def archive(
    document_bytes: bytes, filename: str, mime_type: str, case_id: str,
    prefix: str = ARCHIVE_PREFIX.rstrip("/"), tenant_id: str | None = None,
) -> dict[str, Any]:
    """Upload the original document. Returns a receipt, never raises."""
    if not BUCKET:
        return {
            "archived": False,
            "reason": "DOCUMENT_BUCKET not configured",
        }

    try:
        root = tenant_root(tenant_id)
    except tenant.TenantError as exc:
        return {"archived": False, "reason": f"TenantError: {exc}"}

    client = _get_client()
    if client is None:
        return {"archived": False, "reason": _client_error or "storage client unavailable"}

    stamp = datetime.now(timezone.utc).strftime("%Y/%m/%d")
    safe_name = os.path.basename(filename or "document")
    # The case id comes from the shipment id a document states about itself, so
    # it is held to one segment like the filename.
    safe_case = case_id.replace("/", "_")
    blob_name = f"{root}{prefix}/{stamp}/{safe_case}/{safe_name}"

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
