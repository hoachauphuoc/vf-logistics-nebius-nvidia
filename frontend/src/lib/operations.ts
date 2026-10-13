/**
 * Presentation rules for the operator screens: Today, a case's verification
 * page, and Outcomes.
 *
 * The grouping itself is the API's (worklist.py) -- these helpers only label it,
 * time it and arrange a case's history into one line of events. Kept out of the
 * components so the rules are testable, and, like lib/format.ts, nothing here
 * throws on absent input.
 */

import { actionLabel, caseStateLabel, formatUsd, humaniseAgent, humaniseCode, NO_VALUE } from "./format";
import { formatDuration } from "./pipeline";
import type {
  ActionReceipt,
  AuditRecord,
  Case,
  EvidenceApproval,
  EvidenceDocument,
  EvidenceEvaluation,
  EvidenceExecution,
  EvidenceRequest,
  HumanReview,
  MeasuredSummary,
  WorkBucket,
  WorkItem,
  WorkOwner,
} from "./types";

export const BUCKET_LABEL: Record<WorkBucket, { title: string; blurb: string }> = {
  awaiting_documents: {
    title: "Waiting for documents",
    blurb: "A reviewer asked the shipper for more. Nothing to decide until it arrives.",
  },
  awaiting_review: {
    title: "Waiting for a reviewer",
    blurb: "The findings are in. Someone has to read them and decide.",
  },
  awaiting_sign_off: {
    title: "Waiting for sign-off",
    blurb: "The agent escalated these. The escalation needs a person's signature.",
  },
  awaiting_execution: {
    title: "Approved, not yet carried out",
    blurb: "Decided, and waiting for the decision to be executed.",
  },
};

export function ownerLabel(owner: WorkOwner | null | undefined): string {
  if (!owner || owner.kind === "unassigned" || !owner.name) return "Unassigned";
  return owner.kind === "queue" ? `${humaniseCode(owner.name.toUpperCase())} queue` : owner.name;
}

export type DueTone = "overdue" | "due_soon" | "on_time" | "no_sla";

/**
 * How a waiting case stands against its routing SLA. `due_at` is the API's
 * (waiting_since + the SLA the agent routed it with); no SLA is said, not guessed.
 */
export function dueStatus(item: Pick<WorkItem, "due_at">, now: number = Date.now()): { tone: DueTone; text: string } {
  if (!item.due_at) return { tone: "no_sla", text: "No SLA" };
  const due = new Date(item.due_at).getTime();
  if (Number.isNaN(due)) return { tone: "no_sla", text: "No SLA" };
  const diff = due - now;
  if (diff < 0) return { tone: "overdue", text: `Overdue ${formatDuration(-diff)}` };
  if (diff < 3_600_000) return { tone: "due_soon", text: `${formatDuration(diff)} left` };
  return { tone: "on_time", text: `${formatDuration(diff)} left` };
}

/** "3h 12m" for a span in milliseconds, under a minute as seconds, absent as a dash. */
export function formatSpan(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return NO_VALUE;
  if (ms < 60_000) return `${Math.round(ms / 1000)}s`;
  return formatDuration(ms);
}

/** "median 4m · p95 31m" -- or a dash when nothing was measured. */
export function describeSpread(
  summary: MeasuredSummary | null | undefined,
  format: (value: number | null | undefined) => string = formatSpan,
): string {
  if (!summary || summary.n === 0 || summary.median == null) return NO_VALUE;
  return `median ${format(summary.median)} · p95 ${format(summary.p95)}`;
}

export const describeCostSpread = (summary: MeasuredSummary | null | undefined) =>
  describeSpread(summary, formatUsd);

/** "3 of 7" coverage, so a figure measured on a few cases says so. */
export function coverage(n: number | null | undefined, of: number | null | undefined): string {
  if (n == null || of == null || of === 0) return NO_VALUE;
  return `${n} of ${of}`;
}

// --------------------------------------------------------------------------
// One case, as one line of events
// --------------------------------------------------------------------------

export type TimelineKind =
  | "arrived"
  | "finding"
  | "agent"
  | "refused"
  | "request"
  | "decision"
  | "action"
  | "audit"
  | "evidence_request"
  | "evidence_received"
  | "evidence_eval"
  | "evidence_approval"
  | "evidence_execution";

