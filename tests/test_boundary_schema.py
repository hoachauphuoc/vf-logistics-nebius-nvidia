"""
The delegation boundary's permissions schema, and the gate's reading of it.

WHY THIS FILE EXISTS

Finding A03 of the authorization review of bd6a210. `publish` checked only that
`permissions` was a non-empty object, and `_check_release()` read
`auto_release.permitted` by Python truthiness, so

    {"permissions": {"auto_release": {"permitted": "false"}}}

was stored with a 201 and then evaluated release_shipment as ALLOWED for a clean
case. The author's "do not allow" came out as "allow". A missing ceiling had the
same shape of problem: the check that read it was skipped, so a grant that forgot
a limit had none.

Two layers are pinned here, deliberately separately: publish and simulate refuse
a mistyped policy before anything is written, and the gate refuses one that is
already in a store (written before the schema existed).

Class names use the `Test*` prefix: see test_console_session.py for why.
"""

from __future__ import annotations

import asyncio
import copy
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics import governance  # noqa: E402
from vf_logistics import store as store_mod  # noqa: E402
from test_console_session import TEST_KEY, TEST_SECRET  # noqa: E402

ENV = {
    "VF_API_KEY": TEST_KEY,
    "VF_SESSION_SECRET": TEST_SECRET,
    "IAP_ENABLED": "false",
    "MULTI_TENANT": "false",
    "ANONYMOUS_ROLE": "viewer",
    "STORE_BACKEND": "memory",
}
KEY = {"X-VF-API-Key": TEST_KEY}

# BOUNDARY-v3 as served by the live service on 2026-10-11 (read with a GET). The
# schema must not refuse the policy production is running under.
LIVE_V3 = {
    "allowed_actions": [
        "assign_analyst", "draft_sar", "hold_shipment", "notify_webhook", "publish_decision",
    ],
    "auto_release": {
        "forbidden_destinations": ["belarus", "iran", "north korea", "pakistan", "russia", "syria"],
        "forbidden_hs_prefixes": [
            "2844", "8411", "8458", "8471", "8479", "8504", "8542", "9014", "9026", "9030",
        ],
        "max_declared_value_usd": 25000,
        "max_effective_risk": 39,
        "permitted": True,
        "require_zero_deterministic_findings": True,
    },
    "reason": "Published from the default template",
    "require_human_when": [
        "score_disputed", "injection_detected", "forbidden_field_attempted",
        "compliance_blocked", "exposure_claim_unsupported",
    ],
    "sar_filing": {"may_draft": True, "may_file": False},
}

# The review's test case: risk 1, declared value 1,000, no findings, auto-clear
# permitted. Every condition a valid grant checks is satisfied, so the only thing
# that decides the outcome is how `permitted` is read.
CLEAN_CASE = {
    "case_id": "CASE-A03",
    "risk_score": 1,
    "compliance_status": "CLEARED",
    "shipment": {"declared_value": 1000, "hs_code": "6205.20", "destination": "Hanoi"},
    "validation": {"finding_count": 0, "findings": []},
    "reconciliation": {"auto_clear_permitted": True, "score_disputed": False},
    "input_security": {"injection_screening": {"blocked": False}},
}


def _template() -> dict:
    return copy.deepcopy(governance.proposed_boundary("schema test"))


def _with_release(**changes) -> dict:
    perms = _template()
    perms["auto_release"].update(changes)
    return perms


def _without_release_key(key: str) -> dict:
    perms = _template()
    del perms["auto_release"][key]
    return perms


def _boundary(permissions: dict) -> dict:
    return {"boundary_id": "BOUNDARY-test", "version": 1, "status": "ACTIVE",
            "permissions": permissions}


class TestTheSchemaAcceptsWhatIsInUse(unittest.TestCase):
    """A schema that refused the live policy or the template would break the demo."""

    def test_the_template_is_valid(self):
        self.assertEqual(governance.validate_permissions(_template()), [])

    def test_the_live_boundary_is_valid(self):
        self.assertEqual(governance.validate_permissions(LIVE_V3), [])

    def test_explicitly_withholding_release_is_valid(self):
        self.assertEqual(
            governance.validate_permissions({"auto_release": {"permitted": False}}), []
        )

    def test_an_empty_action_list_is_valid(self):
        """A deny-everything policy is a legitimate one; who may publish it is A01's job."""
        self.assertEqual(governance.validate_permissions({"allowed_actions": []}), [])


class TestTheSchemaRefusesWhatWouldBeMisread(unittest.TestCase):
    """Each of these used to be stored, and several were read as wider than written."""

    CASES = {
        'permitted "false"': _with_release(permitted="false"),
        'permitted "true"': _with_release(permitted="true"),
        "permitted 0": _with_release(permitted=0),
        "permitted 1": _with_release(permitted=1),
        "permitted null": _with_release(permitted=None),
        "permitted missing": _without_release_key("permitted"),
        "risk ceiling missing": _without_release_key("max_effective_risk"),
        "value ceiling missing": _without_release_key("max_declared_value_usd"),
        "negative value ceiling": _with_release(max_declared_value_usd=-1),
        "risk ceiling above 100": _with_release(max_effective_risk=101),
        "risk ceiling as a string": _with_release(max_effective_risk="39"),
        "risk ceiling as a bool": _with_release(max_effective_risk=True),
        "findings flag as a string": _with_release(require_zero_deterministic_findings="false"),
        "HS prefix not 4 digits": _with_release(forbidden_hs_prefixes=["84"]),
        "destination in capitals": _with_release(forbidden_destinations=["Iran"]),
        "empty destination": _with_release(forbidden_destinations=[""]),
        "unknown auto_release key": _with_release(max_value_usd=10),
        "unknown top-level key": {**_template(), "auto_relase": {"permitted": False}},
        "unknown action": {"allowed_actions": ["delete_everything"]},
        "release listed as an action": {"allowed_actions": ["release_shipment"]},
        "duplicate action": {"allowed_actions": ["hold_shipment", "hold_shipment"]},
        "action list not a list": {"allowed_actions": "hold_shipment"},
        "unknown human trigger": {"require_human_when": ["when_it_feels_wrong"]},
        "filing delegated": {"sar_filing": {"may_draft": True, "may_file": True}},
        "drafting as a string": {"sar_filing": {"may_draft": "yes"}},
        "auto_release not an object": {"auto_release": True},
    }

    def test_each_is_refused_with_a_reason(self):
        for label, perms in self.CASES.items():
            with self.subTest(case=label):
                errors = governance.validate_permissions(perms)
                self.assertTrue(errors, f"{label} was accepted")
                self.assertTrue(all(isinstance(e, str) and e for e in errors))

    def test_every_error_is_reported_at_once(self):
        perms = _with_release(permitted="false", max_effective_risk=-5)
        perms["mystery"] = 1
        self.assertGreaterEqual(len(governance.validate_permissions(perms)), 3)


