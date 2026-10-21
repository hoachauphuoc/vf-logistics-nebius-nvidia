# Devpost upload set: 15 images, in upload order

Devpost takes at most 15 images and uses the first as the thumbnail, so this folder holds the
17 screenshots of `docs/screenshots/` cut down to 15 and numbered in the order to upload them.
`01` is a 3:2 centre-crop (1620x1080) of the architecture page, for the thumbnail; the rest are
unchanged copies.

Left out: `01-sign-in.png` (a login screen, and the guest-judge steps are in the testing
instructions) and `05-case-trace.png` (superseded by `16-debate-trace-on-super.png`, the same
trace with the debate hop). Both stay in `docs/screenshots/`.

| Upload as | Source | Caption |
|---|---|---|
| `01-the-rule.png` | `15-architecture.png` | Models may raise risk. Lower it? Never. `effective = max(model, floor)`, with an interactive demonstration. |
| `02-floor-overrules-the-model.png` | `04-review-queue.png` | "The model scored 72 and the deterministic floor put this at 90. The floor stands." Each finding sets a minimum score; a person decides. |
| `03-trace-per-hop-models-and-debate.png` | `16-debate-trace-on-super.png` | The case trace names the model on every hop: Nemotron 3 Nano on screening, Super on investigation and the Senior Auditor debate, with Tavily sources and cost. |
| `04-senior-auditor-debate.png` | `17-senior-auditor-debate-verdict.png` | The auditor chose its own Tavily search, then rendered CONFIRM at 90% confidence. A CONFIRM changes nothing, and nothing the debate says can clear a case. |
| `05-due-diligence-dossier.png` | `06-due-diligence-dossier.png` | The due-diligence dossier (PDF): outcome, shipment as declared, sanctions screening against 18,525 OFAC SDN and UN records, findings. |
| `06-model-choices-measured.png` | `09-evaluation-model-choices.png` | Model choices, tested: Nano flagged 46/52 frauds where the rules saw nothing and Super 47/52 at 4.3x the cost; on 46 labelled debates Ultra cost 5.2x as much and was no better, so the debate runs on Super. |
| `07-evaluation-with-intervals.png` | `08-evaluation.png` | The Evaluation page: every figure with its 95% interval, the synthetic-corpus caveats first. |
| `08-operating-curve.png` | `10-evaluation-operating-curve.png` | The rules at every review threshold: what each setting would hold and miss at the measured fraud rate. |
| `09-governance-delegation-boundary.png` | `07-governance.png` | The delegation boundary a named person publishes, its history, and a policy simulation before publishing. |
| `10-audit-trail.png` | `12-audit-trail.png` | The audit trail: every action, who took it, and every action the boundary refused, recorded like a success. |
| `11-agent-console-cost-and-injection-probe.png` | `11-agent-console-cost-and-injection-probe.png` | Models and rates, cost by agent, and an injection probe that runs the real screen over pasted text. |
| `12-pipeline-board.png` | `02-pipeline-board.png` | The pipeline board: every shipment by workflow state, with spend, agent calls and the boundary version. |
| `13-today-worklist.png` | `03-today-worklist.png` | Today: what is waiting on a person, grouped by what it is waiting for. |
| `14-risk-radar.png` | `13-risk-radar.png` | Risk radar: blocked and incomplete checks, how clearances were reached, completed audits. |
| `15-devops.png` | `14-devops.png` | DevOps: a scripted batch, a bill-of-lading upload through Model Armor, and one-by-hand submission. |

All data on screen is synthetic demo data; the one account shown is `guest-judge@vf-logistics.demo`.
