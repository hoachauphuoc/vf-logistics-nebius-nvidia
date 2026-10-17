"""
The exception route: a release over unresolved or contradicting evidence is its own
operation, behind the operator role and a password sign-in (N04).
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
from test_console_session import TEST_KEY, mint  # noqa: E402
from test_evidence_eval_approve import DOCS3, PAPERS, Base, _submit_per_type  # noqa: E402
from vf_logistics import evidence  # noqa: E402

REVIEWER = "reviewer@forwarder.example"
OPERATOR = "operator@forwarder.example"
URL = "/api/v1/review/CASE-1/approve-exception"
BODY = {
    "reason": "Certificate misread; checked the original",
    "waived": ["contradiction:certificate_country"],
}


def run(coro):
    return asyncio.run(coro)


class TestTheExceptionRoute(Base):
    def setup_method(self):
        super().setup_method()
        from vf_logistics import app as app_mod

        # A one-click (guest) token is honoured only while the guest door is open for that account.
        guest_door = {"VF_ONE_CLICK_JUDGE": "true", "VF_ONE_CLICK_EMAIL": OPERATOR}
        self.operators = patch.dict(os.environ, {"OPERATOR_EMAILS": OPERATOR, **guest_door})
        self.operators.start()
        self.app_mod = app_mod
        self.was = app_mod.limiter.enabled
        app_mod.limiter.enabled = False
        self.client = app_mod.app.test_client()
        self.put()
        out = run(evidence.request_evidence("CASE-1", REVIEWER, documents=DOCS3))
        links = {link["doc_type"]: link["token"] for link in out["links"]}
        _submit_per_type(links, {
            **PAPERS,
            "certificate_of_origin": {"producer_name": "Saigon Plywood Co", "origin_country": "China"},
        })
        assert run(evidence.reevaluate("CASE-1"))["evaluation"]["status"] == "contradicted"

    def teardown_method(self):
        self.app_mod.limiter.enabled = self.was
        self.operators.stop()
        super().teardown_method()

    def _post(self, email, amr, body):
        headers = {"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint(email, amr=amr)}
        return self.client.post(URL, json=body, headers=headers)

    def test_a_reviewer_may_not_make_an_exception(self):
        response = self._post(REVIEWER, "password", BODY)
        assert response.status_code == 403
        assert self.stored()["verification"]["approvals"] == []

    def test_an_operator_on_a_one_click_session_may_not(self):
        response = self._post(OPERATOR, "one_click", BODY)
        assert response.status_code == 403
        assert response.get_json()["required_auth"] == "password"
        assert self.stored()["verification"]["approvals"] == []

    def test_an_operator_with_a_password_makes_a_recorded_exception(self):
        response = self._post(OPERATOR, "password", BODY)
        assert response.status_code == 200
        served = response.get_json()
        assert served["state"] == "APPROVED"
        exception = served["approval"]["exception"]
        assert exception["operation"] == "exception"
        assert exception["waived"] == BODY["waived"]
        assert exception["reason"] == BODY["reason"]
        assert exception["approved_by"] == OPERATOR

    def test_a_list_that_misses_an_item_is_refused(self):
        response = self._post(OPERATOR, "password", {**BODY, "waived": ["something_else"]})
        assert response.status_code == 400
        assert "every waived item" in response.get_json()["error"]
        assert self.stored()["verification"]["approvals"] == []

    def test_a_body_without_a_waived_list_is_refused(self):
        response = self._post(OPERATOR, "password", {"reason": BODY["reason"]})
        assert response.status_code == 400
        assert "waived" in response.get_json()["error"]
