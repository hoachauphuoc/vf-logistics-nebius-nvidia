# Demo video shooting script — ten clips, 164 seconds

One shooting document. There used to be two that disagreed with each other, which is the
same class of defect this script exists to avoid on camera.

**164 seconds, not 180.** The rules ask for a video "less than three (3) minutes", and the
previous version of this script targeted exactly 180.0s — landing on the boundary for no
gain. 2:44 also sits inside the 2:30–2:45 window this was planned to.

The narration is **generated, not spoken live**. `scripts/build_narration.py` synthesises
`build/narration.wav` plus `build/narration.srt` from the ten scenes below, per sentence,
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
| 1 | The problem | 16s | Pipeline `/` |
| 2 | A real document | 15s | DevOps `/devops` → *Upload a document* |
| 3 | The design rule | 20s | Agent Console `/agents` |
| 4 | A case that cleared itself | 20s | Pipeline → a case → trace sheet, the three risk rows |
| 5 | Live evidence | 14s | Same sheet, scrolled to *Live evidence* |
| 6 | The review queue | 16s | Review `/review` |
| 7 | The delegation boundary | 28s | Governance `/governance` |
| 8 | Prompt injection blocked | 15s | Review → the blocked case |
| 9 | Tests and CI | 8s | Terminal, then the GitHub Actions run page |
| 10 | Close | 12s | Pipeline `/` |
| | | **164s** | |

### What changed from the nine-clip version, and why

Nothing had been shot. `build/` did not exist, the repository held no media, and the clip
lengths previously in `SCENES` were measured on 31/08 against footage of the **predecessor**
system — before the Nebius port landed on 17/09. So restructuring cost nothing.

- **Clips 5 and 9 are new, and they exist because the rigour in this project was invisible
  on camera.** 717 tests, a measured HS recall of 91.7%, citations reproduced rather than
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
- [ ] Chrome at **90% zoom**, on the console: https://vf-console-f7rcctz26a-as.a.run.app
- [ ] **Warm both services.** Cloud Run runs at `--min-instances=0`, so the first request
      after an idle period takes 10–20 seconds and will ruin clip 1. Open
      https://vf-logistics-f7rcctz26a-as.a.run.app/health, then the console root, and wait
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
      exists for clip 8. Model Armor refuses it before any model is invoked, so it is fast
      and costs nothing.
- [ ] Do **not** upload `clean_bol.pdf`. An earlier take had three document cases with
      near-identical numbers spread across two columns and they were impossible to tell
      apart on screen. `dirty_bol.pdf` alone carries the document story.
- [ ] Scroll to the top of the Pipeline board before the first frame.

### Three things that must be deployed before clips 3, 4 and 5 will film

These are recent fixes. Shooting against an older revision gets you a screen that
contradicts the narration.

- [ ] **Clip 3 needs the per-agent dollar column on `/agents`.** That card was titled "Cost
      by agent" and displayed only calls and tokens — no money at all — while the old
      narration claimed spend was metered in dollars. The figure is now summed server-side
      from each step's own rate. Verify: the rows show a dollar amount and are **ordered by
      spend**, so the debate agent is near the top despite its low call count.
- [ ] **Clip 4 needs the `risk_floor` fix, or the shot does not exist.** The trace sheet read
      `rec.floor`, a key the backend has never sent — it sends `risk_floor` — and the
      `!= null` guard turned that into silence. **The "Rules floor" row has never rendered
      on any case.** Verify before rolling: open any case and confirm you can see three
      rows, *Effective risk*, *Model alone* and *Rules floor*. If you only see two, you are
      on an old revision and clip 4 has no subject.
- [ ] **Clip 5 only works against the live service.** `external_search_results` does not
      exist in `demo-data.ts`, and `fetchCase` refuses in `DEMO_MODE`. Pick a case that went
      through compliance or investigation; a case that cleared on rules alone ran no
      searches and has no sources to show.

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

## Clip 1 — The problem (0:00 → 0:16, 16s)

**Screen:** Pipeline board at `/`, fully seeded, signed out. No interaction. Scroll down
slowly a little, just for motion.

