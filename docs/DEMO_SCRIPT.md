# Demo video shooting script — nine clips, 180 seconds exactly

One shooting document. There used to be two that disagreed with each other, which is the
same class of defect this script exists to avoid on camera.

The narration is **generated, not spoken live**. `scripts/build_narration.py` synthesises
`build/narration.wav` plus `build/narration.srt` from the nine scenes below, per sentence,
so subtitle timings are measured from real audio rather than interpolated from word counts.
Each scene's speech is padded with silence up to the length of the clip recorded for it, so
if the clips are laid end to end in order, every line lands on the shot it describes with
no nudging on the timeline.

The narration text in this file is copied from `SCENES` in that script. **If you change one,
change both** — and the script is the authority, because it is what produces the audio.

| Clip | Scene | Length | Screen |
|---|---|---|---|
| 1 | The problem | 17s | Pipeline `/` |
| 2 | A real document | 15s | DevOps `/devops` → *Upload a document* |
| 3 | Cost and model tiering | 17s | Agent Console `/agents` |
| 4 | A case that cleared itself | 22s | Pipeline → an AUTO_CLEARED case |
| 5 | The review queue | 16s | Review `/review` |
| 6 | A rendered bill of lading | 19s | Review → an event-sourced case |
| 7 | The delegation boundary | 38s | Governance `/governance` |
| 8 | Prompt injection blocked | 18s | Review → the blocked case |
| 9 | Close | 18s | Pipeline `/` |
| | | **180s** | |

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

**Screen:** Pipeline board at `/`, fully seeded, signed out. No interaction. Scroll down
slowly a little, just for motion.

> A freight forwarder clears thousands of shipments a week. Any one of them can hide price
> manipulation, a sanctioned buyer, or dual-use cargo dressed up as farm equipment.
> Checking all of them by hand is impossible. Letting a model release them is reckless.

Worth letting the six columns be visible: eleven escalated, two blocked by a person, two
released by a person, two cleared automatically. The spread is the point — this is not a
demo where everything is suspicious.

---

## Clip 2 — A real document (0:17 → 0:32, 15s)

**Action:** Go to `/devops`, find **Upload a document**. Drag `dirty_bol.pdf` from Explorer
onto it — drag *slowly*, wait for the drop target to highlight, then release. Cut as soon
as the transcribing state appears. Do not record the wait.

> This is a real bill of lading, dropped the way a mailroom would drop it. Nothing about it
> is pre-registered. Model Armor screens the file before any model reads it. Then an intake
> agent transcribes it.

The case takes 30–60 seconds to reach a terminal state. Clip 5 needs it finished, so shoot
the clips out of order if you like — just lay them back in order on the timeline.

---

## Clip 3 — Cost and model tiering (0:32 → 0:49, 17s)

**Action:** Go to `/agents`. Stop on the per-agent cost and token figures. Do not scroll
past them.

> Fraud detection and compliance screening run in parallel on Nemotron Nano. When either
> raises something serious, an investigation agent opens a deeper case on Super. Every call
> is metered per agent, in tokens and in dollars. Screening a shipment costs well under a
> cent.

**Do not improvise a total.** Say what is on screen. A viewer can read the figures, and a
number said loosely is a number they will check.

---

## Clip 4 — A case that cleared itself (0:49 → 1:11, 22s)

**Action:** Back to `/`. Open a case in the **Cleared** column. Scroll to the **Verdict**
and **Agent hops** blocks and stop there.

> This one cleared on its own. It arrived as a data event, and it sat inside every limit the
> business granted the agent: value under the ceiling, no forbidden destination, no
> deterministic finding. The agent did not decide it was safe. It proved it was permitted,
> and recorded which rule allowed it.

The last two sentences are the thesis of the whole submission. Do not rush them.

---

## Clip 5 — The review queue (0:49 → 1:27, 16s)

**Only shoot this once `dirty_bol.pdf` has settled.** It should be in the queue as an
escalated document case.

**Action:** Go to `/review`. Hold on the list so the red and amber left borders are both
visible, then open one case and scroll so the document sits beside the findings.

