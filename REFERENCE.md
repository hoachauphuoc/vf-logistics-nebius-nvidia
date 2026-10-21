# Floorline — full technical reference

This is the long reference: the API, environment variables, measured results, findings, roadmap and repository layout. The short front page is [README.md](README.md).

The name is the design rule. Deterministic checks set a risk **floor** for every
shipment; the agents may argue a case above that line, and nothing they say can take it
below. (VF Logistics is the freight operator in the demo; the repository, the Cloud Run
service `vf-app` and the API keep that name.)

**Built on:** **Nebius Token Factory** for every model call, running **NVIDIA Nemotron 3
Nano** (fraud, compliance, HS (Harmonized System) classification — whether the declared
customs tariff code fits the goods — and the zero-day radar, an adverse-media search for
parties no sanctions list has caught up with), **NVIDIA Nemotron 3 Super**
(investigation and the Senior Auditor debate), plus
MiniCPM-V-4.5 for reading scanned documents. **Tavily** live web search is called at
runtime by compliance screening, route validation, investigation, the zero-day radar,
the debate and the Governance page's sanctions scan; in the zero-day radar and the
debate, Nemotron calls the search as a tool and chooses the query.

- **Hackathon:** Nebius x NVIDIA Global AI Hackathon
- **Track:** Best Apps and Agents
- **Bonus target:** Best Use of Tavily ($3,000, stackable with a Track Award)

- **Live demo (console):** https://vf-app-350828852747.asia-southeast1.run.app
- **API:** the same URL, under `/api/v1` — health at
  https://vf-app-350828852747.asia-southeast1.run.app/health, the OpenAPI document at
  https://vf-app-350828852747.asia-southeast1.run.app/api/v1/openapi.json

