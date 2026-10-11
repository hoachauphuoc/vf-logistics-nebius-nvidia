"""
Boundary history: versions are never reused and nothing is overwritten.

WHY THIS FILE EXISTS

Two findings of the authorization review of bd6a210, with one root cause each.

A02. The next version was "active version + 1". After a revoke there is no active
boundary, so the next publish was v1 again, its id was BOUNDARY-v1 again, and the
store replaced the record with that id. The review's reproduction:

    before_id = BOUNDARY-v1 / after_id = BOUNDARY-v1
    history_count = 1 / original_author_retained = false

T01. The storage key was the bare boundary_id, shared by every tenant. Each
tenant's first publish is BOUNDARY-v1, so tenant B's first publish erased tenant
A's policy and history (A then read null and 0 records).

Both are pinned through governance.publish_boundary / revoke_boundary rather than
the store alone, because that is the path the route takes. The concurrency test
uses real threads: MemoryStore methods are synchronous under a lock, so
asyncio.gather would serialise them and prove nothing.

FirestoreStore implements the same contract in a transaction. It is held to the
same method signatures by test_tenant_isolation.py; its behaviour is not
exercised here (no emulator in this suite).

Class names use the `Test*` prefix: see test_console_session.py for why.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics import governance  # noqa: E402
from vf_logistics import store as store_mod  # noqa: E402

TENANT_A = "acme-freight"
TENANT_B = "beta-shipping"


def _run(coro):
    return asyncio.run(coro)


def _perms(note: str = "history test") -> dict:
    return governance.proposed_boundary(note)


class _FreshStore(unittest.TestCase):
    MULTI_TENANT = "false"

    def setUp(self):
        self.env = patch.dict(os.environ, {
            "STORE_BACKEND": "memory", "MULTI_TENANT": self.MULTI_TENANT,
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        store_mod._store = None
        self.addCleanup(setattr, store_mod, "_store", None)
        self.store = store_mod.get_store()

    def publish(self, author: str, tenant_id: str | None = None) -> dict:
        return _run(governance.publish_boundary(_perms(author), author, "n", tenant_id=tenant_id))

    def revoke(self, author: str, tenant_id: str | None = None) -> dict:
        return _run(governance.revoke_boundary(author, "stop", tenant_id=tenant_id))

    def history(self, tenant_id: str | None = None) -> list[dict]:
        return _run(self.store.list_boundaries(100, tenant_id=tenant_id))

    def active(self, tenant_id: str | None = None) -> dict | None:
        return _run(self.store.active_boundary(tenant_id=tenant_id))


class TestRepublishAfterRevoke(_FreshStore):
    """A02, the review's three steps."""

    def test_the_original_survives(self):
        first = self.publish("alice@forwarder.example")
        self.revoke("bob@forwarder.example")
        again = self.publish("carol@forwarder.example")

        self.assertEqual(first["boundary_id"], "BOUNDARY-v1")
        self.assertEqual(again["boundary_id"], "BOUNDARY-v2", "an id was reused")

        history = {b["boundary_id"]: b for b in self.history()}
        self.assertEqual(len(history), 2)
        original = history["BOUNDARY-v1"]
        self.assertEqual(original["status"], "REVOKED")
        self.assertEqual(original["published_by"], "alice@forwarder.example")
        self.assertEqual(original["revoked_by"], "bob@forwarder.example")
        self.assertEqual(original["permissions"], first["permissions"])
        self.assertEqual(history["BOUNDARY-v2"]["published_by"], "carol@forwarder.example")

    def test_a_revoked_version_is_not_superseded_by_the_republish(self):
        """It stays REVOKED: its revocation is the fact the record exists to keep."""
        self.publish("a")
        self.revoke("b")
        self.publish("c")
        v1 = next(b for b in self.history() if b["version"] == 1)
        self.assertEqual(v1["status"], "REVOKED")
        self.assertNotIn("superseded_by", v1)

    def test_versions_only_ever_rise(self):
        seen = []
        for i in range(3):
            seen.append(self.publish(f"p{i}")["version"])
            self.revoke(f"r{i}")
        seen.append(self.publish("last")["version"])
        self.assertEqual(seen, [1, 2, 3, 4])

    def test_a_case_reference_keeps_its_target(self):
        """A case records boundary_version; that number must keep meaning one policy."""
        first = self.publish("a")
        self.revoke("b")
        self.publish("c")
        by_version = [b for b in self.history() if b["version"] == first["version"]]
        self.assertEqual(len(by_version), 1)
        self.assertEqual(by_version[0]["published_by"], "a")


