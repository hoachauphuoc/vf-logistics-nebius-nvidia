"""
Module 2: tenant isolation.

What these tests are for
------------------------
Every other test in this suite can pass while tenant isolation is broken, because
isolation is a negative property: it is about what a caller CANNOT see. So these
tests are written from the attacker's side. Tenant A writes, tenant B reads, and
the assertion is that B gets nothing -- on every read path, not a representative
sample, because the one path nobody checked is the one that leaks.

Why get_case returns None rather than 403
-----------------------------------------
A distinct "exists, but is not yours" response confirms the id is real, which
turns the API into an oracle for enumerating another tenant's case ids. So a
foreign case is indistinguishable from a missing one. test_foreign_case_is_
indistinguishable_from_missing is the assertion that keeps it that way.

Why the signature parity test lives here
----------------------------------------
MemoryStore and FirestoreStore are duck-typed with no ABC, so nothing forces them
to agree. During this work MemoryStore gained tenant_id on sixteen methods while
FirestoreStore had none, and every call passing tenant_id would have worked in the
tests and crashed in production. The parity test makes that state unreachable.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("STORE_BACKEND", "memory")

from vf_logistics import store as store_mod  # noqa: E402
from vf_logistics import tenant  # noqa: E402
from vf_logistics.store import (  # noqa: E402
    TENANT_FIELD,
    FirestoreStore,
    MemoryStore,
    new_id,
    utcnow,
)

TENANT_A = "acme-freight"
TENANT_B = "globex-logistics"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _case(case_id: str, state: str = "AUTO_CLEARED", **extra) -> dict:
    return {
        "case_id": case_id,
        "shipment_id": f"SHIP-{case_id}",
        "state": state,
        "created_at": utcnow(),
        "steps": [],
        "actions": [],
        "cleared_by": "ai",
        "_agent_calls": 2,
        "_input_tokens": 1000,
        "_output_tokens": 500,
        "_estimated_cost_usd": 0.001,
        "_sum_latency_ms": 200,
        **extra,
    }


class StoreBackendParityTests(unittest.TestCase):
    def _public_signatures(self, cls) -> dict[str, list[str]]:
        return {
            name: list(inspect.signature(fn).parameters)
            for name, fn in inspect.getmembers(cls, predicate=inspect.isfunction)
            if not name.startswith("_")
        }

    def test_backends_expose_identical_signatures(self):
        """
        Duck-typed backends with no ABC. A method that gained tenant_id on one
        and not the other would pass every test and crash in production, because
        the tests run on memory and production runs on Firestore.
        """
        memory = self._public_signatures(MemoryStore)
        firestore = self._public_signatures(FirestoreStore)

        self.assertEqual(
            set(memory), set(firestore), "the two backends expose different methods",
        )
        for name in sorted(memory):
            self.assertEqual(
                memory[name], firestore[name],
                f"{name}() has different parameters on the two backends",
            )

    def test_every_store_method_accepts_a_tenant(self):
        for name, params in self._public_signatures(MemoryStore).items():
            self.assertIn(
                "tenant_id", params,
                f"{name}() cannot be scoped to a tenant, so it is a leak waiting "
                f"to happen",
            )


class TenantResolutionTests(unittest.TestCase):
    def test_absent_tenant_resolves_to_the_implicit_one_when_single_tenant(self):
        with patch.dict(os.environ, {"MULTI_TENANT": "false"}):
            self.assertEqual(tenant.resolve(None), tenant.SINGLE_TENANT_ID)

    def test_absent_tenant_raises_when_multi_tenant(self):
        """
        There is no default tenant. Resolving one would pool a customer's records
        into a bucket another customer can read.
        """
        with patch.dict(os.environ, {"MULTI_TENANT": "true"}):
            with self.assertRaises(tenant.TenantError):
                tenant.resolve(None)
            with self.assertRaises(tenant.TenantError):
                tenant.resolve("")
            with self.assertRaises(tenant.TenantError):
                tenant.resolve("   ")

    def test_require_tenant_never_falls_back(self):
        """Billing attribution must not silently invoice "default"."""
        with patch.dict(os.environ, {"MULTI_TENANT": "false"}):
            with self.assertRaises(tenant.TenantError):
                tenant.require_tenant(None)

    def test_path_dangerous_ids_are_rejected(self):
        """
        A tenant id lands in Firestore query keys. Anything needing escaping is
        rejected rather than escaped, because an id that needs escaping will be
        used unescaped somewhere eventually.
        """
        for bad in (
            "../other", "a/b", "tenant.with.dots", "has space", "UPPER/slash",
            "x", "", "-starts-with-hyphen", "a" * 64, "tenant\x00null",
        ):
            with self.assertRaises(tenant.TenantError, msg=f"{bad!r} was accepted"):
                tenant.validate(bad)

    def test_ids_are_case_insensitive(self):
        self.assertEqual(tenant.validate("Acme-Freight"), "acme-freight")

    def test_free_mail_does_not_become_a_shared_tenant(self):
        """Otherwise every gmail user would read every other gmail user's data."""
        for address in (
            "someone@gmail.com", "x@outlook.com", "y@zohomail.com",
            "z@protonmail.com",
        ):
            self.assertIsNone(tenant.tenant_from_email(address), address)

    def test_corporate_domain_maps_to_a_tenant(self):
        self.assertEqual(tenant.tenant_from_email("ops@acme.com"), "acme")
        self.assertEqual(tenant.tenant_from_email("ops@acme.co.uk"), "acme")

    def test_isolation_guard_refuses_the_dangerous_combination(self):
        """
        auth.py grants GOVERNANCE_ADMIN to every request when IAP is off. With
        real tenants behind that, a caller who can assert any identity can assert
        any tenant, and the isolation is decoration. Failing to boot is the only
        safe response.
        """
        with patch.dict(os.environ, {
            "MULTI_TENANT": "true", "STORE_BACKEND": "firestore",
            "IAP_ENABLED": "false",
        }):
            with self.assertRaises(tenant.TenantIsolationError):
                tenant.assert_isolation_is_enforceable()

    def test_isolation_guard_allows_the_safe_combinations(self):
        safe = [
            {"MULTI_TENANT": "false", "STORE_BACKEND": "firestore", "IAP_ENABLED": "false"},
            {"MULTI_TENANT": "true", "STORE_BACKEND": "firestore", "IAP_ENABLED": "true"},
            {"MULTI_TENANT": "true", "STORE_BACKEND": "memory", "IAP_ENABLED": "false"},
        ]
        for env in safe:
            with patch.dict(os.environ, env):
                tenant.assert_isolation_is_enforceable()  # must not raise


