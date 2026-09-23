# Demo video script — 3:00 hard limit

Everything below is grounded in the deployed console and the 20-case seeded board as it
stands. Case ids, scores and on-screen strings are real: they were read off the live
service, not invented for the script. If a number here does not match what you see,
re-seed with `python scripts/seed_full_board.py --yes` and check again before recording.

## Setup

- **Record the CONSOLE, not the API:** https://vf-console-f7rcctz26a-as.a.run.app
- 1920x1080, browser at 100% zoom, **signed out** for scenes 1-5
- Warm both services first — Cloud Run cold start is 10-20s and will ruin a take:
  open `https://vf-logistics-f7rcctz26a-as.a.run.app/health`, then the console root
- Close devtools. The board polls a large state payload every 1-2s and an open Network
  tab is the noisiest thing on screen
- Have `judge@vf-logistics.demo` and its password ready for scene 6 only

Budget: six scenes, 30 seconds each. Overrun on scene 3 is the usual failure; it is the
one to rehearse.

---

## Scene 1 — the problem, and the actual claim (0:00-0:30)

**Screen:** Pipeline board at `/`. Do not log in.

> Trade compliance teams clear shipments under time pressure: under-invoicing, shell
> companies, sanctions evasion. A model can spot those patterns. The question nobody
> answers is what happens when the model is wrong.
>
> This is VF Logistics. Twenty shipments, screened by seven agents on NVIDIA Nemotron
> models running on Nebius Token Factory. Everything you are about to see is readable
> without an account.

**Point at:** the six columns. Eleven cases escalated, two blocked by a person, two
released by a person, two cleared automatically. The spread is the point — this is not a
demo where everything is suspicious.

---

## Scene 2 — the deterministic floor (0:30-1:00)

**Screen:** search `FULL-07-BLACKTAX` in the board search box, open the case.

**Read from the Verdict block:**

> Here the model scored this shipment 55. A deterministic rule set scored it 100, because
> the counterparty's tax ID is on a blacklist — that is arithmetic, not judgement.
>
> The agent is allowed to raise risk. It is never allowed to lower it below the floor. So
> the effective score is 100, and the console says exactly that: "The deterministic floor
> overruled the model here."

**Then point at the second call-out:**

> And the action the agent proposed was refused. "The delegation boundary refused hold
> shipment. The outcome above stayed a proposal and the case went to a human." The refusal
> is recorded as a first-class audit fact, not swallowed.

This is the strongest 30 seconds in the video. Do not rush it.

---

## Scene 3 — evidence a regulator could check (1:00-1:30)

**Screen:** same drawer, scroll to **Live evidence**.

> A 45-point disagreement between the floor and the model triggers an automatic debate —
> no human asks for it. And the evidence behind it is reproduced, not summarised.

**Point at the two grouped headings:** `COMPLIANCE READ 5 SOURCES` and
`INVESTIGATION READ 5 SOURCES`.

> Ten sources, fetched live from the web at decision time, each one a clickable citation
> with its real title. A sanctions-entity listing. A Federal Register sanctions notice.

**Click one citation** so a judge sees it resolve to the real page. Come back.

> The audit trail can be handed to a customs authority, because it contains what was
> actually read rather than a claim that something was checked.

---

## Scene 4 — cost, per hop (1:30-2:00)

**Screen:** stay in the drawer, expand one agent hop, then open `/devops`.

> Every model call is metered. Exact prompt, raw reply, tokens in and out, and cost, for
> each of the seven agents.

**Point at a hop's token and cost figures.**

> Four models, each chosen for a job. Nemotron Nano for screening every shipment.
> MiniCPM-V for reading uploaded bills of lading. Super for investigation. And Nemotron
> Ultra on the debate, the one place where the model's reasoning is the outcome instead of
> a score the floor overrides.
>
> Measured, an Ultra debate costs about two cents against Super's tenth of a cent. That is
> thirteen times, not the three-times its rate suggests, because it spends more tokens.
> The figure is measured rather than estimated, and it is in the README.

---

## Scene 5 — the guardrails, briefly (2:00-2:30)

**Screen:** `/governance`, then the Red Team panel in `/devops`.

> Governance is not a slide. There is a kill switch: revoke an agent and it goes
> SUSPENDED mid-pipeline. There is a policy dry run that previews which cases a boundary
> change would flip before you publish it.
>
> And repointing the system at a costlier model is refused unless you confirm it. Asking
> for Ultra across every agent returns a 409 with the multiple spelled out — thirteen
> point three times the cheapest model.

**In the Red Team panel, paste a prompt injection** and show the verdict.

> Injection attempts are blocked at intake, before the model is invoked at all.

---

## Scene 6 — why signing in exists (2:30-3:00)

**Screen:** `/review`, click a decision → the 401 or the login redirect. Then sign in as
`judge@vf-logistics.demo` and record one decision.

> Everything so far needed no account. Recording a decision does — because the audit trail
> names the person who made it.

**Show the audit entry** with the reviewer attributed.

> Seven agents, four NVIDIA models, live web evidence, and a deterministic floor the AI
> cannot argue its way past. Seven hundred and twelve tests. The code and the running
> system are both public.

**End on the board.** Do not end on a slide.

---

## Do not say

- "three Nemotron models" — it is four models: Nano, Super, Ultra, and MiniCPM-V for vision
- "the AI decides" — it proposes; the floor and the boundary decide
- Any claim about accuracy beyond the HS classification holdout (91.7%), which is the only
  measured accuracy number in the project
- "fully autonomous" — the whole architecture argues the opposite, and a judge who notices
  will trust everything else less

## If a take goes wrong

The board is disposable. `python scripts/seed_full_board.py --yes` rebuilds all twenty
cases in about 35 minutes, so re-seed before a recording session, never during one. Do NOT
run `scripts/test_documents.py` against the deployed service to tidy up: it clears the
board before every pass and will delete everything you are about to film.
