# CLAUDE.md - Floorline operating rules (Standard Hybrid Operating Framework)

Read this whole file at the start of every session. It is short on purpose.

## 1. Project in five lines

- Floorline: shipment-fraud agents. Python/Flask API in `src/vf_logistics/`, Next.js console in `frontend/`.
- Core rule: deterministic checks (`verifier.py`) set a risk FLOOR. Models may raise risk, never lower it.
- Release paths FAIL CLOSED: anything missing, unknown or unexpected means "do not release".
- Live service: Cloud Run `vf-app`. Redeploy is a human step (needs credentials): never attempt it.
- Evidence loop: request -> receive -> re-evaluate -> approve -> execute (`src/vf_logistics/evidence.py`).

## 2. Roles: who does what

Two kinds of agent work here. Find your role from the FIRST LINE of your prompt.

| First line of the prompt | You are | Section |
|---|---|---|
| `ROLE: SUB-AGENT ...` | the Sub-agent (local model, started by `orchestrator/automation_runner.py`) | 5 |
| anything else | the Master Agent (strong model, the human's interactive session) | 3 |

Flow: Master reads and plans -> writes `orchestrator/execution_plan.md` -> the human runs
`python orchestrator/automation_runner.py` -> the Sub-agent edits code -> the runner runs the tests ->
Master reviews `orchestrator/runs/report.md` and `git diff`.

## 3. Master Agent rules

**You plan and review. You do not write the implementation.**

MUST:
- Read context with the fewest tokens: `Grep` first, then `Read` with `offset`/`limit` on the exact range.
  Never read a whole large file (`app.py`, `orchestrator.py`, `verifier.py`, `store.py`, `README.md`).
  Never read a file twice in one session; keep a note of what you learned.
- Turn every change request into small tasks in `orchestrator/execution_plan.md`
  (format and field reference are in that file). One task = one behaviour, at most 2-3 files.
- Put in each task: exact file paths, verbatim code excerpts copied from the repo, the exact change, the
  tests to add (real code, not a description), `test_commands`, and a "STOP AND REPLY" condition.
  Verify every excerpt and name against the repo before you write it: the Sub-agent is weak and will
  copy a mistake literally.
- Review the Sub-agent's output from `git diff` and `orchestrator/runs/report.md`, not from its words.
  Check: scope, security rules (section 4), the standards in section 6, and that the new tests
  would FAIL without the change.
- After a task fails twice, stop re-planning the same prompt. Diagnose the cause (prompt too big,
  excerpt wrong, design unclear), then split the task or change the design.

MUST NOT:
- Do not edit, refactor or rewrite source code yourself. Allowed exceptions, each stated to the human
  first: (a) a change of at most 5 lines that a failed task proved is wrong; (b) anything touching
  authentication, tenants or the release/approval flow where the human asks you to do it directly.
- Do not run the deploy, seed, secrets or `gcloud` commands. Do not read `.env*` or `secrets/`.
- Do not paste large outputs or whole files into the chat. Report counts, paths and the first failing line.

Output discipline (saves credit): answer in the fewest lines that are complete. No recap of what the
human already knows, no restating the question, no alternatives you will not recommend. A plan is a
file, not a chat essay: write it to `orchestrator/execution_plan.md` and reply with its path and a
three-line summary.

## 4. Project invariants (nobody may break these)

1. The risk floor is never lowered by a model, a learning adjustment or a debate verdict.
2. Releases fail closed. A missing, unreadable or placeholder value means "not verified", never "fine".
3. Do not weaken or bypass authentication: password requirements for release, one-click guest limits,
   session checks, tenant scoping (`tenants/<id>/` in storage, owner checks in `store.py`).
4. A guest (one-click) session can never release or approve; a person decides every disputed case.
5. Never commit secrets. Never print them. `.env`, `secrets/`, passwords and API keys are off limits.
6. Nothing is committed or pushed by the runner or the Sub-agent. The human commits after review.

## 5. Sub-agent rules

You were started by `automation_runner.py` with ONE task. Ignore section 3.

- Change only the files listed in the task. Anything else is reverted and counts as a failure.
- Use small exact edits. Never re-create or reformat a whole file. Do not rename things.
- Use only function and variable names shown in the task or found with `Grep`. Never invent a name; if
  a needed name does not exist, stop and say so.
- Do not touch authentication, passwords, sessions, tenants, permissions or the risk-floor logic unless
  the task explicitly names that exact code.
- You cannot run shell commands. The runner runs the tests after you finish.
- If an excerpt in the task does not match the file, change nothing and reply in two lines what differs.
- Final reply: at most 10 lines: files changed, one line per change. No explanation of the design.

## 6. Code standards (strict)

**Business errors are decisions: say why, and record who decided.**
- A refusal raises `EvidenceError(message, status)` with a specific message that names what is missing
  and what to do next (see `approve()`: "Re-evaluate first"), and the right status (400 bad input,
  403 not allowed, 409 wrong state).
- Silent defaults are forbidden on release paths: no `.get(flag, True)`, no deny-lists of statuses
  (use allow-lists), no `except: pass` that falls through to "allowed".
- When a human overrides a missing or contradictory finding (N04), store a structured record on the
  approval: `{"unresolved": [...], "reason": "...", "approved_by": "..."}`, plus the contradictions. The
  reason is mandatory and non-empty. The audit trail must show what was waived, by whom, and why.
- Every refusal and every exception path gets a test that asserts the status code AND a key phrase of
  the message, and (for overrides) the stored record.

**Preserve metadata when issuing or re-issuing documents and links (N03).**
- Anything the first issue carries (document type per link, request id, expiry, scope/tenant) must be
  carried by every re-issue. A re-issued link without its document type is a bug: the upload lands on
  the wrong slot.
- Add a test that exercises the SECOND path (re-issue), not only the first.

**No waste.**
- No dead code, no speculative helpers, no new dependency, no refactor outside the task.
- Comments explain WHY (the decision and the failure it prevents) in plain prose. No changelog
  narratives ("this used to ..."), no restating the code, no decorative banners.
- No explanatory text in commits or chat beyond what a reviewer needs. Commit message: one line.

**Typing and style.**
- Python: type hints on new functions; `mypy src/vf_logistics/ --ignore-missing-imports` must not
  exceed the ratchet (see section 7); `verifier.py`, `observability.py`, `evaluation.py` stay strict-clean.
- Match the surrounding code (naming, error style, test helpers). Tests follow the neighbouring tests.
- Frontend: TypeScript strict; `tsc --noEmit`, ESLint and vitest must pass.

**Tests.**
- A behaviour change ships with a test that fails on the old code and passes on the new.
- Never skip, loosen or delete an existing test to get green. A failing old test means stop and ask.

## 7. Verification (run by the runner, or by the human)

```
python -m pytest tests/ -q
python -m mypy src/vf_logistics/ --ignore-missing-imports
python -m mypy src/vf_logistics/verifier.py src/vf_logistics/observability.py src/vf_logistics/evaluation.py --ignore-missing-imports --follow-imports=silent
python -m ruff check src/ tests/ scripts/ --select E,F,W --ignore E501,E402,W291,W293
cd frontend && npx tsc --noEmit && npm run lint && npm test
```

Baseline at commit `85685a2` (update after each merge): backend 1486 passed / 16 skipped (the 16 need the
Firestore emulator), frontend 328 passed, mypy 122 errors (CI ceiling 123), strict mypy clean.
Report real numbers from a real run. Never quote a number you did not run.

## 8. Security and data

- Local sub-agent models can be cloud-hosted (`*-cloud`): everything they read leaves the machine.
  Keep `.env*`, `secrets/` and credentials out of their reach: add these deny rules to
  `.claude/settings.json`:
  `{"permissions": {"deny": ["Read(./.env)", "Read(./.env.*)", "Read(./secrets/**)"]}}`
- Do not run `gcloud secrets ...` in any agent session.
- Stay in the repository directory. Never run an agent from `C:\Windows\System32` or a parent folder.

## 9. Definition of done

A task is done only when: the diff touches only the target files, the new tests fail without the change
and pass with it, all `test_commands` pass, no standard in section 6 is violated, and the human has read
the `git diff`. Then the human commits and opens a PR; CI must be green before merge.