class IsolationOnEveryReadPathTests(unittest.TestCase):
    """Tenant A writes. Tenant B must see nothing, on every path."""

    def setUp(self):
        self.store = MemoryStore()
        _run(self.store.put_case(_case("CASE-A1"), tenant_id=TENANT_A))
        _run(self.store.put_case(
            _case("CASE-A2", state="HELD_FOR_REVIEW", client_reference="REF-A"),
            tenant_id=TENANT_A,
        ))
        _run(self.store.add_event(
            {"event_id": new_id("ev"), "at": utcnow(), "kind": "a"},
            tenant_id=TENANT_A,
        ))
        _run(self.store.add_audit(
            {"audit_id": "AUD-A", "case_id": "CASE-A1", "action": "release",
             "status": "ok", "at": utcnow()},
            tenant_id=TENANT_A,
        ))
        _run(self.store.put_boundary(
            {"boundary_id": "B-A", "version": 1, "status": "ACTIVE"},
            tenant_id=TENANT_A,
        ))

    def test_get_case(self):
        self.assertIsNotNone(_run(self.store.get_case("CASE-A1", tenant_id=TENANT_A)))
        self.assertIsNone(_run(self.store.get_case("CASE-A1", tenant_id=TENANT_B)))

    def test_foreign_case_is_indistinguishable_from_missing(self):
        """
        Both return None. A different response for a real-but-foreign id would
        let a caller enumerate another tenant's case ids.
        """
        foreign = _run(self.store.get_case("CASE-A1", tenant_id=TENANT_B))
        absent = _run(self.store.get_case("CASE-NEVER-EXISTED", tenant_id=TENANT_B))
        self.assertEqual(foreign, absent)

    def test_list_cases(self):
        self.assertEqual(len(_run(self.store.list_cases(tenant_id=TENANT_A))), 2)
        self.assertEqual(_run(self.store.list_cases(tenant_id=TENANT_B)), [])

    def test_query_cases(self):
        rows, _ = _run(self.store.query_cases(tenant_id=TENANT_A))
        self.assertEqual(len(rows), 2)
        rows, _ = _run(self.store.query_cases(tenant_id=TENANT_B))
        self.assertEqual(rows, [])

    def test_query_cases_with_a_state_filter(self):
        rows, _ = _run(self.store.query_cases(
            states=("HELD_FOR_REVIEW",), tenant_id=TENANT_B,
        ))
        self.assertEqual(rows, [], "the review queue must not cross tenants")

    def test_find_case_by_client_reference(self):
        """
        Idempotency keys are the integrator's own strings and will collide across
        customers. A collision must not return someone else's audit.
        """
        self.assertIsNotNone(_run(
            self.store.find_case_by_client_reference("REF-A", tenant_id=TENANT_A)
        ))
        self.assertIsNone(_run(
            self.store.find_case_by_client_reference("REF-A", tenant_id=TENANT_B)
        ))

    def test_count_by_state(self):
        counts = _run(self.store.count_by_state(
            ("AUTO_CLEARED", "HELD_FOR_REVIEW"), tenant_id=TENANT_B,
        ))
        self.assertEqual(sum(counts.values()), 0)

    def test_count_by_cleared_by(self):
        counts = _run(self.store.count_by_cleared_by(tenant_id=TENANT_B))
        self.assertEqual(counts["total_auto_cleared"], 0)

    def test_list_and_query_events(self):
        self.assertEqual(len(_run(self.store.list_events(tenant_id=TENANT_A))), 1)
        self.assertEqual(_run(self.store.list_events(tenant_id=TENANT_B)), [])
        rows, _ = _run(self.store.query_events(tenant_id=TENANT_B))
        self.assertEqual(rows, [])

    def test_list_and_query_audit(self):
        self.assertEqual(len(_run(self.store.list_audit(tenant_id=TENANT_A))), 1)
        self.assertEqual(_run(self.store.list_audit(tenant_id=TENANT_B)), [])
        rows, _ = _run(self.store.query_audit(
            case_id="CASE-A1", tenant_id=TENANT_B,
        ))
        self.assertEqual(rows, [], "an audit trail must not cross tenants")

    def test_boundaries(self):
        """
        Tenant-scoped because "Compliance Admin configures risk rules" is a
        per-customer role: one customer's delegated auto-release ceiling has no
        business governing another's shipments.
        """
        self.assertIsNotNone(_run(self.store.active_boundary(tenant_id=TENANT_A)))
        self.assertIsNone(
            _run(self.store.active_boundary(tenant_id=TENANT_B)),
            "tenant B inherits no authority from tenant A's boundary",
        )
        self.assertEqual(_run(self.store.list_boundaries(tenant_id=TENANT_B)), [])

    def test_no_active_boundary_means_fail_closed_for_the_new_tenant(self):
        """A new tenant starts with no delegated authority, not with someone
        else's."""
        self.assertIsNone(_run(self.store.active_boundary(tenant_id="brand-new")))


class CrossTenantWriteTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        _run(self.store.put_case(_case("CASE-A1"), tenant_id=TENANT_A))

    def test_put_case_refuses_to_rehome_an_existing_case(self):
        """
        A read-modify-write made in another tenant's request context would
        otherwise move the case across the boundary -- a write that silently
        steals a record instead of failing.
        """
        stolen = _run(self.store.get_case("CASE-A1", tenant_id=TENANT_A))
        with self.assertRaises(tenant.TenantError):
            _run(self.store.put_case(
                stolen, expected_version=stolen["_version"], tenant_id=TENANT_B,
            ))
        still_a = _run(self.store.get_case("CASE-A1", tenant_id=TENANT_A))
        self.assertIsNotNone(still_a, "the case must still belong to tenant A")

    def test_reset_clears_only_the_calling_tenant(self):
        """An unscoped wipe would let one customer clear another's board."""
        _run(self.store.put_case(_case("CASE-B1"), tenant_id=TENANT_B))
        removed = _run(self.store.reset(tenant_id=TENANT_B))
        self.assertEqual(removed, 1)
        self.assertIsNotNone(_run(self.store.get_case("CASE-A1", tenant_id=TENANT_A)))
        self.assertIsNone(_run(self.store.get_case("CASE-B1", tenant_id=TENANT_B)))

    def test_release_case_cannot_touch_another_tenants_case(self):
        _run(self.store.claim_next_pending(("AUTO_CLEARED",), tenant_id=TENANT_A))
        _run(self.store.release_case("CASE-A1", tenant_id=TENANT_B))
        case = _run(self.store.get_case("CASE-A1", tenant_id=TENANT_A))
        self.assertTrue(
            case["claimed"], "tenant B must not interfere with tenant A's pipeline",
        )

    def test_every_write_is_stamped_with_an_owner(self):
        """An unowned document can never be returned by a scoped query, which
        would look like data loss rather than like the bug it is."""
        case = _run(self.store.get_case("CASE-A1", tenant_id=TENANT_A))
        self.assertEqual(case[TENANT_FIELD], TENANT_A)


