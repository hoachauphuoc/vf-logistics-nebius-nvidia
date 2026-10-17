---
name: plan-task
description: Write, split or fix tasks in orchestrator/execution_plan.md for the Floorline sub-agent. Use when the user asks to plan a change, add or edit a task, split a failed task, park a task, or archive finished tasks. Covers the task format the runner parses, excerpt and anchor verification, and prompt rules that make a weak local model succeed.
---

# plan-task: write tasks the runner can parse and a weak model can follow

Reply in Vietnamese, in the fewest lines that are complete. The Master edits only `orchestrator/execution_plan.md` (and `orchestrator/archive/` when archiving); never source or tests. Business rules: `.claude/skills/master-planner/business-checklist.md`.

## Steps

1. **Intake.** Read `orchestrator/runs/report.md`, then `Grep` the code, then `Read` with `offset`/`limit` on the exact range. Never read a whole large file (`app.py`, `orchestrator.py`, `verifier.py`, `store.py`, `README.md`, `execution_plan.md`) and never read a file twice.
2. **Split.** One task = one behaviour, at most 2-3 files. Default order for a behaviour change, so the red/green proof comes from the logs (test-gate skill):
   - `<ID>t` tests only, `test_commands` assert the new tests FAIL (exit code 1);
   - `<ID>c` code only, `depends_on: <ID>t`, `test_commands` run the same tests green plus the neighbouring suite.
   Use `read_only: true` to investigate before a design decision, `verify_only: true` for a pure check.
3. **Verify every excerpt** before it goes in the prompt: `Grep -c` for uniqueness of each anchor line, ranged `Read` for the verbatim text. Check every name the sub-agent will use exists (`Grep -n "def name"`); list them in the prompt with their line ("`Base` already exists at line 45").
4. **Write** the task with `Edit` (keeps line endings). Append new tasks after the last `<!-- TASK_END -->` and add a row to the order table at the top. Never rewrite the whole plan.
5. **Validate** with the parser: `python orchestrator/automation_runner.py --dry-run` (a `PLAN ERROR:` line names the task and the cause). Fix and repeat.
6. **Reply**: plan path, task ids, the run command (`--only <ID>t` then `--only <ID>c`), three-line summary.

## Task format (what `parse_plan` and `_validate` accept)

```
<!-- TASK_START: ID -->
## Meta
- title: one line
- depends_on:
  - OTHER_ID
- target_files:
  - path/to/file
- test_commands:
  - python -m pytest tests/test_x.py -q
  - [frontend] npx vitest run src/path/file.test.tsx
- timeout_sec: 300
- max_retries: 1

## Context
Why the change exists; what must not be touched.

## Prompt
``````text
ID. One sentence of what to do.
FILES YOU MAY EDIT (only these): ...
verbatim excerpts, exact change, tests as real code
DONE WHEN: ...
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if an excerpt does not match the file.
``````
<!-- TASK_END -->
```

Parser facts that bite:
- ID: letters, digits, `_ . -`. Duplicate ids and a `depends_on` that is unknown or listed later are a `PLAN ERROR`.
- List items must be INDENTED (`  - item`) under their `key:` line. Backticks around values are stripped.
- `[dir] cmd` runs `cmd` in `repo/dir`. Commands run with `shell=True` (cmd.exe on Windows): no bash-only syntax.
- Normal tasks need a prompt, `target_files` and `test_commands`. `read_only` needs only a prompt. `verify_only` needs only `test_commands`.
- The prompt is the FIRST fenced block under `## Prompt`; use a longer fence (6 backticks) when the prompt itself contains fences.
- Defaults if omitted: `timeout_sec` 180, `max_retries` 2 (three attempts). Set both explicitly.
- No glob in `target_files`: a glob target is not snapshotted, so a failed attempt is not restored.
- Editing a task body changes its hash and the runner reruns it. Leave done tasks alone.
- To park a task, rename its markers to `PARKED_TASK_START` / `PARKED_TASK_END` and write why in the plan header.

## Prompt rules for a weak model

- Anchors for an edit are ONE line, exact, unique (`Grep -c` = 1). Many files are CRLF: multi-line anchors fail. "Add at the end of the file" = anchor on the last existing line, and say "never at the top".
- Say what stays next to what changes ("the `ev_version > 0` check must stay"). "Replace" is read as permission to delete.
- It cannot run commands: no "run the tests", "git status", "compare with baseline".
- Tests are real code in the prompt, asserting status code AND key message phrase (S5), the second path for re-issues (S6), the stored record for overrides (S3).
- Short prompts. Size `timeout_sec` to the edit: 300-420 small, 600 for a long paste. `max_retries: 1` unless retries are known to help.
- A verbatim copy of a long file: first `test_command` is a hash check, under about 100 lines per task.
- Never plan a change that fails a row I1-I6 of the business checklist. If the request needs one, stop and ask the human.

## After a task failed twice

Stop re-planning the same prompt. Decide which it was: prompt too big, excerpt wrong, or design unclear. Then split the task, fix the excerpt from the real file, or ask the human for the design decision and park the task.

## Archiving (keeps the plan cheap to read)

After the human commits a phase, move its done tasks verbatim to `orchestrator/archive/<plan id>.md` and keep one line per task in the order table ("A1 done, archived, commit e45c2d9"). The runner only knows tasks still in the plan, so archive only tasks that nothing pending `depends_on`.