> Everything the agent was not permitted to close comes here. Red is escalated, yellow is
> held; the state is the border colour. The shipping document sits beside the findings,
> because approving a hold you cannot check is a rubber stamp.

Sixteen seconds is short and the line has been cut to the single strongest idea. If you want
the agent's own explanation in shot as well, re-record clip 5 at 35–40 seconds, change that
scene's length in `SCENES`, and regenerate — do not try to read faster.

---

## Clip 6 — A rendered bill of lading (1:27 → 1:46, 19s)

**Action:** In the queue, open a case that arrived as a shipment **event** rather than a
document — its description carries no document reference. Scroll to the source document and
make sure the line explaining that it was rendered from the event is legible.

> This shipment arrived as a data event, with no document at all. So the system rendered one
> from the record it received, and labelled it as rendered, on the page and in the
> provenance. A reconstruction is never presented as an original. That would corrupt the
> audit trail.

---

## Clip 7 — The delegation boundary (1:46 → 2:24, 38s)

**Action:** Go to `/governance`. Hold on the line naming the active boundary and the person
who published it, then scroll to the permissions block.

> The agent has no authority of its own. A human publishes a machine-readable boundary, and
> the agent operates inside it. It sets the value ceiling, the forbidden destinations, and
> which actions the agent may execute without asking. Every action it takes records the
> boundary version that allowed it, so a decision made months ago can be replayed against
> the policy in force at the time. Withdraw the boundary and the system suspends itself. It
> keeps analysing and proposing, but the execution gate refuses every protected action.
> Autonomy here is delegated, and delegation can be revoked.

The longest clip, and the one that earns the submission its category. Thirty-eight seconds
is deliberate.

---

## Clip 8 — Prompt injection blocked (2:24 → 2:42, 18s)

**Action:** In `/review`, open the blocked case created during preparation.

> This document told the agent to ignore its instructions and release the container. Model
> Armor caught it before any model was invoked, so no tokens were spent. The case opened
> already denied, and the file was kept for a human to see.

Verified on live traffic: the case trace reads *blocked at intake, model never invoked*.

---

## Clip 9 — Close (2:42 → 3:00, 18s)

**Action:** Back to `/`. Let the board fill the frame.

> Seven agents on Nebius Token Factory. Nemotron Nano screens every shipment, Super
> investigates, and Ultra argues the cases where the floor and the model disagree. Agents
> that act, inside limits a person set, and stop when they should.

End on the board, not on a slide.

---

## Assembling in Clipchamp

1. Drag `build/narration.wav` onto the timeline at **0:00**.
2. Drop the nine clips in order 1..9, butted together, **no transitions**. Each scene's
   speech is already padded to its clip length, so correct order means picture and sound
   line up on their own.
3. Subtitles: import `build/narration.srt` directly. Do **not** use Clipchamp's *Auto
   captions* — it produces a different transcript and reliably mangles proper nouns
   (Nemotron, Nebius, Model Armor).
4. Do **not** use Clipchamp's *Text to speech*. `narration.wav` is already a synthesised
   voice; using both reads the script twice.

Clip lengths currently in `SCENES`:

```
1: 17s   2: 15s   3: 17s   4: 22s   5: 16s
6: 19s   7: 38s   8: 18s   9: 18s        total 180s
```

## Regenerating the narration

```bash
python scripts/build_narration.py
```

Needs `texttospeech.googleapis.com` enabled and application-default credentials.

- Voice is `en-US-Studio-O`. Change `VOICE` in the script for another (for example
  `en-US-Studio-Q` for a male voice).
- Reading speed is `SPEAKING_RATE`, currently 1.0.
- **If you re-record a clip at a different length, change that scene's seconds in `SCENES`
  and regenerate.** The script reports immediately if a scene's speech no longer fits its
  clip, and by how many seconds. The fix for an overrun is shorter writing, not a faster
  read.
- Scenes 8 and 9 deliberately end with about four seconds of silence, which is room to
  register the last shot before the cut.

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
