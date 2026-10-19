"""
Refusals on the evidence loop's release path, each asserted by status and by the phrase that tells the
person what to do next: a link token that is forged or malformed reads as nothing, an approval or execution
without a named, password-authenticated person is refused, and an approval is executable only in the exact
state that earned it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_evidence_eval_approve import REVIEWER, Base, run  # noqa: E402
from vf_logistics import evidence  # noqa: E402
from vf_logistics.evidence import EvidenceError  # noqa: E402


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def signed(claims) -> str:
    """A token signed with the real key over arbitrary claims, so only the claims are what is wrong."""
    body = b64(json.dumps(claims, separators=(",", ":")).encode())
    return f"{body}." + b64(hmac.new(evidence._key(), body.encode("ascii"), hashlib.sha256).digest())


GOOD = {"v": 1, "t": "evidence", "c": "CASE-1", "r": "REQ-1", "s": 1, "e": 2_000_000_000}


class TestReadingATokenIsAllOrNothing(Base):
    def test_a_well_formed_signed_token_gives_its_claims(self):
        assert evidence.read_token(signed(GOOD), now=1_000_000_000) == GOOD

    def test_a_token_minted_here_reads_back(self):
        token, _ = evidence.mint_token("evidence", "CASE-1", "REQ-1", 2, doc_type="invoice")
        claims = evidence.read_token(token)
        assert (claims["c"], claims["s"], claims["d"]) == ("CASE-1", 2, "invoice")

    @pytest.mark.parametrize("token", [None, 5, "", "nodot", ".sig", "body.", "a.b.c", "x" * 10_000])
    def test_a_malformed_token_is_nothing(self, token):
        assert evidence.read_token(token) is None

    def test_a_forged_signature_is_nothing(self):
        body = signed(GOOD).split(".")[0]
        assert evidence.read_token(f"{body}.{b64(b'wrong')}", now=1_000_000_000) is None

    def test_a_signature_that_is_not_base64_is_nothing(self):
        body = signed(GOOD).split(".")[0]
        assert evidence.read_token(f"{body}.!!!", now=1_000_000_000) is None

    @pytest.mark.parametrize("claims", [
        [1, 2],
        {**GOOD, "v": 2},
        {**GOOD, "e": "soon"},
        {**GOOD, "e": True},
        {**GOOD, "e": 1},
        {**GOOD, "t": ""},
        {**GOOD, "c": 7},
        {**GOOD, "r": None},
        {**GOOD, "s": "1"},
        {**GOOD, "s": True},
    ])
    def test_a_correctly_signed_token_with_wrong_claims_is_still_nothing(self, claims):
        assert evidence.read_token(signed(claims), now=1_000_000_000) is None

    def test_an_expired_token_is_nothing(self):
        assert evidence.read_token(signed(GOOD), now=2_000_000_001) is None


class TestApproveRefusals(Base):
    def refusal(self, *args, **kwargs):
        with pytest.raises(EvidenceError) as caught:
            run(evidence.approve(*args, **kwargs))
        return caught.value

    def test_an_unknown_decision_is_400(self):
        error = self.refusal("CASE-1", "shrug", REVIEWER)
        assert (error.status, "'shrug' is not a decision that can be approved" in error.message) == (400, True)

    def test_an_approval_needs_a_named_person(self):
        error = self.refusal("CASE-1", "block", "")
        assert (error.status, error.message) == (400, "An approval is made by a named person")

    def test_a_missing_case_is_404(self):
        error = self.refusal("NOPE", "block", REVIEWER)
        assert (error.status, error.message) == (404, "case not found")

    def test_only_a_release_can_be_an_exception(self):
        self.put()
        error = self.refusal("CASE-1", "block", REVIEWER, waived=["certificate_of_origin"], actor_auth="password", note="n")
        assert (error.status, error.message) == (400, "Only a release can be an exception.")

    def test_an_exception_needs_a_reason_and_names_what_it_waives(self):
        for reason, waived, phrase in (("  ", ["x"], "needs a reason"), ("why", [], "must name what it waives")):
            with pytest.raises(EvidenceError) as caught:
                run(evidence.approve_exception("CASE-1", REVIEWER, reason, waived, actor_auth="password"))
            assert caught.value.status == 400 and phrase in caught.value.message


class TestExecuteRefusals(Base):
    def refusal(self, executor, auth, case_id="CASE-1"):
        with pytest.raises(EvidenceError) as caught:
            run(evidence.execute_approval(case_id, "APR-1", executor, actor_auth=auth))
        return caught.value

    def test_an_execution_needs_a_named_person(self):
        error = self.refusal("", "password")
        assert (error.status, error.message) == (400, "An execution is done by a named person")

    def test_an_execution_needs_a_password_sign_in(self):
        error = self.refusal(REVIEWER, "one_click")
        assert (error.status, "needs a password sign-in" in error.message) == (403, True)

    def test_a_missing_case_is_404(self):
        error = self.refusal(REVIEWER, "password", case_id="NOPE")
        assert (error.status, error.message) == (404, "case not found")


def case_with(approval=None, state="APPROVED", evidence_version=1, requests=None):
    record = {
        "evidence_version": evidence_version,
        "approvals": [approval] if approval else [],
        "requests": requests or [],
    }
    return {"state": state, "verification": record}


class TestWhenAnApprovalCanBeExecuted:
    def executable(self, case, approval_id="APR-1"):
        return evidence.approval_is_executable(case, approval_id)

    def approval(self, **extra):
        return {"approval_id": "APR-1", "status": "VALID", "evidence_version": 1, **extra}

    def test_a_valid_approval_on_an_approved_case_is_executable(self):
        approval, reason = self.executable(case_with(self.approval()))
        assert approval["approval_id"] == "APR-1" and reason is None

    def test_an_unknown_approval_is_not_found(self):
        assert self.executable(case_with(self.approval()), "APR-9") == (None, "approval not found")

    def test_an_approval_already_used_or_cancelled_is_not_valid(self):
        for status in ("EXECUTED", "SUPERSEDED", "CLAIMING-LOST"):
            _, reason = self.executable(case_with(self.approval(status=status)))
            assert reason == f"approval is {status}, not VALID"

    def test_an_interrupted_execution_may_be_resumed_only_while_the_case_is_executing(self):
        claiming = self.approval(status="CLAIMING")
        assert self.executable(case_with(claiming, state="EXECUTING"))[1] is None
        _, reason = self.executable(case_with(claiming, state="APPROVED"))
        assert reason == "approval is CLAIMING but the case is APPROVED, not EXECUTING"

    def test_a_valid_approval_needs_the_case_to_be_approved_or_a_failed_execution(self):
        assert self.executable(case_with(self.approval(), state="EXECUTION_FAILED"))[1] is None
        _, reason = self.executable(case_with(self.approval(), state="HELD_FOR_REVIEW"))
        assert reason == "case is HELD_FOR_REVIEW, not APPROVED or EXECUTION_FAILED"

    def test_an_approval_for_older_evidence_is_refused_and_says_both_versions(self):
        _, reason = self.executable(case_with(self.approval(evidence_version=1), evidence_version=2))
        assert reason == "approval was for evidence v1; the case is now v2"

    def test_a_request_for_documents_still_open_blocks_execution(self):
        _, reason = self.executable(case_with(self.approval(), requests=[{"request_id": "R", "status": "OPEN"}]))
        assert reason == "a request for documents is still open"
