---
name: test-gate
description: Floorline test standards and how to prove them through the runner. Use when planning the tests for a task, proving new tests fail on the old code (red) and pass on the new (green), running the full verification suite or mypy ratchet as a verify_only task, or deciding whether test evidence in a log is enough.
---

# test-gate: business-grade tests, proved by runner logs

Reply in Vietnamese, in the fewest lines that are complete. The Master never runs pytest, vitest, mypy, ruff or npm itself: every proof below is a task whose output lands in `orchestrator/runs/<ID>/attempt_N.log`.

## What a test must assert (copy the neighbouring tests' helpers and naming)

- **Refusal**: the status code, a key phrase of the message, and that nothing was stored. Real pattern from `tests/test_exception_approval.py:72`:
  ```python
  with pytest.raises(evidence.EvidenceError) as raised:
      run(evidence.approve_exception("CASE-1", REVIEWER, "   ", WAIVED, actor_auth="password"))
  assert raised.value.status == 400
  assert "reason" in raised.value.message
  assert self.stored()["verification"]["approvals"] == []
  ```
- **Override (N04)**: the stored record has `unresolved`, a non-empty `reason`, `approved_by`, and the contradictions.
- **Re-issue (N03)**: the SECOND issue carries document type per link, request id, expiry and tenant, asserted on the re-issued object.
- **Fail closed**: a missing, unreadable or placeholder value gives "not verified"/refusal, one test per such input.
- **Guest**: a one-click session gets 403 on release and approve.
- Test names read as a sentence of the behaviour (`test_it_refuses_when_there_is_nothing_to_waive`).
- Never skip, loosen or delete an existing test. A failing old test means stop and ask the human.

Every pytest command in a task that the Master's session starts gets `--basetemp=orchestrator/runs/<ID>/pytest-tmp`: without it, tests that use `tmp_path` pass and then pytest fails with `WinError 5` on `%TEMP%\pytest-of-*\pytest-current`.

## Red/green proof: tests-first split

Plan two tasks (plan-task, step 2):

`<ID>t` adds the tests only. Its `test_commands` pass only when pytest exits with exactly 1 (tests ran and failed). Exit 2-5 (collection error, usage, no tests) is NOT a red proof and fails the task:
```
- test_commands:
  - python -c "import subprocess,sys; r=subprocess.call('python -m pytest tests/test_x.py -q', shell=True); print('pytest exit', r); sys.exit(0 if r == 1 else 1)"
```
Frontend: `[frontend] python -c "...subprocess.call('npx vitest run src/path/file.test.tsx', shell=True)..."` with the same exit check.

`<ID>c` changes the code, `depends_on: <ID>t`, and runs the same tests normally plus the neighbouring suite:
```
- test_commands:
  - python -m pytest tests/test_x.py -q
  - python -m pytest tests/test_neighbour.py -q
```
The two logs together are the proof: `runs/<ID>t` shows `pytest exit 1`, `runs/<ID>c` shows `exit code 0`. Put new tests in a new file or a new class so existing tests in the file are unaffected by the red step.

When the code already landed without a red proof: say "red not verified" in the review; do not claim it.

## Full verification as a verify_only task

No model call, no `target_files`, always reruns. Commands run in order and stop at the first failure. They must only read, or write under `orchestrator/runs/`: the runner does no scope check on verify_only tasks.

```
<!-- TASK_START: VFULL -->
## Meta
- title: Full verification at the current working tree
- verify_only: true
- test_commands:
  - python -m pytest tests/ -q --basetemp=orchestrator/runs/VFULL/pytest-tmp
  - python -c "import subprocess,sys,re; o=subprocess.run('python -m mypy src/vf_logistics/ --ignore-missing-imports', shell=True, capture_output=True, text=True).stdout; m=re.search(r'Found (\d+) error', o); n=int(m.group(1)) if m else (0 if 'Success' in o else 9999); print('mypy errors', n); sys.exit(0 if n <= 123 else 1)"
  - python -m mypy src/vf_logistics/verifier.py src/vf_logistics/observability.py src/vf_logistics/evaluation.py --ignore-missing-imports --follow-imports=silent
  - python -m ruff check src/ tests/ scripts/ --select E,F,W --ignore E501,E402,W291,W293
  - [frontend] npx tsc --noEmit
  - [frontend] npm run lint
  - [frontend] npm test
- timeout_sec: 900
<!-- TASK_END -->
```

The mypy line fails closed: no "Found N errors" and no "Success" counts as 9999. 123 is the CI ceiling in CLAUDE.md section 7; lower it when the baseline drops. Each command has its own 900 s limit in the runner.

## Reading the numbers

Quote counts only from a log you read (`N passed, M skipped`). Compare with the baseline in CLAUDE.md section 7 and say the difference. 16 skipped tests need the Firestore emulator; more skips than that is a finding.
