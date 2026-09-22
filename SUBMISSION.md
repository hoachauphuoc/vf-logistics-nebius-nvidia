# Devpost Submission — VF Logistics Autonomous Fraud Detection

Copy-paste material for the Devpost form. The demo shooting script is kept
outside the repository — it is recording notes, not part of the submission.

---

## Project name

VF Logistics — Fraud Detection an Operator Can Delegate To

## Elevator pitch (200 char limit on Devpost)

Five NVIDIA Nemotron agents on Nebius Token Factory screen shipments for fraud. Senior Auditor (Super) debates Junior Analyst (Nano) using function calling. A Delegation Boundary, not the agents, decides.

## Track

Best Apps and Agents

## Bonus award targeted

Best Use of Tavily ($3,000) — the compliance agent makes a real, runtime
Tavily search call before every screening decision.

## Hosted project URL

**Console (start here):** https://vf-console-f7rcctz26a-as.a.run.app
**API:** https://vf-logistics-f7rcctz26a-as.a.run.app

The console is readable without signing in. Recording a review decision needs an
account; credentials are in the private testing-instructions field below.

---

## Text description

### The problem

Vietnamese logistics operators lose money to shipment fraud that threshold rules
cannot see. A shipping cost 60% under the historical route average looks like a
promotion, not under-invoicing. A shipper with two lifetime transactions and a
generic company name looks like a new customer, not a shell entity.

Individually each signal is weak and generates false positives. Together they
are damning. Catching that combination is what a SQL rules engine structurally
cannot do, and what a human analyst has no time to do across thousands of
shipments a day.

But detecting fraud is only half the problem. The harder question is: **who
decides what the agent may do about it?** An agent that reasons well is not the
same as an agent you can hand authority to.

### What we built

A multi-agent system on Cloud Run where **seven** specialised agents share one
shipment record — six running NVIDIA Nemotron models on **Nebius Token
Factory**, one running a vision model for document reading — and a
**governance layer** that determines which of those agents' recommendations
actually execute.

**Document Intake Agent** — reads a real shipping document (bill of lading,
commercial invoice, packing list). Rasterises the PDF's first page and sends
it to **MiniCPM-V-4.5**, a vision model on Token Factory (NVIDIA does not
publish a vision model there yet). Transcribes into the structured shipment
record the rest of the pipeline understands. Runs at `temperature=0.0` because
this is transcription, not generation.

**Fraud Detection Agent** — screens seven fraud families (price manipulation,
route fraud, weight/dimension fraud, document fraud, identity fraud, duplicate
billing, time fraud) on **NVIDIA Nemotron 3 Nano**. Returns `risk_score`
0–100, `risk_level`, a `flags[]` array with per-finding severity, and an
explicit `confidence`.

**Compliance Screening Agent** — sanctions exposure against OFAC / UN / EU
patterns, trade and regulatory compliance, AML indicators, on **NVIDIA
Nemotron 3 Nano** — grounded by a **real Tavily search** for the shipper and
receiver names before scoring.

**AI Investigation Agent** — multi-step case investigation across related
shipments, pattern analysis, network mapping and consolidated reporting, on
**NVIDIA Nemotron 3 Super**. Only reached on escalated cases, so it is the one
agent that can afford a larger model.

**Multi-Agent Debate (Senior Auditor)** — **NVIDIA Nemotron 3 Super** reviews the
fraud agent's assessment through native function calling, with three tools it may
choose to invoke: request re-evaluation, search Tavily, render verdict. Opt-in per
case via *Deep Review*.

**HS Classification Agent** — **NVIDIA Nemotron 3 Nano**. The deterministic checks
in `verifier.py` can compare a declared HS code against a dual-use prefix list, but
they cannot tell whether the code matches the cargo actually described. This agent
can, which is what catches a correctly-formatted code on the wrong goods.

**Zero-Day Radar** — **NVIDIA Nemotron 3 Nano**, adverse-media screening for
entities the official sanctions lists have not caught up with yet. A list is always
behind the news; this closes that window.

### Model selection, chosen per task

