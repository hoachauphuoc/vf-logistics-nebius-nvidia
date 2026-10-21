"""
The receiving side of case-decisions, as part of Floorline (N01).

POST /api/v1/receiver/decision is a Pub/Sub push endpoint. It accepts only a push
whose OIDC token Google signed for the configured service account and audience (no
configuration: nothing is accepted), and applies each idempotency key once: a repeat
is counted, not applied again. A message that cannot be deduplicated is refused
(422) and never applied. GET /api/v1/receiver/applied/<key> reads the result.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_console_session import TEST_KEY  # noqa: E402
from test_evidence_eval_approve import Base  # noqa: E402
from vf_logistics import decision_receiver  # noqa: E402
from vf_logistics.app import app  # noqa: E402

SA = "push@vf-test.iam.gserviceaccount.com"
AUDIENCE = "https://vf-test.example/api/v1/receiver/decision"
PUSH_ENV = {"RECEIVER_PUSH_SA": SA, "RECEIVER_PUSH_AUDIENCE": AUDIENCE}
KEYED = {"X-VF-API-Key": TEST_KEY}


def notification(outcome="AUTO_CLEARED"):
    body = {"case_id": "CASE-1", "outcome": outcome, "at": "2026-10-21T00:00:00Z"}
    if outcome == "ESCALATED":
        body.update(fraud_pattern="document mismatch", exposure_estimate=100)
    else:
        body["effective_risk"] = 10
    return body


def envelope(key="exec-apr-1", message_id="m-1", data=None):
    body = data if data is not None else {
        "case_id": "CASE-1", "outcome": "RELEASED_BY_HUMAN", "approval_id": "apr-1", "idempotency_key": key,
    }
    message = {
        "data": base64.b64encode(json.dumps(body).encode()).decode(),
        "attributes": {"idempotency_key": key} if key else {},
        "messageId": message_id,
    }
    return {"message": message, "subscription": "projects/p/subscriptions/case-decisions-receiver"}


class TestTheReceiverRoute(Base):
    def setup_method(self):
        super().setup_method()
        self.client = app.test_client()

    def _push(self, payload):
        with patch.object(decision_receiver, "verify_push_token", return_value=SA):
            return self.client.post("/api/v1/receiver/decision", json=payload, headers={"Authorization": "Bearer t"})

    def _read(self, key):
        return self.client.get(f"/api/v1/receiver/applied/{key}", headers=KEYED)

    def test_a_decision_is_applied_once_and_a_redelivery_is_only_counted(self):
        first = self._push(envelope(message_id="m-1"))
        second = self._push(envelope(message_id="m-2"))
        assert (first.status_code, first.get_json()["outcome"]) == (200, "applied")
        assert (second.status_code, second.get_json()["outcome"]) == (200, "duplicate")
        read = self._read("exec-apr-1")
        assert read.status_code == 200
        assert read.get_json()["deliveries"] == 2
        assert read.get_json()["applied_once"] is True
        assert read.get_json()["first_message_id"] == "m-1"

    def test_a_push_without_an_accepted_token_is_refused_and_nothing_is_applied(self):
        r = self.client.post("/api/v1/receiver/decision", json=envelope(), headers={"Authorization": "Bearer forged"})
        assert r.status_code == 403
        assert "token" in r.get_json()["error"]
        assert self._read("exec-apr-1").status_code == 404

    def test_a_decision_without_a_key_is_refused_not_applied(self):
        r = self._push(envelope(key=""))
        assert r.status_code == 422
        assert r.get_json()["outcome"] == "rejected"

    def test_a_message_whose_data_is_not_a_decision_is_refused(self):
        payload = envelope()
        payload["message"]["data"] = base64.b64encode(b"not json").decode()
        r = self._push(payload)
        assert r.status_code == 422
        assert self._read("exec-apr-1").status_code == 404

    def test_an_unknown_key_reads_as_not_applied(self):
        assert self._read("exec-apr-404").status_code == 404

    @pytest.mark.parametrize("outcome", ["AUTO_CLEARED", "HELD_FOR_REVIEW", "ESCALATED"])
    def test_pipeline_notifications_are_acknowledged_without_applying_a_decision(self, outcome):
        payload = envelope(key="", data=notification(outcome))
        with patch.object(decision_receiver, "get_store", side_effect=AssertionError("must not apply")):
            first = self._push(payload)
            repeat = self._push(payload)
        assert first.status_code == repeat.status_code == 200
        assert first.get_json()["outcome"] == repeat.get_json()["outcome"] == "ignored"
        assert self._read("exec-apr-1").status_code == 404

    @pytest.mark.parametrize("extra", [
        {"approval_id": "apr-1"}, {"idempotency_key": "exec-apr-1"},
        {"executor": "reviewer@example.test"}, {"unknown_field": True},
    ])
    def test_a_keyless_payload_with_approval_metadata_or_unknown_fields_is_still_refused(self, extra):
        body = {**notification(), **extra}
        assert self._push(envelope(key="", data=body)).status_code == 422
        assert self._read("exec-apr-1").status_code == 404

    @pytest.mark.parametrize("field", ["case_id", "at", "effective_risk"])
    def test_an_incomplete_pipeline_notification_is_not_silently_acknowledged(self, field):
        body = notification()
        del body[field]
        assert self._push(envelope(key="", data=body)).status_code == 422

    def test_a_pipeline_notification_needs_a_broker_message_id(self):
        payload = envelope(key="", data=notification())
        del payload["message"]["messageId"]
        assert self._push(payload).status_code == 422

    def test_an_unknown_keyless_outcome_is_still_refused(self):
        body = {**notification(), "outcome": "UNKNOWN"}
        assert self._push(envelope(key="", data=body)).status_code == 422

    def test_a_pipeline_notification_still_requires_a_valid_push_token(self):
        r = self.client.post("/api/v1/receiver/decision", json=envelope(key="", data=notification()))
        assert r.status_code == 403

    def test_a_pipeline_notification_still_requires_its_tenant_in_multi_tenant_mode(self):
        payload = envelope(key="", data=notification())
        with patch.dict(os.environ, {"MULTI_TENANT": "true"}):
            assert self._push(payload).status_code == 422
            payload["message"]["attributes"]["tenant_id"] = "acme"
            with patch.object(decision_receiver, "get_store", side_effect=AssertionError("must not apply")):
                assert self._push(payload).status_code == 200


class TestThePushToken:
    def test_nothing_is_accepted_without_configuration(self):
        with patch.dict(os.environ, {"RECEIVER_PUSH_SA": "", "RECEIVER_PUSH_AUDIENCE": ""}):
            assert decision_receiver.verify_push_token("Bearer anything") is None

    def test_a_token_google_signed_for_the_configured_account_is_accepted(self):
        claims = {"email": SA, "email_verified": True, "aud": AUDIENCE}
        with patch.dict(os.environ, PUSH_ENV), \
                patch("google.oauth2.id_token.verify_oauth2_token", return_value=claims) as verify:
            assert decision_receiver.verify_push_token("Bearer signed") == SA
        assert verify.call_args.kwargs["audience"] == AUDIENCE

    def test_a_token_for_another_account_is_refused(self):
        claims = {"email": "someone-else@x.iam.gserviceaccount.com", "email_verified": True}
        with patch.dict(os.environ, PUSH_ENV), \
                patch("google.oauth2.id_token.verify_oauth2_token", return_value=claims):
            assert decision_receiver.verify_push_token("Bearer signed") is None

    def test_a_token_that_does_not_verify_is_refused(self):
        with patch.dict(os.environ, PUSH_ENV), \
                patch("google.oauth2.id_token.verify_oauth2_token", side_effect=ValueError("bad signature")):
            assert decision_receiver.verify_push_token("Bearer forged") is None

    def test_a_header_that_is_not_a_bearer_token_is_refused(self):
        with patch.dict(os.environ, PUSH_ENV):
            assert decision_receiver.verify_push_token(None) is None
            assert decision_receiver.verify_push_token("Basic abc") is None
