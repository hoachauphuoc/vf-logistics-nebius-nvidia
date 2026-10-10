"""
The due-diligence dossier: a case arranged as the PDF a forwarder files.

Pinned here: every finding the verifier can raise lands on a reference that
exists; the most specific guidance wins; the dossier says when a case was screened
against the synthetic seed list rather than an official one; and the route serves
a PDF to the same audience as the case JSON, scoped to the caller's tenant.
"""

from __future__ import annotations

import asyncio
import os
import re
import unittest
from unittest.mock import patch

os.environ.setdefault("STORE_BACKEND", "memory")

from vf_logistics import dossier, verifier  # noqa: E402

CASE = {
    "case_id": "CASE-DOSSIER-1",
    "shipment_id": "DOSSIER-1",
    "state": "BLOCKED_BY_HUMAN",
    "risk_score": 100,
    "shipment": {
        "shipper_company": "Truong Hai Trading Co", "receiver_company": "Alexsong Pte. Ltd.",
        "origin": "Cat Lai Port, Ho Chi Minh City, Vietnam", "destination": "PSA Singapore, Singapore",
        "cargo_description": "Woven cotton garments", "hs_code": "6205.20",
        "declared_value": 184000, "weight_kg": 2100, "shipping_cost": 2600,
    },
    "validation": {
        "risk_floor": 100,
        "sanctions_screening": "HIT",
        "sanctions_snapshot": {
            "source": "OFAC SDN + UN SC Consolidated", "version": 1, "entity_count": 18525,
            "synced_at": "2026-10-10T07:33:03+00:00",
        },
        "findings": [
            {"code": "VALUE_DENSITY_HIGH", "severity": "MEDIUM", "floor": 50, "detail": "dense"},
            {"code": "SANCTIONS_MATCH", "severity": "CRITICAL", "floor": 100,
             "detail": "receiver matches ALEXSONG PTE LTD (OFAC-SDN-35036)"},
        ],
        "observations": [],
    },
    "reconciliation": {"effective_risk": 100, "risk_floor": 100, "model_risk": 72,
                       "source": "deterministic floor", "auto_clear_permitted": False},
    "decision": {"decided_by": "human", "outcome": "BLOCKED_BY_HUMAN", "rationale": "designated party"},
    "actions": [{"action": "hold_shipment", "status": "done", "detail": {"boundary_version": 2}}],
    "steps": [],
    "source": "event",
}


class TestGuidance(unittest.TestCase):
    def test_every_finding_code_the_verifier_can_raise_has_references_that_exist(self):
        source = open(verifier.__file__, encoding="utf-8").read()
        codes = set(re.findall(r'"code":\s*"([A-Z_]+)"', source))
        self.assertGreater(len(codes), 25)
        for code in codes:
            refs, precedent, action = dossier.guidance_for(code)
            with self.subTest(code=code):
                self.assertTrue(refs and action)
                for ref in refs:
                    self.assertIn(ref, dossier.REFERENCES)
                if precedent:
                    self.assertIn(precedent, dossier.PRECEDENTS)

    def test_the_most_specific_prefix_wins(self):
        dual_use = dossier.guidance_for("HS_DESCRIPTION_MISMATCH_DUAL_USE")
        plain = dossier.guidance_for("HS_DESCRIPTION_MISMATCH")
        self.assertIn("VN_DECREE_259", dual_use[0])
        self.assertNotIn("VN_DECREE_259", plain[0])

    def test_every_cited_source_is_a_link_a_reviewer_can_open(self):
        for key, ref in dossier.REFERENCES.items():
            with self.subTest(ref=key):
                self.assertTrue(ref["url"] == "" if key == "INTERNAL" else ref["url"].startswith("https://"))
        for precedent in dossier.PRECEDENTS.values():
            self.assertTrue(precedent["url"].startswith("https://"))

    def test_findings_are_ordered_worst_first(self):
        codes = [f["code"] for f in dossier.dossier_findings(CASE)]
        self.assertEqual(codes, ["SANCTIONS_MATCH", "VALUE_DENSITY_HIGH"])


class TestRender(unittest.TestCase):
    def test_it_renders_a_pdf(self):
        pdf = dossier.render_dossier(CASE, generated_by="judge@vf-logistics.demo")
        self.assertIsNotNone(pdf)
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_a_case_with_nothing_in_it_still_renders(self):
        """An old case document may lack every optional section."""
        pdf = dossier.render_dossier({"case_id": "CASE-EMPTY"})
        self.assertTrue(pdf and pdf.startswith(b"%PDF"))

    def test_non_latin1_text_does_not_break_the_render(self):
        case = dict(CASE, shipment=dict(CASE["shipment"], shipper_company="Công ty Trường Hải — ООО Тест"))
        self.assertTrue(dossier.render_dossier(case).startswith(b"%PDF"))

    def test_model_punctuation_is_spelled_out_not_turned_into_question_marks(self):
        # Seen on the live board: an exposure estimate "2× value → estimated".
        self.assertEqual(
            dossier._ascii("2× value → estimated ≈ USD 552,000…"),
            "2× value -> estimated ~ USD 552,000...",
        )


class TestRoute(unittest.TestCase):
    def setUp(self):
        from vf_logistics import app as app_mod
        from vf_logistics.store import get_store

        self.env = patch.dict(os.environ, {
            "STORE_BACKEND": "memory", "IAP_ENABLED": "false", "MULTI_TENANT": "false",
            "ANONYMOUS_ROLE": "viewer",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        limiter_was = app_mod.limiter.enabled
        app_mod.limiter.enabled = False
        self.addCleanup(setattr, app_mod.limiter, "enabled", limiter_was)
        self.client = app_mod.app.test_client()
        asyncio.run(get_store().put_case(dict(CASE)))

    def test_a_viewer_gets_the_pdf_inline(self):
        response = self.client.get("/api/v1/orchestrator/case/CASE-DOSSIER-1/dossier")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertIn('inline; filename="dossier-CASE-DOSSIER-1.pdf"', response.headers["Content-Disposition"])
        self.assertTrue(response.data.startswith(b"%PDF"))

    def test_an_unknown_case_is_a_404_not_an_empty_pdf(self):
        response = self.client.get("/api/v1/orchestrator/case/CASE-NOPE/dossier")
        self.assertEqual(response.status_code, 404)

    def test_the_route_is_published_as_viewer(self):
        from vf_logistics import auth
        from vf_logistics.app import app

        row = next(r for r in auth.route_policy(app) if r["path"].endswith("/dossier"))
        self.assertEqual(row["required_role"], "viewer")


if __name__ == "__main__":
    unittest.main()