The model is not a single global setting. Fraud detection and compliance
screening run on **Nemotron 3 Nano** because every shipment gets scored by
both — this is the highest-volume call in the pipeline, and it needs to be
fast and cheap. Investigation runs on **Nemotron 3 Super** because by the time
a case reaches it, the fraud and compliance findings already exist —
investigation synthesises rather than makes the primary judgement, but it
still benefits from a stronger model since the reasoning is multi-hop.
`INVESTIGATION_MODEL` is one environment variable away from **Nemotron 3
Ultra** if more credit becomes available. Document intake needs a vision
model NVIDIA does not currently offer on Token Factory, so it runs on
**MiniCPM-V-4.5**, which the catalog specifically calls out for OCR/PDF work.

All seven agents are reached through the same OpenAI-compatible client
(`nebius_client.py`), so the split adds no integration surface. Every agent
response envelope records the model that produced it, and the console's
per-case trace shows it on each hop.

### A real Tavily call -- 5 integration points

Tavily is woven throughout the pipeline, not just compliance:

1. **Compliance screening** -- `compliance_agent.py` searches shipper and receiver
   names for sanctions, fraud, and shell company indicators before every screening
   call. Results are injected as labelled, untrusted evidence into the LLM context.

2. **Investigation enrichment** -- `investigation_agent.py` searches for the
   specific fraud pattern identified (e.g. "under-invoicing Vietnam logistics") and
   cross-references shipper + receiver as a pair to find business relationship
   evidence before Nemotron Super generates its deep analysis.

