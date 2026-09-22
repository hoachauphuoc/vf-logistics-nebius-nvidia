"use client";

import { HelpDot } from "@/components/help/HelpDot";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { OrchestratorSnapshot } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Board KPIs.
 *
 * Every number here comes from `global_metrics()` -- a cached whole-collection
 * aggregation -- not from the fetched window, so the tiles describe the real
 * system at any case volume. That distinction is worth keeping visible: a tile
 * computed from `cases.length` would silently stop being true at 61 cases.
 */
export function PipelineKpis({
  snapshot,
  loading,
}: {
  snapshot: OrchestratorSnapshot | undefined;
  loading: boolean;
}) {
  if (loading && !snapshot) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-[4.75rem] rounded-xl bg-white/[0.04]" />
        ))}
      </div>
    );
  }

  const agent = snapshot?.agent;
  const suspended = agent?.state !== "READY";
  const worker = snapshot?.worker;

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <Tile
        label="In flight"
        value={snapshot?.in_flight ?? 0}
        helpId="kpi.in-flight"
        hint="Cases the worker will pick up: queued, fraud and compliance done, and investigated."
      />
      <Tile
        label="Awaiting human"
        value={snapshot?.awaiting_human ?? 0}
        helpId="kpi.awaiting-human"
        tone={(snapshot?.awaiting_human ?? 0) > 0 ? "warn" : "neutral"}
        hint="Awaiting a person, held for review and escalated. Nothing leaves these states without a named reviewer."
      />
      <Tile
        label="Agent calls"
        value={snapshot?.agent_calls ?? 0}
        helpId="kpi.agent-calls"
        hint="Model invocations across every case, exact rather than windowed."
      />
      <Tile
        label="Spend"
        value={`$${(snapshot?.estimated_cost_usd ?? 0).toFixed(4)}`}
        helpId="kpi.spend"
        hint="Estimated from token counts and per-model pricing. Rules-cleared cases contribute nothing, which is the point of the pre-filter."
      />
      {/*
        Readiness as a tile rather than a quiet badge. With no published
        delegation boundary the agent is SUSPENDED and *every* outcome stays a
        proposal -- nothing auto-clears, and each case lands on a human. That is
        correct fail-closed behaviour, but an operator watching a board where
        nothing ever clears needs to be told why, not left to infer it.
      */}
      <Tile
        label="Delegated authority"
        value={suspended ? "Suspended" : `v${agent?.boundary?.version ?? "?"}`}
        helpId="kpi.delegated-authority"
        tone={suspended ? "critical" : "clear"}
        hint={
          agent?.reason ??
          "Whether the agent may execute protected actions on its own."
        }
        sub={
          worker?.mode
            ? `worker: ${worker.mode}${worker.running ? "" : " (stopped)"}`
            : undefined
        }
      />
    </div>
  );
}

function Tile({
  label,
  value,
  hint,
  helpId,
  tone = "neutral",
  sub,
}: {
  label: string;
  value: string | number;
  hint: string;
  helpId?: string;
  tone?: "neutral" | "warn" | "critical" | "clear";
  sub?: string;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="bento-card cursor-default px-3.5 py-3">
          <div className="flex items-center gap-1.5">
            <p className="text-[11px] font-medium uppercase tracking-wide text-faint">
              {label}
            </p>
            {helpId && <HelpDot id={helpId} />}
          </div>
          <p
            className={cn(
              "mt-1 font-mono text-[20px] tabular-nums leading-none tracking-display",
              tone === "neutral" && "text-white",
              tone === "warn" && "text-risk-warn",
              tone === "critical" && "text-risk-critical",
              tone === "clear" && "text-risk-clear",
            )}
          >
            {value}
          </p>
          {sub && <p className="mt-1.5 truncate text-[10.5px] text-faint">{sub}</p>}
        </div>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="max-w-[22rem]">
        {hint}
      </TooltipContent>
    </Tooltip>
  );
}