> A forwarder clears thousands of shipments a week. Any one can hide under-invoicing, a
> sanctioned buyer, or dual-use cargo on farm paperwork. Checking by hand is impossible;
> letting a model release them is reckless.

Worth letting the six columns be visible: eleven escalated, two blocked by a person, two
released by a person, two cleared automatically. The spread is the point — this is not a
demo where everything is suspicious.

---

## Clip 2 — A real document (0:16 → 0:31, 15s)

**Action:** Go to `/devops`, find **Upload a document**. Drag `dirty_bol.pdf` from Explorer
onto it — drag *slowly*, wait for the drop target to highlight, then release. Cut as soon
as the transcribing state appears. Do not record the wait.

> This is a real bill of lading, dropped the way a mailroom would drop it. Model Armor
> screens the file before any model reads it. Then an intake agent transcribes it.

The case takes 30–60 seconds to reach a terminal state. Clip 6 needs it finished, so shoot
the clips out of order if you like — just lay them back in order on the timeline.

---

## Clip 3 — The design rule (0:31 → 0:51, 20s)

**Action:** Go to `/agents`. Stop on the **Cost by agent** card. Let the dollar column be
readable, and let it be visible that the debate agent sits high on spend with very few
calls while Nano has many calls and little cost.

> Rules set a risk floor an agent may raise, never lower. So fraud and compliance run on
> Nano: a stronger model cannot change it. Ultra runs one hop, the debate, where its verdict
> is the answer. Spend is metered per agent, in dollars.

This is the clip that earns *Quality of the Idea*, and the argument is the one thing in the
submission a judge is unlikely to have seen before: **model capacity is spent only where it
can change the answer.** The card is the evidence — cheap model on the high-volume hops,
expensive model on the one hop whose output the floor does not override.

**Do not improvise a total.** Say what is on screen. A viewer can read the figures, and a
number said loosely is a number they will check.

---

## Clip 4 — A case that cleared itself (0:51 → 1:11, 20s)

**Action:** Back to `/`. Open a case in the **Cleared** column. Scroll so the three risk
rows — *Effective risk*, *Model alone*, *Rules floor* — are in frame together, and hold
there. If a veto paragraph is present, keep it in shot: *"The model may raise risk but never
lower it, so this score is arithmetic rather than judgement."*

> This one cleared itself. Three numbers say why: what the model scored, what the rules
> floor demanded, and the higher of the two. The agent did not decide it was safe. It proved
> it was permitted, and recorded which rule allowed it.

The last two sentences are the thesis of the whole submission. Do not rush them.

**Check the shot exists before you roll.** See the deployment checklist above: until the
`risk_floor` fix shipped, the *Rules floor* row rendered on no case at all.

---

## Clip 5 — Live evidence (1:11 → 1:25, 14s)

**Action:** Stay in the same sheet. Scroll to **Live evidence**. The heading reads
*COMPLIANCE READ 5 SOURCES*. Hover one anchor so the hostname is legible, then click it and
let the real page open in a new tab. Cut once the destination is recognisable.

> The compliance screen read five public sources at decision time. Each one is a live link,
> not a summary. This is what a customs authority would be shown.

This is the Tavily evidence, and the bonus award rides on it. Until recently these citations
did not render at all: the component read `s.urls` off the search step, a key the backend
never writes, so ten real sources per case showed as a bare count. Clicking through is the
point — it proves the citation resolves rather than decorates.

---

## Clip 6 — The review queue (1:25 → 1:41, 16s)

**Only shoot this once `dirty_bol.pdf` has settled.** It should be in the queue as an
escalated document case.

**Action:** Go to `/review`. Hold on the list so the red and amber left borders are both
visible, then open one case and scroll so the document sits beside the findings.

> Everything the agent was not permitted to close comes here. Red is escalated, yellow is
> held. The document sits beside the findings, because approving a hold you cannot check is
> a rubber stamp.

If you land on a case where the model and the floor disagreed by fifteen points or more, the
disputed banner and the **Senior auditor debate** card with its CONFIRM/DISAGREE badge are
both worth having in frame. The board carries three such cases. Do not lengthen the clip for
it — if you want it as its own beat, re-record at 22–24s, change that scene's seconds in
`SCENES`, re-run `check_narration_budget.py`, and regenerate.

