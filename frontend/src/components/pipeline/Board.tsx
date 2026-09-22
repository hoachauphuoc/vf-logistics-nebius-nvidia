"use client";

import { useState } from "react";

import { HelpDot } from "@/components/help/HelpDot";
import { CaseCard } from "@/components/pipeline/CaseCard";
import { COLUMN_PAGE_SIZE, type BoardBucket } from "@/lib/pipeline";
import { cn } from "@/lib/utils";

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
            <header className="mb-2 flex items-center justify-between gap-2 px-0.5">
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
              <span className="shrink-0 font-mono text-[11px] tabular-nums text-faint">
                {cases.length}
                {cases.length < total && (
                  <span className="text-white/25">/{total}</span>
                )}
              </span>
            </header>

            <div className="flex-1 space-y-2">
              {visible.length === 0 ? (
                <p className="px-1 py-6 text-center text-[11px] text-faint">
                  Nothing here
                </p>
              ) : (
                visible.map((c) => (
                  <CaseCard
                    key={c.case_id}
                    case={c}
                    onOpen={onOpen}
                    selected={c.case_id === selectedCaseId}
                  />
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
