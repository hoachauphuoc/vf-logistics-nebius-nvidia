---
name: runner-autorun
description: Run orchestrator/automation_runner.py from the Master (Claude Pro) session, task by task, in the background, and chain run -> review -> next task until a stop condition. Use when the user asks to run, rerun, retry, resume or auto-run plan tasks, or to check that the runner, the claude CLI and Ollama are ready.
---

# runner-autorun: the Master starts the runner, the runner does the work

Reply in Vietnamese, in the fewest lines that are complete. The runner is the ONLY thing the Master runs besides read-only git inspection. Tests, builds and scripts run inside the runner as `test_commands`.

## Before the first run in a session

1. `python orchestrator/automation_runner.py --check` (exit 0 = ready, 2 = not ready). Not ready: report the failing line (claude CLI, Ollama, git) and ask the human to fix it. Do not work around it.
2. `python orchestrator/automation_runner.py --dry-run`: the plan parses, ids and order are what you expect.
3. `git status --porcelain`: a file that was already dirty before a task is NOT reverted when the sub-agent edits it out of scope (`enforce_scope` skips it). If uncommitted work overlaps a task's neighbourhood, ask the human to commit first.

## One run

- Command: `python orchestrator/automation_runner.py --only <ID>` through the **Bash** tool with `run_in_background: true`, one task per call. Tell the human the command first. Wait for the completion notice; never poll and never sleep.
- The runner passes `--disable-slash-commands`, so the Master's skills never reach the sub-agent. No env prefix is needed.
- Before each run, note `git rev-parse HEAD` and the hashes of already-dirty files (`git ls-files -m -o --exclude-standard | xargs sha1sum` into the scratchpad): the runner does not revert edits to files that were dirty before the task, and untracked files have no `git diff`. Save a copy of an untracked target file too, to diff against after the run.
- Several ids in one `--only` run in plan order, sequentially. Prefer one id per call so each diff is reviewed alone.
- The runner skips a task that is done with an unchanged body, and skips one that failed with an unchanged body unless `--retry-failed`. `verify_only` tasks always rerun.

| Flag | When |
|---|---|
| `--retry-failed` | rerun a failed task after its prompt or the code it depends on changed outside the task body |
| `--keep-failed` | the log does not show what the sub-agent wrote; keep its edits to compare. Afterwards the files are dirty: say so and have them restored before the next run |
| `--timeout N` | override `timeout_sec` for this run only |
| `--no-tests`, `--no-revert` | never in auto-run: they turn off the safety checks |
| `--reset` | forgets every task's state. Only when the human asks in chat |

Exit codes: 0 every selected task ok; 1 a task failed, is blocked by a dependency, or was skipped as failed; 2 plan error, unknown id, or claude CLI missing.

## Auto-run loop (when the human asks to "chạy tự động" a phase)

For each id in the phase, in plan order:
1. Run it (above).
2. Review it with the run-review skill.
3. Go on to the next id only if the review passed every row of `.claude/skills/master-planner/business-checklist.md` that applies.

Stop the loop and report to the human when any of these happens:
- a task failed twice (plan-task: diagnose, do not resend the same prompt);
- the diff touches auth, sessions, tenants, release/approval, or the risk floor in a way the task did not name;
- a review row is "not verified" for I1-I6;
- a task is `read_only` and its answer is needed for a design decision;
- the human's phase is done. The Master never commits: list what is ready for the human's `git diff` and commit.

## Permissions

`.claude/settings.json` allows `python orchestrator/automation_runner.py` so the loop does not stop on a prompt. Every other command still asks. If the human removes that rule, each run asks again: that is their choice, keep going one approval at a time.