class BillingAttributionTests(unittest.TestCase):
    def test_rollups_are_per_tenant(self):
        """
        An unscoped total would bill every customer for the whole platform's
        spend, which is a wrong invoice rather than a wrong dashboard.
        """
        store = MemoryStore()
        _run(store.put_case(_case("CASE-A1"), tenant_id=TENANT_A))
        _run(store.put_case(_case("CASE-A2"), tenant_id=TENANT_A))
        _run(store.put_case(_case("CASE-B1"), tenant_id=TENANT_B))

        a = _run(store.sum_rollups(tenant_id=TENANT_A))
        b = _run(store.sum_rollups(tenant_id=TENANT_B))

        self.assertEqual(a["total_input_tokens"], 2000)
        self.assertEqual(b["total_input_tokens"], 1000)
        self.assertAlmostEqual(a["estimated_cost_usd"], 0.002, places=6)
        self.assertAlmostEqual(b["estimated_cost_usd"], 0.001, places=6)


class WorkerScopeTests(unittest.TestCase):
    def test_worker_claims_across_every_tenant(self):
        """
        tenant_id=None on claim_next_pending means "any tenant", not "the default
        tenant". Scoping the background worker to one would leave every other
        customer's cases unprocessed forever.
        """
        store = MemoryStore()
        _run(store.put_case(_case("CASE-B1", state="INGESTED"), tenant_id=TENANT_B))

        claimed = _run(store.claim_next_pending(("INGESTED",)))
        self.assertIsNotNone(
            claimed, "the worker must pick up work from tenants other than default",
        )
        self.assertEqual(claimed["case_id"], "CASE-B1")


class LegacyDocumentTests(unittest.TestCase):
    def test_documents_written_before_stamping_belong_to_the_default_tenant(self):
        """
        Otherwise the upgrade that introduced the field would make every existing
        case invisible. Sound only because those records predate multi-tenancy by
        definition -- multi-tenancy is what introduced the field.
        """
        store = MemoryStore()
        legacy = _case("CASE-LEGACY")
        # Written directly, bypassing put_case, to simulate a pre-upgrade row.
        store._cases["CASE-LEGACY"] = legacy
        self.assertNotIn(TENANT_FIELD, legacy)

        found = _run(store.get_case(
            "CASE-LEGACY", tenant_id=tenant.SINGLE_TENANT_ID,
        ))
        self.assertIsNotNone(found)
        self.assertIsNone(_run(store.get_case("CASE-LEGACY", tenant_id=TENANT_B)))


