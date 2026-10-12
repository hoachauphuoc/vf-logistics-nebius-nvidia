"use client";

import { ArrowRight, Clock, MessageSquareMore, User } from "lucide-react";
import Link from "next/link";

import { caseStateLabel, formatRelative, humaniseCode } from "@/lib/format";
import { dueStatus, ownerLabel } from "@/lib/operations";
import type { WorkItem } from "@/lib/types";
import { cn } from "@/lib/utils";

const DUE_TONE: Record<string, string> = {
  overdue: "text-risk-critical",
  due_soon: "text-risk-warn",
  on_time: "text-dim",
  no_sla: "text-faint",
};

/**
 * One waiting case on the Today screen: who holds it, the next thing to do, and
 * how it stands against its SLA. The whole card links to the case's own page.
 */
export function WorkCard({ item, now }: { item: WorkItem; now?: number }) {
  const due = dueStatus(item, now);
  return (
    <Link
      href={`/cases/${encodeURIComponent(item.case_id)}`}
      className="group block rounded-lg border border-white/[0.08] bg-black/25 p-3 transition-colors hover:border-white/20 hover:bg-black/40"
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="truncate font-mono text-[12.5px] text-white">
          {item.shipment_id || item.case_id}
        </span>
        {item.risk_score != null && (
          <span className="shrink-0 font-mono text-[11px] tabular-nums text-dim">
            risk {item.risk_score}
          </span>
        )}
      </div>
      <p className="mt-0.5 text-[11px] text-faint">
        {caseStateLabel(item.state)}
        {item.top_finding && ` · ${humaniseCode(item.top_finding)}`}
      </p>

      {item.next_action && (
        <p className="mt-2 flex items-start gap-1.5 text-[12px] leading-snug text-white/85">
          <ArrowRight className="mt-[2px] size-3.5 shrink-0 text-brand" aria-hidden />
          <span>{item.next_action.text}</span>
        </p>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
        <span className="inline-flex items-center gap-1 text-dim">
          <User className="size-3" aria-hidden />
          {ownerLabel(item.owner)}
        </span>
        <span className={cn("inline-flex items-center gap-1", DUE_TONE[due.tone])}>
          <Clock className="size-3" aria-hidden />
          {due.text}
        </span>
        {item.information_rounds > 0 && (
          <span className="inline-flex items-center gap-1 text-dim">
            <MessageSquareMore className="size-3" aria-hidden />
            {item.information_rounds} {item.information_rounds === 1 ? "request" : "requests"}
          </span>
        )}
        {item.waiting_since && (
          <span className="text-faint">since {formatRelative(item.waiting_since)}</span>
        )}
      </div>
    </Link>
  );
}
