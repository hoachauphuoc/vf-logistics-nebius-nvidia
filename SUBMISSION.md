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

https://vf-logistics-f7rcctz26a-as.a.run.app

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

A multi-agent system on Cloud Run where **four** specialised agents share one
shipment record — three running NVIDIA Nemotron models on **Nebius Token
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

All four models are reached through the same OpenAI-compatible client
(`nebius_client.py`), so the split adds no integration surface. Every agent
response envelope records the model that produced it, and the dashboard's
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

- **Five specialised agents across two providers' worth of model shapes** —
  Nemotron 3 Nano for fraud and compliance, Nemotron 3 Super for
  investigation and multi-agent debate, MiniCPM-V-4.5 for document intake — all through one
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
- **Model Armor integration** — windowed screening catches injections diluted
  by surrounding document text
- **Every case gets reviewable paperwork** — an uploaded original is archived
  to Cloud Storage; a data-event case gets a bill of lading rendered from its
  record and labelled `SYSTEM-GENERATED`
- **Scale-to-zero** — `--min-instances=0`, `WORKER_MODE=ondemand`, lease-based
  claiming, exponential backoff
- **Human review queue**, coloured by state — red escalated, yellow held or
  pending
- **Live operations dashboard** — pipeline board, event feed, action log, and
  a per-case trace showing every agent hop with its real latency and model
- Batch analysis, standalone entity screening, consolidated report generation
- `/demo` endpoint that runs a built-in sample so a judge needs zero setup

### Technologies used

| Layer | Choice |
|---|---|
| Model | NVIDIA Nemotron 3 Nano (fraud, compliance), NVIDIA Nemotron 3 Super (investigation), MiniCPM-V-4.5 (document intake, vision) — all via Nebius Token Factory |
| Agent framework | `openai.AsyncOpenAI` against Token Factory's OpenAI-compatible endpoint |
| External signal | Tavily Search API |
| Input security | Google Cloud Model Armor |
| Compute | Cloud Run (source deploy, `--min-instances=0`) |
| State | Firestore Native mode — `cases`, `events`, `audit_log`, `delegation_boundaries` |
| Messaging | Pub/Sub — `shipment-events` inbound, `case-decisions` outbound |
| Documents | Cloud Storage |
| Web | Flask + gunicorn (1 worker, 8 threads), flask-cors |
| Frontend | Vanilla HTML/CSS/JS, no build step |
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
Nano (8B) reliably produces clean JSON for fraud detection and compliance
screening -- the most frequent calls. Super (49B) is notably better at
multi-step reasoning in investigation and debate, but occasionally wraps
JSON in markdown fences that need stripping. Both models respect
`response_format={"type":"json_object"}` but Super sometimes includes
commentary outside the JSON block. Our `parse_model_json()` handles both.

**Token Factory pricing is developer-friendly but hard to predict.** The
per-token pricing ($0.06/$0.30 per million for Nano input/output) is clear,
but predicting total cost for a pipeline of variable-length prompts is
non-trivial. A cost dashboard (showing real-time spend per agent) is
essential for any production deployment -- we built one.

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

Two things worth knowing before recording: the board has to be seeded first
(`POST /api/v1/simulate`) or the cost meter and pipeline board are both empty
on camera, and a document upload takes roughly 30–60 seconds to reach a
terminal state, so narration over that scene needs to be long enough to cover
it. `DEMO_MODE=true` hides Agent Console, Cost Monitor and Volume test from
the sidebar so the recording stays on the features that carry the argument;
append `?full=1` to see everything regardless.

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
openai-sdk, python, flask, gunicorn, asyncio, javascript, html5, docker

**"Try it out" links:**
- https://vf-logistics-f7rcctz26a-as.a.run.app
- https://github.com/hoachauphuoc/vf-logistics-nebius-nvidia

### Additional info

| Field | Answer |
|---|---|
| **Submitter Type** | Individual |
| **Country of residence** | Vietnam |
| **Category** | Best Apps and Agents |
| **Public code repo URL** | https://github.com/hoachauphuoc/vf-logistics-nebius-nvidia |
| **Reproducible Testing instructions in README?** | **Yes** — README → *Reproducible testing* |
| **Testing instructions (private)** | No login required. `GET /health` to warm it, then `POST /api/v1/simulate` and poll `GET /api/v1/orchestrator/state`. Full walkthrough in the README. |

