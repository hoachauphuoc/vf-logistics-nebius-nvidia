import { describe, expect, it } from "vitest";

import { NO_VALUE } from "@/lib/format";

import {
  BUCKET_LABEL,
  buildCaseTimeline,
  CONTRADICTION_KIND_LABEL,
  coverage,
  describeCostSpread,
  describeSpread,
  dueStatus,
  executionClaim,
  formatSpan,
  informationRounds,
  ownerLabel,
  riskLabel,
} from "./operations";

describe("executionClaim", () => {
  const claimingApproval = { approval_id: "ap1", status: "CLAIMING" };

  it("is null unless the case is EXECUTING", () => {
    const claim = executionClaim(
      {
        state: "APPROVED",
        verification: {
          approvals: [claimingApproval],
          executions: [{ approval_id: "ap1", status: "claiming", claim_expires_epoch: 2000 }],
        },
      } as never,
      1_000_000,
    );
    expect(claim).toBeNull();
  });

  it("is null when no approval is still claiming", () => {
    const claim = executionClaim(
      {
        state: "EXECUTING",
        verification: {
          approvals: [{ approval_id: "ap1", status: "APPROVED" }],
          executions: [{ approval_id: "ap1", status: "claiming", claim_expires_epoch: 2000 }],
        },
      } as never,
      1_000_000,
    );
    expect(claim).toBeNull();
  });

  it("is null when the claiming approval has no claiming execution of its own", () => {
    const claim = executionClaim(
      {
        state: "EXECUTING",
        verification: {
          approvals: [claimingApproval],
          executions: [{ approval_id: "other", status: "claiming", claim_expires_epoch: 2000 }],
        },
      } as never,
      1_000_000,
    );
    expect(claim).toBeNull();
  });

  it("reports a claim whose lease is still running as not expired", () => {
    const execution = { approval_id: "ap1", status: "claiming", claim_expires_epoch: 2000 };
    const claim = executionClaim(
      { state: "EXECUTING", verification: { approvals: [claimingApproval], executions: [execution] } } as never,
      1_999_000,
    );
    expect(claim?.expired).toBe(false);
    expect(claim?.execution).toBe(execution);
    expect(claim?.approval).toEqual(claimingApproval);
  });

  it("reports a lease as expired from the exact moment it ends", () => {
    const execution = { approval_id: "ap1", status: "claiming", claim_expires_epoch: 2000 };
    const claim = executionClaim(
      { state: "EXECUTING", verification: { approvals: [claimingApproval], executions: [execution] } } as never,
      2_000_000,
    );
    expect(claim?.expired).toBe(true);
  });

  it("treats a claim with no lease end as expired, as the server does", () => {
    const execution = { approval_id: "ap1", status: "claiming" };
    const claim = executionClaim(
      { state: "EXECUTING", verification: { approvals: [claimingApproval], executions: [execution] } } as never,
      1_000_000,
    );
    expect(claim?.expired).toBe(true);
  });

  it("reads the latest claiming execution when there are several", () => {
    const older = { approval_id: "ap1", status: "claiming", claim_expires_epoch: 100 };
    const newer = { approval_id: "ap1", status: "claiming", claim_expires_epoch: 9_000_000_000 };
    const claim = executionClaim(
      {
        state: "EXECUTING",
        verification: { approvals: [claimingApproval], executions: [older, newer] },
      } as never,
      1_000_000,
    );
    expect(claim?.execution).toBe(newer);
    expect(claim?.expired).toBe(false);
  });
});

describe("riskLabel edges", () => {
  it("shows a zero score rather than dropping it", () => {
    expect(riskLabel({ risk_score: 0, reconciliation: null } as never)).toBe("risk 0");
  });

  it("shows the floor when it differs from the score", () => {
    expect(riskLabel({ risk_score: 55, reconciliation: { risk_floor: 45 } } as never)).toBe("risk 55 (floor 45)");
  });

  it("is null for a missing score even when a floor is known", () => {
    expect(riskLabel({ risk_score: null, reconciliation: { risk_floor: 45 } } as never)).toBeNull();
  });
});

