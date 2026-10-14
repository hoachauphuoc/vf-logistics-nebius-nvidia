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
  isContradicted,
  latestEvaluation,
  ownerLabel,
  riskLabel,
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

describe("buildCaseTimeline approvals", () => {
  // evidence.approve(): the shape of an approval that waived unresolved evidence.
  const approval = (extra: Record<string, unknown> = {}) => ({
    approval_id: "evapr-1", action: "release", approver: "r@x.example",
    evidence_version: 1, status: "VALID", at: "2026-10-12T09:00:00Z", ...extra,
  });

  it("marks a release that waived unresolved evidence, with what and why", () => {
    const c = aCase({
      verification: {
        evidence_version: 1, requests: [], documents: [], evaluations: [],
        approvals: [approval({
          note: "Confirmed by phone",
          exception: { unresolved: ["producer_declaration"], reason: "Confirmed by phone", approved_by: "r@x.example" },
        })],
      },
    } as Partial<Case>);
    const e = buildCaseTimeline(c).find((x) => x.kind === "evidence_approval");
    expect(e?.title).toMatch(/as an exception/);
    expect(e?.detail).toMatch(/Confirmed by phone/);
    expect(e?.detail).toMatch(/producer/i);
    expect(e?.tone).toBe("bad");
  });

  it("leaves an ordinary approval unmarked", () => {
    const c = aCase({
      verification: {
        evidence_version: 1, requests: [], documents: [], evaluations: [],
        approvals: [approval()],
      },
    } as Partial<Case>);
    const e = buildCaseTimeline(c).find((x) => x.kind === "evidence_approval");
    expect(e?.title).not.toMatch(/exception/);
    expect(e?.tone).toBe("good");
  });
});


describe("what the papers said, on the case", () => {
  // evidence.reevaluate(): an evaluation record, verbatim keys. The contradiction
  // sentences are the verifier's own (verifier.check_origin_evidence).
  const evaluation = (extra: Record<string, unknown> = {}) => ({
    evaluation_id: "eveval-1", evidence_version: 3, at: "2026-10-14T04:16:54Z",
    risk_floor: 80, findings: ["ORIGIN_EVIDENCE_CONTRADICTION"], clarified: ["certificate_of_origin", "producer_declaration", "input_purchase_invoices"],
    unresolved: [], status: "contradicted",
    contradictions: [{ kind: "input_origin", detail: "An input purchase invoice is for China-origin goods from Linyi Veneer Co., Ltd." }],
    ...extra,
  });
  const withEvaluations = (evaluations: unknown[], evidence_version = 3) => aCase({
    verification: { evidence_version, requests: [], documents: [], evaluations, approvals: [] },
  } as Partial<Case>);

  it("says which paper contradicts, not only that something does", () => {
    const e = buildCaseTimeline(withEvaluations([evaluation()])).find((x) => x.kind === "evidence_eval");
    expect(e?.title).toBe("Re-evaluated (v3): 3 clarified, 0 unresolved, 1 contradiction");
    expect(e?.detail).toContain("Floor: 80 | Status: contradicted");
    expect(e?.detail).toContain("- An input purchase invoice is for China-origin goods from Linyi Veneer Co., Ltd.");
    expect(e?.tone).toBe("bad");
  });

  it("pluralises, and keeps a clean evaluation to its one line", () => {
    const two = evaluation({ contradictions: [{ kind: "producer", detail: "a" }, { kind: "input_origin", detail: "b" }] });
    expect(buildCaseTimeline(withEvaluations([two])).find((x) => x.kind === "evidence_eval")?.title).toMatch(/2 contradictions$/);
    const clean = evaluation({ status: "provided", contradictions: [], risk_floor: 45 });
    const e = buildCaseTimeline(withEvaluations([clean])).find((x) => x.kind === "evidence_eval");
    expect(e?.detail).toBe("Floor: 45 | Status: provided");
    expect(e?.tone).toBe("good");
  });

  it("names the model that read each document", () => {
    const c = aCase({
      verification: {
        evidence_version: 1, requests: [], evaluations: [], approvals: [],
        documents: [
          { document_id: "d1", doc_type: "input_purchase_invoices", sha256: "45c39ec7bc2bdeadbeef", received_at: "2026-10-14T04:16:00Z", blocked: false,
            extraction: { model: "openbmb/MiniCPM-V-4_5", cost_usd: 0.00057 } },
          { document_id: "d2", doc_type: "producer_declaration", sha256: "ed2b80e04d31cafe", received_at: "2026-10-14T04:16:05Z", blocked: false },
        ],
      },
    } as unknown as Partial<Case>);
    const received = buildCaseTimeline(c).filter((x) => x.kind === "evidence_received");
    expect(received[0].detail).toBe("sha256: 45c39ec7bc2b... · Read by MiniCPM-V 4.5");
    expect(received[1].detail).toBe("sha256: ed2b80e04d31...");
  });

  it("describes a release that waived a contradiction", () => {
    const c = aCase({
      verification: {
        evidence_version: 1, requests: [], documents: [], evaluations: [],
        approvals: [{
          approval_id: "evapr-1", action: "release", approver: "r@x.example", evidence_version: 1,
          status: "VALID", at: "2026-10-14T09:00:00Z",
          exception: {
            unresolved: [], reason: "Certificate misread; checked the original", approved_by: "r@x.example",
            contradictions: [{ kind: "certificate_country", detail: "The certificate of origin states China." }],
          },
        }],
      },
    } as unknown as Partial<Case>);
    const e = buildCaseTimeline(c).find((x) => x.kind === "evidence_approval");
    expect(e?.title).toMatch(/as an exception/);
    expect(e?.detail).toBe("Waived: papers that contradict the declared origin. Reason: Certificate misread; checked the original");
  });

  it("latestEvaluation is the latest at the CURRENT version, and nothing once new papers arrive", () => {
    const old = evaluation({ evaluation_id: "old", evidence_version: 2, status: "missing", contradictions: [] });
    const now = evaluation({ evaluation_id: "now" });
    expect(latestEvaluation(withEvaluations([old, now]))?.evaluation_id).toBe("now");
    expect(latestEvaluation(withEvaluations([old, now], 4))).toBeNull(); // v4 arrived, not yet evaluated
    expect(latestEvaluation(withEvaluations([]))).toBeNull();
    expect(latestEvaluation(aCase())).toBeNull();
  });

  it("isContradicted reads the status or any contradiction, and tolerates absence", () => {
    expect(isContradicted(evaluation() as never)).toBe(true);
    expect(isContradicted(evaluation({ status: "provided", contradictions: [] }) as never)).toBe(false);
    expect(isContradicted(evaluation({ status: "provided" }) as never)).toBe(true); // a contradiction is a contradiction
    expect(isContradicted(null)).toBe(false);
    expect(isContradicted(undefined)).toBe(false);
  });
});