export interface TimelineEvent {
  kind: TimelineKind;
  at: string | null;
  title: string;
  detail?: string | null;
  who?: string | null;
  /** "bad" for a refusal or a block, "good" for a release, else neutral. */
  tone?: "good" | "bad" | "neutral";
}

function reviewEvent(review: HumanReview): TimelineEvent {
  const action = review.action ?? "";
  if (action === "request_info") {
    return {
      kind: "request",
      at: review.at ?? null,
      title: "Asked for more information",
      detail: review.note || null,
      who: review.reviewer ?? null,
      tone: "neutral",
    };
  }
  const overturned =
    review.agent_proposed && review.state_after && review.agent_proposed !== review.state_after
      ? ` (the agent had proposed ${caseStateLabel(review.agent_proposed).toLowerCase()})`
      : "";
  return {
    kind: "decision",
    at: review.at ?? null,
    title: `${caseStateLabel(review.state_after ?? null)}${overturned}`,
    detail: review.note || null,
    who: review.reviewer ?? null,
    tone: action === "release" ? "good" : action === "block" ? "bad" : "neutral",
  };
}

function receiptEvent(receipt: ActionReceipt): TimelineEvent {
  const refused = receipt.status === "denied";
  // governance.execute writes the refusal's reason INSIDE `detail` (gate_reason);
  // the top-level `gate_reason` the type also declares is never sent. Read both so
  // a refused row says why rather than rendering a blank detail on every case.
  const nested = receipt.detail?.gate_reason;
  const reason = typeof nested === "string" && nested ? nested : receipt.gate_reason ?? null;
  return {
    kind: refused ? "refused" : "action",
    at: receipt.at ?? null,
    title: refused
      ? `${actionLabel(receipt.action)} refused by the delegation boundary`
      : `${actionLabel(receipt.action)}${receipt.status && receipt.status !== "done" ? ` (${receipt.status})` : ""}`,
    detail: refused ? reason : null,
    tone: refused ? "bad" : "neutral",
  };
}

/**
 * Everything that happened to a case, in order: when it arrived, what the rules
 * found, what the agents did, what was refused, what was asked for, and what was
 * decided.
 *
 * Built from the case document's own records -- `steps`, `actions`, `reviews` --
 * plus any audit rows the case document does not carry (an audit row with no
 * matching receipt, such as a refusal recorded only on the trail). Rows are
 * de-duplicated by audit id, so a receipt and its audit row are one event.
 */
