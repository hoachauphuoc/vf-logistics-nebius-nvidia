"use client";

import { Ban, Bot, CircleDot, FileCheck, FileQuestion, FileUp, Gavel, Inbox, RefreshCw, Rocket, ScrollText, ShieldCheck, Wrench } from "lucide-react";

import { formatClock, NO_VALUE } from "@/lib/format";
import type { TimelineEvent, TimelineKind } from "@/lib/operations";
import { cn } from "@/lib/utils";

const ICON: Record<TimelineKind, React.ElementType> = {
  arrived: Inbox,
  finding: CircleDot,
  agent: Bot,
  refused: Ban,
  request: FileQuestion,
  decision: Gavel,
  action: Wrench,
  audit: ScrollText,
  evidence_request: FileUp,
  evidence_received: FileCheck,
  evidence_eval: RefreshCw,
  evidence_approval: ShieldCheck,
  evidence_execution: Rocket,
};

const TONE: Record<NonNullable<TimelineEvent["tone"]>, string> = {
  good: "text-risk-clear ring-risk-clear/30 bg-risk-clear/10",
  bad: "text-risk-critical ring-risk-critical/30 bg-risk-critical/10",
  neutral: "text-dim ring-white/10 bg-white/[0.04]",
};

/**
 * A case as one ordered line: arrival, findings, agents, refusals, requests,
 * decisions. The order and the events are lib/operations.buildCaseTimeline's;
 * this only draws them.
 */
export function CaseTimeline({ events }: { events: TimelineEvent[] }) {
  if (events.length === 0) {
    return <p className="text-[12px] text-faint">Nothing has been recorded on this case.</p>;
  }
  return (
    <ol className="relative space-y-3 border-l border-white/[0.08] pl-5" aria-label="Case history">
      {events.map((event, index) => {
        const Icon = ICON[event.kind];
        return (
          <li key={`${event.kind}-${event.at ?? "none"}-${index}`} className="relative">
            <span
              className={cn(
                "absolute -left-[31px] top-0 grid size-[22px] place-items-center rounded-full ring-1",
                TONE[event.tone ?? "neutral"],
              )}
              aria-hidden
            >
              <Icon className="size-3" />
            </span>
            <div className="flex flex-wrap items-baseline justify-between gap-x-3">
              <p
                className={cn(
                  "text-[12.5px] font-medium",
                  event.tone === "bad" ? "text-risk-critical" : event.tone === "good" ? "text-risk-clear" : "text-white/90",
                )}
              >
                {event.title}
              </p>
              <time className="font-mono text-[10.5px] text-faint" dateTime={event.at ?? undefined}>
                {event.at ? formatClock(event.at) : NO_VALUE}
              </time>
            </div>
            {event.who && <p className="mt-0.5 font-mono text-[11px] text-dim">{event.who}</p>}
            {event.detail && (
              <p className="mt-0.5 whitespace-pre-wrap text-[11.5px] leading-relaxed text-dim">
                {event.detail}
              </p>
            )}
          </li>
        );
      })}
    </ol>
  );
}
