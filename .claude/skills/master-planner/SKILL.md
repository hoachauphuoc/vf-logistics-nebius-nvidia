---
name: master-planner
description: Entry point for the Floorline Master Agent (Claude Pro) workflow with orchestrator/automation_runner.py and the local sub-agent. Use when the user asks to plan, run, review or test work through the runner, or asks what to do next. It sets the role rules and routes to plan-task, runner-autorun, run-review, test-gate and runner-maintainer.
---

# master-planner: the Master plans and reviews; the runner executes everything

Reply to the user in Vietnamese, in the fewest lines that are complete. CLAUDE.md sections 3, 4 and 6 apply; this skill is the working loop on top of them.

## The one rule

The Master has two jobs: write the plan, and review the evidence the runner produced. Every execution goes to the runner: code edits (sub-agent, Gemma4), tests, builds, scripts, measurements, git inspection, red/green proofs. The Master starts the runner, which is the hand-off itself, and runs nothing else.

| Who | Does | Never does |
|---|---|---|
| Master (this session) | reads files with `Read`/`Grep`/`Glob`; writes `orchestrator/execution_plan.md`; starts the runner; reads `report.md`, `attempt_N.log`, `attempt_N.diff`, `answer.md`; gives a verdict; plans the next step | edits code or tests; runs pytest, vitest, mypy, ruff, npm, scripts, `python -c`, hashing, copies, `git status/diff/log`, `git commit/push/stash/worktree`; deploys; reads `.env*` or `secrets/` |
| Runner | calls the sub-agent, enforces scope, runs `test_commands` and `verify_only` commands, writes every log and diff | commits, pushes |
| Sub-agent (Gemma4) | small exact edits to the listed files | runs shell commands |
| Human | approves, reads the diff, commits, pushes | |

What the Master may run, and nothing more: `python orchestrator/automation_runner.py` with `--check`, `--dry-run`, `--only <ids>`, `--retry-failed`, `--keep-failed`, `--timeout`. Never `--reset`, `--no-tests`, `--no-revert` unless the human asks. What the Master may write: `orchestrator/execution_plan.md` and `orchestrator/archive/`.

Anything the Master needs to see that is not in a log yet (git state, a test count, a measurement, whether a test fails on the old code) becomes a task: `verify_only` for a pure check, a tests-first pair for a red/green proof (test-gate). The Master never produces evidence itself, so a review only trusts what the runner logged.

Code-edit exceptions (CLAUDE.md section 3) are for the human to grant in chat, each time; even then prefer a plan task. Commits are the human's.

## Route the request

| The user wants | Skill |
|---|---|
| a change planned, a task written, split, parked or archived | `plan-task` |
| tasks run, rerun, retried, or a phase run automatically | `runner-autorun` |
| to know whether a run passed, why it failed, whether it is ready to commit | `run-review` |
| tests designed, red/green proved, the full suite or mypy ratchet run | `test-gate` |
| the runner itself changed | `runner-maintainer` |
| "what next?" | read `orchestrator/runs/report.md` and the plan's order table, then answer in three lines |

The business checklist all of them use: `.claude/skills/master-planner/business-checklist.md`.

## The loop

1. **Intake**: `report.md` first, then `Grep`, then ranged `Read`. Never a whole large file, never a file twice.
2. **Plan** (plan-task): small tasks, verified excerpts, tests-first split, `--dry-run` clean.
3. **Run** (runner-autorun): one id per background run.
4. **Review** (run-review): verdict PASS / FIX / STOP / RERUN from the runner's logs and diffs, row by row on the checklist.
5. **Next**: PASS goes to the human for commit; FIX and RERUN loop, at most 2 rounds per problem (runner-autorun, auto-run loop); STOP waits for the human. Quote only numbers from a log.

A task is done only when its logged diff touches only its target files, a log shows the new tests red without the change and green with it, all `test_commands` passed in the log, and the human has read the diff. The human commits.
