# Receiver contract for the `case-decisions` topic

Who this is for: the team whose system subscribes to Floorline's decisions (ERP, WMS,
billing). It says what Floorline sends, what it guarantees, and the one thing the
receiver must do so that an approved release or block takes effect exactly once.

Floorline now ships that receiver itself (see *The receiver Floorline ships* below):
a downstream system can read the applied record instead of subscribing to the topic,
and then this contract is already met. A system that subscribes to the topic directly
must meet it on its own.

## What is published

One Pub/Sub message per executed human decision, on the topic named by `DECISIONS_TOPIC`
(default `case-decisions`).

| Part | Content |
|---|---|
| data (JSON) | `case_id`, `outcome` (`RELEASED_BY_HUMAN` or `BLOCKED_BY_HUMAN`), `action`, `approval_id`, `evidence_version`, `evaluation_id`, `approver`, `executor`, `idempotency_key`, `at` |
| attribute `idempotency_key` | `exec-<approval_id>`: the same for every send of one approval |
| attribute `tenant_id` | present in multi-tenant deployments: the tenant the case belongs to |

The topic also carries the orchestrator's **pipeline status notifications**:
`AUTO_CLEARED` and `HELD_FOR_REVIEW` with `case_id`, `outcome`, `effective_risk`,
`at`; and `ESCALATED` with `case_id`, `outcome`, `fraud_pattern`,
`exposure_estimate`, `at`. These have no approval or idempotency key and are not
executed human decisions. A receiver dedicated to human decisions acknowledges
these known notification shapes without applying a decision. Other keyless
payloads remain invalid; never invent an approval key to apply them.

## Delivery guarantee: at least once

The same approval can arrive more than once, always with the same `idempotency_key`:

1. **The sender retries when it cannot know the outcome.** A send that timed out, or a
   process killed after the broker accepted the message but before Floorline saved that
   fact, leaves the outcome unknown. The retry reuses the key.
2. **Pub/Sub itself redelivers** a message whose acknowledgement was lost.

Floorline narrows case 1 with the **sent ledger** (below): a retry first reads the
messages the broker accepted and does not send again when its key is there. It cannot
remove case 2, and a ledger read can miss a message, so the receiver's part stays
required.

## What the receiver must do

1. **Claim the key before applying.** Insert `idempotency_key` into a store with a
   uniqueness guarantee (a primary key, a Firestore `create()`, a unique index). If the
   insert fails because the key exists, the decision was applied already: acknowledge
   the message and do nothing else.
2. **Claim and apply in one transaction.** A claim committed without the apply loses the
   decision after a crash; an apply committed without the claim applies it twice.
3. **Acknowledge only after the transaction committed.** An unacknowledged message comes
   back, and step 1 makes that harmless.
4. **Reject a message without `idempotency_key`.** It cannot be deduplicated. Leave it to a
   person (dead-letter it); never apply it automatically.
5. **Keep tenants apart.** Scope the claim store by `tenant_id` when the attribute is
   present.

## Reference implementation and evidence

- `scripts/reference_receiver.py`: `apply_once(attributes, claim, apply)` and
  `firestore_claim(db)`, the contract above as one short module.
- `tests/test_reference_receiver.py`: a repeat is not applied, a message without a key is
  rejected, and against the Firestore emulator 8 concurrent claims of one key let exactly
  one through.
- `tests/test_sim_hard_kill.py`, against the Pub/Sub and Firestore emulators: a process
  killed right after the broker accepted. Without the sent ledger the resume publishes a
  second message under the same key and the reference receiver applies it once. With the
  sent ledger the resume publishes nothing more.

These prove the protocol. They do not prove that a given receiver implements it: each
receiving system has to show its own claim-and-apply transaction.

## The receiver Floorline ships

`src/vf_logistics/decision_receiver.py`, served by the same `vf-app` service:

- `POST /api/v1/receiver/decision` is a Pub/Sub **push** endpoint. It accepts only a
  push whose OIDC token Google signed for the service account in `RECEIVER_PUSH_SA` and
  the audience in `RECEIVER_PUSH_AUDIENCE`; without both settings it accepts nothing
  (403). It records the decision under its `idempotency_key` and tenant in the store
  (`applied_decisions` in Firestore). The record is the application, and the create
  that claims the key is the same transaction, so a repeat only increments
  `deliveries`. A message without a key or a case is refused (422) and never applied;
  Pub/Sub keeps it, redelivers it, or moves it to a dead-letter topic if one is set.
