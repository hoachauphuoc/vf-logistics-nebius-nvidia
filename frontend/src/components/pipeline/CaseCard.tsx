"use client";

import { CheckCircle2, Circle, FileText, Loader2 } from "lucide-react";

import {
  casePriority,
  isTerminal,
  slaStatus,
  type Priority,
  type SlaTone,
} from "@/lib/pipeline";
import { severityLabel } from "@/lib/format";
import type { Case } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Left border colour, by the case's raw state rather than its column. */
const STATE_ACCENT: Record<string, string> = {
  AUTO_CLEARED: "border-l-risk-clear",
  RELEASED_BY_HUMAN: "border-l-risk-clear",
  HELD_FOR_REVIEW: "border-l-risk-warn",
  PENDING_HUMAN: "border-l-risk-warn",
  ESCALATED: "border-l-risk-critical",
  BLOCKED_BY_HUMAN: "border-l-risk-critical",
  DEAD_LETTER: "border-l-risk-unknown",
};

const PRIORITY_CLASS: Record<Priority, string> = {
  CRITICAL: "badge-critical",
  HIGH: "badge-warn",
  MEDIUM: "badge-neutral",
  LOW: "badge-neutral",
};

const SLA_CLASS: Record<SlaTone, string> = {
  overdue: "text-risk-critical",
  urgent: "text-risk-warn",
  ok: "text-faint",
  done: "text-faint",
  none: "text-faint",
};

export function CaseCard({
  case: c,
  onOpen,
  selected,
}: {
  case: Case;
  onOpen: (caseId: string) => void;
  selected: boolean;
}) {
  const priority = casePriority(c);
  const sla = slaStatus(c);
  const active = !isTerminal(c.state);

  // `claimed`, not `worker_lock`. The old board read c.worker_lock, which is a
  // field no case has -- the store writes `claimed` when a worker takes the
  // lease. So the processing spinner never appeared on any card, and the state
  // the operator most wanted to see was the one state the board could not show.
  const processing = c.claimed === true && active;

  const risk = c.risk_score;
  const riskTone =
    risk == null
      ? "unknown"
      : risk >= 70
        ? "high"
        : risk >= 40
          ? "medium"
          : "low";

  // Route and value come off the *shipment*, not off the case. The old board
  // read c.origin_country / c.destination_country, which exist on neither, so
  // the Route line was blank on every card that had one.
  const s = c.shipment ?? {};
  const origin = typeof s.origin === "string" ? s.origin : null;
  const destination = typeof s.destination === "string" ? s.destination : null;
  const route = origin && destination ? `${origin} → ${destination}` : null;
  const value =
    typeof s.declared_value === "number"
      ? `$${s.declared_value.toLocaleString("en-US")}`
      : null;

  const notes: string[] = [];
  if (c.source === "document") notes.push("from document");
  // Attributed, not bare. `compliance_status` is the compliance agent's own
  // verdict, which is frequently not the case's disposition -- a case can carry
  // compliance_status BLOCKED while sitting in "Awaiting a person" because the
  // governance gate refused to execute the block, and another can carry CLEARED
  // while a reviewer has blocked it. Printing the bare word put "blocked" on a
  // queued card and "cleared" on a blocked one, which in a product whose entire
  // output is the words cleared and blocked is the worst available ambiguity.
  if (c.compliance_status) {
    notes.push(
      `compliance: ${c.compliance_status.toLowerCase().replace(/_/g, " ")}`,
    );
  }
  if (c.state === "HELD_FOR_REVIEW") notes.push("analyst assigned");
  if (c.state === "DEAD_LETTER") notes.push("dead letter");
  if (c.state === "BLOCKED_BY_HUMAN") notes.push("blocked by reviewer");
  if (c.state === "RELEASED_BY_HUMAN") notes.push("released by reviewer");

  return (
    <button
      type="button"
      onClick={() => onOpen(c.case_id)}
      className={cn(
        "w-full rounded-lg border border-l-2 border-white/[0.07] bg-black/30 p-2.5 text-left",
        "transition-all active:scale-[0.98] hover:border-white/15 hover:bg-white/[0.04]",
        STATE_ACCENT[c.state] ?? "border-l-white/20",
        selected && "border-glow border-white/25 bg-white/[0.06]",
      )}
    >
      <div className="flex items-start gap-1.5">
        <span className="mt-[2px] shrink-0 text-dim">
          {processing ? (
            <Loader2 className="size-3.5 animate-spin text-brand" aria-label="processing" />
          ) : active ? (
            <Circle className="size-3.5" aria-hidden />
          ) : (
            <CheckCircle2 className="size-3.5" aria-hidden />
          )}
        </span>
        <span className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-white/90">
          {c.shipment_id || c.case_id}
        </span>
        <span className={cn("badge-risk shrink-0 px-1.5 py-0 text-[10px]", PRIORITY_CLASS[priority])}>
          {severityLabel(priority)}
        </span>
      </div>

      {(route || value) && (
        <dl className="mt-2 space-y-0.5">
          {route && (
            <div className="flex gap-2 text-[11px]">
              <dt className="w-11 shrink-0 text-faint">Route</dt>
              <dd className="min-w-0 truncate text-white/75">{route}</dd>
            </div>
          )}
          {value && (
            <div className="flex gap-2 text-[11px]">
              <dt className="w-11 shrink-0 text-faint">Value</dt>
              <dd className="tabular-nums text-white/75">{value}</dd>
            </div>
          )}
        </dl>
      )}

      <p className="mt-1.5 truncate text-[11px] text-faint">
        {notes.join(" · ") || "awaiting first agent"}
      </p>

      <div className="mt-2 flex items-center gap-2">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.07]">
          <div
            className={cn(
              "h-full rounded-full transition-[width] duration-300",
              riskTone === "high" && "bg-risk-critical",
              riskTone === "medium" && "bg-risk-warn",
              riskTone === "low" && "bg-risk-clear",
              riskTone === "unknown" && "bg-risk-unknown",
            )}
            style={{ width: risk == null ? "4%" : `${Math.max(risk, 2)}%` }}
          />
        </div>
        <span
          className={cn(
            "w-7 shrink-0 text-right font-mono text-[12px] tabular-nums",
            riskTone === "high" && "text-risk-critical",
            riskTone === "medium" && "text-risk-warn",
            riskTone === "low" && "text-risk-clear",
            riskTone === "unknown" && "text-risk-unknown",
          )}
        >
          {risk ?? "—"}
        </span>
      </div>

      <div className="mt-1.5 flex items-center justify-between gap-2 text-[10.5px]">
        <span className={SLA_CLASS[sla.tone]}>{sla.text}</span>
        <span className="flex items-center gap-1 text-faint">
          {c.source === "document" && <FileText className="size-3" aria-hidden />}
          {relativeTime(c.created_at)}
        </span>
      </div>
    </button>
  );
}

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const seconds = Math.floor((Date.now() - then) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86_400)}d ago`;
}
