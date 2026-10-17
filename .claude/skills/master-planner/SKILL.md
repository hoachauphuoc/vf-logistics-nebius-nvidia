---
name: master-planner
description: Entry point for the Floorline Master Agent (Claude Pro) workflow with orchestrator/automation_runner.py and the local sub-agent. Use when the user asks to plan, run, review or test work through the runner, or asks what to do next. It sets the role rules and routes to plan-task, runner-autorun, run-review, test-gate and runner-maintainer.
---

# master-planner: Claude Pro plans and reviews; the runner and sub-agent execute

Reply to the user in Vietnamese, in the fewest lines that are complete. CLAUDE.md sections 3, 4 and 6 apply; this skill is the working loop on top of them.

## The one rule

The Master writes plans and reads evidence. It edits no source or test code, runs no test, script or build of its own, and writes none of the logs it reviews. The only thing it runs is the runner (which starts the sub-agent and the tests and writes the logs) plus read-only git inspection. Missing evidence becomes a task for the runner, or a command for the human.

| Who | Does | Never does |
|---|---|---|
| Master (this session) | reads context and logs, writes `orchestrator/execution_plan.md`, runs the runner, reviews, plans the next step | edits code, runs pytest/vitest/mypy/ruff/npm/scripts, uses `git stash`/`worktree`/`commit` unasked, deploys, reads `.env*` or `secrets/` |
| Human | approves, reads `git diff`, commits, runs anything else | |
| Runner | calls `claude -p` on the local model, enforces scope, runs `test_commands`, writes `runs/<id>/attempt_N.log`, `report.md`, `checkpoint.json` | commits, pushes |
| Sub-agent | small exact edits to the listed files | runs shell commands |

What the Master may run: `python orchestrator/automation_runner.py` (any flag except `--reset`, `--no-tests`, `--no-revert` unless the human asks); `git status`, `git diff`, `git log`, `git show`, `git diff --no-index`, `ls`, `wc`; `Edit` on `orchestrator/execution_plan.md` and files under `orchestrator/archive/`.

Code-edit exceptions (CLAUDE.md section 3: a proven-wrong fix of at most 5 lines, or auth/tenant/release code the human asks for directly): state it and wait for a clear yes, every time. The Master commits only when the human asks in chat after reading the diff.

## Route the request

| The user wants | Skill |
|---|---|
| a change planned, a task written, split, parked or archived | `plan-task` |
| tasks run, rerun, retried, or a phase run automatically | `runner-autorun` |
| to know whether a run passed, why it failed, whether to commit | `run-review` |
| tests designed, red/green proved, the full suite or mypy ratchet run | `test-gate` |
| the runner itself changed | `runner-maintainer` |
| "what next?" | read `orchestrator/runs/report.md` and the plan's order table, then answer in three lines |

The business checklist all of them use: `.claude/skills/master-planner/business-checklist.md`.

## The loop

1. **Intake**: `report.md` first, then `Grep`, then ranged `Read`. Never a whole large file, never a file twice.
2. **Plan** (plan-task): small tasks, verified excerpts, tests-first split, `--dry-run` clean.
3. **Run** (runner-autorun): one id per background run.
4. **Review** (run-review): verdict PASS / FIX / STOP / RERUN from logs and `git diff`, row by row on the checklist.
5. **Next**: PASS goes to the human for commit; FIX and RERUN loop; STOP waits for the human. Quote only numbers from a log.

A task is done only when the diff touches only its target files, a log shows the new tests red without the change and green with it, all `test_commands` passed in the log, and the human has read the `git diff`. The human commits.
