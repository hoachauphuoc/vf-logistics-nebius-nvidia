"""
The sub-agent is started with --disable-slash-commands: the Master's skills in .claude/skills/ must
not reach the local model, where they cost tokens on every call and invite it to act as the Master.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "orchestrator"))
import automation_runner as runner  # noqa: E402


def test_the_sub_agent_starts_with_skills_disabled(monkeypatch):
    monkeypatch.delenv("CLAUDE_EXTRA_ARGS", raising=False)
    cmd = runner.claude_command("claude", 40)
    assert "--disable-slash-commands" in cmd


def test_the_tool_limits_stay_in_the_command(monkeypatch):
    monkeypatch.delenv("CLAUDE_EXTRA_ARGS", raising=False)
    cmd = runner.claude_command("claude", 40)
    assert cmd[:2] == ["claude", "-p"]
    assert cmd[cmd.index("--allowedTools") + 1] == runner.ALLOWED_TOOLS
    assert cmd[cmd.index("--disallowedTools") + 1] == runner.DISALLOWED_TOOLS
    assert cmd[cmd.index("--max-turns") + 1] == "40"


def test_extra_args_still_come_last(monkeypatch):
    monkeypatch.setenv("CLAUDE_EXTRA_ARGS", "--verbose")
    cmd = runner.claude_command("claude", 40)
    assert cmd[-1] == "--verbose"
