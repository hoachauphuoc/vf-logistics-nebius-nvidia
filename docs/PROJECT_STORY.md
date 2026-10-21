## Inspiration

A freight forwarder's compliance desk is a queue of PDFs. Someone checks the declared value against the cargo and the consignee against sanctions lists, and decides whether the container moves. When the queue is long the checking gets thin, and the cases that need the most attention are the ones designed to look boring.

A model that can release a container can be talked into releasing one. So the question is what the system may do on its own, who decided that, and what happens when the document argues with the model.

The answer is one line of asymmetry. `verifier.py` computes a deterministic risk floor from arithmetic and list lookups, with no model and no network. An agent may raise risk above the floor and never lower it. A wrong exoneration releases contraband; a wrong escalation costs a person ten minutes. **Floorline** is the line the agents may climb above and never cross below.

## What it does

Floorline screens shipments for a forwarder's compliance desk. Model Armor screens each document as untrusted input before a model reads it, and the deterministic floor is computed first. Nemotron agents score and screen above it, with live Tavily search. An HS classifier checks the declared tariff code against the goods, and a zero-day radar searches adverse media for parties no sanctions list has caught up with.

When the floor exceeds the model's score by 15 points or more, a Senior Auditor debate runs. A confident DISAGREE can send a case to a deeper investigation, upward only; it can never clear one. Clear cases are released inside a delegation boundary a named person published. The rest go to a reviewer with the findings, sources and a due-diligence dossier. Missing evidence is requested per document, received, re-evaluated, approved by a person and executed once per idempotency key.

## How we built it

Nebius Token Factory serves every model call through one OpenAI-compatible endpoint. Nemotron 3 Nano handles fraud, compliance, HS classification and the zero-day radar; Nemotron 3 Super handles investigation and the debate; MiniCPM-V-4.5 reads scanned documents, since Token Factory has no NVIDIA vision model yet. Tavily runs at runtime in six places. The backend is Flask on Cloud Run with Firestore and Pub/Sub, and the Next.js console runs in the same container.

Both model choices were measured rather than assumed. Where the rules score a case 0 the model is the only check, and on 179 such cases Nano flagged 46 of 52 frauds against Super's 47 of 52, at a quarter of the cost, so fraud stays on Nano. The debate began on Ultra, because its verdict can change routing rather than only a score the floor overrides; on 46 labelled disputed cases Ultra reached a verdict less often than Super, said DISAGREE about as often on honest trade as on fraud, and cost 5.2x as much, so the debate runs on Super.

## Challenges we ran into

- **A rate multiple is not a cost multiple, and neither is a price worth paying until it is measured.** We documented Ultra as 3.3x Super from its per-token rate. Measured on the live service a debate cost 13x ($0.0198 against $0.0015), because Ultra makes more tool-call rounds and each one resends the growing transcript. Then we measured what that bought: nothing we could show, so Super runs the debate.
- **A model that agrees with the rules is not independent evidence.** Both models said DISAGREE on honest cases about as often as on fraud, because the auditor is shown the rules' findings and every honest case in the test was one the rules held. The debate can only send a held case to investigation; we report it as a routing step.
- **Booking data cannot separate fraud from honest trade.** Four identical origin-fraud pairs in the benchmark proved it, and led to the evidence loop.
- **Independent reviews found real defects.** Concurrent execution could send a decision twice, and a failed publish was recorded as done. The fixes were claim-before-send and one publish per idempotency key.
- **The screen is not precise.** On a held-out half of a synthetic corpus the rules held 38.4% of clean shipments (95% interval 28–49%). At 0.2% fraud, the 2024 Vietnam customs rate, that is about 206 holds per real fraud case.

## Accomplishments that we're proud of

- The risk floor cannot be talked down, because no model takes part in computing it. The answer to "what can this do without asking" is a versioned document with a person's name on it.
- The HS classifier is our best-measured number. Nano started at 40.0% recall on a 30-case set and 50.0% on a 24-case holdout. Worked examples made it worse. Giving it the published contents of the real HS headings took recall to 92.9% and 91.7%. The numbers are small: 11 of 12 evasions caught, 0 of 12 honest cases flagged, and a 95% interval of 64% to 99% on that recall.
- Tests run against real database and broker emulators: 2,095 backend tests at 96% coverage, 1,729 frontend tests, and mypy at 0 errors.
- Failure is legible. When Model Armor returned 403, the system said so in the response instead of pretending.

## What we learned

- **Choose the model per agent, not per project.** Splitting one model constant by task was cheaper and easier to justify.
- **Fail closed pays off when you find you were wrong.** An IAM misconfiguration was a logged warning and a held container, not an incident.
- **Verify against the deployed system, not the code you remember writing.**
- **Controls compose, and the bugs live in the composition.** Every rule survived review on its own; the ones that broke things were two correct rules meeting.

## What's next for Floorline

Intake tied to a booking reference issued against a customer account, so identity is established before any document is read; the delegation boundary attached to a real approval workflow; broader deterministic floors with a trade-compliance specialist; and per-tenant boundaries so a forwarder can grant a narrower delegation than their customs broker.

The long version of this story is in `docs/PROJECT_STORY_FULL.md`.
