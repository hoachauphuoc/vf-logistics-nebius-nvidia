"""
A plan task with `verify_only: true` needs no Prompt and no target_files: it only runs its
test_commands. It still needs at least one command, and an ordinary task still needs a prompt.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "orchestrator"))
import automation_runner as runner  # noqa: E402


def _plan(task_id: str, meta: str) -> str:
    # The markers are joined from parts so that this file, when it is quoted inside a plan,
    # does not read as a task of that plan.
    return (
        "<!-- TASK" + f"_START: {task_id} -->\n## Meta\n{meta}\n## Context\nNothing to implement.\n"
        + "<!-- TASK" + "_END -->\n"
    )


VERIFY_PLAN = _plan("V", '- title: count the runs\n- verify_only: true\n- test_commands:\n  - python -c "print(1)"\n')
NO_COMMANDS_PLAN = _plan("V", "- title: nothing to run\n- verify_only: true\n")
NO_PROMPT_PLAN = _plan(
    "W", '- title: an ordinary task without a prompt\n- target_files:\n  - a.py\n- test_commands:\n  - python -c "print(1)"\n',
)


def test_a_verify_only_task_needs_no_prompt_and_no_target_files():
    (task,) = runner.parse_plan(VERIFY_PLAN)
    assert task.verify_only is True
    assert task.prompt == ""
    assert task.target_files == []
    assert task.test_commands == ['python -c "print(1)"']


def test_a_verify_only_task_still_needs_a_command():
    with pytest.raises(runner.PlanError):
        runner.parse_plan(NO_COMMANDS_PLAN)


def test_an_ordinary_task_still_needs_a_prompt():
    with pytest.raises(runner.PlanError):
        runner.parse_plan(NO_PROMPT_PLAN)
