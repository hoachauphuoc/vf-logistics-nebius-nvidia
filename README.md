# Floorline — shipment-fraud agents that can raise risk, never lower it

The name is the design rule. Deterministic checks set a risk **floor** for every
shipment; the agents may argue a case above that line, and nothing they say can take it
below. (VF Logistics is the freight operator in the demo; the repository, the Cloud Run
service `vf-app` and the API keep that name.)

**Built on:** **Nebius Token Factory** for every model call, running **NVIDIA Nemotron 3
Nano** (fraud, compliance, HS classification, zero-day radar), **NVIDIA Nemotron 3
Super** (investigation) and **NVIDIA Nemotron 3 Ultra** (the Senior Auditor debate),
plus MiniCPM-V-4.5 for reading scanned documents.

**Hackathon:** Nebius x NVIDIA Global AI Hackathon
**Track:** Best Apps and Agents
**Bonus target:** Best Use of Tavily ($3,000, stackable with a Track Award)

**Live demo (console):** https://vf-app-350828852747.asia-southeast1.run.app
**API:** the same URL, under `/api/v1` — health at
https://vf-app-350828852747.asia-southeast1.run.app/health, the OpenAPI document at
https://vf-app-350828852747.asia-southeast1.run.app/api/v1/openapi.json

One Cloud Run service, `vf-app`, runs the Next.js console and the Flask API in one
container. The console is readable without signing in — the board, every case trace,
the review queue and the audit trail are all public. Two things are not: the spend
figures (operator) and the archived original documents (reviewer), because an anonymous
visitor is a real `viewer` and both sit above it. **Recording a decision needs an
account**, because the audit trail names the person who released a shipment rather than
the service that called the API, and a free-text name field would make that record
worthless. Judges: **Continue as guest judge** on the login page signs you in with one
click and can do everything except clear the board, revoke the agent's authority or
edit the screening rules; the password accounts are in the
Devpost submission's testing-instructions field — a governance-admin account, and one
that holds only the Reviewer role, so you can watch the access control refuse something.

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
in [Measured results](#public-enforcement-cases), the rules plus the agents held 14 of 19
real frauds. And **make every hold quick and defensible to decide**, because at 0.2% fraud
even a good screen holds hundreds of honest shipments per real one. That second job is
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
append-only record naming who or what allowed each action. Model spend is under half a
cent per case (`$0.068`–`$0.088` for a 20-case run); the measured detection figures, on
held-out synthetic data and on 19 public enforcement cases, are in
[Measured results](#measured-results).

A shipment event arrives and nobody touches it again. A background worker scores
it for fraud, decides on that score whether compliance screening is warranted,
decides on the screening whether to open a deep investigation, and then acts:
releasing the shipment, assigning an analyst, or holding the cargo and drafting a
suspicious activity report for human signature.

End to end, for one case:

> scanned document → Model Armor → document intake (MiniCPM-V) → deterministic risk
> floor and pre-filter → fraud + compliance (NVIDIA Nemotron 3 Nano, live Tavily search)
> → investigation (Nemotron 3 Super, Tavily) → auto-debate when floor and model disagree
> (Nemotron 3 Ultra, calling tools) → delegation gate → release / hold / assign analyst /
> draft SAR / webhook / Pub/Sub → audit trail

The case trace opens on this chain for the case in front of you, with the model that ran
each hop (`frontend/src/lib/case-chain.ts`).

The AI model layer runs on **Nebius Token Factory**: **NVIDIA Nemotron 3 Nano**
for fraud, compliance, HS classification and zero-day screening, **NVIDIA Nemotron 3
Super** for deep investigation, **NVIDIA Nemotron 3 Ultra** for the auto-debate, and
a vision model (**MiniCPM-V-4.5**) for document intake, since
Token Factory does not yet carry an NVIDIA vision model. Infrastructure — Cloud
Run, Firestore, Pub/Sub, Cloud Storage, Model Armor — stays on Google Cloud;
nothing about Nebius's rules requires moving hosting, only that the model calls
actually go to Token Factory, which they do.

---

## The design rule: model capacity only where it can change the answer

This is the one non-obvious decision in the system, and for a long time it was written
down 1,000 lines below here as a footnote to an environment variable. It belongs at the
top, because everything else about the model layer follows from it.

`verifier.py` computes a **deterministic risk floor**, and an agent may **raise** risk but
never lower it below that floor. The rule is asymmetric on purpose: escalating on model
judgement is acceptable, exonerating on model judgement is not, because the cost of a
wrong exoneration is released contraband and the cost of a wrong escalation is a human
spending ten minutes on a clean shipment.

**So Nemotron Nano on fraud and compliance is not a budget compromise. It is the correct
choice.** A stronger model there cannot move the outcome in the direction that matters —
the floor has already decided. Measured, putting those two on Ultra would cost 13× per
call, against a rate that is only 3.3×, for no change in any decision.

**And the debate is the one exception, which is why Ultra runs there and nowhere else.**
It fires when the floor and the model disagree by 15 points or more, and what it emits is
not another score for the floor to override — it is a reasoned CONFIRM or DISAGREE on
whether the junior analyst missed something, and that verdict changes routing. In one
direction only: a genuine DISAGREE at confidence 0.7 or above
(`DEBATE_ESCALATE_CONFIDENCE`) sends the case to deep investigation on Nemotron Super —
proposed outcome `ESCALATED`, a SAR drafted for sign-off — and may raise effective risk
to the auditor's adjusted score, never lower it. CONFIRM, a forced default verdict or a
low-confidence DISAGREE change nothing, and `case.debate_effect` records why. A person
still decides every disputed case, because `score_disputed` is a `require_human_when`
trigger in the delegation boundary. So this is the one hop whose output is a verdict on
the dispute rather than a score the floor overrides, and reasoning capacity is
load-bearing there. Measured: `$0.0198` per Ultra debate against Super's `$0.0015`.

The invariant is not a convention. `validate()` computes the floor twice, with and
without the model's finding, and raises if the model's contribution lowered it:

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

Full working, with the per-call measurements and why the cost multiple is 13× rather than
the 3.3× the rate implies: *[Why Ultra is on the debate agent and nowhere else](#why-ultra-is-on-the-debate-agent-and-nowhere-else)*.

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
git diff --shortstat 6bb1e59 b52ea52   # everything since: 297 files, +171,921, in 49 commits
```

The end of the second range is pinned to a commit rather than `HEAD`, which would make
the figure wrong again with the next commit.

The deterministic governance layer — risk floor, untrusted-input boundary,
delegation boundary, shipper identity verification — was carried over rather than
rebuilt, because none of it is model-specific. It is what keeps the system honest
regardless of which model is reasoning. Carried over is not the same as untouched:
`untrusted.py` is byte-for-byte the `755d998` file and `shipper_registry.py` differs
by eleven lines added and two removed, while `verifier.py` grew from 487 lines to
1,618 (+1,151 / −20) and `governance.py` from 492 to 659 (+184 / −17). The
false-positive tuning below is one of the changes to `verifier.py`.

The areas below were rebuilt.

### The model layer

**Before:** four agents on Vertex AI. Gemini 3.5 Flash for document intake, fraud
and compliance; Flash-Lite for investigation, with `thinking_budget=8000`.

**Now:** seven agents on Nebius Token Factory, four models chosen per job.
Nemotron 3 Nano runs the four hops that touch every case; Super runs
investigation; **Ultra runs the auto-debate**; MiniCPM-V-4.5 reads documents,
because Token Factory carries no NVIDIA vision model yet.

**Why the split rather than one model everywhere:** `verifier.py` computes a
deterministic risk floor that an agent may raise but never lower, so on fraud and
compliance a stronger model cannot move the outcome in the direction that matters.
The debate is the exception — its CONFIRM/DISAGREE is a verdict that changes routing,
not a score the floor overrides: a confident DISAGREE escalates the case, and nothing
it says can lower risk — so that is the one place reasoning capacity is worth paying
for. Measured: `$0.0198` per Ultra debate against Super's `$0.0015`.

### Three agents that did not exist

**Before:** intake, fraud, compliance, investigation.

**Now:** plus `hs_classifier_agent.py`, `zero_day_agent.py` and
`debate_agent.py` — 1,656 lines including the chain-of-thought module.

**Why each:**

- **HS classification.** The deterministic checks can compare a declared tariff
  heading against a dual-use prefix list, but cannot tell whether the heading
  matches the cargo actually described. Measured on two sets (`scripts/eval_hs.py`):
  plain Nano reached 40.0% recall on the 30-case pairs set and 50.0% on a 24-case
  holdout of substitutions absent from the reference material, and two few-shot
  examples made it **worse** on both, at 26.7% and 33.3%. Structured reasoning over a
  reference extract of the published heading contents — the production mode — took
  it to **92.9%** recall at 100% precision on the pairs and **91.7%** with no false
  alarms on the holdout. Examples did not help; reasoning against the published
  headings did. Full table: *[HS classification, measured](#hs-classification-measured)*.
- **Zero-day screening.** Sanctions lists lag reality. This runs a live
  adverse-media search when a shipment trips a gate — a dual-use heading, or two or
  more distinct transhipment hubs.
- **Auto-debate.** Fires with no human involved when the floor and the model
  disagree by 15 points or more. Its verdict used to be recorded and read by nothing;
  a genuine, confident DISAGREE now sends the case to deep investigation — upward
  only.

### The console

**Before:** one static HTML page served by Flask from `static/`.

**Now:** a Next.js 16 console — 67 files, 12,672 lines of TypeScript, seven screens
over the operational API, since joined by Access Control (`/admin`) and Evaluation
(`/evaluation`). It started on a Cloud Run service of its own; it now runs in the same
container as the API, one service (`vf-app`) with Next.js on `$PORT` and Flask on
`127.0.0.1:9090` behind it. The old page is still bundled, at `/legacy` when Flask
runs on its own; the deployed container does not pass that path through.

**Why:** the static page could not carry sessions, and the submission needed a
reviewer to sign in before recording a decision. That requirement is the next item.

### Accountability in the audit trail

**Before:** the `reviewer` field was read from the **request body as free text**.
Anyone could record a decision under anyone's name, which makes an audit trail
decoration rather than evidence.

**Now:** HMAC-signed sessions (`auth.py`, 614 lines), operator records as
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

**Now:** `ANONYMOUS_ROLE=viewer`, `X-VF-API-Key` required on writes, and the split
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

**Before the tuning in `afb3be3`:** the deterministic layer caught nearly every attack
in the synthetic corpus and held most of the clean traffic with it — on the holdout
split, a false-positive rate of 76.7%.

**Now:** 38.4%, with precision 84.1% → 91.2% and recall 95.1% → 93.5%, and
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

**Now:** **922 backend tests** at 81% line coverage, 146 frontend tests, and a
mutation check — `scripts/check_test_sensitivity.py` breaks 36 lines on purpose and
the suite catches all 36. Five GitHub Actions jobs run on every push to `master`:
lint, typecheck, test (with a 75% coverage floor), frontend, and a container job that
builds both images and smoke-tests the deployed one. `755d998` had no CI. The workflow
added here on 19 Sep (`a452fd6`) filtered on a branch named `main` while this
repository uses `master`, so it never executed until `64c9e6d` fixed the trigger on
24 Sep.

### Structure

**Before:** a flat repository root — `main.py`, `orchestrator.py`, `agents/` and
fifteen other modules at top level.

**Now:** a `src/vf_logistics/` package with ten modules that did not exist at all:
`auth.py`, `budget.py`, `tenant.py`, `b2b.py`, `openapi.py`, `sanctions.py`,
`hs_reference.py`, `lineage.py`, `observability.py`, `schemas.py`.

## What the system does

Seven specialised agents plus a deterministic verification layer, coordinated by a
governance control plane:

| Agent | Responsibility | Model | Notable config |
|---|---|---|---|
| **Document Intake** | Transcribes bills of lading, invoices and packing lists into a structured record. Reports missing fields as missing rather than inventing them. | `openbmb/MiniCPM-V-4_5` | `temperature=0.0`, multimodal image input (PDFs rasterised first) |
| **Fraud Detection** | Price manipulation, route fraud, weight/dimension fraud, document fraud, identity fraud, duplicate & time fraud. | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | `temperature=0.1` for stable scoring |
| **Compliance Screening** | Sanctions exposure (OFAC/UN/EU patterns), trade & regulatory compliance, AML indicators — grounded by a live Tavily search. | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | `temperature=0.1`, runs in parallel with fraud, Tavily search injected as evidence |
| **AI Investigation** | Multi-step case investigation, pattern analysis, network mapping. | `nvidia/nemotron-3-super-120b-a12b` | Only reached on escalated cases |
| **Multi-Agent Debate** | Senior Auditor (Ultra) reviews Junior Analyst (Nano) fraud assessment using function calling. Can request re-evaluation, run Tavily searches, and render CONFIRM/DISAGREE verdicts. A confident DISAGREE escalates the case; nothing it says can lower risk. | `nvidia/Nemotron-3-Ultra-550b-a55b` | Fires automatically on a 15-point floor-model gap; also manual via "Deep Review". Function calling with 3 tools |

### Model selection, chosen per task

The hackathon's own model guidance is: let Nano or Super handle the fast,
everyday calls, and reach for Ultra when you need serious reasoning. This
system follows that shape directly:

Fraud and compliance screening run on **Nemotron 3 Nano** — every shipment
that arrives gets scored by both, so this is the highest-volume call in the
pipeline. Nano is also fast and cheap, but that is a side benefit rather than the
reason: these two hops sit under the deterministic floor, so a stronger model
cannot move either outcome in the direction that matters. Choosing Nano here costs
nothing in accuracy, which is what makes it the right choice rather than a
compromise — see *[The design rule](#the-design-rule-model-capacity-only-where-it-can-change-the-answer)*.

Investigation runs on **Nemotron 3 Super** — by the time a case reaches it, the
fraud and compliance findings already exist; it only runs on cases that were
escalated or where the deterministic floor and the model disagreed, so it is
the low-volume, high-stakes call that can afford a stronger, pricier model.

The debate agent runs on **Nemotron 3 Ultra**, and it is the only place Ultra is used.
Not because the debate is the most important step, but because it is the only one whose
output the deterministic floor does not override — see
[Why Ultra is on the debate agent and nowhere else](#why-ultra-is-on-the-debate-agent-and-nowhere-else).
Investigation deliberately stays on Super: it is 40% of measured spend already, and
`INVESTIGATION_MODEL` can point it at Ultra if more Token Factory credit becomes
available.

Document intake is the one agent that needs a vision-capable model, and
NVIDIA does not currently publish one on Token Factory, so it runs on
**MiniCPM-V-4.5**, a model the catalog specifically calls out for OCR/PDF
understanding.

All three NVIDIA models and MiniCPM-V are reached through the same
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
`tavily_client.search()` with the shipper and receiver names (e.g. `"<name>"
sanctions OR fraud OR "shell company"`), and the results are folded into the
model's context as a clearly labelled, untrusted evidence block — a real
runtime web search, not a documented-but-unused integration. A Tavily outage
or a missing API key degrades the agent to its pre-Tavily behaviour rather
than blocking the pipeline.

### Multi-Agent Debate: Ultra reviews Nano

The most sophisticated reasoning pattern in the system is **Multi-Agent Debate**,
where a Senior Auditor (Nemotron Ultra 550B) reviews the Junior Analyst's
(Nemotron Nano 30B) fraud assessment.

**Why two models?** Nano is fast and cheap — it scores every shipment that arrives.
But speed optimises for throughput, not for catching the subtle case that slips
through. Ultra is slower and costs more, but it can challenge Nano's reasoning
and catch what Nano missed. The debate is asymmetric: Ultra can call Nano back
for a re-evaluation with specific focus areas, but Nano never calls Ultra.

**Function calling, not prompt chaining.** Nemotron Ultra supports native
tool_calls, so the debate agent uses real function calling with three tools:

| Tool | Purpose |
|---|---|
| `request_nano_reevaluation` | Ask Nano to re-score the shipment with specific focus areas (pricing, identity, route, documents, timing) and a hypothesis about what it might have missed |
| `search_tavily` | Run an additional web search for context (e.g., "Thanh Phat Trading sanctions Vietnam") |
| `render_final_verdict` | Submit the final verdict: **CONFIRM** (agree with Nano) or **DISAGREE** (found issues Nano missed), with confidence, rationale, and recommended action |

Ultra iterates through tool calls until it calls `render_final_verdict`, up to
3 rounds. The debate is recorded on the case and rendered on the review page and in
the case trace as a readable panel — verdict, confidence, rationale, what it changed,
and the rounds — with the raw record one click away, so the analyst sees exactly what
Ultra did.

**When it runs.** The debate fires **automatically**, with no human involved, when
the deterministic floor and the model disagree by 15 points or more — measured at 2
calls across 20 cases. A reviewer can also trigger it manually as "Deep Review"
when:
- The risk score seems too low for the red flags present
- The shipper or receiver name sounds suspicious
- The case is borderline and the analyst wants a second opinion

It is expensive: measured at `$0.0198` per debate against Super's `$0.0015`, and
14–22 seconds against Super's 4–6. See
[Why Ultra is on the debate agent and nowhere else](#why-ultra-is-on-the-debate-agent-and-nowhere-else)
for why that is worth paying on this call and on no other.

**What the automatic verdict changes, and what it cannot.** It never overrides a
person's decision, and it can only push a case upward. A genuine DISAGREE at confidence
0.7 or above (`DEBATE_ESCALATE_CONFIDENCE`) sends the case to deep investigation on
Nemotron Super — proposed outcome `ESCALATED`, a SAR drafted for sign-off — and may
raise effective risk to the auditor's adjusted score, never lower it. CONFIRM, a forced
default verdict or a low-confidence DISAGREE change nothing, and `case.debate_effect`
records which applied. Before this the verdict was recorded and read by nothing, so the
most expensive call in the pipeline could not change a single outcome. A disputed case
still goes to a person either way, because `score_disputed` is a `require_human_when`
trigger in the delegation boundary. A manual Deep Review runs on a case already waiting
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
                 |      investigation                      |
                 |    NVIDIA Nemotron 3 Ultra              |
                 |      the auto-debate                    |
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
     orchestrator.py: asyncio worker loop, runs with no request in flight,
     claims a case under a lease, performs exactly one step, persists, repeats
                             |
       INGESTED --> fraud_detection agent (Nemotron Nano) --> risk_score
          |
          +-- risk < 40 --------------------> AUTO_CLEARED
          |                                     release_shipment()
          |
          +-- risk >= 40 --> compliance agent (Nemotron Nano + Tavily)
                    |
                    +-- cleared, risk < 70 --> HELD_FOR_REVIEW
                    |                            assign_analyst()
                    |
                    +-- BLOCKED / REVIEW_REQUIRED, or risk >= 70,
                        or a confident Senior Auditor DISAGREE
                              |
                              v
                     investigation agent (Nemotron Super)
                              |
                              v
                           ESCALATED
                             hold_shipment()
                             draft_sar()
                             notify_webhook()
                             assign_analyst()

       Any step failing 3 times, with 5s/10s/20s backoff --> DEAD_LETTER

       Terminal decisions are published to Pub/Sub case-decisions for
       downstream ERP / WMS / billing, and every action lands in audit_log.
```

Thresholds are environment variables (`FRAUD_CLEAR_BELOW`, `INVESTIGATE_AT`), so
the routing policy is configuration rather than something buried in code. So is the
debate's: `DEBATE_ESCALATE_CONFIDENCE`, default 0.7, is the confidence a genuine
DISAGREE needs before it can send a case down the investigation branch that it would
otherwise have skipped.

### Why these choices

- **OpenAI-compatible client, one wrapper for four models** — `nebius_client.py`
  wraps `openai.AsyncOpenAI` pointed at Token Factory; all three Nemotron tiers
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
- **Tavily failures degrade, not block** — `tavily_client.search()` returns an
  empty list on any error (missing key, timeout, non-2xx), so a Tavily outage
  falls back to model-only screening instead of failing the case.

---

## Tech stack

| Layer | Choice |
|---|---|
| Model | **NVIDIA Nemotron 3 Nano** (fraud, compliance, HS classification, zero-day radar) + **NVIDIA Nemotron 3 Super** (investigation) + **NVIDIA Nemotron 3 Ultra** (Senior Auditor debate) + **MiniCPM-V-4.5** (document intake, vision), all via **Nebius Token Factory** |
| Agent framework | `openai.AsyncOpenAI` (Token Factory's OpenAI-compatible endpoint) |
| External signal | **Tavily Search API** — live sanctions/news lookup in the compliance agent |
| Input security | **Model Armor** (Google Cloud) — windowed prompt-injection screening |
| Compute | **Cloud Run** (source deploy -> Cloud Build -> Artifact Registry) |
| State | **Firestore** (Native mode) — cases, events, audit log |
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
| `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | fraud, compliance, HS classification, zero-day radar — the four hops that touch **every** case | `verifier.py` computes a deterministic risk floor an agent may raise but never lower, so a stronger model cannot move these outcomes in the direction that matters |
| `nvidia/nemotron-3-super-120b-a12b` | investigation | writes the narrative a human reads; benefits from reasoning, does not decide the verdict |
| `nvidia/Nemotron-3-Ultra-550b-a55b` | the auto-debate ("Senior Auditor") | the one place where the model's output is a verdict that changes routing rather than a score the floor overrides — a confident DISAGREE escalates the case, upward only — so reasoning capacity is worth paying for: measured `$0.0198` per debate against Super's `$0.0015` |
| `openbmb/MiniCPM-V-4_5` | document intake (vision) | not an NVIDIA model, and said plainly: Token Factory carries no NVIDIA vision model yet |

**Where Token Factory accelerated the workflow.** All four models, from 30B to 550B plus a
vision model, are served by **one** OpenAI-compatible endpoint
(`https://api.tokenfactory.nebius.com/v1/`) through `openai.AsyncOpenAI` — `nebius_client.py`
is a thin wrapper, not a bespoke SDK. Three consequences that shaped the build:

- **Model choice became a config value, not an infrastructure change.** `config.py` holds
  the ids and per-token prices; `set_model` swaps them per task. Escalating one hop from
  Nano to Super to Ultra is a string, so the HS experiment — plain Nano, few-shot,
  structured reasoning, reasoning over the published headings, and Super as the teacher
  — cost nothing in plumbing. It took Nano from 40.0% to 92.9% recall on the pairs set
  and from 50.0% to 91.7% on the holdout.
- **No GPU provisioning, so a 550B model was affordable to reach for once.** Ultra runs only
  on the debate path, which fires when the deterministic floor and the model disagree by 15
  points or more. Standing up 550B of capacity for an occasional call would not have been
  worth it; per-token access made a rarely-used heavyweight practical.
- **The port from the predecessor was a client change, not a rewrite.** The JSON contract
  each agent returns was preserved, so swapping Vertex AI Gemini for Token Factory changed
  the base URL, the model ids and the sampling parameters — not the pipeline.

**Other Nebius services used: none.** Token Factory's inference API is the whole Nebius
surface here. Serverless Endpoints and Serverless Jobs are encouraged by the track and are
**not** used — the service runs on Cloud Run, which is stated rather than dressed up.

**Tavily**, which is a separate bonus track, is a live runtime call in five places, not a
stub. See *A real Tavily call, not a simulated one* above.

### Requirement check against the hackathon rules

Checked against the Official Rules for this Hackathon. An earlier version of this table
checked against the **predecessor** hackathon's criteria — it listed "multi-step autonomous
workflow" and "takes meaningful action", which are not requirements here, and omitted the
track, the video, the feedback and the licence, which are.

| Rule | Where it is met |
|---|---|
| Runtime call to Nebius Token Factory | every one of the seven agents |
| At least one NVIDIA open source model | three Nemotron 3 sizes, table above |
| Fits one of the four tracks | **Best Apps and Agents** |
| Significantly updated after the Submission Period opened (26 Aug 2026) | every commit in this repository is dated 17–24 Sep 2026; `git log --reverse --format="%ai"` shows the first |
| Written explanation of what was updated | *What was significantly updated during the Submission Period*, above |
| URL to a working demo | the `vf-app` URL at the top of this file: the console at `/`, the API under `/api/v1` |
| Public repository with a detectable open source licence | GitHub reports this repository's licence as **MIT** |
| README with setup and running instructions | *Spin-up instructions*, below |
| Highlight the NVIDIA models, Token Factory and Nebius services | the section immediately above |
| Feedback on Token Factory, AI Cloud and NVIDIA tools | `SUBMISSION.md` -> *Feedback on Nebius Token Factory, AI Cloud, and NVIDIA tools* |
| Free, unrestricted access for judging, with credentials | *The demo accounts*, below |
| Demonstration video under three minutes, public on YouTube | **OUTSTANDING** — the shooting script is `docs/DEMO_SCRIPT.md` |
| Bonus: functional runtime Tavily call | `tavily_client.search()` on the live compliance path, five integration points |

---

## API

The JSON contract every agent returns was
preserved through the port, so every endpoint below behaves identically to
before; only the `model` field in each response envelope changed.

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
| `/api/v1/orchestrator/drain` | POST | Run every pending case to a terminal state |
| `/api/v1/events/document` | POST | Document intake. Multipart `file` (PDF or image). Screens for injection, transcribes, archives the original, then runs the case to a terminal state in the same request. |
| `/api/v1/events/storage` | POST | Cloud Storage notification sink |
| `/api/v1/ingest/bucket-sweep` | POST | Ingest every unprocessed object in `DOCUMENT_BUCKET` |
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
| `/api/v1/config/model` | GET, POST | Read or switch the Nemotron model used by fraud and compliance. Investigation is pinned separately via `INVESTIGATION_MODEL`. |
| `/internal/execute` | POST | The execution surface, deployed a second time as a split-identity executor |

### Direct agent access

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Web dashboard (HTML) |
| `/health` | GET | Health check, store backend, worker status |
| `/agents` | GET | Agent metadata & capabilities, including which model each runs on |
| `/demo` | GET | Runs the fraud agent on a built-in sample shipment |
| `/api/v1/fraud/analyze` | POST | Analyse one shipment |
| `/api/v1/fraud/batch` | POST | Analyse many |
| `/api/v1/compliance/screen` | POST | Compliance screening for a shipment (includes a Tavily lookup) |
| `/api/v1/compliance/entity` | POST | Screen a single entity |
| `/api/v1/investigation/case` | POST | Deep-dive investigation |
| `/api/v1/investigation/report` | POST | Consolidated report |

### Not listed above

These three tables document 30 of the 51 registered routes — the ones a caller is
likely to want. The five most useful omissions:

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/review/<case_id>/deep-review` | POST | Triggers the Ultra debate manually; the same agent the orchestrator fires automatically |
| `/api/v1/billing/usage` | GET | Windowed spend, including `tavily_searches` / `tavily_cached` / `tavily_billable` |
| `/api/v1/cases` | GET | Case list, slim shape, filterable by state |
| `/api/v1/audit` | GET | The audit trail, filterable by case, action or status |
| `/api/v1/security/screen` | POST | The Red Team surface: paste an attack, get the real screen verdict |

`GET /api/v1/openapi.json` serves a machine-readable document for the whole API, which
is the authoritative list. `docs/swagger.json` is a generated snapshot of the B2B
contract subset only.

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
  --set-env-vars "PROJECT_ID=$PROJECT_ID,WORKER_MODE=ondemand,STORE_BACKEND=firestore,ANONYMOUS_ROLE=viewer,VF_PUBLIC_READS=true" \
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
curl -s $BASE/api/v1/agents           # each agent reports the Nebius/NVIDIA model it runs on
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

**Most of the console needs no account.** An anonymous visitor is a real `viewer`
(`ANONYMOUS_ROLE=viewer`, `VF_PUBLIC_READS=true`): the board, every case trace, the review
queue, the audit trail, the governance history and the evaluation figures are all
readable. If you are here to assess the system, you can ignore this section entirely.

What each role adds is declared on the route itself, by its decorator, not kept in a
list, and `GET /api/v1/auth/policy` returns the table from the running service:

| Role | Routes | What it adds |
|---|---|---|
| none | 6 | Health, the OpenAPI document and the agent roster |
| `viewer` | 21 | Every read: cases, review queue, audit, governance, metrics, evaluation, and the policy dry run |
| `reviewer` | 3 | Decide a case, request a deep review, open the archived original document |
| `operator` | 23 | Anything that spends or ingests: shipments, documents, simulations, drains, resets, `/demo`, and the spend figures (`billing/usage`) |
| `governance_admin` | 4 | Publish or revoke the delegation boundary, change the prefilter rules, run the news scan |

Roles are cumulative: a reviewer is also a viewer, and so on up.

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
account listed in `ADMIN_EMAILS`. It can do everything the judge account can — inject
shipments, decide cases, simulate and publish policy — **except three changes that
would carry over to the next judge**: clear the board, revoke the delegation boundary
(which suspends the agent), and edit the pre-AI screening rules.

Those exceptions are enforced twice, not hidden. The session token carries an `amr`
claim (`password` or `one_click`) inside the same HMAC as the email, so it cannot be
edited. The console's BFF refuses `orchestrator/reset`, `governance/revoke` and the
`governance/prefilter-rules` PUT to any session that does not say `password`, and the
API refuses them again with `auth.require_password_session`, which
returns 403 with `required_auth: "password"`. A token without the claim — one minted
before it existed — counts as *not* a password. A script holding only the API key still
passes, because it has no session to ask about.

Every decision, publish and reset records `actor_auth` beside the name, so the Audit
Trail can tag what was done from the public guest session. The button is off unless
`VF_ONE_CLICK_JUDGE=true`, and `VF_ONE_CLICK_UNTIL` closes it on a date; an end date it
cannot parse closes it too. The session lasts four hours, and the route is POST-only and
rate-limited to 10 a minute per address.

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

Every figure here comes from a script in `scripts/`, is committed as a JSON report under
`data/`, and is served read-only by `GET /api/v1/evaluation` to the console's Evaluation
screen (`/evaluation`), so a number can be traced to the run that produced it. The
corpus is **synthetic** (`scripts/generate_synthetic_cases.py`, seed 20260920, 1,000
cases: 300 shell-company transhipment, 300 HS mismatch, 200 sanctions-alias evasion, 200
clean). No real shipment data is involved: these numbers say how the system behaves on
the attacks we could describe, not on the ones we could not.

### The detection benchmark

`scripts/run_massive_benchmark.py` splits the corpus by `sha256(case_id)[0] % 2` into a
dev half (547 cases) and a holdout half (453). The false-positive tuning was chosen on dev
only, so holdout is the number to quote.

**Rules arm** — the deterministic layer alone, no model calls, free to rerun:

| Holdout, 453 cases | Before tuning | After tuning |
|---|---|---|
| Precision | 84.1% | 91.2% |
| Recall | 95.1% | 93.5% |
| F1 | 0.893 | 0.923 |
| False-positive rate (86 clean) | 76.7% | **38.4%** |
| Sanctions-alias evasion caught | 87 / 87 | 87 / 87 |
| Shell-company transhipment caught | 156 / 156 | 156 / 156 |
| HS mismatch caught | 106 / 124 | 100 / 124 |

The price of the tuning is the last row: six HS substitutions the rules used to hold now
pass the rules alone, which is what the model arm is for. On dev after tuning the figures
are 91.0% precision, 93.5% recall and a 35.1% false-positive rate, so the holdout result
is not an artefact of which half the thresholds saw.

**Full arm** — rules, the HS classifier (Nano, `cot_strict`) and the zero-day radar
through the real gate, on 200 holdout cases taken by stride:

| 200 holdout cases | Rules alone | Full system |
|---|---|---|
| Precision | 90.9% | 90.3% |
| Recall | 95.8% | **100%** |
| F1 | 0.933 | 0.949 |
| False-positive rate (33 clean) | 48.5% | 54.5% |

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

### HS classification, measured

`scripts/eval_hs.py` grades the classifier's own verdict, not the case outcome, on two
sets: 30 pairs (`data/hs_pairs.yaml`, 15 evasive and 15 honest) and a 24-case holdout
(`data/hs_holdout.yaml`, 12 and 12) of substitutions absent from the reference material.
Recall is evasions caught. A reply the model failed to give is counted as neither class,
so the counts in brackets are the graded cases.

| Arm | Model | Pairs recall | Pairs FPR | Holdout recall | Holdout FPR |
|---|---|---|---|---|---|
| Rules (`check_hs_code`) | — | 0% (0/15) | 0% | 0% (0/12) | 0% |
| `base` | Nano | 40.0% (6/15) | 35.7% | 50.0% (6/12) | 41.7% |
| `few_shot`: two worked examples | Nano | **26.7%** (4/15) | 14.3% | **33.3%** (4/12) | 45.5% |
| `cot_zero`: ordered method, verdict last | Nano | 40.0% (6/15) | 28.6% | — | — |
| `cot`: method plus reasoning exemplars | Nano | 53.8% (7/13) | 21.4% | — | — |
| `cot_ref`: method plus reference with exclusion notes | Nano | 100% (15/15) | 0% | — | — |
| **`cot_strict`: method plus published heading contents (production)** | Nano | **92.9%** (13/14) | **0%** | **91.7%** (11/12) | **0%** |
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
- **The holdout is the test that matters:** 91.7% with no false alarms, on substitutions
  the reference never mentions, on Nano rather than Super.

### Public enforcement cases

The synthetic corpus tests the system against its authors' idea of fraud. So
`scripts/build_public_cases.py` rebuilds **19 real cases** — BIS Temporary Denial Orders,
OFAC settlements with freight forwarders, US Commerce circumvention findings, EPPO and
OLAF prosecutions — each as the shipment the paperwork showed, beside the honest trade it
imitated, with the regulator's URL and a verbatim quote on every case
(`data/public_cases.json`). Parties are screened against the real OFAC SDN and UN lists.

| 19 pairs | Rules alone | Full system |
|---|---|---|
| Frauds held | 11 / 19 | 14 / 19 |
| Honest counterparts held | 7 / 19 | 9 / 19 |
| Pairs separated (fraud held, honest cleared) | 4 | 3 |
| Model cost | $0 | $0.034 |

Read it as pairs. **Dual-use pairs are held on both sides**, correctly: controlled goods
need a licence check whether or not this consignee is honest. **Six origin-fraud pairs
are identical at booking** — Vietnamese-declared plywood made from Chinese veneer looks
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

**Workload at real fraud rates.** A corpus is a fifth to four-fifths fraud by
construction; a forwarder's book is not. Vietnam Customs found a violation in 29,849 of
16.84 million declarations in 2024, **0.18%**. At 0.2%, the tuned rules hold about 385 of
every 1,000 shipments to find about 2 real cases. The console's Evaluation screen shows
this for every report at 0.2%, 1% and 2%. The conclusion we draw is that the product's job
is not to hold fewer shipments but to make each hold quick and defensible to decide —
which is what the case trace, the Review screen and the dossier are for.

---

## Reproducible testing

```bash
# Unit + integration tests: 922, at 81% line coverage. CI fails below 75%.
python -m pytest tests/ -v --cov=vf_logistics --cov-fail-under=75

# The mutation check: breaks 36 lines on purpose, one at a time, and requires the
# suite to fail on every one. It edits source in place and restores it, so it
# refuses to run on a tree with uncommitted changes.
python scripts/check_test_sensitivity.py

# Frontend: typecheck, lint, 146 unit tests, production build
cd frontend && npx tsc --noEmit && npm run lint && npm test && npm run build

# Counterparty book, offline
python scripts/check_registry.py        # 11 checks
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
for weeks while testing code that was not in this repository, and then deleted the
seeded demo board the moment the URL was corrected.

Two live checks that need credentials and spend real tokens, so they are run by hand:

```bash
python scripts/check_model_switch_guard.py    # the cost ratchet, end to end, restores Nano
python scripts/compare_debate_models.py       # replays disputed cases through Super and Ultra
```

### Test coverage

| Suite | Count | What it covers |
|-------|-------|----------------|
| Sanctions & zero-day | 64 | Sanctions matching, list freshness, unseen-pattern handling |
| Official sanctions lists | 14 | OFAC SDN and UN parsers on real rows cut from the published files, a registration number from OFAC's remarks, short aliases dropped, `OOO` read as `LLC`, and a refresh that refuses to publish half a list |
| Due-diligence dossier | 11 | Every finding code lands on a reference that exists, the most specific guidance wins, the PDF renders from an empty or non-Latin case, a model's arrow is spelled out rather than printed as `?`, and the route is a viewer read scoped to the tenant |
| Pure logic | 69 | auth, config (including which GCP project is written to, and that none is guessed), schemas, simulator, untrusted, agents._common |
| Decision paths | 57 | Every route a shipment can take through the state machine, and the heading the HS classifier is told was declared |
| Tenant isolation | 43 | Cross-tenant reads, writes, and aggregation |
| Hardening | 42 | Kill switch, Red Team screen, policy dry run, auto-debate, learning loop, per-hop I/O |
| Document upload | 33 | Accepted types, the PDF branch, injection screening |
| Console session | 41 | HMAC signing, forged tokens, reviewer attribution, the signed sign-in method (`amr`), and what a forwarded session may and may not change |
| Network defence | 34 | Rate limits, request size, header hygiene, CSP content, content-type allow-list |
| Verifier | 34 | Risk reconciliation, prompt injection, whitelist, checks, and routing "to, from, or through" a restricted country |
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
| RBAC | 25 | Who gets which role — key alone, key plus session, unlisted address, a session that fails to verify — whether the routes honour it, and that only a password sign-in may clear the board, revoke the boundary or edit the prefilter rules |
| Debate routing | 13 | A genuine, confident DISAGREE sends the case to investigation; a forced verdict does not; risk only moves up |
| Concurrent decisions | 13 | Two reviewers deciding the same case |
| False-positive tuning | 12 | Which signals are findings and which are context: observations carry no floor and are not counted |
| Compliance cache | 12 | Counterparty lookups reused within a case and across cases |
| Console contract | 12 | The field names the console reads from the backend -- the cause of three silent bugs |
| Unpriced model | 9 | An unpriced model is logged, not silently billed at the cheapest rate |
| Screen layers | 7 | Which of the two screening layers may refuse a shipment |
| Audit integrity | 6 | The governance author is the authenticated identity, not a body field |
| Cache concurrency | 5 | That concurrent identical searches all miss, and what that costs |
| Evaluation endpoint | 8 | The committed reports served as written, each naming its split and verifier, never the per-case rows that carry the labels; the workload arithmetic at real fraud rates; and the public-case pairs with their sources |
| Poll drain | 3 | A board poll that advances the pipeline stays a bounded read, with one drain per tenant |
| **Total** | **922** | |

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
| `NEMOTRON_MODEL` | Model for fraud detection and compliance screening | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` |
| `VISION_MODEL` | Model for document intake | `openbmb/MiniCPM-V-4_5` |
| `INVESTIGATION_MODEL` | Model for investigation, pinned separately | `nvidia/nemotron-3-super-120b-a12b` |
| `DEBATE_MODEL` | Model for the debate agent — **the one place Nemotron Ultra is used by default**. See the note below the table. | `nvidia/Nemotron-3-Ultra-550b-a55b` |
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
Nemotron tiers at runtime; investigation ignores it and reads
`INVESTIGATION_MODEL` at import.

#### Why Ultra is on the debate agent and nowhere else

`DEBATE_MODEL` defaults to Nemotron Ultra. Every other agent stays on Nano or Super, and
the reason is architectural rather than financial: `verifier.py` computes a deterministic
risk floor, and an agent may **raise** risk but never lower it below that floor. A
stronger model on fraud detection or compliance therefore cannot move the outcome in the
direction that matters — the floor has already decided. Measured, putting those two on
Ultra would cost 13× per call, against a rate that is only 3.3×, for no change in any
decision.

The debate is the exception. It runs only when the floor and the model disagree by 15
points or more (measured: 2 calls across 20 cases) and what it emits is not a score
awaiting override — it is a reasoned CONFIRM or DISAGREE on whether that disagreement can
be settled without a person. That judgement *is* the outcome, so reasoning capacity is
load-bearing.

**Measured cost, and it is higher than the rate suggests.** Three Ultra debates and two
Super debates have now run on the live service:

| Model | Input | Output | Cost |
|---|---|---|---|
| Ultra | 13,151 | 2,011 | `$0.019184` |
| Ultra | 16,502 | 2,333 | `$0.023501` |
| Ultra | 13,937 | 879 | `$0.016574` |
| Super | 2,522 | 276 | `$0.001005` |
| Super | 5,546 | 403 | `$0.002027` |

`$0.0198` per Ultra debate against Super's `$0.0015` — **13×, not the 3.3× rate
multiple.** The rate accounts for 3.3× of that; the rest is token volume. Ultra consumed
13,151–16,502 input tokens where Super used 2,522–5,546, because it emits more tool-call
rounds and each round resends the growing transcript, so volume compounds on top of price.
An earlier version of this section said "roughly `$0.007` per 20 cases", arrived at by
multiplying Super's token usage by Ultra's rate — which assumed the two models would spend
the same tokens, and they do not.

This is a quality bet, not a measured improvement: nothing yet demonstrates Ultra
resolves more disputes than Super. `scripts/compare_debate_models.py` replays disputed
cases through both and reports resolution rate and cost, and setting `DEBATE_MODEL` back
to `nvidia/nemotron-3-super-120b-a12b` reverses the decision without a deploy.

#### Tavily is the binding cost constraint, not the models

Measured on a 20-case run: **90–106 Tavily searches** (4.5–5.3 per case) against
`$0.067994` of Nemotron. At the free tier's 1,000 credits a month that is **188–222
cases**, while the model bill for those cases is under a dollar — so the external
search, not inference, is what limits throughput. The board reseeded on 10/10 after the
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

**A degrade-gracefully rule matters as much for a new dependency as an old
one.** Tavily is new to this system, and it would have been easy to let a
missing key or a timeout raise into the request handler and fail the case.
`tavily_client.search()` returns an empty list on any failure instead, so the
compliance agent's worst case with Tavily broken is exactly its old behaviour
without Tavily.

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
a scheduled refresh instead of a hand-run one, and replacing the scripted simulator
with a production Pub/Sub subscription from the shipment system.

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
│   ├── verifier.py               Deterministic risk floor (no model consulted)
│   ├── untrusted.py              Schema whitelist for document-sourced fields
│   ├── shipper_registry.py       Counterparty book: verifies a claimed shipper identity
│   ├── sanctions.py              Sanctions index, loaded from Cloud Storage
│   ├── hs_reference.py           Published HS heading contents; took recall 40.0% → 92.9%
│   ├── model_armor.py            Windowed prompt-injection screening
│   ├── nebius_client.py          Nebius Token Factory client (OpenAI-compatible)
│   ├── tavily_client.py          Tavily search API wrapper, with the TTL cache
│   ├── store.py                  Case/event/audit state (Firestore, memory fallback)
│   ├── auth.py                   Roles, API keys, operator records
│   ├── budget.py                 Per-tenant soft spend ceiling
│   ├── tenant.py                 Tenant resolution and scoping
│   ├── lineage.py                Per-step cost attribution
│   ├── evaluation.py             Serves the committed benchmark and HS reports, never per-case rows
│   ├── observability.py          Structured logging, metrics, request context
│   ├── schemas.py                Request/response validation, and AGENT_OUTPUT_SCHEMAS for six agents' replies
│   ├── openapi.py                Generates the OpenAPI document
│   ├── b2b.py                    The published contract surface
│   ├── document_render.py        Renders event-sourced shipments as a bill of lading
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
│       └── debate_agent.py       Senior Auditor debate           — Nemotron 3 Ultra
├── tests/                        39 files, 922 tests
├── scripts/                      Not deployed; seeding, verification, docs, narration
├── sample_docs/                  Seven committed sample PDFs, one per mechanism
├── data/                         Sanctions, HS reference, synthetic corpus, benchmark and eval reports
├── frontend/                     Next.js 16 console, built into the same image as the API
│   ├── src/app/                  App Router pages: board, radar, review, audit, governance,
│   │                             devops, agents, evaluation, admin, legal, login
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
│   ├── ARCHITECTURE.md           The source of truth for how it fits together
│   ├── architecture.html         Diagram source
│   ├── DEMO_SCRIPT.md            Nine scenes, timed to the narration track
│   ├── PROJECT_STORY.md          What was built and what it cost to learn
│   ├── swagger.json              Generated by scripts/build_docs.py — do not hand-edit
│   ├── diagrams/                 Mermaid flows
│   └── screenshots/              Console captures
├── .github/workflows/ci.yml      ruff, mypy ratchet, tests (75% floor), frontend, container smoke
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
