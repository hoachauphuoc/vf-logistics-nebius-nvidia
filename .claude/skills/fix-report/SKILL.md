---
name: fix-report
description: Write the remediation report (対応状況報告, báo cáo khắc phục) that answers an independent review or reverification of Floorline, as a 2-page A4 PDF in Japanese and Vietnamese. Use when the user asks for a report on what was fixed after a review, for the fix status to send to the reviewer, or for a PDF in the format of Floorline_Independent_Review_VI_指摘対応.
---

# fix-report: what was fixed, what was not, and what proves it

Reply to the user in Vietnamese, in the fewest lines that are complete. The report is a document the reviewer will check line by line against the code, so every claim must have evidence the reviewer can reproduce. A report that overstates costs more than one that admits a gap (the reviewer already caught a "27 checks" figure that did not match the script).

## Format (do not change; it matches the reviewer's own sample)

A4, 2 pages, three blocks in this order:

1. **Summary** (要約 / Tóm tắt): one paragraph. What the review found, what was fixed in the repository, what was verified (test counts, check table), where the work sits (branch, commits) and the status words push / PR / deploy / CI, then a pointer to the last table.
2. **Per-item table** (指摘項目ごとの対応表): columns ID, result, one-to-two-sentence fix. One row per review item, in the review's order. Items the review already confirmed: "confirmed by the reviewer, unchanged this time".
3. **Not fixed or not verified** (修正できていない点とその理由): columns item, state, reason. The reason says WHY (outside the repository, not done, not measurable here) and what would close it.

Below the last table, one short "correction of figures" paragraph when a number from an earlier report was wrong. Result words: fixed / fixed (except X) / partial / not verified / not done. Never "complete" for a whole item that has a row in block 3.

## Evidence rules (what may be written)

- Test counts, mypy count, check-table totals: copy from the runner's logs (`orchestrator/runs/VFULL/attempt_N.log`, `orchestrator/runs/verify_review_vi.md` or the last `verify_only` log). Never from memory, never rounded. Name the table's counted and not-counted items.
- "Fails on the old code, passes on the new": only when a log shows the red run (a tests-first task such as `<ID>t`, or a `verify_only` run on the old commit). Otherwise write that the red run was not measured. Say which tasks have it and which do not.
- Status of push, PR, deploy, CI: ask the human or read a `verify_only` log (`git status`, `git log`, `PDCI`). The Master does not guess. Fixes that are not pushed have no CI result: say so. Deploying is the human's step.
- Never claim production behaviour, receiver-side behaviour, real browser, real Firestore/Pub/Sub, model accuracy or cost unless a log of that run exists. These always go to block 3 as "not done" when not run.
- Do not hide a fix the review asked for but the code only half does; put the remaining part in block 3 with the reviewer's own wording of the gap.
- Dates and commit ids: from the plan's order table and the human's commit messages. Business rules (risk floor, fail closed, guest cannot release) are never described as changed unless they were; say "the risk floor is not lowered" only when the diff shows it.

## Steps

1. **Gather** (read only): the review PDF or its text, `orchestrator/execution_plan.md` order table and round lines, `orchestrator/runs/report.md`, the `verify_only` logs above, and the existing fix report under `orchestrator/` if one exists. List per review item: fixed by which task, what proves it, what is still open.
2. **Write the content file** `orchestrator/reports/<review id>/content_ja.json`. Schema (a complete worked example is `examples/ja.json`; Vietnamese is `examples/vi.json`):
   ```json
   {"lang": "ja", "title": "...", "date": "YYYY-MM-DD", "blocks": [
     {"type": "h2", "text": "..."},
     {"type": "p", "text": "... <b>bold</b> allowed ..."},
     {"type": "table", "columns": ["ID", "...", "..."], "rows": [["N01 ...", "...", "..."]], "widths": [0.27, 0.17, 0.56]}
   ]}
   ```
   Japanese is the primary language when the reviewer's sample is Japanese. Text in cells is plain; `<b>` and `<br/>` are the only markup. Quote JSON strings with `\"`.
3. **Translate** to `content_vi.json` with the same blocks and numbers (change `lang` to `vi`). Same facts, same counts, same gaps; no row added or dropped in one language only.
4. **Render** (the one command this skill runs; it reads only the JSON and writes the PDF, it produces no evidence):
   ```
   python .claude/skills/fix-report/make_report.py orchestrator/reports/<id>/content_ja.json "orchestrator/Floorline_Independent_Reverification_<N>_指摘対応<YYYYMMDD>.pdf"
   python .claude/skills/fix-report/make_report.py orchestrator/reports/<id>/content_vi.json "orchestrator/Floorline_Independent_Reverification_<N>_Bao_cao_khac_phuc_<YYYYMMDD>.pdf"
   ```
   Needs reportlab and a system font (Yu Gothic or another CJK font for ja; Arial or similar for vi). If the script exits with "no usable font", tell the human which font to install; do not substitute a font that lacks the glyphs.
5. **Check** each PDF: 2 pages (3 only if a table does not fit, then cut words, not rows), render page images with PyMuPDF (`import pymupdf; page.get_pixmap(dpi=80).save(...)`) and look at them: no cut-off text, no empty squares, bold works, tables fit the margins.
6. **Deliver**: send both PDFs to the user, list in three lines the claims they should re-read before sending (anything about push/PR/CI, any "measured" claim, any figure that changed since the last report). Do not commit the PDFs and do not send them anywhere: sending the report to the reviewer is the human's step.

## When facts change after the report

A push, a merge or a new CI result changes the status sentence in the summary and the CI row in block 3. Edit the content files (never the PDF), render again and say which sentences changed.

## Do not

- Do not copy sentences from the reviewer's PDF as if they were findings of ours.
- Do not shorten block 3 to make the report look finished; a report with an honest long block 3 is the format working.
- Do not put secrets, `.env` values, tokens or customer data in a report.
- Do not add sections, logos, charts or a changed layout: the reviewer's sample is the format.