class SingleTenantBackwardCompatibilityTests(unittest.TestCase):
    def test_omitting_tenant_id_keeps_working(self):
        """
        Every existing call site omits tenant_id. With multi-tenancy off they all
        resolve to the one implicit tenant, so behaviour is unchanged -- which is
        what lets this land without rewriting the orchestrator.
        """
        store = MemoryStore()
        _run(store.put_case(_case("CASE-X")))
        self.assertIsNotNone(_run(store.get_case("CASE-X")))
        self.assertEqual(len(_run(store.list_cases())), 1)
        rows, _ = _run(store.query_cases())
        self.assertEqual(len(rows), 1)

    def test_the_implicit_tenant_is_named_not_blank(self):
        """Turning multi-tenancy on later must not find a population of records
        whose owner is an empty string."""
        store = MemoryStore()
        _run(store.put_case(_case("CASE-X")))
        case = _run(store.get_case("CASE-X"))
        self.assertEqual(case[TENANT_FIELD], tenant.SINGLE_TENANT_ID)
        self.assertTrue(tenant.SINGLE_TENANT_ID)


# --------------------------------------------------------------------------
# Route-level isolation
# --------------------------------------------------------------------------
#
# Everything above tests the store. That is necessary and not sufficient: the
# store was already fully scoped while the orchestrator, governance and tools
# layers dropped the tenant on the way to it, so every store test passed and
# four of fifty-two routes were actually isolated.
#
# These tests run the real Flask handlers with MULTI_TENANT=true. Under that
# setting tenant.resolve(None) raises, so a handler that still drops the tenant
# cannot return a plausible-looking answer -- it 500s, and the walk below fails.


def _auth_as(tenant_id: str):
    """An authenticated context for one tenant, as IAP would produce."""
    from vf_logistics import auth

    return auth.AuthContext(
        email=f"operator@{tenant_id}.example",
        roles={auth.Role.GOVERNANCE_ADMIN},
        iap_subject=f"subject-{tenant_id}",
        tenant_id=tenant_id,
    )


class RouteTenantCompletenessTests(unittest.TestCase):
    """
    The completeness gate for threading the tenant through every layer.

    Written as a walk over routes rather than as one test per route on purpose:
    a per-route list is a list somebody forgets to add to, and the failure that
    causes is silent. This asks the app for its own URL map, so a route added
    later is covered on arrival.
    """

    # Routes excluded, each for a stated reason rather than because it failed.
    #
    # The machine-to-machine sinks take no tenant by design -- _tenant() returns
    # None for them and the store resolves the implicit tenant, which is sound
    # while they are IAM-gated, and tenant.assert_isolation_is_enforceable()
    # refuses to boot the configuration where it would not be.
    #
    # All of these happen to be POST-only, so the GET walk below would not reach
    # them anyway. They are listed so that adding a GET to one of them is a
    # deliberate act rather than something this test quietly starts covering, and
    # the paths are the real ones: an earlier version of this list had
    # "/api/v1/bucket/", which matches nothing -- the route is
    # /api/v1/ingest/bucket-sweep.
    SKIP_PREFIXES = (
        "/api/v1/events/",        # Pub/Sub shipment sink and the GCS storage sink
        "/internal/",             # cross-identity executor hop, IAM-gated
        "/api/v1/ingest/",        # operator sweep of the staging bucket
        "/static/",
    )
    SKIP_EXACT = {
        "/",                      # serves HTML, not the API
        "/health",
        "/healthz",
        "/readyz",
        "/api/v1/openapi.json",
        "/api/v1/config",
        # Spends model tokens on a real inference call, so it needs credentials
        # and would bill a run of the test suite. Its own tests cover it.
        "/demo",
    }

    def setUp(self):
        self.env = patch.dict(os.environ, {
            "MULTI_TENANT": "true",
            "STORE_BACKEND": "memory",
            "IAP_ENABLED": "false",
        })
        self.env.start()
        self.addCleanup(self.env.stop)

        from vf_logistics import app as app_mod

        self.app_mod = app_mod
        app_mod.app.config["TESTING"] = True
        self.client = app_mod.app.test_client()

        ctx = _auth_as(TENANT_A)
        self.auth_patch = patch.object(app_mod, "get_auth_context", lambda: ctx)
        self.auth_patch.start()
        self.addCleanup(self.auth_patch.stop)

    def _gettable_paths(self) -> list[str]:
        paths = []
        for rule in self.app_mod.app.url_map.iter_rules():
            if "GET" not in (rule.methods or set()):
                continue
            if rule.arguments:
                continue  # needs a real id; covered by the per-route tests below
            path = str(rule.rule)
            if path in self.SKIP_EXACT:
                continue
            if any(path.startswith(p) for p in self.SKIP_PREFIXES):
                continue
            paths.append(path)
        return sorted(paths)

    def test_no_get_route_drops_the_tenant(self):
        """
        Under MULTI_TENANT=true a handler that reaches the store without a tenant
        raises TenantError, which surfaces as a 500. Any 5xx here means a layer
        between the route and the store is still dropping the value.
        """
        broken = []
        for path in self._gettable_paths():
            resp = self.client.get(path)
            if resp.status_code >= 500:
                broken.append((path, resp.status_code))

        self.assertEqual(
            [], broken,
            "these routes reached the store without a tenant: "
            + ", ".join(f"{p} -> {s}" for p, s in broken),
        )

    def test_the_walk_actually_covered_something(self):
        """
        Guards the guard. A typo in SKIP_PREFIXES that excluded everything would
        make the test above pass by testing nothing, which is the failure mode of
        every test that iterates over a filtered collection.
        """
        self.assertGreaterEqual(len(self._gettable_paths()), 8)