**Which model provider(s) did you use?** → **Nebius Token Factory**, hosting
**NVIDIA Nemotron 3 Nano**, **NVIDIA Nemotron 3 Super**, and **MiniCPM-V-4.5**

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
| Demo video, up to 3 minutes | pending -- upload to YouTube and paste URL here |
| Public code repository | done -- https://github.com/hoachauphuoc/vf-logistics-nebius-nvidia |
| Devpost text description | this file |
| README with spin-up instructions | `README.md` |
| Reproducible testing instructions | `README.md` -> *Reproducible testing* |
| Hosted project URL | done -- https://vf-logistics-f7rcctz26a-as.a.run.app |
| Runtime call to Nebius Token Factory | done -- all four agents |
| NVIDIA open model used | done -- Nemotron 3 Nano + Super |
| Functional Tavily runtime call | done -- 5 integration points |
| Automated test suite | 226 tests passing (pytest) |
| CI pipeline | GitHub Actions (lint + typecheck + test + coverage) |
| Auto-debate on score disputes | done -- fires without human intervention |
| Human feedback learning loop | done -- derived from reviewed cases, survives restart |
| Adversarial demo scenarios | 3 one-click demos in DevOps |
| Red Team panel | paste any attack, see the real screen verdict |
| Governance kill switch | `/api/v1/governance/revoke` -- agent goes SUSPENDED |
| Policy dry run | preview which cases a boundary would flip before publishing |
| Per-hop model I/O | exact prompt, raw response, tokens and cost per agent call |
| Cost dashboard | real-time token spend + rules savings |

If the repository is private, share it per the hackathon's judging
instructions.

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

1. **No NVIDIA vision model on Token Factory — this is the one gap that
   forced a non-NVIDIA model into an otherwise all-NVIDIA pipeline.** Document
   intake (transcribing bills of lading, invoices, packing lists) needs a
   vision-language model, and at submission time Token Factory's NVIDIA
   catalog has none, so this project runs that one agent on `MiniCPM-V-4.5`
   instead — every other agent is Nemotron. This isn't a small gap: document
   understanding is one of the most common real-world entry points for an
   agentic pipeline (someone always starts from a PDF, a scan, or a photo of
   paperwork), so a team building a genuinely document-first workflow on
   Token Factory today has no first-party NVIDIA option for the very first
   step. Concretely: a Nemotron VL/vision variant, or `nvidia/nemotron-parse`
   style OCR/layout model, exposed through the same OpenAI-compatible endpoint
   would close this without asking developers to manage a second model
   provider just to read a document. Separately, the vision endpoint requires
   images rather than raw PDF bytes (Gemini reads PDFs natively), which meant
   an extra `pypdfium2` rasterisation step (`document_agent.py`) that
   cost real debugging time before we realised it was expected, not a bug — a
   one-line note in the vision-model docs would have saved that.

2. **Streaming for long completions** — The investigation agent's detailed
   reports can take 8–12 seconds. Streaming would improve perceived latency
   for the human reviewer waiting on results.

3. **Rate limit headers** — Token Factory returns 429 on rate limit but doesn't
   include `Retry-After` or `X-RateLimit-*` headers. For production services
   that need to back off gracefully, knowing when to retry matters.

4. **Batch API** — For offline scoring of historical shipments (backtesting new
   risk models), a batch endpoint with lower per-token cost would be valuable.

### NVIDIA open models feedback

1. **Nemotron 3 Nano** — Excellent for deterministic classification tasks. The
   triage agent's risk bucketing is consistent and fast.

2. **Nemotron 3 Super** — Handles complex reasoning (cross-referencing
   compliance rules, temporal anomaly detection) well. The structured output
   is reliable.

3. **Wish list** — A Nemotron variant fine-tuned for entity extraction would
   help the compliance agent pull shipper/receiver names, addresses, and tax
   IDs more accurately from noisy document transcriptions.

---

## Cost note

The service runs with `--min-instances=0`, so it scales to zero when idle.
After recording the demo, it can be deleted:

```bash
gcloud run services delete vf-fraud-detection-nebius --region asia-southeast1
```
