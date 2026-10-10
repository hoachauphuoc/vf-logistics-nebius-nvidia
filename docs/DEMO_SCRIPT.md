# Demo video shooting script — eleven clips, 165 seconds

One shooting document. There used to be two that disagreed with each other, which is the
same class of defect this script exists to avoid on camera.

**165 seconds, not 180.** The rules ask for a video "less than three (3) minutes", and the
previous version of this script targeted exactly 180.0s — landing on the boundary for no
gain. 2:45 also sits at the end of the 2:30–2:45 window this was planned to.

**A pitch, not a tutorial.** The organisers' guidance is to lead with the problem, say who
it is for, show it working, and name Nebius and the NVIDIA model clearly *in the audio*.
So clip 1 opens on the product name and its user, and clips 3 and 10 say "NVIDIA Nemotron"
and "Nebius Token Factory" aloud. Until this revision "NVIDIA" was never spoken at all.

The narration is **generated, not spoken live**. `scripts/build_narration.py` synthesises
`build/narration.wav` plus `build/narration.srt` from the eleven scenes below, per sentence,
so subtitle timings are measured from real audio rather than interpolated from word counts.
Each scene's speech is padded with silence up to the length of the clip recorded for it, so
if the clips are laid end to end in order, every line lands on the shot it describes with
no nudging on the timeline.

The narration text in this file is copied from `SCENES` in that script. **If you change one,
change both** — and the script is the authority, because it is what produces the audio.

That instruction used to be the only thing keeping the two in step, which is how the old
version ended up with a clip heading that started at 0:49 while the clip before it also
ended at 1:11. There is now a check:

```bash
python scripts/check_demo_script_sync.py
```

It reads `SCENES` and asserts that every scene's narration appears here verbatim, that the
length table and the summary block and `SCENES` all agree, and that each heading's
cumulative timecode is the running sum of the clips before it.

**Before spending a TTS run, run the offline budget check:**

```bash
python scripts/check_narration_budget.py
```

It reads `SCENES` directly and reports per-scene headroom. This matters because
`build_narration.py`'s own fit check happens *after* the billable synthesis call, prints to
stdout only, and **exits 0 even when a scene overruns** — and an overrun is not contained:
the timeline advances by `max(clip, spoken)`, so one long scene pushes every later scene off
its cut.

| Clip | Scene | Length | Screen |
|---|---|---|---|
| 1 | The problem | 17s | Pipeline `/` |
| 2 | A real document | 10s | DevOps `/devops` → *Upload a document* |
| 3 | The design rule | 21s | Agent Console `/agents` |
| 4 | The floor overrules the model | 19s | Pipeline → an escalated case → trace sheet, the three risk rows and the veto note |
| 5 | Live evidence | 10s | Same sheet, scrolled to *Live evidence* |
| 6 | The review queue | 12s | Review `/review` |
| 7 | The dossier | 14s | Review → *Due-diligence dossier (PDF)* → the PDF in a new tab |
| 8 | The delegation boundary | 24s | Governance `/governance` |
| 9 | Prompt injection blocked | 14s | Review → the blocked case |
| 10 | Tests and CI | 8s | Terminal, then the GitHub Actions run page |
| 11 | Close | 16s | Evaluation `/evaluation` → *Public enforcement cases*, then Pipeline `/` |
| | | **165s** | |

### What changed on 10/10, and why

Still nothing shot, so restructuring was free again.