---

## Clip 7 — The delegation boundary (1:41 → 2:09, 28s)

**Action:** Go to `/governance`. Hold on the line naming the active boundary and the person
who published it, then scroll to the permissions block.

> The agent has no authority of its own. A human publishes a machine-readable boundary; the
> agent works inside it: the value ceiling, forbidden destinations, which actions it may
> take unasked. Every action records the boundary version that allowed it, so old decisions
> replay against the policy of their day. Withdraw it and the system suspends itself, still
> analysing but refusing every protected action.

Still the longest clip, and the one that earns the submission its category. It came down
from 38s to 28s to fund the evidence clips; the two sentences dropped were *"Autonomy here
is delegated, and delegation can be revoked"* and the split of the suspend behaviour into
two. The remaining four carry the argument.

---

## Clip 8 — Prompt injection blocked (2:09 → 2:24, 15s)

**Action:** In `/review`, open the blocked case created during preparation.

> This document told the agent to ignore its instructions and release the container. Model
> Armor caught it before any model ran, so no tokens were spent. The case opened already
> denied.

Verified on live traffic: the case trace reads *blocked at intake, model never invoked*.

---

## Clip 9 — Tests and CI (2:24 → 2:32, 8s)

**Action:** Two shots, roughly four seconds each, cut together. First a terminal showing the
tail of a real run — `python -m pytest tests/ -q` ending on `717 passed`. Then the GitHub
Actions run page for `master`, with four green jobs visible.

> 717 tests pass at 75 percent coverage. Continuous integration runs them on every push.

**The console has no test or CI screen** — this evidence can only come from a terminal and
from GitHub. Do not fake it with a still: run the suite, let the green line be real. Eight
seconds is enough because the numbers do the work, and a judge who wants the detail has the
repository.

CI is worth showing for a reason beyond the count: the workflow existed for weeks filtered
on branch `main` while this repository uses `master`, so it had **never run once**. It runs
now.

---

## Clip 10 — Close (2:32 → 2:44, 12s)

**Action:** Back to `/`. Let the board fill the frame.

> Seven agents on Nebius Token Factory, with Nemotron picked per hop. Agents that act,
> inside limits a person set. And stop when they should.

End on the board, not on a slide.

---

## Assembling in Clipchamp

1. Drag `build/narration.wav` onto the timeline at **0:00**.
2. Drop the ten clips in order 1..10, butted together, **no transitions**. Each scene's
   speech is already padded to its clip length, so correct order means picture and sound
   line up on their own.
3. Subtitles: import `build/narration.srt` directly. Do **not** use Clipchamp's *Auto
   captions* — it produces a different transcript and reliably mangles proper nouns
   (Nemotron, Nebius, Model Armor).
4. Do **not** use Clipchamp's *Text to speech*. `narration.wav` is already a synthesised
   voice; using both reads the script twice.

Clip lengths currently in `SCENES`:

```
1: 16s   2: 15s   3: 20s   4: 20s   5: 14s
6: 16s   7: 28s   8: 15s   9:  8s  10: 12s     total 164s
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
- Clip 9 and clip 10 have the most headroom, so if one scene needs an extra second that is
  where to take it from.
- Splitting a sentence in two costs 0.25s even if you add no words, because of the gap after
  every sentence.

## Do not say

- "three Nemotron models" — there are four models: Nano, Super, Ultra, and MiniCPM-V for
  document vision, which is not an NVIDIA model and should not be described as one.
- "the AI decides" — it proposes. The deterministic floor and the delegation boundary
  decide.
- "fully autonomous" — the entire architecture argues the opposite, and a judge who notices
  will trust everything else less.
- Any accuracy claim beyond the HS classification holdout (91.7%), which is the only
  measured accuracy figure in the project.
- Anything about the debate being cheap. It is measured at `$0.0198` per debate against
  Super's `$0.0015`.
- **"Super runs the debate."** It runs Ultra. Several source comments and two user-visible
  event strings said Super on that hop for weeks, and the same error had already been copied
  into the README, the architecture diagram and the Devpost submission once.