describe("dueStatus edges", () => {
  const now = Date.parse("2026-06-01T12:00:00Z");

  it("says no SLA for a due date that is not a date", () => {
    expect(dueStatus({ due_at: "not a date" } as never, now)).toEqual({ tone: "no_sla", text: "No SLA" });
  });

  it("counts a case due exactly now as due soon with no time left", () => {
    expect(dueStatus({ due_at: new Date(now).toISOString() } as never, now)).toEqual({
      tone: "due_soon",
      text: "0m left",
    });
  });

  it("gives hours and minutes left for a case that is on time", () => {
    const due = new Date(now + 3 * 3_600_000 + 12 * 60_000).toISOString();
    expect(dueStatus({ due_at: due } as never, now)).toEqual({ tone: "on_time", text: "3h 12m left" });
  });

  it("says how long a case has been overdue", () => {
    const due = new Date(now - 30 * 60_000).toISOString();
    expect(dueStatus({ due_at: due } as never, now)).toEqual({ tone: "overdue", text: "Overdue 30m" });
  });
});

describe("formatSpan", () => {
  it("shows a span under a minute in seconds", () => {
    expect(formatSpan(45_000)).toBe("45s");
  });

  it("shows a longer span as hours and minutes", () => {
    expect(formatSpan(90_000)).toBe("1m");
  });

  it("is a dash for absent, negative or non-finite spans", () => {
    expect(formatSpan(null)).toBe(NO_VALUE);
    expect(formatSpan(undefined)).toBe(NO_VALUE);
    expect(formatSpan(-5)).toBe(NO_VALUE);
    expect(formatSpan(Number.POSITIVE_INFINITY)).toBe(NO_VALUE);
  });
});

describe("describeSpread and describeCostSpread", () => {
  it("uses the format it is given for both figures", () => {
    const summary = { n: 3, median: 2, p95: 5 };
    expect(describeSpread(summary as never, (v) => `${v}!`)).toBe("median 2! · p95 5!");
  });

  it("is a dash when nothing was measured", () => {
    expect(describeSpread({ n: 0, median: null, p95: null } as never)).toBe(NO_VALUE);
    expect(describeSpread(null)).toBe(NO_VALUE);
  });

  it("formats cost figures as dollars", () => {
    expect(describeCostSpread({ n: 2, median: 0.5, p95: 1.5 } as never)).toBe("median $0.5000 · p95 $1.50");
  });
});

describe("coverage", () => {
  it("says how many cases a figure was measured on", () => {
    expect(coverage(3, 7)).toBe("3 of 7");
  });

  it("is a dash when there is nothing to count against", () => {
    expect(coverage(3, 0)).toBe(NO_VALUE);
    expect(coverage(null, 7)).toBe(NO_VALUE);
  });
});

describe("ownerLabel and labels", () => {
  it("names a queue by its humanised code", () => {
    expect(ownerLabel({ kind: "queue", name: "hs_review" } as never)).toBe("HS review queue");
  });

  it("names a person by their name as given", () => {
    expect(ownerLabel({ kind: "person", name: "Ana Ruiz" } as never)).toBe("Ana Ruiz");
  });

  it("gives every contradiction kind a readable label", () => {
    expect(CONTRADICTION_KIND_LABEL.producer).toBe("Producer");
    expect(CONTRADICTION_KIND_LABEL.certificate_country).toBe("Certificate of origin");
  });

  it("gives every work bucket a title and a blurb", () => {
    for (const bucket of Object.values(BUCKET_LABEL)) {
      expect(bucket.title).not.toBe("");
      expect(bucket.blurb).not.toBe("");
    }
    expect(BUCKET_LABEL.awaiting_review.title).toBe("Waiting for a reviewer");
  });
});

