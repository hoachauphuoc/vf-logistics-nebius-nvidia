"""
N07 at the route, not only in the function: who may release or approve, and what the
legacy /decide route refuses once a case has gone through the verification loop.

The unit tests in test_evidence_eval_approve.py cover human_decide and approve called
directly. A refusal that only exists in a function is not a refusal a caller can rely
on, so these go through the Flask routes with real session tokens, and check that a
refused call leaves the stored case exactly as it was.
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_console_session import TEST_KEY  # noqa: E402
from test_evidence_eval_approve import Base as EvidenceBase, approve_open  # noqa: E402
from test_rbac import ADMIN, REVIEWER, ROLE_ENV, _session  # noqa: E402
from vf_logistics import evidence, orchestrator  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class RouteBase(EvidenceBase):
    def setup_method(self):
        self.env = patch.dict(os.environ, dict(ROLE_ENV, STORE_BACKEND="memory"))
        self.env.start()
        from vf_logistics import app as app_mod
        from vf_logistics import store as store_mod

        store_mod._store = None
        self.store = store_mod.get_store()
        self.app_mod = app_mod
        self.limiter_was = app_mod.limiter.enabled
        app_mod.limiter.enabled = False
        self.client = app_mod.app.test_client()

    def teardown_method(self):
        from vf_logistics import store as store_mod

        self.app_mod.limiter.enabled = self.limiter_was
        store_mod._store = None
        self.env.stop()

    def untouched(self, before):
        after = self.stored()
        assert after["state"] == before["state"]
        assert after["_version"] == before["_version"]


# Reviewers are the people who decide; the one-click guest is the ADMIN account signed
# in without a password (VF_ONE_CLICK_*), which has the role but not the credential.
ONE_CLICK = _session(ADMIN, amr="one_click")
PASSWORD = _session(REVIEWER, amr="password")


class TestApproveAndExecuteNeedAPassword(RouteBase):
    def _approved(self):
        self.put()
        self.request_and_submit()
        run(evidence.reevaluate("CASE-1"))
        return run(approve_open(
            "CASE-1", "release", REVIEWER, note="Reviewed", actor_auth="password",
        ))["approval"]["approval_id"]

    def test_a_one_click_session_cannot_approve(self):
        self.put()
        self.request_and_submit()
        run(evidence.reevaluate("CASE-1"))
        before = self.stored()
        response = self.client.post("/api/v1/review/CASE-1/approve",
                                    json={"action": "release", "note": "ok"}, headers=ONE_CLICK)
        assert response.status_code == 403
        assert response.get_json()["required_auth"] == "password"
        self.untouched(before)

    def test_a_one_click_session_cannot_execute(self):
        approval_id = self._approved()
        before = self.stored()
        response = self.client.post("/api/v1/review/CASE-1/execute",
                                    json={"approval_id": approval_id}, headers=ONE_CLICK)
        assert response.status_code == 403
        assert response.get_json()["required_auth"] == "password"
        self.untouched(before)

    def test_a_password_session_can_do_both(self):
        self.put()
        self.request_and_submit()
        run(evidence.reevaluate("CASE-1"))
        approved = self.client.post("/api/v1/review/CASE-1/approve",
                                    json={"action": "block"}, headers=PASSWORD)
        assert approved.status_code == 200, approved.get_data(as_text=True)


class TestLegacyDecideAfterTheLoop(RouteBase):
    def _in_the_loop(self):
        """A case that has asked for, received and re-evaluated documents: it is back
        in a state that waits for a person, and evidence_version is above zero."""
        self.put()
        self.request_and_submit()
        run(evidence.reevaluate("CASE-1"))
        case = self.stored()
        assert case["state"] in ("HELD_FOR_REVIEW", "ESCALATED")
        assert case["verification"]["evidence_version"] >= 1
        return case

    @pytest.mark.parametrize("action", ["release", "block", "request_info"])
    def test_decide_refuses_every_action_and_leaves_the_case_alone(self, action):
        before = self._in_the_loop()
        response = self.client.post("/api/v1/review/CASE-1/decide",
                                    json={"action": action, "note": "reviewed"}, headers=PASSWORD)
        assert response.status_code == 400
        assert "/approve" in response.get_json()["error"]
        self.untouched(before)


class TestLegacyDecideReleaseNeedsAPassword(RouteBase):
    @pytest.mark.parametrize("label,headers", [
        ("one-click session", ONE_CLICK),
        ("api key alone", {"X-VF-API-Key": TEST_KEY}),
    ])
    def test_release_is_refused_without_a_password_and_the_case_is_unchanged(self, label, headers):
        self.put()
        before = self.stored()
        response = self.client.post("/api/v1/review/CASE-1/decide",
                                    json={"action": "release", "note": "ok", "reviewer": REVIEWER},
                                    headers=headers)
        assert response.status_code == 400, label
        assert "password" in response.get_json()["error"].lower()
        self.untouched(before)

    def test_release_with_a_password_is_the_positive_control(self):
        self.put()
        response = self.client.post("/api/v1/review/CASE-1/decide",
                                    json={"action": "release", "note": "ok"}, headers=PASSWORD)
        assert response.status_code == 200, response.get_data(as_text=True)
        assert self.stored()["state"] == "RELEASED_BY_HUMAN"

    def test_block_is_still_open_to_a_one_click_session_on_a_plain_case(self):
        # Intended: only RELEASE needs the password (a block holds cargo, a release
        # sends it on). Recorded so that changing it is a decision, not an accident.
        self.put()
        response = self.client.post("/api/v1/review/CASE-1/decide",
                                    json={"action": "block", "note": "hold"}, headers=ONE_CLICK)
        assert response.status_code == 200, response.get_data(as_text=True)
        assert self.stored()["state"] == "BLOCKED_BY_HUMAN"

    @pytest.mark.parametrize("auth", [None, "api_key", "iap", "one_click"])
    def test_human_decide_release_needs_exactly_a_password(self, auth):
        self.put()
        before = self.stored()
        result = run(orchestrator.human_decide("CASE-1", "release", REVIEWER, "ok", actor_auth=auth))
        assert result["ok"] is False and "password" in result["error"].lower()
        self.untouched(before)
