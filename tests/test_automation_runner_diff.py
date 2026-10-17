"""
Every attempt writes runs/<ID>/attempt_N.diff: each target file against the task's snapshot. The
Master reviews from this file and runs no git itself, so it must cover untracked files and keep what
a failed attempt wrote, which the runner restores afterwards.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "orchestrator"))
import automation_runner as runner  # noqa: E402


def _plan(command: str) -> str:
    # The markers are joined from parts so that this file, when it is quoted inside a plan,
    # does not read as a task of that plan.
    return (
        "<!-- TASK" + "_START: E -->\n## Meta\n- title: an edit\n- target_files:\n  - a.py\n"
        f"- test_commands:\n  - {command}\n- max_retries: 0\n\n## Prompt\nSet x to 2.\n"
        + "<!-- TASK" + "_END -->\n"
    )


def _fake_sub_agent(cmd, stdin_text, cwd, env, timeout):
    (Path(cwd) / "a.py").write_text("x = 2\n", encoding="utf-8")
    return 0, "a.py: x is 2", "", False


def _run(tmp_path: Path, monkeypatch, command: str) -> int:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    plan = tmp_path / "plan.md"
    plan.write_text(_plan(command), encoding="utf-8")
    monkeypatch.setattr(runner, "find_claude", lambda: "claude")
    monkeypatch.setattr(runner, "run_with_timeout", _fake_sub_agent)
    return runner.main(["--repo", str(tmp_path), "--plan", str(plan)])


def _diff(tmp_path: Path) -> str:
    return (tmp_path / "orchestrator" / "runs" / "E" / "attempt_1.diff").read_text(encoding="utf-8")


def test_a_passing_attempt_writes_the_diff_of_its_target_file(tmp_path, monkeypatch):
    assert _run(tmp_path, monkeypatch, 'python -c "print(1)"') == 0
    diff = _diff(tmp_path)
    assert "--- a/a.py" in diff and "+++ b/a.py" in diff
    assert "-x = 1" in diff
    assert "+x = 2" in diff


def test_a_failed_attempt_keeps_its_diff_after_the_files_are_restored(tmp_path, monkeypatch):
    assert _run(tmp_path, monkeypatch, 'python -c "raise SystemExit(3)"') == 1
    assert "+x = 2" in _diff(tmp_path)
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x = 1\n"


def test_a_new_file_is_shown_as_added_lines(tmp_path):
    snap = runner.snapshot(tmp_path, ["new.py"])
    (tmp_path / "new.py").write_text("print(1)\n", encoding="utf-8")
    runner.write_diff(tmp_path, snap, tmp_path / "out.diff")
    diff = (tmp_path / "out.diff").read_text(encoding="utf-8")
    assert "+++ b/new.py" in diff
    assert "+print(1)" in diff
