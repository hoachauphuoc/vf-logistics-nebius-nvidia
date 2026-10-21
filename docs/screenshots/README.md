# Image gallery for the Devpost submission

Seventeen screenshots, 21 Oct 2026, taken from the live service (Cloud Run revision
`vf-app-00045-fxk`, deployed from `fb3a53f`) signed in as the one-click guest judge, except
15, which is `docs/architecture.html`. Images 16 and 17 are a Deep Review run that day on
`CASE-FULL-10-DIVERSION`, which added one debate step to that demo case. Every case, company and person on screen is synthetic
demo data; the one account shown is `guest-judge@vf-logistics.demo`. No token, password or key
is in any frame. Captions below are ready to paste.

| File | Caption |
|---|---|
| `01-sign-in.png` | Sign in: one click as a guest judge, or a password account. Anonymous visitors see only this screen. |
| `02-pipeline-board.png` | The pipeline board: every shipment by workflow state, with spend, agent calls and the published boundary version (v3). |
| `03-today-worklist.png` | Today: what is waiting on a person, grouped by what it is waiting for. |
| `04-review-queue.png` | The idea in one line: "The model scored 72 and the deterministic floor put this at 90. The floor stands." Findings each set a minimum score; a person decides. |
| `05-case-trace-per-hop-models.png` | The case trace names the model that ran each hop (Nemotron 3 Nano on screening, Super on investigation), its time, its Tavily sources and its cost. |
| `06-due-diligence-dossier.png` | The due-diligence dossier (PDF), page 1: outcome, shipment as declared, sanctions screening against 18,525 OFAC SDN and UN records, and findings. |
| `07-governance.png` | Governance: the delegation boundary a named person publishes, its history, and a policy simulation before publishing. |
| `08-evaluation.png` | Evaluation: every figure with its 95% interval, the synthetic-corpus caveats first, and the before/after of the tuning. |
| `09-evaluation-model-choices.png` | Model choices, tested. Nano flagged 46/52 frauds where the rules saw nothing and Super 47/52 at 4.3x the cost; on 46 labelled debates Ultra reached a verdict less often and cost 5.2x as much, so the debate runs on Super. |
| `10-evaluation-operating-curve.png` | The rules at every review threshold: what each setting would hold and miss, at the measured fraud rate. |
| `11-agent-console-cost-and-injection-probe.png` | Agent console: models and per-token rates, cost by agent, and an injection probe that runs the real screen over pasted text. |
| `12-audit-trail.png` | The audit trail: every action, who took it, and every action the boundary refused, recorded like a success. |
| `13-risk-radar.png` | Risk radar: blocked and incomplete checks, how clearances were reached, and the completed audits. |
| `14-devops.png` | DevOps: a scripted batch of three shipments, a bill-of-lading upload through Model Armor, and one-by-hand submission. |
| `15-architecture.png` | Architecture: models may raise risk and never lower it; an interactive demonstration of `effective = max(model, floor)`. |
| `16-debate-trace-on-super.png` | The same trace after a Deep Review: the Senior Auditor debate ran on Nemotron 3 Super (10.2 s), and the verdict panel says the deterministic floor (80) overruled the model (78): the model may raise risk but never lower it. |
| `17-senior-auditor-debate-verdict.png` | The debate itself: the auditor chose its own Tavily search in round 1 and rendered CONFIRM at 90% confidence in round 2, recommending a hold. A CONFIRM changes nothing, and nothing the debate says can clear a case. |

## Not captured, and why

- **Model Armor blocking `sample_docs/injected_bol.pdf`.** Uploading it creates a blocked case
  on the shared board. The injection probe on the agent console (image 11) runs the same
  screen without creating a case.

## Retaking them

`docs/screenshots` was produced with Playwright and the preinstalled Chromium: sign in with
`POST /api/auth/judge`, open each route at 1920x1080 and wait for the network to settle. The
trace and the evaluation cards are element screenshots at 2x; the dossier is
`GET /api/proxy/orchestrator/case/<id>/dossier`, page 1 rendered with pypdfium2.
