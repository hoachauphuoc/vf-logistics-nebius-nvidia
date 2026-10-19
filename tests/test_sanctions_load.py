"""
Loading the sanctions index, fail-closed: an index that cannot be read, or that parses but holds nothing, is
UNAVAILABLE with the reason -- never an empty list on which everyone is clean. A cloud copy that fails falls
back to the bundled seed and says so.
"""

from __future__ import annotations

import gzip
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics import sanctions  # noqa: E402

PAYLOAD = {
    "meta": {"version": 4, "source": "test"},
    "entities": [{"entity_id": "E-1", "name": "Bad Actor Ltd", "programs": ["OFAC"], "countries": ["ir"]}],
}


@pytest.fixture(autouse=True)
def clean_cache():
    keep = (sanctions._cached, sanctions._load_error, sanctions._loaded_at)
    sanctions._cached, sanctions._load_error, sanctions._loaded_at = None, None, 0.0
    yield
    sanctions._cached, sanctions._load_error, sanctions._loaded_at = keep


class TestLoading:
    def test_the_bundled_index_loads_when_no_bucket_is_configured(self):
        with patch.object(sanctions, "INDEX_BUCKET", ""), patch.object(sanctions, "_read_bundled", return_value=PAYLOAD):
            index = sanctions.load()
        assert index is not None and sanctions.load_error() is None

    def test_a_loaded_index_is_reused_until_it_is_old_or_forced(self):
        with patch.object(sanctions, "INDEX_BUCKET", ""), patch.object(sanctions, "_read_bundled", return_value=PAYLOAD) as read:
            first = sanctions.load()
            assert sanctions.load() is first
            sanctions.load(force=True)
        assert read.call_count == 2

    def test_a_cloud_copy_is_preferred(self):
        with patch.object(sanctions, "INDEX_BUCKET", "b"), patch.object(sanctions, "_read_gcs", return_value=PAYLOAD) as gcs, \
                patch.object(sanctions, "_read_bundled") as bundled:
            assert sanctions.load() is not None
        gcs.assert_called_once()
        bundled.assert_not_called()

    def test_a_cloud_failure_falls_back_to_the_bundle_and_says_so(self):
        with patch.object(sanctions, "INDEX_BUCKET", "b"), patch.object(sanctions, "_read_gcs", side_effect=OSError("denied")), \
                patch.object(sanctions, "_read_bundled", return_value=PAYLOAD):
            assert sanctions.load() is not None
        assert "GCS load failed (OSError: denied); using bundled seed index" in sanctions.load_error()

    def test_nothing_readable_at_all_is_unavailable_with_both_reasons(self):
        with patch.object(sanctions, "INDEX_BUCKET", "b"), patch.object(sanctions, "_read_gcs", side_effect=OSError("denied")), \
                patch.object(sanctions, "_read_bundled", side_effect=FileNotFoundError("gone")):
            assert sanctions.load() is None
        reason = sanctions.load_error()
        assert "GCS load failed" in reason and "bundled index unreadable (gone)" in reason

    def test_an_index_with_no_usable_entities_is_a_failed_load_not_a_clean_list(self):
        for payload in ({"entities": []}, {"entities": [{"entity_id": "", "name": "x"}, {"entity_id": "E", "name": ""}]}):
            sanctions._cached = None
            with patch.object(sanctions, "INDEX_BUCKET", ""), patch.object(sanctions, "_read_bundled", return_value=payload):
                assert sanctions.load(force=True) is None
            assert sanctions.load_error() == "index contained no usable entities"

    def test_a_shipment_is_unavailable_not_clear_when_the_list_cannot_be_read(self):
        with patch.object(sanctions, "INDEX_BUCKET", ""), patch.object(sanctions, "_read_bundled", side_effect=OSError("disk")):
            result = sanctions.screen_shipment({"shipper_name": "Anyone"})
        assert result["status"] == sanctions.UNAVAILABLE
        assert result["matches"] == []
        assert "disk" in result["reason"]

    def test_the_reason_has_a_default_when_none_was_recorded(self):
        with patch.object(sanctions, "load", return_value=None), patch.object(sanctions, "load_error", return_value=None):
            assert sanctions.screen_shipment({})["reason"] == "sanctions index unavailable"


class TestReadingFromStorage:
    def blob(self, raw):
        blob = MagicMock()
        blob.download_as_bytes.return_value = raw
        client = MagicMock()
        client.bucket.return_value.blob.return_value = blob
        return client

    @staticmethod
    def storage_module(client):
        """The client library is an optional install here, so stand in for the whole module."""
        import google.cloud as cloud

        fake = MagicMock()
        fake.Client.return_value = client
        return patch.multiple(cloud, storage=fake, create=True), patch.dict(sys.modules, {"google.cloud.storage": fake})

    def test_a_plain_json_object_is_parsed(self):
        client = self.blob(json.dumps(PAYLOAD).encode())
        attr, mod = self.storage_module(client)
        with attr, mod:
            assert sanctions._read_gcs("b", "idx.json") == PAYLOAD

    def test_a_gzip_object_is_decompressed_first(self):
        client = self.blob(gzip.compress(json.dumps(PAYLOAD).encode()))
        attr, mod = self.storage_module(client)
        with attr, mod:
            assert sanctions._read_gcs("b", "idx.json.gz") == PAYLOAD
        client.bucket.assert_called_once_with("b")


class TestAge:
    def index(self, synced_at):
        meta = {"synced_at": synced_at} if synced_at is not None else {}
        return sanctions.SanctionsIndex(meta, sanctions._entities_from_payload(PAYLOAD))

    def test_a_list_synced_three_days_ago_is_three_days_old(self):
        stamp = (datetime.now(timezone.utc) - timedelta(days=3, hours=1)).isoformat()
        assert self.index(stamp).age_days() == 3

    def test_a_stamp_without_a_zone_is_read_as_utc(self):
        stamp = (datetime.now(timezone.utc) - timedelta(days=2, hours=1)).replace(tzinfo=None).isoformat()
        assert self.index(stamp).age_days() == 2

    def test_a_stamp_in_the_future_is_zero_days_not_negative(self):
        assert self.index((datetime.now(timezone.utc) + timedelta(days=5)).isoformat()).age_days() == 0

    def test_no_stamp_or_an_unreadable_one_is_unknown(self):
        assert self.index(None).age_days() is None
        assert self.index("last tuesday").age_days() is None
