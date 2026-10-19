"""
approve() enforces the reason for a release over contradicting papers itself, not only through the exception
operation that checks it first: a caller that reaches approve() directly with a blank note must be refused.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import test_evidence_eval_approve as approval_tests  # noqa: E402
from test_evidence_eval_approve import REVIEWER, run  # noqa: E402
from vf_logistics import evidence  # noqa: E402


class TestTheNoteIsEnforcedByApproveItself:
    def setup_method(self):
        self.papers = approval_tests.TestReleasingAgainstContradictingPapers()
        self.papers.setup_method()
        self.papers._contradicted()

    def teardown_method(self):
        self.papers.teardown_method()

    @pytest.mark.parametrize("note", ["", "   ", None])
    def test_a_blank_note_is_400_and_the_case_stays_escalated(self, note):
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.approve(
                "CASE-1", "release", REVIEWER, note=note, waived=["contradiction:certificate_country"],
                actor_auth="password",
            ))
        assert raised.value.status == 400
        assert "requires a note explaining the exception" in raised.value.message
        assert self.papers.stored()["state"] == "ESCALATED"
