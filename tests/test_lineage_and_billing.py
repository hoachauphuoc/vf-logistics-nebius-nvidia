"""
Modules 1 and 5: data lineage and per-tenant cost attribution.

The test that matters most here is
test_audit_record_contains_no_commercial_payload.

The reason is a conflict that only surfaces at the worst moment.
store.update_audit() and delete_audit() raise AuditImmutabilityError on both
backends, deliberately -- an audit trail you can edit is not one. But a customer
terminating their contract is entitled to have their commercial data removed, and
supplier prices and counterparty relationships sitting in an undeletable log is a
problem with no clean exit.

The resolution is that the immutable record holds only hashes, ids and codes,
while the payload lives on the case document and in GCS, both of which are
deletable per tenant. If a future change puts a cargo description or a raw model
reply back into the audit record, that test fails -- and it should, because the
alternative is discovering the problem during an erasure request.
"""

from __future__ import annotations

import asyncio
import json
import os
import unittest

os.environ.setdefault("STORE_BACKEND", "memory")

from vf_logistics import lineage  # noqa: E402
from vf_logistics import tenant as tenant_mod  # noqa: E402
from vf_logistics.store import MemoryStore, utcnow  # noqa: E402


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


SECRET_CARGO = "Cotton t-shirts, 500 cartons, buyer margin 18 percent"
SECRET_SHIPPER = "Mekong Garment Export Joint Stock Company"
SECRET_PROMPT = "SYSTEM PROMPT v1 confidential internal wording " + ("x" * 500)
SECRET_REPLY = '{"compliance_status": "CLEARED", "internal_note": "known buyer"}'


def _decided_case() -> dict:
    """A case carrying every kind of sensitive value the audit must not keep."""
    return {
        "case_id": "CASE-LIN-1",
        "shipment_id": "SHIP-1",
        "client_reference": "ERP-REF-1",
        "state": "AUTO_CLEARED",
        "risk_score": 12,
        "created_at": utcnow(),
        "shipment": {
            "shipment_id": "SHIP-1",
            "cargo_description": SECRET_CARGO,
            "shipper_company": SECRET_SHIPPER,
            "declared_value": 18000,
        },
        "reconciliation": {
            "model_risk": 12, "risk_floor": 0, "score_disputed": False,
        },
        "validation": {
            "risk_floor": 0,
            "findings": [
                {
                    "code": "DUAL_USE_HS_CODE", "severity": "CRITICAL", "floor": 85,
                    "detail": f"Shipment of {SECRET_CARGO} looks controlled",
                    "measured": {"source_entity_ids": ["OFAC-SDN-12345"]},
                },
                {
                    "code": "FREIGHT_RATIO_LOW", "severity": "MEDIUM", "floor": 45,
                    "detail": "arithmetic, no external authority to cite",
                    "measured": {"ratio": 0.02},
                },
            ],
        },
        "sanctions_snapshot": {
            "version": 7,
            "synced_at": "2026-09-14T00:00:00+00:00",
            "age_days": 6,
            "source": "opensanctions",
        },
        "boundary": {"version": 3},
        "steps": [
            {
                "agent": "fraud_detection",
                "model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
                "prompt": SECRET_PROMPT,
                "prompt_sha256": "a" * 64,
                "raw_response": SECRET_REPLY,
                "input_tokens": 1200,
                "output_tokens": 400,
                "latency_ms": 900,
                "at": utcnow(),
                "parse_error": False,
            },
            {
                "agent": "investigation",
                "model": "nvidia/nemotron-3-super-120b-a12b",
                "prompt_sha256": "b" * 64,
                "raw_response": SECRET_REPLY,
                "input_tokens": 2000,
                "output_tokens": 900,
                "latency_ms": 4000,
                "at": utcnow(),
                "parse_error": False,
            },
        ],
    }


