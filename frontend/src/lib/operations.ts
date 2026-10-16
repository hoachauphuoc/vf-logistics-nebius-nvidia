/**
 * Presentation rules for the operator screens: Today, a case's verification
 * page, and Outcomes.
 *
 * The grouping itself is the API's (worklist.py) -- these helpers only label it,
 * time it and arrange a case's history into one line of events. Kept out of the
 * components so the rules are testable, and, like lib/format.ts, nothing here
 * throws on absent input.
 */

import { actionLabel, caseStateLabel, formatUsd, humaniseAgent, humaniseCode, NO_VALUE, shortModelName } from "./format";
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

/**
 * The evaluation that describes the evidence the case holds NOW: the latest one at the
 * current evidence version. An older evaluation, or none, means new papers have arrived
 * since (or nothing has been evaluated yet) and nothing it says should be shown as the
 * state of the case. Null then.
 */
export function latestEvaluation(c: Pick<Case, "verification">): EvidenceEvaluation | null {
  const v = c.verification;
  if (!v) return null;
  const evaluations = (v.evaluations ?? []) as EvidenceEvaluation[];
  for (let i = evaluations.length - 1; i >= 0; i--) {
    if (evaluations[i]?.evidence_version === v.evidence_version) return evaluations[i];
  }
  return null;
}

/** An execution that was claimed but never confirmed, and whether its lease has run out. */
export interface ExecutionClaim {
  approval: EvidenceApproval;
  execution: EvidenceExecution;
  /** True once the lease has ended: the execution is interrupted, not running. */
  expired: boolean;
}

/**
 * The claim a case in EXECUTING is sitting on, or null when there is none to read.
 *
 * Mirrors evidence.execute_approval, which is the authority: an approval that is
 * CLAIMING on an EXECUTING case, with a "claiming" execution of its own whose
 * `claim_expires_epoch` (Unix SECONDS) is still in the future, is being worked on by
 * someone, and everything is refused 409 until the lease ends; after that the same
 * execution is resumed. A missing epoch counts as expired, as it does there.
 *
 * Only a hint for the screen. The browser clock is not the server's, so the server
 * answers the real question whenever somebody acts on it.
 */
export function executionClaim(
  c: Pick<Case, "state" | "verification">,
  now: number = Date.now(),
): ExecutionClaim | null {
  if (c.state !== "EXECUTING") return null;
  const v = c.verification;
  const approval = (v?.approvals ?? []).find((a) => a.status === "CLAIMING");
  if (!approval) return null;
  const execution = [...(v?.executions ?? [])]
    .reverse()
    .find((e) => e.approval_id === approval.approval_id && e.status === "claiming");
  if (!execution) return null;
  const leaseEndsMs = (Number(execution.claim_expires_epoch) || 0) * 1000;
  return { approval, execution, expired: now >= leaseEndsMs };
}

/**
 * "risk 55 (floor 45)": the score, and the floor when it is not the score. The score
 * is the higher of the model's and the floor, and good papers never lower the floor,
 * so after a clean re-evaluate the case still shows the same number and nothing said why.
 */
export function riskLabel(c: Pick<Case, "risk_score" | "reconciliation">): string | null {
  if (c.risk_score == null) return null;
  const floor = c.reconciliation?.risk_floor;
  return floor != null && floor !== c.risk_score
    ? `risk ${c.risk_score} (floor ${floor})`
    : `risk ${c.risk_score}`;
}

/** Whether the evidence on file contradicts the declaration. */
export function isContradicted(evaluation: EvidenceEvaluation | null | undefined): boolean {
  if (!evaluation) return false;
  return evaluation.status === "contradicted" || (evaluation.contradictions ?? []).length > 0;
}

/** What each kind of contradiction is about, for a label next to its sentence. */
export const CONTRADICTION_KIND_LABEL: Record<string, string> = {
  certificate_country: "Certificate of origin",
  input_origin: "Origin of the inputs",
  producer: "Producer",
};

/** "Origin inputs unverified, Certificate of origin": what a release exception waived. */
function waivedItems(exception: NonNullable<EvidenceApproval["exception"]>): string {
  const missing = (exception.unresolved ?? []).map(humaniseCode);
  const contradicted = (exception.contradictions ?? []).length > 0
    ? ["papers that contradict the declared origin"]
    : [];
  return [...missing, ...contradicted].join(", ") || "nothing recorded";
}

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
    const evaluation = latestEvaluation(c);
    for (const f of findings) {
      // A finding that asked for papers, once those papers are in and agree, is
      // answered. It still holds its floor (documents never lower one), so it stays
      // on the line, but it should not read as an open problem next to a case whose
      // evidence has been received and checked.
      const needed = f.measured?.documents_needed ?? [];
      const answered =
        evaluation != null &&
        !isContradicted(evaluation) &&
        needed.length > 0 &&
        needed.every((d) => (evaluation.clarified ?? []).includes(d));
      events.push({
        kind: "finding",
        at: first,
        title: `${humaniseCode(f.code)} — floor ${f.floor}${answered ? " — evidence received" : ""}`,
        detail: f.detail,
        tone: answered ? "neutral" : "bad",
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
        detail: doc.blocked
          ? "Blocked by Model Armor"
          : [
              `sha256: ${(doc.sha256 ?? "").slice(0, 12)}...`,
              doc.extraction?.model ? `Read by ${shortModelName(doc.extraction.model)}` : null,
            ]
              .filter(Boolean)
              .join(" · "),
        tone: doc.blocked ? "bad" : "good",
      });
    }
    for (const ev of (v.evaluations ?? []) as EvidenceEvaluation[]) {
      const cl = (ev.clarified ?? []).length;
      const un = (ev.unresolved ?? []).length;
      const contradictions = ev.contradictions ?? [];
      const co = contradictions.length;
      events.push({
        kind: "evidence_eval",
        at: ev.at ?? null,
        title: `Re-evaluated (v${ev.evidence_version}): ${cl} clarified, ${un} unresolved${co ? `, ${co} ${co === 1 ? "contradiction" : "contradictions"}` : ""}`,
        // Which paper disagrees is the thing a reviewer needs; a count is not enough.
        detail: [
          `Floor: ${ev.risk_floor} | Status: ${ev.status}`,
          ...contradictions.map((x) => `- ${x.detail}`),
        ].join("\n"),
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
            ? `Waived: ${waivedItems(apr.exception)}. Reason: ${apr.exception.reason}`
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