**Judges:** the deployed console asks everyone to sign in (an anonymous visitor is sent to the sign-in screen and the API answers 401). **Continue as guest judge** on the login page gives you the board, every case trace, the
review queue and the audit trail with no password; the spend figures and the archived original
documents still need a role. The guest signs you in with
one click to inject shipments or upload a document, block a case or ask for information,
and simulate a policy. Anything that releases cargo or would carry over to the next
judge — releasing a shipment, clearing the board, publishing or revoking the agent's
authority, editing the screening rules — needs a password sign-in, because the audit
trail names the person who released a shipment. Two password accounts are in the Devpost testing-instructions
field, one of them Reviewer-only so you can watch the access control refuse something.
Details: [One click for judges](#one-click-for-judges).

## At a glance

- **What it is:** shipment screening for a forwarder's compliance desk. Deterministic
  checks set a risk floor on every shipment; Nemotron agents on Nebius Token Factory score,
  screen, investigate and debate above it, with live Tavily web search. Clear cases are
  released inside limits a named person publishes; the rest go to a reviewer with the
  evidence and a cited dossier.
- **The one design rule:** a model may raise risk, never lower it below the floor:
  `reconcile()` takes the higher of the model's score and the floor, and `validate()`
  raises if the HS or zero-day model findings ever lowered it. The debate is the one hop
  whose verdict can send a disputed case to a deep investigation it would
  otherwise skip, and it can never clear one; a person still decides every disputed case.
- **Measured** (95% Wilson intervals in brackets; the holdout corpus is synthetic):
  - rules alone, 453 holdout cases: recall 93.5% [90–96], false-positive rate 38.4% [28–49];
  - adding the two model checks benchmarked so far, the HS classifier and the zero-day
    radar, on the same 200 holdout cases: recall 95.8% [91–98] → 100% [97–100], because
    the HS classifier caught all 7 disguised tariff codes the rules missed. It also held
    2 more honest shipments (false-positive rate 48.5% [32–65] → 54.5% [37–71]) and, by
    design, released none the rules held. The fraud, compliance, investigation and
    debate agents were not in this run, and most zero-day searches in it were stubbed;
  - 19 public enforcement cases, each paired with the honest trade it imitated: 14 frauds
    held (73.7% [51–89]; rules alone 11), but also 9 of the 19 honest look-alikes (rules
    alone 7). Five pairs came out fraud held and honest released, but two of those flipped
    between runs of the model, so only 3 count as cleanly separated (rules alone: 4);
  - HS classifier on substitutions its reference never mentions: 11 of 12 caught, 0 of 12
    honest cases flagged (95% upper bound 24.2%).
- **The weakness, in reviewer time:** at 0.2% fraud, the 2024 Vietnam customs rate, the
  rules would hold about **206 shipments per real fraud case** (151–271 if recall and
  false-positive rate both land at the best or worst end of their intervals; not a 95%
  interval), and on the 200-case subset the rules plus those two checks hold about 273
  against the rules' 254. Customs' own targeting makes roughly 19 red-channel inspections
  per violation found. So the product's job is to make each hold quick and defensible to
  decide; the screen is not precise, and no real customer traffic has been measured.
- **Cost:** under half a cent of model spend per case (`$0.068`–`$0.088` for a 20-case live
  run; $1.01 per 1,000 for the HS and zero-day checks in the 200-case benchmark).
  Tavily's search quota, not the models, is the binding constraint.
- **Try it in a few minutes:** signed in as guest judge, upload
  `sample_docs/injected_bol.pdf` in DevOps and watch Model Armor block it before any
  model reads it; open a held case for its findings, sources and dossier; simulate a
  policy against the board on Governance; sign in as the Reviewer account and watch the
  console refuse to publish policy, naming the role it needs.
- **Verify:** the console's Evaluation page (`/evaluation`) and `GET /api/v1/evaluation`
  serve every committed report, with 95% intervals and the operating curve (since the
  `896bbae` merge, 14 Oct 2026). The live service runs revision `vf-app-00044-x7b`,
  deployed 21 Oct 2026 from `cd2053f`. `python scripts/run_massive_benchmark.py --arm rules` reruns the rules in seconds
  at no cost; [Reproducible testing](#reproducible-testing) has the rest.

## The problem

Fraud in a forwarder's book is rare, and that is what makes it expensive to find. In 2024
Vietnam Customs processed **16.84 million** export and import declarations, found a
violation in **29,849** of them — **0.18%** — and sent **3.45%** to the red channel for
physical inspection to find them
([customs.gov.vn, 2 Jan 2025](http://customs.gov.vn:8228/index.jsp?pageId=2&aid=208927&cid=24)).
Even the authority's own targeting holds about nineteen declarations for every one that
turns out to be wrong. A forwarder's compliance desk lives inside the same ratio: whatever
it holds, almost all of it is honest, and each hold is a person's time and a customer's
delay.

The signals do not help on their own. A freight charge 60% under the lane's history looks
like a promotion, not under-invoicing; a shipper with two lifetime shipments looks like a
new customer, not a shell. Read together they are the pattern, but a rules engine reads
them one at a time and an analyst has no time to read them together for every booking.

So the job is two jobs. **Hold the right shipments** — and on the public enforcement cases
in [Measured results](#public-enforcement-cases), the rules plus the HS and zero-day
checks held 14 of 19 real frauds (rules alone: 11). And **make every hold quick and
defensible to decide**, because at 0.2% fraud even a good screen holds hundreds of honest
shipments per real one. That second job is
where Floorline earns its place: each held case arrives with the findings, the sanctions
list it was screened against and that list's date, live sources, the document, and a
**due-diligence dossier** that cites the regulation each finding rests on.

### Why now

- **The rules got stricter on the forwarder's side of the desk.** Vietnam's Decree
  259/2025/ND-CP on strategic trade control, in force since 10 Oct 2025, governs dual-use
  goods; Decree 169/2026/ND-CP on customs penalties took effect on 1 Jul 2026. A customs
  broker carries the declarant's obligations (Customs Law 54/2014/QH13, Art. 20(4)).
- **Regulators are naming forwarders.** OFAC has settled with freight and logistics firms
  over shipments they moved — Toll Holdings (2022), C.H. Robinson's non-US subsidiaries
  (2024), Fracht FWO (2025), and Pegasus Worldwide Logistics on 9 Oct 2026. In every one
  the failure was screening, not concealment.
- **Diversion runs through this corridor.** The BIS orders behind our public cases route
  controlled US goods through the UAE, Hong Kong, Turkey, the Maldives and Central Asia,
  and Commerce has found plywood, steel pipe, staples and solar modules completed in
  Vietnam or its neighbours from Chinese inputs.

**Who it is for:** the compliance desk at a freight forwarder or customs broker — the
people who must screen every shipment before it moves and answer for each release to a
customs authority afterwards. Floorline closes the clear cases inside limits that desk
publishes, sends the rest to a person with the evidence attached, and keeps an
append-only record naming who or what allowed each action. The measured detection figures, on
held-out synthetic data and on 19 public enforcement cases, are in
[Measured results](#measured-results).

A shipment event arrives and no one steps it through. Unless the deterministic
pre-filter settles it outright, fraud and compliance screening run in parallel, then the
HS check, the zero-day radar when its gate opens, and the debate when floor and model
disagree. The result decides whether to open a deep investigation, and then the system
acts: releasing the shipment, assigning an analyst, or holding the cargo and drafting a
suspicious activity report for human signature. In the deployed configuration this runs
inside the request that delivered the work, not in a background loop.

End to end, for one case:

> scanned document → Model Armor → document intake (MiniCPM-V) → deterministic risk
> floor and pre-filter → fraud + compliance in parallel (NVIDIA Nemotron 3 Nano, live
> Tavily search) → HS classifier and zero-day radar (Nano) → auto-debate when the floor
> exceeds the model's score by 15+ (Nemotron 3 Super, calling tools) → investigation when
> risk, compliance or a confident DISAGREE calls for it (Nemotron 3 Super, Tavily) →
> delegation gate → release / hold / assign analyst / draft SAR / webhook / Pub/Sub →
> audit trail

The case trace opens on this chain for the case in front of you, with the model that ran
each hop (`frontend/src/lib/case-chain.ts`).

The AI model layer runs on **Nebius Token Factory**: **NVIDIA Nemotron 3 Nano**
for fraud, compliance, HS classification and zero-day screening, **NVIDIA Nemotron 3
Super** for deep investigation and the auto-debate, and
a vision model (**MiniCPM-V-4.5**) for document intake, since
Token Factory does not yet carry an NVIDIA vision model. Infrastructure — Cloud
Run, Firestore, Pub/Sub, Cloud Storage, Model Armor — stays on Google Cloud;
nothing about Nebius's rules requires moving hosting, only that the model calls
actually go to Token Factory, which they do.

---

## The design rule: model capacity only where it can change the answer

This is the one non-obvious decision in the system, and everything else about the model
layer follows from it.

`verifier.py` computes a **deterministic risk floor**, and an agent may **raise** risk but
never lower it below that floor. The rule is asymmetric on purpose: escalating on model
judgement is acceptable, exonerating on model judgement is not, because the cost of a
wrong exoneration is released contraband and the cost of a wrong escalation is a human
spending ten minutes on a clean shipment.

**So Nemotron Nano on fraud and compliance is a choice the floor makes safe, not one it
proves best.** A weak model there can fail to add a hold, but it can never release a
shipment the rules stopped: auto-clear needs a floor of zero (`reconcile()` in
`verifier.py`). Where the floor is zero the model is the only check, so that was measured: on the 179
corpus cases the rules score 0 (52 fraud, 127 honest; flag = model `risk_score` >= 40, a
reply that fails to parse or validate counts as a hold), Nano flagged 46/52 frauds (88%)
[77-95] and Super 47/52 (90%) [79-96], a difference the sample cannot show. Super costs
`$0.00114` a case against Nano's `$0.00026` (4.3×). Honest cases held: Nano 80/127 (63%),
Super 83/127 (65%). Failed replies: Nano 5/179 (2.8%, schema error on `recommendations`),
Super 1/179. On the holdout half Nano flagged 21/24 frauds the rules missed and held
30/53 honest shipments the rules passed; with the rules' own 33 honest holds that is
63/86 (73%) honest holdout shipments held, against 38.4% for the rules alone
(`scripts/compare_fraud_models.py`). Ultra, at 13.3× Nano's per-token rate (16.7× on
input, 12.5× on output; `config.PRICING`), stays priced in config and selectable but is
not used on these calls.

**The debate is the exception: its verdict can change routing, so it was the one hop
measured against Ultra.**
It fires when the floor exceeds the model's score by 15 points or more, so auto-clear is
already ruled out, and what it emits is
not another score for the floor to override — it is a reasoned CONFIRM or DISAGREE on
whether the junior analyst missed something, and that verdict can change routing. In one
direction only: a genuine DISAGREE at confidence 0.7 or above
(`DEBATE_ESCALATE_CONFIDENCE`) sends the case to deep investigation on Nemotron Super
when nothing else would have (effective risk under 70, and compliance not already
`BLOCKED` or `REVIEW_REQUIRED`), and may raise effective risk to the auditor's adjusted
score, never lower it. The case then proposes `ESCALATED` (a hold and a SAR draft)
rather than `HELD_FOR_REVIEW`; the delegation gate executes neither, because
`score_disputed` is a `require_human_when` trigger in the default boundary, so the case
waits in `PENDING_HUMAN` with Super's report attached. CONFIRM, a forced default verdict
or a low-confidence DISAGREE change nothing, and `case.debate_effect` records why. A
person still decides every disputed case. So this is the one hop whose output is a
verdict on the dispute rather than a score the floor overrides, so it was tested against a
larger model. The debate runs on Super by default. On 46 disputed corpus cases (25 fraud,
21 honest) Super reached a verdict on 40 (87%) and Ultra on 37 (80%); Ultra costs `$0.0108`
a debate against Super's `$0.0021` (5.2×) and takes 13.5 s median against 6.4 s. Ultra
disagrees more, not better: DISAGREE on 18/19 frauds (95%) and 17/18 honest (94%) against
Super's 16/22 (73%) and 13/18 (72%), so neither separates fraud from honest trade.
`DEBATE_MODEL=nvidia/Nemotron-3-Ultra-550b-a55b` restores Ultra with no deploy. An earlier
live-service measurement, with real Tavily results, put an Ultra debate at `$0.0198`
against Super's `$0.0015` (13×); that led to this test.

The invariant is not a convention. `reconcile()` sets effective risk to the higher of
the model's score and the floor, and `validate()` computes the floor twice, with and
without the HS classifier's and zero-day radar's findings, and raises if they lowered it:

```python
    base_floor, base_high, _, _ = _floor_for(deterministic_only)
    if floor < base_floor:
        raise AssertionError(
            "model-derived finding lowered the risk floor "
            f"({base_floor} -> {floor}); a model must only ever raise it"
        )
```

That runs on every call. The claim is checked rather than argued, which is the difference
between a design rule and a comment.

Full working, with the measured comparison and the earlier per-call measurements (an Ultra
debate cost 13× a Super one on the live service although Ultra's per-token rate is only
3.3× Super's): *[Why the debate runs on Super, and what was measured](#why-the-debate-runs-on-super-and-what-was-measured)*.

---

## What was significantly updated during the Submission Period

This project began as a Google Cloud entry to a different hackathon, All Things
Agentic 2026, built on Vertex AI Gemini. That entry is public, in the same author's
earlier repository under a second GitHub account:
[CHAUPHUOCHOA/vf-logistics-hackathon-google](https://github.com/CHAUPHUOCHOA/vf-logistics-hackathon-google).
Its first commit is dated 29 Aug 2026, after this hackathon's Submission Period opened
on 26 Aug, and `755d998` (31 Aug) is its last. Every **Before** below describes
`755d998` unless it names a commit of this repository.

The work is measured in two ranges, because this repository does not start where that
one ends. Its first commit, `6bb1e59` (17 Sep), already holds the first step of the
port: the four agents moved to Nebius Token Factory, the Tavily client and the MIT
licence added. Both ranges can be checked from a clone of this repository:

```bash
git fetch https://github.com/CHAUPHUOCHOA/vf-logistics-hackathon-google.git main
git diff --shortstat 755d998 6bb1e59   # the first port step: 32 files, +1,833 / -1,380
git diff --shortstat 6bb1e59 00d896a   # the first ten days, to 27 Sep: 297 files, +171,921, in 49 commits
git diff --shortstat 6bb1e59 d76e64e   # to 14 Oct: 395 files, +199,584 / -6,681, in 131 commits
git diff --shortstat d76e64e febc252 -- src tests frontend   # 14 to 20 Oct, code and console only: 167 files, +23,957 / -292, in 53 commits
```

The ends of the ranges are pinned to commits rather than `HEAD`, which would make the
figures wrong again with the next commit. `d76e64e` is the end of the second range;
the verification-loop fixes of 16–17 Oct (`3e6b1dd` to `443c524`) and the work up to 20 Oct are counted by the third command, which is
limited to `src/`, `tests/` and `frontend/` (its commit count adds `-- src tests frontend` to the command below). Commit counts are from
`git rev-list --count 6bb1e59..<end>`. These commands need the full history: a plain
`git clone` (no `--depth`), or `git fetch --unshallow` first. In a shallow clone
`6bb1e59` is missing and the counts come out wrong.

The deterministic governance layer — risk floor, untrusted-input boundary,
delegation boundary, shipper identity verification — was carried over rather than
rebuilt, because none of it is model-specific. It is what keeps the system honest
regardless of which model is reasoning. Carried over is not the same as untouched. At
`d76e64e`, `untrusted.py` is byte-for-byte the `755d998` file and `shipper_registry.py`
differs by twenty-one lines added and two removed, while `verifier.py` grew from 487
lines to 2,023 (+1,561 / −25) and `governance.py` from 492 to 894 (+449 / −47). The
false-positive tuning below is one of the changes to `verifier.py`.

The areas below were rebuilt.

### The model layer

**Before:** four agents on Vertex AI. Gemini 3.5 Flash for document intake, fraud
and compliance; Flash-Lite for investigation, with `thinking_budget=8000`.

**Now:** seven agents on Nebius Token Factory, three models chosen per job; Ultra stays priced and selectable.
Nemotron 3 Nano runs four hops (fraud and compliance on every case that reaches the
models, HS classification and the zero-day radar when their inputs or gate apply); Super
runs investigation and the auto-debate; MiniCPM-V-4.5 reads documents,
because Token Factory carries no NVIDIA vision model yet.

**Why the split rather than one model everywhere:** `verifier.py` computes a
deterministic risk floor that an agent may raise but never lower, so on fraud and
compliance a weaker model can miss a hold but can never release what the rules stopped;
on score-0 cases Nano flagged 46/52 frauds against Super's 47/52, which the sample cannot tell apart.
The debate is the exception — its CONFIRM/DISAGREE is a verdict that can change routing,
not a score the floor overrides: a confident DISAGREE can send the case to an
investigation it would otherwise skip, and nothing it says can lower risk — so it was the one
hop tested against a larger model: Super `$0.0021` a debate against Ultra's `$0.0108`
(5.2×), with Ultra disagreeing more often rather than separating fraud from honest trade,
so Super is the default.

### Three agents that did not exist

**Before:** intake, fraud, compliance, investigation.

**Now:** plus `hs_classifier_agent.py`, `zero_day_agent.py` and
`debate_agent.py` — 1,751 lines including the chain-of-thought module.

**Why each:**

- **HS classification.** The deterministic checks can compare a declared tariff
  heading against a dual-use prefix list, but cannot tell whether the heading
  matches the cargo actually described. Measured on two sets (`scripts/eval_hs.py`):
  plain Nano reached 40.0% recall on the 30-case pairs set and 50.0% on a 24-case
  holdout of substitutions absent from the reference material, and two few-shot
  examples made it **worse** on both, at 26.7% and 33.3%. Structured reasoning over a
  reference extract of the published heading contents — the production mode — took
  it to **92.9%** recall at 100% precision on the pairs and **91.7%** (11 of 12)
  on the holdout with 0 of 12 honest cases flagged. Examples did not help; reasoning
  against the published headings did. Full table: *[HS classification, measured](#hs-classification-measured)*.
- **Zero-day screening.** Sanctions lists lag reality. This runs a live
  adverse-media search when a shipment trips a code gate: a dual-use heading, a
  high-risk destination, two or more distinct transhipment hubs, or a shipper with at
  most one prior shipment on record (which covers every uploaded document whose shipper
  is not in the counterparty book).
- **Auto-debate.** Fires with no human involved when the floor exceeds the model's
  score by 15 points or more. Its verdict used to be recorded and read by nothing;
  a genuine, confident DISAGREE now sends the case to the deep investigation it would
  otherwise skip and may raise its risk, never lower it. A person still decides the
  case.

### The console

**Before:** one static HTML page served by Flask from `static/`.

**Now:** a Next.js 16 console — 107 files and 20,657 lines of TypeScript at `d76e64e`,
tests excluded. It began as seven screens over the operational API, since joined by Access
Control (`/admin`), Evaluation (`/evaluation`), three operator screens for the
verification loop (`/today`, `/cases/<id>`, `/outcomes`) and a public upload page for
shippers (`/respond/<token>`). It started on a Cloud Run service of its own; it now runs in the same
container as the API, one service (`vf-app`) with Next.js on `$PORT` and Flask on
`127.0.0.1:9090` behind it. The old page is still bundled, at `/legacy` when Flask
runs on its own; the deployed container does not pass that path through.

**Why:** the static page could not carry sessions, and the submission needed a
reviewer to sign in before recording a decision. That requirement is the next item.

### Accountability in the audit trail

**Before:** the `reviewer` field was read from the **request body as free text**.
Anyone could record a decision under anyone's name, which makes an audit trail
decoration rather than evidence.

**Now:** HMAC-signed sessions (`auth.py`, 1,125 lines), operator records as
PBKDF2-SHA256 in `VF_OPERATORS`, and the audit entry names the authenticated
account.

### Who could act on the live service

**Before:** no authentication at all. Every endpoint of `755d998`,
`POST /orchestrator/reset` included, answered anyone who had the URL. Mid-port it was
no better: the console's proxy attached the operator API key to every request and
there was no login yet, so any anonymous visitor held `GOVERNANCE_ADMIN` on the
deployed console, and an unauthenticated `POST /orchestrator/reset` cleared 307 real
cases — found by doing it.

The login closed writes and left the roles decorative. The console still attached its
key to every request, anonymous reads included, and that key grants `governance_admin`
— so every visitor was an admin on every read, and every signed-in user was one on
everything.

**Now:** the code default is `ANONYMOUS_ROLE=viewer` (the deployed service sets `none`), `X-VF-API-Key` required on writes, and the split
is on the HTTP method rather than a path list, so a route added later is covered by
default. The console attaches its key **only alongside a verified session**, and the
backend looks the signed-in email up in `ADMIN_EMAILS` / `OPERATOR_EMAILS` /
`REVIEWER_EMAILS`: the session can only narrow what the key grants, never widen it,
an unlisted address is a viewer, and a session that fails to verify alongside a valid
key is refused with 401 rather than falling back to admin. `GET /api/v1/auth/whoami`
and `GET /api/v1/auth/policy` say what was resolved and what every route enforces, and
the Access Control screen (`/admin`) shows both from the running API. Plus
request-size caps, batch caps and rate limits.

### Cost, which turned out not to be where we assumed

**Before:** an estimate, not metering. `755d998` priced each step's tokens for
whichever cases the dashboard had fetched, so the total changed with the page size;
nothing capped spend, and no agent capped its output. That last gap survived the port:
`max_tokens` was set on **no agent at all**, Token Factory's default is 8,192, and two
runaway calls hit that ceiling and both returned unparseable output after spending
for it.

**Now:** per-hop cost attribution (`lineage.py`), a per-tenant soft ceiling checked
at the single chokepoint every model call passes through (`budget.py`), a ratchet
that refuses a runtime model switch past a rate multiple of the cheapest model, and
a measured `max_tokens` on every agent.

**The finding worth reporting:** **Tavily, not the models, is the binding
constraint.** A 20-case run spends `$0.068`–`$0.088` on inference and 90–106 Tavily
searches, so on the free search tier the quota runs out around 200 cases while
model spend is still negligible. Every cost figure we had published until then was
a model-cost figure.

### False positives, measured on a held-out split

**Before the tuning in `8b798cc`:** the deterministic layer caught nearly every attack
in the synthetic corpus and held most of the clean traffic with it — on the holdout
split, a false-positive rate of 76.7%.

**Now:** 38.4% (95% interval 28–49%, on 86 clean cases), with precision 84.1% →
91.2% and recall 95.1% → 93.5%, and
sanctions-alias and shell-company detection unchanged at 100%. Two signals that
separated nothing became *observations* — shown to the reviewer as context, with no
floor, not counted as findings — and the tuning was chosen on the dev split only.

**Why the split:** a number measured on the cases a threshold was chosen against says
how well it was chosen, not how well it works. Detail and caveats:
*[The detection benchmark](#the-detection-benchmark)*.

### Tests and CI

**Before:** no unit tests in `755d998`, only a self-check script for the counterparty
book. This repository's first commit added one test file, `scripts/test_documents.py`,
which drives a deployed service over HTTP.

**Now:** **2,095 backend tests** pass in CI with none skipped, at 96% line coverage (CI
runs them inside the Firestore and Pub/Sub emulators, so the `FirestoreStore` tests
run for real; without the emulators the 18 emulator tests and the store parity suite
skip). The console has 1,729 frontend tests at 61.6% line coverage. A mutation check —
`scripts/check_test_sensitivity.py`, which can resume from an index — breaks 112 lines of
backend and console code on purpose and the suite catches all 112. mypy reports 0 errors.
Five GitHub Actions jobs run on every push to `master`: lint, typecheck (mypy ceiling 0),
test (backend coverage floor 92%, in the emulators), frontend (coverage floor 35%), and a
container job that builds both images and smoke-tests the deployed one. `755d998` had no test or lint CI, only a Cloud Build deploy config. The workflow
added here on 19 Sep (`ae240fb`) filtered on a branch named `main` while this
repository uses `master`, so it never executed until `9d683f6` fixed the trigger on
24 Sep.

### Structure

**Before:** a flat repository root — `main.py`, `orchestrator.py`, `agents/` and
fifteen other modules at top level.

**Now:** a `src/vf_logistics/` package with seventeen modules that did not exist at all:
`auth.py`, `b2b.py`, `budget.py`, `decision_receiver.py`, `dossier.py`, `evaluation.py`, `evidence.py`,
`hs_reference.py`, `lineage.py`, `membership.py`, `observability.py`, `openapi.py`,
`sanctions.py`, `sanctions_sources.py`, `schemas.py`, `tenant.py`, `worklist.py`. That
excludes `nebius_client.py` and `tavily_client.py`, which came with the first port step,
and the new agents above.

## What the system does

Seven specialised agents plus a deterministic verification layer, coordinated by a
governance control plane:

| Agent | Responsibility | Model | Notable config |
|---|---|---|---|
| **Document Intake** | Transcribes bills of lading, invoices and packing lists into a structured record. Reports missing fields as missing rather than inventing them. | `openbmb/MiniCPM-V-4_5` | `temperature=0.0`, multimodal image input (PDFs rasterised first) |
| **Fraud Detection** | Price manipulation, route fraud, weight/dimension fraud, document fraud, identity fraud, duplicate & time fraud. | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | `temperature=0.1` for stable scoring |
| **Compliance Screening** | Sanctions exposure (OFAC/UN/EU patterns), trade & regulatory compliance, AML indicators — grounded by a live Tavily search. | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | `temperature=0.1`, runs in parallel with fraud, Tavily search injected as evidence |
| **HS Classification** | Whether the declared HS heading matches the cargo described, reasoned against the published heading contents. | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | `cot_strict` prompt, `temperature=0.0`; runs when goods and HS code are both stated |
| **Zero-Day Radar** | Adverse-media search for parties no sanctions list has caught up with. | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | Tavily news tool, last 45 days; only when its code gate opens |
| **AI Investigation** | Multi-step case investigation, pattern analysis, network mapping. | `nvidia/nemotron-3-super-120b-a12b` | Only where compliance returned `BLOCKED` or `REVIEW_REQUIRED`, risk reached 70, or the debate confidently disagreed |
| **Multi-Agent Debate** | Senior Auditor (Super) reviews Junior Analyst (Nano) fraud assessment using function calling. Can request re-evaluation, run Tavily searches, and render CONFIRM/DISAGREE verdicts. A confident DISAGREE can send the case to an investigation it would otherwise skip; nothing it says can lower risk. | `nvidia/nemotron-3-super-120b-a12b` (default; `DEBATE_MODEL` can restore Ultra) | Fires automatically on a 15-point floor-model gap; also manual via "Deep Review". Function calling with 3 tools |

### Model selection, chosen per task

The hackathon's own model guidance is: let Nano or Super handle the fast,
everyday calls, and reach for Ultra when you need serious reasoning. This
system follows that shape, and tested the top rung on the one hop where it could matter:

Fraud and compliance screening run on **Nemotron 3 Nano** — every shipment
that reaches the models is scored by both, so this is the highest-volume call in the
pipeline. Nano is also fast and cheap. The floor is what makes that safe: these two
hops cannot release anything the rules stopped, so a weaker model here costs missed
holds on cases the rules found clean, never a release of flagged cargo. On score-0 cases Nano flagged 46/52
frauds against Super's 47/52, at a quarter of the cost per case — see *[The design rule](#the-design-rule-model-capacity-only-where-it-can-change-the-answer)*.

Investigation runs on **Nemotron 3 Super** — by the time a case reaches it, the
fraud and compliance findings already exist; it runs only where compliance returned
`BLOCKED` or `REVIEW_REQUIRED`, effective risk reached 70, or the Senior Auditor
confidently disagreed, so it is the low-volume, high-stakes call that can afford a
stronger, pricier model.

The debate agent also runs on **Nemotron 3 Super**. It was measured against Nemotron 3
Ultra, its previous default: Ultra reached a verdict on fewer disputes (37/46 against
40/46), cost 5.2× as much, was slower, and disagreed more often without separating fraud
from honest trade. See
[Why the debate runs on Super, and what was measured](#why-the-debate-runs-on-super-and-what-was-measured).
`DEBATE_MODEL` restores Ultra with no deploy. Investigation is 40% of measured spend
already, and `INVESTIGATION_MODEL` can point it at Ultra if more Token Factory credit
becomes available.

Document intake is the one agent that needs a vision-capable model, and
NVIDIA does not currently publish one on Token Factory, so it runs on
**MiniCPM-V-4.5**, a model the catalog specifically calls out for OCR/PDF
understanding.

Nano, Super (and Ultra, if selected) and MiniCPM-V are reached through the same
OpenAI-compatible endpoint (`nebius_client.py`), so the split costs no extra
integration surface. Fraud, compliance, HS classification and document intake are
requested in JSON mode (`response_format={"type": "json_object"}`); zero-day and
the debate reply through tool calls. Investigation is the exception: Super is asked
for JSON by its prompt alone, because with `json_object` on, its reasoning leaked into
the constrained output and only 6 of 12 replies were usable, against 12 of 12 without
it. Every reply is parsed server-side and checked against its agent's schema
(`schemas.AGENT_OUTPUT_SCHEMAS`); an investigation that fails it is asked once more,
and both calls are billed. Every agent response envelope records which model
produced it, visible in the per-case trace in the dashboard.

### A real Tavily call, not a simulated one

The compliance agent's sanctions screening used to rely entirely on the
model's training-time knowledge of who is on OFAC/UN/EU lists. That is
static and can go stale. Before scoring a shipment, the agent now calls
`tavily_client.search_cached()` with the shipper and receiver names (e.g. `"<name>"
sanctions OR fraud OR "shell company"`), and the results are folded into the
model's context as a clearly labelled, untrusted evidence block — a real
runtime web search, not a documented-but-unused integration. A Tavily outage
or a missing API key never blocks the pipeline, and it is not passed off as a clean
result either: the search status goes into the prompt (the worse of the shipper and
receiver searches), so the model is told a search failed rather than that it found
nothing.

### Multi-Agent Debate: Super reviews Nano

The most sophisticated reasoning pattern in the system is **Multi-Agent Debate**,
where a Senior Auditor (Nemotron Super 120B) reviews the Junior Analyst's
(Nemotron Nano 30B) fraud assessment.

**Why two models?** Nano is fast and cheap — it scores every shipment that reaches the
models.
But speed optimises for throughput, not for catching the subtle case that slips
through. Super is slower and costs more, but it can challenge Nano's reasoning
and catch what Nano missed. The debate is asymmetric: Super can call Nano back
for a re-evaluation with specific focus areas, but Nano never calls Super.

**Function calling, not prompt chaining.** Nemotron Super supports native
tool_calls, so the debate agent uses real function calling with three tools:

| Tool | Purpose |
|---|---|
| `request_nano_reevaluation` | Ask Nano to re-score the shipment with specific focus areas (pricing, identity, route, documents, timing) and a hypothesis about what it might have missed |
| `search_tavily` | Run an additional web search for context (e.g., "Thanh Phat Trading sanctions Vietnam") |
| `render_final_verdict` | Submit the final verdict: **CONFIRM** (agree with Nano) or **DISAGREE** (found issues Nano missed), with confidence, rationale, and recommended action |

The auditor iterates through tool calls until it calls `render_final_verdict`, up to
3 rounds. The debate is recorded on the case and rendered on the review page and in
the case trace as a readable panel — verdict, confidence, rationale, what it changed,
and the rounds — with the raw record one click away, so the analyst sees exactly what
the auditor did.

**When it runs.** The debate fires **automatically**, with no human involved, when
the deterministic floor exceeds the model's score by 15 points or more — measured at 2
calls across 20 cases. A reviewer can also trigger it manually as "Deep Review"
when:
- The risk score seems too low for the red flags present
- The shipper or receiver name sounds suspicious
- The case is borderline and the analyst wants a second opinion

On Super it measured `$0.0021` a debate and 6.4 s median; Ultra, selectable with
`DEBATE_MODEL`, measured `$0.0108` and 13.5 s (an earlier live-service run with real
Tavily results put Ultra at `$0.0198` against Super's `$0.0015`, and 14–22 seconds against
4–6). See
[Why the debate runs on Super, and what was measured](#why-the-debate-runs-on-super-and-what-was-measured)
for the comparison.

**What the automatic verdict changes, and what it cannot.** It never overrides a
person's decision, and it can only push a case upward. A genuine DISAGREE at confidence
0.7 or above (`DEBATE_ESCALATE_CONFIDENCE`) sends the case to deep investigation on
Nemotron Super where its risk alone (under 70) and its compliance status would not have,
and may raise effective risk to the auditor's adjusted score, never lower it. The case
then proposes `ESCALATED` rather than `HELD_FOR_REVIEW`. CONFIRM, a forced default
verdict or a low-confidence DISAGREE change nothing, and `case.debate_effect` records
which applied. Before this the verdict was recorded and read by nothing, so the debate
could not change a single outcome. A disputed case still
goes to a person either way, because `score_disputed` is a `require_human_when` trigger
in the delegation boundary: the gate refuses the hold, nothing is executed (no hold, no
SAR draft, no webhook), and the case waits in `PENDING_HUMAN` with the investigation's
narrative for the reviewer. A manual Deep Review runs on a case already waiting
for a person and is recorded as evidence for them; it reroutes nothing.

### The agents are not trusted

This is the part that matters most. Every agent above is a language model, and a
language model can be mistaken, overconfident, or manipulated by the very
document it is reading. The pipeline holds and releases physical cargo, so agent
output is treated as a **claim**, not a finding.

[`verifier.py`](src/vf_logistics/verifier.py) recomputes what can be computed. Freight against
lane baselines, value per kilo, mandatory-field completeness, HS code validity
against a dual-use watchlist held as a code constant, high-risk routing,
counterparty history. No model is consulted, because
`shipping_cost / avg_route_cost` is a division.

Those checks produce a **risk floor**, and the governing rule is asymmetric:

> An agent may **raise** risk. It may never **lower** risk below the
> deterministic floor.

Escalating on model judgement is acceptable; exonerating on model judgement is
not, because a wrong exoneration releases contraband and a wrong escalation costs
a reviewer ten minutes.

Three inputs are deliberately excluded from the document schema in
[`untrusted.py`](src/vf_logistics/untrusted.py): `avg_route_cost`, `shipper_tx_count` and
`created_at`. A document that could state its own route average would defeat the
pricing check by setting it low, and one that could state its own shipper history
would defeat the counterparty check by claiming a long one. Absent history is
treated as unverified, and unverified is not clean.

That exclusion leaves a gap the design has to close somewhere else. Absent
history sets a floor of 45, above the auto-clear threshold of 40, so for a while
*no* uploaded or staged document could clear autonomously — the control was
written around an enrichment step that did not exist yet.
[`shipper_registry.py`](src/vf_logistics/shipper_registry.py) is that step: it resolves the
claimed shipper against our own counterparty book and supplies the trading
history the document is not allowed to assert about itself. Identity must match
on tax ID **and** company name together, because the tax ID is itself read off
the untrusted document — a forged bill of lading carrying a real customer's
number would otherwise inherit that customer's clean history. A number that
matches under a different name is reported as `identity_mismatch` and treated as
worse than unknown.

The human-feedback loop follows the same rule. Two human blocks of a shipper add 15 to
its effective risk, and that may key on the free-text shipper name, because raising risk
is always safe. Five human releases take 10 off, and that discount applies only to a
shipper whose identity the registry verified, counting only human releases of that same
verified counterparty: keyed on the name, a document could borrow any customer's clean
history by typing it. In practice the discount is available only to counterparties in
our book, and it never takes risk below the deterministic floor. The tallies are read
fresh from the store on every scored case, because a cache dropped in one Cloud Run
instance could miss a block recorded on another.

The withheld fields are also reported to the fraud agent as *not available*
rather than as a bare `N/A`, with an instruction that their absence says nothing
about the shipment. The deterministic floor, not the model, remains the thing
that penalises genuinely unverified history.

### Authority is published, not earned

An agent here does not acquire the right to act by reasoning well. A human
publishes a versioned, machine-readable **Delegation Boundary**, and the agent
operates inside it.

That is what keeps this both autonomous and governable. The human is not
approving shipments one at a time — that would be a slow human process with extra
steps. The human approves **policy**, once, and cases execute against it without
supervision. Only cases that fall outside the published boundary come back to a
person.

With no active boundary the system is **SUSPENDED** and fails closed: it still
analyses and proposes, but [`governance.py`](src/vf_logistics/governance.py)'s execution gate
refuses every protected action.

The release path fails closed on the shipment's side too. The orchestrator proposes an
automated release only when compliance returned exactly `CLEARED` (an allowlist: an
`UNKNOWN` or off-schema status used to clear, and now goes to review at HIGH priority)
and `reconcile()` explicitly permitted it, which it never does without a stated risk
floor. The gate then refuses a release when the deterministic finding count is missing
(while the boundary keeps its default zero-findings rule), when the declared value is
absent, unreadable, NaN or negative, or when the destination is blank while the boundary
lists excluded destinations. Each of those used to read as
zero or as nothing to check.

That is the model path. Separately, the deterministic pre-filter releases a whitelisted
or low-value domestic shipment with no model call at all: compliance is recorded as
`COMPLIANT`, lesser findings are set aside, and the fast path is withdrawn by any HIGH or
CRITICAL finding or any finding that blocks auto-clear (a watched-lane origin finding is
one). That release still passes the same gate: risk at most 39, zero counted findings,
declared value at most 25,000 USD, no excluded HS prefix or destination. At the time of
writing, both automatic releases on the live board are of this kind; no case there has
been released automatically on a model's score.

### The reviewer always has the paperwork

Work enters two ways. A shipment event arrives on `/api/v1/events/shipment`, or a
document is uploaded — drag a PDF or a scan onto the **Document intake** card, or
use the file picker; both paths run the same code. In the deployed
`WORKER_MODE=ondemand` configuration the upload request also advances the case,
usually all the way to a terminal state before it responds.

Whichever way it arrived, **a case is meant to carry a bill of lading a human can
read.** When a shipper's original was uploaded it is archived to Cloud Storage and
shown as-is to a signed-in reviewer. When the case came from a data event there is no
original, so
[`document_render.py`](src/vf_logistics/document_render.py) renders one from the record and marks
it `SYSTEM-GENERATED` — on the document itself and in the case provenance
(`generated: true`, `rendered_from`). A reconstruction is never presented as an
original.

### The case as a due-diligence dossier

A customs broker carries the declarant's obligations — Vietnam's Customs Law
(54/2014/QH13) says so in Art. 20(4) — so when a shipment is questioned later, "the model
scored it 85" is not an answer. **Due-diligence dossier (PDF)** on the case trace and the
Review screen (`GET /api/v1/orchestrator/case/<id>/dossier`) renders the record a
forwarder files: the outcome and who decided it, the shipment as declared, the sanctions
list it was screened against and that list's date, every finding with the action it
calls for and the text it rests on, a comparable public enforcement case, the
specialists' views, and provenance.
[`dossier.py`](src/vf_logistics/dossier.py) builds it in code from the stored case; the
only model-written text is the agents' own recorded conclusions, labelled as such. Every
reference below was checked against a fetched copy of the source.

| Finding | Rests on | Comparable public case |
|---|---|---|
| `SANCTIONS_MATCH`, `HIGH_RISK_DESTINATION`, `HIGH_RISK_TRANSIT` | OFAC SDN and UN SC Consolidated List; Customs Law Art. 18 / 20(4); EAR Part 732 Supp. 3 | [OFAC 2022, Toll Holdings](https://ofac.treasury.gov/recent-actions/20220425): a forwarder, "to, from, or through" DPRK, Iran, Syria |
| `DUAL_USE_HS_CODE`, `HS_DESCRIPTION_MISMATCH_DUAL_USE` | [Decree 259/2025/ND-CP](https://luatvietnam.vn/xuat-nhap-khau/nghi-dinh-259-2025-nd-cp-ve-kiem-soat-thuong-mai-chien-luoc-414787-d1.html) on strategic trade control; EAR Part 732 Supp. 3 | [BIS 2023](https://www.govinfo.gov/content/pkg/FR-2023-11-14/html/2023-25005.htm): microcontrollers via a UAE free-zone consignee to Russia |
| `HIGH_RISK_ORIGIN` | OFAC / UN lists; [Customs Law Art. 18 / 20(4)](https://luatvietnam.vn/xuat-nhap-khau/luat-hai-quan-2014-so-54-2014-qh13-87932-d1.html) | [EPPO 2024](https://www.eppo.europa.eu/media/news/germany-eppo-brings-charges-against-two-evading-anti-dumping-duties-aluminium-foil-imports-2024-07-29_en): Chinese foil declared as Myanmar origin |
| `MULTIPLE_DIVERSION_HUBS`, `ROUTE_CHANGED_AFTER_BOOKING` | [EAR Part 732 Supp. 3](https://www.law.cornell.edu/cfr/text/15/appendix-Supplement_No_3_to_part_732), red flag 10: route abnormal for the product | [BIS 2023](https://www.govinfo.gov/content/pkg/FR-2023-05-19/html/2023-10750.htm): brakes to a Maldives agent, destination changed after a forwarder's warning |
| `SHIPPER_NO_HISTORY`, `RECENTLY_REGISTERED_SHIPPER` | EAR Part 732 Supp. 3, red flag 4: little or no business background | — |
| `VALUE_DENSITY_*`, `FREIGHT_ANOMALY` | Customs Law Art. 18; [Decree 169/2026/ND-CP](https://luatvietnam.vn/thue/nghi-dinh-169-2026-nd-cp-quy-dinh-xu-phat-vi-pham-hanh-chinh-trong-linh-vuc-hai-quan-435022-d1.html) on customs penalties | [BIS 2022](https://www.govinfo.gov/content/pkg/FR-2022-12-16/html/2022-27347.htm): a USD 25,000 oscilloscope declared at USD 2,482 |
| `HS_DESCRIPTION_MISMATCH` | Customs Law Art. 18; Decree 169/2026/ND-CP | [EPPO 2024](https://www.eppo.europa.eu/media/news/spain-five-directors-two-companies-indicted-evading-anti-dumping-duties-steel-sheets-2024-09-24_en): finished sheet declared as slab |
| `BLACKLIST_*`, `ZERO_DAY_*`, identity mismatches | the forwarder's own policy | — |

The dossier is not legal advice and says so on the page: a reference says where an
obligation comes from, not that it has been met.

---

## Architecture

```
       Browser: the console screens          API clients, Pub/Sub push
       at /  (reads via /api/proxy/*)        at /api/v1/*
                    |                                  |
                    v                                  v
      +---------------------------------------------------------------+
      |  Cloud Run  ·  asia-southeast1  ·  vf-app  ·  one container   |
      |                                                               |
      |  Next.js 16 on $PORT, the only port Cloud Run routes to       |
      |    /api/proxy/*   the console's BFF, allow-listed per method; |
      |                   attaches the console's key only alongside   |
      |                   a verified session                          |
      |    /api/v1/*, /health, /metrics, /demo                        |
      |                   passed through with the caller's own        |
      |                   credential, nothing added                   |
      |                 |                                             |
      |                 v                                             |
      |  gunicorn --> Flask (vf_logistics.app:app) on 127.0.0.1:9090  |
      |                 |                                             |
      |      agents/ (openai AsyncOpenAI, async)                      |
      |       +- document_agent.py                                    |
      |       +- fraud_detection_agent.py                             |
      |       +- compliance_agent.py        *                         |
      |       +- hs_classifier_agent.py                               |
      |       +- zero_day_agent.py          *                         |
      |       +- investigation_agent.py     *                         |
      |       +- debate_agent.py            *                         |
      |       * search via tavily_client.py --> Tavily Search API     |
      +-------------------------------+-------------------------------+
                                      |  nebius_client.py (OpenAI-compatible)
                                      v
                 +-----------------------------------------+
                 |  Nebius Token Factory                   |
                 |    NVIDIA Nemotron 3 Nano               |
                 |      fraud · compliance · HS · zero-day |
                 |    NVIDIA Nemotron 3 Super              |
                 |      investigation · the auto-debate    |
                 |    MiniCPM-V-4.5 (vision)               |
                 |      document intake                    |
                 +-----------------------------------------+

  Google Cloud infrastructure, unchanged: Firestore (case state, audit log),
  Pub/Sub (shipment-events in, case-decisions out), Cloud Storage (document
  archive), Model Armor (prompt-injection screening).
```

### The autonomous workflow

```
  Pub/Sub shipment-events ---+
  Scripted simulator      ---+--> POST /api/v1/events/shipment
                             |            |
                             |            v
                             |    Firestore cases (state INGESTED)
                             |
     orchestrator.py advance(): claims a case under a lease, performs exactly one
     step, persists. Deployed (WORKER_MODE=ondemand) it runs inside the request
     that delivered the work; WORKER_MODE=poll runs it in an asyncio loop instead.
                             |
       INGESTED --> verifier.validate(): risk floor and pre-filter
          |
          +-- pre-filter settles it, no model:
          |     whitelist / low-value domestic --> AUTO_CLEARED  release_shipment()
          |     blacklist --> proposes ESCALATED; compliance is BLOCKED, so the
          |                   default boundary refuses the hold --> PENDING_HUMAN
          |
          +-- grey area:
                fraud (Nano) || compliance (Nano + Tavily) || route search (Tavily)
                --> HS classifier (Nano), if goods and HS code are stated
                --> zero-day radar (Nano + Tavily), if its code gate opens
                --> re-validate --> auto-debate (Super), if floor - model >= 15
                --> SPECIALISTS_DONE
                      |
                      +-- risk < 40, floor 0, compliance exactly CLEARED,
                      |   no model failure --------------> AUTO_CLEARED
                      |                                      release_shipment()
                      |
                      +-- compliance BLOCKED / REVIEW_REQUIRED, risk >= 70,
                      |   or a confident Senior Auditor DISAGREE
                      |         |
                      |         v
                      |   investigation agent (Nemotron Super) --> ESCALATED
                      |                                      hold_shipment()
                      |                                      draft_sar()
                      |                                      notify_webhook()
                      |                                      assign_analyst()
                      |
                      +-- otherwise -----------------------> HELD_FOR_REVIEW
                                                             assign_analyst()

       Any action the delegation boundary refuses ----------> PENDING_HUMAN
         (under the default boundary: compliance BLOCKED, a disputed score --
          so every debated case -- or an injection; nothing in the pack runs)
       Any step failing 3 times, with 5s/10s/20s backoff --> DEAD_LETTER

       Model-path decisions the gate allows, and verification-loop executions,
       are published to Pub/Sub case-decisions for downstream ERP / WMS /
       billing. Pre-filter outcomes, refused proposals and releases or blocks
       through /decide are recorded in audit_log only. Every action lands there.
```

Thresholds are environment variables (`FRAUD_CLEAR_BELOW`, `INVESTIGATE_AT`), so
the routing policy is configuration rather than something buried in code. So is the
debate's: `DEBATE_ESCALATE_CONFIDENCE`, default 0.7, is the confidence a genuine
DISAGREE needs before it can send a case down the investigation branch that it would
otherwise have skipped.

### Why these choices

- **OpenAI-compatible client, one wrapper for every model** — `nebius_client.py`
  wraps `openai.AsyncOpenAI` pointed at Token Factory; all the Nemotron tiers (Ultra too, if selected)
  and the vision model are reached the same way, so adding or swapping a model
  is a string change, not a new integration.
- **Async calls, gunicorn `--threads 8`** — a single instance handles concurrent
  analyses while each waits on model latency.
- **`WORKER_MODE=ondemand` with `--min-instances=0`** — cases advance *inside*
  request handlers: the Pub/Sub push, the document upload, and the dashboard's
  own state poll each carry the pipeline forward a step. The poll does so only for
  an operator credential — an anonymous or reviewer poll gets the board and no side
  effect — and it waits at most 4 seconds for that step, with one drain in flight per
  tenant, where it used to block for up to 120 seconds. The service scales to zero
  when no shipment exists.
- **One container, two processes** — Next.js listens on `$PORT`, the only port Cloud
  Run routes to; Flask listens on `127.0.0.1:9090` behind it and is reachable only
  through Next (`entrypoint.sh` starts Flask, waits for `/health`, then starts Next).
  `/api/proxy/*` is the console's allow-listed BFF
  ([`proxy-policy.ts`](frontend/src/lib/proxy-policy.ts)) and the only place the
  console's key is attached; `/api/v1/*`, `/health`, `/metrics` and `/demo` are the
  public API, passed through with the caller's own credential
  ([`upstream.ts`](frontend/src/lib/upstream.ts)). The runtime stage installs nothing
  from a package repository — Node is copied out of a digest-pinned image — and
  `Dockerfile.backend` remains as an API-only image for running Flask alone.
- **Claims are leases, not locks** — a case claimed by an instance that then
  crashes or is replaced mid-rollout becomes claimable again after
  `CLAIM_LEASE_SECONDS`.
- **Firestore with an in-memory fallback** — `STORE_BACKEND=memory` runs the
  whole pipeline with no database, so the demo cannot be blocked by
  provisioning.
- **PDF pages are rasterised before reaching the vision model** — Token
  Factory's vision models, like most OpenAI-compatible vision endpoints, take
  images (`image_url` data URLs), not raw PDF bytes the way Gemini's native
  multimodal input did. `pypdfium2` renders the first page to PNG in
  `document_agent.py` before the call.
- **Tavily failures degrade, not block, and are named** — a missing key, a timeout
  or a non-2xx never fails the case, and where a model reads the results
  (`search_cached()` and `search_with_status()`) the failure status goes with them, so
  an outage is not read as "searched, found nothing".

---

## Tech stack

| Layer | Choice |
|---|---|
| Model | **NVIDIA Nemotron 3 Nano** (fraud, compliance, HS classification, zero-day radar) + **NVIDIA Nemotron 3 Super** (investigation and Senior Auditor debate) + **MiniCPM-V-4.5** (document intake, vision), all via **Nebius Token Factory** |
| Agent framework | `openai.AsyncOpenAI` (Token Factory's OpenAI-compatible endpoint) |
| External signal | **Tavily Search API** — live sanctions/news lookup in compliance, route validation, investigation, the zero-day radar, the debate and the Governance scan |
| Input security | **Model Armor** (Google Cloud) — windowed prompt-injection screening |
| Compute | **Cloud Run** (source deploy -> Cloud Build -> Artifact Registry) |
| State | **Firestore** (Native mode) — cases, events, audit log, delegation boundaries and four more collections |
| Messaging | **Pub/Sub** — `shipment-events` in, `case-decisions` out |
| Web | Flask + gunicorn, flask-cors |
| Console | **Next.js 16** (App Router, React 19, Tailwind, TanStack Query), in the same container and Cloud Run service as the API |
| Runtime | One `python:3.11-slim` container with the Node binary copied from a digest-pinned `node:22-slim` image; the runtime stage installs nothing from a package repository |

### Where Token Factory and the NVIDIA models did the work

The rules ask submissions to say where Token Factory accelerated the workflow and which
NVIDIA open models were used, so this is that answer in one place rather than spread over
the sections above.

**The NVIDIA open models, and what each one is for.** Three sizes of Nemotron 3, picked per
task rather than one model everywhere:

| Model | Where it runs | Why this size |
|---|---|---|
| `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | fraud, compliance, HS classification, zero-day radar — fraud and compliance on **every** case that reaches the models, the other two when their inputs or gate apply | `verifier.py` computes a deterministic risk floor an agent may raise but never lower, so a weaker model here can miss a hold but never release what the rules stopped; on score-0 cases Nano flagged 46/52 frauds against Super's 47/52, no difference the sample can show |
| `nvidia/nemotron-3-super-120b-a12b` | investigation and the auto-debate ("Senior Auditor") | investigation writes the narrative a human reads; the debate's verdict can change routing, upward only, and measured against Ultra on 46 disputed cases Super reached a verdict on 40 to Ultra's 37 at `$0.0021` a debate against `$0.0108` |
| `nvidia/Nemotron-3-Ultra-550b-a55b` | optional: `DEBATE_MODEL` selects it for the debate | not used by default; it disagreed more often than Super without separating fraud from honest trade, at 5.2× the cost per debate |
| `openbmb/MiniCPM-V-4_5` | document intake (vision) | not an NVIDIA model, and said plainly: Token Factory carries no NVIDIA vision model yet |

**Where Token Factory accelerated the workflow.** Every model, from 30B to 550B plus a
vision model, are served by **one** OpenAI-compatible endpoint
(`https://api.tokenfactory.nebius.com/v1/`) through `openai.AsyncOpenAI` — `nebius_client.py`
is a thin wrapper, not a bespoke SDK. Three consequences that shaped the build:

- **Model choice became a config value, not an infrastructure change.** `config.py` holds
  the ids and per-token prices; `set_model` swaps them per task. Escalating one hop from
  Nano to Super to Ultra is a string, so the HS experiment — plain Nano, few-shot,
  structured reasoning, reasoning over the published headings, and Super as the teacher
  — cost nothing in plumbing. It took Nano from 40.0% to 92.9% recall on the pairs set
  and from 50.0% to 91.7% on the holdout.
- **No GPU provisioning, so a 550B model could be tried on the debate path.** Ultra was the
  debate default until it was measured against Super; it stays selectable with
  `DEBATE_MODEL`. Standing up 550B of capacity for an occasional comparison would not have
  been worth it; per-token access made it practical to test.
- **The port from the predecessor was a client change, not a rewrite.** The JSON contract
  each agent returns was preserved, so swapping Vertex AI Gemini for Token Factory changed
  the base URL, the model ids and the sampling parameters — not the pipeline.

**Other Nebius services used: none.** Token Factory's inference API is the whole Nebius
surface here. Nebius AI Cloud, including Serverless Endpoints and Serverless Jobs, is
encouraged by the track and is **not** used — the service runs on Cloud Run, which is
stated rather than dressed up.

**Tavily**, which is a separate bonus track, is a live runtime call in six places, not a
stub: compliance screening, route validation, investigation, the zero-day radar, the
debate's search tool, and the Governance page's sanctions scan and entity check. See
*A real Tavily call, not a simulated one* above.

### Requirement check against the hackathon rules

Checked against the Official Rules for this Hackathon. An earlier version of this table
checked against the **predecessor** hackathon's criteria — it listed "multi-step autonomous
workflow" and "takes meaningful action", which are not requirements here, and omitted the
track, the video, the feedback and the licence, which are.

| Rule | Where it is met |
|---|---|
| Runtime call to Nebius Token Factory | every one of the seven agents |
| At least one NVIDIA open source model | Nemotron 3 Nano and Super in use, Ultra selectable; table above |
| Fits one of the four tracks | **Best Apps and Agents** |
| Significantly updated after the Submission Period opened (26 Aug 2026) | every commit in this repository is dated 17 Sep 2026 or later (first `6bb1e59`, 17 Sep; last change to `src/` and `tests/` `2842358`, 20 Oct); `git log --reverse --format="%ai" \| head -1` shows the first, in a full (not shallow) clone |
| Written explanation of what was updated | *What was significantly updated during the Submission Period*, above |
| URL to a working demo | the `vf-app` URL at the top of this file: the console at `/`, the API under `/api/v1` |
| Public repository with a detectable open source licence | GitHub reports this repository's licence as **MIT** |
| README with setup and running instructions | *Spin-up instructions*, below |
| Highlight the NVIDIA models, Token Factory and Nebius services | the section immediately above |
| Feedback on Token Factory, AI Cloud and NVIDIA tools | `SUBMISSION.md` -> *Feedback on Nebius Token Factory, AI Cloud, and NVIDIA tools* |
| Free, unrestricted access for judging, with credentials | *The demo accounts*, below |
| Demonstration video under three minutes, public on YouTube | **OUTSTANDING** — the shooting script is `docs/DEMO_SCRIPT.md` |
| Bonus: functional runtime Tavily call | `tavily_client.search_cached()` on the live compliance path (search status carried into the prompt), six integration points |

---

## API

The JSON contract every agent returns was preserved through the port, so the agent
endpoints below answer in the shape they did before, with the `model` field in each
response envelope naming the Token Factory model. Who may call each route has changed
since: see *[Signing in](#signing-in)*.

### Autonomous orchestration

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/events/shipment` | POST | Shipment-created event sink. Idempotent per `shipment_id`. |
| `/api/v1/simulate` | POST | Inject the scripted three-shipment demo batch |
| `/api/v1/orchestrator/state` | GET | Full dashboard projection: cases, events, audit, counters |
| `/api/v1/orchestrator/case/<case_id>` | GET | One case with every agent hop, latency and action receipt |
| `/api/v1/orchestrator/case/<case_id>/dossier` | GET | The case as a due-diligence dossier (PDF), built by code from the stored case; viewer, like the case itself |
| `/api/v1/orchestrator/tick` | POST | Advance the pipeline one step |
| `/api/v1/orchestrator/reset` | POST | Clear the tenant's cases and events (operator, **password sign-in only**). The audit trail is kept, and the reset is written to it as a `board_reset` row naming who did it |
| `/api/v1/orchestrator/drain` | POST | Run up to `cases` pending cases (default 3, max 10) to a terminal state |
| `/api/v1/events/document` | POST | Document intake. Multipart `file` (PDF or image). Screens for injection, transcribes, archives the original, then runs the case to a terminal state in the same request. |
| `/api/v1/events/storage` | POST | Cloud Storage notification sink (a Pub/Sub push); ignores the service's own `shipping-documents/` and `evidence/` output and, under `MULTI_TENANT`, any object outside the caller's tenant space in `DOCUMENT_BUCKET` |
| `/api/v1/ingest/bucket-sweep` | POST | Ingest up to `limit` (default 10, max 25) unprocessed objects under `prefix` (default `inbox/`) in `DOCUMENT_BUCKET`; under `MULTI_TENANT`, only inside the caller's own tenant space |
| `/api/v1/simulate/bulk` | POST | Randomised shipments, capped at `MAX_BULK_COUNT` |

### Review, governance and configuration

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/review/queue` | GET | Everything the agent was not permitted to close |
| `/api/v1/review/<case_id>/decide` | POST | Record a human decision |
| `/api/v1/review/<case_id>/document` | GET | The case's bill of lading |
| `/api/v1/governance/agent` | GET | Agent status and the boundary version it is operating under |
| `/api/v1/governance/boundaries` | GET | Every published boundary version |
| `/api/v1/governance/publish` | POST | Publish a new delegation boundary |
| `/api/v1/config` | GET | Effective configuration and thresholds |
| `/api/v1/config/model` | GET, POST | Read or switch the Nemotron model used by fraud and compliance, and by the HS classifier and zero-day radar unless `HS_CLASSIFIER_MODEL` / `ZERO_DAY_MODEL` pin them. Investigation is pinned separately via `INVESTIGATION_MODEL`. |
| `/internal/execute` | POST | The execution surface a split-identity executor serves when `EXECUTOR_URL` points at one; the deployed service publishes directly |

### Direct agent access

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Flask's own root. In the container Next.js serves the console here; Flask run on its own redirects to `CONSOLE_URL` if set, or serves the retired static dashboard (also at `/legacy`) |
| `/health` | GET | Health check, store backend, worker status, the serving Cloud Run `revision` and whether the sent ledger is configured (`sent_ledger`) |
| `/api/v1/agents` | GET | The four request/response agents (intake, fraud, compliance, investigation) with their capabilities and the model each runs on; the HS classifier, zero-day radar and debate show theirs on every hop of the case trace |
| `/demo` | GET | Runs the fraud agent on a built-in sample shipment |
| `/api/v1/fraud/analyze` | POST | Analyse one shipment |
| `/api/v1/fraud/batch` | POST | Analyse many |
| `/api/v1/compliance/screen` | POST | Compliance screening for a shipment (includes a Tavily lookup) |
| `/api/v1/compliance/entity` | POST | Screen a single entity |
| `/api/v1/investigation/case` | POST | Deep-dive investigation |
| `/api/v1/investigation/report` | POST | Consolidated report |

### Not listed above

These three tables document 31 of the 73 registered routes (71 paths) — the ones a
caller is likely to want. The most useful omissions:

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/review/<case_id>/deep-review` | POST | Runs the debate (Super by default) by hand on a case awaiting review, the same agent the orchestrator fires automatically; here the verdict is recorded on the case and changes no route (reviewer) |
| `/api/v1/review/<case_id>/request-evidence` | POST | Verification loop: ask the shipper for named documents through a signed link (reviewer) |
| `/api/v1/review/<case_id>/evidence/<request_id>/link`, `.../cancel` | POST | Reissue a request's link, or cancel the request with a reason (reviewer) |
| `/api/v1/review/<case_id>/reevaluate` | POST | Re-run the deterministic origin checks against the evidence received so far (reviewer) |
| `/api/v1/review/<case_id>/approve`, `.../execute` | POST | Approve a release or block bound to an evidence version, then execute it (reviewer, **password sign-in only**) |
| `/api/v1/review/<case_id>/approve-exception` | POST | Release over unresolved or contradicting evidence, with a reason and the list of items waived (operator, **password sign-in only**) |
| `/api/v1/receiver/decision` | POST | The Pub/Sub push endpoint of the decisions receiver. Accepts only a push whose OIDC token Google signed for `RECEIVER_PUSH_SA` and `RECEIVER_PUSH_AUDIENCE` (otherwise 403) and applies each decision once per idempotency key and tenant |
| `/api/v1/receiver/applied/<key>` | GET | What the receiver applied under a key: `applied_once`, `deliveries`, case and outcome (viewer; 404 when nothing was applied) |
| `/api/v1/evidence/respond` | POST | The shipper's upload through a signed link. The shipper has no account; the link's token, in `X-VF-Evidence-Token`, is the only credential |
| `/api/v1/billing/usage` | GET | Windowed spend, including `tavily_searches` / `tavily_cached` / `tavily_billable` |
| `/api/v1/cases` | GET | Case list, slim shape, filterable by state |
| `/api/v1/audit` | GET | The audit trail, filterable by case, action or status |
| `/api/v1/audit/unreconciled` | GET | Executions whose `publish_decision` audit row is still missing after the broker accepted the message (N01), with a count (viewer) |
| `/api/v1/audit/reconcile` | POST | Writes each missing `publish_decision` row once, under the signed-in person (operator; the key alone must name a person). Two reconciliations at the same moment leave one row: the row has a fixed id derived from tenant, case and idempotency key and is created atomically |
| `/api/v1/ops/sent-ledger` | GET | Whether the sent ledger is configured and this service may read it; never its name (viewer) |
| `/api/v1/security/screen` | POST | The injection probe on the console's Agents page: paste an attack, get the real screen verdict |

`GET /api/v1/auth/policy` lists every route with the role it enforces, and is the
authoritative list. `GET /api/v1/openapi.json` and the generated `docs/swagger.json`
describe the B2B contract (4 paths), not the whole API.

### Example

```bash
# BASE is your deployed URL, and this is a WRITE, so it needs an operator key:
#   BASE=https://vf-app-350828852747.asia-southeast1.run.app
#   VF_API_KEY=$(gcloud secrets versions access latest --secret=VF_API_KEY)
curl -s -X POST $BASE/api/v1/fraud/analyze \
  -H 'Content-Type: application/json' \
  -H "X-VF-API-Key: $VF_API_KEY" \
  -d '{
    "shipment_id": "VF-2026-0001",
    "origin": "Ho Chi Minh City",
    "destination": "Hanoi",
    "weight_kg": 150,
    "declared_value": 50000000,
    "shipping_cost": 1200000,
    "avg_route_cost": 3000000,
    "shipper_name": "Thanh Phat Trading Co",
    "receiver_name": "Minh Long Import Ltd",
    "shipper_tx_count": 2,
    "status": "pending",
    "route_details": "HCMC to Hanoi"
  }'
```

Response (`analysis` is a JSON string produced by the model):

```json
{
  "shipment_id": "VF-2026-0001",
  "model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
  "analyzed_at": "2026-09-17T07:10:00.000000",
  "analysis": "{\"risk_score\":78,\"risk_level\":\"HIGH\",\"flags\":[...],\"recommendations\":[...],\"confidence\":0.9}"
}
```

---

## Spin-up instructions

### Prerequisites

- Python 3.11+
- Node.js 20 or later (the container uses 22) and npm, for the console
- A Nebius Token Factory account and API key (https://tokenfactory.nebius.com/)
- A Tavily API key (https://tavily.com/) — optional, the compliance agent
  degrades gracefully without it
- `gcloud` CLI and a Google Cloud project (for Firestore/Pub/Sub/Cloud Run;
  optional for pure local testing with `STORE_BACKEND=memory`)

### 1. Run locally

```bash
git clone <this-repo>
cd vf-logistics-nebius-nvidia

python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

Configure and start:

```bash
cp .env.example .env       # Windows: copy .env.example .env
# set NEBIUS_API_KEY and (optionally) TAVILY_API_KEY

# The package lives in src/, so it is reached as a module rather than a file.
# There is no main.py; the Flask app is src/vf_logistics/app.py, which is also
# what the container runs (Dockerfile: vf_logistics.app:app).
PYTHONPATH=src python -m vf_logistics.app     # http://localhost:8080
```

On PowerShell:

```powershell
$env:PYTHONPATH = "src"; python -m vf_logistics.app
```

`.env.example` sets `STORE_BACKEND=firestore` with a placeholder `PROJECT_ID`, so for a
local run set `STORE_BACKEND=memory` in `.env`. Left as it is, the service falls back to
memory only when no Firestore client can be built (no Google Cloud credentials on the
machine), and `/health` reports which backend it got and why; with credentials present it
would aim at the placeholder project instead.

Port 8080 on its own serves only the retired static page at `/`. The console is the
Next.js app in `frontend/`; start it in a second shell (details in
[`frontend/README.md`](frontend/README.md)):

```bash
cd frontend && npm ci
NEXT_PUBLIC_DEMO_MODE=false FLASK_API_BASE=http://127.0.0.1:8080 npm run dev   # http://localhost:3000
```

`NEXT_PUBLIC_DEMO_MODE` defaults to `true` outside a production build, which would show
fixtures rather than your API.

### 2. Deploy to Cloud Run

Enable the APIs (no `aiplatform.googleapis.com` needed anymore — the model
layer no longer touches Vertex AI):

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  modelarmor.googleapis.com \
  --project YOUR_PROJECT_ID
```

Grant the default compute service account the roles it needs:

```bash
PROJECT_ID=YOUR_PROJECT_ID
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
SA="$PROJECT_NUMBER-compute@developer.gserviceaccount.com"

for ROLE in \
  roles/datastore.user \
  roles/pubsub.publisher \
  roles/storage.objectAdmin \
  roles/artifactregistry.writer \
  roles/logging.logWriter \
  roles/modelarmor.user
do
  gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$SA" --role="$ROLE"
done
```

Provision the state store and the topics:

```bash
gcloud firestore databases create --location=asia-southeast1
gcloud pubsub topics create shipment-events
gcloud pubsub topics create case-decisions
```

Create the secrets once. `VF_SESSION_SECRET` must be at least 32 characters, and
`VF_OPERATORS` holds the sign-in accounts (see *[Signing in](#signing-in)*):

```bash
for S in NEBIUS_API_KEY TAVILY_API_KEY VF_API_KEY VF_SESSION_SECRET VF_OPERATORS; do
  gcloud secrets create $S --replication-policy=automatic --data-file=./secrets/$S
done
```

Deploy. The root `Dockerfile` builds **one image holding both halves** — the Next.js
console on `$PORT` and Flask on `127.0.0.1:9090` behind it — so this is the only
service. Commas inside a value need gcloud's alternate delimiter (`^|^`), which is why
the role lists are set on their own line:

```bash
gcloud run deploy vf-app \
  --source . \
  --region asia-southeast1 \
  --allow-unauthenticated \
  --memory 1Gi --cpu 1 --timeout 300 \
  --min-instances 0 --max-instances 2 \
  --set-env-vars "PROJECT_ID=$PROJECT_ID,WORKER_MODE=ondemand,STORE_BACKEND=firestore,ANONYMOUS_ROLE=none,VF_PUBLIC_READS=false,VF_ONE_CLICK_JUDGE=true" \
  --update-env-vars "^|^ADMIN_EMAILS=you@example.com|REVIEWER_EMAILS=reviewer@example.com" \
  --set-secrets "NEBIUS_API_KEY=NEBIUS_API_KEY:latest,TAVILY_API_KEY=TAVILY_API_KEY:latest,VF_API_KEY=VF_API_KEY:latest,VF_SESSION_SECRET=VF_SESSION_SECRET:latest,VF_OPERATORS=VF_OPERATORS:latest"
```

Redeploying later needs none of the flags: `gcloud run deploy vf-app --source .`
keeps every setting it is not told to change, and restating `--memory` or the env
list is how a redeploy silently shrinks or strips a service.

Verify:

```bash
BASE=$(gcloud run services describe vf-app \
  --region asia-southeast1 --format='value(status.url)')

curl -s $BASE/health                  # expect store.backend=firestore, worker.mode=ondemand
curl -s $BASE/api/v1/agents           # the four request/response agents and the model each runs on
curl -s $BASE/api/v1/auth/whoami      # expect "role": "viewer" -- anonymous is a viewer
curl -s $BASE/api/v1/auth/policy      # every route and the role it enforces

curl -s -X POST $BASE/api/v1/simulate -H "X-VF-API-Key: $VF_API_KEY"
curl -s $BASE/api/v1/orchestrator/state -H "X-VF-API-Key: $VF_API_KEY"   # an operator poll also advances a step
```

`Dockerfile.backend` still builds the API alone, for running Flask without the
console; nothing deploys it.

### 3. Tear down

```bash
gcloud run services delete vf-app --region asia-southeast1
```

---

## Signing in

**The deployed console asks everyone to sign in.** It runs with `ANONYMOUS_ROLE=none` and
`VF_PUBLIC_READS=false`, so an anonymous visitor is sent to the sign-in screen and the API
answers 401. The one-click guest-judge button (`VF_ONE_CLICK_JUDGE=true`) needs no password:
the guest can look around, inject shipments, block a case and simulate policy, but cannot
release or approve. With `ANONYMOUS_ROLE=viewer` (the default in code) and `VF_PUBLIC_READS=true`
(off unless set; used for a demo over synthetic data) an anonymous visitor is a real `viewer` and the board, every
case trace, the review queue, the audit trail, the governance history and the evaluation
figures are readable without an account.

What each role adds is declared on the route itself, by its decorator, not kept in a
list, and `GET /api/v1/auth/policy` returns the table from the running service:

| Role | Routes | What it adds |
|---|---|---|
| none | 6 | Health, the OpenAPI document, the agent roster (at `/agents` and `/api/v1/agents`), and Flask's own pages at `/` and `/legacy` |
| `viewer` | 25 | Every read: cases, review queue, audit, governance, metrics, evaluation, and the policy dry run |
| `reviewer` | 10 | Decide a case, request a deep review, open the archived original document, record time spent on a case, and the verification loop: request, reissue or cancel evidence, re-evaluate, approve and execute (the last two with a password sign-in) |
| `operator` | 24 | Anything that spends or ingests: shipments, documents, simulations, drains, resets, `/demo`, and the spend figures (`billing/usage`) |
| `governance_admin` | 5 | Publish or revoke the delegation boundary, change the prefilter rules, run the news scan, and the console's shared sign-in ledger (`/internal/login-throttle`) |

Roles are cumulative: a reviewer is also a viewer, and so on up. One of the 24 operator
rows is not what it looks like: `POST /api/v1/evidence/respond`, the shipper's upload
through a signed link, is labelled operator in the listing, but the route checks only the
link's token, because the shipper has no account.

**How a caller gets a role.** The API key alone is `governance_admin`; it is a service
credential, and the scripts in `scripts/` use it. A signed-in person holds the role their
address is listed under in `ADMIN_EMAILS`, `OPERATOR_EMAILS` or `REVIEWER_EMAILS`. The
console attaches its key only alongside a session that verifies, and the backend then
**narrows** the key to that person's role — a session can narrow the key but never widen
it, an unlisted address is a viewer, and a session that fails to verify alongside a valid
key is refused with 401 rather than falling back to admin. The Access Control screen
(`/admin`) shows the resolved identity and the policy, both read from the running API.

The reason an account exists at all is **recording a review decision.** The audit trail
names the account that made each call, and that attribution is the point — it is what
makes a released shipment traceable to a person rather than to "the reviewer field in the
request body", which is what it used to be.

### The demo accounts

| Account | Role | Password |
|---|---|---|
| `judge@vf-logistics.demo` | `governance_admin` | Secret Manager, `VF_JUDGE_PASSWORD` |
| `reviewer@vf-logistics.demo` | `reviewer` | Secret Manager, `VF_REVIEWER_PASSWORD` |

Sign in at `/login`. The reviewer account is there so you can watch the access control
refuse something: it can decide a case and open its document, while the spend figures,
document upload and governance publishing stay locked, each naming the role that would
unlock it. Neither password is in this repo or in any log. For your own deployment:

```bash
gcloud secrets versions access latest \
  --secret=VF_JUDGE_PASSWORD --project=<your-project>
```

For a submission review both are supplied in the private testing-instructions field, so
a judge never has to touch `gcloud`.

### One click for judges

The login page and the board's **Start here** strip offer **Continue as guest judge**:
one click, no password, and the session is `guest-judge@vf-logistics.demo`, a separate
account listed in `ADMIN_EMAILS`. It can do most of what the judge account can — inject
shipments, block a case or ask for information, simulate a policy against the board —
**except what releases cargo or would carry over to the next judge**: releasing a
shipment, whether through Decide or the verification loop's approve and execute; clearing
the board; publishing or revoking the delegation boundary (a revoke suspends the agent,
and so does publishing one that permits nothing); and editing the pre-AI screening rules.

Those exceptions are enforced twice, not hidden. The session token carries an `amr`
claim (`password` or `one_click`) inside the same HMAC as the email, so it cannot be
edited. The console's BFF refuses `orchestrator/reset`, `governance/publish`,
`governance/revoke`, the `governance/prefilter-rules` PUT, and the verification loop's
`review/<id>/approve` and `review/<id>/execute` to any session that does not say
`password`, and the API refuses the same six routes again with
`auth.require_password_session`, which returns 403 with `required_auth: "password"`. A
release through `/decide` is refused by the orchestrator itself unless the decision was
made from a password session; a block is not. A token without the claim — one minted
before it existed — counts as *not* a password. A script holding only the API key still
passes the six routes, because it has no session to ask about, but it cannot release
through `/decide`: there it records `actor_auth: "api_key"`, which is not a password.

Every decision, publish and reset records `actor_auth` beside the name, so the Audit
Trail can tag what was done from the public guest session. The button is off unless
`VF_ONE_CLICK_JUDGE=true`, and `VF_ONE_CLICK_UNTIL` closes it on a date; an end date it
cannot parse closes it too. The session lasts four hours, and the route is POST-only and
rate-limited to 10 a minute per address.

Closing the door ends the guest sessions already issued, not only new ones. Both the
console and the API re-read `VF_ONE_CLICK_*` on every request and refuse a `one_click`
token once the door is closed, the end date has passed, or the token names an account
other than `VF_ONE_CLICK_EMAIL`. Changing a variable creates a new revision, so the
cut-off takes effect as soon as Cloud Run moves traffic to it. Password sessions are not
affected.

Password sign-in is limited twice, before PBKDF2 runs: 5 attempts a minute per account
and 20 per source address. The email is normalised once (trimmed and lower-cased) and that
one value is both counted and checked. The count lives on the API's shared ledger
(`/internal/login-throttle`, Firestore collection `login_throttle`), so every instance
spends one allowance. If the ledger cannot answer, the sign-in is refused with 503
rather than counted per instance; only a development server with no API key counts
locally. On Firestore the ledger is a fixed one-minute window counted with an atomic
increment rather than a transaction: under a burst of attempts a transaction queues on
its lock, the console gives up after three seconds, and every one of those sign-ins
would be refused. Finished windows are deleted by a TTL policy on
`login_throttle.expire_at`.

### Creating your own account

There is no self-service sign-up. Accounts live in `VF_OPERATORS` as
`email:iterations:salt:hash` records (PBKDF2-SHA256), semicolon-separated:

```bash
node frontend/scripts/make-operator.mjs you@example.com --out ./secrets
```

That writes the generated password to a **file** rather than printing it, so it does not
land in a shell history or a terminal transcript. Append the record to `VF_OPERATORS`,
list the address under the role it should hold, and roll a revision so new instances read
the new secret version. `--update-env-vars` replaces a list rather than appending to it,
so restate the entries already there:

```bash
gcloud run services update vf-app --region asia-southeast1 \
  --update-secrets VF_OPERATORS=VF_OPERATORS:latest \
  --update-env-vars "^|^REVIEWER_EMAILS=reviewer@example.com,you@example.com"
```

An address that is in `VF_OPERATORS` and in no role list can sign in and is a viewer, so
adding an account is a read-only change until someone deliberately grants it more.

`VF_SESSION_SECRET` must be at least 32 characters; a shorter value is treated as absent,
and in production a missing one takes the console **offline** rather than leaving it open.

---

## Measured results

Every figure here comes from a script in `scripts/` and is committed as a JSON report under
`data/`, so a number can be traced to the run that produced it. All but the
verification-loop run are also served read-only by `GET /api/v1/evaluation` to the
console's Evaluation screen (`/evaluation`). The
corpus is **synthetic** (`scripts/generate_synthetic_cases.py`, seed 20260920, 1,000
cases: 300 shell-company transhipment, 300 HS mismatch, 200 sanctions-alias evasion, 200
clean). No real shipment data is involved: these numbers say how the system behaves on
the attacks we could describe, not on the ones we could not.

Ranges in brackets are 95% Wilson score intervals on the counts behind each rate, in
whole percent rounded outward as the Evaluation screen shows them, and served with the
reports by the same endpoint. They arrived with the 14 Oct 2026 evaluation merge,
`896bbae` (the endpoint change is `0468f98`, the screen `be8a31f`); a deployment built
before it serves the point figures only. Some of the counts are small, and the
intervals are there so a reader can see which differences mean something.

### The detection benchmark

`scripts/run_massive_benchmark.py` splits the corpus by `sha256(case_id)[0] % 2` into a
dev half (547 cases) and a holdout half (453). The false-positive tuning was chosen on dev
only, so holdout is the number to quote.

**Rules arm** — the deterministic layer alone, no model calls, free to rerun:

| Holdout, 453 cases | Before tuning | After tuning |
|---|---|---|
| Precision | 84.1% [80–88] | 91.2% [87–94] |
| Recall | 95.1% [92–97] | 93.5% [90–96] (343/367) |
| F1 | 0.893 | 0.923 |
| False-positive rate (86 clean) | 76.7% [66–85] | **38.4%** [28–49] (33/86) |
| Sanctions-alias evasion caught | 87 / 87 | 87 / 87 |
| Shell-company transhipment caught | 156 / 156 | 156 / 156 |
| HS mismatch caught | 106 / 124 | 100 / 124 |

The price of the tuning is the last row: six HS substitutions the rules used to hold now
pass the rules alone, which is what the model arm is for. On dev after tuning the figures
are 91.0% precision [87–94], 93.5% recall [90–96] and a 35.1% false-positive rate
[26–45]. Each holdout point estimate falls inside dev's interval, which is consistent
with the thresholds not having been fitted to the half they saw; that the two intervals
merely overlap would not, on its own, show that.

**Full arm** — rules, the HS classifier (Nano, `cot_strict`) and the zero-day radar
behind its real search gate, on 200 holdout cases taken by stride. It is "full" only
against the rules arm: the fraud and compliance agents (which can only add holds),
investigation and the debate are not in it, and most zero-day searches were stubbed
(below).

| 200 holdout cases | Rules alone | Rules + HS + zero-day |
|---|---|---|
| Precision | 90.9% [85–95] | 90.3% [85–94] |
| Recall | 95.8% [91–98] | **100%** [97–100] (167/167) |
| F1 | 0.933 | 0.949 |
| False-positive rate (33 clean) | 48.5% [32–65] | 54.5% [37–71] (18/33) |

The model layer caught the 7 HS substitutions the tuned rules missed and added 2 false
positives, both an HS mismatch claimed against a non-controlled heading (floor 40). The
run cost **$0.2019** for 200 cases, or $1.01 per 1,000, with a median of 23.2 s and a p95
of 53.9 s per case.

What belongs next to those numbers:

- **The false-positive rate is still high.** On rules alone, 38.4% of clean holdout
  shipments are held for a person. The clean half of the corpus is deliberately hard (58
  of its 86 holdout cases are near-misses built to look like attacks), but an operator
  would feel this number.
- **The model layer cannot lower it, by design.** An agent may raise risk and never lower
  it below the deterministic floor, so a false positive the rules create is removed only by
  tuning the rules, which is what the first table measures. The model buys recall.
- **Adverse-media detection is barely measured.** Zero-day searches in the benchmark were
  stubbed to return nothing — inventing news would feed the corpus labels to the model
  through the tool and then grade it on repeating them — so only the 9 cases with a real
  Tavily search measure detection. The rest measure the gate (86.6% precision on when to
  search) and how the model handles an empty result; 79 of those 97 verdicts came from the
  final turn that asks for a verdict once the search budget is spent.

#### Operating curve

One recall and one false-positive rate say how the threshold in use does, not what moving
it would buy. `scripts/operating_curve.py` re-scores the rules arm's per-case floors at
every threshold that changes the answer and writes `data/operating_curve/rules.json`,
which ships in the image and is drawn on the Evaluation screen of a build that includes
`896bbae`. Floors take a handful of values, so each row stands for a range of thresholds;
the two rows that another row matches or beats on both counts (81–85, 91–100) are left
out here and kept in the file.
Rules arm, holdout:

| Review threshold | Recall | False-positive rate | Held per real case at 0.2% |
|---|---|---|---|
| **40, the benchmark's** (any value 1–50 holds the same) | 93.5% | 38.4% | ~206 |
| 51–65 | 67.0% | 25.6% | ~191 |
| 66–75 | 67.0% | 9.3% | ~70 |
| 76–80 | 66.5% | 7.0% | ~53 |
| 86–90 | 25.9% | 0% | ~1 |

Raising the threshold into the 66–80 range would cut the reviewer load per real case by
roughly three to four times, and recall would fall from 93.5% to about 67%. That is a
trade between reviewer hours and released fraud that belongs to the operator who carries
the consequences, so we left the threshold where it was and show the curve instead. The
curve is a what-if over the rules' floors, not a setting: in the running system any
non-zero floor withholds auto-clear (`reconcile()`), and the default boundary requires
zero findings, so adopting a higher threshold would mean changing `reconcile()` and the
boundary.

#### Where the false positives come from

On the dev split only, every one of the rules' 40 false positives traces to four findings:
`SHIPPER_NO_HISTORY` sets the floor on 17 of them (15 with nothing else scoring),
`VALUE_DENSITY_HIGH` on 12, `FREIGHT_ANOMALY` on 5, and `DUAL_USE_HS_CODE` on 6, all HS
8471 laptops. We measured five candidate changes on dev and rejected all five: four were
indefensible in compliance terms or keyed on how the generator builds cases, and one lost
recall. So the holdout was not consulted and the verifier is unchanged. This is a null
result, and we report it as one.

The largest lever is policy rather than tuning. Counting a first-time shipper only as
corroboration of another finding, never on its own, would take the dev false-positive
rate from 35.1% to 21.9% with no recall lost on this corpus, and would release the first
shipments of new counterparties unreviewed. Whether a desk accepts that is the
operator's decision, not one we made for them.

### HS classification, measured

`scripts/eval_hs.py` grades the classifier's own verdict, not the case outcome, on two
sets: 30 pairs (`data/hs_pairs.yaml`, 15 evasive and 15 honest) and a 24-case holdout
(`data/hs_holdout.yaml`, 12 and 12) of substitutions absent from the reference material.
Recall is evasions caught. A reply the model failed to give, or an `unknown` verdict, is
counted as neither class, so every rate in the table is over graded cases only and the
counts in brackets are those graded cases.

| Arm | Model | Pairs recall | Pairs FPR | Holdout recall | Holdout FPR |
|---|---|---|---|---|---|
| Rules (`check_hs_code`) | — | 0% (0/15) | 0% | 0% (0/12) | 0% |
| `base` | Nano | 40.0% (6/15) | 35.7% | 50.0% (6/12) | 41.7% |
| `few_shot`: two worked examples | Nano | **26.7%** (4/15) | 14.3% | **33.3%** (4/12) | 45.5% |
| `cot_zero`: ordered method, verdict last | Nano | 40.0% (6/15) | 28.6% | — | — |
| `cot`: method plus reasoning exemplars | Nano | 53.8% (7/13) | 21.4% | — | — |
| `cot_ref`: method plus reference with exclusion notes | Nano | 100% (15/15) | 0% | — | — |
| **`cot_strict`: method plus published heading contents (production)** | Nano | **92.9%** (13/14) [68–99] | **0%** (0/15) [0–21] | **91.7%** (11/12) [64–99] | **0%** (0/12) [0–25] |
| Teacher, `base` prompt | Super | 100% (15/15) | 6.7% | — | — |

What the table says:

- **Worked examples made Nano worse.** On the pairs they taught caution rather than
  classification — the false-positive rate fell, recall fell further — and on the holdout
  both got worse.
- **Reasoning order alone changed nothing, and reasoning exemplars helped a little.** The
  failures turned out to be confabulated heading contents anchored on the declared code,
  not bad reasoning, so the fix was handing the model the real heading text to check
  against.
- **`cot_ref` scored 100% and is not quoted.** Its exclusion notes were written with the
  test pairs in view, so it cannot be told apart from having been handed the answers.
  `cot_strict` strips them and sees only published heading contents; it is what production
  runs (`orchestrator.py`) and the only figure we quote.
- **The holdout is the test that matters:** 11 of 12 evasions caught and 0 of 12 honest
  cases flagged, on substitutions the reference never mentions, on Nano rather than
  Super. Twelve is a small number: the 95% interval on that recall runs from 64% to 99%,
  and "no false alarms" means 0 of 12, whose upper bound is 24.2% (the table rounds it
  outward to 25).

### Public enforcement cases

The synthetic corpus tests the system against its authors' idea of fraud. So
`scripts/build_public_cases.py` rebuilds **19 real cases** — BIS Temporary Denial Orders,
OFAC settlements with freight forwarders, US Commerce circumvention findings, EPPO and
OLAF prosecutions — each as the shipment the paperwork showed, beside the honest trade it
imitated, with the regulator's URL and a verbatim quote on every case
(`data/public_cases.json`). Parties are screened against the real OFAC SDN and UN lists.

| 19 pairs | Rules alone | Rules + HS + zero-day |
|---|---|---|
| Frauds held | 11 / 19 (57.9% [36–77]) | 14 / 19 (73.7% [51–89]) |
| Honest counterparts held | 7 / 19 (36.8% [19–59]) | 9 / 19 (47.4% [27–69]) |
| Pairs separated (fraud held, honest cleared) | 4 | 3 |
| Model cost | $0 | $0.034 |

Read it as pairs. **Five of the seven dual-use pairs are held on both sides**, correctly:
controlled goods need a licence check whether or not this consignee is honest. **Four
origin-fraud pairs are identical at booking** — Vietnamese-declared plywood made from Chinese veneer looks
exactly like plywood made from Vietnamese veneer — so no booking-time screen separates
them, and the report says so rather than tuning a rule until it appears to. Two identical
pairs received different verdicts from the model; that is counted as variance, not
detection. And the lists are retrospective: several parties were designated because of
the very case.

The exercise found two real gaps, both now fixed and measured. Routing was checked on the
destination only, so foil declared as Myanmar origin and rail freight through Belarus
passed; `HIGH_RISK_ORIGIN` and `HIGH_RISK_TRANSIT` close that ("to, from, or through", in
OFAC's words), and change nothing on the synthetic corpus's clean shipments. And OFAC
writes `LLC TESTKOMPLEKT` where a Russian invoice says `OOO Testkomplekt`; the name
normaliser now treats Russian, CIS and Gulf legal forms like `LLC` and `Ltd`.

**Workload at real fraud rates.** The test corpora are half fraud (the public pairs) to
about four-fifths (the synthetic holdout, 367 of 453) by construction; a forwarder's book
is not. Vietnam Customs found a violation in 29,849 of
16.84 million declarations in 2024, **0.18%**. At 0.2%, the tuned rules hold about 385 of
every 1,000 shipments to find about 2 real cases: about **206 held per real fraud case**,
a precision at that prevalence of about 0.49%. On the 200-case subset the full arm ran,
the rules plus the HS and zero-day checks hold about 273 per real case against the rules'
254 on the same cases. Put recall and the false-positive rate at the favourable ends of
their intervals and then the unfavourable ends, and the rules' figure runs from 151 to 271
and the combined arm's from 191 to 359; those are best and worst corners, not a 95% interval. Customs'
own targeting makes roughly 19 red-channel inspections per violation found. The console's Evaluation screen shows
this for every report at 0.2%, 1% and 2% (the best and worst corners in a build that
includes `896bbae`). The conclusion we draw is that the product's job
is not to hold fewer shipments but to make each hold quick and defensible to decide —
which is what the case trace, the Review screen and the dossier are for.

### When booking data is not enough: the verification loop

The four identical origin-fraud pairs above prove that booking-time data alone cannot
distinguish a fraudulent plywood shipment from a legitimate one. Floorline now addresses
this directly: when a shipment lands on a watched lane (HS 4412, Vietnam to US), the
deterministic checks identify what is unverified, and the system organises the work of
collecting and evaluating the missing evidence.

**Six steps, each with its own state and audit trail:**

1. **Identify** -- `check_origin_inputs` flags the shipment with `ORIGIN_INPUTS_UNVERIFIED`
   (floor 45, `blocks_auto_clear`). The dossier (`GET .../dossier.json`) lists the three
   document types needed: certificate of origin, producer declaration, input purchase invoices.
2. **Request** -- A reviewer asks the shipper for specific documents through a signed HMAC
   link. The case moves to `AWAITING_EVIDENCE` and cannot be decided until the request is
   answered or cancelled.
3. **Receive and reconcile** -- The shipper uploads through `/respond/[token]` (public page,
   no login). Each file is screened by Model Armor, archived, and extracted per document type.
   The request tracks which types have been received and stays open until all are in.
4. **Re-evaluate** -- `reevaluate` reruns the deterministic checks against the extracted
   facts. Good evidence is reported as clarified; contradictions raise the floor. The AI
   never lowers the floor.
5. **Approve** -- A reviewer with a password session approves a release or block, binding
   the decision to the evidence version. New evidence after approval supersedes it. A release
   over unresolved or contradicting evidence is refused by `approve` (403) and goes through
   `approve-exception` instead: operator role, password sign-in, a reason and every waived
   item named, all stored on the approval.
6. **Execute** -- `execute_approval` claims the approval atomically before calling Pub/Sub,
   under one key (`exec-<approval_id>`) for every send. A publish failure records
   `EXECUTION_FAILED` (not `RELEASED`); the approval reverts to VALID for retry. A send whose
   outcome is unknown is recorded as such, and a retry first reads the sent ledger and does
   not publish again when the broker already accepted the decision. The receiver
   (`docs/RECEIVER_CONTRACT.md`) applies each key once.

**Measured on a 7-case evaluation corpus** (`scripts/run_verification_eval.py`, report in
`data/eval_results/verification_eval.json`):
3/3 legitimate cases resolved correctly, 2/2 fraudulent blocked, 2 needs-evidence cases
correctly held. **0 improper executions** (wrong authority, stale approval, or missing
evidence). Median cost $0.000108/case, median latency 40ms -- **both from the mocked
harness** (fixed token counts, no model or network calls), so they show the pipeline runs
end to end, not what a real run costs or how long a person takes.

### Three operator screens

| Screen | What the operator sees |
|---|---|
| **Today** (`/today`) | Four columns: waiting for documents, waiting for review, waiting for sign-off, approved but not executed. Who owns each case and what to do next. |
| **Case** (`/cases/[id]`) | One timeline: arrival, findings, agents, evidence requests, documents received, evaluations, approvals, executions. Decision form routes through `approve` + `execute` for cases with evidence. |
| **Outcomes** (`/outcomes`) | Cases resolved, human handling time (idle-aware), request rounds, model cost per case, cases held, executions refused. |

---

## Reproducible testing

```bash
# The test tools are not in requirements.txt; install them first.
pip install -r requirements.txt "pytest>=8.0.0" "pytest-asyncio>=0.23.0" "pytest-cov>=4.1.0" "pytest-mock>=3.12.0"

# Unit + integration tests: 2095 pass with the Firestore and Pub/Sub emulators running (CI does:
# firebase emulators:exec --only firestore,pubsub ...); without them the emulator tests skip.
# Line coverage of vf_logistics is 96% with the emulators. CI fails below 92%.
python -m pytest tests/ -v --cov=vf_logistics --cov-fail-under=92

# The mutation check: breaks 112 lines on purpose, one at a time, and requires the
# suite to fail on every one. It edits source in place and restores it, so it
# refuses to run on a tree with uncommitted changes.
python scripts/check_test_sensitivity.py

# Frontend: install, typecheck, lint, 1,729 unit tests in 91 files, production build
(cd frontend && npm ci && npx tsc --noEmit && npm run lint && npm test && npm run build)

# Real-model run (spends tokens, needs the operator key): cost, model time and whether each
# extracted field is in the document's own text
python scripts/measure_live_run.py --base https://<service-url> --yes-upload --out measure.json

# A receiving system checks itself against docs/RECEIVER_CONTRACT.md
python scripts/receiver_conformance.py https://<receiver>/push --applied-url "https://<receiver>/applied/{key}"

# Counterparty book, offline. The script imports shipper_registry as a top-level
# module, so both directories go on the path.
PYTHONPATH=src/vf_logistics:src python scripts/check_registry.py   # 11 checks
```

The document suite talks to a running service and **clears the board before every
pass**, because re-uploading the same document returns the existing case rather than
re-running it. So point it at something disposable:

```bash
export VF_TEST_BASE=http://localhost:8080
export VF_API_KEY=...                   # uploading is a write; anonymous callers get viewer
python scripts/test_documents.py        # all seven sample docs
python scripts/test_documents.py 3      # three passes, reports any disagreement
```

Against a non-local base it refuses unless you pass `--yes-wipe-board`. That guard
exists because this script once pointed at a service in a different project, passed
until 23 Sep (`126cbd6`) while testing code that was not in this repository, and then
deleted the seeded demo board the moment the URL was corrected.

Two live checks that need credentials and spend real tokens, so they are run by hand:

```bash
python scripts/check_model_switch_guard.py    # the cost ratchet, end to end, restores Nano
python scripts/compare_debate_models.py       # replays disputed cases through Super and Ultra
python scripts/compare_debate_models.py --corpus   # the 46 disputed corpus cases (--per-label, --screen-fraud, --max-cost-usd, --dry-run)
python scripts/compare_fraud_models.py        # Nano vs Super on score-0 corpus cases (--models nano,super,ultra, --limit, --max-cost-usd, --dry-run)
```

### Test coverage

| Suite | Count | What it covers |
|-------|-------|----------------|
| Sanctions & zero-day | 64 | Sanctions matching, list freshness, unseen-pattern handling |
| Official sanctions lists | 14 | OFAC SDN and UN parsers on real rows cut from the published files, a registration number from OFAC's remarks, short aliases dropped, `OOO` read as `LLC`, and a refresh that refuses to publish half a list |
| Due-diligence dossier | 11 | Every finding code lands on a reference that exists, the most specific guidance wins, the PDF renders from an empty or non-Latin case, a model's arrow is spelled out rather than printed as `?`, and the route is a viewer read scoped to the tenant |
| Pure logic | 70 | auth, config (including which GCP project is written to, and that none is guessed), schemas, simulator, untrusted, agents._common |
| Decision paths | 57 | Every route a shipment can take through the state machine, and the heading the HS classifier is told was declared |
| Tenant isolation | 52 | Cross-tenant reads, writes, and aggregation; one shared document bucket split by tenant; and `put_case` refusing a write over another tenant's case on both backends, the Firestore one against a fake of its client calls |
| Hardening | 48 | Kill switch, the injection probe (`security/screen`), policy dry run, auto-debate, per-hop I/O, and the learning loop: a discount only for a registry-verified shipper, tallies read fresh on every scored case |
| Document upload | 33 | Accepted types, the PDF branch, injection screening |
| Console session | 50 | HMAC signing, forged tokens, reviewer attribution, the signed sign-in method (`amr`), and what a forwarded session may and may not change |
| Network defence | 34 | Rate limits, request size, header hygiene, CSP content, content-type allow-list |
| Verifier | 36 | Risk reconciliation (no auto-clear without a stated floor), prompt injection, whitelist, checks, and routing "to, from, or through" a restricted country |
| B2B contract | 28 | The published response shape callers depend on |
| Routes | 27 | Security headers, CORS, auth, validation, pagination |
| Schema enforcement | 37 | Untrusted document fields against the declared schema; that an investigation reply with no summary is a counted failure rather than a finished report; and that Super is asked without `json_object`, which measured 6/12 usable against 12/12, with one retry billed in full |
| Budget | 26 | Per-tenant spend ceiling, cache TTL, fail-open on store error |
| Billing period | 25 | Windowed usage, and that every aggregation has an index |
| Model switch & metering | 25 | The cost ratchet, that an unpriced model cannot bill silently, and that no string names Super on the debate path |
| Debate control flow | 24 | The four ways the debate loop exits, and that a forced verdict never claims the auditor rendered nothing when it rendered something unreadable |
| Debate logic | 22 | Context building, tool dispatch, search depth, and that a failed search is named rather than arriving as an empty list |
| Store | 20 | MemoryStore CRUD, optimistic locking, pagination |
| Tavily cache | 20 | TTL behaviour, key derivation, and that a cached hit is recorded as one |
| Governance | 19 | Boundaries, drift detection, fail-closed, and that the boundary excludes every heading the rules call dual-use |
| Lineage & billing | 18 | Per-step cost attribution |
| Orchestrator | 17 | State machine, tool execution, agent envelopes |
| Observability | 16 | Logging, metrics, request context |
| Security screen logic | 16 | Window arithmetic, and that an unreachable screen fails closed instead of reporting a clean document |
| Output ceilings | 15 | Every agent's `max_tokens`, measured against its real maximum |
| RBAC | 28 | Who gets which role — key alone, key plus session, unlisted address, a session that fails to verify — whether the routes honour it, and that exactly six routes need a password sign-in: clearing the board, publishing or revoking the boundary, editing the prefilter rules, and the verification loop's approve and execute |
| Debate routing | 13 | A genuine, confident DISAGREE sends the case to investigation; a forced verdict does not; risk only moves up |
| Concurrent decisions | 13 | Two reviewers deciding the same case |
| False-positive tuning | 12 | Which signals are findings and which are context: observations carry no floor and are not counted |
| Compliance cache | 12 | Counterparty lookups reused within a case and across cases |
| Console contract | 12 | The field names the console reads from the backend -- the cause of three silent bugs |
| Unpriced model | 9 | An unpriced model is logged, not silently billed at the cheapest rate |
| Screen layers | 7 | Which of the two screening layers may refuse a shipment |
| Audit integrity | 6 | The governance author is the authenticated identity, not a body field |
| Cache concurrency | 5 | That concurrent identical searches all miss, and what that costs |
| Evaluation endpoint | 19 | The committed reports served as written, each naming its split and verifier, never the per-case rows that carry the labels; the workload arithmetic at real fraud rates; the public-case pairs with their sources; Wilson intervals at the edges (0 of 12, 15 of 15) rounded outward; and the operating curve shipped in the image |
| Operating curve | 5 | The threshold sweep on hand-built rows counted by eye, and `scripts/operating_curve.py` run once end to end |
| Release fails closed | 15 | A missing reconciliation, a compliance status other than `CLEARED`, an unverified shipper's discount, a missing finding count, an absent or unusable declared value and a blank destination each withhold an automated release |
| Document archive | 26 | The receipt written onto the case is one the reader can fetch back, and every storage failure is a receipt that says why, or an empty answer, never an exception; under `MULTI_TENANT`, objects filed and ingested only inside the tenant's own space |
| Executor client | 18 | Every way the hop to the executor can fail — no executor, no identity token, a refusal, a crash, a transport error — comes back as something other than "done" |
| Origin inputs | 167 | The watched-lane check behind the verification loop: a shipment on a watched lane cannot be cleared by the rules, and good papers never lower a floor |
| Evidence request, response, re-evaluation, approval, execution | 192 | The signed link and who may use it, uploads through it, re-evaluation, approval bound to an evidence version, and atomic execution (`test_evidence_*.py`) |
| Membership | 31 | Organisation membership resolved on the server, and the three ways a request authenticates |
| Worklist | 26 | The Today and Outcomes read models and the arithmetic behind them |
| Boundary history and schema | 32 | Versions never reused or overwritten; a permission written as the string `"false"` is refused rather than read as true |
| Internal execute | 15 | `/internal/execute` acts only in the organisation it checked the role in |
| Login throttle | 14 | One sign-in attempt ledger for every console instance |
| Approval gate at the route | 14 | Who may release or approve through the real Flask routes, and what the legacy `/decide` refuses |
| Firestore emulator | 18 | `FirestoreStore`'s transactions against the emulator; they skip unless `FIRESTORE_EMULATOR_HOST` is set, and CI runs them inside the emulators |
| Poll drain | 3 | A board poll that advances the pipeline stays a bounded read, with one drain per tenant |
| Exception approval and route | 11 | A release over unresolved or contradicting evidence is an operation of its own: the reason is mandatory, and the waived findings are stored on the approval |
| Publish once per key | 7 | A decision is published once per idempotency key, the key travels as a Pub/Sub attribute, and a resume after an accepted but unconfirmed publish does not publish again |
| Unknown send | 5 | A publish that timed out is recorded as `unknown`, not `failed`, so the retry is read as "result unknown, same key" |
| Unread pages | 7 | A paper the reader only partly read is not provided as read, and the evaluation says why a received paper is unresolved |
| Untyped links | 3 | A request-level link carries no document type, so with several documents requested it cannot say which slot an upload fills |
| Decisions receiver | 19 | The Pub/Sub push endpoint accepts only a Google-signed push, applies each decision once per key and tenant (8 concurrent deliveries of one key apply it once on the emulator), and a message without a key is refused (`test_decision_receiver.py`, `test_applied_decisions.py`, `test_reference_receiver.py`) |
| Sent ledger, hard kill and `/health` | 15 | A retry reads the sent ledger and does not publish again; an unreadable ledger sends nothing; a process killed right after the broker accepted leaves one message on the emulator; `/health` names the revision and the ledger (`test_sent_ledger.py`, `test_sim_hard_kill.py`, `test_health_deploy_info.py`) |
| **Total** | **2,095** | all pass in CI, which runs the emulators; 105 test files. This table names areas of the hardening suite, not every file |

The hardening suite drives real request handlers and real code paths rather
than asserting that routes are registered. An earlier version of it did the
latter and passed while the features underneath were broken.

These scripts only assert on case state (`AUTO_CLEARED`, `HELD_FOR_REVIEW`,
`ESCALATED`, `PENDING_HUMAN`) and JSON shape, not on which model produced a
result, so they exercise the ported pipeline exactly as they exercised the
original.

`GET $BASE/demo` runs the fraud agent on a built-in sample shipment — one
request, no body, no configuration. It needs an operator API key: it spends Nemotron
tokens on a GET, so it is the one read that is not public.

---

## Firestore composite indexes (required once per project)

`review_queue`, `GET /api/v1/cases?state=...` and `GET /api/v1/audit?...`
query `state IN [...]`/`case_id`/`action`/`status` combined with an
`order_by` on a different field, which Firestore only serves from a
composite index — the collection previously avoided this on purpose to stay
zero-setup, at the cost of the bugs this step now fixes (a case waiting for
review could silently fall out of the queue once enough newer cases existed).

**Apply the index file rather than writing the commands by hand.**
[`infra/firestore.indexes.json`](infra/firestore.indexes.json) is the source of
truth and defines **27** composite indexes — 20 on `cases`, 4 on `audit_log`, 2 on
`delegation_boundaries`, 1 on `events`.

```bash
firebase deploy --only firestore:indexes      # needs firebase-tools
```

Every index in that file **leads with `_tenant_id`**, and this is not cosmetic.
Firestore requires equality-filtered fields to precede the ordered field, and every
query in this system is tenant-scoped, so an index without `_tenant_id` is an index
Firestore will refuse to use — the query then fails outright rather than running
slowly. An earlier version of this README printed four hand-written
`gcloud firestore indexes composite create` commands that omitted it; following them
meant waiting out the index builds and still getting `FAILED_PRECONDITION` on
`GET /api/v1/orchestrator/state`. The file's own header comment records that failure.

The windowed billing indexes are generated rather than hand-written, because there
are two document shapes times eight fields:

```bash
python infra/monitoring/create_billing_indexes.py
```

Index builds run in the background (`gcloud firestore indexes composite list`
to check status) and queries against an unbuilt index fail loudly rather
than silently, so there is no risk of quietly querying an unindexed
collection.

---

## Environment variables

| Variable | Description | Default |
|---|---|---|
| `NEBIUS_API_KEY` | Nebius Token Factory API key | unset — required |
| `NEBIUS_BASE_URL` | Token Factory OpenAI-compatible endpoint | `https://api.tokenfactory.nebius.com/v1/` |
| `TAVILY_API_KEY` | Tavily API key for the compliance agent's live search | set in production via Secret Manager (`TAVILY_API_KEY`); optional locally — degrades gracefully if unset |
| `NEMOTRON_MODEL` | Model for fraud detection and compliance screening, and for the HS classifier and zero-day radar unless `HS_CLASSIFIER_MODEL` / `ZERO_DAY_MODEL` pin them | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` |
| `VISION_MODEL` | Model for document intake | `openbmb/MiniCPM-V-4_5` |
| `INVESTIGATION_MODEL` | Model for investigation, pinned separately | `nvidia/nemotron-3-super-120b-a12b` |
| `DEBATE_MODEL` | Model for the debate agent — Defaults to Super; `nvidia/Nemotron-3-Ultra-550b-a55b` restores Ultra with no deploy. See the note below the table. | `nvidia/nemotron-3-super-120b-a12b` |
| `HS_CLASSIFIER_MODEL` / `ZERO_DAY_MODEL` | Pin the HS classifier or the zero-day radar to its own model. Unset, each uses whatever model fraud and compliance are on, including after a `POST /api/v1/config/model` switch. | unset |
| `MODEL_SWITCH_MAX_RATE_MULTIPLE` | How much dearer a model `POST /api/v1/config/model` may select without `confirm_higher_cost`, against the cheapest priced model. Super is 4.0× Nano and permitted; Ultra is 13.3× and answered 409. | `5.0` |
| `TAVILY_ROUTE_CACHE_TTL_SECONDS` | TTL for the shipping-lane disruption search, whose query carries only a country pair. Measured: 20 searches across 6 distinct lanes. `0` disables. | `21600` (6h) |
| `TAVILY_ENTITY_CACHE_TTL_SECONDS` | TTL for the shipper/receiver adverse-media searches. Shorter because these carry a counterparty — though Tavily is *not* the sanctions control. `0` disables. | `3600` (1h) |
| `ZERO_DAY_MIN_DIVERSION_HUBS` | How many **distinct** transhipment hubs a route needs before zero-day screening opens. Two, matching the verifier's `MULTIPLE_DIVERSION_HUBS`. | `2` |
| `ZERO_DAY_NEWS_DAYS` | How far back the zero-day news search looks; older designations are the official list's job | `45` |
| `PROJECT_ID` | GCP project for Firestore, Pub/Sub, Cloud Storage and Model Armor. There is no built-in default: with none resolvable, Firestore falls back to memory and publishing and Model Armor refuse, each saying why | unset — the project Application Default Credentials resolve to, which on Cloud Run is the service's own |
| `WORKER_MODE` | `ondemand` (advance inside requests) or `poll` (always-on loop) | `ondemand` |
| `STORE_BACKEND` | `firestore` or `memory` | `firestore` |
| `CLAIM_LEASE_SECONDS` | How long a claimed case stays claimed | `180` |
| `FRAUD_CLEAR_BELOW` | Risk below which auto-clear is considered | `40` |
| `INVESTIGATE_AT` | Risk at or above which investigation always opens | `70` |
| `DOCUMENT_BUCKET` | Cloud Storage bucket for document archive | unset — set to `vf-fraud-detection-phuochoa-documents` in production |
| `MODEL_ARMOR_TEMPLATE` | Model Armor template id | `vf-document-intake` |
| `MODEL_ARMOR_LOCATION` | Model Armor region — availability is limited; `asia-southeast1` was rejected in testing, `us-central1` worked | `asia-southeast1` |
| `EXECUTOR_URL` | Executor service URL | unset |
| `DECISIONS_TOPIC` | Pub/Sub topic for published decisions | `case-decisions` |
| `SENT_LEDGER_SUBSCRIPTION` | Name of a pull subscription on the decisions topic that only this service reads. A retry after an unknown send reads it and does not publish again when the key is there; unreadable, it sends nothing and records the outcome as unknown. Unset, the ledger is never read. Setup: `docs/RECEIVER_CONTRACT.md` | unset |
| `RECEIVER_PUSH_SA` / `RECEIVER_PUSH_AUDIENCE` | The service account and audience a Pub/Sub push to `/api/v1/receiver/decision` must present in its OIDC token. With either unset the receiver accepts nothing (403). In PowerShell quote the list given to `--update-env-vars`, or the comma becomes a space. | unset |
| `NOTIFY_WEBHOOK_URL` | Outbound alert webhook | unset |
| `MAX_BULK_COUNT` | Cap on the volume-test endpoint | `10` |
| `PORT` | Port the container listens on. In the deployed image Next.js binds it and gunicorn binds `127.0.0.1:9090` behind it (`entrypoint.sh`); when Flask runs on its own, gunicorn binds it directly. | `8080` |
| `MAX_DOCUMENT_MB` | Rejection threshold for uploaded documents | `20` |
| `MAX_ATTEMPTS` | Retries before a case is dead-lettered | `3` |
| `MAX_CONCURRENT` | Cases advanced in parallel | `3` |
| `MAX_CHAIN_STEPS` | Hops one case may take before the chain is cut | `6` |
| `CHAIN_BUDGET_SECONDS` | Wall-clock ceiling for one case's chain | `120` |
| `POLL_SECONDS` | Loop interval in `WORKER_MODE=poll` | `1.5` |
| `ANONYMOUS_ROLE` | Role granted to a request with no credentials. `viewer` makes reads public; `none` refuses them. The process refuses to boot if this grants write. | `viewer` |
| `ADMIN_EMAILS` / `OPERATOR_EMAILS` / `REVIEWER_EMAILS` | Comma-separated addresses holding `governance_admin`, `operator` and `reviewer`. Trimmed and lowercased. A signed-in address in none of them is a viewer. Setting one with gcloud needs the alternate delimiter: `--update-env-vars "^\|^REVIEWER_EMAILS=a@x.com,b@x.com"`. | unset |
| `VF_API_KEY` | Operator API key. Alone it grants `governance_admin`; forwarded by the console only alongside a verified session, which narrows it to that person's role. | set in production via Secret Manager |
| `VF_TENANT_SPEND_CEILING_USD` | Per-tenant soft spend ceiling. Unset, garbage or `<= 0` all mean no ceiling. | unset |
| `MULTI_TENANT` | `true` makes every request resolve its tenant and role from `VF_TENANT_MEMBERS`, and files and ingests documents in the shared `DOCUMENT_BUCKET` only under `tenants/<id>/`. Off, there is one tenant and roles come from the `*_EMAILS` lists. | `false` |
| `VF_TENANT_MEMBERS` | Multi-tenant only: JSON `{principal: {tenant: role}}`, where a principal is a console email, `iap:<subject>`, or `service` for the API key. Each request's tenant and role come from here, and a person in several organisations picks one (sent as `X-VF-Tenant`). Unlisted principals are refused. With `MULTI_TENANT=true` the service will not boot if this is empty or malformed. Keep it in Secret Manager. | unset (ignored when `MULTI_TENANT` is off) |

### Console (the Next.js half of the `vf-app` container)

| Variable | Description | Default |
|---|---|---|
| `FLASK_API_BASE` | Backend base URL, read server-side per request. `entrypoint.sh` sets it to `http://127.0.0.1:9090` in the container; set it yourself only when running the console against a separate API. | set by `entrypoint.sh` |
| `VF_SESSION_SECRET` | HMAC key for session cookies. Must be at least 32 characters; a shorter one is treated as absent. | unset — **required in production**, where a missing value takes the console offline rather than opening it |
| `VF_OPERATORS` | Semicolon-separated `email:iterations:salt:hash` records, PBKDF2-SHA256. Generate with `node frontend/scripts/make-operator.mjs <email> --out <dir>`, which writes the password to a file rather than printing it. | unset |
| `VF_PUBLIC_READS` | `true` lets anonymous visitors read the console. Writes are never covered by it — the split is on the HTTP method, not a path list. Defaults to false so a deployment that forgets it is locked, not open. | `false` |
| `VF_ONE_CLICK_JUDGE` | `true` offers the one-click guest-judge sign-in. Off unless set, like `VF_PUBLIC_READS`. | unset |
| `VF_ONE_CLICK_EMAIL` | The account the button signs in as. Its role comes from the API's `ADMIN_EMAILS` / `OPERATOR_EMAILS` / `REVIEWER_EMAILS`, not from here. | unset |
| `VF_ONE_CLICK_UNTIL` | Optional end date (any `Date.parse` value, e.g. `2026-12-16`). After it, or if it cannot be parsed, the button is gone. | unset |
| `NEXT_PUBLIC_DEMO_MODE` | Build-time, not runtime: `NEXT_PUBLIC_*` is inlined by `next build`, so setting it with `gcloud run deploy --set-env-vars` has no effect on an already-built bundle. `frontend/.env.production` is what actually turns demo fixtures off. | `false` in `.env.production` |

`config.py` holds the shared model registry and per-token pricing for fraud
and compliance. `POST /api/v1/config/model` switches between the registered
Nemotron tiers at runtime, and the HS classifier and zero-day radar follow the switch
unless `HS_CLASSIFIER_MODEL` / `ZERO_DAY_MODEL` pin them; investigation ignores it and
reads `INVESTIGATION_MODEL` at import.

#### Why the debate runs on Super, and what was measured

`DEBATE_MODEL` defaults to Nemotron Super. Every agent stays on Nano or Super, and the
reason a larger model was not the default anywhere is architectural as well as financial:
`verifier.py` computes a deterministic risk floor, and an agent may **raise** risk but
never lower it below that floor. A stronger model on fraud detection or compliance
therefore cannot move the outcome in the direction that matters — the floor has already
decided whether a shipment may clear, and a model can only add holds above it. Ultra's
per-token rate is 13.3× Nano's, blended (`config.rate_multiple`).

The debate is the one hop where a model's output can change routing, so it was the one
tested against Ultra, its previous default. The orchestrator runs it only when the floor
exceeds the model's score by 15 points or more (2 calls across 20 cases on the live run),
and a reviewer can run it by hand with Deep Review on any case awaiting review. Either
way auto-clear is already impossible and a person will decide the case. What it emits is
a reasoned CONFIRM or DISAGREE on whether the junior analyst missed something. CONFIRM
changes nothing; on the automatic path a genuine DISAGREE at confidence 0.7 or above
sends the case to deep investigation on Super and may raise its risk (by hand, the
verdict is recorded for the reviewer and changes no route). It can send a disputed case
to a deep investigation it would otherwise skip (effective risk under the 70 investigation
bar, compliance not already `BLOCKED` or `REVIEW_REQUIRED`), and can never clear one.

**Measured: Super against Ultra on the debate.** 46 disputed corpus cases (25 fraud, 21
honest; the floor exceeded Nano's score by 15 or more), both models debating the same
cases, Tavily stubbed to return nothing (`scripts/compare_debate_models.py --corpus`;
`data/model_comparison/debate_corpus.json`). Intervals in brackets.

| | Super | Ultra |
|---|---|---|
| Reached a verdict | 40/46 (87%) | 37/46 (80%) |
| DISAGREE on fraud | 16/22 (73%) [52-87] | 18/19 (95%) [75-99] |
| DISAGREE on honest | 13/18 (72%) [49-88] | 17/18 (94%) [74-99] |
| Fraud minus honest | +0.5 pt | +0.3 pt |
| Cost per debate | `$0.0021` | `$0.0108` (5.2×) |
| Median seconds | 6.4 | 13.5 |
| Mean input tokens | 5,201 | 7,281 |

Neither model separates fraud from honest trade: the gap between the two DISAGREE rates
is under a point for both. Ultra just disagrees more. Every DISAGREE was at confidence
0.7 or above.

Caveats. The auditor is shown the rules' findings (DETERMINISTIC VALIDATION), and every
honest case in the sample was one the rules had held (floor of 40 or more), so DISAGREE
largely tracks agreement with the rules rather than an independent judgement of the
shipment. A DISAGREE only routes a held case to investigation; nothing it says can clear
a case. The corpus is synthetic and the sample small.

**Why this ratio differs from the earlier one.** The earlier measurement, on the live
service with real Tavily results, was higher: three Ultra debates and two Super debates.
It is what led to the test above.

| Model | Input | Output | Cost |
|---|---|---|---|
| Ultra | 13,151 | 2,011 | `$0.019184` |
| Ultra | 16,502 | 2,333 | `$0.023501` |
| Ultra | 13,937 | 879 | `$0.016574` |
| Super | 2,522 | 276 | `$0.001005` |
| Super | 5,546 | 403 | `$0.002027` |

`$0.0198` per Ultra debate against Super's `$0.0015` — **13×, not the 3.3× rate
multiple.** The rate accounts for 3.3× of that; the rest is token volume, because Ultra
emitted more tool-call rounds and each round resends the growing transcript. The corpus
comparison gave 5.2×, with empty search results and different cases. Real search results
adding input tokens to each round is the likely reason for the gap, but the two
measurements differ in more than that, so it is not isolated. An earlier
version of this section said "roughly `$0.007` per 20 cases", arrived at by multiplying
Super's token usage by Ultra's rate, which assumed the two models would spend the same
tokens, and they do not.

**Nano against Super on fraud screening, where the rules score 0.** 179 corpus cases (52
fraud, 127 honest), flag = model `risk_score` >= 40, a reply that fails to parse or
validate counted as a hold because the orchestrator refuses auto-clear after a model
failure (`scripts/compare_fraud_models.py`; `data/model_comparison/fraud_floor0.json`).
Nano flagged 46/52 frauds (88%) [77-95], Super 47/52 (90%) [79-96]: no difference the
sample can show. Super costs `$0.00114` a case against Nano's `$0.00026` (4.3×). Honest
cases held: Nano 80/127 (63%), Super 83/127 (65%). Failed replies: Nano 5/179 (2.8%,
schema error on `recommendations`), Super 1/179. On the holdout half Nano flagged 21/24
frauds the rules missed and held 30/53 honest shipments the rules passed; with the rules'
own 33 honest holds that is 63/86 (73%) honest holdout shipments held, against 38.4% for
the rules alone.

Setting `DEBATE_MODEL=nvidia/Nemotron-3-Ultra-550b-a55b` restores Ultra with no deploy.

#### Tavily is the binding cost constraint, not the models

Measured on a 20-case run: **90–106 Tavily searches** (4.5–5.3 per case) against
`$0.067994` of Nemotron. At the free tier's 1,000 credits a month that is **188–222
cases**, while the model bill for those cases is under a dollar — so the external
search, not inference, is what limits throughput. The board reseeded on 10 Oct 2026 after the
investigation fix measured `$0.087906` for the same 20 cases: in the earlier run half the
investigation replies were near-empty fragments, so a working investigation costs more
than a broken one did. Searches were not re-counted on that run. `estimated_cost_usd` counts Nebius
only, which is why `GET /api/v1/billing/usage` now also reports `tavily_searches`,
`tavily_cached` and `tavily_billable`. The three are summed independently rather than
derived from each other, because a cache hit and a request that never left the process
(no API key, a timeout) both cost nothing.

Caching is opt-in per call site and **only successful searches are stored**. Caching a
429 or a missing-key failure would turn one outage into a TTL-long outage, and would
re-create the defect `tavily_client` was written to remove: an outage read as a clean
result. An empty `OK` result *is* cached — "we searched and found nothing" is a real
answer. The cache lives in process memory, so on Cloud Run the hit rate depends on which
instance serves the request; a cold instance after a deploy starts empty.

`NEMOTRON_MODEL` and `VISION_MODEL` are read straight from the environment and do
**not** pass through the `PRICING` check that `POST /api/v1/config/model` enforces, so
pointing either at a model absent from `config.PRICING` — `nvidia/Nemotron-3_5-Lightning`
is servable on Token Factory today and is not in the table — costs every call at the
cheapest rate in the table. That under-reports spend, and the tenant spend ceiling
reads the same figure, so it is logged at ERROR both at startup and per call rather
than being silently absorbed.

---

## Findings & learnings

**A measured classifier can still be wrong on the shape of production input.** Every HS
evaluation set and the whole benchmark corpus declare a plain 4-digit heading, like
`8414`. The seeded live board declares `6205.20`, and Nano, asked whether the goods'
heading equals the declared one, answered `6205` and "inconsistent" — on three clean
shipments in three. Nothing measured could see it, because nothing measured had a dot in
it. The guard that caught it was a deterministic one: a reply naming the declared heading
as the goods' own is recorded as `HS_DESCRIPTION_CHECK_CONTRADICTORY`, an observation
with floor 0, so it raised no risk floor. The fix sends the classifier the 4-digit
heading, the shape the numbers were measured on, and a test and a mutation now pin it.

The fix is a trade, and it was measured rather than assumed. On the live model, four runs
per input over the seed board's declarations:

| | Before | After |
|---|---|---|
| The seeded mismatch (furniture declared 9403.60) caught | 0 / 4 | 3 / 4 |
| Four honest declarations given a floor | 4 / 16 | 7 / 14 (2 timeouts) |

Before, the classifier was close to switched off for any code with a subheading: nearly
every reply was "inconsistent" naming the declared heading, which the guard zeroes, so a
real substitution written as `9403.60` went through too. After, production runs the
configuration the 91.7% holdout figure describes, and it queries more of the seed's loosely
described goods — "ceramic tableware" sits between 6911 and 6912, and "woven cotton
garments" does not say shirts. A query costs a person ten minutes and a missed
substitution releases the cargo, which is the asymmetry the whole design rests on, so the
fix stays. The samples are small; what they establish is the direction, not the rate.
The seed board's base cargo now names what 6205 covers, men's shirts: a clean control that
draws a query on its wording is not a clean control.

**Token Factory has 24 models and not one of them is a safety model.** Measured
against the live `/v1/models` endpoint: four NVIDIA models, all chat
(`Nemotron-3_5-Lightning`, `NVIDIA-Nemotron-3-Nano-30B-A3B`,
`nemotron-3-super-120b-a12b`, `Nemotron-3-Ultra-550b-a55b`), no `nemoguard`, no
content-safety classifier, nothing purpose-built for screening input. That is the
single reason a component of this otherwise Nemotron-driven pipeline is a Google
service: there is no NVIDIA-native option on the platform to screen a document with.

**NVIDIA NeMo Guardrails was evaluated to replace Model Armor, and was not adopted.**
The reasoning, since "why isn't the security layer NVIDIA?" is the obvious question:

- It is a **toolkit, not a model**. Adopting it would have added an NVIDIA library
  wrapping a Nemotron call, not an NVIDIA model — so it does not strengthen the
  Token Factory or Nemotron story that the track actually asks about.
- Its `self check input` rail asks an LLM whether text is trying to manipulate an
  LLM, which is **itself injectable**. Model Armor is a purpose-built detector. Asking
  the vulnerable component to police itself is a weaker guarantee, not a stronger one.
- Removing one Google service would not have made the deployment less Google: it runs
  on Cloud Run, Firestore, Cloud Storage and Pub/Sub regardless.
- `nemoguardrails` makes LangChain opt-in but carries `fastembed` and `onnxruntime` as
  mandatory base dependencies, and emits usage telemetry to NVIDIA on `LLMRails`
  instantiation unless `NEMO_GUARDRAILS_NO_USAGE_STATS=1` is set.
- The windowing that `model_armor.py` needs for accuracy would have turned nine
  near-free HTTP calls per document into nine Nemotron calls.

What was taken from the evaluation instead: a free deterministic pass over
`untrusted.INJECTION_PATTERNS` now runs before Model Armor on every screen. It closes
a real gap — an injection in document prose that the vision extractor does not carry
into any structured field never reaches the field-level screen, so nothing catches it
when Model Armor is unreachable. It is **advisory, not blocking**, and deliberately so:
those patterns were written for extracted field values, and a bill of lading
containing the ordinary strings `Booking System:` and `pre-approved` trips two of
them. A committed test asserts exactly that document is not blocked, because refusing
a real shipment on a form label is a worse failure than screening it a moment later.

**Vision models on OpenAI-compatible endpoints want images, not PDFs.**
Gemini read PDF bytes directly; MiniCPM-V, like most vision models behind an
OpenAI-compatible API, expects an `image_url` — sending raw PDF bytes there
either errors or silently misreads the document. `document_agent.py` now
rasterises the first page to PNG with `pypdfium2` before the call.

**A failed search must not read as a clean one.** Tavily is new to this system, and it
would have been easy to let a missing key or a timeout raise into the request handler
and fail the case. Our first integration went the other way: `tavily_client.search()`
returned an empty list on any failure, so the compliance model was told "searched,
found nothing" about a search that never ran. Compliance now calls `search_cached()`
and carries the search status into the prompt (the worse of the shipper and receiver
searches), as the zero-day radar, investigation and the debate do, so an outage still
never blocks a case but is never mistaken for a clean result.

**JSON mode travels well across providers.** Both Gemini's
`response_mime_type="application/json"` and the OpenAI-compatible
`response_format={"type": "json_object"}` do the same job — coerce the model
into emitting parseable JSON — so the prompts and output schemas of the four agents
that existed at the time needed no changes at all, only the transport underneath them.
One model did not carry over cleanly: Nemotron 3 Super with reasoning on returns a
fragment such as `{": {}}": null}` for half its replies under `json_object`, so the
investigation agent now asks it without that mode (see the model section above).

**A human reviewer with no paperwork is not a control.** (Carried over from
the original build.) The review panel only showed a source document for
cases uploaded as a document; event-sourced cases now get a
`SYSTEM-GENERATED` bill of lading rendered from the record
([`document_render.py`](src/vf_logistics/document_render.py)), clearly labelled as such.

**`asyncio.run()` per Flask request breaks a cached client.** (Carried over.)
Every coroutine runs on the one long-lived worker loop the orchestrator
already uses, rather than opening and closing an event loop per request.

**Cloud Build source deploys need three separate grants.** (Carried over.)
`storage.objectAdmin`, `artifactregistry.writer` and `logging.logWriter` on
the default compute service account, or a build that reports `SUCCESS` with
no pushed image and no visible log output.

---

## Roadmap

The orchestration layer and the Nebius/NVIDIA model layer are both live, and so is
deterministic sanctions screening against the real OFAC SDN and UN Security Council
lists (18,525 records, refreshed by `scripts/refresh_sanctions.py` into GCS). What
remains stubbed is historical data: the agents receive route-cost baselines as
request fields rather than pulling them from a warehouse. Next steps: a real
historical-baseline store, the EU and UK consolidated lists alongside OFAC and UN,
a scheduled refresh instead of a hand-run one, a CI job with the Firestore emulator so
the 16 `FirestoreStore` tests that skip today run on every push, and replacing the
scripted simulator with a production Pub/Sub subscription from the shipment system.

Longer term, closing the loop on the humans this system currently escalates
to: build a **Toloka**-backed human-in-the-loop review layer where real customs
and compliance reviewers label the Review Queue's escalated cases (agreed with
the AI, overrode it, or split the difference), and feed that labelled history
back as fine-tuning data for the Nemotron Nano scoring agents — plus
**Tandem** sessions with domain experts to pressure-test the fraud/compliance
prompts against real edge cases before they reach production. Neither is
implemented yet; today's escalation path already produces the human decisions
this would need as training signal (`hold_shipment`, `draft_sar`, the analyst's
resolution), so the labelled data is a byproduct of normal use, not a separate
collection effort.

---

## Repository layout

```
.
├── src/vf_logistics/             The backend package. PYTHONPATH=src reaches it.
│   ├── app.py                    Flask app, routes, async bridge, worker boot
│   ├── orchestrator.py           Autonomous state machine + background worker
│   ├── config.py                 Model registry, per-token pricing, runtime switch
│   ├── governance.py             Delegation Boundary + fail-closed execution gate
│   ├── evidence.py               Verification loop: evidence requests, the signed link, approval, execution
│   ├── decision_receiver.py      The receiving side of the decisions topic: Pub/Sub push, OIDC check, applies each key once
│   ├── verifier.py               Deterministic risk floor (no model consulted)
│   ├── untrusted.py              Schema whitelist for document-sourced fields
│   ├── shipper_registry.py       Counterparty book: verifies a claimed shipper identity
│   ├── sanctions.py              Sanctions index, loaded from Cloud Storage
│   ├── sanctions_sources.py      Parsers for the OFAC SDN and UN consolidated lists
│   ├── hs_reference.py           Published HS heading contents; took recall 40.0% → 92.9%
│   ├── model_armor.py            Windowed prompt-injection screening
│   ├── nebius_client.py          Nebius Token Factory client (OpenAI-compatible)
│   ├── tavily_client.py          Tavily search API wrapper, with the TTL cache
│   ├── store.py                  Case/event/audit state (Firestore, memory fallback)
│   ├── auth.py                   Roles, API keys, operator records
│   ├── budget.py                 Per-tenant soft spend ceiling
│   ├── tenant.py                 Tenant resolution and scoping
│   ├── membership.py             Which tenant a principal may act in, and with what role (MULTI_TENANT)
│   ├── lineage.py                Per-step cost attribution
│   ├── evaluation.py             Serves the committed benchmark and HS reports, never per-case rows
│   ├── worklist.py               Read models behind the Today and Outcomes screens
│   ├── observability.py          Structured logging, metrics, request context
│   ├── schemas.py                Request/response validation, and AGENT_OUTPUT_SCHEMAS for six agents' replies
│   ├── openapi.py                Generates the OpenAPI document
│   ├── b2b.py                    The published contract surface
│   ├── document_render.py        Renders event-sourced shipments as a bill of lading
│   ├── dossier.py                The case as a due-diligence dossier (PDF), built from the stored case
│   ├── document_store.py         Cloud Storage document archive
│   ├── executor_client.py        Calls the split-identity executor service
│   ├── tools.py                  Actions taken on the operator's behalf
│   ├── simulator.py              Scripted shipment events for the demo
│   ├── static/index.html         The legacy dashboard, now served at /legacy
│   └── agents/
│       ├── __init__.py           Public agent API
│       ├── _common.py            Shared JSON parsing, schema check (validate_result), timing, response envelope
│       ├── document_agent.py     Multimodal document intake      — MiniCPM-V-4.5
│       ├── fraud_detection_agent.py  Fraud scoring               — Nemotron 3 Nano
│       ├── compliance_agent.py   Sanctions / trade / AML + Tavily — Nemotron 3 Nano
│       ├── hs_classifier_agent.py    Declared heading vs cargo   — Nemotron 3 Nano
│       ├── hs_cot.py             Reasoning-first prompts and exemplars; the few-shot regression
│       ├── zero_day_agent.py     Adverse media ahead of the lists — Nemotron 3 Nano
│       ├── investigation_agent.py    Deep-dive investigation     — Nemotron 3 Super
│       └── debate_agent.py       Senior Auditor debate           — Nemotron 3 Super
├── tests/                        105 files, 2,095 tests
├── scripts/                      Not deployed; seeding, verification, docs, narration
├── sample_docs/                  Seven committed sample PDFs, one per mechanism
├── data/                         Sanctions, HS reference, synthetic corpus, benchmark and eval reports
├── frontend/                     Next.js 16 console, built into the same image as the API
│   ├── src/app/                  App Router pages: board, radar, review, audit, governance,
│   │                             devops, agents, evaluation, admin, legal, login, today,
│   │                             outcomes, cases/[id], and the shipper's respond/[token]
│   ├── src/components/           UI, incl. the case trace sheet and layout shell
│   ├── src/lib/session.ts        HMAC session signing, via Web Crypto so it runs on Edge
│   ├── src/lib/proxy-policy.ts   The BFF allow-list; the only place the console's key is attached
│   ├── src/lib/upstream.ts       Public API pass-through, with the caller's own credential
│   ├── src/proxy.ts              The login door (Next 16 renamed `middleware` to `proxy`)
│   └── scripts/make-operator.mjs PBKDF2 operator records; writes the password to a file
├── infra/
│   ├── firestore.indexes.json    27 composite indexes; every one leads with _tenant_id
│   ├── model_armor_template.json Filter config for the Model Armor template
│   ├── monitoring/               Alert policies, the spend-ceiling metric, billing indexes
│   └── terraform/                Cloud Armor policy (written, not applied)
├── docs/
│   ├── ARCHITECTURE.md           The source of truth for how it fits together (includes mermaid diagrams)
│   ├── architecture.html         The architecture diagram as a standalone page
│   ├── DEMO_SCRIPT.md            Eight scenes, timed to the narration track
│   ├── PROJECT_STORY.md          What was built and what it cost to learn
│   ├── RECEIVER_CONTRACT.md      What Floorline publishes, what a receiver must do, the sent ledger and the receiver it ships
│   ├── swagger.json              Generated by scripts/build_docs.py — do not hand-edit
│   └── diagrams/                 Mermaid flows
├── .github/workflows/ci.yml      ruff, mypy (ceiling 0), tests in the emulators (92% floor), frontend (coverage floor 35%), container smoke
├── Dockerfile                    The deployed image: Next.js console + Flask API, one container
├── Dockerfile.backend            The API alone, for running Flask without the console
├── entrypoint.sh                 Starts Flask on 127.0.0.1:9090, waits for /health, then Next.js
├── pyproject.toml                Package config and pytest settings
├── requirements.txt
├── .env.example
├── SUBMISSION.md                 Devpost copy
├── LICENSE
└── README.md
```

## License

MIT — hackathon project, 2026.
