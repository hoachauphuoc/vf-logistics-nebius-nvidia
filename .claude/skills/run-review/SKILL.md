---
name: run-review
description: Review what an automation_runner.py run and the sub-agent did, from the runner's logs and diffs, against the Floorline business checklist. Use after a runner run ends, when the user asks whether a task passed, why a task failed or timed out, or whether a phase is ready to commit.
---

# run-review: judge the run from evidence, not from the sub-agent's words

Reply in Vietnamese, in the fewest lines that are complete. Read only, with `Read`/`Grep`: the Master runs no command here, not even git. Checklist: `.claude/skills/master-planner/business-checklist.md`.

## Evidence, in this order

1. `orchestrator/runs/report.md`: status, attempts, tests, files changed, first error line per task.
2. `orchestrator/checkpoint.json` only for the task under review (`Grep -n '"<ID>"' -A 15`).
3. `orchestrator/runs/<ID>/attempt_N.log`, with N = the `Attempts` column of the report (a rerun overwrites `attempt_1.log` and leaves older higher-numbered logs behind): `Grep -n "=== SCOPE ===\|=== TESTS ===\|=== RESULT ==="`, then a ranged `Read` of those sections. Skip `=== PROMPT ===` (the Master wrote it). For `read_only` tasks read `runs/<ID>/answer.md` and check every claim against the repo before relying on it.
4. `orchestrator/runs/<ID>/attempt_N.diff`: the change to every target file, new and untracked files included, as the sub-agent left it (also for a failed attempt, before the restore). Then a ranged `Read` of the changed lines in the real file to see the context.
5. When the git state itself is the question (I6: nothing committed), or the task changed the runner itself (the running process has the old code, so it may write no diff): plan a `verify_only` task with `git status --porcelain`, `git log --oneline -3` and `git diff -- <tracked target files>` as its commands, run it, and read its `attempt_1.log`.

## Checks

- **Scope**: the diff touches only `target_files`; no stray blank lines, reformatting or renames; nothing outside the prompt's change.
- **Tests ran**: the `=== TESTS ===` section shows each `test_command` with `exit code 0` and a pass count. Quote the counts from the log; never a number you did not read.
- **Tests mean something**: the new tests assert status code and key phrase (S5), the stored record for overrides (S3), the second path for re-issues (S6). A test that would pass on the old code proves nothing: the red proof is a log from the tests-first task (test-gate).
- **Business checklist**: go row by row, I1-I6 then S1-S12; mark each ok / fail / not applicable / not verified with the file:line or log section.

## Verdict (one of)

| Verdict | Means | Next |
|---|---|---|
| PASS | every applicable row ok with evidence | tell the human it is ready for `git diff` and commit |
| FIX | a standard row failed, code works | plan-task: a small fix task, or the 5-line exception stated to the human first |
| STOP | an invariant row failed or is not verified | stop, report to the human, plan nothing until they decide |
| RERUN | failure was environmental (lock, CLI, Ollama) | runner-autorun with the same command |

## Reading a failure

| Runner message | Usual cause | Fix in the plan |
|---|---|---|
| `NO CHANGE` | anchor not found, or the model chose STOP (read STDOUT) | re-check the anchor against the file, shorten it |
| `SCOPE VIOLATION` | edit outside `target_files` (reverted unless the file was dirty before) | name the allowed files again; add the file only if truly needed |
| `TESTS FAILED` | wrong placement, deleted code, invented name, copy typo | read the first failing line; add "this must stay" and the real names |
| `TIMEOUT` | prompt too long or model stuck; files restored | shorten or split, raise `timeout_sec`, lower `max_retries` |
| `READ-ONLY task, but files were changed` | the model edited during an investigation | restate "change nothing"; rerun |
| `the claude CLI exited with code N` | CLI or Ollama problem | `--check`; ask the human |
| `blocked: depends on X` | X is not done | run or fix X first |
| `PermissionError` on `checkpoint.tmp` | Windows file lock, transient | rerun the same command |
| tests all pass, then `PermissionError ... pytest-current` in `pytest_sessionfinish` | sandboxed session cannot update the `%TEMP%` symlink for `tmp_path` | add `--basetemp=orchestrator/runs/<ID>/pytest-tmp` to that pytest command, rerun |

A failed attempt's files are restored, but `attempt_N.diff` keeps what the sub-agent wrote.
Report: what was read, what was not, the verdict, the next command or task id. Two failures of the same task: stop re-planning it (plan-task, "After a task failed twice").