- The three exact pipeline notification shapes above, with a case and broker
  message id, return `200` with `outcome: ignored`. They are logged with their
  outcome, case and message id, and cause **no shipment action and no
  `applied_decisions` write**. Repeats therefore have no business side effect.
  OIDC and the multi-tenant tenant requirement still apply. Approval metadata,
  a body-only key, incomplete or unknown payloads are not treated as notifications
  and remain refused with `422`.
- `GET /api/v1/receiver/applied/<key>` (viewer) returns `applied_once`, `deliveries`,
  the case, the outcome and the first message id.

Evidence: `tests/test_applied_decisions.py` (memory store, and the Firestore emulator
with 8 concurrent deliveries of one key: applied once, 8 deliveries counted) and
`tests/test_decision_receiver.py` (the token check, applied then duplicate, refusals).

Set-up (a deployment step, done by a person with project rights; PowerShell, one
line each, replace `<SA>` with the service account the push presents, for example the
default compute account `<project-number>-compute@developer.gserviceaccount.com`):

1. `gcloud pubsub subscriptions create case-decisions-receiver --topic=case-decisions --push-endpoint=https://<service-url>/api/v1/receiver/decision --push-auth-service-account=<SA> --push-auth-token-audience=https://<service-url>/api/v1/receiver/decision`
2. `gcloud run services update vf-app --region <region> --update-env-vars "RECEIVER_PUSH_SA=<SA>,RECEIVER_PUSH_AUDIENCE=https://<service-url>/api/v1/receiver/decision"`
   (keep the quotes: unquoted, PowerShell turns the comma into a space and both values land in `RECEIVER_PUSH_SA`)

Check: publish the same decision twice under one key, then read
`GET /api/v1/receiver/applied/<key>`: `deliveries` is 2 and `applied_once` is true.

## Checking a receiver: the conformance script

Floorline cannot see what a system it does not run does with a decision, so the check is handed
to that system. `scripts/receiver_conformance.py` is run by the receiving team against its own
endpoint. It sends Pub/Sub push envelopes under a fresh key (case id starting `CONF-`, so the
records are easy to discard) and reports PASS, FAIL or UNVERIFIED per obligation:

1. a first delivery is acknowledged;
2. a repeat of the same key is acknowledged;
3. eight concurrent repeats are all acknowledged;
4. a message without `idempotency_key` is refused and not applied;
5. the key was applied once, read from a URL the receiver provides.

```
python scripts/receiver_conformance.py https://wms.example/push --header "Authorization: Bearer <token>" --applied-url "https://wms.example/applied/{key}" --count-field result.applied
```

Exit code 0 means every obligation passed, 1 that one failed, 2 that nothing failed but obligation 5
could not be read (without `--applied-url` the script cannot see how often the key was applied, and
says so rather than passing it). A pass shows the endpoint meets the contract on that run; it does
not replace the receiving team's own tests of what its transaction does.

## Killing a process against real Pub/Sub (operations)

`tests/test_sim_hard_kill.py` also runs against the Pub/Sub of a real project, on a topic created for
the run (`hardkill-<ns>`, deleted with its subscriptions afterwards). The store stays on the Firestore
emulator, so nothing is written to a real database and no production decision is published. It
needs Application Default Credentials that may create topics and subscriptions in the project, the
Firestore emulator running, and no Pub/Sub emulator (PowerShell):

```
$env:FIRESTORE_EMULATOR_HOST = "127.0.0.1:8681"
$env:HARD_KILL_REAL_PUBSUB_PROJECT = "<project-id>"
python -m pytest tests/test_sim_hard_kill.py -v
```

What it shows is what an emulator cannot: whether the broker's own pull returns the message the sent
ledger needs. If the sent-ledger test fails with two messages on the topic, the ledger missed one,
which the receiver's deduplication then absorbs; the failure is a finding, not a flake.

## Sent ledger (sender side, operations)

A pull subscription on the decisions topic that only Floorline reads. Every message the
broker accepted is in it, so a Resume or Retry finds a decision whose own record was never
saved and records it instead of sending it again. If the ledger cannot be read, Floorline
sends nothing and records the outcome as unknown (`send_unknown`); the retry can be made
once the ledger is reachable.

Set-up (a deployment step, done by a person with project rights):

1. Create the subscription **before** the service publishes, with a retention that covers
   the claim lease and the time to a retry, for example:
   `gcloud pubsub subscriptions create case-decisions-sent-ledger --topic=case-decisions --message-retention-duration=7d`
2. Give the service identity `roles/pubsub.subscriber` on that subscription.
3. Set `SENT_LEDGER_SUBSCRIPTION=case-decisions-sent-ledger` on the service.

Without the setting the ledger is never read and behaviour is as before: a retry after
an unknown outcome sends again under the same key, and the receiver's deduplication
handles it.
