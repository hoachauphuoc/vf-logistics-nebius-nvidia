"""
The Today and Outcomes read models (worklist.py) and the activity they feed on.

WHY THIS FILE EXISTS

Plan 2 of the restructure proposal: the console's operator screens group and
count on the server so the numbers are the store's, not one page's. These tests
pin the grouping rules (the distinction that matters is PENDING_HUMAN after a
"Request info" -- waiting on the shipper -- against PENDING_HUMAN for any other
reason -- waiting on a reviewer), the outcome arithmetic, and who may record
handling time.

Class names use the `Test*` prefix: see test_console_session.py for why.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics import store as store_mod  # noqa: E402
from vf_logistics import worklist  # noqa: E402
from test_console_session import TEST_KEY, TEST_SECRET, mint  # noqa: E402

REVIEWER = "reviewer@forwarder.example"
ENV = {
    "VF_API_KEY": TEST_KEY,
    "VF_SESSION_SECRET": TEST_SECRET,
    "IAP_ENABLED": "false",
    "MULTI_TENANT": "false",
    "ANONYMOUS_ROLE": "viewer",
    "STORE_BACKEND": "memory",
    "REVIEWER_EMAILS": REVIEWER,
}


def review(action: str, state_after: str, at: str, reviewer: str = REVIEWER, note: str = "") -> dict:
    return {"action": action, "reviewer": reviewer, "note": note, "at": at, "state_after": state_after}


def case(case_id: str, state: str, **extra) -> dict:
    base = {
        "case_id": case_id, "shipment_id": case_id.replace("CASE-", ""), "state": state,
        "created_at": "2026-10-12T01:00:00+00:00", "updated_at": "2026-10-12T02:00:00+00:00",
        "actions": [], "reviews": [],
    }
    base.update(extra)
    return base


ASSIGNED = [{"action": "assign_analyst", "status": "done",
             "detail": {"queue": "compliance", "priority": "HIGH", "sla_hours": 24}}]


class TestWhatEachCaseIsWaitingFor(unittest.TestCase):
    def test_a_request_for_information_waits_on_the_shipper(self):
        c = case("CASE-1", "PENDING_HUMAN", reviews=[
            review("request_info", "PENDING_HUMAN", "2026-10-12T03:00:00+00:00", note="Certificate of origin"),
        ])
        self.assertEqual(worklist.bucket_for(c), "awaiting_documents")
        self.assertEqual(worklist.next_action(c)["code"], "chase_documents")
        self.assertIn("Certificate of origin", worklist.next_action(c)["text"])
        self.assertEqual(worklist.waiting_since(c), "2026-10-12T03:00:00+00:00")

    def test_a_case_parked_by_the_boundary_waits_on_a_reviewer(self):
        c = case("CASE-2", "PENDING_HUMAN", gate_denials=[{"action": "release_shipment"}])
        self.assertEqual(worklist.bucket_for(c), "awaiting_review")
        self.assertEqual(worklist.next_action(c)["code"], "decide_refused_action")
        self.assertIn("release_shipment", worklist.next_action(c)["text"])

    def test_held_escalated_and_the_verification_states(self):
        self.assertEqual(worklist.bucket_for(case("C", "HELD_FOR_REVIEW")), "awaiting_review")
        self.assertEqual(worklist.bucket_for(case("C", "ESCALATED")), "awaiting_sign_off")
        self.assertEqual(worklist.bucket_for(case("C", "AWAITING_EVIDENCE")), "awaiting_documents")
        self.assertEqual(worklist.bucket_for(case("C", "APPROVED")), "awaiting_execution")

    def test_finished_and_in_flight_cases_are_nobodys_work(self):
        for state in ("AUTO_CLEARED", "RELEASED_BY_HUMAN", "BLOCKED_BY_HUMAN", "INGESTED", "DEAD_LETTER"):
            with self.subTest(state=state):
                self.assertIsNone(worklist.bucket_for(case("C", state)))
                self.assertIsNone(worklist.next_action(case("C", state)))

    def test_a_later_decision_ends_the_wait_for_documents(self):
        """Asked for documents, then a reviewer moved it on: no longer waiting on the shipper."""
        c = case("CASE-3", "HELD_FOR_REVIEW", reviews=[
            review("request_info", "PENDING_HUMAN", "2026-10-12T03:00:00+00:00"),
        ])
        self.assertEqual(worklist.bucket_for(c), "awaiting_review")

    def test_the_next_action_names_the_dispute_and_the_findings(self):
        disputed = case("C", "HELD_FOR_REVIEW", reconciliation={
            "score_disputed": True, "model_risk": 20, "risk_floor": 65,
        })
        self.assertEqual(worklist.next_action(disputed)["code"], "settle_dispute")
        self.assertIn("65", worklist.next_action(disputed)["text"])
        found = case("C", "HELD_FOR_REVIEW", validation={"findings": [
            {"code": "VALUE_DENSITY_LOW", "floor": 45}, {"code": "DUAL_USE_HS_CODE", "floor": 70},
        ]})
        action = worklist.next_action(found)
        self.assertEqual(action["code"], "review_findings")
        self.assertIn("DUAL_USE_HS_CODE and 1 more", action["text"])

    def test_sign_off_mentions_a_sar_waiting_for_a_signature(self):
        c = case("C", "ESCALATED", actions=[{"action": "draft_sar", "status": "done"}])
        self.assertIn("SAR", worklist.next_action(c)["text"])


class TestWhoHoldsTheCase(unittest.TestCase):
    def test_the_last_person_beats_the_queue(self):
        c = case("C", "PENDING_HUMAN", actions=ASSIGNED, reviews=[
            review("request_info", "PENDING_HUMAN", "2026-10-12T03:00:00+00:00", reviewer="ana@x.example"),
        ])
        self.assertEqual(worklist.owner_of(c), {"kind": "person", "name": "ana@x.example"})

    def test_the_queue_the_agent_routed_it_to(self):
        self.assertEqual(
            worklist.owner_of(case("C", "HELD_FOR_REVIEW", actions=ASSIGNED)),
            {"kind": "queue", "name": "compliance"},
        )

    def test_nobody_is_said_plainly(self):
        self.assertEqual(worklist.owner_of(case("C", "HELD_FOR_REVIEW"))["kind"], "unassigned")

    def test_the_due_time_comes_from_the_routing_sla(self):
        item = worklist.work_item(case("C", "HELD_FOR_REVIEW", actions=ASSIGNED))
        self.assertEqual(item["sla_hours"], 24)
        self.assertTrue(item["due_at"].startswith("2026-10-13T02:00:00"))


class TestGrouping(unittest.TestCase):
    def test_counts_cover_every_case_and_the_most_urgent_comes_first(self):
        cases = [case(f"CASE-{i}", "HELD_FOR_REVIEW", risk_score=i) for i in range(60)]
        cases.append(case("CASE-DOC", "PENDING_HUMAN", reviews=[
            review("request_info", "PENDING_HUMAN", "2026-10-12T03:00:00+00:00"),
        ]))
        grouped = worklist.group_work(cases)
        self.assertEqual(grouped["awaiting_review"]["count"], 60)
        self.assertEqual(len(grouped["awaiting_review"]["items"]), worklist.ITEMS_PER_BUCKET)
        self.assertEqual(grouped["awaiting_review"]["items"][0]["risk_score"], 59)
        self.assertEqual(grouped["awaiting_documents"]["count"], 1)
        self.assertEqual(grouped["awaiting_sign_off"]["count"], 0)

    def test_an_item_is_a_projection_not_the_case(self):
        item = worklist.work_item(case("C", "HELD_FOR_REVIEW", shipment={"shipper_tax_id": "X"}))
        self.assertNotIn("shipment", item)
        self.assertNotIn("steps", item)


class TestOutcomeArithmetic(unittest.TestCase):
    def test_percentile_is_nearest_rank_and_none_when_empty(self):
        self.assertIsNone(worklist.percentile([], 0.5))
        self.assertEqual(worklist.percentile([5.0], 0.95), 5.0)
        self.assertEqual(worklist.percentile([1.0, 2.0, 3.0, 4.0], 0.5), 2.0)
        self.assertEqual(worklist.percentile([float(i) for i in range(1, 101)], 0.95), 95.0)

    def test_resolved_cases_are_counted_by_how_and_timed_from_arrival(self):
        released = case("CASE-R", "RELEASED_BY_HUMAN", _estimated_cost_usd=0.004, _sum_latency_ms=9000,
                        reviews=[
                            review("request_info", "PENDING_HUMAN", "2026-10-12T02:00:00+00:00"),
                            review("release", "RELEASED_BY_HUMAN", "2026-10-12T05:00:00+00:00"),
                        ])
        auto = case("CASE-A", "AUTO_CLEARED", cleared_by="rules", _estimated_cost_usd=0.0,
                    updated_at="2026-10-12T01:00:05+00:00")
        out = worklist.summarise_outcomes(
            [released, auto], {"CASE-R": 95_000}, {"HELD_FOR_REVIEW": 3, "ESCALATED": 1}, refused=2,
        )
        self.assertEqual(out["resolved"]["total"], 2)
        self.assertEqual(out["resolved"]["by"]["released_by_reviewer"], 1)
        self.assertEqual(out["resolved"]["by"]["cleared_by_rules"], 1)
        # 01:00 -> 05:00 is four hours; 01:00:00 -> 01:00:05 is five seconds.
        self.assertEqual(out["time_to_resolution_ms"]["n"], 2)
        self.assertEqual(out["time_to_resolution_ms"]["p95"], 4 * 3600 * 1000)
        self.assertEqual(out["information_rounds"]["total"], 1)
        self.assertEqual(out["information_rounds"]["cases_with_rounds"], 1)
        self.assertEqual(out["human_handling_ms"]["n"], 1)
        self.assertEqual(out["human_handling_ms"]["total"], 95_000)
        self.assertEqual(out["human_handling_ms"]["of_human_resolved"], 1)
        self.assertEqual(out["cost_per_resolved_usd"]["total"], 0.004)
        self.assertEqual(out["held_now"]["total"], 4)
        self.assertEqual(out["refused_actions"]["total"], 2)

    def test_what_was_not_measured_is_none_not_zero(self):
        out = worklist.summarise_outcomes([], {}, {}, refused=0)
        self.assertIsNone(out["time_to_resolution_ms"]["median"])
        self.assertIsNone(out["cost_per_resolved_usd"]["mean"])
        self.assertIsNone(out["information_rounds"]["mean_per_resolved"])
        self.assertIsNone(out["external_wait_ms"]["value"])
        self.assertTrue(out["external_wait_ms"]["reason"])

    def test_a_case_without_a_cost_rollup_is_left_out_of_the_cost_figures(self):
        out = worklist.summarise_outcomes(
            [case("C", "AUTO_CLEARED"), case("D", "AUTO_CLEARED", _estimated_cost_usd=0.01)], {}, {}, 0,
        )
        self.assertEqual(out["cost_per_resolved_usd"]["n"], 1)


class _RouteCase(unittest.TestCase):
    def setUp(self):
        from vf_logistics import app as app_mod

        self.env = patch.dict(os.environ, ENV)
        self.env.start()
        self.addCleanup(self.env.stop)
        store_mod._store = None
        self.addCleanup(setattr, store_mod, "_store", None)
        limiter_was = app_mod.limiter.enabled
        app_mod.limiter.enabled = False
        self.addCleanup(setattr, app_mod.limiter, "enabled", limiter_was)
        self.client = app_mod.app.test_client()
        self.store = store_mod.get_store()

    def put(self, c: dict) -> None:
        asyncio.run(self.store.put_case(c))

    def reviewer(self) -> dict:
        return {"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint(REVIEWER, amr="password")}


class TestTheWorklistRoute(_RouteCase):
    def test_groups_the_tenants_waiting_cases(self):
        self.put(case("CASE-H", "HELD_FOR_REVIEW", created_at="2026-10-12T01:00:00+00:00"))
        self.put(case("CASE-D", "PENDING_HUMAN", created_at="2026-10-12T01:01:00+00:00", reviews=[
            review("request_info", "PENDING_HUMAN", "2026-10-12T03:00:00+00:00"),
        ]))
        self.put(case("CASE-X", "AUTO_CLEARED", created_at="2026-10-12T01:02:00+00:00"))
        body = self.client.get("/api/v1/worklist").get_json()
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["buckets"]["awaiting_review"]["items"][0]["case_id"], "CASE-H")
        self.assertEqual(body["buckets"]["awaiting_documents"]["items"][0]["case_id"], "CASE-D")
        self.assertFalse(body["truncated"])

    def test_a_scan_past_the_limit_says_so(self):
        for i in range(5):
            self.put(case(f"CASE-{i}", "HELD_FOR_REVIEW", created_at=f"2026-10-12T01:0{i}:00+00:00"))
        with patch.object(worklist, "SCAN_LIMIT", 3), patch.object(worklist, "PAGE", 2):
            body = self.client.get("/api/v1/worklist").get_json()
        self.assertEqual(body["scanned"], 3)
        self.assertTrue(body["truncated"])


class TestTheOutcomesRoute(_RouteCase):
    def test_reports_resolved_cases_and_handling_time(self):
        self.put(case("CASE-R", "RELEASED_BY_HUMAN", created_at="2026-10-12T01:00:00+00:00", reviews=[
            review("release", "RELEASED_BY_HUMAN", "2026-10-12T01:30:00+00:00"),
        ]))
        asyncio.run(self.store.add_activity("CASE-R", REVIEWER, 40_000))
        asyncio.run(self.store.add_activity("CASE-R", REVIEWER, 20_000))
        body = self.client.get("/api/v1/outcomes").get_json()
        self.assertEqual(body["resolved"]["by"]["released_by_reviewer"], 1)
        self.assertEqual(body["human_handling_ms"]["total"], 60_000)

    def test_the_window_bounds_by_creation(self):
        self.put(case("CASE-OLD", "AUTO_CLEARED", created_at="2026-09-01T00:00:00+00:00"))
        self.put(case("CASE-NEW", "AUTO_CLEARED", created_at="2026-10-12T00:00:00+00:00"))
        body = self.client.get("/api/v1/outcomes?since=2026-10-01T00:00:00Z").get_json()
        self.assertEqual(body["resolved"]["total"], 1)
        body = self.client.get("/api/v1/outcomes?until=2026-10-01T00:00:00Z").get_json()
        self.assertEqual(body["resolved"]["total"], 1)

    def test_a_malformed_window_is_refused(self):
        self.assertEqual(self.client.get("/api/v1/outcomes?since=yesterday").status_code, 400)


class TestRecordingActivity(_RouteCase):
    def setUp(self):
        super().setUp()
        self.put(case("CASE-1", "HELD_FOR_REVIEW"))

    def post(self, body: dict, headers: dict | None = None, case_id: str = "CASE-1"):
        return self.client.post(f"/api/v1/cases/{case_id}/activity", json=body,
                                headers=headers if headers is not None else self.reviewer())

    def test_a_reviewer_s_time_is_recorded_against_the_session_not_the_body(self):
        response = self.post({"active_ms": 30_000, "actor": "someone-else@x.example"})
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        rows = asyncio.run(self.store.list_activity())
        self.assertEqual([(r["actor"], r["active_ms"]) for r in rows], [(REVIEWER, 30_000)])

    def test_who_may_not_record(self):
        cases = {
            "anonymous": ({}, 403),
            "the key alone, no person": ({"X-VF-API-Key": TEST_KEY}, 403),
            "a viewer": ({"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint("nobody@x.example")}, 403),
        }
        for label, (headers, want) in cases.items():
            with self.subTest(caller=label):
                self.assertEqual(self.post({"active_ms": 1000}, headers=headers).status_code, want)
        self.assertEqual(asyncio.run(self.store.list_activity()), [])

    def test_implausible_reports_are_refused(self):
        for value in (0, -5, 120_001, "30000", True, None, 1.5):
            with self.subTest(active_ms=value):
                self.assertEqual(self.post({"active_ms": value}).status_code, 400)

    def test_a_case_of_nobody_s_is_not_found(self):
        self.assertEqual(self.post({"active_ms": 1000}, case_id="CASE-NOPE").status_code, 404)


if __name__ == "__main__":
    unittest.main()