class ReviewActionIsolationTests(unittest.TestCase):
    """
    The two write paths that take a case_id from the caller.

    Both looked up the case unscoped, and put_case preserves the stored owner --
    so a reviewer in one tenant naming another tenant's case id would have had
    their decision recorded against the victim's shipment, successfully.
    """

    def setUp(self):
        self.env = patch.dict(os.environ, {
            "MULTI_TENANT": "true", "STORE_BACKEND": "memory",
        })
        self.env.start()
        self.addCleanup(self.env.stop)

        self.store = MemoryStore()
        self.store_patch = patch.object(store_mod, "_store", self.store)
        self.store_patch.start()
        self.addCleanup(self.store_patch.stop)

        _run(self.store.put_case(
            _case("CASE-A1", state="PENDING_HUMAN"), tenant_id=TENANT_A,
        ))

    def test_human_decide_cannot_reach_another_tenants_case(self):
        from vf_logistics import orchestrator

        result = _run(orchestrator.human_decide(
            "CASE-A1", "block", "reviewer-b", "not mine to block",
            tenant_id=TENANT_B,
        ))

        self.assertFalse(result["ok"])
        # Same answer as a genuinely missing case, so the id cannot be probed.
        self.assertEqual("case not found", result["error"])

        # And the real case is untouched.
        case = _run(self.store.get_case("CASE-A1", tenant_id=TENANT_A))
        self.assertEqual("PENDING_HUMAN", case["state"])

    def test_the_owning_tenant_can_still_decide(self):
        """
        The negative test above passes if human_decide is simply broken, so the
        positive case is asserted alongside it.
        """
        from vf_logistics import orchestrator

        result = _run(orchestrator.human_decide(
            "CASE-A1", "block", "reviewer-a", "sanctioned consignee",
            tenant_id=TENANT_A,
        ))
        self.assertTrue(result["ok"], result.get("error"))
        case = _run(self.store.get_case("CASE-A1", tenant_id=TENANT_A))
        self.assertEqual("BLOCKED_BY_HUMAN", case["state"])

    def test_deep_review_cannot_spend_tokens_on_another_tenants_case(self):
        from vf_logistics import orchestrator

        result = _run(orchestrator.deep_review("CASE-A1", tenant_id=TENANT_B))
        self.assertFalse(result["ok"])
        self.assertEqual("case not found", result["error"])