describe("a finding the papers have answered", () => {
  const finding = {
    code: "ORIGIN_INPUTS_UNVERIFIED", severity: "MEDIUM", floor: 45, detail: "A booking does not show where the inputs came from.",
    source_entity_ids: [],
    measured: { documents_needed: ["certificate_of_origin", "producer_declaration", "input_purchase_invoices"] },
  };
  const caseWith = (evaluation: Record<string, unknown> | null, evidence_version = 3) => aCase({
    validation: { findings: [finding] },
    verification: {
      evidence_version, requests: [], documents: [], approvals: [],
      evaluations: evaluation ? [{
        evaluation_id: "e1", evidence_version: 3, at: "2026-10-14T04:16:19Z", risk_floor: 45, status: "provided",
        clarified: finding.measured.documents_needed, unresolved: [], contradictions: [], ...evaluation,
      }] : [],
    },
  } as unknown as Partial<Case>);
  const findingEvent = (c: Case) => buildCaseTimeline(c).find((x) => x.kind === "finding");

  it("is no longer drawn as an open problem, but keeps its floor on the line", () => {
    const e = findingEvent(caseWith({}));
    expect(e?.title).toBe("Origin inputs unverified — floor 45 — evidence received");
    expect(e?.tone).toBe("neutral");
  });

  it("stays a problem while papers are missing, contradicting, or newer than the evaluation", () => {
    expect(findingEvent(caseWith({ clarified: ["certificate_of_origin"], status: "missing" }))?.tone).toBe("bad");
    expect(findingEvent(caseWith({ status: "contradicted", contradictions: [{ kind: "input_origin", detail: "x" }] }))?.tone).toBe("bad");
    expect(findingEvent(caseWith({}, 4))?.tone).toBe("bad");
    expect(findingEvent(caseWith(null))?.title).toBe("Origin inputs unverified — floor 45");
  });
});

describe("riskLabel", () => {
  it("adds the floor when it is not the score, so a number that did not move says why", () => {
    expect(riskLabel({ risk_score: 55, reconciliation: { risk_floor: 45 } } as never)).toBe("risk 55 (floor 45)");
  });

  it("leaves the score alone when the floor is the score, or there is no floor", () => {
    expect(riskLabel({ risk_score: 80, reconciliation: { risk_floor: 80 } } as never)).toBe("risk 80");
    expect(riskLabel({ risk_score: 80 } as never)).toBe("risk 80");
    expect(riskLabel({ risk_score: 0, reconciliation: { risk_floor: 0 } } as never)).toBe("risk 0");
  });

  it("is null for a case with no score", () => {
    expect(riskLabel({ risk_score: null } as never)).toBeNull();
    expect(riskLabel({} as never)).toBeNull();
  });
});