class DecisionRecordTests(unittest.TestCase):
    def setUp(self):
        self.record = lineage.build_decision_record(
            _decided_case(), "agent_decision", outcome="AUTO_CLEARED",
        )

    def test_audit_record_contains_no_commercial_payload(self):
        """
        The immutable record must survive a tenant erasure request. If it holds
        the customer's cargo descriptions, counterparty names, prompt text or raw
        model replies, it cannot -- and update/delete both raise, so there is no
        way to redact it afterwards.
        """
        blob = json.dumps(self.record)
        for secret, label in (
            (SECRET_CARGO, "cargo description"),
            (SECRET_SHIPPER, "shipper name"),
            (SECRET_PROMPT, "prompt text"),
            (SECRET_REPLY, "raw model reply"),
        ):
            self.assertNotIn(
                secret, blob,
                f"the {label} is in the immutable audit record and could never "
                f"be deleted for a departing customer",
            )

    def test_finding_detail_text_is_not_kept(self):
        """Detail strings interpolate shipment specifics; the code plus the
        source entity id is what an auditor cites."""
        self.assertNotIn("looks controlled", json.dumps(self.record))
        self.assertIn("DUAL_USE_HS_CODE", self.record["finding_codes"])

    def test_source_entity_ids_are_carried(self):
        """
        The field that turns "flagged as high risk" into "matched OFAC SDN entry
        12345" -- the difference between an answer and an assertion.
        """
        self.assertEqual(self.record["source_entity_ids"], ["OFAC-SDN-12345"])

    def test_arithmetic_findings_contribute_no_entity_ids(self):
        """A freight ratio has no external authority to cite, correctly."""
        self.assertEqual(len(self.record["source_entity_ids"]), 1)

    def test_sanctions_staleness_is_recorded_not_implied(self):
        """A verdict is only as good as the list behind it, and a weekly refresh
        means this legitimately reads up to 7."""
        self.assertEqual(self.record["sanctions_list_age_days"], 6)
        self.assertEqual(self.record["sanctions_synced_at"], "2026-09-14T00:00:00+00:00")
        self.assertEqual(self.record["sanctions_list_version"], 7)

    def test_prompt_and_response_hashes_are_kept(self):
        """Enough to prove a produced copy is the one that ran, without holding
        the copy."""
        by_agent = {s["agent"]: s for s in self.record["steps"]}
        self.assertEqual(by_agent["fraud_detection"]["prompt_sha256"], "a" * 64)
        self.assertEqual(len(by_agent["fraud_detection"]["raw_response_excerpt_sha256"]), 64)

    def test_hash_of_absent_text_is_none_not_the_hash_of_nothing(self):
        """sha256("") is a real-looking digest and would read as evidence that
        something existed."""
        self.assertIsNone(lineage.sha256_of(None))
        self.assertIsNone(lineage.sha256_of(""))

    def test_per_model_pricing_not_the_selected_model_rate(self):
        """
        The pipeline mixes models on purpose -- investigation runs on Super at
        five times Nano's input rate. Pricing every step at the registry's
        current model would misreport the bill in whichever direction the
        selection happened to point.
        """
        by_agent = {s["agent"]: s for s in self.record["steps"]}
        nano = by_agent["fraud_detection"]["cost_usd"]
        super_ = by_agent["investigation"]["cost_usd"]
        self.assertGreater(
            super_, nano * 3,
            "the Super step must be priced at Super's rate",
        )

    def test_usage_totals_match_the_sum_of_steps(self):
        usage = self.record["usage"]
        self.assertEqual(usage["agent_calls"], 2)
        self.assertEqual(usage["input_tokens"], 3200)
        self.assertEqual(usage["output_tokens"], 1300)
        self.assertAlmostEqual(
            usage["cost_usd"],
            sum(s["cost_usd"] for s in self.record["steps"]),
            places=8,
        )

    def test_evidence_references_survive_deletion_of_the_evidence(self):
        """The trail can still say what evidence existed after it is gone."""
        refs = self.record["evidence_refs"]
        self.assertEqual(refs["case_document"], "CASE-LIN-1")
        self.assertIn("deleted", refs["note"])

    def test_schema_version_is_stamped(self):
        """A record read years later was written by code nobody has looked at;
        a reader needs to know the shape before parsing."""
        self.assertEqual(self.record["lineage_version"], lineage.LINEAGE_VERSION)

    def test_actor_defaults_to_agent_but_records_a_human(self):
        """The trail must distinguish a reviewer's judgement from the agent's."""
        self.assertEqual(self.record["actor"], "agent")
        human = lineage.build_decision_record(
            _decided_case(), "human_release", actor="alice@customer.example",
        )
        self.assertEqual(human["actor"], "alice@customer.example")