class PrefilterRuleIsolationTests(unittest.TestCase):
    """
    Pre-filter rules used to be verifier.py module globals rebound in place.

    That made them the one control in the system with no tenant at all: a
    governance admin editing their blacklist changed what every other customer's
    shipments were screened against, with no audit record on the affected
    tenants. The assertion that matters is not that the rules are stored
    separately but that they produce different verdicts.
    """

    def setUp(self):
        self.env = patch.dict(os.environ, {
            "MULTI_TENANT": "true", "STORE_BACKEND": "memory",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.store = MemoryStore()

    def test_rules_are_stored_per_tenant(self):
        _run(self.store.put_prefilter_rules(
            {"blacklist_companies": ["acme trading"]}, tenant_id=TENANT_A,
        ))
        self.assertIsNotNone(
            _run(self.store.get_prefilter_rules(tenant_id=TENANT_A))
        )
        self.assertIsNone(
            _run(self.store.get_prefilter_rules(tenant_id=TENANT_B)),
            "tenant B read tenant A's screening rules",
        )

    def test_a_tenants_blacklist_edit_does_not_change_another_tenants_verdict(self):
        """
        The end-to-end version of the same fact, through verifier.validate().

        Asserted on the verdict rather than on storage because storage being
        separate is worth nothing if the check function still reads a global.
        """
        from vf_logistics import verifier

        shipment = {
            "shipper_company": "Acme Trading",
            "shipper_tax_id": "0301234567",
            "origin": "ho chi minh city",
            "destination": "hanoi",
            "declared_value": 50_000,
            "shipping_cost": 1_500,
        }

        rules_a, errors = verifier.apply_prefilter_update(
            verifier.PrefilterRules.defaults(),
            {"blacklist_companies": ["acme trading"]},
        )
        self.assertEqual([], errors)
        rules_b = verifier.PrefilterRules.defaults()

        blocked = verifier.validate(
            shipment, screen_sanctions=False, rules=rules_a,
        )
        clean = verifier.validate(
            shipment, screen_sanctions=False, rules=rules_b,
        )

        codes_a = {f["code"] for f in blocked["findings"]}
        codes_b = {f["code"] for f in clean["findings"]}

        self.assertIn("BLACKLIST_MATCH", codes_a)
        self.assertNotIn(
            "BLACKLIST_MATCH", codes_b,
            "tenant A's blacklist entry decided tenant B's shipment",
        )

    def test_defaults_are_returned_for_a_tenant_that_never_saved_any(self):
        from vf_logistics import verifier

        rules = verifier.PrefilterRules.from_dict(
            _run(self.store.get_prefilter_rules(tenant_id=TENANT_B))
        )
        self.assertEqual(verifier.PrefilterRules.defaults(), rules)

    def test_a_partial_update_leaves_the_other_lists_alone(self):
        """
        The governance screen edits one list at a time. An update that reset the
        four keys it did not mention would quietly restore a blacklist entry a
        customer had removed.
        """
        from vf_logistics import verifier

        base = verifier.PrefilterRules.defaults()
        updated, errors = verifier.apply_prefilter_update(
            base, {"low_value_threshold_usd": 250},
        )
        self.assertEqual([], errors)
        self.assertEqual(250, updated.low_value_threshold_usd)
        self.assertEqual(base.blacklist_companies, updated.blacklist_companies)
        self.assertEqual(base.vip_registry, updated.vip_registry)
        self.assertEqual(base.safe_routes, updated.safe_routes)

    def test_an_invalid_key_applies_nothing(self):
        """
        All or nothing. The previous implementation applied each valid key as it
        went and reported errors afterwards, so a request with one bad field left
        a half-applied rule set behind an error response.
        """
        from vf_logistics import verifier

        base = verifier.PrefilterRules.defaults()
        updated, errors = verifier.apply_prefilter_update(
            base,
            {
                "blacklist_companies": ["legitimately added"],
                "low_value_threshold_usd": "not a number",
            },
        )
        self.assertIsNone(updated)
        self.assertTrue(errors)

    def test_rules_are_immutable(self):
        """
        A check function handed a mutable rule set could edit it, and then whether
        a shipment cleared would depend on which checks had already run against
        the same object.
        """
        import dataclasses

        from vf_logistics import verifier

        rules = verifier.PrefilterRules.defaults()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            rules.low_value_threshold_usd = 999  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
