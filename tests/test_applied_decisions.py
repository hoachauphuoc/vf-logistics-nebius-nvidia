"""
The receiver's record of applied decisions (N01): one application per idempotency key
and tenant, every delivery counted. The last class runs the same on FirestoreStore
against the emulator, with concurrent deliveries, and is skipped without it.
"""

from __future__ import annotations

import asyncio
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from vf_logistics import store as store_mod  # noqa: E402

FIRESTORE = os.getenv("FIRESTORE_EMULATOR_HOST", "")
PROJECT = "vf-applied-test"
RECORD = {"case_id": "CASE-1", "outcome": "RELEASED_BY_HUMAN", "approval_id": "apr-1", "first_message_id": "m-1"}


def run(coro):
    return asyncio.run(coro)


class TestOnMemoryStore:
    def setup_method(self):
        self.store = store_mod.MemoryStore()

    def test_the_first_delivery_applies_and_a_repeat_only_counts(self):
        first = run(self.store.apply_decision_once("exec-apr-1", RECORD))
        second = run(self.store.apply_decision_once("exec-apr-1", {**RECORD, "first_message_id": "m-2"}))
        assert (first["applied"], first["deliveries"]) == (True, 1)
        assert (second["applied"], second["deliveries"]) == (False, 2)
        assert second["first_message_id"] == "m-1"

    def test_the_applied_record_can_be_read_back(self):
        run(self.store.apply_decision_once("exec-apr-1", RECORD))
        run(self.store.apply_decision_once("exec-apr-1", RECORD))
        doc = run(self.store.get_applied_decision("exec-apr-1"))
        assert doc["case_id"] == "CASE-1" and doc["deliveries"] == 2
        assert run(self.store.get_applied_decision("exec-apr-2")) is None

    def test_the_same_key_in_another_tenant_is_its_own_decision(self):
        run(self.store.apply_decision_once("exec-apr-1", RECORD, tenant_id="acme"))
        other = run(self.store.apply_decision_once("exec-apr-1", RECORD, tenant_id="globex"))
        assert other["applied"] is True
        assert run(self.store.get_applied_decision("exec-apr-1", tenant_id="acme"))["deliveries"] == 1
        assert run(self.store.get_applied_decision("exec-apr-1")) is None


@pytest.mark.skipif(not FIRESTORE, reason="FIRESTORE_EMULATOR_HOST is not set")
class TestOnFirestoreStore:
    def setup_method(self):
        request = urllib.request.Request(
            f"http://{FIRESTORE}/emulator/v1/projects/{PROJECT}/databases/(default)/documents",
            method="DELETE",
        )
        urllib.request.urlopen(request, timeout=10).close()  # noqa: S310 - local emulator
        self.store = store_mod.FirestoreStore(PROJECT)

    def test_concurrent_deliveries_of_one_key_apply_it_once(self):
        def deliver(_):
            return run(self.store.apply_decision_once("exec-apr-1", RECORD))

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(deliver, range(8)))
        assert [r["applied"] for r in results].count(True) == 1
        assert run(self.store.get_applied_decision("exec-apr-1"))["deliveries"] == 8
        assert run(self.store.get_applied_decision("exec-apr-1", tenant_id="other")) is None