3. **Route validation** -- `orchestrator.py` runs a parallel Tavily search for
   shipping route disruptions ("port congestion", "sanctions", "shipping lane
   disruption") alongside the fraud and compliance agents. Route intelligence is
   attached to the case for downstream agents.

4. **Governance watchlist scanner** -- the *Scan for sanctions updates* button on
   the Governance page calls `/api/v1/governance/tavily-scan`, which searches for
   recent sanctions additions, OFAC SDN changes, and trade enforcement actions.
   The point is that the code-resident lists on that page can be reviewed against
   what actually changed, rather than only against what a model remembers.

5. **Multi-agent debate** -- `debate_agent.py` exposes `search_tavily` as a tool
   that Nemotron Super can invoke during function-calling debate rounds. Super
   decides at runtime whether to search -- it's a genuine tool call, not scripted.

A missing API key or a Tavily outage degrades each integration to pre-Tavily
behaviour rather than blocking the pipeline.

### Verify the defence layer yourself

The strongest guardrail in the system used to be invisible: 14 injection
patterns plus 15 classes of invisible Unicode, applied to every document before
a model sees it, with nothing in the UI to exercise them. The **Red Team panel**
in DevOps now exposes `/api/v1/security/screen`, which runs the exact functions
the document pipeline runs -- `untrusted.screen_text()` and Model Armor -- over
any text you paste. Preset attacks cover override attempts, role injection,
score manipulation, clearance assertion, output hijacking, tag injection and
hidden characters; a clean control sample is included to show the screen does
not simply block everything. Nothing is simulated or replayed.

Worth knowing what the two layers each do, because they are not
interchangeable. The deterministic pass is free and needs no network, and it closes a
real gap -- an injection in document prose that the vision extractor does not carry
into any structured field never reaches the field-level screen, so nothing catches it
when Model Armor is unreachable. But it only ever **flags for a human**; it cannot
block. Its patterns were written for extracted field values, and a legitimate bill of
lading containing `Booking System:` or `pre-approved` trips two of them. A committed
test asserts that exact document is not blocked. Refusing a real shipment on a form
label is a worse failure than screening it a moment later, so the block decision stays
with the purpose-built detector.

### Governance: the part most agent systems skip

Most agent demonstrations treat "the model decided" as the end of the story.
We treat it as the beginning of a different question: **who authorised that
decision?**

The answer in this system is a **Delegation Boundary**: a versioned,
machine-readable policy published by a named human. The boundary says exactly
which actions the agent may take (`release_shipment`, `hold_shipment`,
`assign_analyst`, `draft_sar`, `notify_webhook`, `publish_decision`) and within
what limits — maximum declared value, maximum effective risk, forbidden HS
prefixes, forbidden destinations. Every executed action records the boundary
version that permitted it.

The boundary enforces a simple rule: **an agent may raise risk, never lower it
below a deterministic floor.** `verifier.py` computes that floor from
arithmetic and code-resident reference lists. A successful prompt injection
can manipulate the model's score; it cannot manipulate the floor, because the
floor does not come from the model.

With no active boundary the entire system is **SUSPENDED**. Analysis keeps
running — the agents will still tell you what they found — but protected
actions are refused.

### Input security: documents are untrusted

A shipping document is attacker-controlled. It arrives as a PDF, goes into a
model, and the model's output moves physical cargo. **Google Cloud Model
Armor** screens the document before any model sees it, in overlapping windows
so an injection diluted by surrounding legitimate text is still caught. After
transcription, `untrusted.py` enforces a strict field whitelist —
`avg_route_cost`, `shipper_tx_count` and `created_at` are deliberately
excluded, so a document cannot assert its own clean history.

`shipper_registry.py` resolves the claimed shipper against our own
counterparty book on tax ID **and** company name together, so a forged
document carrying a real customer's tax number under a different name is
reported as `identity_mismatch` rather than inheriting that customer's clean
record.

Seven sample bills of lading are committed, each isolating one mechanism:

```bash
python scripts/test_documents.py 3
```

### Features and functionality

- **Seven specialised agents** — Nemotron 3 Nano for fraud, compliance, HS
  classification and zero-day radar; Nemotron 3 Super for investigation and the
  Senior Auditor debate; MiniCPM-V-4.5 for document intake — all through one
  OpenAI-compatible client
- **Multi-Agent Debate** — Senior Auditor (Nemotron Super) reviews Junior Analyst
  (Nemotron Nano) using function calling with three tools: request re-evaluation,
  Tavily search, and render verdict. Opt-in "Deep Review" for cases needing extra scrutiny.
- **A real, runtime Tavily search** in the compliance path (and in debate)
- **Autonomous multi-step workflow** — conditional routing with no human
  step-through
- **Delegation Boundary** — versioned policy published by a named human; the
  only source of authority for protected actions
- **Fail-closed execution gate** — no boundary, no execution
- **Deterministic risk floor** — arithmetic and code-resident lists constrain
  what the agent can claim
- **Two-layer input screening** — a free deterministic pass over 14 injection
  patterns and 15 classes of invisible Unicode runs first, then Model Armor's
  windowed screening catches injections diluted by surrounding document text. Only
  Model Armor blocks; the deterministic layer flags for a human, because its patterns
  were written for extracted fields and fire on ordinary phrases like `pre-approved`
- **Every case gets reviewable paperwork** — an uploaded original is archived
  to Cloud Storage; a data-event case gets a bill of lading rendered from its
  record and labelled `SYSTEM-GENERATED`
- **Scale-to-zero** — `--min-instances=0`, `WORKER_MODE=ondemand`, lease-based
  claiming, exponential backoff
- **Human review queue**, coloured by state — red escalated, yellow held or
  pending
- **Live operations console** — pipeline board, event feed, action log, and
  a per-case trace showing every agent hop with its real latency and model
- Batch analysis, standalone entity screening, consolidated report generation
- **Per-tenant soft spend ceiling** — checked at the single chokepoint every model
  call passes through, so no agent can be added that bypasses it

### Technologies used

| Layer | Choice |
|---|---|
| Model | NVIDIA Nemotron 3 Nano (fraud, compliance, HS classification, zero-day radar), NVIDIA Nemotron 3 Super (investigation, Senior Auditor debate), MiniCPM-V-4.5 (document intake, vision) — all via Nebius Token Factory |
| Agent framework | `openai.AsyncOpenAI` against Token Factory's OpenAI-compatible endpoint |
| External signal | Tavily Search API |
| Input security | Google Cloud Model Armor |
| Compute | Cloud Run (source deploy, `--min-instances=0`) |
| State | Firestore Native mode — `cases`, `events`, `audit_log`, `delegation_boundaries` |
| Messaging | Pub/Sub — `shipment-events` inbound, `case-decisions` outbound |
| Documents | Cloud Storage |
| Web | Flask + gunicorn (1 worker, 8 threads), flask-cors |
| Console | Next.js 16 (App Router, React 19, Tailwind, TanStack Query) on a second Cloud Run service |
| Container | python:3.11-slim |

Hackathon requirements: a functional runtime call to Nebius Token Factory ·
use of an NVIDIA open model · multi-step autonomous workflow · meaningful
action taken on the user's behalf · (bonus) a functional runtime Tavily call.

### Other data sources used

None besides the live Tavily search. Shipment records — including the
historical route-cost baseline and the shipper transaction count the agents
reason against — are supplied per request; the verifier falls back to
code-resident lane tables when no `avg_route_cost` is provided.

### Findings and learnings

**Vision models on OpenAI-compatible endpoints want images, not PDFs.**
Porting from Gemini's native PDF support meant adding a rasterisation step
(`pypdfium2`, first page to PNG) before the vision model call — a detail that
would have silently produced garbage transcriptions if missed.

**Structured output travels across providers.** Gemini's
`response_mime_type="application/json"` and the OpenAI-compatible
`response_format={"type":"json_object"}` do the same job, so none of the four
agents' prompts or output schemas needed to change — only the transport
underneath them did. That is what made a same-week model-layer swap possible
without rewriting the governance, verifier, or orchestrator layers at all.

**A new external dependency needs the same fail-open discipline as an old
one.** Tavily is new to this system. `tavily_client.search()` returns an
empty list on any failure (missing key, timeout, non-2xx) rather than
raising, so a Tavily outage degrades the compliance agent to exactly its
pre-Tavily behaviour instead of failing the case.

**Model choice is a per-agent decision, not a project-wide one.** Fraud and
compliance are the highest-volume, primary-judgement calls, so they get the
cheapest model that is still reliable (Nano); investigation is low-volume and
benefits from more reasoning, so it gets a larger tier (Super), with Ultra one
environment variable away. This mirrors the hackathon's own guidance almost
exactly, and it is the same lesson the original Gemini build reached from the
other direction — the two systems disagree on *which* task deserves the
stronger model, which is itself evidence that the choice is genuinely
task-dependent rather than a fixed rule.

**The execution gate is more important than the model.** A judge will
remember "you can publish a policy that constrains what the agent does"
longer than which model scored a shipment 78. Governance is the
differentiator; the model is the commodity -- true regardless of which
provider's models are underneath.

**Nemotron Nano vs Super: observable differences in structured output.**
Nano (`Nemotron-3-Nano-30B-A3B`) reliably produces clean JSON for fraud detection
and compliance screening -- the most frequent calls. Super
(`nemotron-3-super-120b-a12b`) is notably better at multi-step reasoning in
investigation and debate, but occasionally wraps JSON in markdown fences that need
stripping. Both models respect `response_format={"type":"json_object"}` but Super
sometimes includes commentary outside the JSON block. Our `parse_model_json()`
handles both.

**Token Factory pricing is developer-friendly but hard to predict.** The
per-token pricing ($0.06 / $0.24 per million for Nano input/output, $0.30 / $0.90
for Super) is clear, but predicting total cost for a pipeline of variable-length
prompts is non-trivial. A cost dashboard showing real-time spend per agent is
essential for any production deployment -- we built one, and a per-tenant spend
ceiling behind it.

**What we'd build next with Nebius.** (1) Fine-tune Nano on our
fraud-detection domain to improve structured output quality. (2) Deploy
Nemotron Ultra for the debate agent when complex multi-hop reasoning is
needed. (3) Use Nebius Serverless inference for auto-scaling during peak
shipment volumes. (4) Explore Nebius GPU clusters for batch processing
historical fraud cases with investigation agent.

---

## Video script

The shooting script is kept outside this repository — it is operator notes
for one recording session, not submission material that should drift from the
UI it describes.

**The previous script is stale and must not be followed**: it describes the retired
vanilla-HTML dashboard, a `DEMO_MODE` sidebar that no longer exists, and a `/demo`
endpoint that now requires an operator key. The recording has to be redone against the
Next.js console.

Two things worth knowing before recording: the board has to be seeded first
(`POST /api/v1/simulate`) or the cost meter and pipeline board are both empty
on camera, and a document upload takes roughly 30–60 seconds to reach a
terminal state, so narration over that scene needs to be long enough to cover
it.

The Tavily search call is real and runs on every compliance screening, and its
results are now surfaced directly in the case-trace UI — open any escalated
or auto-cleared case, expand the compliance hop, and the "LIVE TAVILY SEARCH
USED" badge with the actual result titles/links (or the "returned nothing,
degraded gracefully" state) is visible on camera, no narration workaround
needed. Model Armor is live and enforcing (`sample_docs/injected_bol.pdf` is
blocked with
`MATCH_FOUND` at `HIGH` confidence before the vision model ever sees it,
`case_id` prefixed `CASE-BLOCKED-`), so that scene can be shown directly
rather than described. The demo should show, in order: a document upload
reaching `AUTO_CLEARED` with the archive receipt visible, the injected sample
document blocked by Model Armor, the Governance page with the active
Delegation Boundary, one escalated case with a SAR draft, and — from the
Audit Trail, searching `denied` — the real `hold_shipment` denials recorded
when the boundary was unpublished, as evidence the fail-closed gate is not
just a slide claim.

---

## Devpost form — field-by-field answers

### Project details

**Built with** (tags): nebius, nvidia, nemotron, token-factory, tavily,
google-cloud, cloud-run, firestore, pub-sub, cloud-storage, model-armor,
openai-sdk, python, flask, gunicorn, asyncio, nextjs, react, typescript,
tailwindcss, docker

**"Try it out" links:**
- https://vf-console-f7rcctz26a-as.a.run.app (console — start here)
- https://vf-logistics-f7rcctz26a-as.a.run.app (API)
- https://github.com/hoachauphuoc/vf-logistics-nebius-nvidia

### Additional info

| Field | Answer |
|---|---|
| **Submitter Type** | Individual |
| **Country of residence** | Vietnam |
| **Category** | Best Apps and Agents |
| **Public code repo URL** | https://github.com/hoachauphuoc/vf-logistics-nebius-nvidia |
| **Reproducible Testing instructions in README?** | **Yes** — README → *Reproducible testing* |
| **Testing instructions (private)** | **Console:** https://vf-console-f7rcctz26a-as.a.run.app — the board, any case, the audit trail and the cost figures are all readable **without signing in**, so nothing is needed to assess the product. To record a review decision, sign in at `/login` as `judge@vf-logistics.demo` with the password supplied alongside this submission; the audit trail will then name that account, which is the point of requiring it. **API only:** `GET /health` to warm it, then `POST /api/v1/simulate` and poll `GET /api/v1/orchestrator/state`. Full walkthrough in the README. |

**Which model provider(s) did you use?** → **Nebius Token Factory**, hosting
**NVIDIA Nemotron 3 Nano** (`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`), **NVIDIA
Nemotron 3 Super** (`nvidia/nemotron-3-super-120b-a12b`), and **MiniCPM-V-4.5**

**Which bonus integrations did you use?** -> **Tavily** -- 5 real, runtime
search integrations: compliance screening, investigation enrichment, route
validation, governance watchlist scanner, and multi-agent debate tool calling.
Verifiable via `GET /agents`, the per-case trace UI, or the raw case document
(`external_search_used` / `external_search_results`).

> Both the Nebius and Tavily calls are verifiable on the live service:
> `GET /agents` reports the model per agent, and every compliance response
> carries `external_search_used` and the search result titles/links, which
> the dashboard renders directly in the case trace.

---

## Submission checklist

| Item | Status |
|---|---|
| Demo video, up to 3 minutes | **OUTSTANDING** — mandatory. Record, upload to YouTube as public, paste the URL here and on Devpost. The old shooting script describes the retired dashboard and cannot be followed. |
| Public code repository | done -- https://github.com/hoachauphuoc/vf-logistics-nebius-nvidia |
| Devpost text description | this file |
| README with spin-up instructions | `README.md` |
| Reproducible testing instructions | `README.md` -> *Reproducible testing* |
| Hosted project URL | done -- console https://vf-console-f7rcctz26a-as.a.run.app, API https://vf-logistics-f7rcctz26a-as.a.run.app |
| Runtime call to Nebius Token Factory | done -- all seven agents |
| NVIDIA open model used | done -- Nemotron 3 Nano + Super |
| Functional Tavily runtime call | done -- 5 integration points |
| Automated test suite | 637 tests passing (pytest) |
| CI pipeline | GitHub Actions (lint + typecheck + test + coverage) |
| Auto-debate on score disputes | done -- fires without human intervention |
| Human feedback learning loop | done -- derived from reviewed cases, survives restart |
| Adversarial demo scenarios | 3 one-click demos in DevOps |
| Red Team panel | paste any attack, see the real screen verdict |
| Governance kill switch | `/api/v1/governance/revoke` -- agent goes SUSPENDED |
| Policy dry run | preview which cases a boundary would flip before publishing |
| Per-hop model I/O | exact prompt, raw response, tokens and cost per agent call |
| Cost dashboard | real-time token spend + rules savings |
| Per-tenant spend ceiling | soft ceiling at the single model-call chokepoint |
| Console login + audit attribution | a decision records the signed-in account, not a typed name |

The repository is public, so no judging-instruction share is required. The one
outstanding item is the video.

---

## Feedback on Nebius Token Factory, AI Cloud, and NVIDIA tools

### What worked well

1. **OpenAI-compatible API** — Migrating from Gemini took hours, not days. The
   same `AsyncOpenAI` client talks to Token Factory; only the base URL, model
   IDs, and pricing table changed. Structured JSON output (`response_format`)
   works identically.

2. **Model variety in one endpoint** — Having Nemotron Nano (fast/cheap),
   Nemotron Super (high-quality reasoning), and a vision model (MiniCPM-V)
   behind the same endpoint simplified architecture. Each agent picks the
   right model for its job without managing multiple SDKs or auth flows.

3. **Generous hackathon credits** — The Nebius Builder Program credits allowed
   extensive iteration on prompt engineering and multi-agent orchestration
   without worrying about cost during development.

4. **Latency for Nemotron Nano** — p95 under 1.5 seconds for the triage agent's
   short responses is fast enough for a real-time review queue.

### What could be improved

Each item below is something we measured while building, with the consequence it had
on this codebase. The first two are the ones we would fix first.

1. **There is no safety or guard model in the catalogue \u2014 24 models, zero
   classifiers.** Queried against the live `/v1/models` endpoint at submission time:
   24 models served, of which four are NVIDIA and all four are chat models
   (`Nemotron-3_5-Lightning`, `NVIDIA-Nemotron-3-Nano-30B-A3B`,
   `nemotron-3-super-120b-a12b`, `Nemotron-3-Ultra-550b-a55b`). No `nemoguard`, no
   content-safety or moderation classifier, nothing purpose-built to screen input.

   The consequence is concrete and visible in this submission: a shipping document is
   attacker-controlled and its transcription moves physical cargo, so it has to be
   screened before a model reads it \u2014 and **the only component of this pipeline that
   is not on Token Factory is that screen**. It runs on Google Cloud Model Armor
   because Token Factory offers no first-party alternative. We evaluated NVIDIA NeMo
   Guardrails as a replacement and did not adopt it, for a reason that is itself
   feedback: Guardrails is a *toolkit*, and its `self check input` rail asks a chat
   model whether text is trying to manipulate a chat model. That is the vulnerable
   component policing itself, and it is injectable. A toolkit cannot substitute for a
   classifier that was trained for the job.

   What would close it: a hosted `nemoguard`-class content-safety or
   jailbreak-detection model behind the same OpenAI-compatible endpoint. A team
   building anything that ingests untrusted text \u2014 which is most agentic pipelines \u2014
   currently has to leave the platform at exactly the security-critical step.

2. **A servable model is missing from the published pricing, and the failure is
   silent.** `nvidia/Nemotron-3_5-Lightning` is returned by `/v1/models` and can be
   called, but we could find no rate for it, and the models endpoint does not carry
   pricing. Because a client has to hard-code a rate table, an unpriced model does not
   fail \u2014 it falls through to whatever default the client picked. In our case that was
   the cheapest entry, which means spend is under-reported and the per-tenant spend
   ceiling that reads the same figure quietly stops holding. We now log it at ERROR at
   startup and per call rather than absorbing it, but the fix belongs upstream.

   What would close it: pricing on the model object in `/v1/models`, or a versioned
   rate-card endpoint. Either lets a client fail loudly on an unknown model instead of
   guessing, and makes a new model adoptable the day it appears.

3. **`usage` can be absent from a completion response, and there is no way to tell
   that apart from a free call.** Our `_usage()` helper returns `(0, 0)` when the block
   is missing, because there is nothing else it can return \u2014 so an unmetered call and
   a zero-token call are indistinguishable downstream, and billing silently
   under-counts. A guarantee that `usage` is always present on a 2xx, or an explicit
   error when it cannot be computed, closes a metering hole that a customer-facing
   invoice sits on top of.

4. **No NVIDIA vision model on Token Factory.** Document intake (transcribing bills
   of lading, invoices, packing lists) needs a vision-language model, and at
   submission time Token Factory's NVIDIA catalog has none, so this project runs that
   one agent on `MiniCPM-V-4.5`. Document understanding is one of the most common
   real-world entry points for an agentic pipeline \u2014 someone always starts from a PDF,
   a scan, or a photo of paperwork \u2014 so a team building a document-first workflow has
   no first-party NVIDIA option for the very first step. A Nemotron VL variant, or an
   `nvidia/nemotron-parse`-style OCR/layout model on the same endpoint, would close it.

   Separately, the vision endpoint requires images rather than raw PDF bytes (Gemini
   reads PDFs natively), which meant an extra `pypdfium2` rasterisation step in
   `document_agent.py` that cost real debugging time before we realised it was expected
   rather than a bug. A one-line note in the vision-model docs would have saved that.

5. **Prefix caching exists on the backend but cannot be billed for, and there is no way
   to tell whether it hit.** The inference docs list "KV Cache" and "Context Caching"
   under optimisations, and the observability page exposes a **KV-cache hit rate**
   distinguishing local from external hits — so prefix caching is real and running. But
   the `Pricing` schema returned by `GET /v1/models?verbose=true` has six dimensions
   (`prompt`, `completion`, `image`, `price_per_video_second`, `request`,
   `price_per_minute`) and **none for cached input**, so there is no field in which a
   discounted cached rate could be expressed. `prompt_tokens_details.cached_tokens` is in
   the OpenAPI schema but carries only a title, no description, and comes back `null` on
   every chat completion we observed.

   The consequence here is concrete and we chose to eat it. Our HS-classification agent
   sends a 1,376-token static nomenclature extract on every call — essentially 100% of
   that agent's input, since the variable part is one cargo description. We measured what
   the block buys before considering trimming it: base Nemotron Nano reaches **40.0%**
   recall on deliberately evasive misclassification cases, naive few-shot prompting makes
   it **worse at 26.7%**, and the same model with this reference block reaches **91.7%**.
   The block is the capability, not overhead, so it stays — and we pay full `prompt` rate
   for an identical prefix 16 times per 20-case run. Either a documented cached-input rate
   or a populated `cached_tokens` would let a builder reason about this instead of
   guessing.

   Related and cheap to fix: **`max_tokens` defaults to 8192 when omitted**, which *is*
   documented but easy to miss, and it cost us real money before we found it. Two calls
   on a measured run returned exactly 8,192 output tokens and both failed to parse — one
   was a degenerate repetition loop emitting `{}, {}, {}, ...` for 38.6 seconds at
   `$0.007873`, which was 29% of that agent's entire spend for the run. `finish_reason:
   "length"` is documented and is what let us tell "the model emitted invalid JSON" from
   "the reply was cut off". Surfacing the 8192 default more prominently — or defaulting
   to the model's context limit rather than a fixed number — would have saved the hunt.

6. **Rate limit headers** \u2014 Token Factory returns 429 on rate limit but does not
   include `Retry-After` or `X-RateLimit-*`. For a production service that has to back
   off gracefully, knowing *when* to retry is the difference between a backoff and a
   guess.

7. **Streaming for long completions** \u2014 the investigation agent's detailed reports
   take 8\u201312 seconds. Streaming would improve perceived latency for a human reviewer
   waiting on a decision.

8. **Batch API** \u2014 for offline scoring of historical shipments (backtesting a new
   risk model against last year's freight), a batch endpoint at a lower per-token cost
   would make the difference between running it and not.

### NVIDIA open models feedback

1. **Nemotron 3 Nano** (`Nemotron-3-Nano-30B-A3B`) — excellent for deterministic
   classification. Fraud scoring and compliance bucketing are consistent and fast, and
   it holds `response_format={"type":"json_object"}` reliably across thousands of calls.

2. **Nemotron 3 Super** (`nemotron-3-super-120b-a12b`) — handles the multi-hop work
   well: cross-referencing compliance findings, temporal anomaly detection, and native
   function calling in the Senior Auditor debate, where it decides at runtime whether
   to search rather than following a script. One observed rough edge: it sometimes
   wraps JSON in markdown fences or adds commentary outside the block even under
   `json_object`, which Nano does not. Our `parse_model_json()` tolerates both, but a
   caller who trusted `json_object` strictly would break on Super and not on Nano.

3. **Wish list, in the order we would use them.** (a) A safety/guard model — see the
   first item above; it is the only reason this pipeline reaches outside Nebius.
   (b) A Nemotron VL variant, so document intake can be Nemotron too. (c) A Nemotron
   fine-tuned for entity extraction, to pull shipper and receiver names, addresses and
   tax IDs out of noisy transcriptions more accurately than a general chat model does.

---

## Cost note

Both services run with `--min-instances=0`, so they scale to zero when idle. After
judging closes they can be deleted:

```bash
gcloud run services delete vf-logistics --region asia-southeast1
gcloud run services delete vf-console   --region asia-southeast1
```
