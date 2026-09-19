# VF Logistics — Autonomous Fraud Detection Agents

**Hackathon:** Nebius x NVIDIA Global AI Hackathon
**Track:** Best Apps and Agents
**Bonus target:** Best Use of Tavily ($3,000, stackable with a Track Award)
**Live demo:** https://vf-logistics-f7rcctz26a-as.a.run.app

## The problem

Vietnamese logistics operators lose money to shipment fraud that is invisible to
threshold rules: a shipping cost 60% under the historical route average looks
like a promo, not under-invoicing. A shipper with 2 lifetime transactions and a
generic company name looks like a new customer, not a shell entity. Catching
these requires reading many weak signals *together* — exactly what a rules
engine cannot do and an analyst has no time to do at volume.

**The impact:** every case a rules engine misses is either a fraud loss that
surfaces weeks later in a reconciliation, or an analyst spending 20+ minutes
manually re-deriving a judgment call the agents below make in seconds, for
every one of hundreds of shipments a day.

A shipment event arrives and nobody touches it again. A background worker scores
it for fraud, decides on that score whether compliance screening is warranted,
decides on the screening whether to open a deep investigation, and then acts:
releasing the shipment, assigning an analyst, or holding the cargo and drafting a
suspicious activity report for human signature.

The AI model layer runs on **Nebius Token Factory**: **NVIDIA Nemotron 3 Nano**
for fraud and compliance scoring, **NVIDIA Nemotron 3 Super** for deep
investigation, and a vision model (**MiniCPM-V-4.5**) for document intake, since
Token Factory does not yet carry an NVIDIA vision model. Infrastructure — Cloud
Run, Firestore, Pub/Sub, Cloud Storage, Model Armor — stays on Google Cloud;
nothing about Nebius's rules requires moving hosting, only that the model calls
actually go to Token Factory, which they do.

---

## What was significantly updated during the Submission Period

This project began as a Google Cloud submission for a different hackathon (All
Things Agentic 2026), built entirely on Vertex AI Gemini. For this hackathon it
was substantially rebuilt as a new, standalone project:

- Every model call in all four agents was rewritten from the `google-genai`
  Vertex AI SDK to `nebius_client.py`, a wrapper around the OpenAI-compatible
  `openai.AsyncOpenAI` client pointed at Nebius Token Factory.
- The model roster changed entirely: **NVIDIA Nemotron 3 Nano** now drives
  fraud detection and compliance screening, **NVIDIA Nemotron 3 Super** drives
  investigation, and **MiniCPM-V-4.5** (a vision model, since Token Factory
  carries no NVIDIA vision model yet) drives document intake. None of these
  existed in the original submission.
- A new, functional **Tavily search integration** was added to the compliance
  agent (`tavily_client.py`): before scoring, it runs a live web search for the
  shipper and receiver names and folds the findings into the model's context as
  labelled, untrusted external evidence — a real runtime dependency, not a
  simulated one.
- Document intake gained a PDF-to-image rasterisation step (`pypdfium2`), because
  vision models on Token Factory take images, not raw PDF bytes the way Gemini
  did natively.
- `config.py`'s model/pricing registry, `.env.example`, `cloudbuild.yaml`, and
  the dashboard's model labels were all rewritten for the new model roster.
- The deterministic governance layer — risk floor, untrusted-input boundary,
  delegation boundary, shipper identity verification — was carried over
  unchanged, because none of it is model-specific; it is what keeps the system
  honest regardless of which LLM is doing the reasoning.

## What the system does

Four specialised agents plus a deterministic verification layer, coordinated by a
governance control plane:

| Agent | Responsibility | Model | Notable config |
|---|---|---|---|
| **Document Intake** | Transcribes bills of lading, invoices and packing lists into a structured record. Reports missing fields as missing rather than inventing them. | `openbmb/MiniCPM-V-4_5` | `temperature=0.0`, multimodal image input (PDFs rasterised first) |
| **Fraud Detection** | Price manipulation, route fraud, weight/dimension fraud, document fraud, identity fraud, duplicate & time fraud. | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | `temperature=0.1` for stable scoring |
| **Compliance Screening** | Sanctions exposure (OFAC/UN/EU patterns), trade & regulatory compliance, AML indicators — grounded by a live Tavily search. | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | `temperature=0.1`, runs in parallel with fraud, Tavily search injected as evidence |
| **AI Investigation** | Multi-step case investigation, pattern analysis, network mapping. | `nvidia/nemotron-3-super-120b-a12b` | Only reached on escalated cases |
| **Multi-Agent Debate** | Senior Auditor (Super) reviews Junior Analyst (Nano) fraud assessment using function calling. Can request re-evaluation, run Tavily searches, and render CONFIRM/DISAGREE verdicts. | `nvidia/nemotron-3-super-120b-a12b` | Opt-in via "Deep Review" button, function calling with 3 tools |

