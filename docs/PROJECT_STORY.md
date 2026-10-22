## Inspiration

A freight forwarder's compliance desk is a queue of PDFs. Someone checks the declared value against the cargo and the consignee against sanctions lists, and decides whether the container moves. When the queue is long the checking gets thin, and the cases that need the most attention are the ones designed to look boring.

A model that can release a container can be talked into releasing one. So the question is what the system may do on its own, who decided that, and what happens when the document argues with the model.

The answer is one line of asymmetry. `verifier.py` computes a deterministic risk **floor** from arithmetic and list lookups, with no model and no network. An agent may raise risk above the floor and never lower it: `effective = max(model, floor)`. A wrong exoneration releases contraband; a wrong escalation costs a person ten minutes. **Floorline** is the line the agents may climb above and never cross below.

## What it does

Floorline screens shipments for a freight forwarder's compliance desk.

- Model Armor screens each document as untrusted input before any model reads it, and the deterministic floor is computed first.
- Nemotron agents on Nebius Token Factory score and screen above the floor, with live Tavily web search. An HS classifier checks the declared tariff code against the goods, and a zero-day radar searches adverse media for parties no sanctions list has caught up with.
- When the floor exceeds the model's score by 15 points or more, a Senior Auditor debate runs. It can send a case to a deeper investigation, upward only; it can never clear one.
- Clear cases are released inside a delegation boundary that a named person published. The rest go to a reviewer with the findings, the sources and a due-diligence dossier.
- Missing evidence is requested per document, received through a link without an account, re-evaluated, approved by a person and executed once per idempotency key. In the demo, two shipments with identical bookings end in different decisions only because their purchase invoices differ: one is released by a person, the other is stopped.

## How we built it

Every model call goes through **Nebius Token Factory**, one OpenAI-compatible endpoint. **NVIDIA Nemotron 3 Nano** handles fraud, compliance, HS classification and the zero-day radar; **NVIDIA Nemotron 3 Super** handles investigation and the debate; MiniCPM-V-4.5 reads scanned documents, because Token Factory has no NVIDIA vision model yet. **Tavily** runs at runtime in six places. The backend is Flask on Cloud Run with Firestore, Pub/Sub and Model Armor, and the Next.js console runs in the same container. Nebius AI Cloud is not used.

Both model choices were measured, not assumed.

- Where the rules score a case 0, the model is the only check. On 179 such cases Nano flagged 46 of 52 frauds against Super's 47 of 52, at a quarter of the cost, so fraud stays on Nano.
- The debate began on Nemotron 3 Ultra, because its verdict can change routing rather than only a score the floor overrides. On 46 labelled disputed cases Ultra reached a verdict less often than Super (37 of 46 against 40 of 46), was no better at telling fraud from honest trade, and cost 5.2x as much, so the debate runs on Super.

## Challenges we ran into

- **A rate multiple is not a cost multiple.** We documented Ultra as 3.3x Super from its per-token rate. Measured on the live service it was 13x, because Ultra makes more tool-call rounds and each one resends the growing transcript. Then we measured what that bought, and could show nothing.
- **A model that agrees with the rules is not independent evidence.** Both models said DISAGREE on honest cases about as often as on fraud, because the auditor sees the rules' findings. We report the debate as a routing step, not a verdict.
- **Booking data cannot separate fraud from honest trade.** Four identical origin-fraud pairs in the benchmark proved it, and led to the evidence loop.
- **Independent reviews found real defects.** Concurrent execution could send a decision twice, and a failed publish was recorded as done; later a race could leave two audit rows for one send. The fixes were claim-before-send, one publish per idempotency key, and one atomic audit row per send.
- **The screen is not precise.** On a held-out half of a synthetic corpus the rules held 38.4% of clean shipments (95% interval 28 to 49%). At 0.2% fraud, the 2024 Vietnam customs rate, that is about 206 holds per real fraud case. The model layer buys recall and costs precision: the whole screen holds about 73% of honest holdout shipments (63 of 86). No real customer traffic has been measured.

## Accomplishments that we're proud of

- The risk floor cannot be talked down, because no model takes part in computing it. The answer to "what can this do without asking" is a versioned document with a person's name on it.
- The HS classifier is our best-measured number. Nano started at 40.0% recall on a 30-case set and 50.0% on a 24-case holdout. Worked examples made it worse. Giving it the published contents of the real HS headings took recall to 92.9% and 91.7%. The numbers are small (11 of 12 evasions caught, 0 of 12 honest cases flagged) and we say so.
- Tests run against real database and broker emulators: 2,120 backend tests (96% line coverage), 1,731 frontend tests (62%), mypy at 0 errors, measured on commit `76d015e`.
- Failure is legible: when Model Armor returned 403, the system said so instead of pretending.

## What we learned

- **Choose the model per agent, not per project, and measure the choice.**
- **Fail closed pays off when you find you were wrong.**
- **Verify against the deployed system, not the code you remember writing.**
- **Controls compose, and the bugs live in the composition.**

## What was significantly updated during the Submission Period

Floorline began as an entry to a different hackathon (All Things Agentic, Google Cloud, Vertex AI Gemini): [CHAUPHUOCHOA/vf-logistics-hackathon-google](https://github.com/CHAUPHUOCHOA/vf-logistics-hackathon-google), first commit 29 Aug 2026 (after this hackathon's Submission Period opened on 26 Aug), last commit `755d998` on 31 Aug (Vietnam time). This repository's first commit is `6bb1e59` (17 Sep).

| | Before (`755d998`) | Now |
|---|---|---|
| Models | 4 agents on Gemini via Vertex AI | 7 agents on Nebius Token Factory: Nemotron 3 Nano, Super, plus MiniCPM-V |
| Console | one static HTML page | Next.js 16 in the same container as the API |
| Evidence loop | a note | request, receive, re-evaluate, approve, execute, with an audit trail |
| Tests | none | 2,120 backend and 1,731 frontend |
| CI | no test or lint CI | five GitHub Actions jobs, each able to fail the build |

The commit ranges are reproducible with the `git diff --shortstat` commands in the README.

## What's next for Floorline

Intake tied to a booking reference issued against a customer account, so identity is established before any document is read; the delegation boundary attached to a real approval workflow; broader deterministic floors with a trade-compliance specialist; and per-tenant boundaries so a forwarder can grant a narrower delegation than their customs broker.

## Try it

Live demo: https://vf-app-350828852747.asia-southeast1.run.app (sign in with **Continue as guest judge**; the testing instructions have the password accounts). Code and setup: https://github.com/hoachauphuoc/vf-logistics-nebius-nvidia
