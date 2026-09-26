"use client";

import { Inbox } from "lucide-react";
import { motion } from "framer-motion";
import { useState } from "react";

import { HelpDot } from "@/components/help/HelpDot";
import { CaseCard } from "@/components/pipeline/CaseCard";
import { COLUMN_PAGE_SIZE, type BoardBucket } from "@/lib/pipeline";
import type { CaseState } from "@/lib/types";
import { cn } from "@/lib/utils";

const COLUMN_TONE: Partial<Record<CaseState, string>> = {
  AUTO_CLEARED: "text-risk-clear",
  PENDING_HUMAN: "text-risk-warn",
  BLOCKED_BY_HUMAN: "text-risk-critical",
};

const COLUMN_ACCENT: Partial<Record<CaseState, string>> = {
  AUTO_CLEARED: "bg-risk-clear",
  PENDING_HUMAN: "bg-risk-warn",
  BLOCKED_BY_HUMAN: "bg-risk-critical",
};

export function Board({
  buckets,
  onOpen,
  selectedCaseId,
}: {
  buckets: BoardBucket[];
  onOpen: (caseId: string) => void;
  selectedCaseId: string | null;
}) {
  // Per-column expansion, held here rather than in the page: it is presentation
  // state with no meaning outside this component, and lifting it would make the
  // page re-render on a "show more" click.
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
      {buckets.map(({ column, cases, total }) => {
        const isExpanded = expanded[column.state] ?? false;
        const visible = isExpanded ? cases : cases.slice(0, COLUMN_PAGE_SIZE);
        const hidden = cases.length - visible.length;

        return (
          <section
            key={column.state}
            className="bento-card flex min-w-0 flex-col p-2.5"
          >
            <header className="mb-2 space-y-2 px-0.5">
              {COLUMN_ACCENT[column.state] && (
                <div className={cn("h-0.5 w-8 rounded-full opacity-60", COLUMN_ACCENT[column.state])} />
              )}
              <div className="flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-1.5">
                  <h2 className="truncate text-[12px] font-medium text-white/85">
                    {column.label}
                  </h2>
                  <HelpDot id={`state:${column.state}`} />
                </div>
              {/* "8/23" when the page is a subset of the column's real total,
                  a bare count when it is all of them. The denominator comes from
                  the exact aggregate, so it does not quietly become the page
                  size at higher volumes. */}
              <span
                className={cn(
                  "shrink-0 rounded-full px-1.5 font-mono text-[11px] tabular-nums",
                  cases.length > 0 && COLUMN_TONE[column.state]
                    ? cn(COLUMN_TONE[column.state], "bg-white/[0.06]")
                    : "text-faint",
                )}
              >
                {cases.length}
                {cases.length < total && (
                  <span className="text-white/25">/{total}</span>
                )}
              </span>
              </div>
            </header>

            <div className="flex-1 space-y-2">
              {visible.length === 0 ? (
                <div className="flex flex-col items-center gap-1.5 px-1 py-6">
                  <span className="grid size-7 place-items-center rounded-lg bg-white/[0.04] ring-1 ring-white/[0.08]">
                    <Inbox className="size-3.5 text-faint" aria-hidden />
                  </span>
                  <p className="text-[11px] text-faint">No cases</p>
                </div>
              ) : (
                visible.map((c, i) => (
                  <motion.div
                    key={c.case_id}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: Math.min(i * 0.04, 0.4), duration: 0.25 }}
                  >
                    <CaseCard
                      case={c}
                      onOpen={onOpen}
                      selected={c.case_id === selectedCaseId}
                    />
                  </motion.div>
                ))
              )}
            </div>

            {(hidden > 0 || isExpanded) && cases.length > COLUMN_PAGE_SIZE && (
              <button
                type="button"
                onClick={() =>
                  setExpanded((prev) => ({
                    ...prev,
                    [column.state]: !isExpanded,
                  }))
                }
                className={cn(
                  "mt-2 w-full rounded-md border border-white/[0.07] py-1.5",
                  "text-[11px] text-dim transition-colors",
                  "hover:border-white/15 hover:bg-white/[0.04] hover:text-white",
                )}
              >
                {isExpanded ? "Collapse" : `Show ${hidden} more`}
              </button>
            )}
          </section>
        );
      })}
    </div>
  );
}