- **Clip 1 opens on a verified figure.** "Thousands of shipments a week" was nobody's
  number. Vietnam Customs found a violation in 29,849 of 16.84 million declarations in
  2024 ([customs.gov.vn](http://customs.gov.vn:8228/index.jsp?pageId=2&aid=208927&cid=24)),
  fewer than one in five hundred — and that ratio is the product's argument: nearly every
  hold is honest, so the work is deciding each one quickly and defensibly.
- **Clip 7 is new: the due-diligence dossier.** It is the answer to clip 1, and the one
  artefact a forwarder would actually file. This is the *Potential Impact* clip.
- **Clip 11 closes on the only measurement made on cases this project did not write:**
  14 of 19 public enforcement cases held, on the Evaluation screen where the table is.
- **Paid for by** clip 2 (the intake agent is on screen, so the sentence naming it went),
  clips 5 and 6 each merging two sentences, and clip 8 losing *"so old decisions replay
  against the policy of their day"*.

### What changed from the nine-clip version, and why

Nothing had been shot. `build/` did not exist, the repository held no media, and the clip
lengths previously in `SCENES` were measured on 31/08 against footage of the **predecessor**
system — before the Nebius port landed on 17/09. So restructuring cost nothing.

- **Clips 5 and 9 are new, and they exist because the rigour in this project was invisible
  on camera.** 921 tests, a measured HS recall of 91.7% on a holdout, citations reproduced rather than
  summarised — a judge scoring Technological Implementation had to read the repository to
  find any of it. Clip 5 also carries the **Tavily bonus award**, which the old script
  showed nowhere at all.
- **Clip 3 now states the design rule instead of the cost.** It used to justify Nano on
  price, which is the framing the README spends a thousand lines correcting: the floor is
  why Nano is *correct* on those hops, not why it is cheap. It also used to say spend was
  metered "in tokens and in dollars" over a screen that showed no dollars.
- **The old clip 6 — a bill of lading rendered from a data event and labelled as rendered —
  was cut.** A real loss: it is a good honesty point. There was nowhere to put it inside
  2:45 once the evidence clips were in. It survives in the console and in `SUBMISSION.md`,
  just not on film.

---

## Part 0 — before you press record

- [ ] Screen recorder at **1920x1080**. A previous take was 852x480 and the case cards
      were unreadable on playback.
- [ ] Chrome at **90% zoom**, on the console: https://vf-app-350828852747.asia-southeast1.run.app
- [ ] **Warm the service.** Cloud Run runs at `--min-instances=0`, so the first request
      after an idle period takes 10–20 seconds and will ruin clip 1. Open
      https://vf-app-350828852747.asia-southeast1.run.app/health, then the console root, and wait
      for the board to paint.
- [ ] **Close devtools.** The board polls a large state payload every 1–2 seconds and an
      open Network tab is the noisiest thing on screen.
- [ ] Seed the board:

      $env:VF_API_KEY = (gcloud secrets versions access latest --secret=VF_API_KEY)
      python scripts/seed_full_board.py --yes

      About 35 minutes for 20 cases across all six terminal states. Do this **before** a
      recording session, never during one.
- [ ] Open Explorer at `sample_docs\` in this repository, positioned in a corner of the
      screen so `dirty_bol.pdf` and `injected_bol.pdf` are both visible.
- [ ] Upload `injected_bol.pdf` **now**, in the preparation phase, so the blocked case
      exists for clip 9. Model Armor refuses it before any model is invoked, so it is fast
      and costs nothing.
- [ ] Do **not** upload `clean_bol.pdf`. An earlier take had three document cases with
      near-identical numbers spread across two columns and they were impossible to tell
      apart on screen. `dirty_bol.pdf` alone carries the document story.
- [ ] Scroll to the top of the Pipeline board before the first frame.
- [ ] **Sign in for clip 2.** Uploading needs the operator role. On `/login` press
      **Continue as guest judge** — one click, no password — then return to `/`. The
      header shows a *One-click* chip; that is fine on camera and true. Do not press
      **Clear board** on DevOps: it is locked for this session anyway, and it would wipe
      the seeded board.
- [ ] **Confirm the live revision has the latest console.** The header chip
      *NVIDIA Nemotron 3 · Nebius Token Factory*, the *Start here* strip and the *End to
      end* chain at the top of every case trace are what make the required tools visible
      in every frame. They are deployed (revision `vf-app-00011` and later — the dossier
  button and the public-case table need it); if the
      chip is missing you are looking at a cached or older page.

### Check these three screens before rolling clips 3, 4 and 5

All three depend on fixes that are deployed. Each check takes a few seconds and catches a
stale tab, a wrong case, or a board that has not settled.

- [ ] **Clip 3: the per-agent dollar column on `/agents`.** The card used to show only
      calls and tokens while the narration claimed dollars. Verify: the rows show a dollar
      amount and are **ordered by spend**, so the debate agent is near the top despite its
      low call count.
- [ ] **Clip 4: three risk rows and the veto note on the chosen case.** Open the case
      named under clip 4 and confirm *Effective risk*, *Model alone* and *Rules floor* are
      all present, *Model alone* is the lower number, and the amber paragraph *"The
      deterministic floor overruled the model here"* is shown. Until the `risk_floor` fix
      shipped, the *Rules floor* row rendered on no case at all.
- [ ] **Clip 4: the investigation step reads as a report.** In the same sheet the
      investigation hop should carry a summary, not a model-failure note. Before
      `78d6db0`, half of Super's investigation replies were empty fragments that still
      parsed; the board was reseeded after the fix, so this should hold for every case,
      but look before you roll.
- [ ] **Clip 5 only works against the live service.** `external_search_results` does not
      exist in `demo-data.ts`, and `fetchCase` refuses in `DEMO_MODE`. The clip 4 case went
      through compliance, so it has sources; a case that cleared on rules alone ran no
      searches and has none.

### Do not press these while recording

- **Anything on `/devops` except the one upload for clip 2.** *Scripted batch* and *Bulk
  load* both add cases and will skew the board you just seeded.
- **Re-uploading the same PDF.** The case id derives from the B/L number printed in the
  file and ingestion is idempotent on `shipment_id`, so the second attempt returns the
  existing case. The server answers `HTTP 202` as if it worked and the board does not
  change.
- **`scripts/test_documents.py`.** It clears the board before every pass. Against this URL
  it refuses without `--yes-wipe-board`, and that guard exists precisely because it once
  deleted a seeded board.

### One thing that will be visible and is fine

`notify_webhook` shows as **skipped** on escalated cases, because `NOTIFY_WEBHOOK_URL` is
not configured in this deployment. That is a recorded reason rather than a failure, and it
is consistent with the story: the system records what it did not do and why. Do not
apologise for it on camera.

An older version of this script warned that `publish_decision` always showed *failed* from
a Pub/Sub IAM error. That is fixed — it now reads `done`. Nothing to avoid.

---

## Clip 1 — The problem (0:00 → 0:17, 17s)

**Screen:** Pipeline board at `/`, fully seeded. No interaction. Scroll down
slowly a little, just for motion. Let the header chip naming NVIDIA Nemotron 3 and Nebius
Token Factory be in frame for the whole clip; close the *Start here* strip before
recording if it crowds the board.

> Floorline is for freight forwarders. In 2024, Vietnam Customs found a violation in fewer
> than one declaration in five hundred. So almost everything held is honest: the job is
> holding the right ones, and deciding each fast.

The figure is 29,849 of 16.84 million (0.18%), from Vietnam Customs' own year-end release.
It is said as a ratio on purpose: a judge remembers "one in five hundred", not "0.18".

Worth letting the six columns be visible. On the board seeded for this take: eleven
escalated, one held, two awaiting a person, two blocked by a person, two released by a
person, two cleared automatically. Preparation adds one more awaiting a person (the
blocked injection document) and clip 2 adds one more escalated. The spread is the point —
this is not a demo where everything is suspicious. If you reseed, read the column counts
off the seed script's summary rather than from this paragraph.

---

## Clip 2 — A real document (0:17 → 0:27, 10s)

**Action:** Go to `/devops`, find **Upload a document**. Drag `dirty_bol.pdf` from Explorer
onto it — drag *slowly*, wait for the drop target to highlight, then release. Cut as soon
as the transcribing state appears. Do not record the wait.

> A real bill of lading, dropped as a mailroom would. Model Armor screens it before any
> model reads it.

The case takes 30–60 seconds to reach a terminal state. Clip 6 needs it finished, so shoot
the clips out of order if you like — just lay them back in order on the timeline.

---

## Clip 3 — The design rule (0:27 → 0:48, 21s)

**Action:** Go to `/agents`. Stop on the **Cost by agent** card. Let the dollar column be
readable, and let it be visible that the debate agent sits high on spend with very few
calls while Nano has many calls and little cost.

> Floorline runs on NVIDIA Nemotron 3, through Nebius Token Factory. Rules set a risk floor
> an agent may raise, never lower. So fraud and compliance run on Nano: a stronger model
> cannot change it. Ultra runs one hop, the debate, where its verdict is the answer.

This is the clip that earns *Quality of the Idea*, and the argument is the one thing in the
submission a judge is unlikely to have seen before: **model capacity is spent only where it
can change the answer.** The card is the evidence — cheap model on the high-volume hops,
expensive model on the one hop whose output the floor does not override.

**Do not improvise a total.** Say what is on screen. A viewer can read the figures, and a
number said loosely is a number they will check.

---

## Clip 4 — The floor overrules the model (0:48 → 1:07, 19s)

**Action:** Back to `/`. In the **Escalated** column open **`FULL-12-DUALUSE`** (industrial
frequency converters under a dual-use heading). On the seeded board it reads *Model alone*
78, *Rules floor* 85, *Effective risk* 85. The sheet opens on the **End to end** chain —
every hop with the NVIDIA model that ran it, then the delegation gate and the actions — so
hold on it for a beat, then scroll so the three risk rows and the amber veto paragraph are
in frame together, and hold there: *"The deterministic floor overruled the model here. The
model may raise risk but never lower it, so this score is arithmetic rather than
judgement."*

Fallback if that case is not vetoed after a reseed: **`FULL-16-FREIGHTANOMALY`** (in
*Released by a reviewer*; 78 against a floor of 90 on this board). Any case works whose
*Model alone* is below its *Rules floor* and which shows the veto paragraph; the two
blacklist and sanctions cases also qualify but open on a denial banner that crowds the
frame.

> Here the model scored this lower than the rules allow. The floor wins, so the higher
> number stands. An agent may raise risk, never lower it. This score is arithmetic, not
> judgement, and the trace records which rule set it.

The third and fourth sentences are the thesis of the whole submission. Do not rush them.
The narration names no figures on purpose: the screen carries them, and a reseed changes
them.

**Why not a case that cleared itself.** This clip used to open a case in the *Cleared*
column and narrate "what the model scored". Both cleared cases on this board clear on a
rule in `sql_prefilter` — a VIP exporter on its registered tax id, and a low-value domestic
consignment — so no model runs: the sheet shows no *Model alone* row, and clip 5 would find
no sources to scroll to.

---

## Clip 5 — Live evidence (1:07 → 1:17, 10s)

**Action:** Stay in the clip 4 sheet. Scroll to **Live evidence**. The first heading reads
*COMPLIANCE READ 5 SOURCES* (an *INVESTIGATION READ 5 SOURCES* group follows it). Hover one
anchor so the hostname is legible, then click it and
let the real page open in a new tab. Cut once the destination is recognisable.

> The compliance screen read five public sources at decision time, each a live link, not a
> summary.

This is the Tavily evidence, and the bonus award rides on it. Until recently these citations
did not render at all: the component read `s.urls` off the search step, a key the backend
never writes, so ten real sources per case showed as a bare count. Clicking through is the
point — it proves the citation resolves rather than decorates.

---

## Clip 6 — The review queue (1:17 → 1:29, 12s)

**Only shoot this once `dirty_bol.pdf` has settled.** It should be in the queue as an
escalated document case.

**Action:** Go to `/review`. Hold on the list so the red and amber left borders are both
visible, then open one case and scroll so the document sits beside the findings.

> Everything the agent may not close comes here, with the document beside the findings,
> because approving a hold you cannot check is a rubber stamp.

If you land on a case where the model and the floor disagreed by fifteen points or more, the
disputed banner and the **Senior auditor debate** card with its CONFIRM/DISAGREE badge are
both worth having in frame. On the seeded board two cases carry one, and only
**`FULL-07-BLACKTAX`** is in the queue (model 68 against a floor of 100); the other,
`FULL-05-SANCTIONS`, has already been blocked by a reviewer. Do not lengthen the clip for
it — if you want it as its own beat, re-record at 18–20s, change that scene's seconds in
`SCENES`, re-run `check_narration_budget.py`, and regenerate.

---

## Clip 7 — The dossier (1:29 → 1:43, 14s)

**Action:** Still in `/review`, on a case with a sanctions or dual-use finding — after a
reseed, **`FULL-05-SANCTIONS`** (blocked by a reviewer; its receiver is *Alexsong Pte.
Ltd.*, a real OFAC designation, OFAC-SDN-35036) or **`FULL-12-DUALUSE`** from the trace
sheet. Press **Due-diligence dossier (PDF)** in the *Paperwork* header. The PDF opens in a
new tab. Hold on the top half (outcome, shipment), then scroll to **Sanctions screening**
(list *OFAC SDN + UN SC Consolidated*, 18,525 entities, the sync date) and the first
**finding**, so *Basis* and *Comparable public case* are both legible.

> One click turns any case into a due-diligence dossier. Every finding, the sanctions list
> and its date, the regulation it rests on, and a real enforcement case like it.

This is the clip that says who would pay for this. Do not narrate the regulations by name;
the page carries them, and a judge reads faster than the voice speaks. **Check before
rolling** that the case's *List* row does not read `bundled_seed`: a case seeded before the
official index went live was screened against the demo list, and the dossier says so in
grey under the table. Reseed if it does.

---

## Clip 8 — The delegation boundary (1:43 → 2:07, 24s)

**Action:** Go to `/governance`. Hold on the line naming the active boundary and the person
who published it, then scroll to the permissions block.

> The agent has no authority of its own. A human publishes a machine-readable boundary; the
> agent works inside it: the value ceiling, forbidden destinations, which actions it may
> take unasked. Every action records the boundary version that allowed it. Withdraw it and
> the system suspends itself, still analysing but refusing every protected action.

Still the longest clip, and the one that earns the submission its category. It came down
from 38s to 28s to fund the evidence clips, and to 24s to fund the dossier. **Do not press
Revoke on camera with the judge session**: it is locked for one-click sign-ins, because a
revoked boundary would suspend the agent for every judge after you.

---

## Clip 9 — Prompt injection blocked (2:07 → 2:21, 14s)

**Action:** In `/review`, open the blocked case created during preparation.

> This document told the agent to ignore its instructions and release the container. Model
> Armor caught it before any model ran. The case opened already denied.

Verified on live traffic: the case trace reads *blocked at intake, model never invoked*.

---

## Clip 10 — Tests and CI (2:21 → 2:29, 8s)

**Action:** Two shots, roughly four seconds each, cut together. First a terminal showing the
tail of a real run — `python -m pytest tests/ -q` ending on `921 passed`. Then the GitHub
Actions run page for `master`, with five green jobs visible.

> 921 tests pass at 81 percent coverage, and CI runs them on every push.

**The console has no test or CI screen** — this evidence can only come from a terminal and
from GitHub. Do not fake it with a still: run the suite, let the green line be real. Eight
seconds is enough because the numbers do the work, and a judge who wants the detail has the
repository.

CI is worth showing for a reason beyond the count: the workflow existed for weeks filtered
on branch `main` while this repository uses `master`, so it had **never run once**. It runs
now.

---

## Clip 11 — Close (2:29 → 2:45, 16s)

**Action:** Go to `/evaluation` and scroll to **Public enforcement cases**, so the table of
nineteen cases with their *Rules* and *Full pipeline* verdicts is in frame (about eight
seconds). Then cut back to `/` and let the board fill the frame, header chip included.

> On nineteen real enforcement cases it held fourteen, and says what it cannot see.
> Floorline: NVIDIA Nemotron on Nebius Token Factory. Agents that act inside limits a person
> set, and stop when they should.

"Says what it cannot see" is the *Missed* rows: origin fraud, which no booking shows. The
table states it; the voice only points at it. **Fourteen is the full-pipeline figure**
(`data/benchmark_results/public_full_all.json`); rules alone held eleven. If that file is
regenerated, re-read the number before recording. End on the board, not on a slide.

---

## Assembling in Clipchamp

1. Drag `build/narration.wav` onto the timeline at **0:00**.
2. Drop the eleven clips in order 1..11, butted together, **no transitions**. Each scene's
   speech is already padded to its clip length, so correct order means picture and sound
   line up on their own.
3. Subtitles: import `build/narration.srt` directly. Do **not** use Clipchamp's *Auto
   captions* — it produces a different transcript and reliably mangles proper nouns
   (Nemotron, Nebius, Model Armor).
4. Do **not** use Clipchamp's *Text to speech*. `narration.wav` is already a synthesised
   voice; using both reads the script twice.

Clip lengths currently in `SCENES`:

```
1: 17s   2: 10s   3: 21s   4: 19s   5: 10s   6: 12s
7: 14s   8: 24s   9: 14s  10:  8s  11: 16s     total 165s
```

## Regenerating the narration

```bash
python scripts/check_narration_budget.py     # free, offline, run this first
python scripts/build_narration.py            # billable
```

`build_narration.py` needs `texttospeech.googleapis.com` enabled and application-default
credentials.

- Voice is `en-US-Studio-O`. Change `VOICE` in the script for another (for example
  `en-US-Studio-Q` for a male voice).
- Reading speed is `SPEAKING_RATE`, currently 1.0.
- **If you re-record a clip at a different length, change that scene's seconds in `SCENES`
  and regenerate.** The script reports immediately if a scene's speech no longer fits its
  clip, and by how many seconds. The fix for an overrun is shorter writing, not a faster
  read.
- Clips 5 and 9 have the most headroom (about 2.5s each on the offline estimate), so if one
  scene needs an extra second that is where to take it from.
- Splitting a sentence in two costs 0.25s even if you add no words, because of the gap after
  every sentence.

## Do not say

- "three Nemotron models" — there are four models: Nano, Super, Ultra, and MiniCPM-V for
  document vision, which is not an NVIDIA model and should not be described as one.
- "the AI decides" — it proposes. The deterministic floor and the delegation boundary
  decide.
- "fully autonomous" — the entire architecture argues the opposite, and a judge who notices
  will trust everything else less.
- Any accuracy claim beyond the HS classification holdout (91.7%) and the public-case count
  (14 of 19 held). Do not turn the second into a percentage: on nineteen cases one case is
  five points.
- Anything about the debate being cheap. It is measured at `$0.0198` per debate against
  Super's `$0.0015`.
- **"Super runs the debate."** It runs Ultra. Several source comments and two user-visible
  event strings said Super on that hop for weeks, and the same error had already been copied
  into the README, the architecture diagram and the Devpost submission once.
