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
import os
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
        Evidence responses are archived under evidence/<request>, beside the
        intake archive; both are system prefixes no sweep ingests.
        """
        receipt = self.archive(prefix="evidence/REQ-7")
        self.assertTrue(receipt["uri"].startswith(f"gs://{BUCKET}/evidence/REQ-7/"))

    def test_single_tenant_layout_is_unchanged_when_the_tenant_is_named(self):
        """The implicit tenant gets no segment: existing buckets keep their layout."""
        with patch.dict(os.environ, {"MULTI_TENANT": "false"}):
            receipt = self.archive(case_id="CASE-SHP-9", filename="invoice.pdf", tenant_id="default")
        self.assertRegex(
            receipt["uri"],
            rf"^gs://{BUCKET}/shipping-documents/\d{{4}}/\d{{2}}/\d{{2}}/CASE-SHP-9/invoice\.pdf$",
        )

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


ACME = "acme-freight"
GLOBEX = "globex-logistics"


class _MultiTenantCase(_ArchiveCase):
    def setUp(self):
        super().setUp()
        env = patch.dict(os.environ, {"MULTI_TENANT": "true"})
        env.start()
        self.addCleanup(env.stop)


class TestTenantLayout(_MultiTenantCase):
    """
    One bucket serves every tenant, so under MULTI_TENANT every object name
    carries its tenant. Without it, two tenants archiving the same shipment id
    and filename on the same day write one object, and the first tenant's
    reviewer is served the second tenant's paperwork.
    """

    def test_two_tenants_with_the_same_case_and_filename_write_two_objects(self):
        acme = self.archive(data=b"acme bill", case_id="CASE-SHP-1", filename="BL.pdf", tenant_id=ACME)
        globex = self.archive(data=b"globex bill", case_id="CASE-SHP-1", filename="BL.pdf", tenant_id=GLOBEX)

        self.assertNotEqual(acme["uri"], globex["uri"])
        self.assertEqual(_run(document_store.fetch(acme["uri"]))[0], b"acme bill")
        self.assertEqual(_run(document_store.fetch(globex["uri"]))[0], b"globex bill")

    def test_originals_and_evidence_are_filed_under_the_tenant(self):
        original = self.archive(case_id="CASE-SHP-9", filename="invoice.pdf", tenant_id=ACME)
        self.assertRegex(
            original["uri"],
            rf"^gs://{BUCKET}/tenants/{ACME}/shipping-documents/"
            rf"\d{{4}}/\d{{2}}/\d{{2}}/CASE-SHP-9/invoice\.pdf$",
        )
        evidence = self.archive(prefix="evidence/evreq-1", tenant_id=ACME)
        self.assertTrue(evidence["uri"].startswith(f"gs://{BUCKET}/tenants/{ACME}/evidence/evreq-1/"))

    def test_no_tenant_or_a_malformed_one_writes_nothing(self):
        """Fails closed: there is no shared root to fall back to."""
        for bad in (None, "", "../" + GLOBEX, f"{ACME}/../{GLOBEX}", f"tenants/{GLOBEX}", "acme freight"):
            with self.subTest(tenant_id=bad):
                receipt = self.archive(tenant_id=bad)
                self.assertFalse(receipt["archived"])
                self.assertNotIn("uri", receipt)
        self.assertEqual(self.gcs.objects, {})

    def test_a_case_id_cannot_climb_out_of_its_segment(self):
        """
        The case id is derived from the shipment id a document states about itself,
        so it is kept to one segment like the filename.
        """
        receipt = self.archive(case_id=f"CASE-x/../../../../{GLOBEX}/inbox", tenant_id=ACME)

        object_name = receipt["uri"].split(f"gs://{BUCKET}/", 1)[1]
        segments = object_name.split("/")
        self.assertEqual(segments[:3], ["tenants", ACME, "shipping-documents"])
        self.assertEqual(len(segments), 8, object_name)
        self.assertNotIn("..", segments)

    def test_a_uri_stored_before_the_tenant_segment_still_reads(self):
        """Stored URIs are opaque: cases archived under the old layout stay reviewable."""
        self.gcs.objects[(BUCKET, "shipping-documents/2026/01/02/CASE-OLD/BL.pdf")] = (b"old", "application/pdf")
        uri = f"gs://{BUCKET}/shipping-documents/2026/01/02/CASE-OLD/BL.pdf"
        self.assertEqual(_run(document_store.fetch(uri)), (b"old", "application/pdf"))


class TestWhatAStagedObjectMayBeIngestedAs(_MultiTenantCase):
    """
    The bucket sweep and the storage-event route ingest an object into the
    caller's board. Under MULTI_TENANT that is only right for an object in the
    caller's own space, and never for the service's own output in anyone's.
    """

    def refusal(self, name, tenant_id=ACME, bucket=BUCKET):
        return document_store.ingest_refusal(bucket, name, tenant_id)

    def test_the_callers_own_staged_object_is_ingestible(self):
        self.assertIsNone(self.refusal(f"tenants/{ACME}/inbox/a.pdf"))
        self.assertIsNone(self.refusal(f"tenants/{ACME}/a.pdf"))

    def test_objects_outside_the_callers_space_are_refused(self):
        for name in (
            f"tenants/{GLOBEX}/inbox/b.pdf",
            f"tenants/{ACME}-x/inbox/b.pdf",       # a tenant id that extends the caller's
            "inbox/legacy.pdf",                    # no tenant can be established
            "evidence/evreq-2/2026/10/14/CASE-2/cert.pdf",
            "shipping-documents/2026/10/14/CASE-3/BL.pdf",
            f"tenants/{GLOBEX}/evidence/evreq-1/2026/10/14/CASE-1/cert.pdf",
        ):
            with self.subTest(name=name):
                self.assertIsNotNone(self.refusal(name))

    def test_the_callers_own_system_output_is_refused(self):
        for name in (
            f"tenants/{ACME}/shipping-documents/2026/10/14/CASE-1/BL.pdf",
            f"tenants/{ACME}/evidence/evreq-1/2026/10/14/CASE-1/cert.pdf",
        ):
            with self.subTest(name=name):
                self.assertIsNotNone(self.refusal(name))

    def test_dot_segments_and_folders_are_refused(self):
        """
        GCS names are literal, but tools that show them as paths resolve "..",
        so a name with one has no unambiguous owner.
        """
        for name in (
            f"tenants/{ACME}/../{GLOBEX}/inbox/b.pdf",
            f"tenants/{ACME}/inbox/../../{GLOBEX}/inbox/b.pdf",
            f"tenants/{ACME}/./inbox/a.pdf",
            f"tenants/{ACME}/inbox/",
            "",
        ):
            with self.subTest(name=name):
                self.assertIsNotNone(self.refusal(name))

    def test_another_bucket_or_no_tenant_is_refused(self):
        self.assertIsNotNone(self.refusal(f"tenants/{ACME}/inbox/a.pdf", bucket="someone-elses-bucket"))
        self.assertIsNotNone(self.refusal(f"tenants/{ACME}/inbox/a.pdf", tenant_id=None))
        self.assertIsNotNone(self.refusal(f"tenants/{ACME}/inbox/a.pdf", tenant_id="../" + ACME))

    def test_single_tenant_skips_only_the_services_own_output(self):
        with patch.dict(os.environ, {"MULTI_TENANT": "false"}):
            self.assertIsNone(self.refusal("inbox/a.pdf", tenant_id=None))
            self.assertIsNone(self.refusal("a.pdf", tenant_id="default"))
            for name in (
                "shipping-documents/2026/10/14/CASE-1/BL.pdf",
                # An evidence upload read as a new shipment would open a case
                # nobody submitted.
                "evidence/evreq-1/2026/10/14/CASE-1/cert.pdf",
                f"tenants/{ACME}/evidence/evreq-1/2026/10/14/CASE-1/cert.pdf",
            ):
                with self.subTest(name=name):
                    self.assertIsNotNone(self.refusal(name, tenant_id=None))


if __name__ == "__main__":
    unittest.main()
