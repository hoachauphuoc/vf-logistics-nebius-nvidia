"""
The document archive (document_store.py) against an in-memory Cloud Storage.

The archive is what a reviewer opens to see the paperwork rather than the
model's transcription of it, and what an auditor is pointed at years later. Two
properties matter, and neither is "the mock came back":

  * the receipt archive() writes onto the case is one fetch() can read back --
    the URI is the only link between a decision and its original document;
  * every failure is a receipt or an empty answer, never an exception, because
    intake must not lose the shipment when it loses the archive.

The fake replaces google.cloud.storage.Client, which is where this module meets
the network; everything above it is the real code.

Class names use the `Test*` prefix: see test_console_session.py for why.
"""

from __future__ import annotations

import asyncio
import re
import sys
import types
import unittest
from unittest.mock import patch

from vf_logistics import document_store

BUCKET = "vf-archive-test"


class Forbidden(Exception):
    """Stands in for google.api_core.exceptions.Forbidden (a 403 from GCS)."""


class NotFound(Exception):
    """Stands in for google.api_core.exceptions.NotFound."""


class FakeGcs:
    """
    The slice of storage.Client the module uses, over a dict of objects.

    Content type is recorded on upload and populated on download, as the real
    Blob does from the response headers.
    """

    def __init__(self):
        self.objects: dict[tuple[str, str], tuple[bytes, str | None]] = {}
        self.fail: Exception | None = None
        self.calls = 0

    def bucket(self, name):
        self.calls += 1
        return _FakeBucket(self, name)

    def list_blobs(self, bucket, prefix=None, max_results=None):
        self.calls += 1
        if self.fail:
            raise self.fail
        names = sorted(n for b, n in self.objects if b == bucket and n.startswith(prefix or ""))
        return [types.SimpleNamespace(name=n) for n in names[:max_results]]


class _FakeBucket:
    def __init__(self, gcs, name):
        self.gcs, self.name = gcs, name

    def blob(self, name):
        return _FakeBlob(self, name)


class _FakeBlob:
    def __init__(self, bucket, name):
        self.bucket, self.name = bucket, name
        self.content_type = None

    def upload_from_string(self, data, content_type=None):
        if self.bucket.gcs.fail:
            raise self.bucket.gcs.fail
        self.bucket.gcs.objects[(self.bucket.name, self.name)] = (bytes(data), content_type)

    def download_as_bytes(self):
        if self.bucket.gcs.fail:
            raise self.bucket.gcs.fail
        try:
            data, self.content_type = self.bucket.gcs.objects[(self.bucket.name, self.name)]
        except KeyError:
            raise NotFound(f"{self.bucket.name}/{self.name}") from None
        return data


def _run(coro):
    return asyncio.run(coro)


class _ArchiveCase(unittest.TestCase):
    """A fresh module client per test: _get_client() caches success and failure alike."""

    BUCKET_NAME = BUCKET

    def setUp(self):
        saved = (document_store._client, document_store._client_error)
        self.addCleanup(setattr, document_store, "_client", saved[0])
        self.addCleanup(setattr, document_store, "_client_error", saved[1])
        document_store._client = None
        document_store._client_error = None

        self.gcs = FakeGcs()
        self.client_factory_calls = 0

        def client(project=None):
            self.client_factory_calls += 1
            return self.gcs

        cloud = types.ModuleType("google.cloud")
        storage = types.ModuleType("google.cloud.storage")
        storage.Client = client  # type: ignore[attr-defined]
        cloud.storage = storage  # type: ignore[attr-defined]
        modules = patch.dict(sys.modules, {"google.cloud": cloud, "google.cloud.storage": storage})
        modules.start()
        self.addCleanup(modules.stop)

        bucket = patch.object(document_store, "BUCKET", self.BUCKET_NAME)
        bucket.start()
        self.addCleanup(bucket.stop)

    def archive(self, data=b"%PDF-1.7 bill", filename="BL-001.pdf", mime="application/pdf",
                case_id="CASE-SHP-1", **kwargs):
        return _run(document_store.archive(data, filename, mime, case_id, **kwargs))


