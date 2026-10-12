"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { useMemo, useState } from "react";

import { HelpDot } from "@/components/help/HelpDot";
import { PageHeading } from "@/components/layout/PageHeading";
import { ErrorState } from "@/components/layout/States";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchOutcomes, queryKeys } from "@/lib/api";
import { caseStateLabel, formatUsd, NO_VALUE } from "@/lib/format";
import { coverage, describeCostSpread, describeSpread, formatSpan } from "@/lib/operations";
import { useTenant } from "@/lib/tenant-context";
import type { Outcomes } from "@/lib/types";
import { cn } from "@/lib/utils";

const WINDOWS = [
  { id: "7d", label: "Last 7 days", days: 7 },
  { id: "30d", label: "Last 30 days", days: 30 },
  { id: "all", label: "All time", days: null },
] as const;

type WindowId = (typeof WINDOWS)[number]["id"];

/** The window's start, to the day, so the query key does not change every render. */
function sinceFor(id: WindowId): string | null {
  const days = WINDOWS.find((w) => w.id === id)?.days ?? null;
  if (days == null) return null;
  const start = new Date(Date.now() - days * 86_400_000);
  return start.toISOString().slice(0, 10);
}

/**
 * Outcomes: whether the work got done, and what it took.
 *
 * Every figure is the API's (worklist.build_outcomes), computed from what the
 * system recorded when it happened. A figure nobody measured is a dash with the
 * reason, never a zero -- a zero handling time would read as "no effort", which
 * is the opposite of "not measured".
 */
export default function OutcomesPage() {
  const { tenant } = useTenant();
  const [windowId, setWindowId] = useState<WindowId>("30d");
  const since = useMemo(() => sinceFor(windowId), [windowId]);

  const outcomes = useQuery({
    queryKey: queryKeys.outcomes(tenant.id, since),
    queryFn: () => fetchOutcomes({ since }),
    retry: false,
  });

  return (
    <>
      <PageHeading title="Outcomes">
        Cases resolved and how, what they took, and what is still held. Counted over
        cases that arrived in the window.
      </PageHeading>

      <div className="mb-4 flex flex-wrap items-center gap-1.5" role="group" aria-label="Window">
        {WINDOWS.map((w) => (
          <button
            key={w.id}
            type="button"
            aria-pressed={w.id === windowId}
            onClick={() => setWindowId(w.id)}
            className={cn(
              "h-7 rounded-md border px-2.5 text-[12px] transition-colors",
              w.id === windowId
                ? "border-brand/50 bg-brand/10 text-white"
                : "border-white/10 text-dim hover:border-white/25 hover:text-white",
            )}
          >
            {w.label}
          </button>
        ))}
      </div>

      {outcomes.isError ? (
        <ErrorState error={outcomes.error} />
      ) : outcomes.isLoading || !outcomes.data ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-28 rounded-xl bg-white/[0.04]" />
          ))}
        </div>
      ) : (
        <OutcomeTiles data={outcomes.data} />
      )}
    </>
  );
}

function Tile({
  label,
  help,
  value,
  sub,
}: {
  label: string;
  help: string;
  value: string;
  sub?: React.ReactNode;
}) {
  return (
    <div className="bento-card p-4">
      <div className="flex items-center gap-1.5">
        <p className="text-[11px] uppercase tracking-wide text-dim">{label}</p>
        <HelpDot id={help} />
      </div>
      <p
        className={cn(
          "mt-1.5 font-mono text-[20px] tabular-nums",
          value === NO_VALUE ? "text-faint" : "text-white",
        )}
      >
        {value}
      </p>
      {sub && <div className="mt-1 text-[11.5px] leading-relaxed text-dim">{sub}</div>}
    </div>
  );
}

function OutcomeTiles({ data }: { data: Outcomes }) {
  const by = data.resolved.by;
  const human = by.released_by_reviewer + by.blocked_by_reviewer;
  const held = Object.entries(data.held_now.by_state).filter(([, n]) => n > 0);

  return (
    <>
      {data.truncated && (
        <p className="mb-4 flex items-start gap-2 rounded-lg border border-risk-warn/30 bg-risk-warn/[0.07] px-3 py-2 text-[12px] text-risk-warn">
          <AlertTriangle className="mt-[1px] size-4 shrink-0" aria-hidden />
          More resolved cases than one read covers ({data.scanned} read). The figures are
          of the newest {data.scanned}.
        </p>
      )}

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Tile
          label="Resolved"
          help="outcomes.resolved"
          value={String(data.resolved.total)}
          sub={
            <>
              {by.cleared_by_rules} by the rules · {by.cleared_by_ai} by the agents ·{" "}
              {by.released_by_reviewer} released and {by.blocked_by_reviewer} blocked by a reviewer
            </>
          }
        />
        <Tile
          label="Arrival to resolution"
          help="outcomes.time_to_resolution"
          value={formatSpan(data.time_to_resolution_ms.median)}
          sub={describeSpread(data.time_to_resolution_ms)}
        />
        <Tile
          label="Human handling time"
          help="outcomes.handling"
          value={formatSpan(data.human_handling_ms.median)}
          sub={
            data.human_handling_ms.n > 0 ? (
              <>
                {describeSpread(data.human_handling_ms)} · measured on{" "}
                {coverage(data.human_handling_ms.n, human)} reviewer-decided cases
              </>
            ) : (
              "Not measured yet: no reviewer has had a resolved case's page open since recording began."
            )
          }
        />
        <Tile
          label="Requests for information"
          help="outcomes.rounds"
          value={String(data.information_rounds.total)}
          sub={
            data.information_rounds.mean_per_resolved == null
              ? NO_VALUE
              : `${data.information_rounds.cases_with_rounds} cases needed one · ${data.information_rounds.mean_per_resolved.toFixed(2)} per resolved case`
          }
        />
        <Tile
          label="Model cost per resolved case"
          help="outcomes.cost"
          value={formatUsd(data.cost_per_resolved_usd.mean)}
          sub={
            data.cost_per_resolved_usd.n > 0
              ? `mean · ${describeCostSpread(data.cost_per_resolved_usd)} · ${formatUsd(data.cost_per_resolved_usd.total)} in all. Nebius Token Factory only; web searches are counted, not priced.`
              : NO_VALUE
          }
        />
        <Tile
          label="Model latency per case"
          help="outcomes.latency"
          value={formatSpan(data.model_latency_ms.median)}
          sub={describeSpread(data.model_latency_ms)}
        />
        <Tile
          label="Held now"
          help="outcomes.held"
          value={String(data.held_now.total)}
          sub={
            held.length === 0
              ? "Nothing is waiting on a person."
              : held.map(([state, n]) => `${n} ${caseStateLabel(state).toLowerCase()}`).join(" · ")
          }
        />
        <Tile
          label="Actions refused"
          help="outcomes.refused"
          value={String(data.refused_actions.total)}
          sub="Agent actions the delegation boundary would not let run, from the audit trail."
        />
      </div>

      <p className="mt-4 text-[11.5px] leading-relaxed text-faint">
        Time waiting on the shipper: {NO_VALUE}. {data.external_wait_ms.reason}
      </p>
    </>
  );
}