describe("informationRounds", () => {
  it("is zero for a case that has never been reviewed", () => {
    expect(informationRounds({} as never)).toBe(0);
  });

  it("counts requests for information and ignores other reviews", () => {
    const reviews = [{ action: "request_info" }, { action: "release" }, null, { action: "request_info" }];
    expect(informationRounds({ reviews } as never)).toBe(2);
  });
});

describe("buildCaseTimeline details", () => {
  it("names the arrival source in plain words", () => {
    const [arrived] = buildCaseTimeline({ created_at: "2026-03-01T10:00:00Z", source: "email_intake" } as never);
    expect(arrived?.title).toBe("Arrived from email intake");
    expect(arrived?.kind).toBe("arrived");
  });

  it("says a reviewer overturned the agent when their decision differs from its proposal", () => {
    const events = buildCaseTimeline({
      reviews: [
        {
          action: "release",
          state_after: "RELEASED_BY_HUMAN",
          agent_proposed: "ESCALATED",
          at: "2026-03-01T12:00:00Z",
          reviewer: "ana",
          note: "Papers check out",
        },
      ],
    } as never);
    const decision = events.find((e) => e.kind === "decision");
    expect(decision?.title).toBe("Released by a reviewer (the agent had proposed escalated)");
    expect(decision?.tone).toBe("good");
    expect(decision?.who).toBe("ana");
    expect(decision?.detail).toBe("Papers check out");
  });

  it("marks a block decision bad and a request for information neutral", () => {
    const events = buildCaseTimeline({
      reviews: [
        { action: "block", state_after: "BLOCKED_BY_HUMAN", at: "2026-03-01T12:00:00Z" },
        { action: "request_info", at: "2026-03-01T13:00:00Z", note: "Need the certificate" },
      ],
    } as never);
    const block = events.find((e) => e.kind === "decision");
    const request = events.find((e) => e.kind === "request");
    expect(block?.tone).toBe("bad");
    expect(request?.title).toBe("Asked for more information");
    expect(request?.detail).toBe("Need the certificate");
  });

  it("suffixes a receipt that did not complete with its status", () => {
    const events = buildCaseTimeline({
      actions: [{ action: "draft_sar", status: "failed", at: "2026-03-01T11:00:00Z" }],
    } as never);
    const action = events.find((e) => e.kind === "action");
    expect(action?.title).toBe("Draft SAR (failed)");
    expect(action?.tone).toBe("neutral");
  });

  it("draws an audit row with no matching receipt, with its actor", () => {
    const events = buildCaseTimeline({} as never, [
      { audit_id: "a9", action: "publish_decision", status: "done", at: "2026-03-01T11:00:00Z", actor: "svc-bot" },
    ] as never);
    const audit = events.find((e) => e.kind === "audit");
    expect(audit?.title).toBe("Publish decision");
    expect(audit?.who).toBe("svc-bot");
  });

  it("skips human decisions from the trail, since reviews already carry them", () => {
    const events = buildCaseTimeline({} as never, [
      { audit_id: "a1", action: "human_release", status: "done", at: "2026-03-01T11:00:00Z" },
    ] as never);
    expect(events.map((e) => e.kind)).toEqual(["arrived"]);
  });

  it("does not draw a receipt twice when its audit row is also on the trail", () => {
    const events = buildCaseTimeline(
      { actions: [{ audit_id: "a1", action: "draft_sar", status: "done", at: "2026-03-01T11:00:00Z" }] } as never,
      [{ audit_id: "a1", action: "draft_sar", status: "done", at: "2026-03-01T11:00:00Z" }] as never,
    );
    expect(events.filter((e) => e.title === "Draft SAR")).toHaveLength(1);
  });

  it("orders events by time, whatever order the case document lists them in", () => {
    const events = buildCaseTimeline({
      created_at: "2026-03-01T10:00:00Z",
      source: "email_intake",
      reviews: [{ action: "release", state_after: "RELEASED_BY_HUMAN", at: "2026-03-01T12:00:00Z" }],
      actions: [{ action: "draft_sar", status: "done", at: "2026-03-01T11:00:00Z" }],
    } as never);
    expect(events.map((e) => e.title)).toEqual([
      "Arrived from email intake",
      "Draft SAR",
      "Released by a reviewer",
    ]);
  });

  it("says what was requested, or a generic word when no document is named", () => {
    const events = buildCaseTimeline({
      verification: {
        requests: [
          { documents: ["bill_of_lading"], status: "OPEN", owner: "ana" },
          { documents: [], status: "CLOSED" },
        ],
      },
    } as never);
    const requests = events.filter((e) => e.kind === "evidence_request");
    expect(requests[0]?.title).toBe("Requested: bill_of_lading");
    expect(requests[0]?.detail).toBe("Status: OPEN");
    expect(requests[0]?.who).toBe("ana");
    expect(requests[1]?.title).toBe("Requested: documents");
  });

  it("marks a document Model Armor blocked as bad, and a clean one with its hash", () => {
    const events = buildCaseTimeline({
      verification: {
        documents: [
          { doc_type: "certificate_of_origin", blocked: true, received_at: "2026-03-01T10:00:00Z" },
          {
            doc_type: "certificate_of_origin",
            blocked: false,
            sha256: "abcdef1234567890",
            received_at: "2026-03-01T11:00:00Z",
          },
        ],
      },
    } as never);
    const received = events.filter((e) => e.kind === "evidence_received");
    expect(received[0]?.detail).toBe("Blocked by Model Armor");
    expect(received[0]?.tone).toBe("bad");
    expect(received[1]?.title).toBe("Received Certificate of origin");
    expect(received[1]?.detail).toContain("sha256: abcdef123456...");
    expect(received[1]?.tone).toBe("good");
  });

  it("calls an evaluation with only unresolved papers neutral, and a clean one good", () => {
    const events = buildCaseTimeline({
      verification: {
        evaluations: [
          { evidence_version: 1, at: "2026-03-01T10:00:00Z", risk_floor: 0, status: "clean", unresolved: ["x"] },
          { evidence_version: 2, at: "2026-03-01T11:00:00Z", risk_floor: 0, status: "clean", unresolved: [] },
        ],
      },
    } as never);
    const evals = events.filter((e) => e.kind === "evidence_eval");
    expect(evals[0]?.tone).toBe("neutral");
    expect(evals[0]?.title).toBe("Re-evaluated (v1): 0 clarified, 1 unresolved");
    expect(evals[1]?.tone).toBe("good");
    expect(evals[1]?.detail).toBe("Floor: 0 | Status: clean");
  });

  it("says a superseded approval was superseded by new evidence", () => {
    const events = buildCaseTimeline({
      verification: {
        approvals: [{ approval_id: "ap1", action: "block", status: "SUPERSEDED", evidence_version: 1, at: "2026-03-01T10:00:00Z" }],
      },
    } as never);
    const approval = events.find((e) => e.kind === "evidence_approval");
    expect(approval?.title).toBe("Block approved (v1)");
    expect(approval?.detail).toBe("Superseded by new evidence");
    expect(approval?.tone).toBe("bad");
  });

  it("shows a denied execution as denied, with its reason and executor", () => {
    const events = buildCaseTimeline({
      verification: {
        executions: [{ status: "denied", reason: "lease lost", executor: "svc-bot", at: "2026-03-01T10:00:00Z" }],
      },
    } as never);
    const execution = events.find((e) => e.kind === "evidence_execution");
    expect(execution?.title).toBe("Execution denied");
    expect(execution?.detail).toBe("lease lost");
    expect(execution?.who).toBe("svc-bot");
    expect(execution?.tone).toBe("bad");
  });

  it("shows a sent execution with its message id as good", () => {
    const events = buildCaseTimeline({
      verification: {
        executions: [{ status: "sent", message_id: "m-42", at: "2026-03-01T10:00:00Z" }],
      },
    } as never);
    const execution = events.find((e) => e.kind === "evidence_execution");
    expect(execution?.title).toBe("Executed (m-42)");
    expect(execution?.tone).toBe("good");
  });
});