class TestArchiveRoundTrip(_ArchiveCase):
    def test_the_receipt_uri_reads_back_the_original(self):
        receipt = self.archive(data=b"%PDF original bytes", mime="image/png")

        self.assertTrue(receipt["archived"])
        self.assertEqual(receipt["bytes"], len(b"%PDF original bytes"))
        self.assertEqual(receipt["content_type"], "image/png")
        data, content_type = _run(document_store.fetch(receipt["uri"]))
        self.assertEqual(data, b"%PDF original bytes")
        self.assertEqual(content_type, "image/png")

    def test_objects_are_filed_by_prefix_date_and_case(self):
        receipt = self.archive(case_id="CASE-SHP-9", filename="invoice.pdf")
        self.assertRegex(
            receipt["uri"],
            rf"^gs://{BUCKET}/shipping-documents/\d{{4}}/\d{{2}}/\d{{2}}/CASE-SHP-9/invoice\.pdf$",
        )

    def test_evidence_goes_under_its_own_prefix(self):
        """
        Evidence responses are archived under evidence/<request>, outside the
        intake archive the bucket sweep skips (orchestrator.ARCHIVE_PREFIX).
        """
        receipt = self.archive(prefix="evidence/REQ-7")
        self.assertTrue(receipt["uri"].startswith(f"gs://{BUCKET}/evidence/REQ-7/"))

    def test_a_filename_cannot_climb_out_of_its_case_folder(self):
        """
        The filename is the uploader's. Only its last component is kept, so a
        name with directories in it cannot land the object in another case's
        folder -- or overwrite that case's original.
        """
        self.archive(data=b"victim", case_id="CASE-OTHER", filename="BL.pdf")
        receipt = self.archive(
            data=b"attacker", case_id="CASE-MINE",
            filename="../../../CASE-OTHER/BL.pdf",
        )

        object_name = receipt["uri"].split(f"gs://{BUCKET}/", 1)[1]
        self.assertTrue(re.search(r"/CASE-MINE/BL\.pdf$", object_name), object_name)
        self.assertNotIn("..", object_name)
        stored = {data for data, _ in self.gcs.objects.values()}
        self.assertEqual(stored, {b"victim", b"attacker"})

    def test_a_missing_filename_still_archives(self):
        receipt = self.archive(filename="")
        self.assertTrue(receipt["archived"])
        self.assertTrue(receipt["uri"].endswith("/CASE-SHP-1/document"))

    def test_list_objects_answers_for_the_configured_bucket_and_prefix(self):
        self.archive(prefix="inbox", filename="a.pdf")
        self.archive(prefix="inbox", filename="b.pdf", case_id="CASE-SHP-2")
        self.archive(prefix="elsewhere", filename="c.pdf")
        self.gcs.objects[("someone-elses-bucket", "inbox/x.pdf")] = (b"x", None)

        names = _run(document_store.list_objects("inbox/", limit=10))
        self.assertEqual(len(names), 2)
        self.assertTrue(all(n.startswith("inbox/") for n in names))
        self.assertEqual(len(_run(document_store.list_objects("inbox/", limit=1))), 1)


class TestArchiveFailuresAreReceipts(_ArchiveCase):
    def test_a_refused_upload_records_why_and_where(self):
        self.gcs.fail = Forbidden("403 caller lacks storage.objects.create")
        receipt = self.archive(case_id="CASE-SHP-3", filename="BL.pdf")

        self.assertFalse(receipt["archived"])
        self.assertNotIn("uri", receipt)
        self.assertIn("Forbidden", receipt["reason"])
        self.assertIn("storage.objects.create", receipt["reason"])
        self.assertTrue(receipt["intended_uri"].endswith("/CASE-SHP-3/BL.pdf"))

    def test_an_unbuildable_client_degrades_every_path_and_says_why(self):
        def no_credentials(project=None):
            raise RuntimeError("Could not automatically determine credentials")

        sys.modules["google.cloud.storage"].Client = no_credentials  # type: ignore[attr-defined]

        receipt = self.archive()

        self.assertFalse(receipt["archived"])
        self.assertIn("Could not automatically determine credentials", receipt["reason"])
        self.assertEqual(_run(document_store.fetch(f"gs://{BUCKET}/a/b.pdf")), (None, None))
        self.assertEqual(_run(document_store.list_objects("inbox/")), [])
        self.assertIn("credentials", document_store.status()["client_error"])

    def test_a_listing_failure_is_an_empty_listing(self):
        self.gcs.fail = Forbidden("403 caller lacks storage.objects.list")
        self.assertEqual(_run(document_store.list_objects("inbox/")), [])


class TestFetchReadsOnlyCloudStorage(_ArchiveCase):
    """
    fetch() is handed the URI stored on a case and streams what it finds to a
    reviewer's browser. Anything that is not a gs:// object is refused before a
    client is built, so the review route cannot be turned into a fetcher of
    arbitrary URLs.
    """

    def test_other_schemes_are_refused_without_touching_storage(self):
        for uri in (
            "https://metadata.google.internal/computeMetadata/v1/",
            "http://127.0.0.1:8080/internal/execute",
            "file:///etc/passwd",
            "s3://bucket/key",
            "/etc/passwd",
            "",
        ):
            with self.subTest(uri=uri):
                self.assertEqual(_run(document_store.fetch(uri)), (None, None))
        self.assertEqual(self.client_factory_calls, 0)
        self.assertEqual(self.gcs.calls, 0)

    def test_a_bucket_without_an_object_is_refused(self):
        self.assertEqual(_run(document_store.fetch(f"gs://{BUCKET}")), (None, None))
        self.assertEqual(_run(document_store.fetch(f"gs://{BUCKET}/")), (None, None))
        self.assertEqual(self.gcs.calls, 0)

    def test_a_missing_object_is_none_not_an_exception(self):
        self.assertEqual(
            _run(document_store.fetch(f"gs://{BUCKET}/shipping-documents/gone.pdf")),
            (None, None),
        )


class TestUnconfiguredArchive(_ArchiveCase):
    """No DOCUMENT_BUCKET: intake proceeds, says why there is no archive, calls nothing."""

    BUCKET_NAME = ""

    def test_archive_says_why_and_builds_no_client(self):
        receipt = self.archive()
        self.assertEqual(receipt, {"archived": False, "reason": "DOCUMENT_BUCKET not configured"})
        self.assertEqual(_run(document_store.list_objects("inbox/")), [])
        self.assertEqual(self.client_factory_calls, 0)

    def test_status_reports_the_archive_as_unconfigured(self):
        self.assertEqual(
            document_store.status(),
            {"bucket": None, "configured": False, "client_error": None},
        )


if __name__ == "__main__":
    unittest.main()