class TestPublishAndSimulateRefuseBeforeWriting(unittest.TestCase):
    """Through the real routes: 422, the reasons, and nothing stored."""

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

    def _stored(self) -> list[dict]:
        return asyncio.run(store_mod.get_store().list_boundaries(50))

    def test_the_review_payload_is_refused_and_not_stored(self):
        for value in ("false", "true", 0, 1):
            with self.subTest(permitted=value):
                response = self.client.post(
                    "/api/v1/governance/publish",
                    json={"permissions": {"auto_release": {"permitted": value}},
                          "author": "schema-test"},
                    headers=KEY,
                )
                self.assertEqual(response.status_code, 422, response.get_data(as_text=True))
                body = response.get_json()
                self.assertTrue(any("permitted" in d for d in body["details"]))
                self.assertEqual(self._stored(), [])

    def test_simulate_refuses_the_same_payload(self):
        response = self.client.post(
            "/api/v1/governance/simulate",
            json={"permissions": {"auto_release": {"permitted": "false"}}},
        )
        self.assertEqual(response.status_code, 422, response.get_data(as_text=True))
        self.assertTrue(response.get_json()["details"])

    def test_a_valid_withholding_publishes_and_release_is_denied(self):
        response = self.client.post(
            "/api/v1/governance/publish",
            json={"permissions": {"auto_release": {"permitted": False}}, "author": "schema-test"},
            headers=KEY,
        )
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        boundary = response.get_json()["boundary"]
        verdict = governance.check("release_shipment", CLEAN_CASE, boundary)
        self.assertFalse(verdict["allowed"])
        self.assertIn("not delegated", verdict["reason"])

    def test_the_template_still_publishes_and_still_releases_a_clean_case(self):
        """The allow path must survive: a gate that denies everything is not a fix."""
        response = self.client.post(
            "/api/v1/governance/publish", json={"author": "schema-test"}, headers=KEY,
        )
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        verdict = governance.check("release_shipment", CLEAN_CASE, response.get_json()["boundary"])
        self.assertTrue(verdict["allowed"], verdict["reason"])

    def test_the_function_refuses_too(self):
        """publish_boundary() is called directly by tests and scripts, not only by the route."""
        with self.assertRaises(governance.BoundaryValidationError) as raised:
            asyncio.run(governance.publish_boundary(
                {"auto_release": {"permitted": "false"}}, "schema-test", "",
            ))
        self.assertTrue(raised.exception.errors)
        self.assertEqual(self._stored(), [])


class TestTheGateReadsStoredPoliciesStrictly(unittest.TestCase):
    """Defence in depth for anything written before the schema existed."""

    def test_a_stored_string_false_does_not_release(self):
        """The exact reproduction from the review, now denied at the gate."""
        verdict = governance.check(
            "release_shipment", CLEAN_CASE,
            _boundary({"auto_release": {"permitted": "false"}}),
        )
        self.assertFalse(verdict["allowed"])

    def test_a_grant_without_ceilings_does_not_release(self):
        for missing in ("max_effective_risk", "max_declared_value_usd"):
            with self.subTest(missing=missing):
                verdict = governance.check(
                    "release_shipment", CLEAN_CASE, _boundary(_without_release_key(missing)),
                )
                self.assertFalse(verdict["allowed"])
                self.assertIn("ceiling", verdict["reason"])

    def test_a_string_auto_clear_flag_on_the_case_does_not_release(self):
        case = copy.deepcopy(CLEAN_CASE)
        case["reconciliation"]["auto_clear_permitted"] = "false"
        verdict = governance.check("release_shipment", case, _boundary(_template()))
        self.assertFalse(verdict["allowed"])

    def test_a_string_may_draft_does_not_delegate_drafting(self):
        perms = {"allowed_actions": ["draft_sar"], "sar_filing": {"may_draft": "false"}}
        verdict = governance.check("draft_sar", CLEAN_CASE, _boundary(perms))
        self.assertFalse(verdict["allowed"])

    def test_the_existing_denials_still_hold(self):
        """Value, HS prefix and destination limits, unchanged by the rewrite."""
        boundary = _boundary(_template())
        for label, change in (
            ("value", {"declared_value": 30_000}),
            ("hs", {"hs_code": "8471.30"}),
            ("destination", {"destination": "Karachi, Pakistan"}),
        ):
            with self.subTest(limit=label):
                case = copy.deepcopy(CLEAN_CASE)
                case["shipment"].update(change)
                self.assertFalse(governance.check("release_shipment", case, boundary)["allowed"])


if __name__ == "__main__":
    unittest.main()
