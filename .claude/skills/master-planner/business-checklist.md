# Business checklist (shared by plan-task, run-review, test-gate, runner-maintainer)

Source of truth: CLAUDE.md sections 4 and 6. This file is the checklist form; when they differ, CLAUDE.md wins.

## Invariants: a "no" on any line stops the work and goes to the human

| # | Check | Where to look |
|---|---|---|
| I1 | The risk floor from `verifier.py` is never lowered by a model, a learning adjustment or a debate verdict | diff of `verifier.py`, `orchestrator.py`, any `max(`/`min(` on risk |
| I2 | Release paths fail closed: missing, unreadable, placeholder or unknown means "not verified" | new `if`/`else` on release, approve, execute paths |
| I3 | Authentication not weakened: release password, one-click guest limits, session checks, tenant scoping (`tenants/<id>/`, owner checks in `store.py`) | diff of `app.py`, `store.py`, auth helpers |
| I4 | A guest session never releases or approves; a person decides every disputed case | role checks on new routes |
| I5 | No secret read, printed, logged or committed (`.env*`, `secrets/`, passwords, API keys) | diff, test fixtures, log lines |
| I6 | Nothing committed or pushed by the runner or the sub-agent | a `verify_only` task's `git log --oneline -3` log, before and after |

## Standards: a "no" fails the task's review; plan a fix task

| # | Check |
|---|---|
| S1 | Every refusal raises `EvidenceError(message, status)`; the message names what is missing AND what to do next; status is 400 bad input, 403 not allowed, 409 wrong state |
| S2 | No silent default on a release path: no `.get(flag, True)`, no deny-list of statuses (allow-lists only), no `except: pass` that falls through to "allowed" |
| S3 | A human override of missing or contradictory evidence (N04) stores `{"unresolved": [...], "reason": "...", "approved_by": "..."}` plus the contradictions; the reason is mandatory and non-empty |
| S4 | Re-issued documents and links keep everything the first issue carried: document type per link, request id, expiry, scope/tenant (N03) |
| S5 | Every refusal and exception path has a test asserting the status code AND a key phrase of the message, and the stored record for overrides |
| S6 | A re-issue change has a test on the SECOND path (re-issue), not only the first |
| S7 | A behaviour change has a test proved red on the old code and green on the new (see test-gate) |
| S8 | No existing test skipped, loosened or deleted |
| S9 | No dead code, speculative helper, new dependency or refactor outside the task |
| S10 | Comments say WHY in plain prose; no changelog narrative, no banners |
| S11 | Type hints on new Python functions; mypy stays at or under the ratchet; `verifier.py`, `observability.py`, `evaluation.py` stay strict-clean |
| S12 | Frontend: TypeScript strict, `tsc --noEmit`, ESLint and vitest pass |

A review names each row it checked and the evidence (file and line, or log section). A row with no evidence is "not verified", never "ok".
