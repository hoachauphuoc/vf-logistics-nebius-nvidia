"""
The concurrent-decision race, and the recovery path that made it destructive.

A reviewer released CASE-FULL-20-THINHISTORY in production and the case read
ESCALATED again twenty seconds later. The immutable audit log is what exposed it:

    07:27:18  release_shipment / human_release  actor=seed-operator
    07:27:38  hold_shipment / draft_sar / assign_analyst / publish_decision

Three separate defects had to line up, and each is pinned by a test here:

  1. `OptimisticLockError` was caught by a bare `except Exception` and handed to
     `_fail()`, which treats everything as a retryable fault.
  2. `_fail()` wrote the case WITHOUT `expected_version` -- the only two case
     writes in the orchestrator that skipped the lock -- so the losing
     transition's stale copy overwrote the reviewer's committed decision.
  3. `advance_until_terminal` judged `state in ACTIONABLE` against its own
     in-memory copy, so the chain never noticed the decision at all and kept
     executing the next transition's tools against a released shipment.

These are written against the seam rather than the wire: the point is the
orchestrator's concurrency contract, and reproducing it through HTTP would test
Flask instead.

Class names here use pytest's `Test*` prefix rather than this suite's usual
`*Tests` suffix. The suffix works elsewhere because those classes subclass
`unittest.TestCase`, which pytest collects by type regardless of name; these are
async and take pytest fixtures, so they are collected by name and the project sets
no `python_classes` override. Without the prefix the whole file silently collects
zero tests and passes.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("STORE_BACKEND", "memory")

from vf_logistics import orchestrator, store  # noqa: E402
from vf_logistics.store import MemoryStore, OptimisticLockError  # noqa: E402


@pytest.fixture
def memory_store(monkeypatch) -> MemoryStore:
    """A store isolated from the process-wide singleton."""
    fresh = MemoryStore()
    monkeypatch.setattr(store, "_store", fresh)
    return fresh


def _case(state: str = "INVESTIGATED", **over) -> dict:
    case = {
        "case_id": "CASE-RACE-01",
        "shipment_id": "RACE-01",
        "state": state,
        "shipment": {"shipment_id": "RACE-01", "declared_value": 1000},
        "actions": [],
        "steps": [],
        "attempts": 0,
        "not_before": None,
        "claimed": False,
    }
    case.update(over)
    return case


async def _seed(memory_store: MemoryStore, case: dict) -> dict:
    await memory_store.put_case(case)
    return await memory_store.get_case(case["case_id"])


class TestFailDoesNotClobber:
    """`_fail()` must never overwrite a case that moved on without it."""

    @pytest.mark.asyncio
    async def test_a_stale_failure_cannot_overwrite_a_human_decision(
        self, memory_store
    ):
        stored = await _seed(memory_store, _case())

        # The transition holds this snapshot. Meanwhile a reviewer commits.
        stale = dict(stored)
        decided = dict(stored)
        decided["state"] = "RELEASED_BY_HUMAN"
        await memory_store.put_case(
            decided, expected_version=stored["_version"]
        )

        # The losing transition had already mutated its copy toward ESCALATED,
        # which is exactly what used to get written back.
        stale["state"] = "ESCALATED"
        await orchestrator._fail(stale, RuntimeError("boom"))

        final = await memory_store.get_case("CASE-RACE-01")
        assert final["state"] == "RELEASED_BY_HUMAN"

    @pytest.mark.asyncio
    async def test_a_stale_failure_does_not_increment_attempts_in_the_store(
        self, memory_store
    ):
        stored = await _seed(memory_store, _case())
        stale = dict(stored)
        decided = dict(stored)
        decided["state"] = "BLOCKED_BY_HUMAN"
        await memory_store.put_case(decided, expected_version=stored["_version"])

        await orchestrator._fail(stale, RuntimeError("boom"))

        final = await memory_store.get_case("CASE-RACE-01")
        assert final.get("attempts", 0) == 0

    @pytest.mark.asyncio
    async def test_a_stale_failure_cannot_dead_letter_a_decided_case(
        self, memory_store
    ):
        # One attempt short of the ceiling, so this _fail would dead-letter it.
        stored = await _seed(
            memory_store, _case(attempts=orchestrator.MAX_ATTEMPTS - 1)
        )
        stale = dict(stored)
        decided = dict(stored)
        decided["state"] = "RELEASED_BY_HUMAN"
        await memory_store.put_case(decided, expected_version=stored["_version"])

        await orchestrator._fail(stale, RuntimeError("boom"))

        final = await memory_store.get_case("CASE-RACE-01")
        assert final["state"] == "RELEASED_BY_HUMAN"

    @pytest.mark.asyncio
    async def test_an_uncontested_failure_still_retries(self, memory_store):
        """The guard must not break ordinary failure handling."""
        stored = await _seed(memory_store, _case())

        await orchestrator._fail(stored, RuntimeError("transient"))

        final = await memory_store.get_case("CASE-RACE-01")
        assert final["attempts"] == 1
        assert final["not_before"] is not None
        assert final["state"] == "INVESTIGATED"

    @pytest.mark.asyncio
    async def test_an_uncontested_failure_still_dead_letters_at_the_ceiling(
        self, memory_store
    ):
        stored = await _seed(
            memory_store, _case(attempts=orchestrator.MAX_ATTEMPTS - 1)
        )

        await orchestrator._fail(stored, RuntimeError("persistent"))

        final = await memory_store.get_case("CASE-RACE-01")
        assert final["state"] == "DEAD_LETTER"


class TestSupersededIsNotFailure:
    """A lost race is not a fault of the case."""

    @pytest.mark.asyncio
    async def test_superseded_writes_nothing(self, memory_store):
        stored = await _seed(memory_store, _case())
        before = stored["_version"]

        stale = dict(stored)
        stale["state"] = "ESCALATED"
        await orchestrator._superseded(stale)

        final = await memory_store.get_case("CASE-RACE-01")
        assert final["state"] == "INVESTIGATED"
        assert final["_version"] == before

    @pytest.mark.asyncio
    async def test_superseded_leaves_attempts_alone(self, memory_store):
        """
        Three reviewer decisions in quick succession must not dead-letter a
        healthy case, which is what counting a lost race as an attempt would do.
        """
        stored = await _seed(memory_store, _case())

        for _ in range(orchestrator.MAX_ATTEMPTS + 1):
            await orchestrator._superseded(dict(stored))

        final = await memory_store.get_case("CASE-RACE-01")
        assert final.get("attempts", 0) == 0
        assert final["state"] != "DEAD_LETTER"

    @pytest.mark.asyncio
    async def test_a_lock_conflict_in_the_chain_does_not_reach_fail(
        self, memory_store, monkeypatch
    ):
        stored = await _seed(memory_store, _case())

        async def _conflict(case):
            raise OptimisticLockError(case["case_id"], 1, 2)

        failed: list = []

        async def _record_fail(case, exc):
            failed.append(exc)

        monkeypatch.setattr(orchestrator, "advance", _conflict)
        monkeypatch.setattr(orchestrator, "_fail", _record_fail)

        await orchestrator.advance_until_terminal(dict(stored))

        assert failed == [], "a lock conflict must not be treated as a failure"


class TestChainRereadsTheStore:
    """The loop condition must be judged against the stored state."""

    @pytest.mark.asyncio
    async def test_the_chain_stops_once_a_human_has_decided(
        self, memory_store, monkeypatch
    ):
        """
        The tools, not just the write, must stop. The optimistic lock only guards
        writes -- by the time it fires, hold_shipment has already run.
        """
        stored = await _seed(memory_store, _case())
        transitions: list[str] = []

        async def _advance(case):
            transitions.append(case["state"])
            # First step succeeds and leaves the case actionable, so the chain
            # would ordinarily continue.
            updated = dict(case)
            updated["state"] = "INVESTIGATED"
            await memory_store.put_case(
                updated, expected_version=case["_version"]
            )
            # A reviewer decides between this step and the next.
            decided = await memory_store.get_case(case["case_id"])
            decided["state"] = "RELEASED_BY_HUMAN"
            await memory_store.put_case(
                decided, expected_version=decided["_version"]
            )
            return await memory_store.get_case(case["case_id"])

        monkeypatch.setattr(orchestrator, "advance", _advance)

        result = await orchestrator.advance_until_terminal(dict(stored))

        assert len(transitions) == 1, (
            "the chain ran a second transition after the case was decided"
        )
        assert result["state"] == "RELEASED_BY_HUMAN"

    @pytest.mark.asyncio
    async def test_a_deleted_case_stops_the_chain(
        self, memory_store, monkeypatch
    ):
        """A reset mid-chain must not loop forever on a case that is gone."""
        stored = await _seed(memory_store, _case())
        calls: list[int] = []

        async def _advance(case):
            calls.append(1)
            updated = dict(case)
            await memory_store.put_case(
                updated, expected_version=case["_version"]
            )
            await memory_store.reset()
            return await memory_store.get_case(case["case_id"]) or updated

        monkeypatch.setattr(orchestrator, "advance", _advance)

        await orchestrator.advance_until_terminal(dict(stored))

        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_an_uncontested_chain_still_runs_to_terminal(
        self, memory_store, monkeypatch
    ):
        """The re-read must not break the ordinary path."""
        stored = await _seed(memory_store, _case(state="INGESTED"))
        sequence = ["SPECIALISTS_DONE", "INVESTIGATED", "ESCALATED"]
        seen: list[str] = []

        async def _advance(case):
            seen.append(case["state"])
            updated = dict(case)
            updated["state"] = sequence[len(seen) - 1]
            await memory_store.put_case(
                updated, expected_version=case["_version"]
            )
            return await memory_store.get_case(case["case_id"])

        monkeypatch.setattr(orchestrator, "advance", _advance)

        result = await orchestrator.advance_until_terminal(dict(stored))

        assert seen == ["INGESTED", "SPECIALISTS_DONE", "INVESTIGATED"]
        assert result["state"] == "ESCALATED"


class TestHumanDecisionGuard:
    """The guards that already worked, pinned so they keep working."""

    @pytest.mark.asyncio
    async def test_a_decided_case_cannot_be_decided_again(self, memory_store):
        await _seed(memory_store, _case(state="RELEASED_BY_HUMAN"))

        result = await orchestrator.human_decide(
            "CASE-RACE-01", "block", "someone", "changed my mind"
        )

        assert result["ok"] is False
        assert "not awaiting review" in result["error"]

    @pytest.mark.asyncio
    async def test_terminal_states_are_not_actionable(self):
        """
        The worker query must never select a human-decided case. This is the
        backstop that makes the whole race narrow rather than routine.
        """
        for state in ("RELEASED_BY_HUMAN", "BLOCKED_BY_HUMAN"):
            assert state in orchestrator.TERMINAL
            assert state not in orchestrator.ACTIONABLE
