import { describe, expect, it } from "vitest";

import { NO_VALUE } from "@/lib/format";
import { helpFor } from "@/lib/help-content";
import {
  BUCKET_LABEL,
  buildCaseTimeline,
  coverage,
  describeSpread,
  dueStatus,
  formatSpan,
  informationRounds,
  ownerLabel,
} from "@/lib/operations";
import { WORK_BUCKETS, type AuditRecord, type Case } from "@/lib/types";

/**
 * The fixtures below are shaped like what the backend WRITES, not like what the
 * TypeScript interfaces declare. That distinction is the point: this project has
 * shipped three screens that read a key the API never sends, guarded by `!= null`
 * so they rendered nothing and every test passed. A refusal's reason is the live
 * example -- governance.execute puts it in `detail.gate_reason`, and the interface
 * also declares a top-level `gate_reason` that nothing ever sets.
 */

function denial(action: string, reason: string, at: string) {
  // governance.py execute(): the shape of a denied receipt, verbatim.
  return {
    audit_id: `audit-${action}`,
    case_id: "CASE-1",
    action,
    status: "denied",
    detail: { gate_reason: reason, boundary_version: 3, human_triggers: [] },
    at,
  };
}

function aCase(overrides: Partial<Case> = {}): Case {
  return {
    case_id: "CASE-1",
    shipment_id: "SHP-1",
    state: "PENDING_HUMAN",
    created_at: "2026-10-12T08:00:00Z",
    ...overrides,
  } as Case;
}

describe("buildCaseTimeline", () => {
  it("says why the delegation boundary refused, from where governance writes it", () => {
    const c = aCase({
      actions: [denial("release_shipment", "DENIED: risk 72 is above the ceiling of 40", "2026-10-12T08:01:00Z")],
    });
    const refused = buildCaseTimeline(c).find((e) => e.kind === "refused");
    expect(refused?.detail).toBe("DENIED: risk 72 is above the ceiling of 40");
    expect(refused?.tone).toBe("bad");
  });

  it("gives a refusal found only on the audit trail its reason too", () => {
    const row = denial("hold_shipment", "DENIED: agent is SUSPENDED.", "2026-10-12T08:02:00Z");
    const refused = buildCaseTimeline(aCase(), [row as AuditRecord]).find((e) => e.kind === "refused");
    expect(refused?.detail).toBe("DENIED: agent is SUSPENDED.");
  });

  it("draws a receipt and its audit row as one event", () => {
    const receipt = denial("release_shipment", "DENIED: x", "2026-10-12T08:01:00Z");
    const events = buildCaseTimeline(aCase({ actions: [receipt] }), [receipt as AuditRecord]);
    expect(events.filter((e) => e.kind === "refused")).toHaveLength(1);
  });

  it("takes a human decision from reviews, with its note, and not again from the trail", () => {
    // orchestrator.human_decide(): the review entry it appends, verbatim keys.
    const c = aCase({
      state: "BLOCKED_BY_HUMAN",
      reviews: [
        {
          action: "block",
          reviewer: "ana@example.com",
          note: "Producer on the C/O does not match the invoice.",
          at: "2026-10-12T09:00:00Z",
          state_before: "HELD_FOR_REVIEW",
          state_after: "BLOCKED_BY_HUMAN",
          agent_proposed: "HELD_FOR_REVIEW",
          sar_signed: null,
        },
      ],
    });
    const trail = [
      { audit_id: "a-h", case_id: "CASE-1", action: "human_block", status: "done", at: "2026-10-12T09:00:01Z", actor: "ana@example.com" },
    ] as AuditRecord[];
    const events = buildCaseTimeline(c, trail);
    const decisions = events.filter((e) => e.kind === "decision");
    expect(decisions).toHaveLength(1);
    expect(decisions[0].who).toBe("ana@example.com");
    expect(decisions[0].detail).toBe("Producer on the C/O does not match the invoice.");
    expect(decisions[0].tone).toBe("bad");
    expect(events.some((e) => e.kind === "audit")).toBe(false);
  });

  it("orders events by time and keeps arrival first", () => {
    const c = aCase({
      validation: { findings: [{ code: "SANCTIONS_MATCH", floor: 90, detail: "d" }] } as Case["validation"],
      steps: [{ agent: "compliance", at: "2026-10-12T08:00:30Z" }] as Case["steps"],
      reviews: [{ action: "request_info", reviewer: "r@x", note: "C/O please", at: "2026-10-12T08:10:00Z" }],
      actions: [denial("release_shipment", "DENIED", "2026-10-12T08:05:00Z")],
    });
    expect(buildCaseTimeline(c).map((e) => e.kind)).toEqual([
      "arrived", "finding", "agent", "refused", "request",
    ]);
  });

  it("does not throw on a case with nothing on it", () => {
    expect(buildCaseTimeline({ case_id: "X" } as Case)).toHaveLength(1);
  });
});

