"""
The runner runs a `verify_only` task without a model: its test_commands run once, the output
is the logged result, and the task runs again on every invocation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "orchestrator"))
import automation_runner as runner  # noqa: E402


def _plan(command: str) -> str:
    # The markers are joined from parts so that this file, when it is quoted inside a plan,
    # does not read as a task of that plan.
    return (
        "<!-- TASK" + "_START: V -->\n## Meta\n- title: a check\n- verify_only: true\n"
        f"- test_commands:\n  - {command}\n\n## Context\nNothing to implement.\n"
        + "<!-- TASK" + "_END -->\n"
    )


COUNTING_PLAN = _plan('python -c "open(\'count.txt\', \'a\').write(\'x\')"')
FAILING_PLAN = _plan('python -c "raise SystemExit(3)"')


def _run(tmp_path: Path, plan_text: str) -> int:
    plan = tmp_path / "plan.md"
    plan.write_text(plan_text, encoding="utf-8")
    return runner.main(["--repo", str(tmp_path), "--plan", str(plan)])


def _checkpoint(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "orchestrator" / "checkpoint.json").read_text(encoding="utf-8"))


def test_the_commands_run_without_a_model_and_run_again_each_time(tmp_path):
    assert _run(tmp_path, COUNTING_PLAN) == 0
    assert (tmp_path / "count.txt").read_text(encoding="utf-8") == "x"
    assert _run(tmp_path, COUNTING_PLAN) == 0
    assert (tmp_path / "count.txt").read_text(encoding="utf-8") == "xx"
    log = (tmp_path / "orchestrator" / "runs" / "V" / "attempt_1.log").read_text(encoding="utf-8")
    assert "=== TESTS ===" in log
    assert "=== RESULT ===\nOK" in log
    state = _checkpoint(tmp_path)["tasks"]["V"]
    assert state["status"] == "done" and state["attempts"] == 1


def test_a_failing_command_is_one_failed_attempt_with_its_output_logged(tmp_path):
    assert _run(tmp_path, FAILING_PLAN) == 1
    log = (tmp_path / "orchestrator" / "runs" / "V" / "attempt_1.log").read_text(encoding="utf-8")
    assert "exit code 3" in log
    assert "=== RESULT ===\nTESTS FAILED" in log
    state = _checkpoint(tmp_path)["tasks"]["V"]
    assert state["status"] == "failed" and state["attempts"] == 1
