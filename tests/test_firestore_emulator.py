"""
FirestoreStore's transactional writes, against the Firestore emulator.

WHY THIS FILE EXISTS

Findings A02, T01 and A04 were fixed with Firestore transactions (publish and
revoke allot versions and create() rather than set(); the sign-in ledger counts
under a transaction). Every other test runs on MemoryStore, and the two backends
are held together only by signature parity -- which is exactly the gap the
review called out for MULTI_TENANT. These tests run the real FirestoreStore code
against the emulator.

Skipped unless FIRESTORE_EMULATOR_HOST is set, so CI without the emulator is
unaffected. To run:

    gcloud emulators firestore start --host-port=127.0.0.1:8681
    FIRESTORE_EMULATOR_HOST=127.0.0.1:8681 python -m pytest tests/test_firestore_emulator.py

The emulator project id is fixed and fake; nothing here can reach a real
database, and every test starts by wiping the emulator's documents.

Class names use the `Test*` prefix: see test_console_session.py for why.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import unittest
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics import governance  # noqa: E402
from vf_logistics import store as store_mod  # noqa: E402

EMULATOR = os.getenv("FIRESTORE_EMULATOR_HOST", "")
PROJECT = "vf-emulator-test"


def _run(coro):
    return asyncio.run(coro)


def _wipe() -> None:
    request = urllib.request.Request(
        f"http://{EMULATOR}/emulator/v1/projects/{PROJECT}/databases/(default)/documents",
        method="DELETE",
    )
    urllib.request.urlopen(request, timeout=10).close()  # noqa: S310 - local emulator


@unittest.skipUnless(EMULATOR, "FIRESTORE_EMULATOR_HOST is not set")
class _EmulatorCase(unittest.TestCase):
    MULTI_TENANT = "false"

    def setUp(self):
        _wipe()
        env = patch.dict(os.environ, {
            "STORE_BACKEND": "firestore", "PROJECT_ID": PROJECT,
            "MULTI_TENANT": self.MULTI_TENANT,
        })
        env.start()
        self.addCleanup(env.stop)
        self.store = store_mod.FirestoreStore(PROJECT)
        store_mod._store = self.store
        self.addCleanup(setattr, store_mod, "_store", None)

    def publish(self, author: str, tenant_id: str | None = None) -> dict:
        return _run(governance.publish_boundary(
            governance.proposed_boundary(author), author, "n", tenant_id=tenant_id,
        ))

    def history(self, tenant_id: str | None = None) -> list[dict]:
        return _run(self.store.list_boundaries(100, tenant_id=tenant_id))


class TestRepublishAfterRevokeOnFirestore(_EmulatorCase):
    def test_the_original_survives_and_the_id_is_new(self):
        first = self.publish("alice")
        _run(governance.revoke_boundary("bob", "stop"))
        again = self.publish("carol")

        self.assertEqual((first["version"], again["version"]), (1, 2))
        history = {b["boundary_id"]: b for b in self.history()}
        self.assertEqual(set(history), {"BOUNDARY-v1", "BOUNDARY-v2"})
        self.assertEqual(history["BOUNDARY-v1"]["status"], "REVOKED")
        self.assertEqual(history["BOUNDARY-v1"]["published_by"], "alice")
        self.assertEqual(history["BOUNDARY-v1"]["revoked_by"], "bob")
        self.assertEqual(history["BOUNDARY-v2"]["status"], "ACTIVE")

    def test_supersession_marks_the_previous_one(self):
        self.publish("a")
        self.publish("b")
        statuses = sorted((b["version"], b["status"]) for b in self.history())
        self.assertEqual(statuses, [(1, "SUPERSEDED"), (2, "ACTIVE")])

    def test_an_existing_document_is_never_overwritten(self):
        """create(), not set(): a collision fails instead of replacing the record."""
        _run(self.store.put_boundary({
            "boundary_id": "BOUNDARY-v1", "version": "unreadable", "status": "SUPERSEDED",
            "published_by": "original",
        }))
        with self.assertRaises(Exception):
            self.publish("intruder")
        stored = self.history()
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["published_by"], "original")

    def test_concurrent_publishes_get_distinct_versions_and_one_active(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            versions = sorted(pool.map(lambda i: self.publish(f"p{i}")["version"], range(6)))
        self.assertEqual(versions, list(range(1, 7)))
        history = self.history()
        self.assertEqual(len(history), 6)
        self.assertEqual(sum(1 for b in history if b["status"] == "ACTIVE"), 1)


class TestTenantsOnFirestore(_EmulatorCase):
    MULTI_TENANT = "true"

    def test_two_tenants_first_publish_do_not_collide(self):
        self.publish("a", tenant_id="acme")
        self.publish("b", tenant_id="beta-shipping")
        active_a = _run(self.store.active_boundary(tenant_id="acme"))
        self.assertIsNotNone(active_a)
        self.assertEqual(active_a["published_by"], "a")
        self.assertEqual(len(self.history(tenant_id="acme")), 1)
        self.assertEqual(len(self.history(tenant_id="beta-shipping")), 1)

    def test_revoking_one_tenant_leaves_the_other(self):
        self.publish("a", tenant_id="acme")
        self.publish("b", tenant_id="beta-shipping")
        _run(governance.revoke_boundary("b", "stop", tenant_id="beta-shipping"))
        self.assertIsNotNone(_run(self.store.active_boundary(tenant_id="acme")))
        self.assertIsNone(_run(self.store.active_boundary(tenant_id="beta-shipping")))


class TestSignInLedgerOnFirestore(_EmulatorCase):
    def hit(self, key: str = "acct:x", limit: int = 3) -> bool:
        # An hour's window, so a test that happens to run across a window
        # boundary is vanishingly unlikely. Patching time.time instead would also
        # move the gRPC client's own deadlines.
        return _run(self.store.hit_rate_limit(key, 3600, limit))

    def test_allows_the_limit_then_refuses(self):
        self.assertEqual([self.hit() for _ in range(5)], [False, False, False, True, True])

    def test_concurrent_attempts_never_spend_more_than_the_limit(self):
        """
        The property a per-process counter lacked: every caller, one ledger.

        At most the limit, not exactly: an attempt that loses on contention after
        every retry is counted as limited (fail closed), so a burst may admit
        fewer. Admitting MORE would be the vulnerability; admitting none would
        mean the ledger is broken, so at least one must get through.
        """
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.hit(limit=5), range(12)))
        admitted = results.count(False)
        self.assertLessEqual(admitted, 5)
        self.assertGreaterEqual(admitted, 1)

    def test_a_burst_is_answered_quickly(self):
        """
        The console waits 3 s and then refuses the sign-in (finding R01). A ledger
        that queues under a burst would turn the limit into an outage.
        """
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: self.hit(limit=5), range(12)))
        self.assertLess(time.monotonic() - started, 3.0)

    def test_the_document_carries_an_expiry_and_no_email(self):
        self.hit("acct:judge@x.example")
        docs = list(self.store._throttle.stream())
        self.assertEqual(len(docs), 1)
        self.assertNotIn("judge", docs[0].id)
        self.assertIn("expire_at", docs[0].to_dict())


class TestSignInLedgerUnderMultiTenancy(_EmulatorCase):
    """Re-review R04: the console's one ledger scope, not a tenant, under MULTI_TENANT."""

    MULTI_TENANT = "true"

    def test_the_platform_scope_counts_as_one_ledger(self):
        scope = store_mod.LOGIN_THROTTLE_SCOPE

        def hit() -> bool:
            return _run(self.store.hit_rate_limit("acct:x", 3600, 3, tenant_id=scope))

        self.assertEqual([hit() for _ in range(5)], [False, False, False, True, True])
        docs = list(self.store._throttle.stream())
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].to_dict()[store_mod.TENANT_FIELD], scope)


class TestOnlyContentionIsRetried(unittest.TestCase):
    """
    Runs without the emulator. A retry loop that swallowed any ValueError would
    retry a real bug eight times and, on the sign-in ledger, report it as
    "limited" -- hiding it behind a 429.
    """

    class Aborted(Exception):
        pass

    def test_races_are_contention(self):
        self.assertTrue(store_mod._is_contention(self.Aborted(), self.Aborted))
        self.assertTrue(store_mod._is_contention(
            ValueError("Failed to commit transaction in 25 attempts."), self.Aborted,
        ))

    def test_other_errors_are_not(self):
        for exc in (ValueError("bad value"), RuntimeError("down"), KeyError("x")):
            with self.subTest(exc=exc):
                self.assertFalse(store_mod._is_contention(exc, self.Aborted))


if __name__ == "__main__":
    unittest.main()