class RecordDecisionPersistenceTests(unittest.TestCase):
    def test_record_is_written_under_the_tenant(self):
        store = MemoryStore()
        import vf_logistics.store as store_mod

        store_mod._store = store
        try:
            record = _run(lineage.record_decision(
                _decided_case(), "agent_decision", tenant_id="acme-freight",
            ))
            stored = _run(store.list_audit(tenant_id="acme-freight"))
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0]["audit_id"], record["audit_id"])
            # And invisible to another tenant.
            self.assertEqual(_run(store.list_audit(tenant_id="globex")), [])
        finally:
            store_mod._store = None

    def test_the_record_cannot_be_edited_or_deleted(self):
        """The immutability that makes the payload split necessary."""
        from vf_logistics.store import AuditImmutabilityError

        store = MemoryStore()
        _run(store.add_audit({"audit_id": "AUD-1", "at": utcnow()}))
        with self.assertRaises(AuditImmutabilityError):
            _run(store.update_audit("AUD-1", {"risk_score": 0}))
        with self.assertRaises(AuditImmutabilityError):
            _run(store.delete_audit("AUD-1"))


class TenantUsageTests(unittest.TestCase):
    def setUp(self):
        import vf_logistics.store as store_mod

        self.store_mod = store_mod
        self.store = MemoryStore()
        store_mod._store = self.store

    def tearDown(self):
        self.store_mod._store = None

    def _case(self, cid, tenant, cleared_by, cost):
        return {
            "case_id": cid, "state": "AUTO_CLEARED", "created_at": utcnow(),
            "cleared_by": cleared_by, "_agent_calls": 2,
            "_input_tokens": 1000, "_output_tokens": 500,
            "_estimated_cost_usd": cost, "_sum_latency_ms": 100,
        }

    def test_usage_is_scoped_to_the_tenant(self):
        _run(self.store.put_case(
            self._case("C-A1", "a", "ai", 0.002), tenant_id="acme-freight",
        ))
        _run(self.store.put_case(
            self._case("C-B1", "b", "ai", 0.009), tenant_id="globex",
        ))

        acme = _run(lineage.tenant_usage("acme-freight"))
        self.assertAlmostEqual(acme["estimated_cost_usd"], 0.002, places=6)
        self.assertEqual(acme["input_tokens"], 1000)

    def test_missing_tenant_raises_rather_than_invoicing_default(self):
        """
        require_tenant(), not resolve(). Attributing spend to "default" would
        produce an invoice that is plausible and wrong, which is worse than an
        error.
        """
        for bad in (None, "", "   "):
            with self.assertRaises(tenant_mod.TenantError):
                _run(lineage.tenant_usage(bad))

    def test_rules_versus_ai_split_is_the_unit_economics_number(self):
        """
        A shipment the deterministic checks settle costs no tokens, so the ratio
        decides whether a customer is profitable to serve.
        """
        _run(self.store.put_case(
            self._case("C-1", "a", "rules", 0.0), tenant_id="acme-freight",
        ))
        _run(self.store.put_case(
            self._case("C-2", "a", "ai", 0.002), tenant_id="acme-freight",
        ))
        usage = _run(lineage.tenant_usage("acme-freight"))
        self.assertEqual(usage["cleared_by_rules"], 1)
        self.assertEqual(usage["cleared_by_ai"], 1)
        self.assertEqual(usage["auto_cleared"], 2)

    def test_cost_per_call_does_not_divide_by_zero(self):
        usage = _run(lineage.tenant_usage("empty-tenant"))
        self.assertEqual(usage["agent_calls"], 0)
        self.assertEqual(usage["cost_per_call_usd"], 0.0)


if __name__ == "__main__":
    unittest.main()
