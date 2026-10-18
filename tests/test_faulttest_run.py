"""
The fault-test driver (review 2026-10-18, open items 1 and 2): what can be checked without the
deployed service. Its session is the console's wire format, its seed lands in the faulttest tenant
only, and its verdicts read a run correctly, a failing one included.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import faulttest_run as ft  # noqa: E402
from test_console_session import TEST_SECRET, mint  # noqa: E402
from test_evidence_eval_approve import Base  # noqa: E402


def test_the_session_is_the_console_wire_format():
    assert ft.mint_session("op@faulttest.test", TEST_SECRET, now=1_000.0) == mint(
        "op@faulttest.test", secret=TEST_SECRET, exp=1_000.0 + 3600,
    )


class TestTheSeed(Base):
    def test_the_case_needs_an_exception_and_lives_in_the_faulttest_tenant_only(self):
        out = asyncio.run(ft.seed_case("FT-TEST-1"))
        assert out["state"] == "HELD_FOR_REVIEW"
        assert sorted(out["unresolved"]) == sorted(ft.DOCS3)
        assert asyncio.run(self.store.get_case("FT-TEST-1", tenant_id=ft.TENANT)) is not None
        assert asyncio.run(self.store.get_case("FT-TEST-1")) is None


def results(rows):
    return [ok for _, ok, _ in rows]


class TestTheVerdicts:
    def test_a_kill_run_that_held(self):
        rows = ft.kill_verdict("EXECUTING", 0, "RELEASED_BY_HUMAN", ["exec-a", "other"], "exec-a")
        assert results(rows) == [True, True, True]
        assert ft.exit_code(rows) == 0

    def test_a_kill_run_whose_resume_published_again(self):
        rows = ft.kill_verdict("EXECUTING", 0, "RELEASED_BY_HUMAN", ["exec-a", "exec-a"], "exec-a")
        assert results(rows) == [True, True, False]
        assert "2 message(s)" in rows[2][2]
        assert ft.exit_code(rows) == 1

    def test_a_kill_that_came_too_late(self):
        rows = ft.kill_verdict("RELEASED_BY_HUMAN", 1, "RELEASED_BY_HUMAN", ["exec-a"], "exec-a")
        assert results(rows)[0] is False

    def test_a_gateway_504_run_that_held(self):
        rows = ft.gateway_verdict(504, "RELEASED_BY_HUMAN", 409, ["exec-b"], "exec-b")
        assert results(rows) == [True, True, True, True]
        assert ft.exit_code(rows) == 0

    def test_a_504_that_came_from_somewhere_else(self):
        rows = ft.gateway_verdict(200, "RELEASED_BY_HUMAN", 409, ["exec-b"], "exec-b")
        assert results(rows)[0] is False
        assert ft.exit_code(rows) == 1