### Model selection, chosen per task

The hackathon's own model guidance is: let Nano or Super handle the fast,
everyday calls, and reach for Ultra when you need serious reasoning. This
system follows that shape directly:

Fraud and compliance screening run on **Nemotron 3 Nano** — every shipment
that arrives gets scored by both, so this is the highest-volume call in the
pipeline, and Nano is fast and inexpensive enough to run it on every event
without a cost blowout.

Investigation runs on **Nemotron 3 Super** — by the time a case reaches it, the
fraud and compliance findings already exist; it only runs on cases that were
escalated or where the deterministic floor and the model disagreed, so it is
the low-volume, high-stakes call that can afford a stronger, pricier model.
`INVESTIGATION_MODEL` is a one-line environment variable away from
`nvidia/Nemotron-3-Ultra-550b-a55b` if more Token Factory credit becomes
available.

Document intake is the one agent that needs a vision-capable model, and
NVIDIA does not currently publish one on Token Factory, so it runs on
**MiniCPM-V-4.5**, a model the catalog specifically calls out for OCR/PDF
understanding.

All three NVIDIA models and MiniCPM-V are reached through the same
OpenAI-compatible endpoint (`nebius_client.py`), so the split costs no extra
integration surface. All responses are requested in JSON mode
(`response_format={"type": "json_object"}`), parsed server-side, so downstream
routing is machine-readable. Every agent response envelope records which model
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

### Multi-Agent Debate: Super reviews Nano

The most sophisticated reasoning pattern in the system is **Multi-Agent Debate**,
where a Senior Auditor (Nemotron Super 120B) reviews the Junior Analyst's
(Nemotron Nano 30B) fraud assessment. This is an opt-in "Deep Review" operation
triggered by an analyst when a case needs extra scrutiny.

**Why two models?** Nano is fast and cheap — it scores every shipment that arrives.
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

Super iterates through tool calls until it calls `render_final_verdict`, up to
3 rounds. The debate trace is recorded in the case and rendered in the UI so
the analyst sees exactly what Super did.

**When to use it.** Deep Review is expensive (~15-30 seconds, Super token costs).
It is not run automatically. An analyst clicks "Deep Review" when:
- The risk score seems too low for the red flags present
- The shipper or receiver name sounds suspicious
- The case is borderline and the analyst wants a second opinion

The verdict does not override the analyst's decision — it is advisory evidence.

### The agents are not trusted

This is the part that matters most. Every agent above is a language model, and a
language model can be mistaken, overconfident, or manipulated by the very
document it is reading. The pipeline holds and releases physical cargo, so agent
output is treated as a **claim**, not a finding.

[`verifier.py`](verifier.py) recomputes what can be computed. Freight against
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
[`untrusted.py`](untrusted.py): `avg_route_cost`, `shipper_tx_count` and
`created_at`. A document that could state its own route average would defeat the
pricing check by setting it low, and one that could state its own shipper history
would defeat the counterparty check by claiming a long one. Absent history is
treated as unverified, and unverified is not clean.

That exclusion leaves a gap the design has to close somewhere else. Absent
history sets a floor of 45, above the auto-clear threshold of 40, so for a while
*no* uploaded or staged document could clear autonomously — the control was
written around an enrichment step that did not exist yet.
[`shipper_registry.py`](shipper_registry.py) is that step: it resolves the
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
analyses and proposes, but [`governance.py`](governance.py)'s execution gate
refuses every protected action.

### The reviewer always has the paperwork

Work enters two ways. A shipment event arrives on `/api/v1/events/shipment`, or a
document is uploaded — drag a PDF or a scan onto the **Document intake** card, or
use the file picker; both paths run the same code. In the deployed
`WORKER_MODE=ondemand` configuration the upload request also advances the case,
usually all the way to a terminal state before it responds.

