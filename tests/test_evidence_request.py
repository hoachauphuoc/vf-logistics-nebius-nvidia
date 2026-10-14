"""
Requests for documents and the signed link (Plan 1, step 2).

What matters here, in order:

1. The link is never in the case. The case JSON is readable by a viewer; a link in it
   would let any viewer submit "evidence". Asserted on the serialised case, so it holds
   however the field is named.
2. A link is valid only if it was signed with this service's key, has not expired, and
   is the CURRENT link of its request. Every other outcome is one answer (None).
3. A session token and an evidence link cannot stand in for one another.
4. While a request is open nobody can decide the case; cancelling it, with a reason,
   is the way out, and the case returns to where it was.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_console_session import TEST_KEY, TEST_SECRET, mint  # noqa: E402
from test_origin_inputs import plywood  # noqa: E402
from vf_logistics import evidence  # noqa: E402
from vf_logistics import store as store_mod  # noqa: E402
from vf_logistics import worklist  # noqa: E402
from vf_logistics.verifier import ORIGIN_EVIDENCE_DOCS, validate  # noqa: E402

REVIEWER = "reviewer@forwarder.example"
ENV = {
    "VF_API_KEY": TEST_KEY, "VF_SESSION_SECRET": TEST_SECRET, "IAP_ENABLED": "false",
    "MULTI_TENANT": "false", "ANONYMOUS_ROLE": "viewer", "STORE_BACKEND": "memory",
    "REVIEWER_EMAILS": REVIEWER,
}


def run(coro):
    return asyncio.run(coro)


class Base:
    def setup_method(self):
        from vf_logistics import app as app_mod

        self.env = patch.dict(os.environ, ENV)
        self.env.start()
        store_mod._store = None
        self.was = app_mod.limiter.enabled
        app_mod.limiter.enabled = False
        self.app_mod = app_mod
        self.client = app_mod.app.test_client()
        self.store = store_mod.get_store()

    def teardown_method(self):
        self.app_mod.limiter.enabled = self.was
        store_mod._store = None
        self.env.stop()

    def put(self, case_id="CASE-1", state="HELD_FOR_REVIEW", shipment=None, **extra):
        shipment = shipment or plywood()
        case = {
            "case_id": case_id, "shipment_id": case_id, "state": state,
            "created_at": "2026-10-12T01:00:00+00:00", "updated_at": "2026-10-12T02:00:00+00:00",
            "shipment": shipment, "validation": validate(shipment), "actions": [], "reviews": [],
        }
        case.update(extra)
        run(self.store.put_case(case))
        return case

    def stored(self, case_id="CASE-1"):
        return run(self.store.get_case(case_id))

    def ask(self, case_id="CASE-1", **kw):
        return run(evidence.request_evidence(case_id, REVIEWER, **kw))

    def reviewer(self):
        return {"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint(REVIEWER, amr="password")}


class TestTheToken(Base):
    def test_a_minted_token_reads_back(self):
        token, expires = evidence.mint_token("default", "CASE-1", "evreq-1", 1)
        claims = evidence.read_token(token)
        assert (claims["t"], claims["c"], claims["r"], claims["s"]) == ("default", "CASE-1", "evreq-1", 1)
        assert claims["e"] == expires

    def test_a_forged_signature_is_refused(self):
        token, _ = evidence.mint_token("default", "CASE-1", "evreq-1", 1)
        body, _, signature = token.partition(".")
        # Flip a character in the MIDDLE of the signature so the actual bytes change.
        # The last char of a 43-char base64url string may only differ in padding bits.
        mid = len(signature) // 2
        ch = signature[mid]
        replacement = "A" if ch != "A" else "B"
        flipped = signature[:mid] + replacement + signature[mid + 1:]
        assert evidence.read_token(f"{body}.{flipped}") is None

    def test_a_tampered_body_is_refused(self):
        """Changing the case or the request in the payload must break the signature."""
        token, _ = evidence.mint_token("default", "CASE-1", "evreq-1", 1)
        other, _ = evidence.mint_token("default", "CASE-2", "evreq-1", 1)
        assert evidence.read_token(f"{other.split('.')[0]}.{token.split('.')[1]}") is None

    def test_an_expired_token_is_refused(self):
        token, expires = evidence.mint_token("default", "CASE-1", "evreq-1", 1, now=time.time() - 8 * 24 * 3600)
        assert evidence.read_token(token) is None
        fresh, expires = evidence.mint_token("default", "CASE-1", "evreq-1", 1)
        assert evidence.read_token(fresh, now=expires - 1) is not None
        assert evidence.read_token(fresh, now=expires) is None

    def test_a_token_signed_with_another_secret_is_refused(self):
        token, _ = evidence.mint_token("default", "CASE-1", "evreq-1", 1)
        with patch.dict(os.environ, {"VF_SESSION_SECRET": "x" * 40}):
            assert evidence.read_token(token) is None

    @pytest.mark.parametrize("junk", [
        None, "", " ", "a", "a.", ".b", "a.b.c", "x" * 2000, 12, {"a": 1}, [], "not.base64!", "e30.e30",
    ])
    def test_anything_else_is_one_answer_not_an_error(self, junk):
        assert evidence.read_token(junk) is None

    def test_a_console_session_is_not_an_evidence_link(self):
        assert evidence.read_token(mint(REVIEWER, amr="password")) is None

    def test_an_evidence_link_is_not_a_console_session(self):
        """Offered as the session header, a link must verify as nobody. It is signed
        with a key derived from the session secret, not the secret, so the HMAC differs."""
        from vf_logistics import auth

        token, _ = evidence.mint_token("default", "CASE-1", "evreq-1", 1)
        with self.app_mod.app.test_request_context(
            headers={auth.CONSOLE_SESSION_HEADER: token},
        ):
            assert auth._console_session_claims() is None
        # Control: the same call accepts a real session, so the None above is the signature.
        with self.app_mod.app.test_request_context(
            headers={auth.CONSOLE_SESSION_HEADER: mint(REVIEWER, amr="password")},
        ):
            assert auth._console_session_claims() is not None

    def test_a_link_signed_with_the_raw_session_secret_is_refused(self):
        """Key separation, tested directly. The two payload shapes already differ, so the
        console-session tests above would pass without it; this is the one that fails if
        the key stops being derived. A well-formed link, signed with the secret itself."""
        import base64
        import hashlib
        import hmac as hmac_mod

        payload = json.dumps(
            {"v": 1, "t": "default", "c": "CASE-1", "r": "evreq-1", "s": 1, "e": int(time.time()) + 3600},
            separators=(",", ":"), sort_keys=True,
        ).encode()
        body = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
        raw = hmac_mod.new(TEST_SECRET.encode(), body.encode(), hashlib.sha256).digest()
        forged = f"{body}.{base64.urlsafe_b64encode(raw).rstrip(b'=').decode()}"
        assert evidence.read_token(forged) is None
        # Control: the same payload signed the real way is accepted.
        real, _ = evidence.mint_token("default", "CASE-1", "evreq-1", 1)
        assert evidence.read_token(real) is not None

    def test_with_no_secret_nothing_is_signed_and_nothing_verifies(self):
        with patch.dict(os.environ, {"VF_SESSION_SECRET": ""}):
            with pytest.raises(evidence.EvidenceError) as raised:
                evidence.mint_token("default", "CASE-1", "evreq-1", 1)
            assert raised.value.status == 503
            assert evidence.read_token("a.b") is None


class TestRequestingDocuments(Base):
    def test_the_minimum_the_findings_ask_for_is_requested_and_the_case_waits(self):
        self.put()
        out = self.ask()
        assert out["state"] == "AWAITING_EVIDENCE"
        assert out["request"]["documents"] == list(ORIGIN_EVIDENCE_DOCS)
        assert out["request"]["finding_codes"] == ["ORIGIN_INPUTS_UNVERIFIED"]
        assert out["request"]["status"] == "SENT"
        assert out["path"] == f"/respond/{out['token']}"
        case = self.stored()
        assert case["state"] == "AWAITING_EVIDENCE"
        assert case["verification"]["resume_state"] == "HELD_FOR_REVIEW"

    def test_the_link_is_not_in_the_case_the_viewers_read(self):
        self.put()
        token = self.ask()["token"]
        assert token not in json.dumps(self.stored())
        assert token.split(".")[1] not in json.dumps(self.stored())
        client_view = self.client.get("/api/v1/orchestrator/case/CASE-1").get_data(as_text=True)
        assert token not in client_view
        # What IS kept is enough to tell links apart and no more.
        outbox = self.stored()["verification"]["requests"][0]["outbox"]
        assert len(outbox) == 1 and len(outbox[0]["token_fingerprint"]) == 12

    def test_the_token_names_the_current_link_of_this_request(self):
        self.put()
        out = self.ask()
        claims = evidence.read_token(out["token"])
        assert claims["r"] == out["request"]["request_id"] and claims["c"] == "CASE-1"
        assert claims["s"] == self.stored()["verification"]["requests"][0]["link_seq"] == 1

    def test_it_reads_as_a_request_for_information_everywhere_one_is_counted(self):
        self.put()
        self.ask(note="Please send the producer's declaration")
        case = self.stored()
        assert worklist.bucket_for(case) == "awaiting_documents"
        assert worklist.information_rounds(case) == 1
        assert case["reviews"][-1]["note"] == "Please send the producer's declaration"

    def test_it_is_audited(self):
        self.put()
        out = self.ask()
        rows, _ = run(self.store.query_audit(case_id="CASE-1"))
        row = next(r for r in rows if r["action"] == "evidence_requested")
        assert row["actor"] == REVIEWER
        assert row["detail"]["request_id"] == out["request"]["request_id"]
        assert out["token"] not in json.dumps(rows)

    def test_what_has_already_arrived_is_not_asked_for_again(self):
        self.put(verification={**evidence.empty_verification(), "documents": [
            {"doc_type": "certificate_of_origin", "extracted": {"origin_country": "Vietnam"}},
        ]})
        assert self.ask()["request"]["documents"] == ["producer_declaration", "input_purchase_invoices"]

    def test_a_copy_that_was_blocked_or_read_into_nothing_is_asked_for_again(self):
        # N04: arrived is not the same as usable.
        self.put(verification={**evidence.empty_verification(), "documents": [
            {"doc_type": "certificate_of_origin", "extracted": {}},
            {"doc_type": "producer_declaration", "extracted": {"producer_name": "X"}, "blocked": True},
        ]})
        assert self.ask()["request"]["documents"] == [
            "certificate_of_origin", "producer_declaration", "input_purchase_invoices",
        ]

    def test_a_reviewer_can_name_fewer_documents(self):
        self.put()
        out = self.ask(documents=["certificate_of_origin"])
        assert out["request"]["documents"] == ["certificate_of_origin"]

    @pytest.mark.parametrize("kw, status, fragment", [
        ({"documents": ["bank_statement"]}, 400, "not a document"),
        ({"documents": "certificate_of_origin"}, 400, "list"),
        ({"finding_codes": ["SANCTIONS_MATCH"]}, 400, "not a finding on this case"),
        ({"note": "x" * 1001}, 400, "1000"),
        ({"owner": 5}, 400, "text"),
    ])
    def test_a_malformed_request_is_refused_and_changes_nothing(self, kw, status, fragment):
        self.put()
        with pytest.raises(evidence.EvidenceError) as raised:
            self.ask(**kw)
        assert raised.value.status == status and fragment in raised.value.message
        assert self.stored()["state"] == "HELD_FOR_REVIEW"
        assert "verification" not in self.stored() or not self.stored()["verification"]["requests"]

    def test_a_case_with_no_finding_that_asks_for_documents_is_refused(self):
        self.put(shipment=plywood(destination="Rotterdam, Netherlands"))
        with pytest.raises(evidence.EvidenceError) as raised:
            self.ask()
        assert "No finding" in raised.value.message

    @pytest.mark.parametrize("state", ["AUTO_CLEARED", "RELEASED_BY_HUMAN", "BLOCKED_BY_HUMAN", "INGESTED", "DEAD_LETTER"])
    def test_only_a_case_waiting_on_a_person_can_be_asked_about(self, state):
        self.put(state=state)
        with pytest.raises(evidence.EvidenceError) as raised:
            self.ask()
        assert raised.value.status == 409
        assert self.stored()["state"] == state

    def test_the_same_request_twice_is_refused_not_duplicated(self):
        self.put()
        self.ask()
        with pytest.raises(evidence.EvidenceError) as raised:
            self.ask()
        assert raised.value.status == 409 and "already requested" in raised.value.message
        assert len(self.stored()["verification"]["requests"]) == 1

    def test_a_missing_case_is_not_found(self):
        with pytest.raises(evidence.EvidenceError) as raised:
            self.ask("NOPE")
        assert raised.value.status == 404

    def test_a_person_is_required(self):
        self.put()
        with pytest.raises(evidence.EvidenceError):
            run(evidence.request_evidence("CASE-1", ""))

    def test_losing_the_race_with_another_write_is_a_409_and_writes_nothing(self):
        self.put()
        lost = store_mod.OptimisticLockError("CASE-1", 1, 2)
        with patch.object(type(self.store), "put_case", side_effect=lost):
            with pytest.raises(evidence.EvidenceError) as raised:
                self.ask()
        assert raised.value.status == 409
        rows, _ = run(self.store.query_audit(case_id="CASE-1"))
        assert not [r for r in rows if r["action"] == "evidence_requested"]


class TestLinksAndCancelling(Base):
    def test_a_new_link_retires_the_old_one(self):
        self.put()
        first = self.ask()
        second = run(evidence.reissue_link("CASE-1", first["request"]["request_id"], REVIEWER))
        request = self.stored()["verification"]["requests"][0]
        assert request["link_seq"] == 2
        assert evidence.read_token(first["token"])["s"] == 1 < evidence.read_token(second["token"])["s"] == 2
        prints = [o["token_fingerprint"] for o in request["outbox"]]
        assert len(prints) == 2 and prints[0] != prints[1]

    def test_cancelling_the_only_request_returns_the_case_to_where_it_was(self):
        self.put(state="ESCALATED")
        first = self.ask()
        out = run(evidence.cancel_request("CASE-1", first["request"]["request_id"], REVIEWER, "Shipper unreachable"))
        assert out["state"] == "ESCALATED"
        case = self.stored()
        assert case["state"] == "ESCALATED"
        assert case["verification"]["requests"][0]["status"] == "CANCELLED"
        assert case["verification"]["requests"][0]["cancel_reason"] == "Shipper unreachable"

    def test_cancelling_one_of_two_requests_leaves_the_case_waiting(self):
        self.put()
        a = self.ask(documents=["certificate_of_origin"])
        self.ask(documents=["producer_declaration"])
        run(evidence.cancel_request("CASE-1", a["request"]["request_id"], REVIEWER, "Asked in error"))
        assert self.stored()["state"] == "AWAITING_EVIDENCE"
        assert len(evidence.open_requests(self.stored())) == 1

    def test_a_reason_is_required_to_cancel(self):
        self.put()
        out = self.ask()
        for reason in (None, "", "   "):
            with pytest.raises(evidence.EvidenceError):
                run(evidence.cancel_request("CASE-1", out["request"]["request_id"], REVIEWER, reason))
        assert self.stored()["state"] == "AWAITING_EVIDENCE"

    def test_a_closed_request_can_be_neither_cancelled_nor_given_a_link(self):
        self.put()
        out = self.ask()
        rid = out["request"]["request_id"]
        run(evidence.cancel_request("CASE-1", rid, REVIEWER, "done with it"))
        with pytest.raises(evidence.EvidenceError) as again:
            run(evidence.cancel_request("CASE-1", rid, REVIEWER, "again"))
        with pytest.raises(evidence.EvidenceError) as link:
            run(evidence.reissue_link("CASE-1", rid, REVIEWER))
        assert again.value.status == link.value.status == 409

    def test_an_unknown_request_is_not_found(self):
        self.put()
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.reissue_link("CASE-1", "evreq-nope", REVIEWER))
        assert raised.value.status == 404


class TestWhileARequestIsOpen(Base):
    def test_nobody_can_decide_the_case(self):
        self.put()
        self.ask()
        for action in ("release", "block", "request_info"):
            result = run(__import__("vf_logistics.orchestrator", fromlist=["x"]).human_decide(
                "CASE-1", action, REVIEWER, "because"))
            assert result["ok"] is False and "not awaiting review" in result["error"], action
        assert self.stored()["state"] == "AWAITING_EVIDENCE"

    def test_the_state_is_a_known_one_everywhere_states_are_listed(self):
        from vf_logistics import b2b, orchestrator, schemas

        assert "AWAITING_EVIDENCE" in orchestrator.TERMINAL
        assert "AWAITING_EVIDENCE" not in orchestrator.AWAITING_HUMAN
        assert "AWAITING_EVIDENCE" in {s.value for s in schemas.CaseState}
        assert "AWAITING_EVIDENCE" not in b2b.unmapped_terminal_states()
        assert b2b.outcome_for({"state": "AWAITING_EVIDENCE"}).value != "ERROR"


class TestTheRoutes(Base):
    def test_a_reviewer_gets_the_link_once_and_it_is_not_cacheable(self):
        self.put()
        response = self.client.post("/api/v1/review/CASE-1/request-evidence", json={}, headers=self.reviewer())
        assert response.status_code == 201, response.get_data(as_text=True)
        assert response.headers["Cache-Control"] == "no-store"
        body = response.get_json()
        assert body["path"].startswith("/respond/") and body["state"] == "AWAITING_EVIDENCE"
        assert self.stored()["verification"]["requests"][0]["created_by"] == REVIEWER

    def test_who_may_not_ask(self):
        self.put()
        for label, headers in {
            "anonymous": {},
            "a viewer": {"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint("nobody@x.example", amr="password")},
        }.items():
            for path in ("request-evidence", "evidence/evreq-1/link", "evidence/evreq-1/cancel"):
                status = self.client.post(f"/api/v1/review/CASE-1/{path}", json={}, headers=headers).status_code
                assert status in (401, 403), (label, path, status)
        assert self.stored()["state"] == "HELD_FOR_REVIEW"

    def test_the_name_recorded_is_the_session_not_the_body(self):
        self.put()
        self.client.post("/api/v1/review/CASE-1/request-evidence",
                         json={"reviewer": "someone-else@x.example"}, headers=self.reviewer())
        assert self.stored()["verification"]["requests"][0]["created_by"] == REVIEWER

    @pytest.mark.parametrize("body", [[], "text", 5, None])
    def test_a_body_that_is_not_an_object_is_handled(self, body):
        self.put()
        response = self.client.post("/api/v1/review/CASE-1/request-evidence", json=body, headers=self.reviewer())
        assert response.status_code == 201

    def test_a_refusal_is_its_status_and_a_message(self):
        self.put(state="AUTO_CLEARED")
        response = self.client.post("/api/v1/review/CASE-1/request-evidence", json={}, headers=self.reviewer())
        assert response.status_code == 409 and "error" in response.get_json()
        assert self.client.post("/api/v1/review/NOPE/request-evidence", json={}, headers=self.reviewer()).status_code == 404

    def test_cancel_and_link_routes_work_end_to_end(self):
        self.put()
        rid = self.client.post("/api/v1/review/CASE-1/request-evidence", json={},
                               headers=self.reviewer()).get_json()["request"]["request_id"]
        link = self.client.post(f"/api/v1/review/CASE-1/evidence/{rid}/link", json={}, headers=self.reviewer())
        assert link.status_code == 200 and link.headers["Cache-Control"] == "no-store"
        no_reason = self.client.post(f"/api/v1/review/CASE-1/evidence/{rid}/cancel", json={}, headers=self.reviewer())
        assert no_reason.status_code == 400
        done = self.client.post(f"/api/v1/review/CASE-1/evidence/{rid}/cancel",
                                json={"reason": "Shipper reached by phone"}, headers=self.reviewer())
        assert done.status_code == 200 and done.get_json()["state"] == "HELD_FOR_REVIEW"


class TestReevaluateRoute(Base):
    """N05 at the HTTP boundary: the refusal is a status and a message, not a 500."""

    def _post(self, case_id="CASE-1", headers=None):
        return self.client.post(
            f"/api/v1/review/{case_id}/reevaluate", json={},
            headers=self.reviewer() if headers is None else headers,
        )

    def test_a_decided_case_is_a_409_with_its_state_in_the_message(self):
        self.put(state="RELEASED_BY_HUMAN")
        response = self._post()
        assert response.status_code == 409
        assert "RELEASED_BY_HUMAN" in response.get_json()["error"]
        assert self.stored()["state"] == "RELEASED_BY_HUMAN"

    def test_a_case_that_never_asked_for_documents_is_a_409_and_unchanged(self):
        self.put()
        response = self._post()
        assert response.status_code == 409
        assert "requested" in response.get_json()["error"].lower()
        assert "verification" not in self.stored()

    def test_an_unknown_case_is_a_404(self):
        assert self._post("NOPE").status_code == 404

    def test_a_viewer_and_an_anonymous_caller_are_refused(self):
        self.put()
        viewer = {"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint("nobody@x.example", amr="password")}
        for headers in ({}, viewer):
            assert self._post(headers=headers).status_code in (401, 403)