class TestSupersession(_FreshStore):
    def test_publish_supersedes_and_links_both_ways(self):
        self.publish("a")
        second = self.publish("b")
        history = {b["boundary_id"]: b for b in self.history()}
        self.assertEqual(history["BOUNDARY-v1"]["status"], "SUPERSEDED")
        self.assertEqual(history["BOUNDARY-v1"]["superseded_by"], "BOUNDARY-v2")
        self.assertEqual(second["supersedes"], "BOUNDARY-v1")
        self.assertEqual(self.active()["boundary_id"], "BOUNDARY-v2")

    def test_two_active_records_are_both_superseded(self):
        """A defect left behind by the old two-write publish must not survive the next one."""
        _run(self.store.put_boundary({"boundary_id": "BOUNDARY-v1", "version": 1, "status": "ACTIVE"}))
        _run(self.store.put_boundary({"boundary_id": "BOUNDARY-v2", "version": 2, "status": "ACTIVE"}))
        self.publish("a")
        statuses = sorted((b["version"], b["status"]) for b in self.history())
        self.assertEqual(statuses, [(1, "SUPERSEDED"), (2, "SUPERSEDED"), (3, "ACTIVE")])

    def test_records_written_before_the_counter_existed_set_the_floor(self):
        """The live service holds v1-v3 and no counter; its next publish is v4."""
        for v, status in ((1, "SUPERSEDED"), (2, "SUPERSEDED"), (3, "ACTIVE")):
            _run(self.store.put_boundary({"boundary_id": f"BOUNDARY-v{v}", "version": v, "status": status}))
        self.assertEqual(self.publish("a")["boundary_id"], "BOUNDARY-v4")

    def test_the_implicit_tenant_keeps_the_existing_key_format(self):
        """So the documents already in Firestore are the ones the code updates."""
        self.publish("a")
        self.assertIn("BOUNDARY-v1", self.store._boundaries)


class TestConcurrentPublishes(_FreshStore):
    def test_ten_at_once_get_ten_versions_and_one_active(self):
        def one(i: int) -> int:
            return self.publish(f"p{i}")["version"]

        with ThreadPoolExecutor(max_workers=10) as pool:
            versions = sorted(pool.map(one, range(10)))

        self.assertEqual(versions, list(range(1, 11)))
        history = self.history()
        self.assertEqual(len(history), 10)
        self.assertEqual(sum(1 for b in history if b["status"] == "ACTIVE"), 1)
        self.assertEqual(self.active()["version"], 10)


class TestAFailedPublishChangesNothing(_FreshStore):
    def test_failure_before_commit_keeps_the_active_boundary(self):
        self.publish("a")
        before = self.history()

        with patch.object(store_mod, "_stamp_tenant", side_effect=RuntimeError("disk full")):
            with self.assertRaises(RuntimeError):
                self.publish("b")

        self.assertEqual(self.history(), before)
        self.assertEqual(self.active()["boundary_id"], "BOUNDARY-v1")
        # And the version that failed is not burnt in a way that leaves a gap.
        self.assertEqual(self.publish("c")["boundary_id"], "BOUNDARY-v2")

    def test_an_existing_key_is_refused_not_overwritten(self):
        self.publish("a")
        original = dict(self.history()[0])
        # Force the allotment to collide with the stored record: forget the
        # counter and read every stored version as 0, so v1 is allotted again.
        self.store._boundary_counters.clear()
        with patch.object(store_mod, "_as_version", return_value=0):
            with self.assertRaises(store_mod.BoundaryConflict):
                self.publish("intruder")
        self.assertEqual(self.history()[0]["published_by"], original["published_by"])


class TestTenantsDoNotShareASlot(_FreshStore):
    """T01, with multi-tenancy on as the review ran it."""

    MULTI_TENANT = "true"

    def test_each_tenants_first_publish_survives_the_other(self):
        a = self.publish("a@acme.example", tenant_id=TENANT_A)
        b = self.publish("b@beta.example", tenant_id=TENANT_B)
        self.assertEqual(a["boundary_id"], b["boundary_id"], "same version, which is the point")

        active_a = self.active(tenant_id=TENANT_A)
        self.assertIsNotNone(active_a, "tenant B's publish erased tenant A's policy")
        self.assertEqual(active_a["published_by"], "a@acme.example")
        self.assertEqual(len(self.history(tenant_id=TENANT_A)), 1)
        self.assertEqual(len(self.history(tenant_id=TENANT_B)), 1)

    def test_revoking_one_tenant_leaves_the_other_running(self):
        self.publish("a", tenant_id=TENANT_A)
        self.publish("b", tenant_id=TENANT_B)
        self.revoke("b", tenant_id=TENANT_B)
        self.assertIsNotNone(self.active(tenant_id=TENANT_A))
        self.assertIsNone(self.active(tenant_id=TENANT_B))
        self.assertEqual(self.history(tenant_id=TENANT_A)[0]["status"], "ACTIVE")

    def test_versions_are_counted_per_tenant(self):
        for _ in range(3):
            self.publish("a", tenant_id=TENANT_A)
        self.assertEqual(self.publish("b", tenant_id=TENANT_B)["version"], 1)
        self.assertEqual(self.publish("a", tenant_id=TENANT_A)["version"], 4)

    def test_the_audit_trail_carries_the_full_grant(self):
        """The trail answers \"what was the agent allowed\" without the boundary record."""
        published = self.publish("a", tenant_id=TENANT_A)
        rows = _run(self.store.list_audit(limit=10, tenant_id=TENANT_A))
        row = next(r for r in rows if r.get("action") == "publish_delegation_boundary")
        self.assertEqual(row["detail"]["permissions"], published["permissions"])


if __name__ == "__main__":
    unittest.main()