Whichever way it arrived, **a case is meant to carry a bill of lading a human can
read.** When a shipper's original was uploaded it is archived to Cloud Storage and
shown as-is. When the case came from a data event there is no original, so
[`document_render.py`](document_render.py) renders one from the record and marks
it `SYSTEM-GENERATED` — on the document itself and in the case provenance
(`generated: true`, `rendered_from`). A reconstruction is never presented as an
original.

---

## Architecture

```
                    Browser (static/index.html)
                      |  fetch() JSON
                      v
      +---------------------------------------------+
      |  Cloud Run  ·  asia-southeast1               |
      |  vf-fraud-detection-nebius                   |
      |                                               |
      |  gunicorn --> Flask (main.py)                 |
      |                 |                             |
      |                 +- /                UI         |
      |                 +- /health                     |
      |                 +- /agents                     |
      |                 +- /demo                       |
      |                 +- /api/v1/**                  |
      |                      |                          |
      |      agents/ (openai AsyncOpenAI, async)        |
      |       +- document_agent.py                      |
      |       +- fraud_detection_agent.py                |
      |       +- compliance_agent.py -----> tavily_client.py --> Tavily Search API
      |       +- investigation_agent.py                  |
      +-----------------------+-----------------------------+
                              |  nebius_client.py (OpenAI-compatible)
                              v
         +-----------------------------------------+
         |  Nebius Token Factory                    |
         |    NVIDIA Nemotron 3 Nano                 |
         |      fraud · compliance                   |
         |    NVIDIA Nemotron 3 Super                |
         |      investigation                         |
         |    MiniCPM-V-4.5 (vision)                  |
         |      document intake                       |
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
                    +-- BLOCKED / REVIEW_REQUIRED, or risk >= 70
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
the routing policy is configuration rather than something buried in code.

### Why these choices

- **OpenAI-compatible client, one wrapper for four models** — `nebius_client.py`
  wraps `openai.AsyncOpenAI` pointed at Token Factory; all three Nemotron tiers
  and the vision model are reached the same way, so adding or swapping a model
  is a string change, not a new integration.
- **Async calls, gunicorn `--threads 8`** — a single instance handles concurrent
  analyses while each waits on model latency.
- **`WORKER_MODE=ondemand` with `--min-instances=0`** — cases advance *inside*
  request handlers: the Pub/Sub push, the document upload, and the dashboard's
  own state poll each carry the pipeline forward a step. The service scales to
  zero when no shipment exists.
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
| Model | **NVIDIA Nemotron 3 Nano** (fraud, compliance) + **NVIDIA Nemotron 3 Super** (investigation) + **MiniCPM-V-4.5** (document intake, vision), all via **Nebius Token Factory** |
| Agent framework | `openai.AsyncOpenAI` (Token Factory's OpenAI-compatible endpoint) |
| External signal | **Tavily Search API** — live sanctions/news lookup in the compliance agent |
| Input security | **Model Armor** (Google Cloud) — windowed prompt-injection screening |
| Compute | **Cloud Run** (source deploy -> Cloud Build -> Artifact Registry) |
| State | **Firestore** (Native mode) — cases, events, audit log |
| Messaging | **Pub/Sub** — `shipment-events` in, `case-decisions` out |
| Web | Flask + gunicorn, flask-cors |
| Frontend | Vanilla HTML/CSS/JS, no build step |
| Runtime | Python 3.11-slim container |

Requirement check against the hackathon rules:

- Runtime call to Nebius Token Factory -> every one of the four agents
- Uses an NVIDIA open model -> `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` (fraud,
  compliance) and `nvidia/nemotron-3-super-120b-a12b` (investigation)
- Functional, runtime Tavily API call -> `tavily_client.search()` in the
  compliance agent, on the live path, not a stub
- Multi-step, autonomous workflow -> four agents chained with conditional
  branching, driven by a background worker with no human in the loop
- Takes meaningful action -> shipments are held or released, analysts
  assigned, SAR drafts produced, decisions published

---

## API

Unchanged from the original design — the JSON contract every agent returns was
preserved through the port, so every endpoint below behaves identically to
before; only the `model` field in each response envelope changed.

### Autonomous orchestration

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/events/shipment` | POST | Shipment-created event sink. Idempotent per `shipment_id`. |
| `/api/v1/simulate` | POST | Inject the scripted three-shipment demo batch |
| `/api/v1/orchestrator/state` | GET | Full dashboard projection: cases, events, audit, counters |
| `/api/v1/orchestrator/case/<case_id>` | GET | One case with every agent hop, latency and action receipt |
| `/api/v1/orchestrator/tick` | POST | Advance the pipeline one step |
| `/api/v1/orchestrator/reset` | POST | Clear all cases, events and audit records |
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

