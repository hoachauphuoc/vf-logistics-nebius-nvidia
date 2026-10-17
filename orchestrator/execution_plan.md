# Execution plan - Floorline backlog (full)

Written by the Master, executed by `orchestrator/automation_runner.py` through the local sub-agent.

- Plan id: `PLAN-BACKLOG-01`
- Base commit: `85685a2`
- Run in phases and read `git diff` between them (suggested):
  1. `--only A1,C2,R1` (already done in the first run)
  2. `--only A2`
  3. `--only B1`   4. `--only B2` then `--only B3a` then `--only B3b`   5. `--only C1`   6. `--only D1` then `--only D2a,D2b`
  7. `--only N01a`, then `--only N01b`, then `--only N01c` (one at a time; read `git diff` after each)
  8. `--only R2` (read-only; answer in `runs/R2/answer.md`)
  9. `--only N04a`, then `--only N04b` (one at a time; read `git diff` after each)
  10. `--only V1`, then run `python scripts/verify_review_vi.py` any time to re-measure (no runner needed)
  11. `--only VO1`, then `--only VO2` (one at a time). After VO2 a verification task is written in the plan
      with `verify_only: true`; it is not written before, because the old parser would reject it.
  12. `--only N06d1`, `--only N06d2`, `--only N01d1`, `--only N01d2` (one at a time, in this order), then `--only V2` to re-measure.
      N06d1 and N06d2 replace the parked task C3, which stays parked.
  13. `--only N08e`; `--only N03d1t` (red: log shows `pytest exit 1`), `--only N03d1c`, then `--only V3` (its log lists the existing tests N03d1c breaks; migrate them next). The combined task N03d1 is parked, superseded by N03d1t/N03d1c.
  13. `--only RM1t` (its tests must fail: the log shows `pytest exit 1`), then `--only RM1c` (same tests green).
  14. `--only RM2t` (red), then `--only RM2c` (green). After RM2c the Master reviews from `runs/<ID>/attempt_N.diff` and runs no git.
  15. PRE-DEPLOY GATE (phase PD, review VI 2026-10-15 + CLAUDE.md section 7). In this order, one id per run:
      `PDSYNC` (the code to test is exactly origin/master), `PD1` (add the newer fixes to the review VI table),
      `V2` (review VI table: every counted check PASS), `VFULL` (backend, ruff, tsc, lint, vitest), `PDCI` (GitHub CI,
      typecheck/mypy included, green on the origin/master commit). GO for deploy only if all five logs are green and the
      human checklist in task PDCI's context is done. After the human deploys: `PDPOST` (the live service answers and runs
      the new code). Every task here is verify_only except PD1.
  16. REVERIFICATION VI of 2026-10-17 (commit 76e6b01), one id per run, in this order, reading `git diff` after each: `--only N06e` (P1: a country field read like a bare string), `--only N01e1`, then `--only N01e2` (P1: DeadlineExceeded/RetryError are unknown; an accepted publish keeps its message id when its record fails to save), `--only N08g`, then `--only N08h` (P2: reload after a lost connection; poll an EXECUTING case). Then `--only VFULL`. Not fixable in this repository, listed in the report: the receiving side must drop a repeat by the idempotency_key attribute; a process that dies between the broker's accept and any save; a real Firestore/Pub/Sub/browser run; the "27 checks" figure in the fix report against the 25 in scripts/verify_review_vi.py.
  17. FOLLOW-UP of the reverification: the mypy command of VFULL was fixed in the plan (it now passes --python-version of the running Python and fails when mypy stops early; before, mypy exited 2 on a numpy stub, the parsed count was 1 and the gate passed vacuously). Then `--only VR1`, then `--only VR2` (one at a time; each runs the whole table), then `--only VFULL` to prove the new command, and `--only VMYPY` shows the raw mypy output.
  18. N08 GAPS found by the Master check of 83826f6: `--only N08i` (the review page did not poll an EXECUTING case), then `--only N08jt` (red: 3 named tests fail), then `--only N08jc` (a 409 from execute reads the case again; human decision: the Resume-refusal test now expects one reload). Then `--only VFULL`.
  19. OPEN ITEMS OF THE FIX REPORT that the repository can close, one id per run: `--only N01mt` (red), `--only N01mc`, `--only N01kt` (red: 2 named tests), `--only N01kc`, `--only N08kt`, `--only N08kv` (red on the old page), then `--only VFULL`. Still open after these, by design: a process killed outright between the broker's accept and the save (needs a human decision: duplicates for the receiver to drop, or no automatic resend), the receiving side, the real environment.
- Task C3 is PARKED (not parsed): it needs a human decision on multi-page PDF behaviour. To enable it,
  rename its PARKED_TASK_START / PARKED_TASK_END markers to TASK_START / TASK_END.
- B3a, B3b and D2b contain design decisions: read B2/D1 answers (`runs/<id>/answer.md`) before running them.
- B3 failed three times (runs/B3) and was split into B3a (code) and B3b (tests); its old checkpoint entry
  stays `failed` and is ignored because B3 is no longer in this plan.
- B3a and B3b ran and were committed (`16c3358`). N01a-c and R2 were written at that commit, from the Rev2 review.
- N04 (dedicated exception operation), human decision: the thorough fix, in three steps. Step 1 is N04a (function)
  and N04b (route), ADDITIVE, no existing test changes except one pinned line in test_rbac. Step 2 (planned after
  step 1 is reviewed): approve() refuses a release over unresolved or contradicting evidence with 403 and points to
  the exception operation, and the existing tests move to it. R2's count was wrong; a probe that made approve()
  refuse every exception failed 39 backend tests (26 in test_evidence_execution.py, 11 in
  test_evidence_eval_approve.py, 1 in test_n07_policy_gate.py, 1 in test_resume_after_publish.py), most of them
  because their setup approves a release with a note. Step 3: the console (api.ts, proxy-policy.ts, ReviewPanel).
- N01 stays partial after N01a-c: a publish whose result is unknown (timeout) is still recorded as failed, and
  deduplication on the receiving side is outside this repository.
- Commit after each reviewed phase; the runner and sub-agent never commit.

| Order | Id | What |
|---|---|---|
| 1 | A1 | Reload case on EXECUTION_FAILED |
| 2 | C2 | Keep pages/pages_read |
| 3 | R1 | Read-only: N04 investigation |
| 4 | A2 | Show shipper links after Request info as full URLs |
| 5 | B1 | Reissued evidence link returns one typed link per missing document (N03) |
| 6 | B2 | Investigate: Release approval at evidence_version 0 (N04) |
| 7 | B3a | approve() refuses Release without an evaluation, also at evidence_version 0 (N04): code only |
| 8 | B3b | Tests for B3a (new test class at the end of the test file) |
| 9 | C1 | A country field listing several countries is not "provided" (N06-A) |
| 10 | D1 | Investigate: can the UI Resume an interrupted execution? |
| 11 | D2a | Show EXECUTING as in progress or interrupted (display only) |
| 12 | D2b | Resume button for an interrupted execution |
| 13 | N01a | Send the idempotency key as a Pub/Sub message attribute |
| 14 | N01b | A decision is published once per idempotency key |
| 15 | N01c | Test: a resume after an accepted publish does not publish again |
| 16 | R2 | Read-only: what a dedicated exception operation for N04 would change |
| 17 | N04a | approve_exception(): a release over open evidence as its own operation |
| 18 | N04b | Route for the exception operation (operator role, password) |
| 19 | V1 | Verification script: how much of review VI is already addressed |
| 20 | VO1 | Runner: the plan parser accepts verify_only tasks |
| 21 | VO2 | Runner: runs verify_only tasks without a model, one log per run |
| 22 | V2 | verify_only: full review VI check (backend and frontend), log in runs/V2 |
| 23 | N06d1 | A partly read paper (pages_read < pages) is not provided: verifier |
| 24 | N06d2 | The evaluation record lists the papers that were not fully read |
| 25 | N01d1 | A publish that timed out is recorded as unknown, not failed: tools |
| 26 | N01d2 | An execution whose send timed out is recorded as send_unknown: evidence |
| 27 | N08e | Frontend test: Release then Cancel sends nothing |
| 28t | N03d1t | Tests first: a request-level link is refused when several documents were requested |
| 28c | N03d1c | Code for N03d1t |
| 29v | V3 | verify_only: which existing tests the N03d1c change breaks |
| 29m | N03m1, N03m2 | Migrate the two test helpers to the typed link of the first document (human approved) |
| 29w | V4 | verify_only: the full backend suite |
| PD-a | PDSYNC | verify_only: the working tree's code equals origin/master (what will be deployed) |
| PD-b | PD1 | Review VI table also checks send_unknown, the refused request-level link, the unread record |
| PD-c | V2 | verify_only: review VI table (rerun after PD1) |
| PD-d | VFULL | verify_only: backend suite, ruff, tsc, lint, vitest (rerun) |
| PD-e | PDCI | verify_only: GitHub CI on the origin/master commit, every job green (mypy ratchet included) |
| PD-f | PDPOST | verify_only, AFTER the human deploys: the live service is healthy and serves the new code |

N03d1c round 1: FIX, 10 existing tests broke (9 in test_evidence_respond.py, 1 in test_evidence_eval_approve.py), human approved migrating the two helpers; log runs/V3/attempt_1.log. Next: run N03m1, N03m2, V3, V4.
N03d1c round 2: FIX, V4 (full suite) shows 2 failures: the tenant upload test still uses the request-level link (N03m3), and test_operating_curve fails because the relative --basetemp makes the script print a relative path (environmental; V4 now uses an absolute basetemp via %CD%); V3 was skipped as "failed earlier, unchanged" and is superseded by V4. Logs runs/V4/attempt_1.log. Next: run N03m3, then V4. Limit reached after this round: if V4 is not clean, stop and report.
| 27 | RM1t | Runner: test that the sub-agent starts with skills disabled (red first) |
| 28 | RM1c | Runner: claude_command always passes --disable-slash-commands |
| 29 | RM2t | Runner: test that every attempt writes attempt_N.diff (red first) |
| 30 | RM2c | Runner: run_task writes attempt_N.diff before any restore |
| 31 | N06e | A country field with one country twice or an unstated entry is compared with the declaration (N06) |
| 32 | N01e1 | DeadlineExceeded and RetryError are recorded as unknown, not failed (N01) |
| 33 | N01e2 | An accepted publish keeps its message id when its record fails to save (N01) |
| 34 | N08g | ReviewPanel reloads the case after a lost connection on approve or execute (N08) |
| 35 | N08h | The case page reads an EXECUTING case again every 15 seconds (N08) |
| 36 | VR1 | Review VI table: rows N06-f, N01-g, N01-h for the backend fixes |
| 37 | VR2 | Review VI table: rows N08-f, N08-g and operations.test.ts in its vitest run |
| 38 | N08i | The review queue page reads an EXECUTING case again every 15 seconds (N08) |
| 39t | N08jt | Tests first: a 409 from execute (Resume, Execute, Release) reads the case again (N08) |
| 39c | N08jc | Code for N08jt |
| 40 | VR3 | Review VI table: row N08-h for the 409-reloads-the-case tests |
| 41t | N01mt | Tests first: a publish record that fails to save twice keeps the accepted message id (N01) |
| 41c | N01mc | Code for N01mt: `_save_publish_record` hands an accepted receipt back unsaved |
| 42t | N01kt | Tests first: a cancellation around the publish leaves a record a Resume can read (N01) |
| 42c | N01kc | Code for N01kt: `except asyncio.CancelledError` saves shielded, then re-raises |
| 43t | N08kt | Test for the review page: polls an EXECUTING case, stops when it ends (N08) |
| 43v | N08kv | verify_only: that test fails on the page before N08i (red proof) |
| 41f | N01mcf1 | Fix round 1 of N01mc: remove the blank line inside the signature of publish_decision_direct |

N01mc round 1: FIX, behaviour passed (40 tests, ruff clean) but EDIT 1 left a blank line inside the signature of publish_decision_direct; log runs/N01mc/attempt_1.log, diff runs/N01mc/attempt_1.diff.
N01mcf1 (round 1 of N01mc): PASS, blank line removed, 40 tests and ruff green; log runs/N01mcf1/attempt_1.log.
N01kc round 1: RERUN, the one-line anchor was not unique (prefix of the handler at line 166); both attempts dropped the next line, IndentationError; prompt now uses the unique two-line anchor; failed logs were runs/N01kc/attempt_1.log, attempt_2.log (attempt_1.log is overwritten by the rerun). Rerun: PASS, 43 tests and ruff green, runs/N01kc/attempt_1.log.

N01e2 round 1: RERUN, its mypy test_command wanted tools.py clean but 2 no-any-return errors exist outside the change (lines 200 and 290; tools.py is not in the strict list); replaced by a ruff check; code and tests passed (38 + 105), log runs/N01e2/attempt_2.log

---

<!-- TASK_START: A1 -->
## Meta
- title: ReviewPanel reloads the case when approve-then-execute ends in EXECUTION_FAILED
- depends_on: []
- target_files:
  - frontend/src/components/review/ReviewPanel.tsx
  - frontend/src/components/review/ReviewPanel.test.tsx
- test_commands:
  - [frontend] npx vitest run src/components/review/ReviewPanel.test.tsx
  - [frontend] npx tsc --noEmit
  - [frontend] npm run lint
- timeout_sec: 180
- max_retries: 2

## Context
The web console is a Next.js app in `frontend/` (tests: vitest). The case page does not poll, so a case
is only refreshed when a component calls the `onDecided()` prop. The Retry button is rendered only when
the loaded case state is `EXECUTION_FAILED`. Finding N08-A of the independent review: after the first
approve-then-execute fails, the page is never reloaded and Retry never appears.
Hard limits: do not touch login, passwords, sessions, roles, tenants, identity or the proxy.

## Prompt
````text
TASK A1. Make ReviewPanel reload the case when "approve and execute" ends in EXECUTION_FAILED.

FILES YOU MAY EDIT (only these two):
- frontend/src/components/review/ReviewPanel.tsx
- frontend/src/components/review/ReviewPanel.test.tsx
Use small exact edits only. Never re-create or reformat a whole file. If the edit text is not found
(the file may use Windows line endings), retry with a shorter anchor of one or two lines.

THE BUG
In ReviewPanel.tsx the mutation `verificationApprove` approves a case and then executes the approval.
When execution fails the backend answers with state "EXECUTION_FAILED". The mutation's onSuccess then
sets an error message and returns WITHOUT calling onDecided().

Current code, `onSuccess` of `const verificationApprove = useMutation({` (verbatim):
```tsx
    onSuccess: (result) => {
      const state = (result as Record<string, unknown>)?.state;
      if (state === "EXECUTION_FAILED") {
        setFormError("The decision was approved but execution failed. You can retry.");
        setPending(null);
        return;
      }
      setFormError(null);
      setNote("");
      onDecided();
      toast({ title: "Decision executed via the verification loop" });
    },
```
The sibling mutation `verificationExecute` already calls onDecided() in its failure branch. Do NOT change it.

CHANGE 1 (ReviewPanel.tsx): inside the `if (state === "EXECUTION_FAILED") {` block, call `onDecided();`
right before `return;`. Keep the message text and `setPending(null);`. The block must become:
```tsx
      if (state === "EXECUTION_FAILED") {
        setFormError("The decision was approved but execution failed. You can retry.");
        setPending(null);
        // Reload the case: it is now EXECUTION_FAILED, and the Retry button only
        // appears once the page has that state. The case page does not poll.
        onDecided();
        return;
      }
```

CHANGE 2 (ReviewPanel.test.tsx): add exactly one test inside the first
`describe("ReviewPanel verification actions", ...)` block, directly BEFORE the existing test whose line is
`  it("offers Execute for an approved case", () => {`
Use that line as the edit anchor: new text = the new test, a blank line, then that same line again.
The helpers and default mocks already exist (approveCase resolves an approval with id "evapr-9",
executeApproval resolves { state: "EXECUTION_FAILED" }, renderPanel(c) returns the onDecided mock,
makeCase("HELD_FOR_REVIEW") has a verification record). Do not add imports or change mocks.
```tsx
  it("reloads the case when approve-then-execute ends in EXECUTION_FAILED, so Retry can appear", async () => {
    const onDecided = renderPanel(makeCase("HELD_FOR_REVIEW"));
    fireEvent.click(screen.getByRole("button", { name: "Release" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(executeApproval).toHaveBeenCalledWith("CASE-1", "evapr-9"));
    await waitFor(() => expect(onDecided).toHaveBeenCalledTimes(1));
    expect((await screen.findByRole("alert")).textContent).toMatch(/execution failed/i);
  });
```

DONE WHEN: only the two files changed; the only non-test change is the added `onDecided();` call
and its comment; nothing else was edited.
STOP AND REPLY WITHOUT EDITING if the excerpts above do not match the files.
````
<!-- TASK_END -->

<!-- TASK_START: C2 -->
## Meta
- title: Keep pages and pages_read on every received evidence document
- depends_on: []
- target_files:
  - src/vf_logistics/evidence.py
  - tests/test_evidence_respond.py
- test_commands:
  - python -m pytest tests/test_evidence_respond.py -q
  - python -m pytest tests/test_evidence_eval_approve.py tests/test_origin_inputs.py -q
- timeout_sec: 180
- max_retries: 2

## Context
A shipper uploads an evidence PDF through a signed link. `receive_evidence()` in
`src/vf_logistics/evidence.py` builds a dict `doc_record` stored on the case. The extractor reads only
the FIRST page of a PDF and reports `source_pages` and `source_pages_read` at the top level of its
result envelope, but `doc_record` drops them, so nobody can later tell pages 2..N were never read.
This task only RECORDS the two numbers. No decision logic changes: no check, finding, status or floor.
Hard limits: do not touch authentication, password, session, tenant or permission code.

## Prompt
````text
TASK C2. Keep the page counts on every received evidence document.

FILES YOU MAY EDIT: src/vf_logistics/evidence.py and tests/test_evidence_respond.py only.
Do not edit document_agent.py or orchestrator.py. Do not edit, delete or loosen any existing test,
except the signature and body of the helper `submit` exactly as described below.
Use only names that appear in the excerpts. Use small exact edits; never re-create a whole file.

CHANGE (a) - src/vf_logistics/evidence.py, the dict inside receive_evidence (verbatim today):
```python
        "received_at": now,
        "blocked": blocked,
        "extracted": extraction.get("result") if extraction and not extraction.get("parse_error") else None,
```
Insert these lines right after `"blocked": blocked,` and before `"extracted": ...`:
```python
        # How much of the file the reader saw, named as in ingest_document's
        # provenance: `pages` is the PDF's page count, `pages_read` how many of them
        # were transcribed. None when no extraction ran (blocked) or it did not say.
        "pages": extraction.get("source_pages") if extraction else None,
        "pages_read": extraction.get("source_pages_read") if extraction else None,
```
`extraction` is None when the file was blocked by the screen, otherwise the envelope dict.

CHANGE (b) - tests/test_evidence_respond.py, helper `submit` in class Base. Today it starts with:
```python
    def submit(self, token, data=None, filename="cert.pdf", mime="application/pdf"):
        """Submit evidence through receive_evidence, mocking the extraction."""
```
Replace those two lines with:
```python
    def submit(self, token, data=None, filename="cert.pdf", mime="application/pdf", **envelope_extra):
        """Submit evidence through receive_evidence, mocking the extraction.

        `envelope_extra` are added to the mocked extraction envelope, e.g.
        source_pages=3, source_pages_read=1 as document_agent.extract_evidence reports them.
        """
```
In the same helper, the mock dict ends with these two lines (the ones with "latency_ms": 50 above them):
```python
            "latency_ms": 50, "input_tokens": 100, "output_tokens": 50,
            "parse_error": False, "at": "2026-10-12T08:00:00Z",
        }
```
Add the line `            **envelope_extra,` after the "parse_error" line, before the closing brace. Use the
"latency_ms": 50 line as part of the anchor: the same "parse_error" line appears elsewhere in the file.

CHANGE (c) - insert this class directly BEFORE the line `class TestTheRoute(Base):`
(two blank lines before and after):
```python
class TestPagesKeptOnTheDocument(Base):
    """The reader sees page 1 only. The document record keeps how many pages the file has
    and how many were read, as `pages` and `pages_read`."""

    def _only_document(self):
        return self.stored()["verification"]["documents"][0]

    def test_the_page_counts_of_the_extraction_are_kept(self):
        self.put()
        _, token = self.request_and_token()
        self.submit(token, source_pages=3, source_pages_read=1)
        doc = self._only_document()
        assert doc["pages"] == 3
        assert doc["pages_read"] == 1

    def test_an_extraction_that_reports_no_pages_leaves_them_none(self):
        self.put()
        _, token = self.request_and_token()
        self.submit(token)
        doc = self._only_document()
        assert "pages" in doc and "pages_read" in doc
        assert doc["pages"] is None and doc["pages_read"] is None
```

DONE WHEN: only the two files changed; both new tests exist; existing callers
submit(token), submit(token, data=...), submit(token, mime=...) still work.
STOP AND REPLY WITHOUT EDITING if the excerpts above do not match the files.
````
<!-- TASK_END -->

<!-- TASK_START: R1 -->
## Meta
- title: Investigate: can a release be approved after the request was cancelled before any upload?
- depends_on: []
- read_only: true
- timeout_sec: 180
- max_retries: 1

## Context
Read-only investigation (finding N04). The Master will read the answer and decide the fix. Change no file.

## Prompt
````text
TASK R1 (READ ONLY - do not edit or create any file).
In src/vf_logistics/evidence.py read approve(), cancel_request() and reevaluate().
Scenario: a case is HELD_FOR_REVIEW, three documents are requested, the request is cancelled before any
document is uploaded (evidence_version stays 0), then approve() is called with action "release" and an
empty note. Answer with function names and the exact condition that decides each answer:
1. What state is the case in after cancel_request()?
2. Can reevaluate() run in that state at evidence_version 0, and what does it record?
3. Why does approve() accept the release with no evaluation?
4. Which is the smallest safe change: (a) approve() refuses a release with HTTP 409 when the current
   evidence version has no evaluation, or (b) approve() evaluates automatically? Give one reason.
Reply in at most 25 lines. Quote at most one line of code per answer.
````
<!-- TASK_END -->

<!-- TASK_START: A2 -->
## Meta
- title: Show shipper links after Request info as full URLs
- depends_on: []
- target_files:
  - frontend/src/components/review/ReviewPanel.tsx
  - frontend/src/components/review/ReviewPanel.test.tsx
- test_commands:
  - [frontend] npx vitest run src/components/review/ReviewPanel.test.tsx
  - [frontend] npx tsc --noEmit
  - [frontend] npm run lint
- timeout_sec: 240
- max_retries: 2

## Context
ReviewPanel shows evidence links after "Request info". They are bare paths; the shipper needs full URLs. Frontend only; do not touch login, proxy, roles or tenants.

## Prompt
``````text
RUNNER MODE OVERRIDE (applies to everything below): you cannot run shell commands, git or tests; the runner runs them after you finish. Skip every step that says to run a command, see a test fail, check git status or compare with a baseline; do only the file edits and reading. Where the text says STOP and ask, change nothing and reply in at most 3 lines what differs.

TASK A2 - show the shipper links after "Request info" as full URLs, not bare paths

You are working in the Floorline repository. The web console is a Next.js app in `frontend/`; its tests use vitest. Make ONE small change and update/add its tests. Do nothing else.

FILES YOU MAY EDIT (only these two):
- frontend/src/components/review/ReviewPanel.tsx
- frontend/src/components/review/ReviewPanel.test.tsx

Do not edit any other file. Do not touch anything about login, passwords, sessions, roles, tenants, identity or the proxy. Do not reformat, re-indent or rewrite either file, and never re-create a whole file: use small exact edits (the Edit tool) only. Do not run `npm install`.

THE PROBLEM
After a reviewer clicks "Request info" and confirms, ReviewPanel shows the links to send to the shipper, in the block marked `data-testid="evidence-links"`. The API returns only RELATIVE paths such as `/respond/<token>` and the panel shows them as they are. A reviewer cannot paste a relative path into an email; they need the full address, `<console origin>/respond/<token>`. (The backend's own docstring says "The console turns this into an absolute address", but the console never did.)

Current code in frontend/src/components/review/ReviewPanel.tsx, inside `onSuccess` of `const verificationRequest = useMutation({` (verbatim):
```tsx
      const links = Array.isArray(data?.links)
        ? (data.links as Array<{ doc_type?: string; path?: string }>)
            .map((l) => (l.path ? `${l.doc_type ? l.doc_type + ": " : ""}${l.path}` : ""))
            .filter(Boolean)
        : typeof data?.path === "string"
          ? [data.path]
          : [];
      setEvidenceLinks(links);
```
The same file already has a helper that reads `window` safely for server rendering. Copy its style (verbatim):
```tsx
function signInHref(): string {
  const here =
    typeof window === "undefined" ? "/review" : window.location.pathname + window.location.search;
  return `/login?next=${encodeURIComponent(here)}`;
}
```

WHAT TO CHANGE (exactly this, and no more)
1. Add this small helper function to ReviewPanel.tsx immediately AFTER the closing `}` of `signInHref` and BEFORE the `/**` comment of `Paperwork` (a blank line before and after it):
```tsx
/**
 * The address a shipper opens, from the path the API returns (`/respond/<token>`).
 * The path alone is not something a reviewer can paste into an email. Without a
 * window (server rendering) the path is the best there is.
 */
function absoluteLink(path: string): string {
  return typeof window === "undefined" ? path : new URL(path, window.location.origin).toString();
}
```
Suggested Edit anchor: the single line ``  return `/login?next=${encodeURIComponent(here)}`;`` followed by the line `}` is unique in the file; put the helper after that `}`.

2. In `verificationRequest.onSuccess`, use the helper in the two places, and nowhere else:
   - `${l.path}` becomes `${absoluteLink(l.path)}` (keep the `l.path ? ... : ""` guard around it, and keep the doc-type label in front, so the line still reads `certificate_of_origin: <full url>`);
   - `[data.path]` becomes `[absoluteLink(data.path)]`.
   The result must be:
```tsx
      const links = Array.isArray(data?.links)
        ? (data.links as Array<{ doc_type?: string; path?: string }>)
            .map((l) => (l.path ? `${l.doc_type ? l.doc_type + ": " : ""}${absoluteLink(l.path)}` : ""))
            .filter(Boolean)
        : typeof data?.path === "string"
          ? [absoluteLink(data.path)]
          : [];
      setEvidenceLinks(links);
```
Nothing else changes: `evidenceLinks` stays a `string[]`, the rendering block with `data-testid="evidence-links"` stays as it is.

OUT OF SCOPE (do not do): a copy-to-clipboard button (there is no reusable copy component in the app; the only `CopyButton` is a private function inside another file), any env var or configured base URL, any change to `requestEvidence` in `src/lib/api.ts`, any change to how links are stored or rendered.

THE TESTS (write/update them FIRST, run them, see them fail, then make the change)
Mock available at the top of frontend/src/components/review/ReviewPanel.test.tsx (verbatim; do not change it):
```tsx
  requestEvidence: vi.fn(async () => ({
    path: "/respond/request-level",
    links: [
      { doc_type: "certificate_of_origin", path: "/respond/cert-token" },
      { doc_type: "producer_declaration", path: "/respond/decl-token" },
    ],
  })),
```
`vi`, `requestEvidence`, `fireEvent`, `screen`, `renderPanel`, `makeCase` are already available in the test file; do NOT add imports. In the vitest/jsdom environment `window.location.origin` is `http://localhost:3000`, but do NOT hardcode it: read `window.location.origin` in the test.

(a) UPDATE the existing test `shows the per-document links after Request info`. Its last lines currently are (verbatim):
```tsx
    const banner = await screen.findByTestId("evidence-links");
    expect(banner.textContent).toContain("certificate_of_origin: /respond/cert-token");
    expect(banner.textContent).toContain("producer_declaration: /respond/decl-token");
  });
```
Replace the two `expect` lines (keep the `const banner` line and the closing `});`) so they read:
```tsx
    // Full addresses a reviewer can paste into an email, not bare paths.
    const origin = window.location.origin;
    expect(banner.textContent).toContain(`certificate_of_origin: ${origin}/respond/cert-token`);
    expect(banner.textContent).toContain(`producer_declaration: ${origin}/respond/decl-token`);
```

(b) ADD one new test directly AFTER that test (so before `it("says it is waiting for the shipper and offers Cancel while awaiting evidence"`). It covers the fallback where the API sends only the request-level `path` and no `links`:
```tsx
  it("shows the request-level link as a full address when the API sends no per-document links", async () => {
    vi.mocked(requestEvidence).mockResolvedValueOnce({ path: "/respond/request-level" });
    renderPanel(makeCase("HELD_FOR_REVIEW"));
    fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: "need papers" } });
    fireEvent.click(screen.getByRole("button", { name: "Request info" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    const banner = await screen.findByTestId("evidence-links");
    expect(banner.textContent).toContain(`${window.location.origin}/respond/request-level`);
  });
```
(There is no TODO in it; copy it as it is.)

STEPS
(The test counts below assume the repository is at its original state. If the separate task A1 was already applied, there is 1 more passing test: expect `2 failed | 29 passed (31)` in step 1, 31 in ReviewPanel.test.tsx afterwards and 330 in total.)
1. Do (a) and (b) only. From the `frontend` folder run: `npx vitest run src/components/review/ReviewPanel.test.tsx`. Expected: exactly TWO failing tests, with messages like `expected 'Send these links to the shipper (show...' to contain 'certificate_of_origin: http://localhost:3000/respond/cert-token'` and `... to contain 'http://localhost:3000/respond/request-level'`; the summary `Tests  2 failed | 28 passed (30)`.
2. Make the change in ReviewPanel.tsx (helper + the two uses).
3. Run the same command again. Expected: `Tests  30 passed (30)`.
4. From the `frontend` folder run `npx tsc --noEmit` (no output = good), then `npm run lint` (no errors), then `npm test` (expected: `Tests  329 passed (329)`).
5. Run `git diff --stat`: expect exactly the two files.

DONE WHEN
- the two tests failed before the change and pass after it;
- nothing else in the suite changed (329 passed in total), tsc and lint clean;
- `git diff` touches only the two files above and the only non-test changes are the `absoluteLink` helper and its two uses.

STOP AND ASK (do not guess) IF
- the `verificationRequest` code or the `data-testid="evidence-links"` block does not look like the excerpts above;
- TypeScript complains about `absoluteLink(data.path)` or `absoluteLink(l.path)`: do not use `any` or `as` casts to silence it; `data.path` is already narrowed to `string` by the `typeof data?.path === "string"` check and `l.path` by the `l.path ?` check. Paste the error and stop;
- another test in the suite (not in ReviewPanel.test.tsx) fails after your change; do not edit it, report it;
- you feel the change needs a copy button, an env var, or a change in any other file: that is out of scope, stop;
- the Edit tool cannot find your `old_string` twice in a row (Windows line endings can break multi-line matches; use single-line anchors then).

DO NOT
- call `window.location.origin` at module level or outside the `typeof window === "undefined"` guard (the Next.js server render has no `window` and would crash);
- compute the full URL while rendering (in the `evidenceLinks.map(...)`); do it in `onSuccess` as above;
- call `absoluteLink` with an empty or missing path; keep the `l.path ? ... : ""` guard (an empty path would turn into a link to the console's home page);
- hardcode `http://localhost:3000` in the tests, or use `process.env` / `NEXT_PUBLIC_*`;
- change `key={l}`, the text "Send these links to the shipper (shown once):", or any `data-testid`;
- change any other test or any mock at the top of the test file;
- add or change imports.
``````
<!-- TASK_END -->


<!-- TASK_START: B1 -->
## Meta
- title: Reissued evidence link returns one typed link per missing document (N03)
- depends_on: []
- target_files:
  - src/vf_logistics/evidence.py
  - tests/test_evidence_request.py
  - tests/test_evidence_respond.py
- test_commands:
  - python -m pytest tests/test_evidence_request.py tests/test_evidence_respond.py -q
  - python -m pytest tests/test_evidence_request.py tests/test_evidence_respond.py tests/test_evidence_eval_approve.py tests/test_evidence_execution.py tests/test_evidence_reevaluable_mirror.py tests/test_n07_policy_gate.py tests/test_origin_inputs.py -q
- timeout_sec: 300
- max_retries: 2

## Context
evidence.py issues signed upload links per requested document type. A re-issued link loses its document type, so an upload lands on the wrong slot. Re-issue must carry the same metadata as the first issue. Do not change token signing or receive_evidence.

## Prompt
``````text
RUNNER MODE OVERRIDE (applies to everything below): you cannot run shell commands, git or tests; the runner runs them after you finish. Skip every step that says to run a command, see a test fail, check git status or compare with a baseline; do only the file edits and reading. Where the text says STOP and ask, change nothing and reply in at most 3 lines what differs.

TASK B1: a reissued evidence link must give one typed link per missing document (finding N03)

You are working in the Python/Flask repository "Floorline". Run every command from the repository root. Fix ONE bug with the smallest possible change and add tests. Read this whole message before you edit anything.

HARD RULES
1. Edit ONLY these three files: src/vf_logistics/evidence.py, tests/test_evidence_request.py, tests/test_evidence_respond.py. Do not touch anything else (not frontend/, not src/vf_logistics/app.py, not auth code, not other tests).
2. Use small targeted edits (the Edit tool, one hunk at a time). Never re-create or rewrite a whole file. Never reformat code you are not changing.
3. Do NOT change how links are signed or checked. mint_token, read_token, _key, _issue and receive_evidence must stay exactly as they are. Never weaken authentication, password or tenant checks.
4. Do not run git commit, git stash, git checkout, git reset or git push. Do not install packages. Do not delete, rename or edit existing tests (you only ADD tests, plus the one added assert described in step 6).
5. Keep every key the two functions already return. You may only ADD a key.
6. If the code you see differs from the excerpts below, or a step cannot be done as written, STOP and tell me what differs. Do not improvise and do not invent helper names other than the one given.
7. In the code blocks below, a first line that starts with "# VERBATIM" or "# NEW" is a label for you, NOT code. Never paste that label line into any file. "VERBATIM" blocks show what the file contains today; "NEW" blocks are what you add or put in place of the old lines.

BACKGROUND
A reviewer asks the shipper for three documents. request_evidence() in src/vf_logistics/evidence.py returns one link per document in "links": [{"doc_type", "token", "path"}], and each token is minted with doc_type=..., so an upload made through that link is stored as that document type.
reissue_link() in the same file (used when the reviewer needs a fresh link) returns only {"request", "token", "path"}. That token has NO doc_type, and receive_evidence() files an upload made with an untyped token under the FIRST document type still missing.
Reproduction of the bug: request certificate_of_origin + producer_declaration + input_purchase_invoices, call reissue_link, the shipper uploads the invoice first through the only link the reviewer got -> the invoice is stored as certificate_of_origin.

One rule you must respect: _issue() adds 1 to request["link_seq"], and every token carries that number; a token is accepted only while its number equals request["link_seq"]. So per-document tokens must be minted AFTER _issue() has run, and they must use request["link_seq"] (the new value). Minted before _issue they would be rejected as "replaced".

CURRENT CODE (verbatim from src/vf_logistics/evidence.py)

1) The end of request_evidence():

# VERBATIM src/vf_logistics/evidence.py
    # N03: mint one link per doc_type so the token carries which document to expect.
    token, _ = _issue(request, scope, case_id, requested_by, now)
    links = []
    for dt in wanted:
        dt_token, dt_expires = mint_token(scope, case_id, str(request["request_id"]), int(request["link_seq"]), doc_type=dt)  # type: ignore[arg-type]
        links.append({"doc_type": dt, "token": dt_token, "path": link_path(dt_token)})
    record["requests"].append(request)

2) The whole of reissue_link():

# VERBATIM src/vf_logistics/evidence.py
async def reissue_link(
    case_id: str,
    request_id: str,
    issued_by: str,
    *,
    actor_auth: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """A new link for an open request. The old one stops working."""
    store = get_store()
    stored = await store.get_case(case_id, tenant_id=tenant_id)
    if not stored:
        raise EvidenceError("case not found", 404)
    expected_version = stored.get("_version")
    case = copy.deepcopy(stored)
    request = find_request(case, request_id)
    if request is None:
        raise EvidenceError("request not found", 404)
    if request.get("status") not in OPEN_STATUSES:
        raise EvidenceError(f"That request is {str(request.get('status')).lower()}; no link can be issued for it.", 409)

    now = utcnow()
    token, _ = _issue(request, tenant.resolve(tenant_id), case_id, issued_by, now)
    case["updated_at"] = now
    await _write(case, expected_version, tenant_id)
    await _audit(case_id, "evidence_link_issued", issued_by, actor_auth, {
        "request_id": request_id, "seq": request["link_seq"],
    }, tenant_id)
    return {"request": public_request(request), "token": token, "path": link_path(token)}

Useful facts: request["documents"] is the list of requested document types. request.get("received_docs") is a dict {doc_type: document_id} of the types already received (it may be missing or None on a request that has received nothing). link_path(token) returns "/respond/<token>". A link must never be stored in the case (the case JSON is readable by viewers): only return it.

WHAT TO DO

Step 0 (baseline). Run the command in "RUN" below (the long list of suites) and write down the number of passed tests. Run `git status --short` and tell me if it prints anything.

Step 1. Write the tests first (section TESTS below), run only them, and confirm they FAIL with KeyError: 'links' (that is the bug). Do not continue if they pass.

Step 2. Add this helper in src/vf_logistics/evidence.py, directly after the function _issue and before the comment banner "# Operations" (exact name and signature):

# NEW (add exactly this)
def _document_links(
    request: dict[str, Any], scope: str, case_id: str, doc_types: list[str],
) -> list[dict[str, str]]:
    """
    N03: one link per document type, each token naming the type it is for. They carry
    the request's CURRENT link_seq, so the next `_issue` retires them along with the
    request-level token. Call it after `_issue`, never before.
    """
    links = []
    for dt in doc_types:
        dt_token, _ = mint_token(
            scope, case_id, str(request["request_id"]), int(request["link_seq"]), doc_type=dt,
        )
        links.append({"doc_type": dt, "token": dt_token, "path": link_path(dt_token)})
    return links

Step 3. In request_evidence(), replace the 4 lines that build `links` by one call (keep the `token, _ = _issue(...)` line and the `record["requests"].append(request)` line):

# NEW (add exactly this)
    links = _document_links(request, scope, case_id, wanted)

The result of request_evidence() must be byte-for-byte the same shape as before.

Step 4. In reissue_link(): keep a variable `scope`, mint the request-level token as now, then build the typed links for ONLY the documents the request still waits for, and return them under a new key "links". Replace these two lines of the excerpt:

    token, _ = _issue(request, tenant.resolve(tenant_id), case_id, issued_by, now)

and

    return {"request": public_request(request), "token": token, "path": link_path(token)}

with:

# NEW (add exactly this)
    scope = tenant.resolve(tenant_id)
    token, _ = _issue(request, scope, case_id, issued_by, now)
    received_docs = request.get("received_docs") or {}
    still_missing = [d for d in request.get("documents") or [] if d not in received_docs]
    links = _document_links(request, scope, case_id, still_missing)

and

# NEW (add exactly this)
    return {
        "request": public_request(request),
        "token": token,
        "path": link_path(token),
        "links": links,
    }

Also replace the one-line docstring of reissue_link with:

# NEW (add exactly this)
    """
    A new link for an open request. The old one stops working.

    Returns {"request", "token", "path", "links"}. `links` has one typed link per
    document the request still waits for (N03), the same shape request_evidence
    returns. Send those: the top-level `token` has no document type, so an upload
    through it is filed as the first type still missing, whatever it really is.
    """

Do NOT remove the top-level "token" and "path" from either function: existing tests and the console still read them.

Step 5. Run the new tests again: they must pass now.

Step 6 (the route test). In tests/test_evidence_request.py, in the existing test test_cancel_and_link_routes_work_end_to_end, add ONE line right after the line `assert link.status_code == 200 and link.headers["Cache-Control"] == "no-store"`:

# NEW (add exactly this)
        assert [item["doc_type"] for item in link.get_json()["links"]] == list(ORIGIN_EVIDENCE_DOCS)

(ORIGIN_EVIDENCE_DOCS is already imported at the top of that file. Do not add an import.)

Step 7. Run the full RUN list, then the whole backend suite. Compare with the baseline from step 0.

TESTS

A) tests/test_evidence_request.py. Class TestLinksAndCancelling already has this test (verbatim, do not change it):

# VERBATIM tests/test_evidence_request.py
    def test_a_new_link_retires_the_old_one(self):
        self.put()
        first = self.ask()
        second = run(evidence.reissue_link("CASE-1", first["request"]["request_id"], REVIEWER))
        request = self.stored()["verification"]["requests"][0]
        assert request["link_seq"] == 2
        assert evidence.read_token(first["token"])["s"] == 1 < evidence.read_token(second["token"])["s"] == 2
        prints = [o["token_fingerprint"] for o in request["outbox"]]
        assert len(prints) == 2 and prints[0] != prints[1]

Add these two new methods inside the same class, directly after it (same indentation, 4 spaces):

# NEW (add exactly this)
    def test_n03_a_new_link_comes_as_one_typed_link_per_document(self):
        """N03: the reissued answer has the same per-document shape as the first request."""
        self.put()
        docs = ["certificate_of_origin", "producer_declaration", "input_purchase_invoices"]
        first = self.ask(documents=docs)
        second = run(evidence.reissue_link("CASE-1", first["request"]["request_id"], REVIEWER))
        assert [link["doc_type"] for link in second["links"]] == docs
        for link in second["links"]:
            claims = evidence.read_token(link["token"])
            assert claims["d"] == link["doc_type"]
            assert claims["s"] == 2 and claims["r"] == first["request"]["request_id"]
            assert link["path"] == f"/respond/{link['token']}"
        # The old top-level keys are still there, and the old links are retired.
        assert second["path"] == f"/respond/{second['token']}"
        assert evidence.read_token(second["token"])["s"] == 2
        assert all(evidence.read_token(link["token"])["s"] == 1 for link in first["links"])

    def test_n03_no_link_is_in_the_case_after_a_reissue(self):
        self.put()
        first = self.ask()
        second = run(evidence.reissue_link("CASE-1", first["request"]["request_id"], REVIEWER))
        stored = json.dumps(self.stored())
        for link in second["links"]:
            assert link["token"] not in stored
            assert link["token"].split(".")[1] not in stored

B) tests/test_evidence_respond.py. Class TestN03DocumentType (verbatim start, do not change):

# VERBATIM tests/test_evidence_respond.py
class TestN03DocumentType(Base):
    DOCS = ["certificate_of_origin", "producer_declaration", "input_purchase_invoices"]

    def _links(self):
        self.put()
        out = run(evidence.request_evidence("CASE-1", REVIEWER, documents=self.DOCS))
        return {link["doc_type"]: link["token"] for link in out["links"]}

Its last method is test_the_response_lists_what_is_still_missing. Add the two methods below directly after that last method, still inside the class (4-space indentation), and leave the two blank lines before `class TestEvidenceIsFiledUnderItsTenant(Base):` as they are. `self.submit(token)` is the helper already defined in the Base class of that file: it uploads a PDF through a link with the extraction mocked.

# NEW (add exactly this)
    def test_a_reissued_link_still_files_each_document_under_its_own_type(self):
        """N03 reproduction: three documents requested, a new link issued, and the invoice
        sent first. Through the reissued per-document link it is stored as the invoice;
        before, the reissue returned only an untyped link, which filed it as the first
        type still missing (the certificate of origin)."""
        links = self._links()
        request_id = self.stored()["verification"]["requests"][0]["request_id"]
        reissued = run(evidence.reissue_link("CASE-1", request_id, REVIEWER))
        new_links = {link["doc_type"]: link["token"] for link in reissued["links"]}
        assert sorted(new_links) == sorted(self.DOCS)
        result = self.submit(new_links["input_purchase_invoices"])
        assert result["doc_type"] == "input_purchase_invoices"
        assert result["still_missing"] == ["certificate_of_origin", "producer_declaration"]
        stored = self.stored()["verification"]
        assert [d["doc_type"] for d in stored["documents"]] == ["input_purchase_invoices"]
        assert list(stored["requests"][0]["received_docs"]) == ["input_purchase_invoices"]
        # The links from before the reissue are retired, typed or not.
        with pytest.raises(evidence.EvidenceError) as raised:
            self.submit(links["certificate_of_origin"])
        assert raised.value.status == 403

    def test_a_reissue_after_a_receipt_offers_links_only_for_what_is_still_missing(self):
        links = self._links()
        self.submit(links["producer_declaration"])
        request_id = self.stored()["verification"]["requests"][0]["request_id"]
        reissued = run(evidence.reissue_link("CASE-1", request_id, REVIEWER))
        assert [link["doc_type"] for link in reissued["links"]] == [
            "certificate_of_origin", "input_purchase_invoices",
        ]
        # The new link for the invoice files it as the invoice, not as the first type missing.
        result = self.submit(reissued["links"][1]["token"])
        assert result["doc_type"] == "input_purchase_invoices"
        assert result["still_missing"] == ["certificate_of_origin"]

RUN (PowerShell, from the repository root)
python -m pytest tests/test_evidence_request.py tests/test_evidence_respond.py tests/test_evidence_eval_approve.py tests/test_evidence_execution.py tests/test_evidence_reevaluable_mirror.py tests/test_n07_policy_gate.py tests/test_origin_inputs.py -q
python -m pytest tests -q

Only the tests this task is about (step 1 and step 5):
python -m pytest "tests/test_evidence_request.py::TestLinksAndCancelling" "tests/test_evidence_request.py::TestTheRoutes::test_cancel_and_link_routes_work_end_to_end" "tests/test_evidence_respond.py::TestN03DocumentType" -q

EXPECTED: before the change that command shows "5 failed, 9 passed": the 4 new tests and test_cancel_and_link_routes_work_end_to_end fail, all with KeyError: 'links'. After the change nothing fails ("14 passed"), and the passed count of the long RUN list is exactly 4 higher than your step 0 baseline (4 new tests; the route test already existed).

DONE WHEN
- the new tests failed before the change and pass after it;
- the related suites and the whole backend suite pass with no failures and the passed count is baseline + 4;
- `git diff --stat` lists exactly three files: src/vf_logistics/evidence.py, tests/test_evidence_request.py, tests/test_evidence_respond.py;
- reissue_link still returns "request", "token" and "path" and now also "links"; request_evidence still returns the same five keys;
- you did not touch mint_token, read_token, _key, _issue, receive_evidence, any auth or tenant code, or anything under frontend/.

STOP AND ASK ME (do not continue) IF
- a test other than the five named above fails, before or after your change;
- the excerpts above do not match the file;
- you think you need to change signing, token validation, receive_evidence, app.py or the frontend;
- the new tests already pass before your change.

REPORT BACK: the output of `git diff --stat`, the pass/fail summary lines of the three pytest runs (new tests before the change, related suites after, whole suite after), and one sentence on anything that surprised you. Do not commit.
``````
<!-- TASK_END -->


<!-- TASK_START: B2 -->
## Meta
- title: Investigate: Release approval at evidence_version 0 (N04)
- depends_on: []
- read_only: true
- timeout_sec: 240
- max_retries: 1

## Context
Read-only investigation of the evidence loop. Change no file. The Master reads the answer.

## Prompt
``````text
RUNNER MODE OVERRIDE (applies to everything below): you cannot run shell commands, git or tests; the runner runs them after you finish. Skip every step that says to run a command, see a test fail, check git status or compare with a baseline; do only the file edits and reading. Where the text says STOP and ask, change nothing and reply in at most 3 lines what differs.

TASK B2: READ-ONLY investigation. Answer the questions below. Do NOT change anything.

You are looking at the Python/Flask repository "Floorline" (backend in src/vf_logistics, Next.js console in frontend/). This is an investigation only.

HARD RULES
1. READ-ONLY. Use only the Read, Grep and Glob tools. Do not edit, create, delete or move any file. Do not run pytest, python, git or any shell command. If you feel you need to run something to be sure, say so in your answer instead of running it.
2. Every factual claim must name the file and function it comes from, with the 1 to 3 lines of code that decide it quoted exactly. If you did not see the code that proves a claim, write UNSURE and say what you would need to check. Never guess.
3. Do not propose or write any patch. In question 6 you give a recommendation in words only.

SCENARIO UNDER INVESTIGATION
A reviewer asks the shipper for three documents (certificate_of_origin, producer_declaration, input_purchase_invoices) with request_evidence(). The case was HELD_FOR_REVIEW before. The reviewer then cancels that request with cancel_request() BEFORE any document is submitted, so verification["evidence_version"] stays 0. Then the reviewer calls approve() with action "release", an EMPTY note and actor_auth "password". Reported result: the approval succeeds, the case becomes APPROVED, approval["evaluation_id"] is None, and no exception is raised, so nothing about the papers was ever checked.

FILES TO READ
- src/vf_logistics/evidence.py : request_evidence, cancel_request, verification_of, open_requests, reevaluate, approve, approval_is_executable, and the constants REEVALUABLE and APPROVABLE_STATES
- src/vf_logistics/verifier.py : check_origin_evidence
- src/vf_logistics/orchestrator.py : human_decide
- src/vf_logistics/app.py : the routes review_reevaluate, review_approve, review_execute
- frontend/src/components/review/ReviewPanel.tsx and frontend/src/lib/types.ts (REEVALUABLE_STATES, AWAITING_HUMAN)
- tests/test_evidence_eval_approve.py : the test test_re_evaluating_k_of_3_documents and the helpers at the top of that file

QUESTIONS (answer each one, numbered 1 to 7, in this order)

Q1. State of the case after cancel_request().
 a) In cancel_request(), which lines decide the new value of case["state"]? Quote them. For a case that was HELD_FOR_REVIEW before the request, what are afterwards: case["state"], verification["resume_state"], verification["evidence_version"], verification["evaluations"], verification["documents"], and the status of the cancelled request?
 b) What does open_requests(case) return afterwards, and why (which constant decides)?
 c) Does the cancelled request stay in verification["requests"] or is it removed?
 d) What would case["state"] be if the case had been ESCALATED before the request? And if resume_state were None?
 e) Is the resulting state in APPROVABLE_STATES? In REEVALUABLE?

Q2. Can reevaluate() run in that state at evidence_version 0?
 a) Go through every guard at the top of reevaluate() in order (the state check against REEVALUABLE, and the check on existing.get("requests")) and say for each one whether this case passes, and why a CANCELLED request counts or does not count.
 b) What does verifier.check_origin_evidence(shipment, documents) return when `documents` is an empty list? (status, present, missing, contradictions)
 c) So what evaluation record does reevaluate() append to verification["evaluations"] for this case: the values of evidence_version, status, unresolved, contradictions, and which state the case ends in?
 d) After that re-evaluation, what does approve() with action "release" and an EMPTY note do, and what does it do with a NON-empty note? Quote the lines of approve() that decide it.

Q3. Why does approve() let the release through today?
 a) Walk through approve() top to bottom for the scenario (action "release", note "", actor_auth "password", evidence_version 0, no evaluations, no open request) and say which guard passes at each step.
 b) Quote the exact condition that demands an evaluation, and say precisely why it does not fire at evidence_version 0.
 c) Why does the block that needs a note for unresolved or contradicting evidence not fire either (what is `latest_eval` there)?
 d) What are approval["evaluation_id"] and approval["evidence_version"] in the stored approval?

Q4. How does the console decide to offer Re-evaluate, and what does a Release click do?
 a) In ReviewPanel.tsx, which two conditions must hold for the Re-evaluate button to be shown? Where does REEVALUABLE_STATES come from, which backend constant does it mirror, and which test keeps them equal? Is the button shown for the case after the cancel?
 b) For the same case, are the Release and Block buttons shown (which condition)? When the reviewer confirms Release, which function runs (decide or verificationApprove), and what API calls does it make in order (approveCase then ...)? Does anything in the UI stop a release when no evaluation exists?
 c) What does the UI show when approve() answers HTTP 409 (look at the onError of verificationApprove and at how api.ts turns a non-OK answer into an Error)?

Q5. Legacy path. After the cancel, could the reviewer release the case through the older route /decide (orchestrator.human_decide) instead? Quote the guard that answers it.

Q6. Which fix is the smallest and safe?
 Option (a): approve() answers 409 "evaluate first" when there is no evaluation for the current evidence version, including evidence_version 0.
 Option (b): approve() evaluates by itself when there is none.
 For each option say: which function(s) would have to change; what new side effects it would have (writes, audit rows, floor or state changes, optimistic-lock version); whether the reviewer would see what was evaluated BEFORE the approval is recorded; whether a case in the cancelled state could be left stranded (could it still be re-evaluated through the existing UI and API afterwards? use your answers to Q2 and Q4); and the risk to the rules "deterministic checks set a risk floor, models raise but never lower" and "release paths fail closed".
 Then: which option do you recommend, in two or three sentences? And for option (a): should action "block" also be refused when there is no evaluation at evidence_version 0, or stay allowed? Justify in two sentences. Remember that at evidence_version greater than 0 approve() already refuses BOTH actions when the evaluation is missing.

Q7. Other callers. List every place in the repository (src/, scripts/, tests/) that calls approve() from evidence.py, with file and line, and say for each whether it would still work if a release at evidence_version 0 without an evaluation were refused (for example because it re-evaluates first). Use Grep for "approve(".

ANSWER FORMAT
Numbered answers Q1 to Q7, with sub-letters as above. For every claim: file path, function name, quoted code. End with a list "UNSURE:" of anything you could not verify (write "none" if none). Do not edit any file.
``````
<!-- TASK_END -->


<!-- TASK_START: B3a -->
## Meta
- title: approve() refuses a Release without an evaluation, also at evidence_version 0 (N04, code)
- depends_on:
  - B2
- target_files:
  - src/vf_logistics/evidence.py
- test_commands:
  - python -m pytest tests/test_evidence_request.py tests/test_evidence_respond.py tests/test_evidence_eval_approve.py tests/test_evidence_execution.py tests/test_evidence_reevaluable_mirror.py tests/test_n07_policy_gate.py tests/test_origin_inputs.py -q
- timeout_sec: 420
- max_retries: 1

## Context
First half of the old task B3, which failed three times (runs/B3): attempt 1 REPLACED the existing `ev_version > 0` check instead of adding a new one after it (two existing tests failed), attempt 2 put the test class at the top of the test file, attempt 3 hung for 300s. Now split: B3a is the code change only (this task), B3b adds the tests. approve() must fail closed: a release with no evaluation for the current evidence version is refused with EvidenceError (409). Existing tests must stay green; do not edit them.
Master review after B3a and B3b: temporarily remove the new check, run `python -m pytest "tests/test_evidence_eval_approve.py::TestN04ReleaseNeedsAnEvaluation" -q`, expect 5 failed and 3 passed, then restore it.

## Prompt
``````text
TASK B3a. approve() in src/vf_logistics/evidence.py must refuse a RELEASE that has no evaluation, also at evidence_version 0 (finding N04). Add ONE new check and change ONE docstring line. Nothing else.

FILE YOU MAY EDIT (only this one): src/vf_logistics/evidence.py, only inside the function approve().
The file uses Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given below. Never use a multi-line old_string. Never re-create or rewrite the file.

WHY
A reviewer requests documents, then cancels the request before any arrives. The case goes back to HELD_FOR_REVIEW, evidence_version stays 0 and there is no evaluation. approve("release", note="") now succeeds and the console executes it at once, so a shipment is released although nothing was evaluated. Releases must fail closed. A block does not need an evaluation: it only holds the shipment.

CURRENT CODE inside approve() (verbatim). The first check MUST STAY exactly as it is:
```python
    if latest_eval is None and ev_version > 0:
        raise EvidenceError(
            "The evidence has been updated but not yet re-evaluated. Re-evaluate first.", 409,
        )

    if action == "release" and actor_auth != "password":
        raise EvidenceError(
            "A release approval needs a password sign-in, not a one-click session.", 403,
        )
```

EDIT 1: insert the new check.
Edit tool: old_string is exactly this ONE line (it occurs once in the file):
    if action == "release" and actor_auth != "password":
new_string is the block below: the comment, the new check, a blank line, and then that same line again:
```python
    # N04: a release also needs an evaluation at version 0. A request cancelled before
    # anything arrived leaves no evaluation at all, and a release then went through
    # with nothing checked. A block does not need one: it only holds the shipment.
    if latest_eval is None and action == "release":
        raise EvidenceError(
            "This release has not been evaluated: no evaluation of the evidence on file "
            "exists yet. Re-evaluate first, then approve the release.", 409,
        )

    if action == "release" and actor_auth != "password":
```
Result: the new check sits AFTER the `ev_version > 0` check and BEFORE the password check. Do NOT delete, replace or edit the `ev_version > 0` check: a previous attempt replaced it and two existing tests failed.

EDIT 2: the docstring of approve().
Edit tool: old_string is exactly this ONE line (it occurs once in the file):
    - the evaluation at the current evidence_version exists
new_string is these two lines:
    - the evaluation at the current evidence_version exists (for a block at evidence
      version 0 none is needed; a release always needs one)

DONE WHEN: only src/vf_logistics/evidence.py changed; the `if latest_eval is None and ev_version > 0:` block is still there and unchanged; the new `if latest_eval is None and action == "release":` block follows it directly, before the password check; nothing outside approve() changed.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if either old_string line is not found in the file.
``````
<!-- TASK_END -->

<!-- TASK_START: B3b -->
## Meta
- title: Tests for approve() refusing a Release without an evaluation (N04, tests)
- depends_on:
  - B3a
- target_files:
  - tests/test_evidence_eval_approve.py
- test_commands:
  - python -m pytest "tests/test_evidence_eval_approve.py::TestN04ReleaseNeedsAnEvaluation" -q
  - python -m pytest tests/test_evidence_request.py tests/test_evidence_respond.py tests/test_evidence_eval_approve.py tests/test_evidence_execution.py tests/test_evidence_reevaluable_mirror.py tests/test_n07_policy_gate.py tests/test_origin_inputs.py -q
- timeout_sec: 600
- max_retries: 1

## Context
Second half of the old task B3 (see B3a). B3a already added the check to approve() in evidence.py; this task only adds the test class that pins it. The class has 8 tests. Without B3a's check, 5 of them fail (the refused-release tests); 3 pass before and after (block allowed at version 0, normal path, new evidence without a new evaluation).

## Prompt
``````text
TASK B3b. Add ONE new test class at the very END of tests/test_evidence_eval_approve.py. Nothing else. The code change it tests is already in src/vf_logistics/evidence.py (task B3a).

FILE YOU MAY EDIT (only this one): tests/test_evidence_eval_approve.py.
The file uses Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given below. Never use Write on this file. Do not add imports at the top. Do not edit, move or delete any existing line or test.

WHERE: at the END of the file, never at the top. The file ends with the class TestReevaluateKeepsAnEscalation. Its LAST line occurs once in the file:
        assert run(evidence.reevaluate("CASE-1"))["state"] == "ESCALATED"
Edit tool: old_string is exactly that ONE line (8 leading spaces). new_string is that same line, then TWO blank lines, then the whole class below, written exactly as shown.

NAMES THAT ALREADY EXIST in this file; use them and do not define or import them again: Base (class at line 45, with put() and stored()), run(), REVIEWER, DOCS3, PAPERS, _submit_per_type(), pytest, evidence. The base class is Base. Do not invent another name. The one extra import (orchestrator) sits inside the last test on purpose.

THE CLASS (add exactly this):
```python
class TestN04ReleaseNeedsAnEvaluation(Base):
    """
    A release is approved on an evaluation of the evidence on file. A request cancelled
    before anything arrived leaves evidence_version at 0 with NO evaluation, and approve()
    must refuse a release then: the console executes an approval at once, so the shipment
    would be released with nothing checked.
    """

    def _requested_then_cancelled(self, state="HELD_FOR_REVIEW"):
        self.put(state=state)
        out = run(evidence.request_evidence("CASE-1", REVIEWER, documents=DOCS3))
        run(evidence.cancel_request(
            "CASE-1", out["request"]["request_id"], REVIEWER, "Shipper unreachable",
        ))
        case = self.stored()
        assert case["state"] == state
        assert case["verification"]["evidence_version"] == 0
        assert case["verification"]["evaluations"] == []
        return case

    def test_request_cancel_then_release_with_an_empty_note_is_refused(self):
        before = self._requested_then_cancelled()
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.approve("CASE-1", "release", REVIEWER, note="", actor_auth="password"))
        assert raised.value.status == 409
        assert "re-evaluate" in raised.value.message.lower()
        after = self.stored()
        assert after["state"] == "HELD_FOR_REVIEW"
        assert after["_version"] == before["_version"]
        assert after["verification"]["approvals"] == []

    def test_a_note_does_not_stand_in_for_the_missing_evaluation(self):
        self._requested_then_cancelled()
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.approve("CASE-1", "release", REVIEWER, note="Seen it", actor_auth="password"))
        assert raised.value.status == 409
        assert self.stored()["verification"]["approvals"] == []

    def test_the_case_is_not_stranded_re_evaluate_then_release_with_a_reason(self):
        self._requested_then_cancelled()
        with pytest.raises(evidence.EvidenceError):
            run(evidence.approve("CASE-1", "release", REVIEWER, note="", actor_auth="password"))
        result = run(evidence.reevaluate("CASE-1"))
        evaluation = result["evaluation"]
        assert evaluation["evidence_version"] == 0
        assert evaluation["status"] == "missing"
        assert evaluation["unresolved"] == DOCS3
        assert result["state"] == "HELD_FOR_REVIEW"
        # Nothing was received, so every paper is unresolved: the release is an
        # exception and needs its reason, exactly as after a partial set.
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.approve("CASE-1", "release", REVIEWER, note="", actor_auth="password"))
        assert raised.value.status == 400
        approved = run(evidence.approve(
            "CASE-1", "release", REVIEWER, note="Papers seen on site", actor_auth="password",
        ))
        approval = approved["approval"]
        assert approved["state"] == "APPROVED"
        assert approval["evaluation_id"] == evaluation["evaluation_id"]
        assert approval["evidence_version"] == 0
        assert approval["exception"]["unresolved"] == DOCS3
        assert approval["exception"]["reason"] == "Papers seen on site"

    def test_an_escalated_case_is_refused_too_and_stays_escalated(self):
        self._requested_then_cancelled(state="ESCALATED")
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.approve("CASE-1", "release", REVIEWER, note="ok", actor_auth="password"))
        assert raised.value.status == 409
        assert run(evidence.reevaluate("CASE-1"))["state"] == "ESCALATED"

    def test_a_block_needs_no_evaluation_because_it_only_holds_the_shipment(self):
        self._requested_then_cancelled()
        result = run(evidence.approve("CASE-1", "block", REVIEWER, note="", actor_auth="password"))
        assert result["state"] == "APPROVED"
        assert result["approval"]["action"] == "block"
        assert result["approval"]["evaluation_id"] is None

    def test_the_normal_path_is_unchanged(self):
        self.put()
        out = run(evidence.request_evidence("CASE-1", REVIEWER, documents=DOCS3))
        _submit_per_type({link["doc_type"]: link["token"] for link in out["links"]}, PAPERS)
        evaluation = run(evidence.reevaluate("CASE-1"))["evaluation"]
        result = run(evidence.approve("CASE-1", "release", REVIEWER, note="", actor_auth="password"))
        assert result["state"] == "APPROVED"
        assert result["approval"]["evaluation_id"] == evaluation["evaluation_id"]
        assert result["approval"]["evidence_version"] == 3

    def test_new_evidence_without_a_new_evaluation_is_still_refused(self):
        """Above version 0 the rule is the old one, for a release and for a block."""
        self.put()
        out = run(evidence.request_evidence("CASE-1", REVIEWER, documents=DOCS3))
        links = {link["doc_type"]: link["token"] for link in out["links"]}
        _submit_per_type(links, {dt: PAPERS[dt] for dt in DOCS3[:2]})
        run(evidence.reevaluate("CASE-1"))
        # The third paper arrives after the evaluation on file: version 3, evaluated at 2.
        _submit_per_type(links, {DOCS3[2]: PAPERS[DOCS3[2]]})
        assert self.stored()["state"] == "HELD_FOR_REVIEW"
        assert self.stored()["verification"]["evidence_version"] == 3
        for action in ("release", "block"):
            with pytest.raises(evidence.EvidenceError) as raised:
                run(evidence.approve("CASE-1", action, REVIEWER, note="ok", actor_auth="password"))
            assert raised.value.status == 409
            assert "not yet re-evaluated" in raised.value.message

    def test_a_case_that_never_asked_for_documents_is_refused_and_not_changed(self):
        """Not reachable from the console (a case with no verification record is decided
        through /decide), but the API refuses it too, writes nothing, and leaves /decide open."""
        from vf_logistics import orchestrator

        self.put()
        before = self.stored()
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.approve("CASE-1", "release", REVIEWER, note="ok", actor_auth="password"))
        assert raised.value.status == 409
        after = self.stored()
        assert "verification" not in after
        assert after["_version"] == before["_version"]
        decided = run(orchestrator.human_decide(
            "CASE-1", "release", REVIEWER, "reviewed", actor_auth="password",
        ))
        assert decided["ok"] is True
```

DONE WHEN: only tests/test_evidence_eval_approve.py changed; the diff only ADDS lines, all after the old last line of the file; the new class is named TestN04ReleaseNeedsAnEvaluation, extends Base, and has 8 tests.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if the last-line anchor is not found.
``````
<!-- TASK_END -->


<!-- TASK_START: C1 -->
## Meta
- title: A country field listing several countries is not "provided" (N06-A)
- depends_on: []
- target_files:
  - src/vf_logistics/verifier.py
  - tests/test_origin_inputs.py
- test_commands:
  - python -m pytest tests/test_origin_inputs.py -q
  - python -m pytest tests/test_verifier.py tests/test_evidence_respond.py tests/test_evidence_eval_approve.py -q
- timeout_sec: 300
- max_retries: 2

## Context
verifier.py treats an origin country field as provided. A field naming two different countries must not count. This only makes the check stricter; the risk floor is never lowered.

## Prompt
``````text
RUNNER MODE OVERRIDE (applies to everything below): you cannot run shell commands, git or tests; the runner runs them after you finish. Skip every step that says to run a command, see a test fail, check git status or compare with a baseline; do only the file edits and reading. Where the text says STOP and ask, change nothing and reply in at most 3 lines what differs.

TASK C1 - A country field that lists two different countries must not count as "provided"

RULES FOR THIS TASK (read them first, they apply to every step)
- Work ONLY in the two files listed under FILES. Do not open, edit or "tidy" anything else.
- Make the smallest change that does the job. Do not rewrite or reformat whole files, do not run a formatter or a linter with --fix, do not rename anything.
- Do not edit, delete, skip or loosen any EXISTING test. You may only ADD tests.
- Do not touch authentication, password, session, tenant or permission code anywhere in the repo.
- Use ONLY the function and variable names that appear in the code excerpts below. If you want a name that is not in an excerpt, grep for it first; if it does not exist, do not invent it - stop and ask me.
- Edit with small exact replacements. If the edit tool says the text was not found (the files may use Windows line endings), retry with a shorter anchor of one or two lines. Never recreate a whole file.
- Before changing anything run the BASELINE command and tell me how many tests passed.
- When finished run the TEST COMMANDS and paste the last 15 lines of each output.
- If any STOP AND ASK condition at the bottom happens, stop and ask me. Do not improvise.

BACKGROUND
Floorline checks shipments for origin circumvention. On a watched trade lane the shipper must send three papers: certificate_of_origin, producer_declaration and input_purchase_invoices. A model reads each paper into a dict of fields (called "extracted"). The function check_origin_evidence(shipment, documents) in src/vf_logistics/verifier.py decides from those dicts whether each paper counts as "provided". Project rules you must keep: a check may only RAISE risk or leave it unchanged, never lower it; and when in doubt a paper is treated as NOT proven (fail closed).

THE BUG
A paper counts as provided when, for every group of required fields, _states_something(value) is true for at least one field of the group. _states_something returns True for a list when ANY element of the list is meaningful. So a certificate with origin_country = ["Vietnam", "China"] is accepted: status "provided", missing [], contradictions []. But a field that lists two different countries does not say where the goods come from, so it must not count.

FILES
- src/vf_logistics/verifier.py     (change)
- tests/test_origin_inputs.py      (append new tests at the END only)

BASELINE command (run it before any edit; expect about 150 passed)
python -m pytest tests/test_origin_inputs.py -q

CURRENT CODE (copied verbatim from the repo)

1) Helpers that already exist. You will REUSE them. Do NOT change them. They are in src/vf_logistics/verifier.py near line 366:

```python
# FILE: src/vf_logistics/verifier.py
def _scalar(value: Any) -> Any:
    """A one-element list as its element; models sometimes wrap a single answer."""
    if isinstance(value, (list, tuple)) and len(value) == 1:
        return value[0]
    return value


def _is_meaningful(value: Any) -> bool:
    """A string that states something. Anything else (None, numbers, lists of
    several) is not a stated value for the fields that use this."""
    value = _scalar(value)
    return isinstance(value, str) and not is_placeholder_text(value)


def _states_something(value: Any) -> bool:
    """A meaningful value, or a list holding at least one (["not stated", "Vietnam"])."""
    if isinstance(value, (list, tuple)):
        return any(_is_meaningful(v) for v in value)
    return _is_meaningful(value)
```

2) The country canonicaliser (near line 1266). You will add new code right AFTER it and BEFORE `def watched_lane`:

```python
# FILE: src/vf_logistics/verifier.py
def _canon_country(text: Any) -> str:
    name = str(text or "").strip().lower()
    return _COUNTRY_ALIASES.get(name, name)
```

3) The required fields, inside check_origin_evidence (near line 1387). Do NOT change this:

```python
# FILE: src/vf_logistics/verifier.py
    _REQUIRED_FIELDS: dict[str, tuple[tuple[str, ...], ...]] = {
        "certificate_of_origin": (("origin_country",),),
        # N06-E: the declaration exists to say where the inputs came from. A producer
        # name with no stated input origin does not document that.
        "producer_declaration": (("producer_name",), ("input_origins",)),
        "input_purchase_invoices": (
            ("supplier_name",),
            ("goods_origin_country", "supplier_country"),
        ),
    }
```

4) The loop in check_origin_evidence that classifies the papers (near line 1397). You will add 3 lines in it:

```python
# FILE: src/vf_logistics/verifier.py
    for doc in documents or []:
        if isinstance(doc, dict) and isinstance(doc.get("extracted"), dict):
            dt = str(doc.get("doc_type"))
            ext = doc["extracted"]
            if ext:
                read_by_type.setdefault(dt, []).append(ext)
            required = _REQUIRED_FIELDS.get(dt, ())
            if required and not all(
                any(_states_something(ext.get(f)) for f in group) for group in required
            ):
                continue
            if not ext:
                continue
            by_type.setdefault(dt, []).append(ext)
```

WHAT TO CHANGE (exactly this, nothing more)

(a) In src/vf_logistics/verifier.py, directly after the function _canon_country and before def watched_lane, insert these lines (keep two blank lines before and after, as elsewhere in the file):

```python
# ADD: src/vf_logistics/verifier.py
# N06-A: the extracted fields that must name ONE country. `input_origins` is left out
# on purpose: a producer's declaration lists several countries and is meant to.
_ONE_COUNTRY_FIELDS = ("origin_country", "goods_origin_country", "supplier_country")


def _names_several_countries(value: Any) -> bool:
    """A list that states more than one distinct country, e.g. ["Vietnam", "China"].

    Entries that say nothing ("not stated") and spellings of one country ("Vietnam",
    "Viet Nam") do not count, so ["not stated", "Vietnam"] still names one.
    """
    if not isinstance(value, (list, tuple)):
        return False
    return len({_canon_country(_scalar(v)) for v in value if _is_meaningful(v)}) > 1
```

(b) In the loop of excerpt 4, insert these 4 lines (with exactly this indentation, 12 spaces) AFTER the `continue` that ends the `if required and not all(...)` block and BEFORE the line `if not ext:`:

```python
# ADD: src/vf_logistics/verifier.py
            # N06-A: a country field that lists two countries does not say where the
            # goods come from, so the paper is unproven. It stays in `read_by_type`.
            if any(_names_several_countries(ext.get(f)) for f in _ONE_COUNTRY_FIELDS):
                continue
```

Why this is correct (use it to check yourself, do not change the design):
- Only origin_country, goods_origin_country and supplier_country must name one country. input_origins (the producer declaration's list) is NOT in _ONE_COUNTRY_FIELDS, so a declaration listing ["Vietnam", "Indonesia"] stays provided. That legitimate list must keep working.
- Countries are compared through _canon_country, so "Vietnam" and "Viet Nam" are the same country and ["Vietnam", "Viet Nam"] is NOT flagged.
- Entries that say nothing ("not stated", "N/A", None, "") are skipped by _is_meaningful, so ["not stated", "Vietnam"] still names one country and stays "provided", exactly as today.
- The new check sits AFTER the line that adds the paper to read_by_type, so what the paper says is still read for contradictions. It only stops the paper from being added to by_type, so it is not in `present`, it is in `missing`, and the status becomes "missing" (the same road an unreadable paper already takes).
- This task adds NO new finding and NO new contradiction. Do not add any.

TESTS
Append the class below at the END of tests/test_origin_inputs.py. The names plywood, docs, GOOD, check_origin_evidence and pytest already exist in that file: add NO imports. Replace the two TODO comments by two real tests that follow the instructions in the comments (use the style of the tests above them).

```python
# TEST: append to tests/test_origin_inputs.py
class TestN06ACountryFieldsNameOneCountry:
    """origin_country, goods_origin_country and supplier_country must name ONE country.
    A list of two different countries used to count as stated (one meaningful entry was
    enough), so a certificate for ["Vietnam", "China"] read as "provided"."""

    @pytest.mark.parametrize("value", [
        ["Vietnam", "China"], ["China", "Vietnam"], ["Vietnam", "Indonesia"],
        ["Vietnam", "Viet Nam", "China"], ["not stated", "Vietnam", "China"],
    ])
    def test_a_certificate_for_two_countries_is_not_provided(self, value):
        cert = {"producer_name": "Saigon Plywood Co., Ltd.", "origin_country": value}
        out = check_origin_evidence(plywood(), docs(**{**GOOD, "certificate_of_origin": cert}))
        assert out["status"] == "missing"
        assert out["missing"] == ["certificate_of_origin"]
        assert "certificate_of_origin" not in out["present"]
        assert out["findings"] == [] and out["contradictions"] == []

    @pytest.mark.parametrize("value", [
        ["Vietnam"], "Vietnam", ["Viet Nam"], ["Vietnam", "Viet Nam"],
        ["not stated", "Vietnam"], ["Vietnam", "N/A"],
    ])
    def test_one_country_is_still_provided_however_it_is_wrapped_or_spelled(self, value):
        cert = {"producer_name": "Saigon Plywood Co., Ltd.", "origin_country": value}
        out = check_origin_evidence(plywood(), docs(**{**GOOD, "certificate_of_origin": cert}))
        assert out["status"] == "provided"
        assert out["missing"] == []

    @pytest.mark.parametrize("origins", [
        ["Vietnam"], ["Vietnam", "Indonesia"], ["Vietnam", "Indonesia", "Malaysia"],
    ])
    def test_the_producers_declaration_may_still_list_several_input_origins(self, origins):
        # input_origins is a list on purpose; it is not one of the one-country fields.
        declaration = {"producer_name": "Saigon Plywood Co., Ltd.", "input_origins": origins}
        out = check_origin_evidence(plywood(), docs(**{**GOOD, "producer_declaration": declaration}))
        assert out["status"] == "provided"

    # TODO (you write this test): an invoice built as
    #     {**GOOD["input_purchase_invoices"], "goods_origin_country": ["Vietnam", "China"]}
    # (supplier_country stays the clean "Vietnam") must give status "missing" and
    # missing == ["input_purchase_invoices"]. Parametrize over the field name so the
    # same assertions also run with "supplier_country" holding the two-country list.

    # TODO (you write this test): an invoice with supplier_country "China" and
    # goods_origin_country ["Vietnam", "Indonesia"] (plus supplier_name and producer_name
    # as in GOOD) must still give status "contradicted" with a contradiction of kind
    # "input_origin": a paper that is not provable must still be read for contradictions.
```

For reference, these are the existing fixtures the tests use (already in tests/test_origin_inputs.py, do not copy them):

```python
# FILE: tests/test_origin_inputs.py
def docs(**sets) -> list[dict]:
    return [{"doc_type": t, "extracted": e} for t, e in sets.items() if e is not None]


GOOD = {
    "certificate_of_origin": {"producer_name": "Saigon Plywood Co., Ltd.", "origin_country": "Vietnam"},
    "producer_declaration": {"producer_name": "SAIGON PLYWOOD COMPANY LIMITED", "input_origins": ["Vietnam", "Indonesia"]},
    "input_purchase_invoices": {
        "supplier_name": "Mekong Veneer", "supplier_country": "Vietnam",
        "goods_origin_country": "Vietnam", "producer_name": "Saigon Plywood Co",
    },
}
```

TEST COMMANDS (PowerShell, run from the repo root)
1. python -m pytest tests/test_origin_inputs.py -q
   Expect: all pass, about 164 passed (150 old + 14 new, a bit more once your two TODO tests are written).
2. python -m pytest tests/test_verifier.py tests/test_evidence_respond.py tests/test_evidence_eval_approve.py -q
   Expect: all pass, nothing else changed.
3. python -m pytest -q
   Expect: no failures (about 1500 passed, 16 skipped).

SELF-CHECK before you report (answer each in one line)
- Which existing function did you leave untouched even though it is the "root" of the bug, and why? (answer: _states_something, because input_origins and ["not stated","Vietnam"] rely on it)
- Which of your new tests would fail if the code in step (b) were removed?
- Did `git diff --stat` show only src/vf_logistics/verifier.py and tests/test_origin_inputs.py?

STOP AND ASK (do not continue) if
- the excerpts above do not match the file (a name or a line is missing or different);
- the BASELINE command does not pass;
- any existing test fails after your change, or you feel you must edit an existing test to make it pass;
- you think you need to change _states_something, _is_meaningful, _scalar, _REQUIRED_FIELDS, any finding, any floor/severity value, or any file other than the two listed;
- you think a list of two countries should raise a contradiction or a finding instead of only being "not provided" (that is a separate decision for a human).
``````
<!-- TASK_END -->


<!-- TASK_START: D1 -->
## Meta
- title: Investigate: can the UI Resume an interrupted execution?
- depends_on: []
- read_only: true
- timeout_sec: 240
- max_retries: 1

## Context
Read-only investigation of execution claim, lease and UI. Change no file. The Master reads the answer.

## Prompt
``````text
RUNNER MODE OVERRIDE (applies to everything below): you cannot run shell commands, git or tests; the runner runs them after you finish. Skip every step that says to run a command, see a test fail, check git status or compare with a baseline; do only the file edits and reading. Where the text says STOP and ask, change nothing and reply in at most 3 lines what differs.

TASK D1 - READ-ONLY INVESTIGATION. Do NOT edit, create or delete any file. Do NOT run tests, npm, pip or anything that writes. Allowed tools: Read, Grep, Glob, and read-only git (git log -1 --oneline, git status --short, git show <rev>:<path>). Your whole output is a written report.

CONTEXT
Floorline is a Flask backend (src/vf_logistics) with a Next.js console (frontend/). Code is at git commit 85685a2 (check with: git log -1 --oneline; if it differs, say so in your report and carry on).
A reviewer first APPROVES a release/block decision (an "approval"), then EXECUTES it (backend calls the shipment tool and publishes the decision on Pub/Sub). Execution is done by evidence.execute_approval in three phases: CLAIM (case state becomes EXECUTING, the approval status becomes CLAIMING, an execution record with status "claiming" and a lease deadline claim_expires_epoch is written), SEND, CONFIRM. If the server dies between CLAIM and CONFIRM the case stays EXECUTING forever. The backend can resume such an execution after the lease has expired; inside the lease it refuses with HTTP 409.
We want to know whether the console can offer a "Resume" action for that situation, and with how little change. Your job is to find out the facts. You are NOT asked to change anything.

QUESTIONS - answer ALL of them. For each answer give: the file path, the function or constant name, the line number(s), and a quoted snippet of at most 5 lines.
Q1. Which function in frontend/src/lib/api.ts loads the case shown on the page /cases/<id>? Which URL does it request? Which file under frontend/src/app/api/ forwards that request, and does that file parse, filter or rename any field of the JSON body (look at what it does with the response body)?
Q2. Which Flask route in src/vf_logistics/app.py answers that request? Does the route filter, strip or rename anything in the stored case before jsonify? Which role decorator guards it?
Q3. In frontend/src/lib/types.ts: which interfaces describe case.verification, an approval and an execution? List the fields that EvidenceApproval and EvidenceExecution declare. Is the field claim_expires_epoch declared anywhere in frontend/src? Is the approval status declared?
Q4. In src/vf_logistics/evidence.py, function execute_approval: (a) list every value written to approval["status"] and to an execution's "status" (value, line). (b) What exactly is stored in claim_expires_epoch: which unit (seconds or milliseconds?) and computed from which constant (and what is that constant's value)? (c) What does execute_approval do when it finds an execution with status "claiming" on a case whose state is "EXECUTING": before the lease ends, and after it ends? Quote the error text of the first case.
Q5. Which backend function decides whether an approval can be executed right now? Give its name, whether it is pure, what it returns, and EVERY condition it checks (status and case state combinations, evidence version, open requests). Which of those conditions can the browser evaluate from the case JSON, and which can it not evaluate reliably?
Q6. Using only the case JSON, how can the UI tell "still running (lease not expired)" from "interrupted (lease expired)"? Write the exact formula including units. What does the backend do when claim_expires_epoch is missing or 0, and so what should the UI do? Name one reason the browser's answer can be wrong.
Q7. Today an EXECUTING case cannot be resumed from the console. Find EVERY frontend gate that prevents it (there are at least three: look in frontend/src/lib/types.ts, frontend/src/app/cases/[id]/page.tsx and frontend/src/components/review/ReviewPanel.tsx). For each: file, constant or condition, line, and what it does for an EXECUTING case. Also say which of them is the "list of states that allow actions" and in which file that list is DEFINED (versus only imported).
Q8. How would a reviewer even reach the page of an EXECUTING case? Read src/vf_logistics/worklist.py (WORK_STATES, bucket_for) and frontend/src/components/operations/WorkCard.tsx and say what you find. Do NOT propose to change it; just report the facts.
Q9. Which function does the console call to execute, with which body, and what does the reviewer see when the backend answers 409? Follow executeApproval in frontend/src/lib/api.ts through parseOrThrow / ApiError, to the onError of the verificationExecute mutation in frontend/src/components/review/ReviewPanel.tsx and to where formError is rendered.

THEN WRITE
A. "Smallest UI-only change": a numbered list (file, function or constant, what to add, at most 2 lines each) that would offer a Resume button ONLY when the claim has expired and relies on the backend 409 as the real authority.
B. "Needs a backend change?" yes or no, with the reason (is claim_expires_epoch served to the browser or not?).
C. "Could not verify": anything you are not sure about.

WHERE TO LOOK (starting points only)
Grep for: claim_expires_epoch, CLAIMING, VERIFICATION_LOOP_STATES, validApproval, orchestrator_case, fetchCase, executeApproval, WORK_STATES, AWAITING_HUMAN.

DONE WHEN
- Q1 ... Q9, A, B and C are all answered, every factual claim has a file path and a line number you actually read.
- git status --short shows nothing new (you changed no file).

STOP AND ASK (do not improvise) if
- a file or function named above does not exist, or the code clearly contradicts the CONTEXT paragraph (then report what the code really does and ask which one is right);
- you are tempted to edit a file, run the app, or run tests to "check" something: do not, report it under C instead.

PITFALLS
- Do not guess. If you did not read the line, do not cite it.
- The unit of claim_expires_epoch matters (seconds vs milliseconds). State which and prove it from the code that writes it.
- A list can be DEFINED in one file and only IMPORTED in another; report where it is defined.
- In PowerShell, square brackets in a path are wildcards, so frontend/src/app/cases/[id]/page.tsx fails with Select-String -Path. Use the Read and Grep tools (they take the path as written) or -LiteralPath.
- Do not answer from this prompt: it deliberately does not contain the answers.

FINAL REPORT (your last message)
A markdown report with the sections Q1 ... Q9, A, B, C, exactly as asked above. You changed no file, so do not list changed files.
``````
<!-- TASK_END -->


<!-- TASK_START: D2a -->
## Meta
- title: Show EXECUTING as in progress or interrupted (display only)
- depends_on: []
- target_files:
  - frontend/src/lib/types.ts
  - frontend/src/lib/operations.ts
  - frontend/src/components/review/ReviewPanel.tsx
  - frontend/src/components/review/ReviewPanel.test.tsx
- test_commands:
  - [frontend] npx vitest run src/components/review/ReviewPanel.test.tsx
  - [frontend] npx tsc --noEmit
  - [frontend] npm run lint
  - [frontend] npx vitest run
- timeout_sec: 300
- max_retries: 2

## Context
ReviewPanel should show whether an EXECUTING case is in progress or its claim has expired. Display only: no new button, no backend change.

## Prompt
``````text
RUNNER MODE OVERRIDE (applies to everything below): you cannot run shell commands, git or tests; the runner runs them after you finish. Skip every step that says to run a command, see a test fail, check git status or compare with a baseline; do only the file edits and reading. Where the text says STOP and ask, change nothing and reply in at most 3 lines what differs.

TASK D2a - show whether an EXECUTING case is "in progress" or "interrupted" (DISPLAY ONLY, no new button, no backend change).

CONTEXT
Floorline: Flask backend in src/vf_logistics, Next.js console in frontend/. Code is at git commit 85685a2 (run: git log -1 --oneline). You are on Windows (PowerShell). Every edit and command will ask for permission: that is expected.
How execution works (backend, already done, do NOT change it): when a reviewer clicks Execute, evidence.execute_approval CLAIMS the approval: the case state becomes "EXECUTING", the approval status becomes "CLAIMING", and an execution record is written with status "claiming" and claim_expires_epoch = time.time() + 300, i.e. Unix SECONDS (not milliseconds). If the server dies before it confirms, the case stays EXECUTING. Until claim_expires_epoch the backend refuses another execute (HTTP 409); after it the backend resumes the same execution. The case JSON that the console already receives contains verification.approvals[].status and verification.executions[].claim_expires_epoch (verified: it is served unfiltered).

PROBLEM (verified in the code)
1. The console says nothing about an EXECUTING case.
2. Worse, the case page frontend/src/app/cases/[id]/page.tsx does not even mount the decision panel (ReviewPanel) for an EXECUTING case: it shows "Nobody owes this case anything". The page decides with the constant VERIFICATION_LOOP_STATES, which is DEFINED in frontend/src/lib/types.ts (page.tsx only imports it) and lacks "EXECUTING". So page.tsx itself needs NO change.
3. The TypeScript interface EvidenceExecution does not declare claim_expires_epoch, so the UI cannot read it with types.

GOAL
For a case in state EXECUTING, ReviewPanel shows one status paragraph (data-testid="state-hint", the same test id the other state hints use):
- lease still running, or no claim could be read from the data: text starts with "Execution in progress"
- lease expired: text starts with "Execution interrupted - claim expired"
No Resume/Execute/Retry button appears for EXECUTING (that is the next task, D2b). No backend change. Nothing else changes.

DESIGN (already decided - do not redesign)
a) frontend/src/lib/types.ts: add "EXECUTING" to VERIFICATION_LOOP_STATES (and fix its comment); add two OPTIONAL fields to EvidenceExecution: claim_expires_epoch and resumed.
b) frontend/src/lib/operations.ts: add the exported pure function executionClaim(c, now) that returns {approval, execution, expired} or null. It mirrors the backend: the case state must be "EXECUTING"; the approval is the one with status "CLAIMING"; the execution is the LAST one of that approval with status "claiming"; the lease is expired when now >= claim_expires_epoch * 1000 (the epoch is in SECONDS, now is in milliseconds); a missing/0 epoch counts as expired (the backend does the same).
c) frontend/src/components/review/ReviewPanel.tsx: keep a "now" in React state and move it on every 15 seconds ONLY while the case is EXECUTING (setInterval inside useEffect, cleaned up). Reason: the lint rule react-hooks/purity makes `Date.now()` called while rendering an ERROR, and the lease runs out while the page is open. Then compute claim and interrupted, and render the status paragraph.

HARD RULES (read them twice, they apply to every step)
1. Touch only the files named in this prompt. No other file, no new file, no renames.
2. Change files ONLY with the Edit tool (small find-and-replace; Read a file once before you first edit it, the tool refuses otherwise). Never rewrite or re-create a whole file with Write, never reformat code you are not changing, never "tidy up".
3. Never change authentication, password, session, role, permission or tenant code (frontend lib/identity.ts, the login and proxy code, backend auth.py and the @require_* decorators in app.py). It is out of scope and must stay exactly as it is.
4. Never change, delete, rename, skip (.skip / .only / xfail) or loosen an EXISTING test. You only ADD tests.
5. Do not install or upgrade packages (no npm install, no pip install). Do not run git commit, git push, git stash, git reset or git checkout. Do not create files outside this task.
6. Do not invent names. Every function, constant, field and test id used below either already exists in the repo or is defined in this prompt. If a name you need is missing, STOP AND ASK.
7. The Python backend is the authority. The console only hints; never add console logic that replaces or bypasses a backend check.
8. If an Edit fails with "string not found" although the text looks identical, the file probably has Windows (CRLF) line endings. Read the exact lines with Read and retry with a shorter find text (even a single line). Never fall back to rewriting the file.

STEP 0 - PREFLIGHT (read only)
- git log -1 --oneline  (expect 85685a2 ... ; if different, tell me and continue only if the FIND blocks below match).
- Use Grep to confirm: "VERIFICATION_LOOP_STATES" in frontend/src/lib/types.ts, "const validApproval" in frontend/src/components/review/ReviewPanel.tsx, "state-hint" in the same file.
- Run (PowerShell, from the repository root): Set-Location frontend; npx vitest run src/components/review/ReviewPanel.test.tsx
  Expect: Tests  29 passed (29). If anything fails BEFORE you change a file, STOP AND ASK.

STEP 1 - WRITE THE TESTS FIRST (file: frontend/src/components/review/ReviewPanel.test.tsx)
The file already defines makeCase(state, verification) and renderPanel(case) (renderPanel returns the onDecided mock). Reuse them. Apply EDIT 1, 2, 3 below, in order. The tests you add:
- in progress while the lease runs; interrupted when expired; missing epoch counts as expired; EXECUTING with nothing to read is NOT called interrupted;
- no Execute/Retry/Release/Block/Request info/Re-evaluate button for EXECUTING (it.each over a running and an expired lease);
- a fake-timer test: the hint flips from "in progress" to "interrupted" while the panel stays open (fake ONLY setInterval, clearInterval and Date - faking setTimeout would break testing-library's waiting helpers - and restore real timers in afterEach);
- the constant test: VERIFICATION_LOOP_STATES contains "EXECUTING" (this is what lets the case page mount the panel).

EDIT 1: imports - add act (from testing-library) and afterEach (from vitest)
File: `frontend/src/components/review/ReviewPanel.test.tsx`
FIND (must occur exactly once; copy it exactly, including indentation):
```
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Tooltip as TooltipPrimitive } from "radix-ui";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
```
REPLACE WITH:
```
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Tooltip as TooltipPrimitive } from "radix-ui";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
```

EDIT 2: import - also import the VERIFICATION_LOOP_STATES constant from types
File: `frontend/src/components/review/ReviewPanel.test.tsx`
FIND (must occur exactly once; copy it exactly, including indentation):
```
}));

import { approveCase, cancelEvidenceRequest, decideReview, executeApproval, reevaluateCase, requestEvidence } from "@/lib/api";
import type { Case } from "@/lib/types";

import { ReviewPanel } from "./ReviewPanel";
```
REPLACE WITH:
```
}));

import { approveCase, cancelEvidenceRequest, decideReview, executeApproval, reevaluateCase, requestEvidence } from "@/lib/api";
import { type Case, VERIFICATION_LOOP_STATES } from "@/lib/types";

import { ReviewPanel } from "./ReviewPanel";
```

EDIT 3: append the new tests at the END of the file (the FIND text is the last test of the file; keep it and add the new block after it)
File: `frontend/src/components/review/ReviewPanel.test.tsx`
FIND (must occur exactly once; copy it exactly, including indentation):
```
    expect(screen.queryByRole("button", { name: "Cancel request" })).toBeNull();
  });
});
```
REPLACE WITH:
```
    expect(screen.queryByRole("button", { name: "Cancel request" })).toBeNull();
  });
});


/**
 * N08-B display: an EXECUTING case is either being worked on (the claim's lease is
 * still running) or interrupted (the lease has run out, so evidence.execute_approval
 * would resume it). The panel says which, from data the case already carries.
 * `claim_expires_epoch` is Unix SECONDS, as the backend writes it.
 */
function executing(claimExpiresEpoch?: number): Case {
  return makeCase("EXECUTING", {
    approvals: [
      { approval_id: "evapr-1", action: "release", approver: "r", evidence_version: 1, status: "CLAIMING", at: "" },
    ],
    executions: [
      {
        execution_id: "evexe-1", approval_id: "evapr-1", executor: "r", status: "claiming", at: "",
        ...(claimExpiresEpoch === undefined ? {} : { claim_expires_epoch: claimExpiresEpoch }),
      },
    ],
  });
}

const inSeconds = (s: number) => Math.floor(Date.now() / 1000) + s;

describe("ReviewPanel: an execution in flight or interrupted (N08-B)", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.useRealTimers());

  it("says the execution is in progress while the claim's lease is still running", () => {
    renderPanel(executing(inSeconds(300)));
    const hint = screen.getByTestId("state-hint").textContent ?? "";
    expect(hint).toMatch(/Execution in progress/);
    expect(hint).not.toMatch(/interrupted/);
  });

  it("says the execution is interrupted once the lease has expired", () => {
    renderPanel(executing(inSeconds(-60)));
    const hint = screen.getByTestId("state-hint").textContent ?? "";
    expect(hint).toMatch(/Execution interrupted - claim expired/);
    expect(hint).not.toMatch(/in progress/);
  });

  it("treats a claim with no recorded expiry as expired, as the backend does", () => {
    renderPanel(executing(undefined));
    expect(screen.getByTestId("state-hint").textContent).toMatch(/Execution interrupted - claim expired/);
  });

  it("does not call an EXECUTING case interrupted when there is no claim to read", () => {
    renderPanel(makeCase("EXECUTING"));
    expect(screen.getByTestId("state-hint").textContent).toMatch(/Execution in progress/);
  });

  it.each([
    ["running", 300],
    ["expired", -60],
  ])("offers no Execute, Retry or decision button for an EXECUTING case whose lease is %s", (_label, offset) => {
    renderPanel(executing(inSeconds(offset)));
    for (const name of ["Execute", "Retry", "Release", "Block", "Request info", "Re-evaluate"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
  });

  it("moves from in progress to interrupted when the lease runs out while the page is open", () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(new Date("2026-10-15T10:00:00Z"));
    renderPanel(executing(Math.floor(Date.now() / 1000) + 20));
    expect(screen.getByTestId("state-hint").textContent).toMatch(/Execution in progress/);
    act(() => {
      vi.advanceTimersByTime(30_000);
    });
    expect(screen.getByTestId("state-hint").textContent).toMatch(/Execution interrupted - claim expired/);
  });

  it("lets the case page mount the panel for an EXECUTING case", () => {
    // The page shows "Nobody owes this case anything" instead of the panel for any
    // state this list lacks.
    expect(VERIFICATION_LOOP_STATES).toContain("EXECUTING");
  });
});
```

Run (from the repository root): Set-Location frontend; npx vitest run src/components/review/ReviewPanel.test.tsx
EXPECTED NOW (red): 6 failed | 31 passed (37). Five fail with: Unable to find an element by: [data-testid="state-hint"]; one fails on the VERIFICATION_LOOP_STATES check. The two "offers no ... button" tests already pass - that is correct (they pin existing behaviour). If you see a different picture (for example a TypeScript or import error, or 0 failures), STOP AND ASK before continuing.

STEP 2 - PRODUCTION CODE
EDIT 4: VERIFICATION_LOOP_STATES - add EXECUTING and fix the comment
File: `frontend/src/lib/types.ts`
FIND (must occur exactly once; copy it exactly, including indentation):
```
/** Cases sitting in a person's queue. Mirrors AWAITING_HUMAN. */
/** States of the verification loop in which a reviewer still has an action to take. */
export const VERIFICATION_LOOP_STATES: readonly string[] = [
  "AWAITING_EVIDENCE",
  "APPROVED",
  "EXECUTION_FAILED",
];
```
REPLACE WITH:
```
/** Cases sitting in a person's queue. Mirrors AWAITING_HUMAN. */
/**
 * States of the verification loop in which a reviewer still has an action to take,
 * or has to be told what an execution is doing (EXECUTING: running, or interrupted
 * with its claim expired).
 */
export const VERIFICATION_LOOP_STATES: readonly string[] = [
  "AWAITING_EVIDENCE",
  "APPROVED",
  "EXECUTING",
  "EXECUTION_FAILED",
];
```

EDIT 5: EvidenceExecution - declare the two optional fields the backend writes
File: `frontend/src/lib/types.ts`
FIND (must occur exactly once; copy it exactly, including indentation):
```
export interface EvidenceExecution {
  execution_id: string;
  approval_id: string;
  executor: string;
  status: string;
  message_id?: string | null;
  at: string;
  reason?: string | null;
}
```
REPLACE WITH:
```
export interface EvidenceExecution {
  execution_id: string;
  approval_id: string;
  executor: string;
  status: string;
  message_id?: string | null;
  at: string;
  reason?: string | null;
  /**
   * Unix SECONDS (not milliseconds) at which this claim's lease ends. Set while the
   * status is "claiming". evidence.execute_approval refuses a second execute until
   * then and resumes the same execution after it; a missing value counts as expired.
   */
  claim_expires_epoch?: number | null;
  /** Who picked an interrupted claim up again, and when. */
  resumed?: Array<{ executor: string; at: string }>;
}
```

EDIT 6: add ExecutionClaim and executionClaim just above the docblock of riskLabel
File: `frontend/src/lib/operations.ts`
FIND (must occur exactly once; copy it exactly, including indentation):
```
/**
 * "risk 55 (floor 45)": the score, and the floor when it is not the score. The score
```
REPLACE WITH:
```
/** An execution that was claimed but never confirmed, and whether its lease has run out. */
export interface ExecutionClaim {
  approval: EvidenceApproval;
  execution: EvidenceExecution;
  /** True once the lease has ended: the execution is interrupted, not running. */
  expired: boolean;
}

/**
 * The claim a case in EXECUTING is sitting on, or null when there is none to read.
 *
 * Mirrors evidence.execute_approval, which is the authority: an approval that is
 * CLAIMING on an EXECUTING case, with a "claiming" execution of its own whose
 * `claim_expires_epoch` (Unix SECONDS) is still in the future, is being worked on by
 * someone, and everything is refused 409 until the lease ends; after that the same
 * execution is resumed. A missing epoch counts as expired, as it does there.
 *
 * Only a hint for the screen. The browser clock is not the server's, so the server
 * answers the real question whenever somebody acts on it.
 */
export function executionClaim(
  c: Pick<Case, "state" | "verification">,
  now: number = Date.now(),
): ExecutionClaim | null {
  if (c.state !== "EXECUTING") return null;
  const v = c.verification;
  const approval = (v?.approvals ?? []).find((a) => a.status === "CLAIMING");
  if (!approval) return null;
  const execution = [...(v?.executions ?? [])]
    .reverse()
    .find((e) => e.approval_id === approval.approval_id && e.status === "claiming");
  if (!execution) return null;
  const leaseEndsMs = (Number(execution.claim_expires_epoch) || 0) * 1000;
  return { approval, execution, expired: now >= leaseEndsMs };
}

/**
 * "risk 55 (floor 45)": the score, and the floor when it is not the score. The score
```

EDIT 7: react import - add useEffect
File: `frontend/src/components/review/ReviewPanel.tsx`
FIND (must occur exactly once; copy it exactly, including indentation):
```
import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, FileText, Loader2, Lock, LogIn, Sparkles } from "lucide-react";
import { useState } from "react";

import { HelpDot } from "@/components/help/HelpDot";
```
REPLACE WITH:
```
import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, FileText, Loader2, Lock, LogIn, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

import { HelpDot } from "@/components/help/HelpDot";
```

EDIT 8: operations import - add executionClaim
File: `frontend/src/components/review/ReviewPanel.tsx`
FIND (must occur exactly once; copy it exactly, including indentation):
```
import { helpFor } from "@/lib/help-content";
import { type Identity, lockReason, roleLabel, useIdentity } from "@/lib/identity";
import { CONTRADICTION_KIND_LABEL, isContradicted, latestEvaluation } from "@/lib/operations";
import {
  AWAITING_HUMAN,
```
REPLACE WITH:
```
import { helpFor } from "@/lib/help-content";
import { type Identity, lockReason, roleLabel, useIdentity } from "@/lib/identity";
import { CONTRADICTION_KIND_LABEL, executionClaim, isContradicted, latestEvaluation } from "@/lib/operations";
import {
  AWAITING_HUMAN,
```

EDIT 9: the clock: state plus an interval that only runs while the case is EXECUTING
File: `frontend/src/components/review/ReviewPanel.tsx`
FIND (must occur exactly once; copy it exactly, including indentation):
```
  const [evidenceLinks, setEvidenceLinks] = useState<string[]>([]);

  // Who this decision will be recorded as, and whether they may record one.
  //
```
REPLACE WITH:
```
  const [evidenceLinks, setEvidenceLinks] = useState<string[]>([]);

  // The clock the execution claim is read against. A claim's lease runs out while
  // this panel is open, and nothing else re-renders it, so while the case is
  // EXECUTING the clock is moved on every 15 seconds. Not ticking otherwise.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (c.state !== "EXECUTING") return;
    const timer = setInterval(() => setNow(Date.now()), 15_000);
    return () => clearInterval(timer);
  }, [c.state]);

  // Who this decision will be recorded as, and whether they may record one.
  //
```

EDIT 10: claim and interrupted - computed right after validApproval
File: `frontend/src/components/review/ReviewPanel.tsx`
FIND (must occur exactly once; copy it exactly, including indentation):
```
    (a) => a.status === "VALID",
  );

  const verificationCancel = useMutation({
```
REPLACE WITH:
```
    (a) => a.status === "VALID",
  );
  // EXECUTING with a claim whose lease has run out is an interrupted execution; with
  // the lease still running (or no claim to read) it is somebody's execution in flight.
  const claim = executionClaim(c, now);
  const interrupted = claim?.expired === true;

  const verificationCancel = useMutation({
```

EDIT 11: the status paragraph - placed between the APPROVED hint and the EXECUTION_FAILED hint
File: `frontend/src/components/review/ReviewPanel.tsx`
FIND (must occur exactly once; copy it exactly, including indentation):
```
          {hasVerification && c.state === "EXECUTION_FAILED" && (
            <p className="text-[11.5px] text-risk-critical" data-testid="state-hint">
```
REPLACE WITH:
```
          {hasVerification && c.state === "EXECUTING" && (
            <p
              className={cn("text-[11.5px]", interrupted ? "text-risk-warn" : "text-dim")}
              data-testid="state-hint"
            >
              {interrupted
                ? "Execution interrupted - claim expired. The earlier attempt never confirmed that the decision was sent."
                : "Execution in progress. The decision is being sent; this page shows the result when it finishes."}
            </p>
          )}
          {hasVerification && c.state === "EXECUTION_FAILED" && (
            <p className="text-[11.5px] text-risk-critical" data-testid="state-hint">
```

STEP 3 - RUN (from the repository root, PowerShell)
Set-Location frontend
npx vitest run src/components/review/ReviewPanel.test.tsx     # expect: Tests  37 passed (37)
npx vitest run                                                # expect: every file passes (26 files, 336 tests in the reference run)
npx tsc --noEmit                                              # expect: no output
npm run lint                                                  # expect: no errors, no warnings
If a command fails, fix ONLY what your change caused, re-run, and report what you fixed. If you cannot, STOP AND ASK.

DONE WHEN
- The 8 new tests pass, all 29 old ones still pass, the whole vitest run, tsc and lint are clean.
- git diff touches exactly four files: frontend/src/lib/types.ts, frontend/src/lib/operations.ts, frontend/src/components/review/ReviewPanel.tsx, frontend/src/components/review/ReviewPanel.test.tsx. (Check with: git diff --stat. Do not commit.)
- No Resume/Execute/Retry button was added; page.tsx, api.ts, backend files are untouched.

STOP AND ASK (do not improvise) if
- a FIND block does not match even after the CRLF advice in rule 8, or the repo is not at 85685a2 and the code around a FIND block is different;
- you feel you must edit page.tsx, api.ts, identity.ts, any Python file or any other test;
- lint reports an error from a react-hooks rule (for example react-hooks/purity) and your fix would be anything other than the code above;
- the red run in step 1 does not look like the description.

PITFALLS (the usual ways this goes wrong)
- Do NOT add "EXECUTING" to AWAITING_HUMAN. That constant mirrors the backend's list of cases a person can decide; adding EXECUTING there would put Release/Block buttons on a case that is mid-execution. Do NOT add it to REEVALUABLE_STATES either (a backend test, tests/test_evidence_reevaluable_mirror.py, pins that list to the backend).
- Do NOT edit frontend/src/app/cases/[id]/page.tsx. The list lives in types.ts.
- claim_expires_epoch is SECONDS. Comparing it with Date.now() directly (milliseconds) makes every claim look expired.
- Do NOT call Date.now() in the body of the component (lint error react-hooks/purity). Use the `now` state + interval exactly as written.
- Do NOT use vi.useFakeTimers() without the toFake list; it fakes setTimeout and the waiting helpers hang.
- Do NOT show "interrupted" when there is no claim to read. The safe default is "Execution in progress" (no button is offered either way in this task).
- Do NOT change the wording of the two paragraphs: the tests match on "Execution in progress" and "Execution interrupted - claim expired" (a plain hyphen with spaces, not an en dash).
- Do NOT edit the existing "does not offer Re-evaluate once the case is EXECUTING" test; it must keep passing as it is.

FINAL REPORT (your last message, plain text, no code dump)
- The list of files you changed (paths only).
- For each command in the "Run" steps: the command and its last summary line (for example "Tests  37 passed (37)").
- Anything that surprised you or did not match this prompt.
``````
<!-- TASK_END -->


<!-- TASK_START: D2b -->
## Meta
- title: Resume button for an interrupted execution
- depends_on:
  - D2a
- target_files:
  - frontend/src/components/review/ReviewPanel.tsx
  - frontend/src/components/review/ReviewPanel.test.tsx
  - tests/test_evidence_execution.py
- test_commands:
  - [frontend] npx vitest run src/components/review/ReviewPanel.test.tsx
  - [frontend] npx tsc --noEmit
  - [frontend] npm run lint
  - python -m pytest tests/test_evidence_execution.py tests/test_n07_policy_gate.py -q
- timeout_sec: 300
- max_retries: 2

## Context
Adds a Resume button shown only for an interrupted execution. The backend stays the authority (claim lease, idempotency key). Never retry from the UI without the backend allowing it.

## Prompt
``````text
RUNNER MODE OVERRIDE (applies to everything below): you cannot run shell commands, git or tests; the runner runs them after you finish. Skip every step that says to run a command, see a test fail, check git status or compare with a baseline; do only the file edits and reading. Where the text says STOP and ask, change nothing and reply in at most 3 lines what differs.

TASK D2b - a "Resume" button for an interrupted execution (the backend stays the authority). Depends on D2a.

CONTEXT
Floorline: Flask backend in src/vf_logistics, Next.js console in frontend/. You are on Windows (PowerShell). Every edit and command will ask for permission: that is expected.
Backend facts (already implemented and tested, do NOT change any backend source file):
- evidence.execute_approval(case_id, approval_id, executor, ...) carries out an approved decision. On a case in state "EXECUTING" whose approval has status "CLAIMING" and whose execution (status "claiming") has a claim_expires_epoch in the past, it RESUMES that same execution (same execution_id). Inside the lease it raises HTTP 409 with the text "Another execution of this approval is in progress. Try again after it finishes or its claim expires." claim_expires_epoch is Unix SECONDS.
- The route is POST /api/v1/review/<case_id>/execute with body {"approval_id": "<id>"}; the console function is executeApproval(caseId, approvalId) in frontend/src/lib/api.ts (it already exists; do not change it). A backend refusal arrives as an ApiError whose message is the backend's text; ReviewPanel already shows it in the red alert (formError) through the onError of the verificationExecute mutation.
- The data the UI needs IS served: the case JSON (GET /api/v1/orchestrator/case/<id>) is returned unfiltered, including verification.approvals[].status and verification.executions[].claim_expires_epoch. NO backend change is needed. The three backend tests in this task only PROVE that and pin it.

WHAT D2a ALREADY GAVE YOU (verify first, see step 0)
- operations.ts exports executionClaim(c, now) -> {approval, execution, expired} | null.
- ReviewPanel.tsx has `const [now, setNow]`, `const claim = executionClaim(c, now);` and `const interrupted = claim?.expired === true;`, plus the status paragraph for EXECUTING.
- The test file has the helpers `executing(claimExpiresEpoch?)` and `inSeconds(s)` and the imports act/afterEach.

PROBLEM
For an interrupted execution (EXECUTING, approval CLAIMING, lease expired) the console shows the D2a status text but offers nothing to continue. The Execute/Retry button only exists for APPROVED / EXECUTION_FAILED and only for an approval with status "VALID" (validApproval).

GOAL
When interrupted, show a button labelled exactly "Resume" next to where Execute/Retry appear. Clicking it calls executeApproval(c.case_id, <the CLAIMING approval's approval_id>). Success and failure handling is the existing handling of verificationExecute (toast, onDecided, red alert with the backend's 409 text). No confirmation dialog (Execute and Retry have none). The button is hidden while the lease is still running, when there is no readable claim, and in every state other than EXECUTING.

DESIGN (already decided - do not redesign)
- `resumable` = the CLAIMING approval of the claim, but only when `interrupted` is true. (executionClaim already returns null unless the case state is EXECUTING.)
- The SAME mutation verificationExecute is reused; its mutationFn picks `resumable ?? validApproval`.
- The one existing Button is reused: shown when `resumable != null` OR (state is APPROVED/EXECUTION_FAILED AND there is a validApproval); label "Resume" if resumable, else "Retry" if EXECUTION_FAILED, else "Execute".
- The hint paragraph for the interrupted case gets one more sentence: "Resume continues it."
- The Resume button lives inside the same block as Execute, which is already hidden from people without the Reviewer role (the role lock above it). Do not move it outside that block.
- Browser clock vs server clock: the button is only a hint that the lease is over. If the server says the claim is still live it answers 409 and the text is shown. Do NOT add any "try anyway" logic or any retry/suppression of that error.

HARD RULES (read them twice, they apply to every step)
1. Touch only the files named in this prompt. No other file, no new file, no renames.
2. Change files ONLY with the Edit tool (small find-and-replace; Read a file once before you first edit it, the tool refuses otherwise). Never rewrite or re-create a whole file with Write, never reformat code you are not changing, never "tidy up".
3. Never change authentication, password, session, role, permission or tenant code (frontend lib/identity.ts, the login and proxy code, backend auth.py and the @require_* decorators in app.py). It is out of scope and must stay exactly as it is.
4. Never change, delete, rename, skip (.skip / .only / xfail) or loosen an EXISTING test. You only ADD tests.
5. Do not install or upgrade packages (no npm install, no pip install). Do not run git commit, git push, git stash, git reset or git checkout. Do not create files outside this task.
6. Do not invent names. Every function, constant, field and test id used below either already exists in the repo or is defined in this prompt. If a name you need is missing, STOP AND ASK.
7. The Python backend is the authority. The console only hints; never add console logic that replaces or bypasses a backend check.
8. If an Edit fails with "string not found" although the text looks identical, the file probably has Windows (CRLF) line endings. Read the exact lines with Read and retry with a shorter find text (even a single line). Never fall back to rewriting the file.

STEP 0 - PREFLIGHT (read only)
- Use Grep to confirm D2a is in place: "export function executionClaim" in frontend/src/lib/operations.ts; "const interrupted = claim?.expired === true" and "const [now, setNow]" in frontend/src/components/review/ReviewPanel.tsx; "function executing(" and "const inSeconds" in frontend/src/components/review/ReviewPanel.test.tsx.
  If any is missing, STOP AND ASK (D2a must be done first).
- Run (repository root): Set-Location frontend; npx vitest run src/components/review/ReviewPanel.test.tsx   -> expect Tests  37 passed (37).
- Run (repository root): python -m pytest tests/test_evidence_execution.py tests/test_n07_policy_gate.py -q   -> expect 41 passed.
  If either fails before you change anything, STOP AND ASK.

STEP 1 - FRONTEND TESTS FIRST (file: frontend/src/components/review/ReviewPanel.test.tsx)
The tests you add: Resume is offered and calls executeApproval("CASE-1", "evapr-1") (the CLAIMING approval) once the claim expired; Resume is offered when the epoch is missing; NOT offered while the lease runs; NOT offered with no claim to read; NOT offered on APPROVED / EXECUTION_FAILED / HELD_FOR_REVIEW / RELEASED_BY_HUMAN even if the data still has a CLAIMING approval; a backend 409 is shown in the alert and the button is usable again and onDecided is not called; Resume appears after the lease runs out while the panel is open (fake timers, same toFake list as D2a); Execute for an APPROVED case is unchanged and has no Resume next to it.

EDIT 1: import - add ApiError (a real class, the api mock keeps the original exports)
File: `frontend/src/components/review/ReviewPanel.test.tsx`
FIND (must occur exactly once; copy it exactly, including indentation):
```
}));

import { approveCase, cancelEvidenceRequest, decideReview, executeApproval, reevaluateCase, requestEvidence } from "@/lib/api";
import { type Case, VERIFICATION_LOOP_STATES } from "@/lib/types";

import { ReviewPanel } from "./ReviewPanel";
```
REPLACE WITH:
```
}));

import { ApiError, approveCase, cancelEvidenceRequest, decideReview, executeApproval, reevaluateCase, requestEvidence } from "@/lib/api";
import { type Case, VERIFICATION_LOOP_STATES } from "@/lib/types";

import { ReviewPanel } from "./ReviewPanel";
```

EDIT 2: append the new tests at the END of the file (the FIND text is the end of the D2a tests; keep it and add the new block after it)
File: `frontend/src/components/review/ReviewPanel.test.tsx`
FIND (must occur exactly once; copy it exactly, including indentation):
```
    expect(VERIFICATION_LOOP_STATES).toContain("EXECUTING");
  });
});
```
REPLACE WITH:
```
    expect(VERIFICATION_LOOP_STATES).toContain("EXECUTING");
  });
});


/**
 * N08-B action: Resume continues an interrupted execution -- a CLAIMING approval on
 * an EXECUTING case whose claim has expired -- through the same executeApproval call
 * as Execute and Retry. The button is a hint that the lease is over; the backend stays
 * the authority and answers 409 while the claim is still live.
 */
describe("ReviewPanel: resuming an interrupted execution (N08-B)", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.useRealTimers());

  it("offers Resume, and calls executeApproval with the claimed approval, once the claim has expired", async () => {
    vi.mocked(executeApproval).mockResolvedValueOnce({ state: "RELEASED_BY_HUMAN" });
    const onDecided = renderPanel(executing(inSeconds(-60)));
    expect(screen.getByTestId("state-hint").textContent).toMatch(/Resume continues it/);
    fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    await waitFor(() => expect(executeApproval).toHaveBeenCalledWith("CASE-1", "evapr-1"));
    await waitFor(() => expect(onDecided).toHaveBeenCalled());
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("offers Resume for a claim with no recorded expiry", () => {
    renderPanel(executing(undefined));
    expect(screen.getByRole("button", { name: "Resume" })).toBeTruthy();
  });

  it("does not offer Resume while the claim's lease is still running", () => {
    renderPanel(executing(inSeconds(300)));
    expect(screen.queryByRole("button", { name: "Resume" })).toBeNull();
    expect(executeApproval).not.toHaveBeenCalled();
  });

  it("does not offer Resume for an EXECUTING case with no claim to read", () => {
    renderPanel(makeCase("EXECUTING"));
    expect(screen.queryByRole("button", { name: "Resume" })).toBeNull();
  });

  it.each(["APPROVED", "EXECUTION_FAILED", "HELD_FOR_REVIEW", "RELEASED_BY_HUMAN"])(
    "does not offer Resume on a %s case, whatever its approvals say",
    (state) => {
      const stale = executing(inSeconds(-60));
      renderPanel({ ...stale, state } as unknown as Case);
      expect(screen.queryByRole("button", { name: "Resume" })).toBeNull();
    },
  );

  it("shows the backend's refusal when the claim is still live there", async () => {
    const refusal =
      "Another execution of this approval is in progress. Try again after it finishes or its claim expires.";
    vi.mocked(executeApproval).mockRejectedValueOnce(new ApiError(refusal, 409, "http"));
    const onDecided = renderPanel(executing(inSeconds(-60)));
    fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    expect((await screen.findByRole("alert")).textContent).toContain(refusal);
    expect(onDecided).not.toHaveBeenCalled();
    // The reviewer can try again later: the button is not left disabled.
    expect((screen.getByRole("button", { name: "Resume" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("offers Resume only after the lease runs out while the page is open", () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(new Date("2026-10-15T10:00:00Z"));
    renderPanel(executing(Math.floor(Date.now() / 1000) + 20));
    expect(screen.queryByRole("button", { name: "Resume" })).toBeNull();
    act(() => {
      vi.advanceTimersByTime(30_000);
    });
    expect(screen.getByRole("button", { name: "Resume" })).toBeTruthy();
  });

  it("keeps Execute for an approved case, with no Resume beside it", () => {
    const approval = { approval_id: "evapr-1", action: "release", approver: "r", evidence_version: 1, status: "VALID", at: "" };
    renderPanel(makeCase("APPROVED", { approvals: [approval] }));
    expect(screen.getByRole("button", { name: "Execute" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Resume" })).toBeNull();
  });
});
```

Run (repository root): Set-Location frontend; npx vitest run src/components/review/ReviewPanel.test.tsx
EXPECTED NOW (red): 4 failed | 44 passed (48). The 4 failures: the first test (the hint does not yet contain "Resume continues it"), "offers Resume for a claim with no recorded expiry", "shows the backend's refusal ...", "offers Resume only after the lease runs out ...". The other new tests are negative guards and already pass - that is correct. Different picture (import/TypeScript error, 0 failures)? STOP AND ASK.

STEP 2 - BACKEND CONTRACT TESTS (file: tests/test_evidence_execution.py - only ADD; change nothing else in that file)
These three tests are EXPECTED TO PASS IMMEDIATELY, because no backend change is needed: they pin what the console depends on (the served case carries the CLAIMING approval and a claim_expires_epoch in seconds one lease from now; a resume inside the lease is a 409 with the "Another execution ..." text and publishes nothing; a resume after the lease continues the SAME execution over HTTP). If one of them FAILS, that means the data is not what this prompt says: STOP AND ASK and do not touch any backend source file.

EDIT 3: import time (alphabetical position, between sys and types)
File: `tests/test_evidence_execution.py`
FIND (must occur exactly once; copy it exactly, including indentation):
```
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch
```
REPLACE WITH:
```
import os
import sys
import time
import types
from unittest.mock import AsyncMock, MagicMock, patch
```

EDIT 4: append the new test class just before class TestExecutedDecisionsReachTheLearningLoop
File: `tests/test_evidence_execution.py`
FIND (must occur exactly once; copy it exactly, including indentation):
```
class TestExecutedDecisionsReachTheLearningLoop(Base):
    """
```
REPLACE WITH:
```
class TestN08BInterruptedExecutionOverHttp(Base):
    """What the console reads and does about an execution that was claimed and never
    confirmed. It offers Resume from the case JSON a viewer can read, so that JSON must
    carry the claim and its deadline (Unix seconds); the answer to Resume is the
    backend's, and its 409 text is what the console shows."""

    def setup_method(self):
        super().setup_method()
        from vf_logistics import app as app_mod

        self.app_mod = app_mod
        self.was = app_mod.limiter.enabled
        app_mod.limiter.enabled = False
        self.client = app_mod.app.test_client()

    def teardown_method(self):
        self.app_mod.limiter.enabled = self.was
        super().teardown_method()

    def _interrupted(self):
        """A case left EXECUTING / CLAIMING by a send that never came back."""
        self.put()
        self.request_and_submit()
        run(evidence.reevaluate("CASE-1"))
        approval_id = run(evidence.approve(
            "CASE-1", "release", REVIEWER, note="Reviewed", actor_auth="password",
        ))["approval"]["approval_id"]
        boom = AsyncMock(side_effect=asyncio.CancelledError)
        with patch("vf_logistics.tools.publish_decision", new=boom), pytest.raises(asyncio.CancelledError):
            run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        return approval_id

    def _headers(self):
        from test_console_session import mint

        return {"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint(REVIEWER, amr="password")}

    def test_the_case_a_viewer_reads_carries_the_claim_and_its_deadline(self):
        before = time.time()
        approval_id = self._interrupted()
        served = self.client.get("/api/v1/orchestrator/case/CASE-1").get_json()
        assert served["state"] == "EXECUTING"
        record = served["verification"]
        assert [(a["approval_id"], a["status"]) for a in record["approvals"]] == [(approval_id, "CLAIMING")]
        (execution,) = record["executions"]
        assert execution["approval_id"] == approval_id and execution["status"] == "claiming"
        # Seconds since the epoch, one lease from the claim: the console compares it with
        # its own clock to tell a running execution from an interrupted one.
        assert before + evidence.CLAIM_LEASE_S <= execution["claim_expires_epoch"] <= time.time() + evidence.CLAIM_LEASE_S

    def test_a_resume_inside_the_lease_is_refused_with_the_text_the_console_shows(self):
        approval_id = self._interrupted()
        with patch("vf_logistics.tools.publish_decision", new=AsyncMock(return_value=OK_RECEIPT)) as publish:
            response = self.client.post("/api/v1/review/CASE-1/execute",
                                        json={"approval_id": approval_id}, headers=self._headers())
        assert response.status_code == 409
        assert "Another execution of this approval is in progress" in response.get_json()["error"]
        publish.assert_not_called()
        assert self.stored()["state"] == "EXECUTING"

    def test_a_resume_after_the_lease_continues_the_same_execution(self):
        approval_id = self._interrupted()
        case = self.stored()
        claimed = case["verification"]["executions"][0]["execution_id"]
        case["verification"]["executions"][0]["claim_expires_epoch"] = time.time() - 1
        run(self.store.put_case(case))
        with patch("vf_logistics.tools.publish_decision", new=AsyncMock(return_value=OK_RECEIPT)):
            response = self.client.post("/api/v1/review/CASE-1/execute",
                                        json={"approval_id": approval_id}, headers=self._headers())
        assert response.status_code == 200 and response.get_json()["state"] == "RELEASED_BY_HUMAN"
        stored = self.stored()
        assert [e["execution_id"] for e in stored["verification"]["executions"]] == [claimed]
        assert stored["verification"]["executions"][0]["status"] == "sent"
        assert stored["verification"]["approvals"][0]["status"] == "EXECUTED"


class TestExecutedDecisionsReachTheLearningLoop(Base):
    """
```

Run (repository root): python -m pytest tests/test_evidence_execution.py -q -k N08B      -> expect 3 passed.

STEP 3 - PRODUCTION CODE (file: frontend/src/components/review/ReviewPanel.tsx)
EDIT 5: resumable - right after the `interrupted` line
File: `frontend/src/components/review/ReviewPanel.tsx`
FIND (must occur exactly once; copy it exactly, including indentation):
```
  const interrupted = claim?.expired === true;
```
REPLACE WITH:
```
  const interrupted = claim?.expired === true;
  // The approval Resume continues: the CLAIMING one of an interrupted execution. Only a
  // hint that the lease is over -- evidence.execute_approval decides, and answers 409
  // while the claim is still live (the message is shown in the form's alert).
  const resumable = interrupted ? claim?.approval : undefined;
```

EDIT 6: the mutation: act on the resumable approval when there is one, else on validApproval
File: `frontend/src/components/review/ReviewPanel.tsx`
FIND (must occur exactly once; copy it exactly, including indentation):
```
  const verificationExecute = useMutation({
    mutationFn: () => {
      if (!validApproval) throw new Error("No valid approval to execute");
      return executeApproval(c.case_id, validApproval.approval_id);
    },
    onSuccess: (result) => {
```
REPLACE WITH:
```
  const verificationExecute = useMutation({
    mutationFn: () => {
      const approval = resumable ?? validApproval;
      if (!approval) throw new Error("No valid approval to execute");
      return executeApproval(c.case_id, approval.approval_id);
    },
    onSuccess: (result) => {
```

EDIT 7: the hint for the interrupted case gets the extra sentence
File: `frontend/src/components/review/ReviewPanel.tsx`
FIND (must occur exactly once; copy it exactly, including indentation):
```
            >
              {interrupted
                ? "Execution interrupted - claim expired. The earlier attempt never confirmed that the decision was sent."
                : "Execution in progress. The decision is being sent; this page shows the result when it finishes."}
            </p>
```
REPLACE WITH:
```
            >
              {interrupted
                ? "Execution interrupted - claim expired. The earlier attempt never confirmed that the decision was sent. Resume continues it."
                : "Execution in progress. The decision is being sent; this page shows the result when it finishes."}
            </p>
```

EDIT 8: the Button's visibility condition
File: `frontend/src/components/review/ReviewPanel.tsx`
FIND (must occur exactly once; copy it exactly, including indentation):
```
            )}
          {hasVerification &&
            (c.state === "APPROVED" || c.state === "EXECUTION_FAILED") &&
            validApproval && (
              <Button
                size="sm"
```
REPLACE WITH:
```
            )}
          {hasVerification &&
            (resumable != null ||
              ((c.state === "APPROVED" || c.state === "EXECUTION_FAILED") && validApproval != null)) && (
              <Button
                size="sm"
```

EDIT 9: the Button's label
File: `frontend/src/components/review/ReviewPanel.tsx`
FIND (must occur exactly once; copy it exactly, including indentation):
```
                  <Loader2 className="mr-1.5 size-3.5 animate-spin motion-reduce:animate-none" />
                )}
                {c.state === "EXECUTION_FAILED" ? "Retry" : "Execute"}
              </Button>
            )}
```
REPLACE WITH:
```
                  <Loader2 className="mr-1.5 size-3.5 animate-spin motion-reduce:animate-none" />
                )}
                {resumable ? "Resume" : c.state === "EXECUTION_FAILED" ? "Retry" : "Execute"}
              </Button>
            )}
```

STEP 4 - RUN (repository root, PowerShell)
Set-Location frontend
npx vitest run src/components/review/ReviewPanel.test.tsx     # expect: Tests  48 passed (48)
npx vitest run                                                # expect: every file passes (26 files, 347 tests in the reference run)
npx tsc --noEmit                                              # expect: no output
npm run lint                                                  # expect: no errors, no warnings
Set-Location ..
python -m pytest tests/test_evidence_execution.py tests/test_n07_policy_gate.py -q     # expect: 44 passed
python -m pytest tests -q                                     # expect: everything passes (1489 passed, 16 skipped in the reference run; the skipped count can differ on your machine)
If a command fails, fix ONLY what your change caused, re-run, and report. If you cannot, STOP AND ASK.

DONE WHEN
- 11 new frontend tests + 3 new backend tests pass; every old test still passes; tsc and lint are clean.
- git diff --stat (nothing is committed, so it still includes D2a) lists exactly these five files in total: frontend/src/lib/types.ts, frontend/src/lib/operations.ts, frontend/src/components/review/ReviewPanel.tsx, frontend/src/components/review/ReviewPanel.test.tsx, tests/test_evidence_execution.py. In D2b itself you only edited the last three of them. No backend SOURCE file (anything under src/) changed. Do not commit.
- Execute still works for APPROVED, Retry still works for EXECUTION_FAILED (existing tests prove it).

STOP AND ASK (do not improvise) if
- D2a is not in place or a FIND block does not match (after the CRLF advice in rule 8);
- one of the three backend contract tests fails;
- you think a backend source change is needed, or you want to edit api.ts, page.tsx, types.ts, operations.ts (none of them changes in D2b);
- the red run in step 1 does not look like the description.

PITFALLS (the usual ways this goes wrong)
- validApproval has status "VALID"; the approval to resume has status "CLAIMING". Do not look for the Resume approval in validApproval, and do not change validApproval's condition.
- executeApproval takes the APPROVAL id (approval.approval_id), not the execution id and not the case id alone.
- Do not add "EXECUTING" to the condition (c.state === "APPROVED" || c.state === "EXECUTION_FAILED"); `resumable` already implies EXECUTING.
- Do not decide the 409 yourself in the browser, do not catch and hide the backend's error, do not add a retry loop, do not add a client-side lease check inside mutationFn. The backend decides.
- Do not move the button out of the role-locked block or give it its own permission logic. Do not touch identity/auth code.
- Do not compare claim_expires_epoch with Date.now() yourself anywhere; executionClaim already does it, in seconds.
- Do not change the Execute or Retry labels or behaviour; their existing tests must pass unchanged.
- In tests: mockResolvedValueOnce / mockRejectedValueOnce must be consumed by the test that sets them (each of the tests above clicks Resume exactly once), otherwise the leftover leaks into the next test.
- Keep the backend test class independent: it only ADDS a class; do not edit the Base class, the fixtures or any existing test in that file.

FINAL REPORT (your last message, plain text, no code dump)
- The list of files you changed (paths only).
- For each command in the "Run" steps: the command and its last summary line (for example "Tests  37 passed (37)").
- Anything that surprised you or did not match this prompt.
``````
<!-- TASK_END -->


<!-- TASK_START: N01a -->
## Meta
- title: Send the idempotency key as a Pub/Sub message attribute (N01)
- depends_on: []
- target_files:
  - src/vf_logistics/tools.py
  - tests/test_evidence_execution.py
  - tests/test_publish_attribute.py
- test_commands:
  - python -m pytest tests/test_publish_attribute.py -q
  - python -m pytest tests/test_evidence_execution.py tests/test_evidence_request.py tests/test_evidence_respond.py tests/test_evidence_eval_approve.py tests/test_evidence_reevaluable_mirror.py tests/test_n07_policy_gate.py tests/test_origin_inputs.py tests/test_executor_client.py tests/test_pure_logic.py tests/test_internal_execute.py -q
- timeout_sec: 420
- max_retries: 1

## Context
Independent review Rev2, finding N01 (still open): a retry after an execution whose confirmation was lost must not be applied twice downstream. execute_approval already puts `idempotency_key` (`exec-<approval_id>`, fixed per approval) in the message BODY. This task also sends it as a Pub/Sub message ATTRIBUTE, so a subscriber can drop a repeat without parsing the body. Downstream deduplication itself lives outside this repository and is not part of this task.
Master review: with the two helper edits and without the tools.py edit, `python -m pytest tests/test_publish_attribute.py -q` shows 1 failed and 1 passed.

## Prompt
``````text
TASK N01a. Send the idempotency key as a Pub/Sub message attribute.

FILES YOU MAY EDIT (only these three):
1. src/vf_logistics/tools.py, only inside publish_decision_direct().
2. tests/test_evidence_execution.py, only the two lines of the helper _fake_pubsub() named below.
3. tests/test_publish_attribute.py, a NEW file: it does not exist yet. Create it with Write, with exactly the content given at the end.
The first two files use Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given (leading spaces included). Never use a multi-line old_string. Never use Write on an existing file.

EDIT 1 (tools.py). old_string is exactly this ONE line (12 leading spaces; it occurs once):
            future = publisher.publish(topic, json.dumps(body).encode("utf-8"))
new_string is these six lines:
            # The key is also a message attribute so a subscriber can drop a repeat
            # without parsing the body (N01). Attribute values must be strings.
            attributes = {}
            if body.get("idempotency_key"):
                attributes["idempotency_key"] = str(body["idempotency_key"])
            future = publisher.publish(topic, json.dumps(body).encode("utf-8"), **attributes)

EDIT 2 (tests/test_evidence_execution.py, the fake Pub/Sub client must accept attributes). old_string is exactly this ONE line (4 leading spaces; it occurs once):
    def publish(topic, data):
new_string:
    def publish(topic, data, **attributes):

EDIT 3 (same file, record the attributes). old_string is exactly this ONE line (8 leading spaces; it occurs once):
        published.append({"topic": topic, "body": __import__("json").loads(data)})
new_string:
        published.append({"topic": topic, "attributes": attributes, "body": __import__("json").loads(data)})
Edits 2 and 3 only widen a test helper. Do not change any test or assertion.

THE NEW FILE tests/test_publish_attribute.py (create with Write, exactly this content):
```python
"""
The idempotency key travels with the Pub/Sub message as an attribute (N01), so a
subscriber can drop a repeat without parsing the body.
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
from test_evidence_eval_approve import Base  # noqa: E402
from test_evidence_execution import _fake_pubsub, _with_pubsub  # noqa: E402
from vf_logistics import tools  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class TestTheKeyIsAMessageAttribute(Base):
    def _publish(self, decision):
        pubsub, published = _fake_pubsub(["msg-1"])
        with patch.dict(os.environ, {"PROJECT_ID": "test-project"}), _with_pubsub(pubsub):
            receipt = run(tools.publish_decision("CASE-1", decision))
        return receipt, published

    def test_the_idempotency_key_is_sent_as_an_attribute(self):
        receipt, published = self._publish({"outcome": "RELEASED_BY_HUMAN", "idempotency_key": "exec-abc"})
        assert receipt["status"] == "done"
        assert published[0]["attributes"] == {"idempotency_key": "exec-abc"}
        assert published[0]["body"]["idempotency_key"] == "exec-abc"

    def test_a_decision_without_a_key_carries_no_attribute(self):
        receipt, published = self._publish({"outcome": "HELD_FOR_REVIEW"})
        assert receipt["status"] == "done"
        assert published[0]["attributes"] == {}
```

DONE WHEN: only the three files changed; tools.py differs from before by the six lines of edit 1 only; test_evidence_execution.py differs by exactly two lines; the new file has 2 tests.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if an old_string line is not found, or if tests/test_publish_attribute.py already exists.
``````
<!-- TASK_END -->

<!-- TASK_START: N01b -->
## Meta
- title: A decision is published once per idempotency key (N01)
- depends_on:
  - N01a
- target_files:
  - src/vf_logistics/tools.py
  - tests/test_publish_dedupe.py
- test_commands:
  - python -m pytest tests/test_publish_dedupe.py -q
  - python -m pytest tests/test_evidence_execution.py tests/test_evidence_request.py tests/test_evidence_respond.py tests/test_evidence_eval_approve.py tests/test_evidence_reevaluable_mirror.py tests/test_n07_policy_gate.py tests/test_origin_inputs.py tests/test_executor_client.py tests/test_pure_logic.py tests/test_internal_execute.py -q
- timeout_sec: 480
- max_retries: 1

## Context
Finding N01: when the claim of an execution expires after the publish was accepted but before the outcome was confirmed, the resume publishes the decision a second time. tools.publish_decision() is the one place every publish passes through, so it looks in the audit log for an earlier publish of the same case with the same idempotency key that went out (status done, with a message id), and returns that receipt instead of publishing again. A failed or unconfirmed earlier publish does not count. release_shipment/hold_shipment still run again on a resume; that behaviour is pinned by an existing test and stays.
Master review: with the tests and without the tools.py change, `python -m pytest tests/test_publish_dedupe.py -q` shows 1 failed and 3 passed.

## Prompt
``````text
TASK N01b. tools.publish_decision() must not publish a decision a second time when an earlier publish with the same idempotency key already went out.

FILES YOU MAY EDIT (only these two):
1. src/vf_logistics/tools.py, only the two places below.
2. tests/test_publish_dedupe.py, a NEW file: it does not exist yet. Create it with Write, with exactly the content given at the end.
tools.py uses Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given. Never use a multi-line old_string. Never use Write on tools.py.

EDIT 1 (tools.py, add a helper above publish_decision). old_string is exactly this ONE line (no leading spaces; it occurs once):
async def publish_decision(
new_string is the whole helper below, then two blank lines, then that same line again:
```python
async def _earlier_publish(
    case_id: str, key: str, tenant_id: str | None,
) -> dict[str, Any] | None:
    """
    The audit row of a publish with this idempotency key that went out, or None.

    A retry after an interrupted execution must not publish the decision a second
    time when the first publish was accepted and only its confirmation was lost.
    Only a row that carries a message id proves the publish; a failed one does not.
    """
    rows, _ = await get_store().query_audit(
        case_id=case_id, action="publish_decision", status="done", limit=200,
        tenant_id=tenant_id,
    )
    for row in rows:
        detail = row.get("detail") or {}
        if detail.get("idempotency_key") != key:
            continue
        delegated = detail.get("executor")
        message_id = detail.get("message_id") or (
            delegated.get("message_id") if isinstance(delegated, dict) else None
        )
        if message_id:
            return row
    return None


async def publish_decision(
```

EDIT 2 (tools.py, use the helper). old_string is exactly this ONE line (4 leading spaces; it occurs once):
    body = {"case_id": case_id, **decision, "at": utcnow()}
new_string is the block below: the check, a blank line, and then that same line again:
```python
    key = decision.get("idempotency_key")
    if key:
        earlier = await _earlier_publish(case_id, str(key), tenant_id)
        if earlier is not None:
            return earlier

    body = {"case_id": case_id, **decision, "at": utcnow()}
```
Do not change anything else in tools.py: not publish_decision_direct, not release_shipment, not hold_shipment, not _audit.

THE NEW FILE tests/test_publish_dedupe.py (create with Write, exactly this content):
```python
"""
A decision is published once per idempotency key (N01). A retry after an interrupted
execution must not publish it again when the first publish was accepted.
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
from test_evidence_eval_approve import Base  # noqa: E402
from test_evidence_execution import _fake_pubsub, _with_pubsub  # noqa: E402
from vf_logistics import tools  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class TestAnEarlierPublishIsNotRepeated(Base):
    KEY = "exec-apr-1"

    def _publish(self, pubsub, case_id="CASE-1", key=KEY):
        decision = {"outcome": "RELEASED_BY_HUMAN"}
        if key:
            decision["idempotency_key"] = key
        with patch.dict(os.environ, {"PROJECT_ID": "test-project"}), _with_pubsub(pubsub):
            return run(tools.publish_decision(case_id, decision))

    def test_a_second_publish_with_the_same_key_returns_the_first_receipt(self):
        pubsub, published = _fake_pubsub(["msg-1", "msg-2"])
        first = self._publish(pubsub)
        second = self._publish(pubsub)
        assert len(published) == 1
        assert second["audit_id"] == first["audit_id"]
        assert second["status"] == "done"
        assert second["detail"]["message_id"] == "msg-1"

    def test_a_publish_that_failed_is_sent_again(self):
        pubsub, published = _fake_pubsub([TimeoutError("deadline exceeded"), "msg-2"])
        first = self._publish(pubsub)
        assert first["status"] == "failed"
        second = self._publish(pubsub)
        assert second["status"] == "done"
        assert second["detail"]["message_id"] == "msg-2"
        assert len(published) == 2

    def test_another_key_or_another_case_is_sent(self):
        pubsub, published = _fake_pubsub(["msg-1", "msg-2", "msg-3"])
        self._publish(pubsub)
        self._publish(pubsub, key="exec-apr-2")
        self._publish(pubsub, case_id="CASE-2")
        assert len(published) == 3

    def test_a_decision_without_a_key_is_always_sent(self):
        pubsub, published = _fake_pubsub(["msg-1", "msg-2"])
        self._publish(pubsub, key=None)
        self._publish(pubsub, key=None)
        assert len(published) == 2
```

DONE WHEN: only the two files changed; tools.py gained the helper and the five-line check and nothing else; the new file has 4 tests.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if an old_string line is not found, or if tests/test_publish_dedupe.py already exists.
``````
<!-- TASK_END -->

<!-- TASK_START: N01c -->
## Meta
- title: Test that a resume after an accepted publish does not publish again (N01)
- depends_on:
  - N01b
- target_files:
  - tests/test_resume_after_publish.py
- test_commands:
  - python -m pytest tests/test_resume_after_publish.py -q
  - python -m pytest tests/test_evidence_execution.py tests/test_publish_dedupe.py -q
- timeout_sec: 420
- max_retries: 1

## Context
End-to-end pin for N01a and N01b through execute_approval: the first attempt publishes and dies before it confirms, the claim lease runs out, the resume reuses the first message id and sends nothing. Tests only; the code is already in tools.py.
Master review: remove the check in publish_decision() that calls _earlier_publish, run the new test, expect it to fail, then restore the check.

## Prompt
``````text
TASK N01c. Create ONE new test file. Nothing else.

FILE YOU MAY EDIT (only this one): tests/test_resume_after_publish.py, a NEW file: it does not exist yet. Create it with Write, with exactly the content below. Do not edit any other file.

```python
"""
A resume after a publish that was accepted but never confirmed (N01): the lease has
run out, the same execution continues, and the decision is not published a second time.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_evidence_eval_approve import Base  # noqa: E402
from test_evidence_execution import _fake_pubsub, _with_pubsub  # noqa: E402
from vf_logistics import evidence, tools  # noqa: E402

REVIEWER = "reviewer@forwarder.example"


def run(coro):
    return asyncio.run(coro)


class TestAResumeAfterAnAcceptedPublish(Base):
    def test_the_resume_does_not_publish_the_decision_again(self):
        self.put()
        self.request_and_submit()
        run(evidence.reevaluate("CASE-1"))
        approval_id = run(evidence.approve(
            "CASE-1", "release", REVIEWER, note="Reviewed", actor_auth="password",
        ))["approval"]["approval_id"]
        pubsub, published = _fake_pubsub(["msg-1", "msg-2"])
        real_publish = tools.publish_decision

        async def publish_then_die(*args, **kwargs):
            await real_publish(*args, **kwargs)
            raise asyncio.CancelledError

        env = {"PROJECT_ID": "test-project"}
        # First attempt: the claim is written, the publish is accepted, and the process
        # dies before the outcome is confirmed.
        with patch.dict(os.environ, env), _with_pubsub(pubsub):
            with patch("vf_logistics.tools.publish_decision", new=publish_then_die), \
                    pytest.raises(asyncio.CancelledError):
                run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        assert len(published) == 1
        assert self.stored()["state"] == "EXECUTING"

        case = self.stored()
        case["verification"]["executions"][0]["claim_expires_epoch"] = time.time() - 1
        run(self.store.put_case(case))

        with patch.dict(os.environ, env), _with_pubsub(pubsub):
            result = run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        assert result["state"] == "RELEASED_BY_HUMAN"
        assert result["message_id"] == "msg-1"
        assert len(published) == 1
        stored = self.stored()
        assert [e["status"] for e in stored["verification"]["executions"]] == ["sent"]
        assert stored["verification"]["executions"][0]["message_id"] == "msg-1"
        assert stored["verification"]["approvals"][0]["status"] == "EXECUTED"
```

DONE WHEN: only tests/test_resume_after_publish.py was created, and it has exactly 1 test.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if tests/test_resume_after_publish.py already exists.
``````
<!-- TASK_END -->

<!-- TASK_START: R2 -->
## Meta
- title: Investigate: what a dedicated exception operation for N04 would change
- depends_on: []
- read_only: true
- timeout_sec: 420
- max_retries: 1

## Context
Finding N04 (open): a release over unresolved or contradicting evidence is approved through the same approve() call as a normal release, with a note. The review asks for a dedicated operation with its own permission and a mandatory record. Before any design, list what depends on today's behaviour. Read-only: change nothing.

## Prompt
``````text
TASK R2 (READ-ONLY: change nothing, create nothing). Answer in at most 45 lines, with file:line for every item.

Question: what would be affected if a release over unresolved or contradicting evidence could be approved only through a dedicated exception operation, and approve() refused such a release?

1. BACKEND. In src/vf_logistics/evidence.py, function approve(): the branch that handles unresolved or contradicting evidence (search "requires a note explaining the exception") and the shape of the "exception" record it stores. In src/vf_logistics/app.py: every route that calls evidence.approve (search "evidence.approve(") and the decorators on it.
2. ROLES. In src/vf_logistics/auth.py: the roles and their order (class Role, ROLE_HIERARCHY, ROLE_RANK), and what require_role, require_password_session and the decorators require_reviewer and require_operator (defined elsewhere; search "def require_reviewer") check.
3. TESTS THAT RELY ON TODAY'S BEHAVIOUR. Search tests/ for approvals of "release" over unresolved or contradicting evidence: search for "exception", "unresolved" and "contradict" in tests/test_evidence_eval_approve.py, tests/test_evidence_execution.py, tests/test_n07_policy_gate.py and tests/test_origin_inputs.py. List each as file::test_name, one line each.
4. FRONTEND. Where frontend/src/components/review/ReviewPanel.tsx and frontend/src/lib/api.ts send a release together with a note for such a case (search "approveCase" and "contradicted"), and which tests in frontend/src/components/review/ReviewPanel.test.tsx cover it (list test titles).
5. ONE LINE: the number of existing tests (backend + frontend) that would have to change.
Do not propose a design. Do not edit any file.
STOP AND REPLY (at most 3 lines) if a search finds nothing you can cite.
``````
<!-- TASK_END -->

<!-- TASK_START: N04a -->
## Meta
- title: approve_exception(), a release over open evidence as an operation of its own (N04, step 1)
- depends_on:
  - N01c
- target_files:
  - src/vf_logistics/evidence.py
  - tests/test_exception_approval.py
- test_commands:
  - python -m pytest tests/test_exception_approval.py -q
  - python -m pytest tests/test_exception_approval.py tests/test_evidence_request.py tests/test_evidence_respond.py tests/test_evidence_eval_approve.py tests/test_evidence_execution.py tests/test_evidence_reevaluable_mirror.py tests/test_n07_policy_gate.py tests/test_origin_inputs.py tests/test_publish_dedupe.py tests/test_resume_after_publish.py -q
- timeout_sec: 600
- max_retries: 1

## Context
Review Rev2, finding N04. Today a release over unresolved or contradicting evidence goes through approve() with a note. Decision (human, chose the thorough fix): such a release becomes its own operation, approve_exception(), that names every waived item, gives a reason, needs a stronger role (set on the route in N04b) and a password, and stores a mandatory record. This is step 1 of 3 and is ADDITIVE: approve() keeps accepting a note for now, so no existing test changes. Step 2 (a later task) makes approve() refuse such a release and moves the existing tests to the new operation. Step 3 is the console.
Waived items are the unresolved document types and "contradiction:<kind>" for each contradiction of the current evaluation.
Master review: with the new test file and without the evidence.py edits, `python -m pytest tests/test_exception_approval.py -q` shows 5 failed and 1 passed (the pinned legacy test).

## Prompt
``````text
TASK N04a. Add approve_exception() to src/vf_logistics/evidence.py and let approve() record what an exception waives. Six small edits and one new test file.

FILES YOU MAY EDIT (only these two):
1. src/vf_logistics/evidence.py, only inside approve() and directly above it.
2. tests/test_exception_approval.py, a NEW file: it does not exist yet. Create it with Write, with exactly the content given at the end.
evidence.py uses Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given (leading spaces included). Never use a multi-line old_string. Never use Write on evidence.py. Apply the edits in the order 1 to 6. Do not touch any other line of approve(): in particular keep the existing note check and the existing `exception = {` record exactly as they are.

EDIT 1 (a new parameter of approve). old_string, ONE line (4 leading spaces; occurs once):
    execute: bool = True,
new_string, two lines:
```python
    execute: bool = True,
    waived: list[str] | None = None,
```

EDIT 2 (only a release can be an exception). old_string, ONE line (4 leading spaces; occurs once):
    exception: dict[str, Any] | None = None
new_string, the lines below, ending with that same line again:
```python
    if waived is not None and action != "release":
        raise EvidenceError("Only a release can be an exception.", 400)

    exception: dict[str, Any] | None = None
```

EDIT 3 (every waived item must be named). old_string, ONE line (12 leading spaces; occurs once):
            if not (note or "").strip():
new_string, the lines below, ending with that same line again:
```python
            needed = unresolved + [f"contradiction:{c['kind']}" for c in contradictions]
            if waived is not None and sorted(set(waived)) != sorted(set(needed)):
                raise EvidenceError(
                    "An exception must name every waived item: " + ", ".join(needed) + ".", 400,
                )
            if not (note or "").strip():
```

EDIT 4 (record what was waived). old_string, ONE line (16 leading spaces; occurs once):
                exception["contradictions"] = contradictions
new_string, the lines below (the first is the old line again):
```python
                exception["contradictions"] = contradictions
            if waived is not None:
                exception["operation"] = "exception"
                exception["waived"] = sorted(set(waived))
```

EDIT 5 (nothing to waive). old_string, ONE line (4 leading spaces; occurs once):
    approval: dict[str, Any] = {
new_string, the lines below, ending with that same line again:
```python
    if waived is not None and exception is None:
        raise EvidenceError("There is nothing to waive: approve the release normally.", 409)

    approval: dict[str, Any] = {
```

EDIT 6 (the new operation, directly above approve). old_string, ONE line (no leading spaces; occurs once):
async def approve(
new_string is the whole function below, then two blank lines, then that same line again:
```python
async def approve_exception(
    case_id: str,
    approver: str,
    reason: str,
    waived: list[str],
    *,
    actor_auth: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """
    Release over unresolved or contradicting evidence, as an operation of its own.

    The caller names every item it waives (the unresolved documents, and
    "contradiction:<kind>" for each contradiction) and gives a reason; the approval
    records both. Who may call it is decided by the route (operator role and a
    password sign-in); approve() enforces the password rule again.
    """
    if not (reason or "").strip():
        raise EvidenceError("An exception needs a reason.", 400)
    if not waived:
        raise EvidenceError("An exception must name what it waives.", 400)
    return await approve(
        case_id, "release", approver, note=reason.strip(), actor_auth=actor_auth,
        waived=[str(w) for w in waived], tenant_id=tenant_id,
    )


async def approve(
```

THE NEW FILE tests/test_exception_approval.py (create with Write, exactly this content):
```python
"""
A release over unresolved or contradicting evidence is an operation of its own (N04):
it names every item it waives and gives a reason, and the approval records both.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_evidence_eval_approve import DOCS3, PAPERS, Base, _submit_per_type  # noqa: E402
from vf_logistics import evidence  # noqa: E402

REVIEWER = "reviewer@forwarder.example"
REASON = "Certificate misread; checked the original"
WAIVED = ["contradiction:certificate_country"]


def run(coro):
    return asyncio.run(coro)


class TestTheExceptionOperation(Base):
    def _full_set(self, **override):
        self.put()
        out = run(evidence.request_evidence("CASE-1", REVIEWER, documents=DOCS3))
        links = {link["doc_type"]: link["token"] for link in out["links"]}
        _submit_per_type(links, {**PAPERS, **override})
        return run(evidence.reevaluate("CASE-1"))

    def _contradicted(self):
        result = self._full_set(
            certificate_of_origin={"producer_name": "Saigon Plywood Co", "origin_country": "China"},
        )
        assert result["evaluation"]["status"] == "contradicted"

    def test_it_records_what_it_waives_and_why(self):
        self._contradicted()
        result = run(evidence.approve_exception(
            "CASE-1", REVIEWER, REASON, WAIVED, actor_auth="password",
        ))
        assert result["state"] == "APPROVED"
        exception = result["approval"]["exception"]
        assert exception["operation"] == "exception"
        assert exception["waived"] == WAIVED
        assert exception["reason"] == REASON
        assert exception["approved_by"] == REVIEWER
        assert [c["kind"] for c in exception["contradictions"]] == ["certificate_country"]
        assert result["approval"]["evaluation_id"] is not None

    def test_it_refuses_a_list_that_does_not_match_what_is_open(self):
        self._contradicted()
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.approve_exception(
                "CASE-1", REVIEWER, REASON, ["something_else"], actor_auth="password",
            ))
        assert raised.value.status == 400
        assert "every waived item" in raised.value.message
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.approve_exception("CASE-1", REVIEWER, REASON, [], actor_auth="password"))
        assert raised.value.status == 400
        assert "what it waives" in raised.value.message
        assert self.stored()["state"] == "ESCALATED"
        assert self.stored()["verification"]["approvals"] == []

    def test_it_needs_a_reason(self):
        self._contradicted()
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.approve_exception("CASE-1", REVIEWER, "   ", WAIVED, actor_auth="password"))
        assert raised.value.status == 400
        assert "reason" in raised.value.message
        assert self.stored()["verification"]["approvals"] == []

    def test_it_needs_a_password_sign_in(self):
        self._contradicted()
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.approve_exception("CASE-1", REVIEWER, REASON, WAIVED, actor_auth="one_click"))
        assert raised.value.status == 403
        assert self.stored()["verification"]["approvals"] == []

    def test_it_refuses_when_there_is_nothing_to_waive(self):
        assert self._full_set()["evaluation"]["status"] == "provided"
        with pytest.raises(evidence.EvidenceError) as raised:
            run(evidence.approve_exception(
                "CASE-1", REVIEWER, REASON, ["certificate_of_origin"], actor_auth="password",
            ))
        assert raised.value.status == 409
        assert "nothing to waive" in raised.value.message
        assert self.stored()["verification"]["approvals"] == []

    def test_the_normal_approval_still_takes_a_note_in_this_step(self):
        """Pinned only until the step that makes approve() refuse an exception."""
        self._contradicted()
        result = run(evidence.approve(
            "CASE-1", "release", REVIEWER, note=REASON, actor_auth="password",
        ))
        assert result["state"] == "APPROVED"
        assert "operation" not in result["approval"]["exception"]
```

DONE WHEN: only the two files changed; evidence.py gained the six edits and nothing else; no existing line of approve() was removed or changed except by edits 1 to 6 (edits 2 to 5 only ADD lines around existing ones); the new file has 6 tests.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if an old_string line is not found, or if tests/test_exception_approval.py already exists.
``````
<!-- TASK_END -->

<!-- TASK_START: N04b -->
## Meta
- title: Route for the exception operation, operator role and password (N04, step 1)
- depends_on:
  - N04a
- target_files:
  - src/vf_logistics/app.py
  - tests/test_rbac.py
  - tests/test_exception_route.py
- test_commands:
  - python -m pytest tests/test_exception_route.py tests/test_rbac.py -q
  - python -m pytest tests/test_exception_approval.py tests/test_evidence_request.py tests/test_evidence_respond.py tests/test_evidence_eval_approve.py tests/test_evidence_execution.py tests/test_evidence_reevaluable_mirror.py tests/test_n07_policy_gate.py tests/test_origin_inputs.py tests/test_publish_dedupe.py tests/test_resume_after_publish.py -q
- timeout_sec: 600
- max_retries: 1

## Context
Step 1 of the N04 fix, second half: POST /api/v1/review/<case_id>/approve-exception calls evidence.approve_exception() (task N04a). Permission: the operator role, one above the reviewer who makes normal approvals, plus a password session. tests/test_rbac.py pins the exact set of password-only routes "so a change is deliberate"; this task adds the new route to that set, which is the one existing line of that test that may change.
Master review: with the new test file and without the app.py edit, `python -m pytest tests/test_exception_route.py -q` shows 5 failed.

## Prompt
``````text
TASK N04b. Add one route to src/vf_logistics/app.py, add its path to one set in tests/test_rbac.py, and create one new test file.

FILES YOU MAY EDIT (only these three):
1. src/vf_logistics/app.py, only the ONE insertion below.
2. tests/test_rbac.py, only the ONE insertion below.
3. tests/test_exception_route.py, a NEW file: it does not exist yet. Create it with Write, with exactly the content given at the end.
The first two files use Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given. Never use a multi-line old_string. Never use Write on an existing file.

EDIT 1 (app.py). old_string, ONE line (no leading spaces; occurs once):
@app.route("/api/v1/review/<case_id>/execute", methods=["POST"])
new_string is the whole block below (a new route, two blank lines), ending with that same line again:
```python
@app.route("/api/v1/review/<case_id>/approve-exception", methods=["POST"])
@require_operator
@require_password_session
@limiter.limit("10 per minute")
def review_approve_exception(case_id: str) -> Any:
    """Release over unresolved or contradicting evidence: a reason and every waived item."""
    from vf_logistics import evidence

    body = _json_object()
    person, actor_auth = _acting_person(body)
    waived = body.get("waived")
    if not isinstance(waived, list):
        return jsonify({"error": "waived must be a list of the items this exception waives"}), 400
    return _evidence_response(evidence.approve_exception(
        case_id, person, str(body.get("reason") or "").strip(), [str(w) for w in waived],
        actor_auth=actor_auth, tenant_id=_tenant(),
    ))


@app.route("/api/v1/review/<case_id>/execute", methods=["POST"])
```

EDIT 2 (tests/test_rbac.py, the pinned set of password-only routes). old_string, ONE line (12 leading spaces; occurs once):
            "/api/v1/review/<case_id>/execute",
new_string, these two lines:
```python
            "/api/v1/review/<case_id>/execute",
            "/api/v1/review/<case_id>/approve-exception",
```
Change nothing else in that test.

THE NEW FILE tests/test_exception_route.py (create with Write, exactly this content):
```python
"""
The exception route: a release over unresolved or contradicting evidence is its own
operation, behind the operator role and a password sign-in (N04).
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
from test_console_session import TEST_KEY, mint  # noqa: E402
from test_evidence_eval_approve import DOCS3, PAPERS, Base, _submit_per_type  # noqa: E402
from vf_logistics import evidence  # noqa: E402

REVIEWER = "reviewer@forwarder.example"
OPERATOR = "operator@forwarder.example"
URL = "/api/v1/review/CASE-1/approve-exception"
BODY = {
    "reason": "Certificate misread; checked the original",
    "waived": ["contradiction:certificate_country"],
}


def run(coro):
    return asyncio.run(coro)


class TestTheExceptionRoute(Base):
    def setup_method(self):
        super().setup_method()
        from vf_logistics import app as app_mod

        # A one-click (guest) token is honoured only while the guest door is open for that account.
        guest_door = {"VF_ONE_CLICK_JUDGE": "true", "VF_ONE_CLICK_EMAIL": OPERATOR}
        self.operators = patch.dict(os.environ, {"OPERATOR_EMAILS": OPERATOR, **guest_door})
        self.operators.start()
        self.app_mod = app_mod
        self.was = app_mod.limiter.enabled
        app_mod.limiter.enabled = False
        self.client = app_mod.app.test_client()
        self.put()
        out = run(evidence.request_evidence("CASE-1", REVIEWER, documents=DOCS3))
        links = {link["doc_type"]: link["token"] for link in out["links"]}
        _submit_per_type(links, {
            **PAPERS,
            "certificate_of_origin": {"producer_name": "Saigon Plywood Co", "origin_country": "China"},
        })
        assert run(evidence.reevaluate("CASE-1"))["evaluation"]["status"] == "contradicted"

    def teardown_method(self):
        self.app_mod.limiter.enabled = self.was
        self.operators.stop()
        super().teardown_method()

    def _post(self, email, amr, body):
        headers = {"X-VF-API-Key": TEST_KEY, "X-VF-Session": mint(email, amr=amr)}
        return self.client.post(URL, json=body, headers=headers)

    def test_a_reviewer_may_not_make_an_exception(self):
        response = self._post(REVIEWER, "password", BODY)
        assert response.status_code == 403
        assert self.stored()["verification"]["approvals"] == []

    def test_an_operator_on_a_one_click_session_may_not(self):
        response = self._post(OPERATOR, "one_click", BODY)
        assert response.status_code == 403
        assert response.get_json()["required_auth"] == "password"
        assert self.stored()["verification"]["approvals"] == []

    def test_an_operator_with_a_password_makes_a_recorded_exception(self):
        response = self._post(OPERATOR, "password", BODY)
        assert response.status_code == 200
        served = response.get_json()
        assert served["state"] == "APPROVED"
        exception = served["approval"]["exception"]
        assert exception["operation"] == "exception"
        assert exception["waived"] == BODY["waived"]
        assert exception["reason"] == BODY["reason"]
        assert exception["approved_by"] == OPERATOR

    def test_a_list_that_misses_an_item_is_refused(self):
        response = self._post(OPERATOR, "password", {**BODY, "waived": ["something_else"]})
        assert response.status_code == 400
        assert "every waived item" in response.get_json()["error"]
        assert self.stored()["verification"]["approvals"] == []

    def test_a_body_without_a_waived_list_is_refused(self):
        response = self._post(OPERATOR, "password", {"reason": BODY["reason"]})
        assert response.status_code == 400
        assert "waived" in response.get_json()["error"]
```

DONE WHEN: only the three files changed; app.py gained the new route and nothing else; tests/test_rbac.py gained exactly one line; the new file has 5 tests.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if an old_string line is not found, or if tests/test_exception_route.py already exists.
``````
<!-- TASK_END -->

<!-- TASK_START: V1 -->
## Meta
- title: Verification script for the independent review of 2026-10-15 (review VI)
- depends_on: []
- target_files:
  - scripts/verify_review_vi.py
- test_commands:
  - python -c "import hashlib; t=open('scripts/verify_review_vi.py',encoding='utf-8').read().replace(chr(13)+chr(10),chr(10)).rstrip(); raise SystemExit(0 if hashlib.sha256(t.encode('utf-8')).hexdigest()=='ea55baaa42bc20af50c70d215a6faa385d95ec64384bf854f15fff4770047dd1' else 1)"
  - python scripts/verify_review_vi.py --no-frontend
- timeout_sec: 900
- max_retries: 1

## Context
The question: how much of review VI (Floorline_Independent_Review_VI_20261015.pdf) does the repository already address? The Master answers from the table this script prints, not from the sub-agent's words. The script edits no source file. It runs the existing tests that assert the correct behaviour, five probes for findings that have no test, and the frontend tests (skipped with --no-frontend), then prints one table per check, one per item, and the percentage. It also writes orchestrator/runs/verify_review_vi.md and always exits 0, so the runner records the table even while findings are open. After this task it can be run directly at any time, with no runner: `python scripts/verify_review_vi.py`.
The first test command compares the file with the exact content below (a hash), so a copy mistake fails the task.
Master review: read `orchestrator/runs/V1/attempt_1.log` (section TESTS) or `orchestrator/runs/verify_review_vi.md`. Run the script once without --no-frontend for the full table.

## Prompt
``````text
TASK V1. Create ONE new file. Nothing else.

FILE YOU MAY EDIT (only this one): scripts/verify_review_vi.py, a NEW file: it does not exist yet. Create it with Write, with exactly the content below, character for character. Do not change, shorten, reformat or "improve" any line. Do not edit any other file.

```python
#!/usr/bin/env python3
"""
verify_review_vi.py - how much of the independent review of 2026-10-15
(Floorline_Independent_Review_VI) the repository already addresses.

Read-only: it edits no source file. It runs the existing tests that assert the CORRECT
behaviour, a few probes for findings that have no test, and prints one table with a
percentage. It writes orchestrator/runs/verify_review_vi.md and always exits 0, so a
runner records the table instead of stopping at the first open finding.

    python scripts/verify_review_vi.py
    python scripts/verify_review_vi.py --no-frontend      # skip the vitest part
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(os.environ.get("VF_REPO") or Path(__file__).resolve().parent.parent)
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

PASS, FAIL, NO_TEST, OUT_OF_SCOPE, SKIP = "PASS", "FAIL", "NO TEST", "OUT OF SCOPE", "SKIP"
ITEMS = ["N01", "N02", "N03", "N04", "N05", "N06", "N07", "N08", "E01"]

# (id, item, what the review asks for, kind, spec)
#   py:    [(test file, test name prefix)]   every match must pass, at least one must exist
#   js:    [test title fragment]             every match must pass, at least one must exist
#   probe: name of a probe function below
#   none:  kind "no_test" or "out_of_scope", spec is the reason
CHECKS = [
    ("N01-a", "N01", "the same idempotency key on every retry", "py",
     [("test_evidence_execution.py", "test_n01_idempotency_key_is_fixed_per_approval")]),
    ("N01-b", "N01", "a resume is refused inside the lease and continues the same execution after it", "py",
     [("test_evidence_execution.py", "test_n01_a_second_person_cannot_resume_inside_the_lease"),
      ("test_evidence_execution.py", "test_n01_a_second_person_can_resume_after_the_lease_expires")]),
    ("N01-c", "N01", "a publish accepted but never confirmed is not published again on resume", "py",
     [("test_resume_after_publish.py", "test_the_resume_does_not_publish_the_decision_again"),
      ("test_publish_dedupe.py", "test_a_second_publish_with_the_same_key_returns_the_first_receipt"),
      ("test_publish_attribute.py", "test_the_idempotency_key_is_sent_as_an_attribute")]),
    ("N01-d", "N01", "an unknown send result is told apart from a send that did not happen", "probe",
     "probe_unknown_publish"),
    ("N01-e", "N01", "deduplication at the receiving system", "none",
     (OUT_OF_SCOPE, "the receiver is not in this repository")),
    ("N02-a", "N02", "a failed send is EXECUTION_FAILED, not completed", "py",
     [("test_evidence_execution.py", "test_a_publish_that_raises_is_a_failed_send_not_a_crash"),
      ("test_evidence_execution.py", "test_a_delegated_publish_that_did_not_happen_is_a_failed_send")]),
    ("N03-a", "N03", "a re-issued link is one typed link per missing document", "py",
     [("test_evidence_request.py", "test_n03_a_new_link_comes_as_one_typed_link_per_document"),
      ("test_evidence_respond.py", "test_a_reissued_link_still_files_each_document_under_its_own_type")]),
    ("N03-b", "N03", "three documents in any order are stored under their own type", "py",
     [("test_evidence_respond.py", "test_three_documents_in_any_order_are_each_stored_as_their_own_type")]),
    ("N04-a", "N04", "a request cancelled before any upload cannot lead to an unevaluated release", "py",
     [("test_evidence_eval_approve.py", "test_request_cancel_then_release_with_an_empty_note_is_refused"),
      ("test_evidence_eval_approve.py", "test_a_note_does_not_stand_in_for_the_missing_evaluation")]),
    ("N04-b", "N04", "a release over missing evidence needs a reason and stores the exception", "py",
     [("test_evidence_eval_approve.py", "test_n04_release_with_unresolved_evidence_needs_a_note"),
      ("test_evidence_eval_approve.py", "test_n04_release_of_that_case_is_an_exception_with_a_recorded_reason")]),
    ("N04-c", "N04", "an exception is its own operation: operator role, password, every waived item named", "py",
     [("test_exception_approval.py", "test_it_records_what_it_waives_and_why"),
      ("test_exception_route.py", "test_a_reviewer_may_not_make_an_exception"),
      ("test_exception_route.py", "test_an_operator_with_a_password_makes_a_recorded_exception")]),
    ("N05-a", "N05", "a closed case, or one that never asked for documents, is not re-evaluated", "py",
     [("test_evidence_eval_approve.py", "test_a_case_outside_the_loop_is_refused_and_left_untouched"),
      ("test_evidence_eval_approve.py", "test_a_case_that_never_asked_for_documents_is_refused_and_not_changed")]),
    ("N06-a", "N06", "placeholder values and missing required fields are not proof", "py",
     [("test_origin_inputs.py", "test_a_placeholder_producer_is_not_a_producer_to_mismatch_against"),
      ("test_origin_inputs.py", "test_a_declaration_that_names_the_producer_but_no_inputs_is_not_proof")]),
    ("N06-b", "N06", "a field naming several countries is not provided", "py",
     [("test_origin_inputs.py", "test_a_certificate_for_two_countries_is_not_provided"),
      ("test_origin_inputs.py", "test_an_invoice_listing_two_countries_is_not_provided")]),
    ("N06-c", "N06", "values of the wrong type (number, object) are not a stated value", "probe",
     "probe_value_types"),
    ("N06-d", "N06", "a partly read paper (pages_read < pages) is not unconditionally provided", "probe",
     "probe_unread_pages"),
    ("N07-a", "N07", "the legacy decide route is closed for any case with a verification record", "py",
     [("test_evidence_eval_approve.py", "test_a_case_with_a_verification_record_cannot_be_released_through_decide"),
      ("test_evidence_eval_approve.py", "test_release_without_a_password_is_refused_on_a_plain_case")]),
    ("N07-b", "N07", "the policy gate tests", "py", [("test_n07_policy_gate.py", "test_")]),
    ("N08-a", "N08", "after a failed first execution the case reloads and Retry appears", "js",
     ["reloads the case when approve-then-execute ends in EXECUTION_FAILED"]),
    ("N08-b", "N08", "an interrupted execution is shown and can be resumed after the lease", "js",
     ["offers Resume, and calls executeApproval with the claimed approval, once the claim has expired",
      "says the execution is interrupted once the lease has expired"]),
    ("N08-c", "N08", "shared links are full addresses, one per document", "js",
     ["shows the per-document links after Request info",
      "shows the request-level link as a full address"]),
    ("N08-d", "N08", "a shipper with no console session can submit a document (it was a 401)", "js",
     ["lets a shipper with no console session reach the API"]),
    ("N08-e", "N08", "nothing is sent before the reviewer confirms (Release, then Cancel)", "none",
     (NO_TEST, "no frontend test found that clicks Release then Cancel and checks that approve and execute were not called")),
    ("E01-a", "E01", "changing only the answer label changes the score, not the decision", "probe",
     "probe_e01_label"),
    ("E01-b", "E01", "the output says cost and time are mocked, not measured", "probe",
     "probe_e01_basis"),
]


# ---------------------------------------------------------------------------- runners


def run_pytest(files: list[str]) -> dict[tuple[str, str], str]:
    """{(test file name, test name incl. parameters): PASSED | FAILED | ERROR}."""
    base = Path(tempfile.mkdtemp(prefix="vf_verify_")) / "pt"
    cmd = [sys.executable, "-m", "pytest", *[f"tests/{f}" for f in files], "-q",
           "-p", "no:cacheprovider", "-rA", f"--basetemp={base}"]
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=900).stdout
    results: dict[tuple[str, str], str] = {}
    for line in out.splitlines():
        m = re.match(r"^(PASSED|FAILED|ERROR) (\S+)", line)
        if m:
            node = m.group(2).replace("\\", "/")
            results[(node.split("::")[0].split("/")[-1], node.split("::")[-1])] = m.group(1)
    return results


def run_vitest() -> dict[str, str] | None:
    """{test title: passed | failed}, or None when the frontend cannot be run here."""
    front = ROOT / "frontend"
    if not (front / "node_modules").exists():
        return None
    outfile = Path(tempfile.mkdtemp(prefix="vf_verify_")) / "vitest.json"
    cmd = (f'npx vitest run src/components/review/ReviewPanel.test.tsx route.test.ts '
           f'--reporter=json --outputFile="{outfile}"')
    try:
        subprocess.run(cmd, shell=True, cwd=front, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=900)
        data = json.loads(outfile.read_text(encoding="utf-8"))
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    titles: dict[str, str] = {}
    for suite in data.get("testResults", []):
        for t in suite.get("assertionResults", []):
            titles[t.get("title", "")] = t.get("status", "")
    return titles


# ------------------------------------------------------------------------------ probes

_ENV = None


def _env() -> dict[str, str]:
    global _ENV
    if _ENV is None:
        from test_evidence_eval_approve import ENV
        _ENV = {**ENV, "PROJECT_ID": "verify-project"}
    return _ENV


def probe_unknown_publish() -> tuple[bool, str]:
    from test_evidence_execution import _fake_pubsub, _with_pubsub
    from vf_logistics import store as store_mod
    from vf_logistics import tools

    with patch.dict(os.environ, _env()):
        store_mod._store = None
        module, _ = _fake_pubsub([TimeoutError("deadline exceeded")])
        with _with_pubsub(module):
            receipt = asyncio.run(tools.publish_decision("CASE-V", {"outcome": "RELEASED_BY_HUMAN"}))
        store_mod._store = None
    status = receipt.get("status")
    return status != "failed", f"a publish that timed out is recorded as '{status}'"


def _origin_documents(**override):
    from test_evidence_eval_approve import PAPERS

    papers = {**PAPERS, **override}
    return [{"doc_type": dt, "extracted": ext} for dt, ext in papers.items()]


def probe_value_types() -> tuple[bool, str]:
    from test_origin_inputs import plywood
    from vf_logistics.verifier import check_origin_evidence

    base = check_origin_evidence(plywood(), _origin_documents())
    if base.get("status") != "provided":
        return False, f"probe baseline is '{base.get('status')}', not provided"
    bad = check_origin_evidence(plywood(), _origin_documents(
        certificate_of_origin={"producer_name": 123, "origin_country": {"name": "Vietnam"}},
    ))
    ok = "certificate_of_origin" in (bad.get("missing") or [])
    return ok, f"a certificate with a number and an object as values gives status '{bad.get('status')}'"


def probe_unread_pages() -> tuple[bool, str]:
    from test_origin_inputs import plywood
    from vf_logistics.verifier import check_origin_evidence

    docs = _origin_documents()
    base = check_origin_evidence(plywood(), docs)
    if base.get("status") != "provided":
        return False, f"probe baseline is '{base.get('status')}', not provided"
    partly_read = [{**d, "pages": 2, "pages_read": 1} for d in docs]
    got = check_origin_evidence(plywood(), partly_read)
    return got.get("status") != "provided", f"three papers read 1 page of 2 give status '{got.get('status')}'"


def _verification_eval():
    path = ROOT / "scripts" / "run_verification_eval.py"
    spec = importlib.util.spec_from_file_location("run_verification_eval", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, path


def probe_e01_label() -> tuple[bool, str]:
    module, _ = _verification_eval()
    cases = json.loads((ROOT / "data" / "verification_cases.json").read_text(encoding="utf-8"))
    spec = next((c for c in cases if c["id"] == "V-FRAUD-01"), None)
    if spec is None:
        return False, "case V-FRAUD-01 not found in data/verification_cases.json"
    flipped = dict(spec, expected_outcome=(
        "RELEASED_BY_HUMAN" if spec["expected_outcome"] != "RELEASED_BY_HUMAN" else "BLOCKED_BY_HUMAN"))
    with patch.dict(os.environ, module.ENV):
        first = module.evaluate_case(spec)
        second = module.evaluate_case(flipped)
    ok = (first["final_state"] == second["final_state"]
          and first["improper_execution"] != second["improper_execution"])
    return ok, (f"decision {first['final_state']} / {second['final_state']}; "
                f"improper_execution {first['improper_execution']} / {second['improper_execution']}")


def probe_e01_basis() -> tuple[bool, str]:
    _, path = _verification_eval()
    found = "measurement_basis" in path.read_text(encoding="utf-8")
    return found, "the summary carries measurement_basis" if found else "no measurement_basis in the summary"


# ------------------------------------------------------------------------------- report


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    no_frontend = "--no-frontend" in sys.argv

    files = sorted({f for c in CHECKS if c[3] == "py" for f, _ in c[4]})
    print(f"running {len(files)} backend test files ...", flush=True)
    py_results = run_pytest(files)
    print("running the frontend tests ...", flush=True)
    js_results = None if no_frontend else run_vitest()

    rows = []
    for cid, item, what, kind, spec in CHECKS:
        evidence = ""
        if kind == "py":
            found = [(py_results[k], k) for f, prefix in spec for k in py_results if k[0] == f and k[1].startswith(prefix)]
            missing = [prefix for f, prefix in spec if not any(k[0] == f and k[1].startswith(prefix) for k in py_results)]
            if missing:
                result, evidence = FAIL, "test not found or not run: " + ", ".join(missing)
            elif all(s == "PASSED" for s, _ in found):
                result, evidence = PASS, f"{len(found)} test(s) passed"
            else:
                bad = next(k[1] for s, k in found if s != "PASSED")
                result, evidence = FAIL, f"failing: {bad}"
        elif kind == "js":
            if js_results is None:
                result, evidence = SKIP, "frontend tests not run here"
            else:
                found = [(st, t) for frag in spec for t, st in js_results.items() if frag in t]
                missing = [frag for frag in spec if not any(frag in t for t in js_results)]
                if missing:
                    result, evidence = FAIL, "test not found: " + missing[0][:60]
                elif all(st == "passed" for st, _ in found):
                    result, evidence = PASS, f"{len(found)} test(s) passed"
                else:
                    result, evidence = FAIL, "failing: " + next(t for st, t in found if st != "passed")[:60]
        elif kind == "probe":
            try:
                ok, evidence = globals()[spec]()
                result = PASS if ok else FAIL
            except Exception as exc:  # noqa: BLE001 - a broken probe is a failed check, not a crash
                result, evidence = FAIL, f"probe error: {type(exc).__name__}: {exc}"
        else:
            result, evidence = spec
        rows.append((cid, item, what, result, evidence))

    lines = ["# Review VI check against the current repository", "",
             "| Check | Item | What the review asks | Result | Evidence |", "|---|---|---|---|---|"]
    lines += [f"| {c} | {i} | {w} | {r} | {e} |" for c, i, w, r, e in rows]

    lines += ["", "| Item | Status | Checks passed |", "|---|---|---|"]
    fixed = 0
    for item in ITEMS:
        mine = [r for r in rows if r[1] == item and r[3] in (PASS, FAIL)]
        passed = sum(1 for r in mine if r[3] == PASS)
        state = "fixed" if mine and passed == len(mine) else ("open" if passed == 0 else "partial")
        fixed += state == "fixed"
        extra = [r[0] for r in rows if r[1] == item and r[3] in (NO_TEST, OUT_OF_SCOPE, SKIP)]
        lines.append(f"| {item} | {state} | {passed}/{len(mine)}" + (f" (not counted: {', '.join(extra)})" if extra else "") + " |")

    counted = [r for r in rows if r[3] in (PASS, FAIL)]
    passed_all = sum(1 for r in counted if r[3] == PASS)
    pct = round(100 * passed_all / len(counted)) if counted else 0
    lines += ["", f"Checks passed: {passed_all} of {len(counted)} = {pct}%.",
              f"Items fully fixed: {fixed} of {len(ITEMS)}.",
              "Not counted: " + (", ".join(f"{r[0]} ({r[3]})" for r in rows if r[3] in (NO_TEST, OUT_OF_SCOPE, SKIP)) or "none") + ".",
              "A passing test means the correct behaviour is asserted and holds. It is not a production certificate."]

    text = "\n".join(lines)
    print(text)
    out = Path(os.environ.get("VF_VERIFY_OUT") or ROOT / "orchestrator" / "runs" / "verify_review_vi.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    print(f"\nwritten to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

DONE WHEN: only scripts/verify_review_vi.py was created, with exactly the content above.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if scripts/verify_review_vi.py already exists.
``````
<!-- TASK_END -->

<!-- TASK_START: VO1 -->
## Meta
- title: Runner plan parser accepts verify_only tasks (step 1 of 2)
- depends_on: []
- target_files:
  - orchestrator/automation_runner.py
  - tests/test_automation_runner_verify_plan.py
- test_commands:
  - python -m py_compile orchestrator/automation_runner.py
  - python -m pytest tests/test_automation_runner_verify_plan.py -q
- timeout_sec: 420
- max_retries: 1

## Context
Why: the Master does not run anything (skill master-planner). A measurement or full test run must be a task whose output lands in a log the Master reads. Today every non-read-only task needs a changed target file, so a pure verification task cannot exist. A task with `verify_only: true` will call no model and only run its test_commands (step 2, task VO2). This step only teaches the plan parser the new key: the field, and the two checks it relaxes. The runner does not run such a task yet, and the real plan has no such task yet.
Hard limits: change only the five lines named below; do not touch run_task, main, preflight or any other function.
Expected in the log: `3 passed` for the new test file.

## Prompt
``````text
TASK VO1. Teach orchestrator/automation_runner.py the plan key `verify_only`. Five one-line edits and one new test file.

FILES YOU MAY EDIT (only these two):
1. orchestrator/automation_runner.py, only the five places below.
2. tests/test_automation_runner_verify_plan.py, a NEW file: it does not exist yet. Create it with Write, with exactly the content given at the end.
Use the Edit tool with a ONE-LINE old_string, exactly as given (leading spaces included). Never use a multi-line old_string. Never use Write on automation_runner.py. Apply the edits in order.

EDIT 1 (a field of the Task dataclass). old_string, ONE line (4 leading spaces; occurs once):
```python
    read_only: bool = False
```
new_string, two lines:
```python
    read_only: bool = False
    verify_only: bool = False
```

EDIT 2 (read the key, in parse_plan). old_string, ONE line (8 leading spaces; occurs once):
```python
        read_only = str(meta.get("read_only", "false")).lower() == "true"
```
new_string, two lines (the first is the old line again):
```python
        read_only = str(meta.get("read_only", "false")).lower() == "true"
        verify_only = str(meta.get("verify_only", "false")).lower() == "true"
```

EDIT 3 (pass it to Task, in parse_plan). old_string, ONE line (12 leading spaces; occurs once):
```python
            read_only=read_only,
```
new_string, two lines (the first is the old line again):
```python
            read_only=read_only,
            verify_only=verify_only,
```

EDIT 4 (a verify_only task has no prompt, in _validate). old_string, ONE line (8 leading spaces; occurs once):
```python
        if not t.prompt:
```
new_string, ONE line:
```python
        if not t.prompt and not t.verify_only:
```

EDIT 5 (a verify_only task has no target files, in _validate). old_string, ONE line (8 leading spaces; occurs once):
```python
        if not t.read_only and not t.target_files:
```
new_string, ONE line:
```python
        if not t.read_only and not t.verify_only and not t.target_files:
```
Do not touch the next check in _validate (`if not t.read_only and not t.test_commands:`): a verify_only task still needs at least one command.

THE NEW FILE tests/test_automation_runner_verify_plan.py (create with Write, exactly this content):
```python
"""
A plan task with `verify_only: true` needs no Prompt and no target_files: it only runs its
test_commands. It still needs at least one command, and an ordinary task still needs a prompt.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "orchestrator"))
import automation_runner as runner  # noqa: E402


def _plan(task_id: str, meta: str) -> str:
    # The markers are joined from parts so that this file, when it is quoted inside a plan,
    # does not read as a task of that plan.
    return (
        "<!-- TASK" + f"_START: {task_id} -->\n## Meta\n{meta}\n## Context\nNothing to implement.\n"
        + "<!-- TASK" + "_END -->\n"
    )


VERIFY_PLAN = _plan("V", '- title: count the runs\n- verify_only: true\n- test_commands:\n  - python -c "print(1)"\n')
NO_COMMANDS_PLAN = _plan("V", "- title: nothing to run\n- verify_only: true\n")
NO_PROMPT_PLAN = _plan(
    "W", '- title: an ordinary task without a prompt\n- target_files:\n  - a.py\n- test_commands:\n  - python -c "print(1)"\n',
)


def test_a_verify_only_task_needs_no_prompt_and_no_target_files():
    (task,) = runner.parse_plan(VERIFY_PLAN)
    assert task.verify_only is True
    assert task.prompt == ""
    assert task.target_files == []
    assert task.test_commands == ['python -c "print(1)"']


def test_a_verify_only_task_still_needs_a_command():
    with pytest.raises(runner.PlanError):
        runner.parse_plan(NO_COMMANDS_PLAN)


def test_an_ordinary_task_still_needs_a_prompt():
    with pytest.raises(runner.PlanError):
        runner.parse_plan(NO_PROMPT_PLAN)
```

DONE WHEN: only the two files changed; automation_runner.py gained exactly the five edits (3 added lines, 2 changed lines) and nothing else; the new file has 3 tests.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if an old_string line is not found, or if tests/test_automation_runner_verify_plan.py already exists.
``````
<!-- TASK_END -->

<!-- TASK_START: VO2 -->
## Meta
- title: Runner runs verify_only tasks without a model (step 2 of 2)
- depends_on:
  - VO1
- target_files:
  - orchestrator/automation_runner.py
  - tests/test_automation_runner_verify_run.py
- test_commands:
  - python -m py_compile orchestrator/automation_runner.py
  - python -m pytest tests/test_automation_runner_verify_plan.py tests/test_automation_runner_verify_run.py -q
  - python orchestrator/automation_runner.py --dry-run
- timeout_sec: 480
- max_retries: 1

## Context
Step 2: after VO1 the parser accepts `verify_only: true`. Now the runner runs such a task: no model call, only its test_commands, once; the output goes to `orchestrator/runs/<id>/attempt_1.log` (sections TESTS and RESULT, the same layout as other tasks) and the task runs again on every invocation, even when it passed before, because it is a measurement. A failing command is one failed attempt, nothing is restored. `claude` is required only when the plan has a task that is not verify_only. A verify_only task that failed is still skipped on the next run unless --retry-failed is given; that is intended and unchanged.
Hard limits: only the four places below; do not touch run_task's body, preflight, snapshot, restore or enforce_scope.
After this task a verification task can be written in the plan (for example one running `python scripts/verify_review_vi.py`), run by the runner, and read by the Master from its log.
Expected in the log: `5 passed` for the two new test files together, and the dry run listing the plan.

## Prompt
``````text
TASK VO2. Make orchestrator/automation_runner.py run `verify_only` tasks without a model. One new function, three small edits, and one new test file.

FILES YOU MAY EDIT (only these two):
1. orchestrator/automation_runner.py, only the four places below.
2. tests/test_automation_runner_verify_run.py, a NEW file: it does not exist yet. Create it with Write, with exactly the content given at the end.
Use the Edit tool with a ONE-LINE old_string, exactly as given (leading spaces included). Never use a multi-line old_string. Never use Write on automation_runner.py. Apply the edits in order. The names Task, Options, Checkpoint, STATUS_DONE, STATUS_FAILED, run_tests, tail, utc_now, time already exist in the file: use them, define nothing else.

EDIT 1 (the new function, directly above run_task). old_string, ONE line (no leading spaces; occurs once):
```python
def run_task(task: Task, opts: Options, cp: Checkpoint) -> bool:
```
new_string is the whole function below, ending with that same line again (the last line of the block is the old line):
```python
def run_verify_task(task: Task, opts: Options, cp: Checkpoint) -> bool:
    """
    A task with no model call: its test_commands run once and their output is the result.

    Used to check or measure what already exists. A failing command is a finding to read,
    not something to retry, so there is one attempt and nothing is restored.
    """
    run_dir = opts.runs_dir / task.id
    run_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    cp.update(task.id, status="running", prompt_hash=task.body_hash, started_at=utc_now(),
              attempts=0, last_error=None, title=task.title)
    print(f"[{task.id}] verify-only: running {len(task.test_commands)} command(s) ...", flush=True)
    ok, test_log = run_tests(task.test_commands, opts.repo)
    took = time.monotonic() - started
    (run_dir / "attempt_1.log").write_text(
        f"task: {task.id}  verify-only  duration: {took:.1f}s\n\n"
        f"=== TESTS ===\n{test_log}\n\n=== RESULT ===\n{'OK' if ok else 'TESTS FAILED'}\n",
        encoding="utf-8",
    )
    error = None if ok else "TESTS FAILED:\n" + tail(test_log)
    cp.update(task.id, attempts=1, last_error=error, last_attempt_at=utc_now(),
              status=STATUS_DONE if ok else STATUS_FAILED, finished_at=utc_now(), files_changed=[],
              duration_s=round(took, 1), tests="passed" if ok else "failed")
    print(f"[{task.id}] verify-only: {'OK' if ok else 'FAILED - ' + error.splitlines()[0]}", flush=True)
    return ok


def run_task(task: Task, opts: Options, cp: Checkpoint) -> bool:
```

EDIT 2 (claude is needed only for tasks that call a model, in main). old_string, ONE line (4 leading spaces; occurs once):
```python
    if claude_bin is None:
```
new_string, ONE line:
```python
    if claude_bin is None and not all(t.verify_only for t in tasks):
```

EDIT 3 (a verify_only task runs every time, in main). old_string, ONE line (8 leading spaces; occurs once):
```python
        if state.get("status") == STATUS_DONE and state.get("prompt_hash") == task.body_hash:
```
new_string, ONE line:
```python
        if state.get("status") == STATUS_DONE and state.get("prompt_hash") == task.body_hash and not task.verify_only:
```
Do not touch the next statement (`if state.get("status") == STATUS_FAILED ... \`).

EDIT 4 (choose the function, in main). old_string, ONE line (8 leading spaces; occurs once):
```python
        if not run_task(task, opts, cp):
```
new_string, two lines:
```python
        run_one = run_verify_task if task.verify_only else run_task
        if not run_one(task, opts, cp):
```

THE NEW FILE tests/test_automation_runner_verify_run.py (create with Write, exactly this content):
```python
"""
The runner runs a `verify_only` task without a model: its test_commands run once, the output
is the logged result, and the task runs again on every invocation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "orchestrator"))
import automation_runner as runner  # noqa: E402


def _plan(command: str) -> str:
    # The markers are joined from parts so that this file, when it is quoted inside a plan,
    # does not read as a task of that plan.
    return (
        "<!-- TASK" + "_START: V -->\n## Meta\n- title: a check\n- verify_only: true\n"
        f"- test_commands:\n  - {command}\n\n## Context\nNothing to implement.\n"
        + "<!-- TASK" + "_END -->\n"
    )


COUNTING_PLAN = _plan('python -c "open(\'count.txt\', \'a\').write(\'x\')"')
FAILING_PLAN = _plan('python -c "raise SystemExit(3)"')


def _run(tmp_path: Path, plan_text: str) -> int:
    plan = tmp_path / "plan.md"
    plan.write_text(plan_text, encoding="utf-8")
    return runner.main(["--repo", str(tmp_path), "--plan", str(plan)])


def _checkpoint(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "orchestrator" / "checkpoint.json").read_text(encoding="utf-8"))


def test_the_commands_run_without_a_model_and_run_again_each_time(tmp_path):
    assert _run(tmp_path, COUNTING_PLAN) == 0
    assert (tmp_path / "count.txt").read_text(encoding="utf-8") == "x"
    assert _run(tmp_path, COUNTING_PLAN) == 0
    assert (tmp_path / "count.txt").read_text(encoding="utf-8") == "xx"
    log = (tmp_path / "orchestrator" / "runs" / "V" / "attempt_1.log").read_text(encoding="utf-8")
    assert "=== TESTS ===" in log
    assert "=== RESULT ===\nOK" in log
    state = _checkpoint(tmp_path)["tasks"]["V"]
    assert state["status"] == "done" and state["attempts"] == 1


def test_a_failing_command_is_one_failed_attempt_with_its_output_logged(tmp_path):
    assert _run(tmp_path, FAILING_PLAN) == 1
    log = (tmp_path / "orchestrator" / "runs" / "V" / "attempt_1.log").read_text(encoding="utf-8")
    assert "exit code 3" in log
    assert "=== RESULT ===\nTESTS FAILED" in log
    state = _checkpoint(tmp_path)["tasks"]["V"]
    assert state["status"] == "failed" and state["attempts"] == 1
```

DONE WHEN: only the two files changed; automation_runner.py gained the function and the three edits and nothing else; the new file has 2 tests.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if an old_string line is not found, if the Task dataclass has no verify_only field (task VO1 not applied), or if tests/test_automation_runner_verify_run.py already exists.
``````
<!-- TASK_END -->

<!-- TASK_START: V2 -->
## Meta
- title: Full check of review VI against the repository, no model, one log
- verify_only: true
- test_commands:
  - python scripts/verify_review_vi.py

## Context
A verify_only task: the runner calls no model and runs the command once. The output lands in `orchestrator/runs/V2/attempt_1.log` (section TESTS) and the script also writes `orchestrator/runs/verify_review_vi.md`. It runs the backend tests, the frontend tests (vitest) and five probes, then prints one table per check, one per item and the percentage. It edits no source file and always exits 0, so open findings are rows in the table, not a failed task. It reruns on every invocation, so it can be used again after each fix. The last table read from a log: 21 of 23 checks pass (91%), 7 of 9 items fixed; open: N01-d (a timed-out publish is recorded as failed) and N06-d (a partly read paper still counts as provided); N08-e has no test; N01-e is outside this repository.
<!-- TASK_END -->

<!-- TASK_START: N06d1 -->
## Meta
- title: A paper the reader only partly read is not provided (N06-B, verifier)
- depends_on: []
- target_files:
  - src/vf_logistics/verifier.py
  - tests/test_unread_pages.py
- test_commands:
  - python -m pytest tests/test_unread_pages.py -q
  - python -m pytest tests/test_origin_inputs.py tests/test_evidence_respond.py tests/test_evidence_eval_approve.py tests/test_evidence_request.py tests/test_exception_approval.py -q
- timeout_sec: 420
- max_retries: 1

## Context
Review VI, finding N06-B (still open): the reader transcribes only page 1 of a PDF, evidence.py already stores `pages` and `pages_read` on every received document (task C2), but check_origin_evidence ignores them, so a paper read 1 page of 2 still counts as provided. This task makes the verifier treat such a paper as unproven (it lands in `missing`, so reevaluate lists it as unresolved) and report it in a new result key `unread`. Stricter only: it never lowers the floor. A record that does not say how much was read behaves as before. What a partly read paper does say is still read for contradictions. This replaces the parked task C3 (older and longer, four files); C3 stays parked and is not to be enabled.
Hard limits: only the five edits below; pages are read from the document record, never from its `extracted` content (untrusted).
Master review (from the log): `6 passed` for the new test file; before the edits all 6 fail.

## Prompt
``````text
TASK N06d1. In src/vf_logistics/verifier.py make check_origin_evidence treat a partly read paper as unproven. Five small edits and one new test file.

FILES YOU MAY EDIT (only these two):
1. src/vf_logistics/verifier.py, only the five places below.
2. tests/test_unread_pages.py, a NEW file: it does not exist yet. Create it with Write, with exactly the content given at the end.
verifier.py uses Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given (leading spaces included). Never use a multi-line old_string. Never use Write on verifier.py. Apply the edits in order. Do not change any other line of check_origin_evidence: keep the existing required-fields check and the existing several-countries check exactly as they are.

EDIT 1 (a new helper, directly above _as_list). old_string, ONE line (no leading spaces; occurs once):
```python
def _as_list(value: Any) -> list[Any]:
```
new_string is the whole helper below; its last line is the old line again:
```python
def _read_in_part(doc: dict[str, Any]) -> bool:
    """
    True when the record says the file had more pages than the reader saw.

    `pages` and `pages_read` are written by evidence.receive_evidence from the reader's
    own counts, never from the extraction. A record without them, or with anything but
    two integers, is not read as partial.
    """
    pages, pages_read = doc.get("pages"), doc.get("pages_read")
    return (
        isinstance(pages, int) and not isinstance(pages, bool)
        and isinstance(pages_read, int) and not isinstance(pages_read, bool)
        and pages_read < pages
    )


def _as_list(value: Any) -> list[Any]:
```

EDIT 2 (a list that collects what was not fully read). old_string, ONE line (4 leading spaces; occurs once):
```python
    read_by_type: dict[str, list[dict[str, Any]]] = {}
```
new_string, two lines (the first is the old line again):
```python
    read_by_type: dict[str, list[dict[str, Any]]] = {}
    unread: list[dict[str, Any]] = []
```

EDIT 3 (the check, inside the loop over documents). old_string, ONE line (12 leading spaces; occurs once):
```python
            required = _REQUIRED_FIELDS.get(dt, ())
```
new_string is the block below; its last line is the old line again:
```python
            # N06-B: a paper the reader only partly read cannot prove what its other pages
            # say. It stays in `read_by_type` above, so what it does say is still read for
            # contradictions; it is left out of `by_type`, so it counts as unproven.
            if _read_in_part(doc):
                unread.append({"doc_type": dt, "pages": doc["pages"], "pages_read": doc["pages_read"]})
                continue
            required = _REQUIRED_FIELDS.get(dt, ())
```

EDIT 4 (the result carries the list). old_string, ONE line (8 leading spaces; occurs once):
```python
        "contradictions": contradictions,
```
new_string, two lines (the first is the old line again):
```python
        "contradictions": contradictions,
        "unread": unread,
```

EDIT 5 (the docstring names the new key). old_string, ONE line (4 leading spaces; occurs once):
```python
    Returns {"status": "missing"|"provided"|"contradicted", "present", "missing",
```
new_string, ONE line:
```python
    Returns {"status": "missing"|"provided"|"contradicted", "present", "missing", "unread",
```

THE NEW FILE tests/test_unread_pages.py (create with Write, exactly this content):
```python
"""
A paper the reader only partly read (pages_read < pages) is not provided (review VI, N06-B):
it cannot prove what its other pages say. What it does say is still read for contradictions.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from test_evidence_eval_approve import DOCS3, PAPERS  # noqa: E402
from test_origin_inputs import plywood  # noqa: E402
from vf_logistics.verifier import check_origin_evidence  # noqa: E402


def _docs(pages=None, pages_read=None, **override):
    docs = []
    for doc_type, extracted in {**PAPERS, **override}.items():
        doc = {"doc_type": doc_type, "extracted": extracted}
        if pages is not None:
            doc["pages"] = pages
        if pages_read is not None:
            doc["pages_read"] = pages_read
        docs.append(doc)
    return docs


def test_papers_read_in_part_are_unproven_and_listed():
    result = check_origin_evidence(plywood(), _docs(pages=2, pages_read=1))
    assert result["status"] == "missing"
    assert result["present"] == []
    assert sorted(u["doc_type"] for u in result["unread"]) == sorted(DOCS3)
    assert {(u["pages"], u["pages_read"]) for u in result["unread"]} == {(2, 1)}


def test_only_the_partly_read_paper_is_missing():
    docs = _docs()
    first = docs[0]["doc_type"]
    docs[0] = {**docs[0], "pages": 3, "pages_read": 1}
    result = check_origin_evidence(plywood(), docs)
    assert result["missing"] == [first]
    assert [u["doc_type"] for u in result["unread"]] == [first]


def test_a_fully_read_paper_is_unchanged():
    result = check_origin_evidence(plywood(), _docs(pages=2, pages_read=2))
    assert result["status"] == "provided"
    assert result["unread"] == []


def test_records_that_do_not_say_how_much_was_read_behave_as_before():
    for pages, pages_read in ((None, None), (2, None), (None, 1), ("2", "1"), (2.0, 1.0), (True, False)):
        result = check_origin_evidence(plywood(), _docs(pages=pages, pages_read=pages_read))
        assert result["status"] == "provided", (pages, pages_read)
        assert result["unread"] == [], (pages, pages_read)


def test_what_a_partly_read_paper_says_is_still_read_for_contradictions():
    docs = _docs(certificate_of_origin={"producer_name": "Saigon Plywood Co", "origin_country": "China"})
    docs = [
        {**d, "pages": 2, "pages_read": 1} if d["doc_type"] == "certificate_of_origin" else d
        for d in docs
    ]
    result = check_origin_evidence(plywood(), docs)
    assert result["status"] == "contradicted"
    assert [c["kind"] for c in result["contradictions"]] == ["certificate_country"]
    assert "certificate_of_origin" in result["missing"]


def test_pages_are_read_from_the_record_never_from_the_extraction():
    certificate = {**PAPERS["certificate_of_origin"], "pages": 9, "pages_read": 1}
    result = check_origin_evidence(plywood(), _docs(certificate_of_origin=certificate))
    assert result["status"] == "provided"
    assert result["unread"] == []
```

DONE WHEN: only the two files changed; verifier.py gained the helper, one list, one if-block, one result key and one changed docstring line, and nothing else; the new file has 6 tests.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if an old_string line is not found, or if tests/test_unread_pages.py already exists.
``````
<!-- TASK_END -->

<!-- TASK_START: N06d2 -->
## Meta
- title: The evaluation records which papers were not fully read (N06-B, evidence)
- depends_on:
  - N06d1
- target_files:
  - src/vf_logistics/evidence.py
  - tests/test_unread_pages_evaluation.py
- test_commands:
  - python -m pytest tests/test_unread_pages.py tests/test_unread_pages_evaluation.py -q
  - python -m pytest tests/test_origin_inputs.py tests/test_evidence_respond.py tests/test_evidence_eval_approve.py tests/test_evidence_request.py tests/test_evidence_execution.py tests/test_exception_approval.py -q
- timeout_sec: 420
- max_retries: 1

## Context
Second half of N06-B: reevaluate() copies the new `unread` list from the verifier into the evaluation record it stores, so the reviewer can see WHY a received paper is "unresolved". One line. The new test goes through receive_evidence and reevaluate with a mocked extraction that reports 1 page read of 2.
Master review (from the log): `7 passed` for the two new test files together; before the evidence.py edit the new evaluation test fails.

## Prompt
``````text
TASK N06d2. In src/vf_logistics/evidence.py, function reevaluate(), add the key `unread` to the evaluation record. One edit and one new test file.

FILES YOU MAY EDIT (only these two):
1. src/vf_logistics/evidence.py, only the one place below.
2. tests/test_unread_pages_evaluation.py, a NEW file: it does not exist yet. Create it with Write, with exactly the content given at the end.
evidence.py uses Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given (leading spaces included). Never use a multi-line old_string. Never use Write on evidence.py.

EDIT 1. old_string, ONE line (8 leading spaces; occurs once):
```python
        "contradictions": evidence_result.get("contradictions") or [],
```
new_string, two lines (the first is the old line again):
```python
        "contradictions": evidence_result.get("contradictions") or [],
        "unread": evidence_result.get("unread") or [],
```

THE NEW FILE tests/test_unread_pages_evaluation.py (create with Write, exactly this content):
```python
"""
The evaluation a reviewer reads says WHY a received paper is unresolved when the reader only
saw part of it (review VI, N06-B).
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(__file__))
from test_evidence_eval_approve import DOCS3, PAPERS, Base, tiny_pdf  # noqa: E402
from vf_logistics import evidence  # noqa: E402

REVIEWER = "reviewer@forwarder.example"


def run(coro):
    return asyncio.run(coro)


class TestTheEvaluationSaysWhatWasNotRead(Base):
    def _submit_read_in_part(self, links):
        for doc_type, extracted in PAPERS.items():
            mock = {
                "agent": "evidence_extraction", "model": "test", "result": extracted,
                "latency_ms": 10, "input_tokens": 10, "output_tokens": 10,
                "parse_error": False, "at": "2026-10-12T08:00:00Z",
                "source_pages": 2, "source_pages_read": 1,
            }
            with patch("vf_logistics.agents.document_agent.extract_evidence", new=AsyncMock(return_value=mock)), \
                    patch("vf_logistics.model_armor.screen", new=AsyncMock(return_value={"blocked": False})), \
                    patch("vf_logistics.model_armor.extract_pdf_text", return_value=("text", None)), \
                    patch("vf_logistics.document_store.archive", new=AsyncMock(return_value={"archived": True, "uri": "gs://t/d"})):
                run(evidence.receive_evidence(links[doc_type], tiny_pdf(), f"{doc_type}.pdf", "application/pdf"))

    def test_a_received_paper_read_in_part_is_unresolved_and_says_why(self):
        self.put()
        out = run(evidence.request_evidence("CASE-1", REVIEWER, documents=DOCS3))
        links = {link["doc_type"]: link["token"] for link in out["links"]}
        self._submit_read_in_part(links)
        evaluation = run(evidence.reevaluate("CASE-1"))["evaluation"]
        assert evaluation["status"] == "missing"
        assert sorted(evaluation["unresolved"]) == sorted(DOCS3)
        assert sorted(u["doc_type"] for u in evaluation["unread"]) == sorted(DOCS3)
        assert {(u["pages"], u["pages_read"]) for u in evaluation["unread"]} == {(2, 1)}
```

DONE WHEN: only the two files changed; evidence.py gained that one line and nothing else; the new file has 1 test.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if the old_string line is not found, if check_origin_evidence in src/vf_logistics/verifier.py has no "unread" key (task N06d1 not applied), or if tests/test_unread_pages_evaluation.py already exists.
``````
<!-- TASK_END -->

<!-- TASK_START: N01d1 -->
## Meta
- title: A publish that timed out is recorded as unknown, not failed (N01, tools)
- depends_on: []
- target_files:
  - src/vf_logistics/tools.py
  - tests/test_publish_dedupe.py
  - tests/test_evidence_execution.py
- test_commands:
  - python -m pytest tests/test_publish_dedupe.py tests/test_evidence_execution.py -q
  - python -m pytest tests/test_resume_after_publish.py tests/test_publish_attribute.py tests/test_executor_client.py tests/test_pure_logic.py tests/test_internal_execute.py -q
- timeout_sec: 420
- max_retries: 1

## Context
Review VI, finding N01 (still open): when `future.result(timeout=15)` times out, the broker may have accepted the message, yet the audit row says "failed", the same as "nothing was sent". This task records a timeout as status "unknown" in tools.publish_decision_direct; every other exception stays "failed". A retry still sends (the duplicate lookup in publish_decision only counts rows with status "done") and carries the same idempotency key.
DELIBERATE CHANGE OF TWO EXISTING TEST LINES (the human asked for this behaviour): two assertions pinned the old status for a timeout, `["failed", "done"]` in test_evidence_execution.py and `first["status"] == "failed"` in test_publish_dedupe.py. They become "unknown". No other existing test line changes.
Master review (from the log): both updated tests fail before the tools.py edit and pass after; the related suites pass.

## Prompt
``````text
TASK N01d1. A publish that times out is recorded as "unknown". One edit in tools.py and two one-line edits in existing tests.

FILES YOU MAY EDIT (only these three):
1. src/vf_logistics/tools.py, only the one place below, inside publish_decision_direct().
2. tests/test_publish_dedupe.py, only the one line below.
3. tests/test_evidence_execution.py, only the one line below.
All three use Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given (leading spaces included). Never use a multi-line old_string. Never use Write on an existing file. Change no other assertion or test.

EDIT 1 (tools.py). old_string, ONE line (12 leading spaces; occurs once):
```python
            status="failed",
```
new_string, the three lines below (the last is the old line with a changed value):
```python
            # A timeout means the broker may have accepted the message, which is not the same
            # as "not sent" (N01). A retry carries the same idempotency key.
            status="unknown" if isinstance(exc, TimeoutError) else "failed",
```
Do not change anything else in tools.py: not the `except Exception as exc:` line, not the error text, not _audit.

EDIT 2 (tests/test_publish_dedupe.py, the first publish in test_a_publish_that_failed_is_sent_again was a timeout). old_string, ONE line (8 leading spaces; occurs once):
```python
        assert first["status"] == "failed"
```
new_string, ONE line:
```python
        assert first["status"] == "unknown"
```

EDIT 3 (tests/test_evidence_execution.py, in test_a_real_publish_failure_then_a_retry_leaves_a_complete_record). old_string, ONE line (8 leading spaces; occurs once):
```python
        assert [r["status"] for r in self._audit_rows("publish_decision")] == ["failed", "done"]
```
new_string, ONE line:
```python
        assert [r["status"] for r in self._audit_rows("publish_decision")] == ["unknown", "done"]
```

DONE WHEN: only the three files changed; tools.py gained two comment lines and one changed line; each test file changed by exactly one line.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if an old_string line is not found.
``````
<!-- TASK_END -->

<!-- TASK_START: N01d2 -->
## Meta
- title: An execution whose send timed out is recorded as send_unknown (N01, evidence)
- depends_on:
  - N01d1
- target_files:
  - src/vf_logistics/evidence.py
  - tests/test_evidence_execution.py
  - tests/test_send_unknown.py
- test_commands:
  - python -m pytest tests/test_send_unknown.py tests/test_evidence_execution.py -q
  - python -m pytest tests/test_resume_after_publish.py tests/test_publish_attribute.py tests/test_executor_client.py tests/test_pure_logic.py tests/test_internal_execute.py -q
- timeout_sec: 480
- max_retries: 1

## Context
Second half of the N01 fix: execute_approval() reads the publish receipt; when its status is "unknown" the execution is recorded as `send_unknown` with a reason, instead of `send_failed`. The case still goes to EXECUTION_FAILED and the approval to VALID, so a retry is possible; the retry reuses the same idempotency key (message body and attribute), which is how the receiving side can drop a repeat. Any other publish error stays `send_failed`. The console shows an unknown status string as "Execution send_unknown" with the reason; no frontend change is needed.
DELIBERATE CHANGE OF ONE EXISTING TEST LINE: `["send_failed", "sent"]` in test_evidence_execution.py becomes `["send_unknown", "sent"]`, because that test's first publish is a timeout.
Not covered by this fix: deduplication on the receiving system, which is outside this repository.
Master review (from the log): `5 passed` for tests/test_send_unknown.py (3 from N01d1's behaviour, 2 new); the updated existing line passes only after the evidence.py edit.

## Prompt
``````text
TASK N01d2. execute_approval() records a timed-out send as `send_unknown`. One edit in evidence.py, one one-line edit in an existing test, one new test file.

FILES YOU MAY EDIT (only these three):
1. src/vf_logistics/evidence.py, only the one place below, inside execute_approval().
2. tests/test_evidence_execution.py, only the one line below.
3. tests/test_send_unknown.py, a NEW file: it does not exist yet. Create it with Write, with exactly the content given at the end.
The first two files use Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given (leading spaces included). Never use a multi-line old_string. Never use Write on an existing file.

EDIT 1 (evidence.py, in the branch `if pub_failed:` of the confirm phase). old_string, ONE line (8 leading spaces; occurs once):
```python
        exe2["status"] = "send_failed"
```
new_string is the block below; it replaces that one line:
```python
        # A publish that timed out may have been accepted. Say so, so the retry is read as
        # "result unknown, same key" and not as "nothing was sent" (N01).
        unknown = isinstance(pub_receipt, dict) and pub_receipt.get("status") == "unknown"
        exe2["status"] = "send_unknown" if unknown else "send_failed"
        if unknown:
            exe2["reason"] = (
                "The publish timed out and may have been accepted; "
                "a retry reuses the same idempotency key."
            )
```
Do not change the lines around it (`exe2["message_id"] = None`, the approval revert, the state change).

EDIT 2 (tests/test_evidence_execution.py, in test_a_real_publish_failure_then_a_retry_leaves_a_complete_record). old_string, ONE line (8 leading spaces; occurs once):
```python
        assert [e["status"] for e in record["executions"]] == ["send_failed", "sent"]
```
new_string, ONE line:
```python
        assert [e["status"] for e in record["executions"]] == ["send_unknown", "sent"]
```

THE NEW FILE tests/test_send_unknown.py (create with Write, exactly this content):
```python
"""
A publish that timed out is "unknown", not "failed" (review VI, N01): the broker may have
accepted the message, so the retry is read as "result unknown, same key". Any other send
error stays a failed send.
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
from test_evidence_eval_approve import Base  # noqa: E402
from test_evidence_execution import _fake_pubsub, _with_pubsub  # noqa: E402
from vf_logistics import evidence, tools  # noqa: E402

REVIEWER = "reviewer@forwarder.example"
KEY = "exec-apr-9"


def run(coro):
    return asyncio.run(coro)


class TestAPublishThatTimedOut(Base):
    def _publish(self, pubsub):
        decision = {"outcome": "RELEASED_BY_HUMAN", "idempotency_key": KEY}
        with patch.dict(os.environ, {"PROJECT_ID": "test-project"}), _with_pubsub(pubsub):
            return run(tools.publish_decision("CASE-1", decision))

    def test_a_timeout_is_recorded_as_unknown_and_keeps_the_key(self):
        pubsub, _ = _fake_pubsub([TimeoutError("deadline exceeded")])
        receipt = self._publish(pubsub)
        assert receipt["status"] == "unknown"
        assert receipt["detail"]["idempotency_key"] == KEY
        assert "TimeoutError" in receipt["detail"]["error"]

    def test_any_other_error_is_still_a_failed_publish(self):
        pubsub, _ = _fake_pubsub([ConnectionError("unreachable")])
        assert self._publish(pubsub)["status"] == "failed"

    def test_an_unknown_publish_is_not_taken_as_an_earlier_send(self):
        first_pubsub, _ = _fake_pubsub([TimeoutError("deadline exceeded")])
        assert self._publish(first_pubsub)["status"] == "unknown"
        second_pubsub, published = _fake_pubsub(["msg-2"])
        second = self._publish(second_pubsub)
        assert second["status"] == "done"
        assert second["detail"]["message_id"] == "msg-2"
        assert len(published) == 1


class TestAnExecutionWhoseSendTimedOut(Base):
    def _approved(self):
        self.put()
        self.request_and_submit()
        run(evidence.reevaluate("CASE-1"))
        return run(evidence.approve(
            "CASE-1", "release", REVIEWER, note="Reviewed", actor_auth="password",
        ))["approval"]["approval_id"]

    def test_a_timed_out_send_is_unknown_and_the_retry_sends_with_the_same_key(self):
        approval_id = self._approved()
        pubsub, published = _fake_pubsub([TimeoutError("deadline exceeded"), "msg-ok"])
        with patch.dict(os.environ, {"PROJECT_ID": "test-project"}), _with_pubsub(pubsub):
            first = run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
            after_first = self.stored()
            second = run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        assert first["state"] == "EXECUTION_FAILED"
        executions = after_first["verification"]["executions"]
        assert [e["status"] for e in executions] == ["send_unknown"]
        assert "may have been accepted" in executions[0]["reason"]
        assert after_first["verification"]["approvals"][0]["status"] == "VALID"
        assert second["state"] == "RELEASED_BY_HUMAN" and second["message_id"] == "msg-ok"
        assert [p["body"]["idempotency_key"] for p in published] == [f"exec-{approval_id}"] * 2
        assert [e["status"] for e in self.stored()["verification"]["executions"]] == ["send_unknown", "sent"]

    def test_any_other_send_error_stays_a_failed_send(self):
        approval_id = self._approved()
        pubsub, _ = _fake_pubsub([ConnectionError("unreachable")])
        with patch.dict(os.environ, {"PROJECT_ID": "test-project"}), _with_pubsub(pubsub):
            result = run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        assert result["state"] == "EXECUTION_FAILED"
        assert [e["status"] for e in self.stored()["verification"]["executions"]] == ["send_failed"]
```

DONE WHEN: only the three files changed; evidence.py gained the block and nothing else; test_evidence_execution.py changed by exactly one line; the new file has 5 tests.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if an old_string line is not found, if tools.py does not contain `status="unknown" if isinstance(exc, TimeoutError)` (task N01d1 not applied), or if tests/test_send_unknown.py already exists.
``````
<!-- TASK_END -->

<!-- TASK_START: N08e -->
## Meta
- title: Test that Release then Cancel sends nothing (N08, frontend)
- depends_on: []
- target_files:
  - frontend/src/components/review/ReviewPanel.test.tsx
- test_commands:
  - [frontend] npx vitest run src/components/review/ReviewPanel.test.tsx
  - [frontend] npx tsc --noEmit
- timeout_sec: 420
- max_retries: 1

## Context
Review VI, N08: "pressing Release then Cancel calls neither approve nor execute" was verified by the reviewer's own test; the repository has none, so the verification script lists it as NO TEST (check N08-e). The behaviour already exists (the confirmation dialog sends nothing before Confirm); this task only adds the test. No source file changes.
Master review (from the log): the vitest run shows one more passing test in ReviewPanel.test.tsx than before; tsc passes.

## Prompt
``````text
TASK N08e. Add ONE test to frontend/src/components/review/ReviewPanel.test.tsx. Nothing else.

FILE YOU MAY EDIT (only this one): frontend/src/components/review/ReviewPanel.test.tsx. The file may use Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given (leading spaces included). Never use a multi-line old_string. Never use Write on this file. Do not add imports and do not change any mock: renderPanel, evaluated, fireEvent, screen, waitFor, approveCase and executeApproval already exist in the file.

WHERE: inside the describe block that holds the test "leaves a clean release as it was", directly before the test "still needs a note to block, as before". old_string, ONE line (2 leading spaces; occurs once):
```tsx
  it("still needs a note to block, as before", async () => {
```
new_string is the block below: the new test, a blank line, and then that same line again:
```tsx
  it("sends nothing when the reviewer cancels the confirmation (Release, then Cancel)", async () => {
    renderPanel(evaluated("HELD_FOR_REVIEW", { status: "provided", risk_floor: 45 }));
    fireEvent.click(screen.getByRole("button", { name: "Release" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull());
    expect(approveCase).not.toHaveBeenCalled();
    expect(executeApproval).not.toHaveBeenCalled();
  });

  it("still needs a note to block, as before", async () => {
```

DONE WHEN: only this file changed, by the added test and nothing else; every existing test is untouched.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if the old_string line is not found.
``````
<!-- TASK_END -->

<!-- PARKED_TASK_START: N03d1 -->
## Meta
- title: A request-level link is refused when several documents were requested (N03)
- depends_on: []
- target_files:
  - src/vf_logistics/evidence.py
  - tests/test_untyped_link.py
- test_commands:
  - python -m pytest tests/test_untyped_link.py -q
- timeout_sec: 420
- max_retries: 1

## Context
Review VI, N03 (what is left): requests and re-issues now return one typed link per document, but the request-level link (`token`/`path`, no document type) is still honoured in receive_evidence, and with several documents requested it files the upload under the first one still missing, whatever the paper is. Fix: that link is refused (400, with a message that names the next step) when more than one document was requested; with one document requested it keeps working.
KNOWN FALLOUT: existing tests that upload through the request-level link of a multi-document request will now fail. This task deliberately runs only its own new test file; the existing tests are measured next by the verify_only task V3, whose log lists every one that fails, and they are migrated in later tasks. Do not touch them here.
Master review (from the log): `3 passed` for tests/test_untyped_link.py; before the edit the first test fails.

## Prompt
``````text
TASK N03d1. In src/vf_logistics/evidence.py, function receive_evidence(), refuse a request-level link when several documents were requested. One edit and one new test file.

FILES YOU MAY EDIT (only these two):
1. src/vf_logistics/evidence.py, only the one place below.
2. tests/test_untyped_link.py, a NEW file: it does not exist yet. Create it with Write, with exactly the content given at the end.
evidence.py uses Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given (leading spaces included). Never use a multi-line old_string. Never use Write on evidence.py. Do not edit any existing test.

EDIT 1. old_string, ONE line (8 leading spaces; occurs once):
```python
        # A request-level link (no document in the token): the first one not yet in.
```
new_string is the block below. It REPLACES that one comment line; the two lines that follow it in the file (`doc_type = still_missing[0] if still_missing else (` and its continuation) stay exactly as they are:
```python
        # A request-level link (no document in the token) cannot say which paper an upload is.
        # With one document requested there is nothing to confuse; with several, the upload
        # would be filed under whichever is still missing, whatever it actually is (N03).
        if len(requested_docs) > 1:
            raise EvidenceError(
                "This link does not say which document it is for. Ask for a link for each document.",
                400,
            )
```

THE NEW FILE tests/test_untyped_link.py (create with Write, exactly this content):
```python
"""
A request-level link carries no document type. With several documents requested it cannot say
which paper an upload is, so it is refused instead of filing the upload under whichever is still
missing (review VI, N03). With one document requested there is nothing to confuse.
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_evidence_eval_approve import DOCS3, PAPERS, Base, tiny_pdf  # noqa: E402
from vf_logistics import evidence  # noqa: E402

REVIEWER = "reviewer@forwarder.example"


def run(coro):
    return asyncio.run(coro)


def _receive(token, extracted):
    mock = {
        "agent": "evidence_extraction", "model": "test", "result": extracted,
        "latency_ms": 10, "input_tokens": 10, "output_tokens": 10,
        "parse_error": False, "at": "2026-10-12T08:00:00Z",
    }
    with patch("vf_logistics.agents.document_agent.extract_evidence", new=AsyncMock(return_value=mock)), \
            patch("vf_logistics.model_armor.screen", new=AsyncMock(return_value={"blocked": False})), \
            patch("vf_logistics.model_armor.extract_pdf_text", return_value=("text", None)), \
            patch("vf_logistics.document_store.archive", new=AsyncMock(return_value={"archived": True, "uri": "gs://t/d"})):
        return run(evidence.receive_evidence(token, tiny_pdf(), "doc.pdf", "application/pdf"))


class TestARequestLevelLink(Base):
    def test_with_several_documents_requested_it_is_refused(self):
        self.put()
        out = run(evidence.request_evidence("CASE-1", REVIEWER, documents=DOCS3))
        with pytest.raises(evidence.EvidenceError) as raised:
            _receive(out["token"], PAPERS["input_purchase_invoices"])
        assert raised.value.status == 400
        assert "which document" in raised.value.message
        assert self.stored()["verification"]["documents"] == []

    def test_a_typed_link_still_files_the_upload_under_its_own_type(self):
        self.put()
        out = run(evidence.request_evidence("CASE-1", REVIEWER, documents=DOCS3))
        links = {link["doc_type"]: link["token"] for link in out["links"]}
        _receive(links["input_purchase_invoices"], PAPERS["input_purchase_invoices"])
        stored = self.stored()["verification"]["documents"]
        assert [d["doc_type"] for d in stored] == ["input_purchase_invoices"]

    def test_with_one_document_requested_the_request_level_link_still_works(self):
        self.put()
        out = run(evidence.request_evidence("CASE-1", REVIEWER, documents=["certificate_of_origin"]))
        _receive(out["token"], PAPERS["certificate_of_origin"])
        stored = self.stored()["verification"]["documents"]
        assert [d["doc_type"] for d in stored] == ["certificate_of_origin"]
```

DONE WHEN: only the two files changed; evidence.py gained the block in place of one comment line and nothing else; the new file has 3 tests.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if the old_string line is not found, or if tests/test_untyped_link.py already exists.
``````
<!-- PARKED_TASK_END -->

<!-- TASK_START: N03d1t -->
## Meta
- title: Tests first: a request-level link is refused when several documents were requested (N03)
- depends_on: []
- target_files:
  - tests/test_untyped_link.py
- test_commands:
  - python -c "import subprocess,sys; r=subprocess.call('python -m pytest tests/test_untyped_link.py -q --basetemp=orchestrator/runs/N03d1t/pytest-tmp', shell=True); print('pytest exit', r); sys.exit(0 if r == 1 else 1)"
- timeout_sec: 420
- max_retries: 1

## Context
Review VI, N03 (what is left): requests and re-issues return one typed link per document, but the request-level link (`token`/`path`, no document type) is still honoured by receive_evidence and, with several documents requested, files the upload under the first one still missing, whatever the paper is. Fix in two tasks (tests first): this one adds the tests, which must FAIL now (the log shows `pytest exit 1`: the refusal test fails, the other two pass); N03d1c makes them pass. The earlier combined task N03d1 is parked: it did not give a red proof.
Expected in the log: `pytest exit 1`, `1 failed, 2 passed`.

## Prompt
``````text
TASK N03d1t. Create ONE new test file. Nothing else.

FILE YOU MAY EDIT (only this one): tests/test_untyped_link.py, a NEW file: it does not exist yet. Create it with Write, with exactly the content below, character for character. Do not edit any other file.

```python
"""
A request-level link carries no document type. With several documents requested it cannot say
which paper an upload is, so it is refused instead of filing the upload under whichever is still
missing (review VI, N03). With one document requested there is nothing to confuse.
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_evidence_eval_approve import DOCS3, PAPERS, Base, tiny_pdf  # noqa: E402
from vf_logistics import evidence  # noqa: E402

REVIEWER = "reviewer@forwarder.example"


def run(coro):
    return asyncio.run(coro)


def _receive(token, extracted):
    mock = {
        "agent": "evidence_extraction", "model": "test", "result": extracted,
        "latency_ms": 10, "input_tokens": 10, "output_tokens": 10,
        "parse_error": False, "at": "2026-10-12T08:00:00Z",
    }
    with patch("vf_logistics.agents.document_agent.extract_evidence", new=AsyncMock(return_value=mock)), \
            patch("vf_logistics.model_armor.screen", new=AsyncMock(return_value={"blocked": False})), \
            patch("vf_logistics.model_armor.extract_pdf_text", return_value=("text", None)), \
            patch("vf_logistics.document_store.archive", new=AsyncMock(return_value={"archived": True, "uri": "gs://t/d"})):
        return run(evidence.receive_evidence(token, tiny_pdf(), "doc.pdf", "application/pdf"))


class TestARequestLevelLink(Base):
    def test_with_several_documents_requested_it_is_refused(self):
        self.put()
        out = run(evidence.request_evidence("CASE-1", REVIEWER, documents=DOCS3))
        with pytest.raises(evidence.EvidenceError) as raised:
            _receive(out["token"], PAPERS["input_purchase_invoices"])
        assert raised.value.status == 400
        assert "which document" in raised.value.message
        assert self.stored()["verification"]["documents"] == []

    def test_a_typed_link_still_files_the_upload_under_its_own_type(self):
        self.put()
        out = run(evidence.request_evidence("CASE-1", REVIEWER, documents=DOCS3))
        links = {link["doc_type"]: link["token"] for link in out["links"]}
        _receive(links["input_purchase_invoices"], PAPERS["input_purchase_invoices"])
        stored = self.stored()["verification"]["documents"]
        assert [d["doc_type"] for d in stored] == ["input_purchase_invoices"]

    def test_with_one_document_requested_the_request_level_link_still_works(self):
        self.put()
        out = run(evidence.request_evidence("CASE-1", REVIEWER, documents=["certificate_of_origin"]))
        _receive(out["token"], PAPERS["certificate_of_origin"])
        stored = self.stored()["verification"]["documents"]
        assert [d["doc_type"] for d in stored] == ["certificate_of_origin"]
```

DONE WHEN: only tests/test_untyped_link.py was created, with exactly the content above (3 tests).
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if tests/test_untyped_link.py already exists.
``````
<!-- TASK_END -->

<!-- TASK_START: N03d1c -->
## Meta
- title: Code: a request-level link is refused when several documents were requested (N03)
- depends_on:
  - N03d1t
- target_files:
  - src/vf_logistics/evidence.py
- test_commands:
  - python -m pytest tests/test_untyped_link.py -q --basetemp=orchestrator/runs/N03d1c/pytest-tmp
- timeout_sec: 420
- max_retries: 1

## Context
Second half of N03d1t. receive_evidence() refuses a request-level link (400, message names the next step) when more than one document was requested; with one document requested it keeps working. KNOWN FALLOUT: existing tests that upload through the request-level link of a multi-document request will now fail. This task runs only its own tests; the existing tests are measured by the verify_only task V3 and migrated afterwards. Do not touch them here.
Expected in the log: `3 passed`.

## Prompt
``````text
TASK N03d1c. In src/vf_logistics/evidence.py, function receive_evidence(), refuse a request-level link when several documents were requested. One edit.

FILE YOU MAY EDIT (only this one): src/vf_logistics/evidence.py, only the one place below. The file uses Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given (leading spaces included). Never use a multi-line old_string. Never use Write on evidence.py. Do not edit any test.

EDIT 1. old_string, ONE line (8 leading spaces; occurs once):
```python
        # A request-level link (no document in the token): the first one not yet in.
```
new_string is the block below. It REPLACES that one comment line; the two lines that follow it in the file (`doc_type = still_missing[0] if still_missing else (` and its continuation) stay exactly as they are:
```python
        # A request-level link (no document in the token) cannot say which paper an upload is.
        # With one document requested there is nothing to confuse; with several, the upload
        # would be filed under whichever is still missing, whatever it actually is (N03).
        if len(requested_docs) > 1:
            raise EvidenceError(
                "This link does not say which document it is for. Ask for a link for each document.",
                400,
            )
```

DONE WHEN: only evidence.py changed, by that block in place of one comment line and nothing else.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if the old_string line is not found, or if tests/test_untyped_link.py does not exist (task N03d1t not applied).
``````
<!-- TASK_END -->

<!-- TASK_START: N03m1 -->
## Meta
- title: Test helper request_and_token uses the typed link of the first document (N03 migration, round 1)
- depends_on:
  - N03d1c
- target_files:
  - tests/test_evidence_respond.py
- test_commands:
  - python -c "import ast; ast.parse(open('tests/test_evidence_respond.py', encoding='utf-8').read()); print('syntax ok')"
- timeout_sec: 300
- max_retries: 1

## Context
N03d1c refuses the request-level link when several documents were requested, so the helper `request_and_token` (a request for the default documents, then `out["token"]`) breaks 9 tests of this file. The human approved migrating the helper: it returns the typed link of the first requested document instead. That is the same document the request-level link used to pick (the first one still missing), so what the tests upload is unchanged. Only the helper changes; no test body, no assertion. The command only checks the syntax: the effect is measured by the verify_only task V3 (a failing test there is a finding, not a failure of this task).

## Prompt
``````text
TASK N03m1. Change ONE line of the helper request_and_token in tests/test_evidence_respond.py. Nothing else.

FILE YOU MAY EDIT (only this one): tests/test_evidence_respond.py. It may use Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given (leading spaces included). Never use a multi-line old_string. Never use Write on this file. Do not edit any test or assertion.

EDIT 1. old_string, ONE line (8 leading spaces; occurs once, at line 89):
```python
        return out["request"]["request_id"], out["token"]
```
new_string, ONE line:
```python
        return out["request"]["request_id"], out["links"][0]["token"]
```

DONE WHEN: only this file changed, by that one line.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if the old_string line is not found.
``````
<!-- TASK_END -->

<!-- TASK_START: N03m2 -->
## Meta
- title: Test helper request_and_submit uses the typed link of the first document (N03 migration, round 1)
- depends_on:
  - N03d1c
- target_files:
  - tests/test_evidence_eval_approve.py
- test_commands:
  - python -c "import ast; ast.parse(open('tests/test_evidence_eval_approve.py', encoding='utf-8').read()); print('syntax ok')"
- timeout_sec: 300
- max_retries: 1

## Context
Same migration for the shared helper `Base.request_and_submit` in test_evidence_eval_approve.py (imported by other test files): it takes `out["token"]`, which N03d1c refuses when several documents are requested (it broke test_a_request_with_documents_still_missing_stays_open_after_evaluation). It takes the typed link of the first requested document instead; with a single document requested that is the same document as before. One line; the effect is measured by V3 and V4.

## Prompt
``````text
TASK N03m2. Change ONE line of the helper request_and_submit in tests/test_evidence_eval_approve.py. Nothing else.

FILE YOU MAY EDIT (only this one): tests/test_evidence_eval_approve.py. It may use Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given (leading spaces included). Never use a multi-line old_string. Never use Write on this file. Do not edit any test or assertion.

EDIT 1. old_string, ONE line (8 leading spaces; occurs once, at line 72):
```python
        token = out["token"]
```
new_string, ONE line:
```python
        token = out["links"][0]["token"]
```

DONE WHEN: only this file changed, by that one line.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if the old_string line is not found.
``````
<!-- TASK_END -->

<!-- TASK_START: N03m3 -->
## Meta
- title: Tenant upload test uses the typed link of the first document (N03 migration, round 2)
- depends_on:
  - N03m1
- target_files:
  - tests/test_evidence_respond.py
- test_commands:
  - python -c "import ast; ast.parse(open('tests/test_evidence_respond.py', encoding='utf-8').read()); print('syntax ok')"
- timeout_sec: 300
- max_retries: 1

## Context
Round 2 of the N03 migration. The full-suite log (runs/V4/attempt_1.log) shows one test still failing because of N03d1c: test_the_upload_lands_under_the_tenant_the_link_was_minted_for builds its own request without the helper and uploads through the request-level `["token"]` of a multi-document request. It takes the typed link of the first document instead (the same document the request-level link used to pick). One line; the effect is measured by V4.

## Prompt
``````text
TASK N03m3. Change ONE line in tests/test_evidence_respond.py, inside test_the_upload_lands_under_the_tenant_the_link_was_minted_for. Nothing else.

FILE YOU MAY EDIT (only this one): tests/test_evidence_respond.py. It may use Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given (leading spaces included). Never use a multi-line old_string. Never use Write on this file. Do not edit any other test or assertion.

EDIT 1. old_string, ONE line (12 leading spaces; occurs once, at line 413):
```python
            token = run(evidence.request_evidence("CASE-1", REVIEWER, tenant_id=self.TENANT))["token"]
```
new_string, ONE line:
```python
            token = run(evidence.request_evidence("CASE-1", REVIEWER, tenant_id=self.TENANT))["links"][0]["token"]
```

DONE WHEN: only this file changed, by that one line.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if the old_string line is not found.
``````
<!-- TASK_END -->

<!-- TASK_START: V3 -->
## Meta
- title: Measure which existing tests the request-level link change breaks
- verify_only: true
- test_commands:
  - python -m pytest tests/test_evidence_request.py tests/test_evidence_respond.py tests/test_evidence_eval_approve.py tests/test_evidence_execution.py tests/test_evidence_reevaluable_mirror.py tests/test_n07_policy_gate.py tests/test_origin_inputs.py tests/test_exception_approval.py tests/test_exception_route.py tests/test_rbac.py tests/test_untyped_link.py tests/test_unread_pages_evaluation.py tests/test_send_unknown.py -q -rf --basetemp=orchestrator/runs/V3/pytest-tmp

## Context
A verify_only task: no model, one command, the output in `orchestrator/runs/V3/attempt_1.log` (section TESTS, with a `FAILED` line for every failing test because of -rf). Run it after N03d1. A failing command is a finding here, not a defect of the task: the Master reads the list and plans the migration of those tests. It reruns on every invocation.
<!-- TASK_END -->

<!-- TASK_START: V4 -->
## Meta
- title: Full backend suite at the current working tree
- verify_only: true
- test_commands:
  - python -m pytest tests/ -q -rf --basetemp=%CD%\orchestrator\runs\V4\pytest-tmp
- timeout_sec: 900

## Context
A verify_only task: no model, the whole backend suite, the output in `orchestrator/runs/V4/attempt_1.log` (a `FAILED` line per failing test). Baseline in CLAUDE.md section 7 was 1486 passed and 16 skipped at commit 85685a2; the suite has grown since, so compare failures, not totals. A failing command is a finding, not a defect of the task.
<!-- TASK_END -->

<!-- TASK_START: V5 -->
## Meta
- title: Operating curve test with a basetemp outside the repository
- verify_only: true
- test_commands:
  - python -m pytest tests/test_operating_curve.py -q -rf --basetemp=%TEMP%\vf_curve_tmp

## Context
V4 had one failure, tests/test_operating_curve.py::test_the_script_runs_end_to_end. scripts/operating_curve.py prints `wrote <path>` relative to the repository when the output file is inside it (lines 169-173), and the test expects the absolute path; pytest's --basetemp inside the repository (the test-gate convention) puts it there. This task runs the same test with a basetemp outside the repository, to show the failure is that artefact and not a regression. A failing command is a finding.
<!-- TASK_END -->

<!-- TASK_START: VGIT -->
## Meta
- title: Git state before the commit
- verify_only: true
- test_commands:
  - git status --porcelain
  - git diff --stat
  - git log --oneline -3

## Context
A verify_only task: read-only git commands, the output in `orchestrator/runs/VGIT/attempt_1.log`. It gives the exact list of changed and untracked files for the human's commit.
<!-- TASK_END -->

<!-- TASK_START: VFULL -->
## Meta
- title: Full verification at the current working tree (CLAUDE.md section 7)
- verify_only: true
- test_commands:
  - python -m pytest tests/ -q -rf --basetemp=%TEMP%\vf_full_tmp
  - python -c "import subprocess,sys,re; v=str(sys.version_info[0])+'.'+str(sys.version_info[1]); r=subprocess.run('python -m mypy src/vf_logistics/ --ignore-missing-imports --python-version '+v, shell=True, capture_output=True, text=True); o=r.stdout; m=re.search(r'Found (\d+) error', o); n=int(m.group(1)) if m else (0 if 'Success' in o else 9999); stopped=r.returncode>1 or 'prevented further checking' in o; print('mypy exit', r.returncode, 'errors', n, 'stopped early', stopped); sys.exit(1 if stopped or n>123 else 0)"
  - python -m mypy src/vf_logistics/verifier.py src/vf_logistics/observability.py src/vf_logistics/evaluation.py --ignore-missing-imports --follow-imports=silent
  - python -m ruff check src/ tests/ scripts/ --select E,F,W --ignore E501,E402,W291,W293
  - [frontend] npx tsc --noEmit
  - [frontend] npm run lint
  - [frontend] npm test
- timeout_sec: 900

## Context
The deploy gate of CLAUDE.md section 7, as one verify_only task: backend suite, mypy ratchet (CI ceiling 123) and the strict-clean modules, ruff, then the frontend (tsc, lint, vitest). Commands stop at the first failure, so the log names the first thing to fix. The pytest basetemp is outside the repository on purpose: inside it, tests/test_operating_curve.py fails because the script prints a relative path.
<!-- TASK_END -->

<!-- TASK_START: N03e -->
## Meta
- title: The verification eval script uploads through the typed link of each document (N03 regression)
- depends_on:
  - N03d1c
- target_files:
  - scripts/run_verification_eval.py
- test_commands:
  - python -c "import ast; ast.parse(open('scripts/run_verification_eval.py', encoding='utf-8').read()); print('syntax ok')"
- timeout_sec: 300
- max_retries: 1

## Context
Found by V2 (runs/V2/attempt_1.log, check E01-a): after N03d1c, scripts/run_verification_eval.py uploads every document of a multi-document request through the request-level link `out["token"]`, which is now refused, and evaluate_case swallows the error and reports "ERROR" for the case. No test covers the script; the red proof is the V2 log (E01-a FAIL, decision ERROR / ERROR) and the green proof will be the next V2 log. The script uses `doc_types` (the keys of the evidence) as the requested documents, so `out["links"]` has one typed link per document it uploads.

## Prompt
``````text
TASK N03e. Two small edits in scripts/run_verification_eval.py. Nothing else.

FILE YOU MAY EDIT (only this one): scripts/run_verification_eval.py. It may use Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given. Never use a multi-line old_string. Never use Write on this file.

EDIT 1 (collect the typed links right after the request). old_string, ONE line (12 leading spaces; occurs once):
```python
            out = run(evidence.request_evidence(case_id, REVIEWER, documents=doc_types))
```
new_string, two lines (the first is the old line again):
```python
            out = run(evidence.request_evidence(case_id, REVIEWER, documents=doc_types))
            links = {link["doc_type"]: link["token"] for link in out["links"]}
```

EDIT 2 (upload each document through its own link). old_string, ONE line WITHOUT its leading spaces (occurs once):
```python
run(evidence.receive_evidence(out["token"], tiny_pdf(), f"{dt}.pdf", "application/pdf"))
```
new_string, ONE line (also without leading spaces; the spaces in front of the old text stay as they are):
```python
run(evidence.receive_evidence(links[dt], tiny_pdf(), f"{dt}.pdf", "application/pdf"))
```

DONE WHEN: only this file changed, by one added line and one changed line.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if an old_string is not found.
``````
<!-- TASK_END -->

<!-- TASK_START: N08f -->
## Meta
- title: The review VI check N08-e looks for the Release-then-Cancel test
- depends_on:
  - N08e
- target_files:
  - scripts/verify_review_vi.py
- test_commands:
  - python -c "import ast; ast.parse(open('scripts/verify_review_vi.py', encoding='utf-8').read()); print('syntax ok')"
- timeout_sec: 300
- max_retries: 1

## Context
N08e added the frontend test "sends nothing when the reviewer cancels the confirmation (Release, then Cancel)", but check N08-e of scripts/verify_review_vi.py was written as a fixed "NO TEST" row. It becomes a normal frontend check that looks for that test title. The next V2 log shows the row as PASS or FAIL.

## Prompt
``````text
TASK N08f. Two one-line edits in scripts/verify_review_vi.py (the N08-e entry of CHECKS). Nothing else.

FILE YOU MAY EDIT (only this one): scripts/verify_review_vi.py. Use the Edit tool with a ONE-LINE old_string, exactly as given (leading spaces included). Never use a multi-line old_string. Never use Write on this file.

EDIT 1. old_string, ONE line (4 leading spaces; occurs once):
```python
    ("N08-e", "N08", "nothing is sent before the reviewer confirms (Release, then Cancel)", "none",
```
new_string, ONE line:
```python
    ("N08-e", "N08", "nothing is sent before the reviewer confirms (Release, then Cancel)", "js",
```

EDIT 2. old_string, ONE line (5 leading spaces; occurs once):
```python
     (NO_TEST, "no frontend test found that clicks Release then Cancel and checks that approve and execute were not called")),
```
new_string, ONE line:
```python
     ["sends nothing when the reviewer cancels the confirmation"]),
```

DONE WHEN: only this file changed, by those two lines.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if an old_string line is not found.
``````
<!-- TASK_END -->

<!-- TASK_START: VMERGE -->
## Meta
- title: Where the branches stand (local refs only, no fetch)
- verify_only: true
- test_commands:
  - git status -sb
  - git branch -a -vv
  - git log --oneline --decorate -8 --all
  - git log --oneline -5

## Context
A verify_only task with read-only git commands, the output in `orchestrator/runs/VMERGE/attempt_1.log`. It answers "was the work merged into main/master?" from the LOCAL refs only: it does not fetch, so a merge made on GitHub after the last fetch is not visible here.
<!-- TASK_END -->

<!-- TASK_START: VMERGE2 -->
## Meta
- title: Was gemma-backlog merged into master (after a fetch)
- verify_only: true
- test_commands:
  - git fetch origin
  - git status -sb
  - git branch -r --contains HEAD
  - git merge-base --is-ancestor HEAD origin/master && echo MERGED_INTO_ORIGIN_MASTER || echo NOT_MERGED_INTO_ORIGIN_MASTER
  - git log --oneline --decorate -6 origin/master
  - git ls-remote --heads origin

## Context
A verify_only task for the question "was it merged?". `git fetch origin` only updates the remote-tracking refs (no change to the working tree, the branch or any file); the other commands are read-only. Output in `orchestrator/runs/VMERGE2/attempt_1.log`. A squash or rebase merge would not make HEAD an ancestor of origin/master, so the log also lists the newest commits of origin/master and the remote heads.
<!-- TASK_END -->

<!-- TASK_START: VPR -->
## Meta
- title: Pull request state of gemma-backlog (read-only, GitHub CLI)
- verify_only: true
- test_commands:
  - gh pr list --repo hoachauphuoc/vf-logistics-nebius-nvidia --head gemma-backlog --state all --json number,title,state,mergedAt,baseRefName,mergeStateStatus,statusCheckRollup
  - gh pr checks --repo hoachauphuoc/vf-logistics-nebius-nvidia gemma-backlog

## Context
A verify_only task that only reads: the pull requests whose head is gemma-backlog (state, base branch, merged time, merge status, CI rollup) and the CI checks of the branch. Output in `orchestrator/runs/VPR/attempt_1.log`. If `gh` is missing or not signed in, the log says so and the answer has to come from VMERGE2.
<!-- TASK_END -->

<!-- TASK_START: VLOCAL -->
## Meta
- title: Local master versus origin/master (read-only)
- verify_only: true
- test_commands:
  - git log --oneline --decorate -5
  - git branch -vv
  - git rev-parse HEAD origin/master origin/gemma-backlog
  - git rev-list --left-right --count origin/master...HEAD

## Context
Read-only git commands, output in `orchestrator/runs/VLOCAL/attempt_1.log`. The last line prints "<commits only on origin/master> <commits only on local HEAD>": a first number 0 and a second number above 0 means the local branch is ahead of origin/master and the push did not reach the remote.
<!-- TASK_END -->

<!-- TASK_START: VCI -->
## Meta
- title: CI state on GitHub (read-only, GitHub CLI)
- verify_only: true
- test_commands:
  - git ls-remote --heads origin master gemma-backlog
  - gh pr list --repo hoachauphuoc/vf-logistics-nebius-nvidia --state all --limit 5 --json number,title,state,headRefName,baseRefName,mergedAt,mergeStateStatus
  - gh run list --repo hoachauphuoc/vf-logistics-nebius-nvidia --limit 10 --json databaseId,workflowName,headBranch,headSha,event,status,conclusion,createdAt

## Context
Read-only: the heads of master and gemma-backlog on the remote, the latest pull requests, and the latest GitHub Actions runs with their branch, commit, status and conclusion. Output in `orchestrator/runs/VCI/attempt_1.log`. It reruns on every invocation.
<!-- TASK_END -->

<!-- TASK_START: VBRANCH -->
## Meta
- title: Which remote branches have commits that master does not (read-only after a fetch)
- verify_only: true
- test_commands:
  - git fetch origin --prune
  - git merge-base --is-ancestor origin/gemma-backlog origin/master && echo GEMMA_BACKLOG_IN_MASTER || echo GEMMA_BACKLOG_NOT_IN_MASTER
  - git log --oneline --decorate -4 origin/master
  - git log --oneline --format="%h %an %ad %s" --date=short origin/master..origin/claude/kind-meitner-gqllb8
  - git rev-list --count origin/master..origin/claude/fervent-darwin-ij8esp
  - git rev-list --count origin/master..origin/claude/elegant-pascal-lsbuxt
  - git rev-list --count origin/master..origin/gemma-backlog

## Context
Read-only after `git fetch origin --prune` (updates remote-tracking refs only). For each branch: how many commits it has that origin/master does not (0 = nothing would be lost by deleting it), and the commit(s) that claude/kind-meitner-gqllb8 has beyond master. Output in `orchestrator/runs/VBRANCH/attempt_1.log`.
<!-- TASK_END -->

<!-- TASK_START: VKEEP -->
## Meta
- title: What the one extra commit of claude/kind-meitner-gqllb8 contains (read-only)
- verify_only: true
- test_commands:
  - git show --stat --format="%h %an %ad%n%s%n%b" --date=short 8031a83
  - git ls-tree -r --name-only origin/master -- orchestrator/execution_plan.md

## Context
Read-only. The commit `8031a83` is the only commit of the branch that master lacks. The first command lists its files, the second shows whether master has the same file path today. Output in `orchestrator/runs/VKEEP/attempt_1.log`.
<!-- TASK_END -->

<!-- TASK_START: PDSYNC -->
## Meta
- title: Pre-deploy, step 1 - the code under test is exactly origin/master
- verify_only: true
- test_commands:
  - git fetch origin
  - git status -sb
  - git rev-parse HEAD origin/master
  - git diff --stat origin/master -- src frontend tests requirements.txt pyproject.toml Dockerfile Dockerfile.backend entrypoint.sh
  - git diff --quiet origin/master -- src frontend tests requirements.txt pyproject.toml Dockerfile Dockerfile.backend entrypoint.sh

## Context
Every later check runs on the working tree, so it must hold the code that will be deployed: the application, its tests and the files that build the image, compared with origin/master. The last command exits 1 when anything differs; the one before shows what. `scripts/` and `orchestrator/` are tooling, not part of the image, and are left out on purpose (PD1 changes `scripts/verify_review_vi.py`). Read-only apart from `git fetch`, which only updates remote-tracking refs.
<!-- TASK_END -->

<!-- TASK_START: PD1 -->
## Meta
- title: Pre-deploy, step 2 - the review VI table also checks the fixes made after it was written
- depends_on: []
- target_files:
  - scripts/verify_review_vi.py
- test_commands:
  - python -c "import ast; ast.parse(open('scripts/verify_review_vi.py', encoding='utf-8').read()); print('syntax ok')"
  - python scripts/verify_review_vi.py --no-frontend
- timeout_sec: 420
- max_retries: 1

## Context
scripts/verify_review_vi.py is the single table that answers "is review VI fixed?". Three fixes landed after it was written and are not rows yet: a timed-out send recorded as send_unknown (N01), the request-level link refused when several documents were requested (N03), and the evaluation record that names papers read only in part (N06). This task adds one row each, pointing at their existing tests. The second command runs the table (it always exits 0); the verdict is read from V2's log.

## Prompt
``````text
TASK PD1. Add three rows to the list CHECKS in scripts/verify_review_vi.py. Nothing else.

FILE YOU MAY EDIT (only this one): scripts/verify_review_vi.py. Use the Edit tool with a ONE-LINE old_string, exactly as given (leading spaces included). Never use a multi-line old_string. Never use Write on this file. Do not change any existing row.

EDIT 1. old_string, ONE line (4 leading spaces; occurs once, at line 100):
```python
    ("E01-a", "E01", "changing only the answer label changes the score, not the decision", "probe",
```
new_string is the block below: three new rows, and then that same line again as the last line:
```python
    ("N01-f", "N01", "a timed-out send is recorded as send_unknown and the retry sends with the same key", "py",
     [("test_send_unknown.py", "test_a_timeout_is_recorded_as_unknown_and_keeps_the_key"),
      ("test_send_unknown.py", "test_a_timed_out_send_is_unknown_and_the_retry_sends_with_the_same_key")]),
    ("N03-c", "N03", "a link without a document type is refused when several documents were requested", "py",
     [("test_untyped_link.py", "test_with_several_documents_requested_it_is_refused"),
      ("test_untyped_link.py", "test_with_one_document_requested_the_request_level_link_still_works")]),
    ("N06-e", "N06", "the evaluation record names the papers that were read only in part", "py",
     [("test_unread_pages_evaluation.py", "test_a_received_paper_read_in_part_is_unresolved_and_says_why")]),
    ("E01-a", "E01", "changing only the answer label changes the score, not the decision", "probe",
```

DONE WHEN: only this file changed, by the eight added lines; every existing row is unchanged.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if the old_string line is not found.
``````
<!-- TASK_END -->

<!-- TASK_START: PDCI -->
## Meta
- title: Pre-deploy, step 5 - GitHub CI is green on the exact origin/master commit
- verify_only: true
- test_commands:
  - git fetch origin
  - python -c "import json,subprocess as s; R='hoachauphuoc/vf-logistics-nebius-nvidia'; sha=s.check_output(['git','rev-parse','origin/master'],text=True).strip(); runs=json.loads(s.check_output(['gh','run','list','--repo',R,'--workflow','CI','--branch','master','--limit','5','--json','databaseId,headSha,status,conclusion,event'],text=True)); run=next((r for r in runs if r['headSha']==sha),None); print('origin/master',sha); print('CI run',run); jobs=json.loads(s.check_output(['gh','run','view',str(run['databaseId']),'--repo',R,'--json','jobs'],text=True))['jobs'] if run else []; print('\n'.join(j['name']+': '+str(j['conclusion']) for j in jobs)); ok=bool(run) and run['conclusion']=='success' and bool(jobs) and all(j['conclusion']=='success' for j in jobs); print('CI_ON_DEPLOY_COMMIT_GREEN' if ok else 'CI_NOT_PROVEN'); raise SystemExit(0 if ok else 1)"

## Context
The CI workflow (.github/workflows/ci.yml) runs on every push to master: lint, typecheck (strict mypy on the clean modules and the ratchet on the whole package, Python 3.11, pinned mypy), tests, frontend, and a container job that builds and smoke-tests the images. This task finds the CI run for the exact origin/master commit and prints every job with its conclusion; it passes only when the run and every job are "success". It is also the mypy proof: the local mypy line in VFULL cannot be trusted on this machine (a numpy stub with Python 3.12 syntax stops mypy before it checks anything).

HUMAN CHECKLIST BEFORE DEPLOY (cannot be checked from this machine; the Master does not touch production):
1. Open evidence requests on the live service. Production runs an older build that gave shippers ONE link per request. After this deploy such a link is refused (400) when the request asked for several documents (N03). For every open request with several documents: after deploy, issue a new link (the console's new-link action) and send the typed links again.
2. Firestore: 16 backend tests skip without the Firestore emulator. Run them in an environment that has it (the agent may not run gcloud), or accept the gap knowingly.
3. Configuration: this deploy needs no new environment variable or secret. The new route approve-exception needs an account in OPERATOR_EMAILS to be used; the console does not call it yet.
4. The deploy itself (Cloud Run `vf-app`) is the human's, with their credentials.
5. Recommended by the review: one end-to-end run in a real browser with two cases (reviewer asks, shipper uploads without signing in, re-evaluate, decision with a reason, execution), and note the evidence version, decider and result of each.
<!-- TASK_END -->

<!-- TASK_START: PDPOST -->
## Meta
- title: After deploy - the live service is healthy and serves the new code
- verify_only: true
- test_commands:
  - python -c "import httpx; B='https://vf-app-350828852747.asia-southeast1.run.app'; h=httpx.get(B+'/health',timeout=30); print('health',h.status_code,h.text[:300]); p=httpx.get(B+'/api/v1/review/CASE-PROBE/approve-exception',timeout=30); print('approve-exception GET',p.status_code); ok=h.status_code==200 and p.status_code==405; print('NEW_CODE_LIVE' if ok else 'NOT_PROVEN'); raise SystemExit(0 if ok else 1)"

## Context
Run ONLY after the human has deployed. Two read-only GET requests to the live service, no credentials: `/health` must answer 200, and the route added in this release (`/api/v1/review/<id>/approve-exception`, POST only) must answer 405 Method Not Allowed to a GET. 405 means the route exists, so the new code is serving; 404 means the old build is still live. Nothing is written on the service.
<!-- TASK_END -->

<!-- TASK_START: VPDF -->
## Meta
- title: Print the Japanese review report (HTML) to PDF with headless Edge
- verify_only: true
- test_commands:
  - if exist "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" (echo EDGE_FOUND) else (echo EDGE_MISSING)
  - "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --headless --disable-gpu --no-pdf-header-footer --print-to-pdf="%CD%\orchestrator\runs\VPDF\review_vi_report_ja.pdf" "%CD%\orchestrator\archive\review_vi_report_ja.html"
  - dir orchestrator\runs\VPDF

## Context
A verify_only task that produces a file instead of changing code: it prints `orchestrator/archive/review_vi_report_ja.html` (the Japanese report for the reviewer) to `orchestrator/runs/VPDF/review_vi_report_ja.pdf` with headless Edge, then lists the folder to show the file size. Nothing outside `orchestrator/runs/` is written. If the first line says EDGE_MISSING, the second command fails and the log says so.
<!-- TASK_END -->

<!-- TASK_START: VCHK -->
## Meta
- title: Recheck after the review corrections - commit present, gate green, nothing deployed
- verify_only: true
- test_commands:
  - git log --oneline -6
  - git status --porcelain
  - git rev-parse HEAD origin/master
  - git diff --stat origin/master -- src frontend tests requirements.txt pyproject.toml Dockerfile Dockerfile.backend entrypoint.sh

## Context
Read-only check that the corrections the human reported are committed: the last commits, the working tree (which should list only the tooling files not yet committed), and whether HEAD's code equals origin/master. The gate itself is rerun as separate tasks (V2, VFULL) after this one.
<!-- TASK_END -->

## Parked

<!-- PARKED_TASK_START: C3 -->
## Meta
- title: A partly read paper (pages_read < pages) is not fully provided (N06-B)
- depends_on:
  - C1
  - C2
- target_files:
  - src/vf_logistics/verifier.py
  - src/vf_logistics/evidence.py
  - tests/test_origin_inputs.py
  - tests/test_evidence_eval_approve.py
- test_commands:
  - python -m pytest tests/test_origin_inputs.py tests/test_evidence_respond.py tests/test_evidence_eval_approve.py -q
  - python -m pytest tests/test_verifier.py -q
- timeout_sec: 300
- max_retries: 2

## Context
verifier.py must not treat a document the reader only partly read as fully provided. Stricter only; never lowers the floor. PARKED until the human decides the multi-page behaviour.

## Prompt
``````text
RUNNER MODE OVERRIDE (applies to everything below): you cannot run shell commands, git or tests; the runner runs them after you finish. Skip every step that says to run a command, see a test fail, check git status or compare with a baseline; do only the file edits and reading. Where the text says STOP and ask, change nothing and reply in at most 3 lines what differs.

TASK C3 - A paper the reader only partly read (pages_read < pages) is not fully "provided"

PREREQUISITES: tasks C1 and C2 are already applied in this working copy. (C2 made every received evidence document carry the top-level keys "pages" and "pages_read".) If `grep -n "pages_read" src/vf_logistics/evidence.py` finds nothing, STOP and tell me.

RULES FOR THIS TASK (read them first, they apply to every step)
- Work ONLY in the files listed under FILES. Do not open, edit or "tidy" anything else.
- Make the smallest change that does the job. Do not rewrite or reformat whole files, do not run a formatter or a linter with --fix, do not rename anything.
- Do not edit, delete, skip or loosen any EXISTING test. The only existing test code you may change is the signature/body of the helper `_submit_per_type` exactly as shown below.
- Do not touch authentication, password, session, tenant or permission code anywhere in the repo.
- Use ONLY the function and variable names that appear in the code excerpts below. If you want a name that is not in an excerpt, grep for it first; if it does not exist, do not invent it - stop and ask me.
- Edit with small exact replacements. If the edit tool says the text was not found (the files may use Windows line endings), retry with a shorter anchor of one or two lines. Never recreate a whole file.
- Before changing anything run the BASELINE command and tell me how many tests passed.
- When finished run the TEST COMMANDS and paste the last 15 lines of each output.
- If any STOP AND ASK condition at the bottom happens, stop and ask me. Do not improvise.

BACKGROUND
The evidence reader transcribes only page 1 of a PDF. Since task C2 each stored evidence document (the dicts passed to check_origin_evidence) has top-level keys "pages" (page count of the file) and "pages_read" (pages the reader transcribed). A multi-page paper that was read from page 1 only cannot prove what pages 2..N say, so check_origin_evidence must NOT count it as fully provided. Project rules you must keep: a check may only RAISE risk or leave it unchanged, never lower it; when in doubt a paper is NOT proven (fail closed); what a partly read paper does say must still be read for contradictions.

WHAT MUST HAPPEN
- A document whose "pages" and "pages_read" are both real integers (not bool) and pages_read < pages: is NOT added to `present` (so it lands in `missing`, and reevaluate then lists it as "unresolved"), and is reported in a new key of the result: "unread": [{"doc_type", "pages", "pages_read"}].
- A document without these keys, with None, with strings/floats/bools, or with pages_read >= pages behaves EXACTLY as before. The result always has the key "unread" (an empty list when nothing is unread).
- The partly read document is still put in read_by_type first, so its contradictions are still reported.
- reevaluate() copies the new key into the evaluation record it writes, so a reviewer can see WHY a received paper is "unresolved".
- pages / pages_read are read from the document dict itself (written by our own code). NEVER read them from doc["extracted"] (that is the untrusted model output).

FILES
- src/vf_logistics/verifier.py                (change)
- src/vf_logistics/evidence.py                (change: ONE entry in reevaluate)
- tests/test_origin_inputs.py                 (append at the END)
- tests/test_evidence_eval_approve.py         (change helper `_submit_per_type`, add one test class)

BASELINE command (run it before any edit; expect about 258 passed)
python -m pytest tests/test_origin_inputs.py tests/test_evidence_respond.py tests/test_evidence_eval_approve.py -q

CURRENT CODE (copied verbatim from the repo as it is after C1 and C2)

1) src/vf_logistics/verifier.py, the helper just before check_origin_evidence (near line 1360). You will add a new function right after it:

```python
# FILE: src/vf_logistics/verifier.py
def _as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    return list(value) if isinstance(value, (list, tuple, set)) else [value]
```

2) The end of the docstring of check_origin_evidence (near line 1382):

```python
# FILE: src/vf_logistics/verifier.py
    Returns {"status": "missing"|"provided"|"contradicted", "present", "missing",
    "findings", "contradictions"}; `findings` are extra findings to add to the case
    (empty unless something contradicts).
    """
```

3) Inside check_origin_evidence, the two dicts that collect papers (near line 1398):

```python
# FILE: src/vf_logistics/verifier.py
    by_type: dict[str, list[dict[str, Any]]] = {}
    read_by_type: dict[str, list[dict[str, Any]]] = {}
```

4) The loop that classifies the papers (near line 1415), as it is after C1:

```python
# FILE: src/vf_logistics/verifier.py
            ext = doc["extracted"]
            if ext:
                read_by_type.setdefault(dt, []).append(ext)
            required = _REQUIRED_FIELDS.get(dt, ())
```

5) The return statement at the end of check_origin_evidence (near line 1514):

```python
# FILE: src/vf_logistics/verifier.py
        "findings": findings,
        "contradictions": contradictions,
    }
```

6) src/vf_logistics/evidence.py, in reevaluate() (near line 790): the documents handed to the check, and the evaluation record. Note that `documents` are the stored document dicts themselves, so they carry "pages" and "pages_read":

```python
# FILE: src/vf_logistics/evidence.py
    documents = [
        d for d in record["documents"]
        if isinstance(d, dict) and not d.get("blocked") and isinstance(d.get("extracted"), dict)
    ]
    evidence_result = verifier.check_origin_evidence(shipment, documents)
```

```python
# FILE: src/vf_logistics/evidence.py
        "clarified": evidence_result.get("present") or [],
        "unresolved": evidence_result.get("missing") or [],
        "contradictions": evidence_result.get("contradictions") or [],
        "status": evidence_result["status"],
```

7) tests/test_evidence_eval_approve.py, the helper that submits one document per type with a mocked extraction (near line 240):

```python
# FILE: tests/test_evidence_eval_approve.py
def _submit_per_type(links, extracted_by_type):
    for dt, ext in extracted_by_type.items():
        mock = {
            "agent": "evidence_extraction", "model": "test", "result": ext,
            "latency_ms": 10, "input_tokens": 10, "output_tokens": 10,
            "parse_error": False, "at": "2026-10-12T08:00:00Z",
        }
```

WHAT TO CHANGE (exactly this, nothing more)

(a) verifier.py: insert this function right after _as_list (excerpt 1), two blank lines before and after:

```python
# ADD: src/vf_logistics/verifier.py
def _read_in_part(doc: dict[str, Any]) -> bool:
    """True when the record says the file had more pages than the reader saw.

    `pages` and `pages_read` are written by evidence.receive_evidence from the reader's
    own counts. A record without them (an older one, or an extraction that reported none)
    is not "partly read": nothing says it was.
    """
    pages, read = doc.get("pages"), doc.get("pages_read")
    if isinstance(pages, bool) or isinstance(read, bool):
        return False
    if not isinstance(pages, int) or not isinstance(read, int):
        return False
    return read < pages
```

(b) verifier.py: replace the docstring ending of excerpt 2 by:

```python
# ADD: src/vf_logistics/verifier.py
    A document the reader saw only part of (its record has `pages_read` below `pages`)
    is not complete proof: it is left out of `present` and listed in `unread`. What it
    does say is still read for contradictions.

    Returns {"status": "missing"|"provided"|"contradicted", "present", "missing",
    "findings", "contradictions", "unread"}; `findings` are extra findings to add to the
    case (empty unless something contradicts) and `unread` is a list of
    {"doc_type", "pages", "pages_read"}, empty when every document was read in full.
    """
```

(c) verifier.py: directly after the line `read_by_type: dict[str, list[dict[str, Any]]] = {}` (excerpt 3) add one line:

```python
# ADD: src/vf_logistics/verifier.py
    unread: list[dict[str, Any]] = []
```

(d) verifier.py: in the loop (excerpt 4) replace the two lines `if ext:` / `read_by_type.setdefault(dt, []).append(ext)` by the block below. The new lines go INSIDE `if ext:`, AFTER the read_by_type line, and BEFORE `required = ...`:

```python
# ADD: src/vf_logistics/verifier.py
            if ext:
                read_by_type.setdefault(dt, []).append(ext)
                # N06-B: the reader saw only some of the pages. What it did read is in
                # `read_by_type` and still counts for contradictions, but a partial
                # reading cannot prove the rest, so it never reaches `by_type`.
                if _read_in_part(doc):
                    unread.append({
                        "doc_type": dt, "pages": doc["pages"], "pages_read": doc["pages_read"],
                    })
                    continue
```

(e) verifier.py: in the return (excerpt 5) add `"unread": unread,` as the last entry:

```python
# ADD: src/vf_logistics/verifier.py
        "findings": findings,
        "contradictions": contradictions,
        "unread": unread,
    }
```

(f) evidence.py, reevaluate: in the evaluation record (second block of excerpt 6) add these three lines between the "contradictions" line and the "status" line:

```python
# ADD: src/vf_logistics/evidence.py
        "contradictions": evidence_result.get("contradictions") or [],
        # Received but only partly read: why such a document is in `unresolved`.
        "unread": evidence_result.get("unread") or [],
        "status": evidence_result["status"],
```

(g) tests/test_evidence_eval_approve.py: change the helper of excerpt 7 to take extra envelope fields:

```python
# ADD: tests/test_evidence_eval_approve.py
def _submit_per_type(links, extracted_by_type, **envelope_extra):
    """`envelope_extra` goes into every mocked extraction envelope (source_pages=...)."""
    for dt, ext in extracted_by_type.items():
        mock = {
            "agent": "evidence_extraction", "model": "test", "result": ext,
            "latency_ms": 10, "input_tokens": 10, "output_tokens": 10,
            "parse_error": False, "at": "2026-10-12T08:00:00Z",
            **envelope_extra,
        }
```

Do NOT change anything else in verifier.py or evidence.py. In particular do NOT change usable_document, receive_evidence, request_evidence, approve, the findings/floors, or _REQUIRED_FIELDS.

Why this is correct (use it to check yourself, do not change the design):
- The `continue` in (d) comes after the document is stored in read_by_type, so contradictions are still read from a partly read paper; only by_type (which feeds `present`) is skipped.
- `present` excludes the paper, so `missing` includes it; evidence.reevaluate already turns `missing` into "unresolved", and approve() already demands a written note to release over unresolved evidence. So fail-closed behaviour needs no change there.
- isinstance(True, int) is True in Python, so bools are rejected explicitly in _read_in_part.
- If a second, fully read copy of the same type exists, the type is `present` (by_type has it) and the short read stays listed in `unread`.
- An EMPTY extraction ({}) is not listed as unread: `if ext:` is false for it. Keep the new code inside `if ext:`.

TESTS

(h) Append this to the END of tests/test_origin_inputs.py. It uses names that already exist in that file (plywood, docs, GOOD, check_origin_evidence, ORIGIN_EVIDENCE_DOCS, pytest): add NO imports. Replace the two TODO comments by two real tests that follow their instructions.

```python
# TEST: append to tests/test_origin_inputs.py
def with_pages(documents: list[dict], doc_type: str, pages, pages_read) -> list[dict]:
    """`documents` with the page counts evidence.receive_evidence records set on one of them."""
    for d in documents:
        if d["doc_type"] == doc_type:
            d["pages"], d["pages_read"] = pages, pages_read
    return documents


class TestN06BADocumentTheReaderOnlyPartlyRead:
    """The reader transcribes page 1 of a PDF (PDF_PAGES_READ). A paper whose record says
    it had more pages than were read cannot prove the whole of it: it is not `present`, and
    `unread` says which paper and how much of it was seen."""

    @pytest.mark.parametrize("doc_type", ORIGIN_EVIDENCE_DOCS)
    def test_a_paper_with_pages_unread_is_not_provided_and_is_listed(self, doc_type):
        out = check_origin_evidence(plywood(), with_pages(docs(**GOOD), doc_type, 3, 1))
        assert out["status"] == "missing"
        assert doc_type not in out["present"]
        assert out["missing"] == [doc_type]
        assert out["unread"] == [{"doc_type": doc_type, "pages": 3, "pages_read": 1}]
        assert out["findings"] == [] and out["contradictions"] == []

    @pytest.mark.parametrize("pages, pages_read", [(1, 1), (3, 3), (2, 5)])
    def test_a_paper_read_in_full_is_provided_with_nothing_unread(self, pages, pages_read):
        out = check_origin_evidence(plywood(), with_pages(docs(**GOOD), "certificate_of_origin", pages, pages_read))
        assert out["status"] == "provided"
        assert out["unread"] == []

    @pytest.mark.parametrize("pages, pages_read", [
        (None, None), (3, None), (None, 1), ("3", "1"), (True, False),
    ])
    def test_a_record_without_usable_counts_behaves_as_before(self, pages, pages_read):
        out = check_origin_evidence(plywood(), with_pages(docs(**GOOD), "certificate_of_origin", pages, pages_read))
        assert out["status"] == "provided"
        assert out["unread"] == []

    def test_documents_without_the_fields_behave_as_before(self):
        out = check_origin_evidence(plywood(), docs(**GOOD))
        assert out["status"] == "provided" and out["unread"] == []
        empty = check_origin_evidence(plywood(), [])
        assert empty["status"] == "missing" and empty["unread"] == []

    # TODO (you write this test): what a partly read paper DOES say still counts. Use
    #     cert = {"producer_name": "Saigon Plywood Co", "origin_country": "China"}
    # in place of GOOD["certificate_of_origin"], mark it 4 pages / 1 read with with_pages,
    # and assert status "contradicted", a contradiction of kind "certificate_country", and
    # out["unread"] == [{"doc_type": "certificate_of_origin", "pages": 4, "pages_read": 1}].

    # TODO (you write this test): two certificates, the first 3 pages / 1 read and the second
    # (plain GOOD["certificate_of_origin"]) with no counts. Build the list as
    #     with_pages(docs(**GOOD), "certificate_of_origin", 3, 1) + docs(certificate_of_origin=GOOD["certificate_of_origin"])
    # and assert status "provided", "certificate_of_origin" in out["present"], and that
    # out["unread"] still lists exactly one entry, for "certificate_of_origin".
```

(i) tests/test_evidence_eval_approve.py: insert this block directly BEFORE the line `class TestN07LegacyDecide(Base):` (two blank lines before and after). DOCS3, PAPERS, REVIEWER, run, evidence, pytest and Base already exist in that file (PAPERS is defined further down the file; that is fine because it is only used when the tests run): add NO imports. Replace the TODO comment by a real test.

```python
# TEST: insert before `class TestN07LegacyDecide(Base):` in tests/test_evidence_eval_approve.py
class TestN06BPartlyReadPapers(Base):
    """The reader sees page 1 of a PDF only. A paper it read in part is received, but it
    is not proof: the evaluation leaves it unresolved and says what was seen."""

    def _evaluate(self, **certificate_pages):
        self.put()
        out = run(evidence.request_evidence("CASE-1", REVIEWER, documents=DOCS3))
        links = {link["doc_type"]: link["token"] for link in out["links"]}
        _submit_per_type(links, {dt: PAPERS[dt] for dt in DOCS3 if dt != "certificate_of_origin"})
        _submit_per_type(links, {"certificate_of_origin": PAPERS["certificate_of_origin"]}, **certificate_pages)
        return run(evidence.reevaluate("CASE-1"))["evaluation"]

    def test_a_certificate_of_which_one_page_was_read_is_unresolved_not_clarified(self):
        ev = self._evaluate(source_pages=4, source_pages_read=1)
        assert ev["status"] == "missing"
        assert ev["unresolved"] == ["certificate_of_origin"]
        assert "certificate_of_origin" not in ev["clarified"]
        assert ev["unread"] == [{"doc_type": "certificate_of_origin", "pages": 4, "pages_read": 1}]
        # The paper is still on the record as received.
        assert self.stored()["verification"]["requests"][0]["received_docs"]["certificate_of_origin"]

    @pytest.mark.parametrize("counts", [{}, {"source_pages": 1, "source_pages_read": 1}])
    def test_a_paper_read_in_full_or_without_counts_is_clarified_with_nothing_unread(self, counts):
        ev = self._evaluate(**counts)
        assert ev["status"] == "provided"
        assert ev["unresolved"] == [] and ev["unread"] == []

    # TODO (you write this test): releasing over a partly read certificate is allowed only
    # with a note, like any unresolved evidence. Call self._evaluate(source_pages=4, source_pages_read=1),
    # then evidence.approve("CASE-1", "release", REVIEWER, note="", actor_auth="password") must raise
    # evidence.EvidenceError with status 400 (use pytest.raises like the tests above), and the same call
    # with note="Read pages 2-4 by hand" must succeed with
    # result["approval"]["exception"]["unresolved"] == ["certificate_of_origin"].
```

TEST COMMANDS (PowerShell, run from the repo root)
1. python -m pytest tests/test_origin_inputs.py tests/test_evidence_respond.py tests/test_evidence_eval_approve.py -q
   Expect: all pass (about 273 passed before your two or three TODO tests).
2. python -m pytest tests/test_verifier.py -q
   Expect: all pass.
3. python -m pytest -q
   Expect: no failures (about 1530 passed, 16 skipped).

SELF-CHECK before you report (answer each in one line)
- Why does a partly read paper still produce contradictions? (answer: it is put in read_by_type before the `continue`)
- Where do pages / pages_read come from: the document dict or doc["extracted"]? Why?
- What does `unread` hold when no document has page counts?
- Did `git diff --stat` show only the four listed files?

STOP AND ASK (do not continue) if
- C1 or C2 does not seem to be applied, or the excerpts above do not match the files;
- the BASELINE command does not pass;
- any existing test fails after your change, or you feel you must edit an existing test to make it pass;
- you think you need to change usable_document, receive_evidence, request_evidence, approve, the UI (frontend/), document_agent.py, or add a finding / floor for unread papers (all out of scope: that is a separate decision for a human);
- you are tempted to treat pages_read < pages as a CONTRADICTION: it is only "not fully provided".
``````
<!-- PARKED_TASK_END -->

---

<!-- TASK_START: RM1t -->
## Meta
- title: Test that the sub-agent is started with skills disabled (must fail before RM1c)
- target_files:
  - tests/test_automation_runner_cli_args.py
- test_commands:
  - python -c "import subprocess,sys; r=subprocess.call('python -m pytest tests/test_automation_runner_cli_args.py -q', shell=True); print('pytest exit', r); sys.exit(0 if r == 1 else 1)"
  - python -m ruff check tests/test_automation_runner_cli_args.py --select E,F,W --ignore E501,E402,W291,W293
- timeout_sec: 300
- max_retries: 1

## Context
The Master's skills live in `.claude/skills/`. `claude -p` loads them for the sub-agent too: they cost
tokens on every call and invite the weak model to act as the Master. `claude` 2.1.301 has the flag
`--disable-slash-commands` ("Disable all skills"). RM1c adds it to `claude_command` in
`orchestrator/automation_runner.py`. This task only adds the tests; the first test MUST fail now
(the test_command passes only when pytest exits with 1). Do not touch `orchestrator/automation_runner.py`.

## Prompt
``````text
RM1t. Create ONE new file with exactly the content below. Change nothing else.
FILES YOU MAY EDIT (only these): tests/test_automation_runner_cli_args.py (new file; it does not exist yet)

You cannot run commands. The runner runs the tests after you finish. The first test is EXPECTED to
fail today; do not try to make it pass and do not edit orchestrator/automation_runner.py.

Names you may use, all already exist in orchestrator/automation_runner.py:
- `claude_command(claude_bin: str, max_turns: int) -> list[str]`
- `ALLOWED_TOOLS`, `DISALLOWED_TOOLS` (module-level strings)

Write this file with the Write tool, exactly:

# NEW FILE tests/test_automation_runner_cli_args.py
"""
The sub-agent is started with --disable-slash-commands: the Master's skills in .claude/skills/ must
not reach the local model, where they cost tokens on every call and invite it to act as the Master.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "orchestrator"))
import automation_runner as runner  # noqa: E402


def test_the_sub_agent_starts_with_skills_disabled(monkeypatch):
    monkeypatch.delenv("CLAUDE_EXTRA_ARGS", raising=False)
    cmd = runner.claude_command("claude", 40)
    assert "--disable-slash-commands" in cmd


def test_the_tool_limits_stay_in_the_command(monkeypatch):
    monkeypatch.delenv("CLAUDE_EXTRA_ARGS", raising=False)
    cmd = runner.claude_command("claude", 40)
    assert cmd[:2] == ["claude", "-p"]
    assert cmd[cmd.index("--allowedTools") + 1] == runner.ALLOWED_TOOLS
    assert cmd[cmd.index("--disallowedTools") + 1] == runner.DISALLOWED_TOOLS
    assert cmd[cmd.index("--max-turns") + 1] == "40"


def test_extra_args_still_come_last(monkeypatch):
    monkeypatch.setenv("CLAUDE_EXTRA_ARGS", "--verbose")
    cmd = runner.claude_command("claude", 40)
    assert cmd[-1] == "--verbose"
# END OF FILE (do not write this line)

DONE WHEN: the file exists with exactly that content (without the two marker lines starting with "# NEW FILE" and "# END OF FILE").
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if tests/test_automation_runner_cli_args.py already exists.
``````
<!-- TASK_END -->

<!-- TASK_START: RM1c -->
## Meta
- title: claude_command always passes --disable-slash-commands to the sub-agent
- depends_on:
  - RM1t
- target_files:
  - orchestrator/automation_runner.py
- test_commands:
  - python -m pytest tests/test_automation_runner_cli_args.py tests/test_automation_runner_verify_plan.py tests/test_automation_runner_verify_run.py -q --basetemp=orchestrator/runs/RM1c/pytest-tmp
  - python -m ruff check orchestrator/ --select E,F,W --ignore E501,E402,W291,W293
- timeout_sec: 300
- max_retries: 1

## Context
Makes the RM1t tests pass. One added list item and one comment line in `claude_command`; the runner's
safety flags (`--allowedTools`, `--disallowedTools`, `--permission-mode`, `--max-turns`) and the
`CLAUDE_EXTRA_ARGS` handling must stay exactly as they are (runner-maintainer guarantee R2).

## Prompt
``````text
RM1c. Add the flag --disable-slash-commands to the command list in claude_command.
FILES YOU MAY EDIT (only these): orchestrator/automation_runner.py

You cannot run commands. The runner runs the tests after you finish.

The function today (lines 376-385 of orchestrator/automation_runner.py), verbatim:

def claude_command(claude_bin: str, max_turns: int) -> list[str]:
    cmd = [
        claude_bin, "-p", "--output-format", "text",
        "--permission-mode", "acceptEdits",
        "--allowedTools", ALLOWED_TOOLS,
        "--disallowedTools", DISALLOWED_TOOLS,
        "--max-turns", str(max_turns),
    ]
    extra = os.environ.get("CLAUDE_EXTRA_ARGS", "")
    return cmd + (shlex.split(extra) if extra else [])

Make ONE edit with the Edit tool. The anchor is this single line (it appears once in the file):
        "--max-turns", str(max_turns),
Replace it with these three lines (the first line stays exactly as it is, 8 spaces of indent each):
        "--max-turns", str(max_turns),
        # The Master's skills must not reach the local model: they cost tokens and invite it to act as the Master.
        "--disable-slash-commands",

Everything else in the function and in the file stays unchanged. Do not remove or reorder any other item.

DONE WHEN: the list in claude_command ends with "--max-turns", str(max_turns), then the comment line, then "--disable-slash-commands", then the closing ].
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if the function does not match the excerpt above.
``````
<!-- TASK_END -->

<!-- TASK_START: RM2t -->
## Meta
- title: Test that every attempt writes a diff of its target files (must fail before RM2c)
- target_files:
  - tests/test_automation_runner_diff.py
- test_commands:
  - python -c "import subprocess,sys; r=subprocess.call('python -m pytest tests/test_automation_runner_diff.py -q --basetemp=orchestrator/runs/RM2t/pytest-tmp', shell=True); print('pytest exit', r); sys.exit(0 if r == 1 else 1)"
  - python -m ruff check tests/test_automation_runner_diff.py --select E,F,W --ignore E501,E402,W291,W293
- timeout_sec: 300
- max_retries: 1

## Context
The Master only plans and reviews; it runs no git command. It reviews what the sub-agent changed
from a file the runner writes: `orchestrator/runs/<ID>/attempt_N.diff`, a unified diff of each target
file against the task's snapshot. It covers untracked files (no `git diff` for them) and is written
before a failed attempt is restored. RM2c adds `write_diff` and calls it in `run_task`. This task only
adds the tests; they MUST fail now (pass only when pytest exits with 1). Do not touch the runner.

## Prompt
``````text
RM2t. Create ONE new file with exactly the content below. Change nothing else.
FILES YOU MAY EDIT (only these): tests/test_automation_runner_diff.py (new file; it does not exist yet)

You cannot run commands. The runner runs the tests after you finish. These tests are EXPECTED to
fail today (write_diff does not exist yet); do not try to make them pass and do not edit
orchestrator/automation_runner.py.

Names you may use, all already exist in orchestrator/automation_runner.py:
- `main(argv)`, `snapshot(repo, targets)`, `find_claude()`, `run_with_timeout(cmd, stdin_text, cwd, env, timeout)`
- `write_diff` does NOT exist yet; RM2c adds it. Use it exactly as written below.

Write this file with the Write tool, exactly:

# NEW FILE tests/test_automation_runner_diff.py
"""
Every attempt writes runs/<ID>/attempt_N.diff: each target file against the task's snapshot. The
Master reviews from this file and runs no git itself, so it must cover untracked files and keep what
a failed attempt wrote, which the runner restores afterwards.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "orchestrator"))
import automation_runner as runner  # noqa: E402


def _plan(command: str) -> str:
    # The markers are joined from parts so that this file, when it is quoted inside a plan,
    # does not read as a task of that plan.
    return (
        "<!-- TASK" + "_START: E -->\n## Meta\n- title: an edit\n- target_files:\n  - a.py\n"
        f"- test_commands:\n  - {command}\n- max_retries: 0\n\n## Prompt\nSet x to 2.\n"
        + "<!-- TASK" + "_END -->\n"
    )


def _fake_sub_agent(cmd, stdin_text, cwd, env, timeout):
    (Path(cwd) / "a.py").write_text("x = 2\n", encoding="utf-8")
    return 0, "a.py: x is 2", "", False


def _run(tmp_path: Path, monkeypatch, command: str) -> int:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    plan = tmp_path / "plan.md"
    plan.write_text(_plan(command), encoding="utf-8")
    monkeypatch.setattr(runner, "find_claude", lambda: "claude")
    monkeypatch.setattr(runner, "run_with_timeout", _fake_sub_agent)
    return runner.main(["--repo", str(tmp_path), "--plan", str(plan)])


def _diff(tmp_path: Path) -> str:
    return (tmp_path / "orchestrator" / "runs" / "E" / "attempt_1.diff").read_text(encoding="utf-8")


def test_a_passing_attempt_writes_the_diff_of_its_target_file(tmp_path, monkeypatch):
    assert _run(tmp_path, monkeypatch, 'python -c "print(1)"') == 0
    diff = _diff(tmp_path)
    assert "--- a/a.py" in diff and "+++ b/a.py" in diff
    assert "-x = 1" in diff
    assert "+x = 2" in diff


def test_a_failed_attempt_keeps_its_diff_after_the_files_are_restored(tmp_path, monkeypatch):
    assert _run(tmp_path, monkeypatch, 'python -c "raise SystemExit(3)"') == 1
    assert "+x = 2" in _diff(tmp_path)
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x = 1\n"


def test_a_new_file_is_shown_as_added_lines(tmp_path):
    snap = runner.snapshot(tmp_path, ["new.py"])
    (tmp_path / "new.py").write_text("print(1)\n", encoding="utf-8")
    runner.write_diff(tmp_path, snap, tmp_path / "out.diff")
    diff = (tmp_path / "out.diff").read_text(encoding="utf-8")
    assert "+++ b/new.py" in diff
    assert "+print(1)" in diff
# END OF FILE (do not write this line)

DONE WHEN: the file exists with exactly that content (without the two marker lines starting with "# NEW FILE" and "# END OF FILE").
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if tests/test_automation_runner_diff.py already exists.
``````
<!-- TASK_END -->

<!-- TASK_START: RM2c -->
## Meta
- title: run_task writes runs/<ID>/attempt_N.diff of the target files before any restore
- depends_on:
  - RM2t
- target_files:
  - orchestrator/automation_runner.py
- test_commands:
  - python -m pytest tests/test_automation_runner_diff.py tests/test_automation_runner_cli_args.py tests/test_automation_runner_verify_plan.py tests/test_automation_runner_verify_run.py -q --basetemp=orchestrator/runs/RM2c/pytest-tmp
  - python -m ruff check orchestrator/ --select E,F,W --ignore E501,E402,W291,W293
- timeout_sec: 420
- max_retries: 1

## Context
Makes the RM2t tests pass. Three additive edits in one file: an import, a new function after
`restore`, and one call in `run_task` right before the existing `cp.update(..., attempts=attempt, ...)`
line, which is before any `restore(opts.repo, snap)`. Nothing existing is removed or changed:
scope enforcement, restore, retries and the log format stay as they are (runner-maintainer R3-R5, R8).
Standard library only (R10).

## Prompt
``````text
RM2c. Add a write_diff function to the runner and call it once per attempt.
FILES YOU MAY EDIT (only these): orchestrator/automation_runner.py

You cannot run commands. The runner runs the tests after you finish. Make exactly THREE edits with
the Edit tool. Each anchor below is ONE line that appears once in the file. Do not change or remove
anything else.

EDIT 1. Anchor (line 33):
import fnmatch
Replace it with these two lines:
import difflib
import fnmatch

EDIT 2. Anchor (the first line of the function after `restore`):
def enforce_scope(repo: Path, before: dict[str, str | None], after: dict[str, str | None],
Replace that ONE line with the new function, two blank lines, then the same anchor line unchanged:

def write_diff(repo: Path, snap: dict[str, bytes | None], path: Path) -> None:
    """Unified diff of each target file against the task's snapshot, written to `path`.

    The Master reviews from this file and runs no git: it must cover untracked files and keep what
    a failed attempt wrote, because the runner restores the files right after.
    """
    chunks: list[str] = []
    for rel, old in snap.items():
        current = repo / rel
        new = current.read_bytes() if current.is_file() else None
        if new == old:
            continue
        a = (old or b"").decode("utf-8", errors="replace").splitlines(keepends=True)
        b = (new or b"").decode("utf-8", errors="replace").splitlines(keepends=True)
        chunks.extend(difflib.unified_diff(a, b, f"a/{rel}", f"b/{rel}"))
    path.write_text("".join(chunks), encoding="utf-8", newline="")


def enforce_scope(repo: Path, before: dict[str, str | None], after: dict[str, str | None],

EDIT 3. Anchor (inside run_task, 8 spaces of indent):
        cp.update(task.id, attempts=attempt, last_error=error, last_attempt_at=utc_now())
Replace it with these two lines (8 spaces of indent each; the second line stays exactly as it is):
        write_diff(opts.repo, snap, run_dir / f"attempt_{attempt}.diff")
        cp.update(task.id, attempts=attempt, last_error=error, last_attempt_at=utc_now())

The names `snap`, `run_dir`, `attempt`, `opts` already exist in run_task. `Path` is already imported.
The line `restore(opts.repo, snap)` further down must stay where it is.

DONE WHEN: `import difflib` is above `import fnmatch`; `write_diff` is defined right above `enforce_scope`;
the write_diff call is directly above that cp.update line in run_task.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if any anchor is not found exactly once.
``````
<!-- TASK_END -->

<!-- TASK_START: N06e -->
## Meta
- title: A country field that holds one country twice or with an unstated entry is compared with the declaration (N06, verifier)
- depends_on: []
- target_files:
  - src/vf_logistics/verifier.py
  - tests/test_origin_inputs.py
- test_commands:
  - python -m pytest tests/test_origin_inputs.py -q
  - python -m pytest tests/test_verifier.py tests/test_evidence_respond.py tests/test_evidence_eval_approve.py -q
  - python -m mypy src/vf_logistics/verifier.py --ignore-missing-imports --follow-imports=silent
- timeout_sec: 420
- max_retries: 1

## Context
Independent reverification of 2026-10-17 (commit 76e6b01), finding N06 (P1, partly fixed). A certificate whose origin_country is ["not stated", "China"] or ["China", "PRC"] counts as "provided" in the completeness test (it holds one country), but the contradiction read in check_origin_evidence only looks at a bare string, so the list is skipped: 0 contradictions, status provided, and Release is approved with no reason and no recorded exception. The same holds for goods_origin_country / supplier_country on the invoice. A bare "China" is caught (floor 45 -> 80), so the same paper passes or fails by how the field is wrapped.
Fix: one helper, `_stated_country`, reads a country field by its distinct stated entries and returns the one canonical country (or "" for none or several). The completeness test and the contradiction reads then see the same value. This only adds contradictions: the risk floor is never lowered. A field that lists two different countries stays unproven (existing N06-A), and a producer declaration's input_origins is untouched.
Master review (from the log): with the tests and without the verifier.py edits, `python -m pytest tests/test_origin_inputs.py -q` shows 6 failed; with both, it passes. The Master also checks that Edit 3 and Edit 4 left no other use of raw_origin.

## Prompt
``````text
TASK N06e. A country field that states one country (twice, or beside an unstated entry) must be compared with the declaration, like a bare string. Six one-line edits in verifier.py and one insertion in the test file.

FILES YOU MAY EDIT (only these two): src/vf_logistics/verifier.py and tests/test_origin_inputs.py. Both use Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given (leading spaces included). Never use a multi-line old_string. Never use Write on these files. Do not touch any other line, any existing test, or any import.

EDIT 1 (verifier.py, add the helper after _names_several_countries). old_string, ONE line (4 leading spaces; occurs once):
```python
    return len({_canon_country(_scalar(v)) for v in value if _is_meaningful(v)}) > 1
```
new_string is that same line, then two blank lines, then the helper:
```python
    return len({_canon_country(_scalar(v)) for v in value if _is_meaningful(v)}) > 1


def _stated_country(value: Any) -> str:
    """The one country a field states, in its canonical spelling; "" when it states none or several.

    A list is read by its distinct stated entries, so ["not stated", "China"] and
    ["China", "PRC"] both state China. The completeness test accepts such a list as one
    country, so the contradiction reads must take it the same way (N06): a list they
    skipped was a paper counted as provided and never compared with the declaration.
    """
    values = value if isinstance(value, (list, tuple)) else [value]
    names = {_canon_country(_scalar(v)) for v in values if _is_meaningful(v)}
    return names.pop() if len(names) == 1 else ""
```

EDIT 2 (verifier.py, certificate). old_string, ONE line (8 leading spaces; occurs once):
```python
        raw_origin = _scalar(cert.get("origin_country"))
```
new_string, ONE line:
```python
        raw_origin = _stated_country(cert.get("origin_country"))
```

EDIT 3 (verifier.py). old_string, ONE line (8 leading spaces; occurs once):
```python
        if not _is_meaningful(raw_origin):
```
new_string, ONE line:
```python
        if not raw_origin:
```

EDIT 4 (verifier.py). old_string, ONE line (8 leading spaces; occurs once):
```python
        stated = _canon_country(raw_origin)
```
new_string, ONE line:
```python
        stated = raw_origin
```

EDIT 5 (verifier.py, invoice). old_string, ONE line (20 leading spaces; occurs once; it is the line inside `goods_origin = next(`):
```python
                    _canon_country(_scalar(v))
```
new_string, ONE line:
```python
                    _stated_country(v)
```

EDIT 6 (verifier.py, invoice). old_string, ONE line (20 leading spaces; occurs once; the line right below the `for v in (inv.get("goods_origin_country"), ...)` line):
```python
                    if _is_meaningful(v)
```
new_string, ONE line:
```python
                    if _stated_country(v)
```
Do not change anything else in verifier.py: not _names_several_countries, not the completeness loop, not the producer_declaration read.

EDIT 7 (tests/test_origin_inputs.py, three tests inside class TestN06ACountryFieldsNameOneCountry, directly before its last test). old_string, ONE line (4 leading spaces; occurs once):
```python
    def test_an_invoice_with_two_countries_is_still_read_for_contradictions(self):
```
new_string is the three tests below, a blank line, and then that same line again:
```python
    @pytest.mark.parametrize("value", [
        ["not stated", "China"], ["China", "PRC"], ["N/A", "People's Republic of China"],
    ])
    def test_a_certificate_for_china_contradicts_a_vietnam_declaration(self, value):
        # One country, however it is wrapped: it must be compared with the declaration (N06).
        cert = {"producer_name": "Saigon Plywood Co., Ltd.", "origin_country": value}
        out = check_origin_evidence(plywood(), docs(**{**GOOD, "certificate_of_origin": cert}))
        assert out["status"] == "contradicted"
        assert "certificate_country" in [c["kind"] for c in out["contradictions"]]

    @pytest.mark.parametrize("goods_origin,supplier_country", [
        (["not stated", "China"], "Vietnam"),
        (["China", "PRC"], "Vietnam"),
        ("not stated", ["China", "PRC"]),
    ])
    def test_an_invoice_for_china_goods_contradicts_however_the_field_is_written(self, goods_origin, supplier_country):
        invoice = {
            **GOOD["input_purchase_invoices"],
            "goods_origin_country": goods_origin,
            "supplier_country": supplier_country,
        }
        out = check_origin_evidence(plywood(), docs(**{**GOOD, "input_purchase_invoices": invoice}))
        assert out["status"] == "contradicted"
        assert "input_origin" in [c["kind"] for c in out["contradictions"]]

    def test_two_spellings_of_the_declared_country_contradict_nothing(self):
        cert = {"producer_name": "Saigon Plywood Co., Ltd.", "origin_country": ["Vietnam", "Viet Nam"]}
        out = check_origin_evidence(plywood(), docs(**{**GOOD, "certificate_of_origin": cert}))
        assert out["status"] == "provided"
        assert out["contradictions"] == []

```

DONE WHEN: only these two files changed; verifier.py gained the helper and has six edited lines, all in the places above; the test file gained the three tests (the first two parametrized).
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if an old_string line is not found exactly once.
``````
<!-- TASK_END -->

<!-- TASK_START: N01e1 -->
## Meta
- title: A publish that the Google SDK reports as DeadlineExceeded or RetryError is recorded as unknown, not failed (N01, tools)
- depends_on: []
- target_files:
  - src/vf_logistics/tools.py
  - tests/test_publish_dedupe.py
- test_commands:
  - python -m pytest tests/test_publish_dedupe.py tests/test_evidence_execution.py -q
  - python -m pytest tests/test_resume_after_publish.py tests/test_publish_attribute.py tests/test_executor_client.py tests/test_pure_logic.py tests/test_internal_execute.py -q
- timeout_sec: 420
- max_retries: 1

## Context
Independent reverification of 2026-10-17, finding N01 (P1, partly fixed). N01d1 records a built-in TimeoutError as "unknown", but the Google Pub/Sub client reports a publish that ran out of time as google.api_core.exceptions.DeadlineExceeded or RetryError, which are not TimeoutError, so those are still recorded as "failed" and read as "nothing was sent". The check goes by class name, through the exception's MRO, so tools.py needs no google.api_core import and the test needs none (google.api_core cannot be imported in this environment: protobuf version clash). Every other exception stays "failed". A retry still sends and carries the same idempotency key.
Master review (from the log): with the test and without the tools.py edits, test_publish_dedupe.py shows 1 failed; with them it passes.

## Prompt
``````text
TASK N01e1. A DeadlineExceeded or RetryError from the publish is "unknown", like a TimeoutError. One helper and one changed line in tools.py, two tests in test_publish_dedupe.py.

FILES YOU MAY EDIT (only these two): src/vf_logistics/tools.py and tests/test_publish_dedupe.py. Both use Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given (leading spaces included). Never use a multi-line old_string. Never use Write on these files. Add no import.

EDIT 1 (tools.py, add a helper above publish_decision_direct). old_string, ONE line (no leading spaces; occurs once):
```python
async def publish_decision_direct(
```
new_string is the helper below, then two blank lines, then that same line again:
```python
def _may_have_been_accepted(exc: BaseException) -> bool:
    """
    True when the broker may have taken the message although the call raised.

    A timeout, and the Google SDK's DeadlineExceeded and RetryError, say nothing about
    whether the message went out (N01). They are matched by class name down the MRO so
    this module needs no google.api_core import.
    """
    return isinstance(exc, TimeoutError) or any(
        cls.__name__ in ("DeadlineExceeded", "RetryError") for cls in type(exc).__mro__
    )
```

EDIT 2 (tools.py). old_string, ONE line (12 leading spaces; occurs once):
```python
            status="unknown" if isinstance(exc, TimeoutError) else "failed",
```
new_string, ONE line:
```python
            status="unknown" if _may_have_been_accepted(exc) else "failed",
```
Do not change anything else in tools.py.

EDIT 3 (tests/test_publish_dedupe.py, two tests inside class TestAnEarlierPublishIsNotRepeated, before its last test). old_string, ONE line (4 leading spaces; occurs once):
```python
    def test_a_decision_without_a_key_is_always_sent(self):
```
new_string is the two tests below, a blank line, and then that same line again:
```python
    def test_an_sdk_deadline_error_is_unknown_not_failed(self):
        # The names are the SDK's own; google.api_core cannot be imported here.
        class DeadlineExceeded(Exception):
            pass

        class RetryError(Exception):
            pass

        for n, error in enumerate((DeadlineExceeded("504 Deadline Exceeded"), RetryError("Deadline of 60.0s exceeded"))):
            pubsub, _ = _fake_pubsub([error])
            first = self._publish(pubsub, key=f"exec-sdk-{n}")
            assert first["status"] == "unknown"
            assert first["detail"]["error"].startswith(type(error).__name__)

    def test_any_other_publish_error_stays_failed(self):
        class ServiceUnavailable(Exception):
            pass

        pubsub, _ = _fake_pubsub([ServiceUnavailable("503 Service Unavailable")])
        assert self._publish(pubsub)["status"] == "failed"

```

DONE WHEN: only these two files changed; tools.py gained the helper and one changed line; the test file gained the two tests.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if an old_string line is not found exactly once.
``````
<!-- TASK_END -->

<!-- TASK_START: N01e2 -->
## Meta
- title: A publish the broker accepted keeps its message id when saving its record fails (N01, tools)
- depends_on:
  - N01e1
- target_files:
  - src/vf_logistics/tools.py
  - tests/test_resume_after_publish.py
- test_commands:
  - python -m pytest tests/test_resume_after_publish.py tests/test_publish_dedupe.py tests/test_evidence_execution.py -q
  - python -m pytest tests/test_publish_attribute.py tests/test_executor_client.py tests/test_pure_logic.py tests/test_internal_execute.py -q
  - python -m ruff check src/vf_logistics/tools.py tests/test_resume_after_publish.py --select E,F,W --ignore E501,E402,W291,W293
- timeout_sec: 480
- max_retries: 1

## Context
Independent reverification of 2026-10-17, finding N01 (P1, partly fixed). In publish_decision_direct the Pub/Sub publish and the audit save of its success sit in one try. Reproduced: the broker accepted "msg-1", the save of the audit row raised ServiceUnavailable once, the handler took it for a failed send and wrote a "failed" row with no message id; the case became EXECUTION_FAILED, and Retry published the same decision again ("msg-2"). The lookup of an earlier publish only counts rows that carry a message id, so it could not see the first one.
Fix: remember that the broker accepted the message (`accepted`). If the save then raises, the handler saves the row again WITH the message id and status "done"; the caller reads it as sent. If that second save also raises, the exception still reaches the caller as before (nothing new is hidden), so the receiving side must keep dropping a repeat by the idempotency_key message attribute (N01a); that is outside this repository, as is a process that dies between the accept and any save.
Master review (from the log): with the new test and without the tools.py edits the test fails (the case ends EXECUTION_FAILED and the message id is lost); with them it passes, and the other listed suites pass.

## Prompt
``````text
TASK N01e2. When the broker accepted the message but saving its record failed, the record is saved again with the message id. Four one-line edits in tools.py (all inside publish_decision_direct) and one test class in test_resume_after_publish.py. Task N01e1 is already applied: the status line below mentions _may_have_been_accepted.

FILES YOU MAY EDIT (only these two): src/vf_logistics/tools.py and tests/test_resume_after_publish.py. Both use Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given (leading spaces included). Never use a multi-line old_string. Never use Write on these files. Add no import. Change no other line of publish_decision_direct.

EDIT 1 (tools.py). old_string, ONE line (8 leading spaces; occurs once):
```python
        import asyncio
```
new_string is the lines below (the last is the old line):
```python
        # Filled once the broker has accepted the message (N01). A failure to SAVE its record
        # is not a failure to SEND: reading it as one lost the message id, and the retry
        # published the decision a second time.
        accepted: dict[str, Any] = {}
        import asyncio
```

EDIT 2 (tools.py). old_string, ONE line (8 leading spaces; occurs once):
```python
        message_id = await asyncio.to_thread(_publish)
```
new_string is that line and the line below it:
```python
        message_id = await asyncio.to_thread(_publish)
        accepted["message_id"] = message_id
```

EDIT 3 (tools.py, inside the `except Exception as exc:` block). old_string, ONE line (12 leading spaces; occurs once):
```python
            {**body, "error": f"{type(exc).__name__}: {exc}"},
```
new_string, ONE line:
```python
            {**body, **accepted, "error": f"{type(exc).__name__}: {exc}"},
```

EDIT 4 (tools.py, the status line in the same block). old_string, ONE line (12 leading spaces; occurs once):
```python
            status="unknown" if _may_have_been_accepted(exc) else "failed",
```
new_string is the two lines below:
```python
            # An accepted message is a sent one, whatever happened to its first record.
            status="done" if accepted else ("unknown" if _may_have_been_accepted(exc) else "failed"),
```

EDIT 5 (tests/test_resume_after_publish.py, a new class at the end of the file). old_string, ONE line (8 leading spaces; occurs once; it is the last line of the file):
```python
        assert stored["verification"]["approvals"][0]["status"] == "EXECUTED"
```
new_string is that same line, then two blank lines, then the class:
```python
        assert stored["verification"]["approvals"][0]["status"] == "EXECUTED"


class TestARecordThatFailsToSaveAfterTheBrokerAccepted(Base):
    def test_the_message_id_is_kept_and_the_decision_is_sent_once(self):
        self.put()
        self.request_and_submit()
        run(evidence.reevaluate("CASE-1"))
        approval_id = run(evidence.approve(
            "CASE-1", "release", REVIEWER, note="Reviewed", actor_auth="password",
        ))["approval"]["approval_id"]
        pubsub, published = _fake_pubsub(["msg-1", "msg-2"])
        real_audit = tools._audit
        refused: list[str] = []

        async def store_down_once(case_id, action, detail, status="done", tenant_id=None):
            # The first save of the publish record fails after the broker accepted the message.
            if action == "publish_decision" and not refused:
                refused.append(action)
                raise RuntimeError("ServiceUnavailable: the store did not answer")
            return await real_audit(case_id, action, detail, status, tenant_id)

        with patch.dict(os.environ, {"PROJECT_ID": "test-project"}), _with_pubsub(pubsub), \
                patch("vf_logistics.tools._audit", new=store_down_once):
            result = run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))

        assert result["state"] == "RELEASED_BY_HUMAN"
        assert result["message_id"] == "msg-1"
        assert len(published) == 1
        stored = self.stored()
        assert [e["status"] for e in stored["verification"]["executions"]] == ["sent"]
        assert stored["verification"]["executions"][0]["message_id"] == "msg-1"
        rows = [r for r in run(self.store.list_audit(limit=500)) if r.get("action") == "publish_decision"]
        assert [(r["status"], r["detail"]["message_id"]) for r in rows] == [("done", "msg-1")]
```

DONE WHEN: only these two files changed; tools.py has four changed places, all inside publish_decision_direct; the test file gained one class at its end.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if an old_string line is not found exactly once.
``````
<!-- TASK_END -->

<!-- TASK_START: N08g -->
## Meta
- title: The review panel reloads the case when approve or execute loses the connection (N08, frontend)
- depends_on: []
- target_files:
  - frontend/src/components/review/ReviewPanel.tsx
  - frontend/src/components/review/ReviewPanel.test.tsx
- test_commands:
  - [frontend] npx vitest run src/components/review/ReviewPanel.test.tsx
  - [frontend] npx tsc --noEmit
  - [frontend] npm run lint
- timeout_sec: 600
- max_retries: 1

## Context
Independent reverification of 2026-10-17, finding N08 (partly fixed), part A. On the real ReviewPanel, Release -> Confirm -> approve succeeds -> execute fails with a 20-second timeout: onError only shows the message, the case is not reloaded, and the screen stays in the state before the approval, although the server approved and may be executing. Only the EXECUTION_FAILED answer reloaded the case (task A1).
Fix: a connection failure (ApiError kind "unreachable") says nothing about what the server did, so the approve/execute mutations call onDecided() (the reload) after it. A refusal the server sent (kind "http", e.g. 409 "in progress" or "Re-evaluate first") is an answer, so it does not reload: the existing test "shows the backend's refusal when the claim is still live there" stays as it is.
Master review (from the log): the vitest run shows 3 more passing tests; with the tests and without the ReviewPanel.tsx edits, the two "reloads the case" tests fail; tsc and lint pass.

## Prompt
``````text
TASK N08g. After a lost connection, ReviewPanel reloads the case. Four edits in ReviewPanel.tsx and three tests in ReviewPanel.test.tsx.

FILES YOU MAY EDIT (only these two): frontend/src/components/review/ReviewPanel.tsx and frontend/src/components/review/ReviewPanel.test.tsx. Both use Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given (leading spaces included). Never use a multi-line old_string. Never use Write on these files. Do not change any mock or any existing test; ApiError, approveCase, executeApproval, renderPanel, makeCase, fireEvent, screen and waitFor already exist in the test file.

EDIT 1 (ReviewPanel.tsx, import). old_string, ONE line (no leading spaces; occurs once):
```tsx
import { approveCase, cancelEvidenceRequest, caseDossierUrl, decideReview, executeApproval, requestDeepReview, reevaluateCase, requestEvidence, reviewDocumentUrl } from "@/lib/api";
```
new_string, ONE line (only `ApiError, ` is new):
```tsx
import { ApiError, approveCase, cancelEvidenceRequest, caseDossierUrl, decideReview, executeApproval, requestDeepReview, reevaluateCase, requestEvidence, reviewDocumentUrl } from "@/lib/api";
```

EDIT 2 (ReviewPanel.tsx, a helper). old_string, ONE line (no leading spaces; occurs once):
```tsx
const ACTION_LABEL: Record<HumanAction, string> = {
```
new_string is the helper below, a blank line, and then that same line again:
```tsx
// A dropped or timed-out connection says nothing about what the server did: the decision
// may have been approved or executed before the answer was lost (N08). A refusal the
// server sent (kind "http") is an answer, so there is nothing to reload.
function outcomeUnknown(error: unknown): boolean {
  return error instanceof ApiError && error.kind === "unreachable";
}

const ACTION_LABEL: Record<HumanAction, string> = {
```

EDIT 3 (ReviewPanel.tsx). old_string, ONE line (2 leading spaces; occurs once):
```tsx
  const verificationApprove = useMutation({
```
new_string is the three lines below (the first is the old line):
```tsx
  const verificationApprove = useMutation({
    onSettled: (_data, error) => {
      if (outcomeUnknown(error)) onDecided();
    },
```

EDIT 4 (ReviewPanel.tsx). old_string, ONE line (2 leading spaces; occurs once):
```tsx
  const verificationExecute = useMutation({
```
new_string is the three lines below (the first is the old line):
```tsx
  const verificationExecute = useMutation({
    onSettled: (_data, error) => {
      if (outcomeUnknown(error)) onDecided();
    },
```
Change nothing else in ReviewPanel.tsx: not the onSuccess or onError handlers, not the other mutations.

EDIT 5 (ReviewPanel.test.tsx, three tests inside the describe "ReviewPanel: resuming an interrupted execution (N08-B)", before its last test). old_string, ONE line (2 leading spaces; occurs once):
```tsx
  it("keeps Execute for an approved case, with no Resume beside it", () => {
```
new_string is the three tests below, a blank line, and then that same line again:
```tsx
  it("reloads the case when Release's execute step loses the connection, and still shows the error", async () => {
    vi.mocked(executeApproval).mockRejectedValueOnce(
      new ApiError("The request took longer than 20s and was abandoned.", 0, "unreachable"),
    );
    const onDecided = renderPanel(makeCase("HELD_FOR_REVIEW"));
    fireEvent.click(screen.getByRole("button", { name: "Release" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(onDecided).toHaveBeenCalledTimes(1));
    expect((await screen.findByRole("alert")).textContent).toMatch(/took longer than 20s/);
  });

  it("reloads the case when Retry loses the connection", async () => {
    vi.mocked(executeApproval).mockRejectedValueOnce(new ApiError("Failed to fetch", 0, "unreachable"));
    const approval = { approval_id: "evapr-1", action: "release", approver: "r", evidence_version: 1, status: "VALID", at: "" };
    const onDecided = renderPanel(makeCase("EXECUTION_FAILED", { approvals: [approval] }));
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(onDecided).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole("alert")).toBeTruthy();
  });

  it("does not reload for a refusal the server sent, which is an answer and not a lost connection", async () => {
    vi.mocked(approveCase).mockRejectedValueOnce(new ApiError("Re-evaluate first.", 409, "http"));
    const onDecided = renderPanel(makeCase("HELD_FOR_REVIEW"));
    fireEvent.click(screen.getByRole("button", { name: "Release" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Re-evaluate first.");
    expect(onDecided).not.toHaveBeenCalled();
    expect(executeApproval).not.toHaveBeenCalled();
  });

  it("keeps Execute for an approved case, with no Resume beside it", () => {
```
(The line `  it("keeps Execute ...` at the end of new_string is the old line, kept.)

DONE WHEN: only these two files changed; ReviewPanel.tsx gained the ApiError import, one helper and two onSettled blocks; the test file gained three tests.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if an old_string line is not found exactly once.
``````
<!-- TASK_END -->

<!-- TASK_START: N08h -->
## Meta
- title: The case page reads an EXECUTING case again every 15 seconds (N08, frontend)
- depends_on: []
- target_files:
  - frontend/src/lib/operations.ts
  - frontend/src/lib/operations.test.ts
  - frontend/src/app/cases/[id]/page.tsx
- test_commands:
  - [frontend] npx vitest run src/lib/operations.test.ts src/components/review/ReviewPanel.test.tsx
  - [frontend] npx tsc --noEmit
  - [frontend] npm run lint
- timeout_sec: 600
- max_retries: 1

## Context
Independent reverification of 2026-10-17, finding N08 (partly fixed), part B. On the real CasePage a case was read once as EXECUTING; the API then changed it to RELEASED_BY_HUMAN and the 60-second clock ticked: the page read no new data, so once the claim lease expired it showed "interrupted - claim expired" with a Resume button for a decision that had completed. The panel's 15-second timer only moves the clock; nothing reloads the case.
Fix: the case query refetches every 15 seconds while the case is EXECUTING and not otherwise. The decision is a small pure function (caseRefetchMs) so a test can pin it; the page uses it as `refetchInterval`. The backend already refuses a second execution of an approval that is no longer executable (409), so a stale Resume click is still refused.
Master review (from the log): operations.test.ts shows 2 more passing tests (they fail on the old code because caseRefetchMs does not exist); the page change is one import word and two lines, which the Master reads in `git diff` because no page test mounts CasePage.

## Prompt
``````text
TASK N08h. The case page reads an EXECUTING case again every 15 seconds. One new function with two tests, and a two-line change in the page.

FILES YOU MAY EDIT (only these three): frontend/src/lib/operations.ts, frontend/src/lib/operations.test.ts and frontend/src/app/cases/[id]/page.tsx. All use Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given (leading spaces included). Never use a multi-line old_string. Never use Write on these files. Change nothing else.

EDIT 1 (operations.ts, add the function). old_string, ONE line (no leading spaces; occurs once):
```ts
/** Whether the evidence on file contradicts the declaration. */
```
new_string is the function below, a blank line, and then that same line again:
```ts
/**
 * How often the case page reads a case again, in milliseconds, or false for never.
 *
 * An execution ends on the server without anyone asking the page, so a page that read
 * the case once as EXECUTING would later show a finished decision as "interrupted" with a
 * Resume button (N08). Every other state changes only when somebody acts on this page.
 */
export function caseRefetchMs(state: string | undefined): number | false {
  return state === "EXECUTING" ? 15_000 : false;
}
```

EDIT 2 (operations.test.ts, import). old_string, ONE line (2 leading spaces; occurs once):
```ts
  buildCaseTimeline,
```
new_string is these two lines:
```ts
  buildCaseTimeline,
  caseRefetchMs,
```

EDIT 3 (operations.test.ts, tests). old_string, ONE line (no leading spaces; occurs once):
```ts
describe("riskLabel", () => {
```
new_string is the block below, a blank line, and then that same line again:
```ts
describe("caseRefetchMs", () => {
  it("reads an executing case again every 15 seconds", () => {
    expect(caseRefetchMs("EXECUTING")).toBe(15_000);
  });

  it("leaves every other state, and a page with no data yet, alone", () => {
    for (const state of ["HELD_FOR_REVIEW", "APPROVED", "EXECUTION_FAILED", "RELEASED_BY_HUMAN", "BLOCKED_BY_HUMAN", undefined]) {
      expect(caseRefetchMs(state)).toBe(false);
    }
  });
});
```

EDIT 4 (page.tsx, import). old_string, ONE line (no leading spaces; occurs once):
```tsx
import { buildCaseTimeline, informationRounds, riskLabel } from "@/lib/operations";
```
new_string, ONE line:
```tsx
import { buildCaseTimeline, caseRefetchMs, informationRounds, riskLabel } from "@/lib/operations";
```

EDIT 5 (page.tsx, the case query). old_string, ONE line (4 leading spaces; occurs once):
```tsx
    queryFn: () => fetchCase(caseId),
```
new_string is these three lines (the first is the old line):
```tsx
    queryFn: () => fetchCase(caseId),
    // An execution ends on the server without anyone asking this page (N08).
    refetchInterval: (query) => caseRefetchMs(query.state.data?.state),
```

DONE WHEN: only these three files changed; operations.ts gained one function; operations.test.ts gained one import word and one describe; page.tsx gained one import word and two lines.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if an old_string line is not found exactly once.
``````
<!-- TASK_END -->

<!-- TASK_START: VMYPY -->
## Meta
- title: Raw mypy result for src/vf_logistics (the count VFULL parses looks too low)
- verify_only: true
- test_commands:
  - python -c "import subprocess; o=subprocess.run('python -m mypy src/vf_logistics/ --ignore-missing-imports --python-version 3.13', shell=True, capture_output=True, text=True); l=(o.stdout or '').splitlines(); print('exit', o.returncode); print('lines', len(l)); print(chr(10).join(l[-6:])); print('stderr:', (o.stderr or '')[-400:])"
- timeout_sec: 600

## Context
VFULL printed "mypy errors 1" while the baseline in CLAUDE.md section 7 is 122. This task prints the exit code, the number of output lines and the last lines of mypy, so the log shows whether mypy checked everything or stopped early.
<!-- TASK_END -->

<!-- TASK_START: VR1 -->
## Meta
- title: The review VI table checks the three backend fixes of the reverification (N06, N01)
- depends_on: []
- target_files:
  - scripts/verify_review_vi.py
- test_commands:
  - python -c "import ast; ast.parse(open('scripts/verify_review_vi.py', encoding='utf-8').read()); print('syntax ok')"
  - python scripts/verify_review_vi.py
- timeout_sec: 1500
- max_retries: 1

## Context
Reverification of 2026-10-17: N06e, N01e1 and N01e2 fixed three findings, but the table printed by scripts/verify_review_vi.py had no row for them. This task adds three "py" rows to CHECKS (same shape as N06-b): one per fix, each naming the new test (a name prefix matches its parametrized cases too). The script runs the whole backend suite and always exits 0, so the second test command only produces the table in the log; the Master reads the three new rows there. The file already holds uncommitted edits of the human (rows N01-f, N03-c, N06-e): leave them as they are.
Master review (from the log): the table has three more rows, N06-f, N01-g and N01-h, each PASS; the percentage line counts them.

## Prompt
``````text
TASK VR1. Add three rows to the CHECKS list of scripts/verify_review_vi.py. One insertion, nothing else.

FILE YOU MAY EDIT (only this one): scripts/verify_review_vi.py. It uses Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given (leading spaces included). Never use a multi-line old_string. Never use Write on this file. Do not touch any existing row, any function or any import.

EDIT 1. old_string, ONE line (4 leading spaces; occurs once):
```python
    ("E01-a", "E01", "changing only the answer label changes the score, not the decision", "probe",
```
new_string is the three rows below, and then that same line again:
```python
    ("N06-f", "N06", "a country field that states one country, twice or beside an unstated entry, is compared with the declaration", "py",
     [("test_origin_inputs.py", "test_a_certificate_for_china_contradicts_a_vietnam_declaration"),
      ("test_origin_inputs.py", "test_an_invoice_for_china_goods_contradicts_however_the_field_is_written")]),
    ("N01-g", "N01", "a Google SDK deadline error is an unknown send result, not a failed one", "py",
     [("test_publish_dedupe.py", "test_an_sdk_deadline_error_is_unknown_not_failed")]),
    ("N01-h", "N01", "a publish the broker accepted keeps its message id when its record fails to save", "py",
     [("test_resume_after_publish.py", "test_the_message_id_is_kept_and_the_decision_is_sent_once")]),
    ("E01-a", "E01", "changing only the answer label changes the score, not the decision", "probe",
```

DONE WHEN: only this file changed, by the three rows above, placed directly above the E01-a row.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if the old_string line is not found exactly once.
``````
<!-- TASK_END -->

<!-- TASK_START: VR2 -->
## Meta
- title: The review VI table checks the two frontend fixes of the reverification (N08)
- depends_on:
  - VR1
- target_files:
  - scripts/verify_review_vi.py
- test_commands:
  - python -c "import ast; ast.parse(open('scripts/verify_review_vi.py', encoding='utf-8').read()); print('syntax ok')"
  - python scripts/verify_review_vi.py
- timeout_sec: 1500
- max_retries: 1

## Context
Reverification of 2026-10-17: N08g (the panel reloads the case after a lost connection) and N08h (the case page reads an EXECUTING case again every 15 seconds) have frontend tests, but the script's vitest call runs only ReviewPanel.test.tsx and route.test.ts, so the N08h test in src/lib/operations.test.ts would never be seen. This task adds that file to the vitest command and adds two "js" rows (same shape as N08-e) that look for the new test titles. A row whose title is not found is reported as NO TEST, not as a pass.
Master review (from the log): the table has two more rows, N08-f and N08-g, each PASS; none shows NO TEST.

## Prompt
``````text
TASK VR2. Two edits in scripts/verify_review_vi.py: the vitest command and two new rows. Nothing else.

FILE YOU MAY EDIT (only this one): scripts/verify_review_vi.py. It uses Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given (leading spaces included). Never use a multi-line old_string. Never use Write on this file. Do not touch any existing row, any function or any import.

EDIT 1 (the vitest command, so operations.test.ts is run too). old_string, ONE line (4 leading spaces; occurs once):
```python
    cmd = (f'npx vitest run src/components/review/ReviewPanel.test.tsx route.test.ts '
```
new_string, ONE line (only ` src/lib/operations.test.ts` is new, before the closing quote):
```python
    cmd = (f'npx vitest run src/components/review/ReviewPanel.test.tsx route.test.ts src/lib/operations.test.ts '
```

EDIT 2 (two rows). old_string, ONE line (4 leading spaces; occurs once):
```python
    ("E01-a", "E01", "changing only the answer label changes the score, not the decision", "probe",
```
new_string is the two rows below, and then that same line again:
```python
    ("N08-f", "N08", "after a lost connection on approve or execute the review panel reloads the case", "js",
     ["reloads the case when Release's execute step loses the connection",
      "reloads the case when Retry loses the connection",
      "does not reload for a refusal the server sent"]),
    ("N08-g", "N08", "the case page reads an EXECUTING case again every 15 seconds", "js",
     ["reads an executing case again every 15 seconds"]),
    ("E01-a", "E01", "changing only the answer label changes the score, not the decision", "probe",
```

DONE WHEN: only this file changed; the vitest command names a third test file; two rows sit directly above the E01-a row.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if an old_string line is not found exactly once.
``````
<!-- TASK_END -->

<!-- TASK_START: N08i -->
## Meta
- title: The review queue page reads an EXECUTING case again every 15 seconds (N08, frontend)
- depends_on: []
- target_files:
  - frontend/src/app/review/page.tsx
- test_commands:
  - [frontend] npx vitest run src/lib/operations.test.ts src/components/review/ReviewPanel.test.tsx
  - [frontend] npx tsc --noEmit
  - [frontend] npm run lint
- timeout_sec: 300
- max_retries: 1

## Context
Master check of commit 83826f6 against reverification VI, N08 part B. N08h made the CASE page (`cases/[id]/page.tsx`) read an EXECUTING case again every 15 seconds. The REVIEW page (`review/page.tsx`) renders the same ReviewPanel, which shows `detail ?? summary` (ReviewPanel.tsx line 244) and runs the same 15-second clock on the claim lease; its `detail` query (page.tsx lines 63-68) has no refetchInterval, so a case read once as EXECUTING that finishes on the server is shown as "Execution interrupted - claim expired" with a Resume button once the lease runs out. The reverification's criterion: a finished case is never shown as interrupted.
Fix: the same `caseRefetchMs` (frontend/src/lib/operations.ts, tested in operations.test.ts by N08h) as `refetchInterval` on the review page's detail query. Only the detail query: the panel reads `detail` first, and the queue's own refresh is not part of this finding.
No page test mounts the review page (it needs the tenant, identity and router providers); the rule itself is the tested pure function. Master review: read `git diff` (one import line, a comment and one option); the test commands prove nothing else broke.

## Prompt
``````text
TASK N08i. The review page reads an EXECUTING case again every 15 seconds. Two small edits in one file.

FILE YOU MAY EDIT (only this one): frontend/src/app/review/page.tsx. It uses Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given (leading spaces included). Never use a multi-line old_string. Never use Write on this file. `caseRefetchMs` already exists: it is exported from frontend/src/lib/operations.ts. Do not edit operations.ts.

EDIT 1 (import). old_string, ONE line (no leading spaces; occurs once):
```tsx
import { useTenant } from "@/lib/tenant-context";
```
new_string is these two lines (the second is the old line, kept):
```tsx
import { caseRefetchMs } from "@/lib/operations";
import { useTenant } from "@/lib/tenant-context";
```

EDIT 2 (the detail query). old_string, ONE line (4 leading spaces; occurs once):
```tsx
    enabled: selectedId !== null,
```
new_string is these three lines (the last is the old line, kept):
```tsx
    // The panel shows this document, and an execution ends on the server without anyone asking this page (N08).
    refetchInterval: (query) => caseRefetchMs(query.state.data?.state),
    enabled: selectedId !== null,
```
Change nothing else: not the queue query, not the invalidate function, not the JSX.

DONE WHEN: only frontend/src/app/review/page.tsx changed: one new import line, and one comment line plus one refetchInterval line in the detail query.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if an old_string line is not found exactly once.
``````
<!-- TASK_END -->

<!-- TASK_START: N08jt -->
## Meta
- title: Tests first - a 409 from execute (Resume, Execute, Release) reads the case again (N08, frontend)
- depends_on:
  - N08i
- target_files:
  - frontend/src/components/review/ReviewPanel.test.tsx
- test_commands:
  - [frontend] python -c "import subprocess,sys; r=subprocess.call('npx vitest run src/components/review/ReviewPanel.test.tsx', shell=True); print('vitest exit', r); sys.exit(0 if r == 1 else 1)"
- timeout_sec: 420
- max_retries: 1

## Context
Master check of commit 83826f6 against reverification VI, N08. The criterion asks to reload the case "khi ... Resume bị từ chối". Today a 409 from execute only shows the message: the page keeps the buttons of a state the server has left (Resume on a case whose execution finished, Execute on an approval already executed).
HUMAN DECISION (17/10/2026, in chat): the existing test "shows the backend's refusal when the claim is still live there" asserted `expect(onDecided).not.toHaveBeenCalled();`. The human asked for a reload on a refused Resume, so that ONE assertion becomes `toHaveBeenCalledTimes(1)`; the rest of the test (refusal shown, Resume not left disabled) stays. The N08g test "does not reload for a refusal the server sent" is about a 409 from APPROVE ("Re-evaluate first.") and stays: approve's refusal is an answer about the evaluation, not about a moved case.
This task writes the tests only. Expected on the old code: 3 failures (the changed Resume test, the Execute 409 test, the Release 409 test); the 403 test passes on both (it fences the change to 409 only). The test command passes when vitest exits 1.
Edit 1 uses a TWO-line old_string on purpose: the line `expect(onDecided).not.toHaveBeenCalled();` occurs twice in the file, so one line cannot be unique. The Master checked on 17/10/2026 that the Edit tool matches a two-line old_string on a CRLF file and keeps CRLF.
Master review: in the log, exactly the 3 named tests fail, every other test passes; `git diff` shows one changed assertion and three new tests.

## Prompt
``````text
TASK N08jt. Tests only: a 409 from execute reads the case again. One changed assertion and three new tests in ReviewPanel.test.tsx. Do not edit ReviewPanel.tsx: these tests are meant to fail until the next task.

FILE YOU MAY EDIT (only this one): frontend/src/components/review/ReviewPanel.test.tsx. It uses Windows line endings (CRLF). Use the Edit tool. Never use Write on this file. Do not change any mock or any other test. ApiError, executeApproval, renderPanel, makeCase, executing, inSeconds, fireEvent, screen and vi already exist in the file.

EDIT 1 (the existing test "shows the backend's refusal when the claim is still live there"). This is the ONLY edit with a TWO-line old_string (4 leading spaces on each line; the pair occurs once):
```tsx
    expect((await screen.findByRole("alert")).textContent).toContain(refusal);
    expect(onDecided).not.toHaveBeenCalled();
```
new_string, two lines (only `.not.toHaveBeenCalled()` becomes `.toHaveBeenCalledTimes(1)`):
```tsx
    expect((await screen.findByRole("alert")).textContent).toContain(refusal);
    expect(onDecided).toHaveBeenCalledTimes(1);
```
The lines after it in that test (the comment and the `disabled).toBe(false)` check) stay exactly as they are.

EDIT 2 (three new tests in the same describe, before its last test). old_string, ONE line (2 leading spaces; occurs once):
```tsx
  it("keeps Execute for an approved case, with no Resume beside it", () => {
```
new_string is the three tests below, a blank line, and then that same line again:
```tsx
  it("reads the case again when Execute is refused because the case has moved on", async () => {
    vi.mocked(executeApproval).mockRejectedValueOnce(
      new ApiError("Approval evapr-1 is not executable: case is RELEASED_BY_HUMAN, not APPROVED or EXECUTION_FAILED", 409, "http"),
    );
    const approval = { approval_id: "evapr-1", action: "release", approver: "r", evidence_version: 1, status: "VALID", at: "" };
    const onDecided = renderPanel(makeCase("APPROVED", { approvals: [approval] }));
    fireEvent.click(screen.getByRole("button", { name: "Execute" }));
    expect((await screen.findByRole("alert")).textContent).toContain("not executable");
    expect(onDecided).toHaveBeenCalledTimes(1);
  });

  it("reads the case again when Release's execute step is refused with 409", async () => {
    vi.mocked(executeApproval).mockRejectedValueOnce(
      new ApiError("Another execution of this approval is in progress.", 409, "http"),
    );
    const onDecided = renderPanel(makeCase("HELD_FOR_REVIEW"));
    fireEvent.click(screen.getByRole("button", { name: "Release" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    expect((await screen.findByRole("alert")).textContent).toContain("in progress");
    expect(onDecided).toHaveBeenCalledTimes(1);
  });

  it("does not read the case again when execute is refused for another reason than a moved case", async () => {
    vi.mocked(executeApproval).mockRejectedValueOnce(new ApiError("Releasing needs a password sign-in.", 403, "http"));
    const approval = { approval_id: "evapr-1", action: "release", approver: "r", evidence_version: 1, status: "VALID", at: "" };
    const onDecided = renderPanel(makeCase("APPROVED", { approvals: [approval] }));
    fireEvent.click(screen.getByRole("button", { name: "Execute" }));
    expect((await screen.findByRole("alert")).textContent).toContain("password sign-in");
    expect(onDecided).not.toHaveBeenCalled();
  });

  it("keeps Execute for an approved case, with no Resume beside it", () => {
```
(The line `  it("keeps Execute ...` at the end of new_string is the old line, kept.)

DONE WHEN: only ReviewPanel.test.tsx changed: one assertion changed in the "claim is still live there" test, three new tests before "keeps Execute for an approved case".
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if an old_string is not found exactly once.
``````
<!-- TASK_END -->

<!-- TASK_START: N08jc -->
## Meta
- title: Code for N08jt - a 409 from execute reads the case again, the refusal is still shown (N08, frontend)
- depends_on:
  - N08jt
- target_files:
  - frontend/src/components/review/ReviewPanel.tsx
- test_commands:
  - [frontend] npx vitest run src/components/review/ReviewPanel.test.tsx src/lib/operations.test.ts
  - [frontend] npx tsc --noEmit
  - [frontend] npm run lint
- timeout_sec: 420
- max_retries: 1

## Context
Code for the tests of N08jt. Execute answers 409 when the case is not in the state the page shows: another execution of the approval is still running, or it has finished (evidence.py line 1097: "case is {state}, not APPROVED or EXECUTION_FAILED"). Both executeApproval call sites (the verificationApprove mutation after a successful approve, line 376, and the verificationExecute mutation behind Execute / Retry / Resume, line 474) go through one helper that calls onDecided() on a 409 and rethrows, so onError still shows the refusal. A 409 from approveCase is not touched (the N08g test "does not reload for a refusal the server sent" stays green). A lost connection is still handled by the existing onSettled/outcomeUnknown (no double reload: a 409 has kind "http").
Edit order matters: the 8-space `return executeApproval(...)` line (approve path) is edited first; after it, the 6-space line in verificationExecute is unique (before, it is a substring of the 8-space line).
Master review: the N08jt tests pass, all other ReviewPanel tests pass, tsc and lint pass; `git diff` shows one helper and two call sites changed.

## Prompt
``````text
TASK N08jc. A 409 from execute reads the case again. Three edits in ReviewPanel.tsx, in this order: EDIT 1, EDIT 2, EDIT 3.

FILE YOU MAY EDIT (only this one): frontend/src/components/review/ReviewPanel.tsx. It uses Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given (leading spaces included). Never use a multi-line old_string. Never use Write on this file. Do not edit the test file. ApiError, executeApproval, c and onDecided already exist in this component. Do not change outcomeUnknown, any onSettled, onSuccess or onError block.

EDIT 1 (a helper inside the component, before the verification-loop mutations). old_string, ONE line (2 leading spaces; occurs once):
```tsx
  // N08: For cases in the verification loop, route decisions through the new API.
```
new_string is the helper below, a blank line, and then that same line again:
```tsx
  // Execute answers 409 when the case is no longer in the state this page shows: another
  // execution of the approval is still running, or it has finished (N08). The refusal is
  // still shown; the case is read again so the buttons match what the server holds.
  const executeReloadingOnConflict = async (approvalId: string) => {
    try {
      return await executeApproval(c.case_id, approvalId);
    } catch (error) {
      if (error instanceof ApiError && error.kind === "http" && error.status === 409) onDecided();
      throw error;
    }
  };

  // N08: For cases in the verification loop, route decisions through the new API.
```

EDIT 2 (approve path; do this BEFORE EDIT 3). old_string, ONE line (8 leading spaces; occurs once):
```tsx
        return executeApproval(c.case_id, approval.approval_id);
```
new_string, ONE line (8 leading spaces):
```tsx
        return executeReloadingOnConflict(approval.approval_id);
```

EDIT 3 (the verificationExecute mutation; after EDIT 2 this line occurs once). old_string, ONE line (6 leading spaces):
```tsx
      return executeApproval(c.case_id, approval.approval_id);
```
new_string, ONE line (6 leading spaces):
```tsx
      return executeReloadingOnConflict(approval.approval_id);
```
The line above it, `if (!approval) throw new Error("No valid approval to execute");`, stays.

DONE WHEN: only ReviewPanel.tsx changed: one new helper (EDIT 1) and two `return executeApproval(...)` lines now call executeReloadingOnConflict.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if an old_string line is not found exactly once at the moment of its edit.
``````
<!-- TASK_END -->

<!-- TASK_START: VR3 -->
## Meta
- title: The review VI table checks that a refused execute (409) reads the case again (N08)
- depends_on:
  - N08jc
- target_files:
  - scripts/verify_review_vi.py
- test_commands:
  - python -c "import ast; ast.parse(open('scripts/verify_review_vi.py', encoding='utf-8').read()); print('syntax ok')"
  - python scripts/verify_review_vi.py
- timeout_sec: 1500
- max_retries: 1

## Context
N08jt and N08jc made a 409 from execute read the case again. This task adds one "js" row for those tests, directly above the E01-a row, in the same shape as N08-f. A row whose title is not found is reported as FAIL ("test not found"), not as a pass. No row for N08i (the review page polls an EXECUTING case): no test mounts that page, and its rule (caseRefetchMs) is already the N08-g row.
Master review (from the log): the table has one more row, N08-h, PASS; none shows FAIL or NO TEST.

## Prompt
``````text
TASK VR3. One edit in scripts/verify_review_vi.py: one new row. Nothing else.

FILE YOU MAY EDIT (only this one): scripts/verify_review_vi.py. It uses Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given (leading spaces included). Never use a multi-line old_string. Never use Write on this file. Do not touch any existing row, any function or any import.

EDIT 1 (one row). old_string, ONE line (4 leading spaces; occurs once):
```python
    ("E01-a", "E01", "changing only the answer label changes the score, not the decision", "probe",
```
new_string is the row below, and then that same line again:
```python
    ("N08-h", "N08", "a refused execute (409) makes the review panel read the case again, other refusals do not", "js",
     ["shows the backend's refusal when the claim is still live there",
      "reads the case again when Execute is refused because the case has moved on",
      "reads the case again when Release's execute step is refused with 409",
      "does not read the case again when execute is refused for another reason"]),
    ("E01-a", "E01", "changing only the answer label changes the score, not the decision", "probe",
```

DONE WHEN: only this file changed; one row sits directly above the E01-a row.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if the old_string line is not found exactly once.
``````
<!-- TASK_END -->

<!-- TASK_START: N01mt -->
## Meta
- title: Tests first - a publish record that fails to save twice keeps the accepted message id (N01)
- depends_on:
  - N08jc
- target_files:
  - tests/test_resume_after_publish.py
- test_commands:
  - python -c "import subprocess,sys; r=subprocess.call('python -m pytest tests/test_resume_after_publish.py -q -p no:cacheprovider', shell=True); print('pytest exit', r); sys.exit(0 if r == 1 else 1)"
  - python -m ruff check tests/test_resume_after_publish.py --select E,F,W --ignore E501,E402,W291,W293
- timeout_sec: 420
- max_retries: 1

## Context
Open item of the reverification VI fix report: "if the second save also fails, the exception reaches the caller and the message id can be lost". In tools.publish_decision_direct, after the broker accepted, the success record fails to save, the except handler saves again (N01e2), and if THAT save fails too the exception leaves publish_decision; evidence.execute_approval catches it (evidence.py line 1268) as a failed send: EXECUTION_FAILED, send_failed, and Retry publishes the decision a second time although msg-1 was known.
This task writes the tests only (new class at the end of the file). Expected on the current code: test_the_execution_is_recorded_as_sent_with_the_message_id FAILS (state EXECUTION_FAILED); the fence test test_a_record_that_cannot_be_saved_for_a_message_that_never_went_out_still_raises PASSES on both (nothing went out, so the error must still reach the caller: fail closed). The test command passes when pytest exits 1.
Master review: in the log exactly the one named test fails, at the `result["state"]` assertion; every other test in the file passes.

## Prompt
``````text
TASK N01mt. Tests only: one new test class at the END of tests/test_resume_after_publish.py. Do not edit any source file: the first test is meant to fail until the next task.

FILE YOU MAY EDIT (only this one): tests/test_resume_after_publish.py. It uses Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given (leading spaces included). Never use a multi-line old_string. Never use Write on this file. Do not change any existing test. asyncio, os, time, patch, pytest, Base, _fake_pubsub, _with_pubsub, evidence, tools, REVIEWER and run already exist in this file.

EDIT 1 (add at the END of the file, never at the top). old_string, ONE line (8 leading spaces; it is the last line of the file and occurs once):
```python
        assert [(r["status"], r["detail"]["message_id"]) for r in rows] == [("done", "msg-1")]
```
new_string is that same line first, then two blank lines, then the class below:
```python
        assert [(r["status"], r["detail"]["message_id"]) for r in rows] == [("done", "msg-1")]


class TestARecordThatFailsToSaveTwiceAfterTheBrokerAccepted(Base):
    def test_the_execution_is_recorded_as_sent_with_the_message_id(self):
        self.put()
        self.request_and_submit()
        run(evidence.reevaluate("CASE-1"))
        approval_id = run(evidence.approve(
            "CASE-1", "release", REVIEWER, note="Reviewed", actor_auth="password",
        ))["approval"]["approval_id"]
        pubsub, published = _fake_pubsub(["msg-1", "msg-2"])
        real_audit = tools._audit

        async def store_down_for_publish(case_id, action, detail, status="done", tenant_id=None):
            # Both saves of the publish record fail; the broker has the message (N01).
            if action == "publish_decision":
                raise RuntimeError("ServiceUnavailable: the store did not answer")
            return await real_audit(case_id, action, detail, status, tenant_id)

        with patch.dict(os.environ, {"PROJECT_ID": "test-project"}), _with_pubsub(pubsub), \
                patch("vf_logistics.tools._audit", new=store_down_for_publish):
            result = run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))

        assert result["state"] == "RELEASED_BY_HUMAN"
        assert result["message_id"] == "msg-1"
        assert len(published) == 1
        stored = self.stored()
        assert [e["status"] for e in stored["verification"]["executions"]] == ["sent"]
        assert stored["verification"]["executions"][0]["message_id"] == "msg-1"

    def test_a_record_that_cannot_be_saved_for_a_message_that_never_went_out_still_raises(self):
        # Nothing went out, so there is no message id to hand back: the error goes on and
        # the caller records a failed send.
        class ServiceUnavailable(Exception):
            pass

        pubsub, _ = _fake_pubsub([ServiceUnavailable("503 Service Unavailable")])

        async def store_down(*args, **kwargs):
            raise RuntimeError("the store did not answer")

        with patch.dict(os.environ, {"PROJECT_ID": "test-project"}), _with_pubsub(pubsub), \
                patch("vf_logistics.tools._audit", new=store_down), \
                pytest.raises(RuntimeError, match="store did not answer"):
            run(tools.publish_decision("CASE-1", {"outcome": "RELEASED_BY_HUMAN", "idempotency_key": "exec-apr-9"}))
```

DONE WHEN: only this file changed; the old last line is kept and the new class follows it at the end of the file.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if the old_string line is not found exactly once.
``````
<!-- TASK_END -->

<!-- TASK_START: N01mc -->
## Meta
- title: Code for N01mt - an accepted message's receipt is handed back when its record cannot be saved (N01)
- depends_on:
  - N01mt
- target_files:
  - src/vf_logistics/tools.py
- test_commands:
  - python -m pytest tests/test_resume_after_publish.py tests/test_publish_dedupe.py tests/test_evidence_execution.py -q -p no:cacheprovider
  - python -m ruff check src/vf_logistics/tools.py --select E,F,W --ignore E501,E402,W291,W293
- timeout_sec: 600
- max_retries: 1

## Context
Code for the tests of N01mt. A new helper `_save_publish_record` saves the publish record through `_audit`; when the store refuses it AND the broker accepted the message, it returns the receipt unsaved (same shape as an `_audit` entry, without audit_id) instead of raising, so evidence.published_message_id reads msg-1 and the execution is recorded as sent. Without an accepted message it raises as before (fail closed: nothing went out). The except handler of publish_decision_direct calls the helper instead of `_audit` and passes `accepted=bool(accepted)`; `accepted` is keyword-only with no default, so no caller can forget it.
Edit 2 uses a TWO-line old_string on purpose: `        return await _audit(` occurs many times in tools.py, so only the pair with the line above it is unique. The Edit tool matches a two-line old_string on a CRLF file (N08jt did the same and passed).
Master review: the N01mt tests pass, test_publish_dedupe.py and test_evidence_execution.py stay green, ruff passes; `git diff` shows one helper, one renamed call and one added keyword.

## Prompt
``````text
TASK N01mc. Three edits in src/vf_logistics/tools.py, in this order. Nothing else.

FILE YOU MAY EDIT (only this one): src/vf_logistics/tools.py. It uses Windows line endings (CRLF). Use the Edit tool. Never use Write on this file. Do not edit any test. Do not touch `_audit`, `_may_have_been_accepted`, `publish_decision`, `_earlier_publish` or the `try:` part of publish_decision_direct. `_audit`, `utcnow` and `Any` already exist in this module.

EDIT 1 (a new helper, directly above publish_decision_direct). old_string, ONE line (no leading spaces; occurs once):
```python
async def publish_decision_direct(
```
new_string is the helper below, two blank lines, and then that same line again:
```python
async def _save_publish_record(
    case_id: str, action: str, detail: dict[str, Any], status: str = "done",
    tenant_id: str | None = None, *, accepted: bool,
) -> dict[str, Any]:
    """
    Save the record of a publish; for a message the broker accepted, hand the receipt
    back unsaved when the store refuses it.

    Raising there turned a sent message into "nothing was sent": the execution failed and
    the retry published the decision a second time although its message id was known (N01).
    Without an accepted message the error goes on, and the caller records a failed send.
    """
    try:
        return await _audit(case_id, action, detail, status=status, tenant_id=tenant_id)
    except Exception:  # noqa: BLE001
        if not accepted:
            raise
        return {"case_id": case_id, "action": action, "status": status, "detail": detail, "at": utcnow()}


async def publish_decision_direct(
```

EDIT 2 (the except handler calls the helper). This is the ONLY edit with a TWO-line old_string (the first line has 4 leading spaces, the second 8; the pair occurs once):
```python
    except Exception as exc:  # noqa: BLE001
        return await _audit(
```
new_string, two lines (only `_audit` becomes `_save_publish_record`):
```python
    except Exception as exc:  # noqa: BLE001
        return await _save_publish_record(
```

EDIT 3 (pass accepted). old_string, ONE line (12 leading spaces; occurs once):
```python
            status="done" if accepted else ("unknown" if _may_have_been_accepted(exc) else "failed"),
```
new_string is these two lines (the first is the old line, kept):
```python
            status="done" if accepted else ("unknown" if _may_have_been_accepted(exc) else "failed"),
            accepted=bool(accepted),
```
The lines around it (the three comment lines above and `tenant_id=tenant_id,` below) stay as they are.

DONE WHEN: only tools.py changed: one new function above publish_decision_direct, `_audit` renamed to `_save_publish_record` in the except handler only, and one `accepted=bool(accepted),` line.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if an old_string is not found exactly once.
``````
<!-- TASK_END -->

<!-- TASK_START: N01kt -->
## Meta
- title: Tests first - a cancellation around the publish leaves a record a Resume can read (N01)
- depends_on:
  - N01mc
- target_files:
  - tests/test_resume_after_publish.py
- test_commands:
  - python -c "import subprocess,sys; r=subprocess.call('python -m pytest tests/test_resume_after_publish.py -q -p no:cacheprovider', shell=True); print('pytest exit', r); sys.exit(0 if r == 1 else 1)"
  - python -m ruff check tests/test_resume_after_publish.py --select E,F,W --ignore E501,E402,W291,W293
- timeout_sec: 420
- max_retries: 1

## Context
Reverification VI, N01, case reproduced by the reviewer: after the broker accepted, the task is interrupted with CancelledError before the publish record is saved; the case stays EXECUTING/claiming with no record, and a Resume after the lease publishes a second time. `except Exception` in publish_decision_direct does not catch CancelledError (a BaseException), so nothing is saved.
Three tests in a new class at the end of the file:
1. cancelled while saving after the broker accepted: a record ("done", msg-1) exists, and the Resume after the lease does not publish again. FAILS on the current code (no record).
2. cancelled while waiting for the broker (asyncio.to_thread replaced by a coroutine that raises CancelledError): an "unknown" record with the idempotency key exists. FAILS on the current code.
3. same as 2 with the store down too: the caller still gets CancelledError, not the store's error. PASSES on both (a fence for the next task).
The test command passes when pytest exits 1. Patching `asyncio.to_thread` is safe here: MemoryStore (the tests' store) does not use it.
Master review: in the log exactly tests 1 and 2 fail, every other test passes (including the N01mt class).

## Prompt
``````text
TASK N01kt. Tests only: one new test class at the END of tests/test_resume_after_publish.py. Do not edit any source file: two of these tests are meant to fail until the next task.

FILE YOU MAY EDIT (only this one): tests/test_resume_after_publish.py. It uses Windows line endings (CRLF). Use the Edit tool with a ONE-LINE old_string, exactly as given (leading spaces included). Never use a multi-line old_string. Never use Write on this file. Do not change any existing test. asyncio, os, time, patch, pytest, Base, _fake_pubsub, _with_pubsub, evidence, tools, REVIEWER and run already exist in this file.

EDIT 1 (add at the END of the file, never at the top). old_string, ONE line (12 leading spaces; it is the last line of the file and occurs once):
```python
            run(tools.publish_decision("CASE-1", {"outcome": "RELEASED_BY_HUMAN", "idempotency_key": "exec-apr-9"}))
```
new_string is that same line first, then two blank lines, then the class below:
```python
            run(tools.publish_decision("CASE-1", {"outcome": "RELEASED_BY_HUMAN", "idempotency_key": "exec-apr-9"}))


class TestACancellationAroundThePublish(Base):
    def test_a_cancellation_after_the_broker_accepted_keeps_the_message_id_for_the_resume(self):
        self.put()
        self.request_and_submit()
        run(evidence.reevaluate("CASE-1"))
        approval_id = run(evidence.approve(
            "CASE-1", "release", REVIEWER, note="Reviewed", actor_auth="password",
        ))["approval"]["approval_id"]
        pubsub, published = _fake_pubsub(["msg-1", "msg-2"])
        real_audit = tools._audit
        cancelled: list[str] = []

        async def cancelled_while_saving(case_id, action, detail, status="done", tenant_id=None):
            # The task is cancelled while it saves the publish record, after the broker accepted.
            if action == "publish_decision" and not cancelled:
                cancelled.append(action)
                raise asyncio.CancelledError
            return await real_audit(case_id, action, detail, status, tenant_id)

        env = {"PROJECT_ID": "test-project"}
        with patch.dict(os.environ, env), _with_pubsub(pubsub), \
                patch("vf_logistics.tools._audit", new=cancelled_while_saving), \
                pytest.raises(asyncio.CancelledError):
            run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        assert len(published) == 1
        assert self.stored()["state"] == "EXECUTING"
        rows = [r for r in run(self.store.list_audit(limit=500)) if r.get("action") == "publish_decision"]
        assert [(r["status"], r["detail"]["message_id"]) for r in rows] == [("done", "msg-1")]

        case = self.stored()
        case["verification"]["executions"][0]["claim_expires_epoch"] = time.time() - 1
        run(self.store.put_case(case))

        with patch.dict(os.environ, env), _with_pubsub(pubsub):
            result = run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        assert result["state"] == "RELEASED_BY_HUMAN"
        assert result["message_id"] == "msg-1"
        assert len(published) == 1

    def test_a_cancellation_before_the_broker_answered_is_recorded_as_unknown(self):
        pubsub, _ = _fake_pubsub(["msg-1"])

        async def cancelled_while_waiting(*args, **kwargs):
            raise asyncio.CancelledError

        with patch.dict(os.environ, {"PROJECT_ID": "test-project"}), _with_pubsub(pubsub), \
                patch("asyncio.to_thread", new=cancelled_while_waiting), \
                pytest.raises(asyncio.CancelledError):
            run(tools.publish_decision("CASE-1", {"outcome": "RELEASED_BY_HUMAN", "idempotency_key": "exec-apr-7"}))
        rows = [r for r in run(self.store.list_audit(limit=500)) if r.get("action") == "publish_decision"]
        assert [r["status"] for r in rows] == ["unknown"]
        assert rows[0]["detail"]["error"].startswith("CancelledError")
        assert rows[0]["detail"]["idempotency_key"] == "exec-apr-7"

    def test_the_cancellation_still_reaches_the_caller_when_the_store_is_down_too(self):
        pubsub, _ = _fake_pubsub(["msg-1"])

        async def cancelled_while_waiting(*args, **kwargs):
            raise asyncio.CancelledError

        async def store_down(*args, **kwargs):
            raise RuntimeError("the store did not answer")

        with patch.dict(os.environ, {"PROJECT_ID": "test-project"}), _with_pubsub(pubsub), \
                patch("asyncio.to_thread", new=cancelled_while_waiting), \
                patch("vf_logistics.tools._audit", new=store_down), \
                pytest.raises(asyncio.CancelledError):
            run(tools.publish_decision("CASE-1", {"outcome": "RELEASED_BY_HUMAN", "idempotency_key": "exec-apr-6"}))
```

DONE WHEN: only this file changed; the old last line is kept and the new class follows it at the end of the file.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if the old_string line is not found exactly once.
``````
<!-- TASK_END -->

<!-- TASK_START: N01kc -->
## Meta
- title: Code for N01kt - a cancelled publish saves its record shielded, then the cancellation goes on (N01)
- depends_on:
  - N01kt
- target_files:
  - src/vf_logistics/tools.py
- test_commands:
  - python -m pytest tests/test_resume_after_publish.py tests/test_publish_dedupe.py tests/test_evidence_execution.py -q -p no:cacheprovider
  - python -m ruff check src/vf_logistics/tools.py --select E,F,W --ignore E501,E402,W291,W293
- timeout_sec: 600
- max_retries: 1

## Context
Code for the tests of N01kt. A new `except asyncio.CancelledError` clause, placed BEFORE `except Exception` in publish_decision_direct, saves the publish record through `_save_publish_record` (N01mc) inside `asyncio.shield`, so a second cancellation cannot stop the save: "done" with the message id when the broker had accepted, "unknown" otherwise (like a timeout; a retry reuses the same idempotency key). Then it re-raises: the cancellation is never swallowed. If that save fails (only possible without an accepted message, since the helper hands an accepted receipt back), the store's error is dropped so the caller still sees CancelledError (test 3 of N01kt).
`asyncio` is the function-local `import asyncio` at the top of the try block; it is bound before any await, so the except clause can name it. Leave that import where it is.
Not covered and stays in block 3 of the report: a process killed outright (SIGKILL, out of memory) between the broker's accept and the save runs no handler at all.
Round 1 (RERUN): the first prompt anchored on `    except Exception as exc:  # noqa: BLE001` alone, which is also a prefix of the handler at line 166, so the Edit tool found two matches; both attempts widened the anchor and dropped the `return await _save_publish_record(` line (IndentationError, runs/N01kc/attempt_1.log, attempt_2.log). The anchor is now the unique two-line pair.
Master review: all N01kt and N01mt tests pass, the neighbouring suites stay green, ruff passes; `git diff` shows one new except clause and nothing else.

## Prompt
``````text
TASK N01kc. One insertion in src/vf_logistics/tools.py. Nothing else.

FILE YOU MAY EDIT (only this one): src/vf_logistics/tools.py. It uses Windows line endings (CRLF). Use the Edit tool. Never use Write on this file. Do not edit any test. Do not touch the `import asyncio` line, `_save_publish_record`, `_audit` or the existing `except Exception` handler. `_save_publish_record`, `body`, `accepted`, `case_id` and `tenant_id` already exist in this function.

EDIT 1 (a new except clause, directly above the existing one). This edit uses a TWO-line old_string on purpose: the first line alone also matches another handler in this file ("... BLE001 - a failed alert must not kill the case"). old_string, these TWO lines (the first has 4 leading spaces, the second 8; the pair occurs once):
```python
    except Exception as exc:  # noqa: BLE001
        return await _save_publish_record(
```
new_string is the clause below, and then those SAME TWO lines again, unchanged:
```python
    except asyncio.CancelledError as exc:
        # Cancelled while the broker was taking the message, or after it had (N01). The
        # record is saved shielded from the cancellation, so a Resume after the lease finds
        # the message id (or an unknown outcome) instead of reading "nothing was sent".
        try:
            await asyncio.shield(_save_publish_record(
                case_id, "publish_decision",
                {**body, **accepted, "error": f"{type(exc).__name__}: {exc}"},
                status="done" if accepted else "unknown",
                tenant_id=tenant_id, accepted=bool(accepted),
            ))
        except Exception:  # noqa: BLE001
            # Only possible without an accepted message (nothing went out): the store's
            # error must not replace the cancellation the caller is waiting for.
            pass
        raise
    except Exception as exc:  # noqa: BLE001
        return await _save_publish_record(
```
(The last two lines of new_string are the two old lines, kept: after the edit `        return await _save_publish_record(` must still directly follow `    except Exception as exc:  # noqa: BLE001`. Indentation: `except` 4 spaces, its body 8, the inner `try` body 12, the call arguments 16.)

DONE WHEN: only tools.py changed: one new `except asyncio.CancelledError` clause directly above `except Exception as exc:  # noqa: BLE001`.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if the old_string line is not found exactly once.
``````
<!-- TASK_END -->

<!-- TASK_START: N08kt -->
## Meta
- title: Test for the review page - an EXECUTING case is read again every 15 seconds and the polling stops when it ends (N08)
- depends_on: []
- target_files:
  - frontend/src/app/review/page.test.tsx
- test_commands:
  - [frontend] npx vitest run src/app/review/page.test.tsx
  - [frontend] npx tsc --noEmit
  - [frontend] npm run lint
- timeout_sec: 420
- max_retries: 1

## Context
Open item of the fix report: "no test mounts the /review page; the 15-second reload was confirmed only by the tested rule (caseRefetchMs) and the diff". N08i already added `refetchInterval` to the page's detail query, so this test is expected to PASS here; its red proof against the page before N08i is task N08kv.
The test mounts the real ReviewQueuePage with a real QueryClient and fake timers. Mocked: the API (queue empty, fetchCase answers EXECUTING then RELEASED_BY_HUMAN), the tenant hook, the ?case= listener (opens CASE-1), ReviewPanel (a stub that prints the state the page hands it; the panel has its own tests) and HelpDot. Template: src/app/evaluation/page.test.tsx (vi.mock with importOriginal, then import the page).
Master review: the log shows 1 passing test in page.test.tsx; tsc and lint pass.

## Prompt
``````text
TASK N08kt. Create ONE new file: frontend/src/app/review/page.test.tsx, with exactly the content below. Nothing else.

FILE YOU MAY CREATE (only this one): frontend/src/app/review/page.test.tsx. It does not exist yet: create it with the Write tool. Do not edit page.tsx or any other file.

Content (copy exactly):
```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  fetchReviewQueue: vi.fn(async () => ({ items: [], next_cursor: null })),
  fetchCase: vi.fn(),
}));
vi.mock("@/lib/tenant-context", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/tenant-context")>()),
  useTenant: () => ({ tenant: { id: "tenant-a" } }),
}));
vi.mock("@/lib/url-state", async (importOriginal) => {
  const { useEffect } = await import("react");
  return {
    ...(await importOriginal<typeof import("@/lib/url-state")>()),
    // The page is opened on ?case=CASE-1.
    CaseParamListener: ({ onChange }: { onChange: (caseId: string | null) => void }) => {
      useEffect(() => onChange("CASE-1"), [onChange]);
      return null;
    },
    writeCaseParam: vi.fn(),
  };
});
// The panel has its own tests; here it only shows which state the page handed it.
vi.mock("@/components/review/ReviewPanel", () => ({
  ReviewPanel: ({ detail }: { detail?: { state: string } }) => <p data-testid="panel-state">{detail?.state ?? "none"}</p>,
}));
vi.mock("@/components/help/HelpDot", () => ({ HelpDot: () => null }));

import { fetchCase } from "@/lib/api";

import ReviewQueuePage from "./page";

/**
 * N08: the review page shows the case a link opened. An execution ends on the server
 * without anyone asking the page, so while the case is EXECUTING the page reads it again
 * every 15 seconds; once it has finished, the polling stops.
 */
describe("Review page: an executing case is read again (N08)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => vi.useRealTimers());

  it("reads an executing case again after 15 seconds and stops once it has finished", async () => {
    vi.mocked(fetchCase)
      .mockResolvedValueOnce({ case_id: "CASE-1", state: "EXECUTING" } as never)
      .mockResolvedValue({ case_id: "CASE-1", state: "RELEASED_BY_HUMAN" } as never);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ReviewQueuePage />
      </QueryClientProvider>,
    );
    expect((await screen.findByTestId("panel-state")).textContent).toBe("EXECUTING");
    expect(fetchCase).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    expect(fetchCase).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(screen.getByTestId("panel-state").textContent).toBe("RELEASED_BY_HUMAN"));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(fetchCase).toHaveBeenCalledTimes(2);
  });
});
```

DONE WHEN: the new file exists with exactly this content and no other file changed.
STOP AND REPLY WITHOUT WRITING (at most 3 lines) if frontend/src/app/review/page.test.tsx already exists.
``````
<!-- TASK_END -->

<!-- TASK_START: N08kv -->
## Meta
- title: verify_only - the review page test fails on the page before N08i (red proof)
- verify_only: true
- depends_on:
  - N08kt
- test_commands:
  - python -c "import subprocess as s, tarfile, io, os, shutil, sys, _winapi; d='orchestrator/runs/N08kv/old'; j=d+'/frontend/node_modules'; os.path.isdir(j) and os.rmdir(j); shutil.rmtree(d, ignore_errors=True); os.makedirs(d); tarfile.open(fileobj=io.BytesIO(s.check_output(['git','archive','3420388~1','frontend'])), mode='r:').extractall(d, filter='data'); _winapi.CreateJunction(os.path.abspath('frontend/node_modules'), os.path.abspath(j)); shutil.copy('frontend/src/app/review/page.test.tsx', d+'/frontend/src/app/review/page.test.tsx'); r=s.call('npx vitest run src/app/review/page.test.tsx', shell=True, cwd=d+'/frontend'); os.rmdir(j); print('vitest exit on the page before N08i', r); sys.exit(0 if r == 1 else 1)"
- timeout_sec: 600

## Context
Red proof for N08kt without touching the working tree. The command extracts `frontend/` as it was at 3420388~1 (cfd18f8: before N08i, so the review page has no refetchInterval) into orchestrator/runs/N08kv/old with `git archive` (reads git, writes only under orchestrator/runs/), links the real frontend/node_modules into it with a directory junction, copies the new page.test.tsx in, runs it there, removes the junction (os.rmdir removes the link, never the target), and passes only when vitest exits 1.
Master review: the log shows the test failing at `expect(fetchCase).toHaveBeenCalledTimes(2)` with "called 1 times"; any other failure (module not found, fs access) means the proof did not run: report "red not verified" for N08kt rather than claiming it.
<!-- TASK_END -->

<!-- TASK_START: N01mcf1 -->
## Meta
- title: Fix round 1 of N01mc - remove the blank line inserted inside the signature of publish_decision_direct
- depends_on:
  - N01mc
- target_files:
  - src/vf_logistics/tools.py
- test_commands:
  - python -c "l=open('src/vf_logistics/tools.py',encoding='utf-8').read().splitlines(); i=l.index('async def publish_decision_direct('); print(repr(l[i+1])); raise SystemExit(0 if l[i+1].startswith('    case_id: str') else 1)"
  - python -m pytest tests/test_resume_after_publish.py tests/test_publish_dedupe.py tests/test_evidence_execution.py -q -p no:cacheprovider
  - python -m ruff check src/vf_logistics/tools.py --select E,F,W --ignore E501,E402,W291,W293
- timeout_sec: 300
- max_retries: 1

## Context
N01mc passed (40 tests, ruff clean) but its EDIT 1 left an empty line between `async def publish_decision_direct(` and its first parameter line (runs/N01mc/attempt_1.diff). Valid Python, but a stray change in a reviewed diff. This task removes only that empty line.
Master review: the first test command prints `'    case_id: str, ...'`; `git diff src/vf_logistics/tools.py` no longer shows the blank line.

## Prompt
``````text
TASK N01mcf1. Remove ONE empty line in src/vf_logistics/tools.py. Nothing else.

FILE YOU MAY EDIT (only this one): src/vf_logistics/tools.py. It uses Windows line endings (CRLF). Use the Edit tool. Never use Write on this file.

Today the file has these three lines (the middle one is empty):
```python
async def publish_decision_direct(

    case_id: str, body: dict[str, Any], tenant_id: str | None = None,
```
EDIT 1. old_string is those THREE lines exactly (first line no leading spaces, second line empty, third line 4 leading spaces). new_string is the same without the empty line:
```python
async def publish_decision_direct(
    case_id: str, body: dict[str, Any], tenant_id: str | None = None,
```

DONE WHEN: `async def publish_decision_direct(` is directly followed by its `case_id: str, ...` line, and nothing else in the file changed.
STOP AND REPLY WITHOUT EDITING (at most 3 lines) if the three lines are not found exactly once.
``````
<!-- TASK_END -->
