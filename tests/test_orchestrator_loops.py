"""
The loops that drive cases forward: one worker tick, the request-driven chain, the drain, the background
worker. Each must count what it did, stop when a reviewer or a reset got there first, and never let one bad
case stop the rest.
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_evidence_eval_approve import Base, run  # noqa: E402
from vf_logistics import orchestrator  # noqa: E402
from vf_logistics.store import OptimisticLockError  # noqa: E402


def lock_error(case_id="CASE-1"):
    return OptimisticLockError(case_id, 1, 2)


@pytest.fixture(autouse=True)
def fresh_stats():
    before = dict(orchestrator._stats)
    yield
    orchestrator._stats.clear()
    orchestrator._stats.update(before)


class TestTick(Base):
    def test_with_nothing_waiting_it_moves_nothing(self):
        with patch.object(orchestrator, "advance", new=AsyncMock()) as advance:
            assert run(orchestrator.tick()) == 0
        advance.assert_not_called()

    def test_each_claimed_case_is_advanced_once_and_counted(self):
        self.put("CASE-1", state="INGESTED")
        self.put("CASE-2", state="INGESTED")
        before = orchestrator._stats["advanced"]
        with patch.object(orchestrator, "advance", new=AsyncMock(side_effect=lambda c: c)) as advance:
            assert run(orchestrator.tick()) == 2
        assert advance.call_count == 2
        assert orchestrator._stats["advanced"] == before + 2

    def test_no_more_than_the_concurrency_limit_are_claimed(self):
        for i in range(5):
            self.put(f"CASE-{i}", state="INGESTED")
        with patch.object(orchestrator, "advance", new=AsyncMock(side_effect=lambda c: c)), \
                patch.object(orchestrator, "MAX_CONCURRENT", 2):
            assert run(orchestrator.tick()) == 2

    def test_a_case_a_reviewer_changed_meanwhile_is_superseded_not_failed(self):
        self.put(state="INGESTED")
        failed = orchestrator._stats["failed"]
        with patch.object(orchestrator, "advance", new=AsyncMock(side_effect=lock_error())), \
                patch.object(orchestrator, "_superseded", new=AsyncMock()) as superseded, \
                patch.object(orchestrator, "_fail", new=AsyncMock()) as fail:
            assert run(orchestrator.tick()) == 1
        superseded.assert_called_once()
        fail.assert_not_called()
        assert orchestrator._stats["failed"] == failed

    def test_a_case_that_raises_is_failed_and_the_others_still_run(self):
        self.put("CASE-1", state="INGESTED")
        self.put("CASE-2", state="INGESTED")
        failed = orchestrator._stats["failed"]

        async def advance(case):
            if case["case_id"] == "CASE-1":
                raise RuntimeError("model down")
            return case

        with patch.object(orchestrator, "advance", new=AsyncMock(side_effect=advance)) as moved, \
                patch.object(orchestrator, "_fail", new=AsyncMock()) as fail:
            assert run(orchestrator.tick()) == 2
        assert moved.call_count == 2
        assert fail.call_args.args[0]["case_id"] == "CASE-1"
        assert str(fail.call_args.args[1]) == "model down"
        assert orchestrator._stats["failed"] == failed + 1


class TestAdvanceUntilTerminal(Base):
    def chain(self, case, advance):
        with patch.object(orchestrator, "advance", new=AsyncMock(side_effect=advance)) as mock:
            return run(orchestrator.advance_until_terminal(case)), mock

    def test_it_runs_until_the_case_stops_being_actionable(self):
        self.put(state="INGESTED")
        states = iter(["SPECIALISTS_DONE", "AUTO_CLEARED"])

        async def advance(case):
            case = {**case, "state": next(states)}
            await self.store.put_case(case)
            return case

        done, mock = self.chain(self.stored(), advance)
        assert done["state"] == "AUTO_CLEARED"
        assert mock.call_count == 2

    def test_a_case_that_is_not_actionable_is_returned_untouched(self):
        self.put(state="AUTO_CLEARED")
        done, mock = self.chain(self.stored(), lambda c: c)
        assert done["state"] == "AUTO_CLEARED"
        mock.assert_not_called()

    def test_a_case_deleted_mid_chain_ends_the_chain(self):
        self.put(state="INGESTED")

        async def advance(case):
            self.store._cases.clear()
            return {**case, "state": "SPECIALISTS_DONE"}

        done, mock = self.chain(self.stored(), advance)
        assert mock.call_count == 1
        assert done["state"] == "SPECIALISTS_DONE"

    def test_a_reviewer_decision_in_the_middle_stops_the_chain_before_the_next_step(self):
        self.put(state="INGESTED")

        async def advance(case):
            await self.store.put_case({**await self.store.get_case("CASE-1"), "state": "RELEASED_BY_HUMAN"})
            return {**case, "state": "SPECIALISTS_DONE"}

        done, mock = self.chain(self.stored(), advance)
        assert mock.call_count == 1
        assert done["state"] == "RELEASED_BY_HUMAN"

    def test_a_lock_conflict_stops_the_chain_and_marks_the_case_superseded(self):
        self.put(state="INGESTED")
        with patch.object(orchestrator, "_superseded", new=AsyncMock()) as superseded:
            _, mock = self.chain(self.stored(), AsyncMock(side_effect=lock_error()))
        superseded.assert_called_once()
        assert mock.call_count == 1

    def test_an_exception_fails_the_case_and_stops(self):
        self.put(state="INGESTED")
        failed = orchestrator._stats["failed"]
        with patch.object(orchestrator, "_fail", new=AsyncMock()) as fail:
            _, mock = self.chain(self.stored(), AsyncMock(side_effect=RuntimeError("boom")))
        assert fail.call_count == 1 and mock.call_count == 1
        assert orchestrator._stats["failed"] == failed + 1

    def test_the_step_ceiling_bounds_a_case_that_never_settles(self):
        self.put(state="INGESTED")
        with patch.object(orchestrator, "MAX_CHAIN_STEPS", 3):
            _, mock = self.chain(self.stored(), lambda c: c)
        assert mock.call_count == 3


class TestDrain(Base):
    def test_it_runs_each_claimed_case_to_the_end_and_lists_them(self):
        self.put("CASE-1", state="INGESTED")
        self.put("CASE-2", state="INGESTED")
        with patch.object(orchestrator, "advance_until_terminal", new=AsyncMock(side_effect=lambda c: c)):
            assert run(orchestrator.drain(max_cases=5)) == {"drained": 2, "case_ids": ["CASE-1", "CASE-2"]}

    def test_it_stops_at_the_limit(self):
        for i in range(3):
            self.put(f"CASE-{i}", state="INGESTED")
        with patch.object(orchestrator, "advance_until_terminal", new=AsyncMock(side_effect=lambda c: c)):
            assert run(orchestrator.drain(max_cases=1))["drained"] == 1

    def test_an_empty_board_drains_nothing(self):
        assert run(orchestrator.drain()) == {"drained": 0, "case_ids": []}


class TestWorkerLoop:
    def loop_once(self, tick):
        """Run the loop for exactly one pass: the sleep that ends it is the signal."""
        sleeps = []

        async def stop(seconds):
            sleeps.append(seconds)
            raise asyncio.CancelledError

        with patch.object(orchestrator, "tick", new=tick), patch.object(asyncio, "sleep", new=stop):
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(orchestrator.worker_loop())
        return sleeps

    def test_after_work_it_comes_straight_back(self):
        assert self.loop_once(AsyncMock(return_value=2)) == [0.1]

    def test_when_idle_it_waits_the_poll_interval(self):
        assert self.loop_once(AsyncMock(return_value=0)) == [orchestrator.POLL_SECONDS]

    def test_a_tick_that_raises_is_recorded_and_the_loop_survives(self):
        errors = orchestrator._stats["tick_errors"]
        sleeps = self.loop_once(AsyncMock(side_effect=ValueError("store down")))
        assert sleeps == [orchestrator.POLL_SECONDS]
        assert orchestrator._stats["tick_errors"] == errors + 1
        assert orchestrator._stats["last_tick_error"] == "ValueError: store down"
        assert orchestrator._stats["started_at"]


class TestStartWorker:
    def test_outside_poll_mode_nothing_is_scheduled(self):
        with patch.object(orchestrator, "WORKER_MODE", "ondemand"), \
                patch.object(asyncio, "run_coroutine_threadsafe") as schedule:
            orchestrator.start_worker(MagicMock())
        schedule.assert_not_called()

    def test_in_poll_mode_the_loop_is_scheduled_on_the_given_loop(self):
        loop = MagicMock()
        with patch.object(orchestrator, "WORKER_MODE", "poll"), patch.object(orchestrator, "_worker_task", None), \
                patch.object(orchestrator, "worker_loop", new=MagicMock(return_value="coro")), \
                patch.object(asyncio, "run_coroutine_threadsafe", return_value="task") as schedule:
            orchestrator.start_worker(loop)
            assert orchestrator._worker_task == "task"
        schedule.assert_called_once_with("coro", loop)

    def test_a_loop_already_running_is_not_started_twice(self):
        running = MagicMock()
        running.done.return_value = False
        with patch.object(orchestrator, "WORKER_MODE", "poll"), patch.object(orchestrator, "_worker_task", running), \
                patch.object(asyncio, "run_coroutine_threadsafe") as schedule:
            orchestrator.start_worker(MagicMock())
        schedule.assert_not_called()