describe("informationRounds", () => {
  it("counts only requests for information", () => {
    const c = aCase({
      reviews: [
        { action: "request_info", reviewer: "a" },
        { action: "request_info", reviewer: "a" },
        { action: "release", reviewer: "a" },
      ],
    });
    expect(informationRounds(c)).toBe(2);
    expect(informationRounds(aCase())).toBe(0);
  });
});

describe("dueStatus", () => {
  const now = Date.parse("2026-10-12T12:00:00Z");
  it("says there is no SLA rather than guessing one", () => {
    expect(dueStatus({ due_at: null }, now)).toEqual({ tone: "no_sla", text: "No SLA" });
    expect(dueStatus({ due_at: "not a date" }, now).tone).toBe("no_sla");
  });
  it("separates overdue, due within the hour, and on time", () => {
    expect(dueStatus({ due_at: "2026-10-12T11:00:00Z" }, now).tone).toBe("overdue");
    expect(dueStatus({ due_at: "2026-10-12T12:30:00Z" }, now).tone).toBe("due_soon");
    expect(dueStatus({ due_at: "2026-10-13T12:00:00Z" }, now).tone).toBe("on_time");
  });
});

describe("figures nobody measured are a dash, never zero", () => {
  it("formatSpan", () => {
    expect(formatSpan(null)).toBe(NO_VALUE);
    expect(formatSpan(undefined)).toBe(NO_VALUE);
    expect(formatSpan(-1)).toBe(NO_VALUE);
    expect(formatSpan(42_000)).toBe("42s");
  });
  it("describeSpread", () => {
    expect(describeSpread({ n: 0, median: null, p95: null, total: null })).toBe(NO_VALUE);
    expect(describeSpread(null)).toBe(NO_VALUE);
    expect(describeSpread({ n: 2, median: 5_000, p95: 9_000, total: 14_000 })).toBe("median 5s · p95 9s");
  });
  it("coverage", () => {
    expect(coverage(3, 0)).toBe(NO_VALUE);
    expect(coverage(3, 7)).toBe("3 of 7");
  });
});

describe("ownerLabel", () => {
  it("says Unassigned plainly", () => {
    expect(ownerLabel({ kind: "unassigned", name: null })).toBe("Unassigned");
    expect(ownerLabel(null)).toBe("Unassigned");
  });
  it("names a person or a queue", () => {
    expect(ownerLabel({ kind: "person", name: "ana@example.com" })).toBe("ana@example.com");
    expect(ownerLabel({ kind: "queue", name: "trade-review" })).toMatch(/queue$/);
  });
});

describe("every group the API can return has a label and a help entry", () => {
  // HelpDot renders nothing for an unregistered id, so a missing entry is not an
  // error anywhere -- the dot is simply absent. Driven by WORK_BUCKETS so a new
  // group cannot be added without its words.
  it.each(WORK_BUCKETS)("%s", (bucket) => {
    expect(BUCKET_LABEL[bucket]?.title).toBeTruthy();
    expect(helpFor(`today.${bucket}`)).toBeDefined();
  });

  it.each([
    "nav:/today", "nav:/outcomes", "today.groups", "case.timeline",
    "outcomes.resolved", "outcomes.time_to_resolution", "outcomes.handling", "outcomes.rounds",
    "outcomes.cost", "outcomes.latency", "outcomes.held", "outcomes.refused",
  ])("%s", (id) => {
    expect(helpFor(id)).toBeDefined();
  });
});