### Example

```bash
curl -s -X POST $BASE/api/v1/fraud/analyze \
  -H 'Content-Type: application/json' \
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

python main.py             # http://localhost:8080
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

Deploy, with `NEBIUS_API_KEY` and `TAVILY_API_KEY` set as secrets rather than
plain env vars in a real deployment:

```bash
gcloud run deploy vf-fraud-detection-nebius \
  --source . \
  --region asia-southeast1 \
  --allow-unauthenticated \
  --memory 1Gi --cpu 1 --timeout 300 \
  --min-instances 0 --max-instances 3 \
  --set-env-vars "PROJECT_ID=$PROJECT_ID,WORKER_MODE=ondemand,STORE_BACKEND=firestore,DECISIONS_TOPIC=case-decisions,CLAIM_LEASE_SECONDS=120" \
  --set-secrets "NEBIUS_API_KEY=NEBIUS_API_KEY:latest,TAVILY_API_KEY=TAVILY_API_KEY:latest"
```

Verify:

```bash
BASE=$(gcloud run services describe vf-fraud-detection-nebius \
  --region asia-southeast1 --format='value(status.url)')

curl -s $BASE/health          # expect store.backend=firestore, worker.mode=ondemand
curl -s $BASE/agents          # each agent reports the Nebius/NVIDIA model it runs on

curl -s -X POST $BASE/api/v1/simulate
curl -s $BASE/api/v1/orchestrator/state   # poll; each poll also advances a step
```

### 3. Tear down

```bash
gcloud run services delete vf-fraud-detection-nebius --region asia-southeast1
```

---

## Reproducible testing

```bash
python scripts/test_documents.py        # uploads all seven sample docs
python scripts/test_documents.py 3      # three passes, reports any disagreement
python scripts/check_registry.py        # 11 checks on the counterparty book
```

These scripts only assert on case state (`AUTO_CLEARED`, `HELD_FOR_REVIEW`,
`ESCALATED`, `PENDING_HUMAN`) and JSON shape, not on which model produced a
result, so they exercise the ported pipeline exactly as they exercised the
original.

`GET $BASE/demo` runs the fraud agent on a built-in sample shipment — one
request, no body, no configuration.

---

## Firestore composite indexes (required once per project)

`review_queue`, `GET /api/v1/cases?state=...` and `GET /api/v1/audit?...`
query `state IN [...]`/`case_id`/`action`/`status` combined with an
`order_by` on a different field, which Firestore only serves from a
composite index — the collection previously avoided this on purpose to stay
zero-setup, at the cost of the bugs `firestore.indexes.json` and this step
now fix (a case waiting for review could silently fall out of the queue
once enough newer cases existed). Create the four indexes once per project:

```bash
gcloud firestore indexes composite create --collection-group=cases \
  --field-config=field-path=state,order=ascending \
  --field-config=field-path=created_at,order=descending

gcloud firestore indexes composite create --collection-group=audit_log \
  --field-config=field-path=case_id,order=ascending \
  --field-config=field-path=at,order=descending

gcloud firestore indexes composite create --collection-group=audit_log \
  --field-config=field-path=action,order=ascending \
  --field-config=field-path=at,order=descending

gcloud firestore indexes composite create --collection-group=audit_log \
  --field-config=field-path=status,order=ascending \
  --field-config=field-path=at,order=descending
