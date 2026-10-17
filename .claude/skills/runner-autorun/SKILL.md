---
name: runner-autorun
description: Run orchestrator/automation_runner.py from the Master (Claude Pro) session, task by task, in the background, and chain run -> review -> fix round (at most 2 per problem) -> next task until a stop condition. Use when the user asks to run, rerun, retry, resume or auto-run plan tasks, or to check that the runner, the claude CLI and Ollama are ready.
---

# runner-autorun: the Master starts the runner, the runner does the work

Reply in Vietnamese, in the fewest lines that are complete. The runner is the ONLY command the Master runs. Tests, builds, scripts and git inspection run inside the runner as `test_commands` or `verify_only` tasks.

## Before the first run in a session

1. `python orchestrator/automation_runner.py --check` (exit 0 = ready, 2 = not ready). Not ready: report the failing line (claude CLI, Ollama, git) and ask the human to fix it. Do not work around it.
2. `python orchestrator/automation_runner.py --dry-run`: the plan parses, ids and order are what you expect.
3. Read the `git:` line of `--check` ("N changed path(s) before the run"). A file already dirty before a task is reported but NOT reverted when the sub-agent edits it out of scope. If N is not 0 and the phase touches code near uncommitted work, ask the human to commit first. For the exact list, run a `verify_only` task whose command is `git status --porcelain`.

## One run

- Command: `python orchestrator/automation_runner.py --only <ID>` through the **Bash** tool with `run_in_background: true`, one task per call. Tell the human the command first. Wait for the completion notice; never poll and never sleep.
- The runner passes `--disable-slash-commands`, so the Master's skills never reach the sub-agent. No env prefix is needed.
- The Master takes no snapshots, hashes or copies of its own. Evidence of what changed comes from the runner: `=== SCOPE ===` in the log (changed files and violations, including already-dirty files) and `runs/<ID>/attempt_N.diff` (each target file against the task's snapshot, also for untracked files, written before a failed attempt is restored).
- Several ids in one `--only` run in plan order, sequentially. Prefer one id per call so each diff is reviewed alone.
- The runner skips a task that is done with an unchanged body, and skips one that failed with an unchanged body unless `--retry-failed`. `verify_only` tasks always rerun.

| Flag | When |
|---|---|
| `--retry-failed` | rerun a failed task after its prompt or the code it depends on changed outside the task body |
| `--keep-failed` | rarely: `attempt_N.diff` already keeps a failed attempt's edits; use it only to run more checks on those edits in a `verify_only` task. Afterwards the files are dirty: say so and have them restored before the next run |
| `--timeout N` | override `timeout_sec` for this run only |
| `--no-tests`, `--no-revert` | never in auto-run: they turn off the safety checks |
| `--reset` | forgets every task's state. Only when the human asks in chat |

Exit codes: 0 every selected task ok; 1 a task failed, is blocked by a dependency, or was skipped as failed; 2 plan error, unknown id, or claude CLI missing.

## Auto-run loop (when the human asks to "chạy tự động" a phase)

The human's request to auto-run a phase authorizes, for that phase only: running its tasks, and planning and running fix rounds as below. Nothing else (no commit, no new feature, no other phase).

For each id in the phase, in plan order:
1. Run it (above).
2. Review it with the run-review skill: verdict PASS, FIX, RERUN or STOP.
3. **PASS**: go on to the next id.
4. **RERUN** (cause outside the code: Windows lock, sandbox, CLI/Ollama, a wrong `test_command` or excerpt in the task itself): fix only what the cause needs in that task's own Meta or Prompt (plan-task rules), `--dry-run`, run it again. Example: RM1c got `--basetemp` after a `WinError 5` on `pytest-current`.
5. **FIX** (the task passed but the review found a standard row failing, or it failed on its code): plan a fix task `<ID>f1` (then `<ID>f2`) with plan-task, tests-first when it changes behaviour (`<ID>f1t` / `<ID>f1c`), `depends_on` the original, scope no wider than the original's files plus their tests. Run and review it the same way.
6. Write one line per round under the order table of the plan: `<ID> round N: <verdict>, <cause in a few words>, log runs/<id>/attempt_K.log`. The line is the counter, so the limit holds across sessions.

**At most 2 rounds per problem.** A problem is the original task id. Each RERUN or FIX counts as one round; the runner's own `max_retries` attempts inside one run do not count. If round 2 is not PASS, stop: do not plan round 3 (CLAUDE.md section 3). Diagnose in the report whether the prompt was too big, an excerpt was wrong, or the design is unclear, and propose the split or the decision the human must make.

Stop the whole loop and report to the human when any of these happens:
- the 2-round limit is reached for a problem;
- the same first error line comes back after a round (the fix did not touch the cause);
- verdict STOP: a row I1-I6 failed or is not verified, or the diff touches auth, sessions, tenants, release/approval or the risk floor in a way the task did not name;
- the fix would need a file outside the original's scope, a new dependency, a change or deletion of an existing test, or a design decision (CLAUDE.md sections 4 and 6);
- a `read_only` answer is needed for a design decision;
- `--check` fails or the runner exits with code 2 twice;
- the phase is done.

The report: per task the verdict, rounds used, the logs read, and what is ready for the human's `git diff`. The Master never commits in the loop.

## Permissions

`.claude/settings.json` allows `python orchestrator/automation_runner.py` so the loop does not stop on a prompt. Every other command still asks. If the human removes that rule, each run asks again: that is their choice, keep going one approval at a time.
