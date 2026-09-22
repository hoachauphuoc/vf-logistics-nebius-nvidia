# VF Logistics — Autonomous Fraud Detection Agents

**Hackathon:** Nebius x NVIDIA Global AI Hackathon
**Track:** Best Apps and Agents
**Bonus target:** Best Use of Tavily ($3,000, stackable with a Track Award)

**Live demo (console):** https://vf-console-f7rcctz26a-as.a.run.app
**API:** https://vf-logistics-f7rcctz26a-as.a.run.app

The console is readable without signing in — the board, a case, the audit trail and
the cost figures are all public. **Recording a decision needs an account**, because
the audit trail names the person who released a shipment rather than the service that
called the API, and a free-text name field would make that record worthless. Judges:
the credentials are in the Devpost submission's testing-instructions field.

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

- Every model call in all four agents that existed at the time was rewritten from
  the `google-genai` Vertex AI SDK to `nebius_client.py`, a wrapper around the
  OpenAI-compatible `openai.AsyncOpenAI` client pointed at Nebius Token Factory.
  Three more agents have been added since, all Nemotron from the start.
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
                    Browser (Next.js 16 console, separate Cloud Run service)
                      |  fetch() JSON
                      v
      +---------------------------------------------+
      |  Cloud Run  ·  asia-southeast1               |
      |  vf-logistics  (+ vf-console)                 |
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
| Model | **NVIDIA Nemotron 3 Nano** (fraud, compliance, HS classification, zero-day radar) + **NVIDIA Nemotron 3 Super** (investigation, Senior Auditor debate) + **MiniCPM-V-4.5** (document intake, vision), all via **Nebius Token Factory** |
| Agent framework | `openai.AsyncOpenAI` (Token Factory's OpenAI-compatible endpoint) |
| External signal | **Tavily Search API** — live sanctions/news lookup in the compliance agent |
| Input security | **Model Armor** (Google Cloud) — windowed prompt-injection screening |
| Compute | **Cloud Run** (source deploy -> Cloud Build -> Artifact Registry) |
| State | **Firestore** (Native mode) — cases, events, audit log |
| Messaging | **Pub/Sub** — `shipment-events` in, `case-decisions` out |
| Web | Flask + gunicorn, flask-cors |
| Console | **Next.js 16** (App Router, React 19, Tailwind, TanStack Query) on a second Cloud Run service |
| Runtime | Python 3.11-slim container |

Requirement check against the hackathon rules:

- Runtime call to Nebius Token Factory -> every one of the seven agents
- Uses an NVIDIA open model -> `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` (fraud,
  compliance) and `nvidia/nemotron-3-super-120b-a12b` (investigation)
- Functional, runtime Tavily API call -> `tavily_client.search()` in the
  compliance agent, on the live path, not a stub
- Multi-step, autonomous workflow -> seven agents chained with conditional
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
gcloud run deploy vf-logistics \
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
BASE=$(gcloud run services describe vf-logistics \
  --region asia-southeast1 --format='value(status.url)')

curl -s $BASE/health          # expect store.backend=firestore, worker.mode=ondemand
curl -s $BASE/agents          # each agent reports the Nebius/NVIDIA model it runs on

curl -s -X POST $BASE/api/v1/simulate
curl -s $BASE/api/v1/orchestrator/state   # poll; each poll also advances a step
```

### 3. Tear down

```bash
gcloud run services delete vf-logistics --region asia-southeast1
gcloud run services delete vf-console   --region asia-southeast1
```

---

## Signing in

**Most of the console needs no account.** The board, every case trace, the audit trail
and the cost figures are all readable anonymously — `VF_PUBLIC_READS=true` on the console
and `ANONYMOUS_ROLE=viewer` on the backend govern that, and the split is on the **HTTP
method**, not a path list, so reads are public and writes never are. If you are here to
assess the system, you can ignore this section entirely.

Signing in is required for exactly one thing: **recording a review decision.** The audit
trail names the account that made each call, and that attribution is the point — it is
what makes a released shipment traceable to a person rather than to "the reviewer field
in the request body", which is what it used to be.

### The demo reviewer account

| | |
|---|---|
| Sign-in page | `/login` on the console |
| Address | `judge@vf-logistics.demo` |
| Password | Secret Manager, `VF_JUDGE_PASSWORD` — not in this repo and not in any log |

Read the password for your own deployment with:

```bash
gcloud secrets versions access latest \
  --secret=VF_JUDGE_PASSWORD --project=<your-project>
```

For a submission review the same password is supplied in the private
testing-instructions field, so a judge never has to touch `gcloud`.

### Creating your own operator

There is no self-service sign-up. Accounts live in `VF_OPERATORS` as
`email:iterations:salt:hash` records (PBKDF2-SHA256), semicolon-separated:

```bash
node frontend/scripts/make-operator.mjs you@example.com --out ./secrets
```

That writes the generated password to a **file** rather than printing it, so it does not
land in a shell history or a terminal transcript. Append the record to `VF_OPERATORS` and
redeploy the console:

```bash
gcloud run services update vf-console --region asia-southeast1 \
  --update-secrets VF_OPERATORS=VF_OPERATORS:latest
```

`VF_SESSION_SECRET` must be at least 32 characters; a shorter value is treated as absent,
and in production a missing one takes the console **offline** rather than leaving it open.

---

## Reproducible testing

```bash
# Unit + integration tests (637 tests)
python -m pytest tests/ -v

# Document upload tests
python scripts/test_documents.py        # uploads all seven sample docs
python scripts/test_documents.py 3      # three passes, reports any disagreement
python scripts/check_registry.py        # 11 checks on the counterparty book
```

### Test coverage

| Suite | Count | What it covers |
|-------|-------|----------------|
| Pure logic | 61 | auth, config, schemas, simulator, untrusted, agents._common |
| Sanctions & zero-day | 62 | Sanctions matching, list freshness, unseen-pattern handling |
| Decision paths | 54 | Every route a shipment can take through the state machine |
| Tenant isolation | 43 | Cross-tenant reads, writes, and aggregation |
| Hardening | 42 | Kill switch, Red Team screen, policy dry run, auto-debate, learning loop, per-hop I/O |
| Document upload | 33 | Accepted types, the PDF branch, injection screening |
| Console session | 31 | HMAC signing, forged tokens, reviewer attribution |
| Network defence | 31 | Rate limits, request size, header hygiene |
| Verifier | 30 | Risk reconciliation, prompt injection, whitelist, checks |
| B2B contract | 28 | The published response shape callers depend on |
| Routes | 27 | Security headers, CORS, auth, validation, pagination |
| Schema enforcement | 27 | Untrusted document fields against the declared schema |
| Budget | 26 | Per-tenant spend ceiling, cache TTL, fail-open on store error |
| Billing period | 24 | Windowed usage, and that every aggregation has an index |
| Store | 20 | MemoryStore CRUD, optimistic locking, pagination |
| Governance | 18 | Boundaries, drift detection, fail-closed |
| Lineage & billing | 18 | Per-step cost attribution |
| Orchestrator | 17 | State machine, tool execution, agent envelopes |
| Observability | 16 | Logging, metrics, request context |
| Concurrent decisions | 13 | Two reviewers deciding the same case |
| Unpriced model | 9 | An unpriced model is logged, not silently billed at the cheapest rate |
| Screen layers | 7 | Which of the two screening layers may refuse a shipment |
| **Total** | **637** | |

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
| `DEBATE_MODEL` | Model for the debate agent — **the one place Nemotron Ultra is used by default**. See the note below the table. | `nvidia/Nemotron-3-Ultra-550b-a55b` |
| `MODEL_SWITCH_MAX_RATE_MULTIPLE` | How much dearer a model `POST /api/v1/config/model` may select without `confirm_higher_cost`, against the cheapest priced model. Super is 4.0× Nano and permitted; Ultra is 13.3× and answered 409. | `5.0` |
| `TAVILY_ROUTE_CACHE_TTL_SECONDS` | TTL for the shipping-lane disruption search, whose query carries only a country pair. Measured: 20 searches across 6 distinct lanes. `0` disables. | `21600` (6h) |
| `TAVILY_ENTITY_CACHE_TTL_SECONDS` | TTL for the shipper/receiver adverse-media searches. Shorter because these carry a counterparty — though Tavily is *not* the sanctions control. `0` disables. | `3600` (1h) |
| `ZERO_DAY_MIN_DIVERSION_HUBS` | How many **distinct** transhipment hubs a route needs before zero-day screening opens. Two, matching the verifier's `MULTIPLE_DIVERSION_HUBS`. | `2` |
| `ZERO_DAY_NEWS_DAYS` | How far back the zero-day news search looks; older designations are the official list's job | `45` |
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
| `ANONYMOUS_ROLE` | Role granted to a request with no credentials. `viewer` makes reads public; `none` refuses them. The process refuses to boot if this grants write. | `viewer` |
| `VF_API_KEY` | Operator API key. Also what the console forwards upstream. | set in production via Secret Manager |
| `VF_TENANT_SPEND_CEILING_USD` | Per-tenant soft spend ceiling. Unset, garbage or `<= 0` all mean no ceiling. | unset |

### Console (the `vf-console` Cloud Run service)

| Variable | Description | Default |
|---|---|---|
| `FLASK_API_BASE` | Backend base URL. Read server-side per request, so it changes without a rebuild. | unset — required |
| `VF_SESSION_SECRET` | HMAC key for session cookies. Must be at least 32 characters; a shorter one is treated as absent. | unset — **required in production**, where a missing value takes the console offline rather than opening it |
| `VF_OPERATORS` | Semicolon-separated `email:iterations:salt:hash` records, PBKDF2-SHA256. Generate with `node frontend/scripts/make-operator.mjs <email> --out <dir>`, which writes the password to a file rather than printing it. | unset |
| `VF_PUBLIC_READS` | `true` lets anonymous visitors read the console. Writes are never covered by it — the split is on the HTTP method, not a path list. Defaults to false so a deployment that forgets it is locked, not open. | `false` |
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
Ultra costs 13× each and 3.3× overall for no change in any decision.

The debate is the exception. It runs only when the floor and the model disagree by 15
points or more (measured: 2 calls across 20 cases) and what it emits is not a score
awaiting override — it is a reasoned CONFIRM or DISAGREE on whether that disagreement can
be settled without a person. That judgement *is* the outcome, so reasoning capacity is
load-bearing. At this volume the switch costs roughly `$0.007` per 20 cases.

This is a quality bet, not a measured improvement: nothing yet demonstrates Ultra
resolves more disputes than Super. `scripts/compare_debate_models.py` replays disputed
cases through both and reports resolution rate and cost, and setting `DEBATE_MODEL` back
to `nvidia/nemotron-3-super-120b-a12b` reverses the decision without a deploy.

#### Tavily is the binding cost constraint, not the models

Measured on a 20-case run: **90–106 Tavily searches** (4.5–5.3 per case) against
`$0.067994` of Nemotron. At the free tier's 1,000 credits a month that is **188–222
cases**, while the model bill for the same traffic is under seven cents — so the external
search, not inference, is what limits throughput. `estimated_cost_usd` counts Nebius
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
├── frontend/                     Next.js 16 console (its own Cloud Run service)
│   ├── src/app/                  App Router pages: board, review, billing, legal, login
│   ├── src/components/           UI, incl. AccountMenu and the layout shell
│   ├── src/lib/session.ts        HMAC session signing, via Web Crypto so it runs on Edge
│   ├── src/proxy.ts              The login door (Next 16 renamed `middleware` to `proxy`)
│   └── scripts/make-operator.mjs PBKDF2 operator records; writes the password to a file
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