```

Index builds run in the background (`gcloud firestore indexes composite list`
to check status) and queries against an unbuilt index fail loudly rather
than silently, so there is no risk of quietly querying an unindexed
collection. `firestore.indexes.json` is the source of truth for what should
exist; the commands above are how to apply it against a plain `gcloud`
project (no `firebase-tools` dependency required).

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
| `PROJECT_ID` | GCP project used for Firestore, Pub/Sub, Cloud Storage | `project-93ded24f-21c3-4f1b-a7d` |
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
| `PORT` | Port gunicorn binds to | `8080` |
| `MAX_DOCUMENT_MB` | Rejection threshold for uploaded documents | `20` |
| `MAX_ATTEMPTS` | Retries before a case is dead-lettered | `3` |
| `MAX_CONCURRENT` | Cases advanced in parallel | `3` |
| `MAX_CHAIN_STEPS` | Hops one case may take before the chain is cut | `6` |
| `CHAIN_BUDGET_SECONDS` | Wall-clock ceiling for one case's chain | `120` |
| `POLL_SECONDS` | Loop interval in `WORKER_MODE=poll` | `1.5` |

`config.py` holds the shared model registry and per-token pricing for fraud
and compliance. `POST /api/v1/config/model` switches between the registered
Nemotron tiers at runtime; investigation ignores it and reads
`INVESTIGATION_MODEL` at import.

---

## Findings & learnings

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
into emitting parseable JSON — so the four agents' prompts and output schemas
needed no changes at all, only the transport underneath them.

**A human reviewer with no paperwork is not a control.** (Carried over from
the original build.) The review panel only showed a source document for
cases uploaded as a document; event-sourced cases now get a
`SYSTEM-GENERATED` bill of lading rendered from the record
([`document_render.py`](document_render.py)), clearly labelled as such.

**`asyncio.run()` per Flask request breaks a cached client.** (Carried over.)
Every coroutine runs on the one long-lived worker loop the orchestrator
already uses, rather than opening and closing an event loop per request.

**Cloud Build source deploys need three separate grants.** (Carried over.)
`storage.objectAdmin`, `artifactregistry.writer` and `logging.logWriter` on
the default compute service account, or a build that reports `SUCCESS` with
no pushed image and no visible log output.

---

## Roadmap

The orchestration layer and the Nebius/NVIDIA model layer are both live. What
remains stubbed is historical data: the agents receive route-cost baselines as
request fields rather than pulling them from a warehouse, and the compliance
agent's sanctions knowledge is now grounded by a live Tavily search but still
has no dedicated OFAC/UN/EU list lookup. Next steps: a real historical-baseline
store, a dedicated sanctions-list API behind the compliance agent alongside
Tavily, and replacing the scripted simulator with a production Pub/Sub
subscription from the shipment system.

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
├── main.py                       Flask app, routes, async bridge, worker boot
├── orchestrator.py               Autonomous state machine + background worker
├── config.py                     Model registry, per-token pricing, runtime switch
├── governance.py                 Delegation Boundary + fail-closed execution gate
├── verifier.py                   Deterministic risk floor (no model consulted)
├── untrusted.py                  Schema whitelist for document-sourced fields
├── shipper_registry.py           Counterparty book: verifies a claimed shipper identity
├── model_armor.py                Windowed prompt-injection screening
├── nebius_client.py              Nebius Token Factory client (OpenAI-compatible)
├── tavily_client.py              Tavily search API wrapper
├── store.py                      Case/event/audit state (Firestore, memory fallback)
├── document_render.py            Renders event-sourced shipments as a bill of lading
├── document_store.py             Cloud Storage document archive
├── executor_client.py            Calls the split-identity executor service
├── tools.py                      Actions taken on the operator's behalf
├── simulator.py                  Scripted shipment events for the demo
├── scripts/                      Not deployed; data generation and verification
├── sample_docs/                  Seven committed sample PDFs, one per mechanism
├── agents/
│   ├── __init__.py               Public agent API
│   ├── _common.py                Shared JSON parsing, timing, response envelope
│   ├── document_agent.py         Multimodal document intake      — MiniCPM-V-4.5
│   ├── fraud_detection_agent.py  Fraud scoring                   — Nemotron 3 Nano
│   ├── compliance_agent.py       Sanctions / trade / AML + Tavily — Nemotron 3 Nano
│   └── investigation_agent.py    Deep-dive investigation         — Nemotron 3 Super
├── static/
│   └── index.html                Dashboard (no build step)
├── infra/
│   └── model_armor_template.json  Filter config for the Model Armor template
├── docs/
│   ├── architecture.html         Diagram source
│   └── PROJECT_STORY.md          What was built and what it cost to learn
├── Dockerfile                    python:3.11-slim + gunicorn
├── cloudbuild.yaml               Cloud Build config
├── requirements.txt
├── .env.example
├── SUBMISSION.md                 Devpost copy
└── README.md
```

## License

MIT — hackathon project, 2026.
