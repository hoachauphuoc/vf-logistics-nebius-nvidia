---
name: runner-maintainer
description: Plan a change to orchestrator/automation_runner.py itself (new flag, task field, log format, CLI call, scope or retry behaviour) without breaking its safety guarantees. Use when the user asks to update, extend or fix the runner, or when a run exposed a runner limitation.
---

# runner-maintainer: change the runner through the runner

Reply in Vietnamese, in the fewest lines that are complete. The runner is code: the Master plans its change as tasks (plan-task skill) and the sub-agent edits it. The running process has already loaded the old file, so a task may edit `automation_runner.py`; the change takes effect from the next run.

## Guarantees no runner change may weaken (a change that touches one goes to the human first)

| # | Guarantee | Code |
|---|---|---|
| R1 | Never commits, pushes or stashes | no `git commit/push/stash` anywhere in the file |
| R2 | The sub-agent cannot run shell commands or reach the web | `ALLOWED_TOOLS`, `DISALLOWED_TOOLS`, `claude_command` |
| R3 | Edits outside `target_files` are reported and reverted | `enforce_scope`, `git_state`, `in_scope` |
| R4 | A failed attempt restores the target files | `snapshot`, `restore`, `run_task` |
| R5 | A task is "done" only after its `test_commands` passed; any error, timeout or non-zero exit is a failure | `run_task`, `run_tests`, `run_verify_task` |
| R6 | The plan fails closed: a malformed task is a `PLAN ERROR`, never a guess | `parse_plan`, `_validate` |
| R7 | A changed task body reruns; an unchanged failed task does not rerun unasked | `body_hash`, the loop in `main` |
| R8 | Every attempt writes a full log; the report lists every task | `attempt_N.log`, `write_report` |
| R9 | The sub-agent talks only to the local Ollama endpoint, with no real API key | `sub_agent_env` |
| R10 | Standard library only | imports at the top |

## How to plan it

1. Locate the code with `Grep -n "^def \|^class "` on the runner, then ranged `Read`. Do not read the whole file.
2. Split by behaviour: parser changes (`parse_plan`, `_validate`, `Task`) and execution changes (`run_task`, `run_verify_task`, `main`) are separate tasks, as VO1/VO2 were.
3. Tests go in `tests/test_automation_runner_<topic>.py`, in the style of `tests/test_automation_runner_verify_plan.py` (parser, pure) and `tests/test_automation_runner_verify_run.py` (runs with `tmp_path`, no model). A test must never call the real claude CLI or Ollama.
4. Tests-first (test-gate): `<ID>t` proves red, `<ID>c` makes it green.
5. Every task's `test_commands` include all runner tests: `python -m pytest tests/test_automation_runner_verify_plan.py tests/test_automation_runner_verify_run.py tests/test_automation_runner_<topic>.py -q`, plus `python -m ruff check orchestrator/ --select E,F,W --ignore E501,E402,W291,W293`.
6. After the code task: `python orchestrator/automation_runner.py --check` and `--dry-run` (runner-autorun) must still pass on the real plan.
7. Update the docstring usage block at the top of the runner and the flag table in the runner-autorun skill in the same change.

## Known gaps worth a task (check they are still open before planning)

- A rerun overwrites `attempt_1.log` but leaves a higher-numbered log from an earlier run; the log header has no run timestamp, so a stale log can be read as current.
- A file already dirty before a task is not reverted on a scope violation (`enforce_scope` skips it); consider failing the task harder or refusing to start on dirty target neighbours.
- Glob `target_files` are not snapshotted or restored; consider rejecting globs in `_validate`.
- verify_only commands have no scope check.
