"use client";

import {
  Ban,
  Coins,
  Gauge,
  ShieldAlert,
  SlidersHorizontal,
} from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { NO_VALUE, formatLatency, formatUsd } from "@/lib/format";
import { unverifiedChecks } from "@/lib/risk";
import type { ComplianceAuditResponse, TenantUsageResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Props {
  audits: ComplianceAuditResponse[];
  usage: TenantUsageResponse | undefined;
  loading: boolean;
  /**
   * Set when the usage/billing read FAILED, as distinct from `usage` being absent
   * because it is still loading.
   *
   * Without this the two are the same state at render time -- `usage === undefined`,
   * `loading === false` -- and the money tiles used to resolve that with `?? 0`, so a
   * dead billing API produced "Token spend $0" in 26px semibold on a compliance
   * console. A real measured zero renders as `$0` too, so the two were indistinguishable.
   */
  usageError?: unknown;
}

export function KpiCards({ audits, usage, loading, usageError }: Props) {
  if (loading) {
    return (
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="bento-card p-4">
            <Skeleton className="h-3 w-24 bg-white/10" />
            <Skeleton className="mt-3 h-7 w-16 bg-white/10" />
            <Skeleton className="mt-2 h-3 w-32 bg-white/[0.07]" />
          </div>
        ))}
      </div>
    );
  }

  const blocked = audits.filter((a) => a.outcome === "BLOCKED").length;
  const held = audits.filter(
    (a) => a.outcome === "HELD_FOR_REVIEW" || a.outcome === "PENDING_HUMAN",
  ).length;
  const cleared = audits.filter((a) => a.outcome === "CLEARED").length;
  const errored = audits.filter((a) => a.outcome === "ERROR").length;

  // Audits resting on at least one check that did not return an answer. Counted
  // across every outcome, including cleared ones: a clearance with a gap in it
  // is exactly the case that needs surfacing, and it is invisible in the
  // outcome counts above.
  const withGaps = audits.filter((a) => unverifiedChecks(a.findings).length > 0);

  // Null rather than 0 when the read failed. `formatUsd`/`formatLatency` render null as
  // an em dash, which is the honest answer: the figure was not measured. Coercing to 0
  // here would defeat the guard those helpers exist to provide.
  const usageFailed = usageError != null;
  const rulesOnly = usageFailed ? null : usage?.cleared_by_rules ?? 0;
  const byAi = usageFailed ? null : usage?.cleared_by_ai ?? 0;
  // Clearances the *agent* reached on its own. Deliberately not `cleared`:
  // count_by_cleared_by() upstream counts only state == AUTO_CLEARED, so a
  // shipment a reviewer released is absent from it entirely -- not even in its
  // `unknown` bucket. The panel below therefore describes automatic clearances
  // and says so; labelling it "cleared of audited" made it read "1 cleared of 6"
  // on a window where two audits had in fact cleared, which is a number an
  // operator would reasonably have reported to a customer.
  const autoCleared = (rulesOnly ?? 0) + (byAi ?? 0);
  const byHuman = Math.max(cleared - autoCleared, 0);

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard
        icon={Ban}
        tone="critical"
        label="Blocked"
        value={String(blocked)}
        sub={`${held} held for review · ${cleared} cleared`}
      />

      <StatCard
        icon={ShieldAlert}
        tone={withGaps.length > 0 ? "warn" : "clear"}
        label="Incomplete checks"
        value={String(withGaps.length)}
        sub={
          withGaps.length === 0
            ? "every check returned a verdict"
            : `${withGaps.filter((a) => a.outcome === "CLEARED").length} of them cleared anyway`
        }
        hint={
          "Audits where at least one screening did not return an answer. A check " +
          "that did not run is not a clearance, so these are tracked separately " +
          "from the outcome counts rather than folded into them."
        }
      />

      <StatCard
        icon={Coins}
        tone="neutral"
        label="Token spend"
        value={formatUsd(usage?.estimated_cost_usd)}
        sub={
          usageFailed
            ? "Billing read failed — this is not a measured zero"
            : `${formatUsd(usage?.cost_per_call_usd)} per agent call · ${
                usage?.agent_calls ?? NO_VALUE
              } calls`
        }
        hint={
          "Computed from token counts at the per-model rate card. Excludes " +
          "search credits, egress and compute, which is why it is labelled an " +
          "estimate rather than an invoice."
        }
      />

      <StatCard
        icon={Gauge}
        tone="neutral"
        label="Mean latency"
        value={formatLatency(usage?.avg_latency_ms)}
        sub={`${errored} audit${errored === 1 ? "" : "s"} returned no verdict`}
      />

      {/* Wide card. The rules/AI split is the number that decides what an
          account costs to serve, so it gets room for the bar rather than being
          compressed into a third stat tile. */}
      <div className="bento-card border-glow p-4 sm:col-span-2 xl:col-span-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div className="flex items-center gap-2">
            <SlidersHorizontal className="size-3.5 text-dim" aria-hidden />
            <span className="text-[11px] font-medium uppercase tracking-wider text-dim">
              How clearances were reached
            </span>
          </div>
          <span className="text-[11px] text-faint">
            {cleared} of {audits.length} audited cleared
            {byHuman > 0 && `, ${autoCleared} of them automatically`}
          </span>
        </div>

        {usageFailed ? (
          <p className="mt-3 text-[13px] text-risk-warn">
            The billing read failed, so the rules-versus-model split cannot be shown.
            An empty bar here would read as &ldquo;no automatic clearances&rdquo;, which
            is a claim about the pipeline rather than about the request that failed.
          </p>
        ) : autoCleared === 0 ? (
          <p className="mt-3 text-[13px] text-faint">
            {cleared === 0
              ? "No clearances in this window."
              : `No automatic clearances. All ${cleared} went through a reviewer, which is the expensive path in staff time even where it is free in tokens.`}
          </p>
        ) : (
          <>
            <div className="mt-3 flex h-2 overflow-hidden rounded-full bg-white/[0.06]">
              <div
                className="bg-brand/70"
                style={{ width: `${((rulesOnly ?? 0) / autoCleared) * 100}%` }}
              />
              <div
                className="bg-indigo-400/60"
                style={{ width: `${((byAi ?? 0) / autoCleared) * 100}%` }}
              />
            </div>
            <div className="mt-2.5 flex flex-wrap gap-x-5 gap-y-1 text-[12px]">
              <LegendDot className="bg-brand/70">
                <span className="text-white">{rulesOnly ?? NO_VALUE}</span> by deterministic
                rules
                <span className="text-faint"> · no tokens spent</span>
              </LegendDot>
              <LegendDot className="bg-indigo-400/60">
                <span className="text-white">{byAi ?? NO_VALUE}</span> after the model layer
              </LegendDot>
              {/* Shown as a third figure rather than a third bar segment: the bar
                  is the unit-economics split between rules and models, and a human
                  release belongs to neither. Omitting it entirely is what made the
                  two numbers on this screen disagree. */}
              {byHuman > 0 && (
                <span className="text-dim">
                  <span className="text-white">{byHuman}</span> released by a
                  reviewer
                  <span className="text-faint"> · outside the automatic split</span>
                </span>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

const TONE_CLASS = {
  critical: "text-[#ff8080]",
  warn: "text-[#f7bc5c]",
  clear: "text-brand",
  neutral: "text-dim",
} as const;

function StatCard({
  icon: Icon,
  tone,
  label,
  value,
  sub,
  hint,
}: {
  icon: typeof Ban;
  tone: keyof typeof TONE_CLASS;
  label: string;
  value: string;
  sub: string;
  hint?: string;
}) {
  const body = (
    <div className="bento-card border-glow p-4">
      <div className="flex items-center gap-2">
        <Icon className={cn("size-3.5", TONE_CLASS[tone])} aria-hidden />
        <span className="text-[11px] font-medium uppercase tracking-wider text-dim">
          {label}
        </span>
      </div>
      <div className="tnum mt-2.5 text-[26px] font-semibold leading-none tracking-display text-white">
        {value}
      </div>
      <p className="mt-2 text-[12px] leading-snug text-faint">{sub}</p>
    </div>
  );

  if (!hint) return body;

  return (
    <Tooltip>
      <TooltipTrigger asChild>{body}</TooltipTrigger>
      <TooltipContent side="bottom" className="max-w-[22rem]">
        <p className="text-[12px] leading-relaxed">{hint}</p>
      </TooltipContent>
    </Tooltip>
  );
}

function LegendDot({
  className,
  children,
}: {
  className: string;
  children: React.ReactNode;
}) {
  return (
    <span className="flex items-center gap-1.5 text-dim">
      <span className={cn("size-2 shrink-0 rounded-full", className)} aria-hidden />
      {children}
    </span>
  );
}