export function buildCaseTimeline(c: Case, audit: AuditRecord[] = []): TimelineEvent[] {
  const events: TimelineEvent[] = [];

  events.push({
    kind: "arrived",
    at: c.created_at ?? null,
    title: `Arrived${c.source ? ` from ${humaniseCode(String(c.source).toUpperCase()).toLowerCase()}` : ""}`,
    tone: "neutral",
  });

  const findings = c.validation?.findings ?? [];
  if (findings.length > 0) {
    const first = (c.steps ?? []).find((s) => s.at)?.at ?? c.created_at ?? null;
    for (const f of findings) {
      events.push({
        kind: "finding",
        at: first,
        title: `${humaniseCode(f.code)} — floor ${f.floor}`,
        detail: f.detail,
        tone: "bad",
      });
    }
  }

  for (const step of c.steps ?? []) {
    if (!step?.agent) continue;
    events.push({
      kind: "agent",
      at: step.at ?? null,
      title: `${humaniseAgent(step.agent)} ran${step.parse_error ? " (unreadable reply)" : ""}`,
      tone: "neutral",
    });
  }

  const seen = new Set<string>();
  for (const receipt of c.actions ?? []) {
    if (!receipt?.action) continue;
    if (receipt.audit_id) seen.add(receipt.audit_id);
    events.push(receiptEvent(receipt));
  }

  for (const review of c.reviews ?? []) {
    if (review) events.push(reviewEvent(review));
  }

  for (const row of audit) {
    if (!row?.action || seen.has(row.audit_id)) continue;
    // Human decisions are already on the line from `reviews`, with their note.
    if (row.action.startsWith("human_")) continue;
    seen.add(row.audit_id);
    const reason = row.detail?.gate_reason;
    events.push({
      kind: row.status === "denied" ? "refused" : "audit",
      at: row.at ?? null,
      title: `${actionLabel(row.action)}${row.status && row.status !== "done" ? ` (${row.status})` : ""}`,
      detail: row.status === "denied" && typeof reason === "string" ? reason : null,
      who: row.actor ?? null,
      tone: row.status === "denied" ? "bad" : "neutral",
    });
  }

  // Verification loop events (evidence.py)
  const v = c.verification;
  if (v) {
    for (const req of (v.requests ?? []) as EvidenceRequest[]) {
      const docs = (req.documents ?? []).join(", ");
      events.push({
        kind: "evidence_request",
        at: req.created_at ?? null,
        title: `Requested: ${docs || "documents"}`,
        detail: `Status: ${req.status}`,
        who: req.owner ?? null,
        tone: "neutral",
      });
    }
    for (const doc of (v.documents ?? []) as EvidenceDocument[]) {
      events.push({
        kind: "evidence_received",
        at: doc.received_at ?? null,
        title: `Received ${humaniseCode(doc.doc_type)}`,
        detail: doc.blocked ? "Blocked by Model Armor" : `sha256: ${(doc.sha256 ?? "").slice(0, 12)}...`,
        tone: doc.blocked ? "bad" : "good",
      });
    }
    for (const ev of (v.evaluations ?? []) as EvidenceEvaluation[]) {
      const cl = (ev.clarified ?? []).length;
      const un = (ev.unresolved ?? []).length;
      const co = (ev.contradictions ?? []).length;
      events.push({
        kind: "evidence_eval",
        at: ev.at ?? null,
        title: `Re-evaluated (v${ev.evidence_version}): ${cl} clarified, ${un} unresolved${co ? `, ${co} contradictions` : ""}`,
        detail: `Floor: ${ev.risk_floor} | Status: ${ev.status}`,
        tone: co > 0 ? "bad" : un > 0 ? "neutral" : "good",
      });
    }
    for (const apr of (v.approvals ?? []) as EvidenceApproval[]) {
      events.push({
        kind: "evidence_approval",
        at: apr.at ?? null,
        title: `${apr.action === "release" ? "Release" : "Block"} approved (v${apr.evidence_version})${apr.exception ? " as an exception" : ""}`,
        detail: apr.status === "SUPERSEDED"
          ? "Superseded by new evidence"
          : apr.exception
            ? `Waived: ${apr.exception.unresolved.map(humaniseCode).join(", ")}. Reason: ${apr.exception.reason}`
            : `Status: ${apr.status}`,
        who: apr.approver ?? null,
        tone: apr.status === "SUPERSEDED" || apr.exception ? "bad" : apr.action === "release" ? "good" : "neutral",
      });
    }
    for (const exe of (v.executions ?? []) as EvidenceExecution[]) {
      events.push({
        kind: "evidence_execution",
        at: exe.at ?? null,
        title: exe.status === "sent" ? `Executed (${exe.message_id ?? "no msg id"})` : `Execution ${exe.status}`,
        detail: exe.reason ?? null,
        who: exe.executor ?? null,
        tone: exe.status === "sent" ? "good" : exe.status === "denied" ? "bad" : "neutral",
      });
    }
  }

  // Stable on equal or missing timestamps, so findings stay grouped under arrival.
  return events
    .map((event, index) => ({ event, index }))
    .sort((a, b) => {
      const ta = a.event.at ? new Date(a.event.at).getTime() : Number.NaN;
      const tb = b.event.at ? new Date(b.event.at).getTime() : Number.NaN;
      if (Number.isNaN(ta) || Number.isNaN(tb) || ta === tb) return a.index - b.index;
      return ta - tb;
    })
    .map(({ event }) => event);
}

/** How many times a reviewer had to ask before the case could move. Mirrors worklist.information_rounds. */
export function informationRounds(c: Pick<Case, "reviews">): number {
  return (c.reviews ?? []).filter((r) => r?.action === "request_info").length;
}
