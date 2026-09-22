"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Ban, Check, ChevronRight, ExternalLink } from "lucide-react";
import { useState } from "react";

import { ErrorState } from "@/components/layout/States";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchCase, queryKeys } from "@/lib/api";
import {
  actionLabel,
  auditStatusLabel,
  caseStateLabel,
  complianceStatusLabel,
  humaniseAgent,
  lowerFirst,
} from "@/lib/format";
import { useTenant } from "@/lib/tenant-context";
import type { ActionReceipt, Case, CaseStep } from "@/lib/types";
import { cn } from "@/lib/utils";

export function CaseTraceSheet({
  caseId,
  onOpenChange,
}: {
  caseId: string | null;
  onOpenChange: (open: boolean) => void;
}) {
  const { tenant } = useTenant();

  const query = useQuery({
    queryKey: queryKeys.case(tenant.id, caseId ?? ""),
    queryFn: () => fetchCase(caseId as string),
    // Fetched only while the sheet is open. The board holds slim cases and the
    // trace is ~13KB per case, so fetching it for every card on the board would
    // multiply the page weight by the number of cards for data nobody has asked
    // to see.
    enabled: caseId !== null,
    retry: false,
  });

  const c = query.data;

  return (
    <Sheet open={caseId !== null} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-full gap-0 overflow-y-auto border-white/[0.08] bg-slate-950/95 backdrop-blur-xl scrollbar-thin sm:max-w-xl"
      >
        <SheetHeader className="border-b border-white/[0.06] px-5 pb-4 pt-5">
          <SheetTitle className="font-mono text-[14px] text-white">
            {c?.shipment_id || caseId}
          </SheetTitle>
          <SheetDescription className="text-[12px] text-dim">
            {c
              ? `${caseStateLabel(c.state)} · ${c.steps?.length ?? 0} agent hop(s)`
              : "Loading the trace"}
          </SheetDescription>
        </SheetHeader>

        <div className="space-y-5 px-5 py-5">
          {query.isError && <ErrorState error={query.error} />}

          {query.isLoading && (
            <div className="space-y-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-20 rounded-lg bg-white/[0.04]" />
              ))}
            </div>
          )}

          {c && (
            <>
              <Verdict case={c} />
              <Economics case={c} />
              <Hops steps={c.steps ?? []} />
              <Evidence case={c} />
              <Receipts actions={c.actions ?? []} denials={c.gate_denials ?? []} />
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function Block({
  title,
  children,
  note,
}: {
  title: string;
  children: React.ReactNode;
  note?: string;
}) {
  return (
    <section>
      <h3 className="text-[11px] font-medium uppercase tracking-wide text-faint">
        {title}
      </h3>
      {note && <p className="mt-1 text-[11.5px] leading-relaxed text-dim">{note}</p>}
      <div className="mt-2">{children}</div>
    </section>
  );
}

/**
 * What was decided, and whether the model or the arithmetic decided it.
 *
 * `reconciliation.source` is the field that matters most and is easiest to miss:
 * "deterministic floor" means the model was overruled. A reviewer reading a risk
 * score of 100 needs to know whether an agent concluded that or whether a
 * sanctions match forced it, because only one of those is arguable.
 */
function Verdict({ case: c }: { case: Case }) {
  const rec = c.reconciliation;
  const vetoed = rec?.source === "deterministic floor" || rec?.vetoed === true;
  const denied = (c.gate_denials?.length ?? 0) > 0;

  return (
    <Block title="Verdict">
      <div className="space-y-2">
        <Row label="State" value={caseStateLabel(c.state)} />
        {c.decision?.outcome && (
          <Row
            label="Outcome"
            value={complianceStatusLabel(c.decision.outcome)}
          />
        )}
        {c.proposed_outcome && !c.decision?.outcome && (
          <Row
            label="Proposed"
            value={`${complianceStatusLabel(c.proposed_outcome)} — not executed`}
            tone="warn"
          />
        )}
        <Row
          label="Effective risk"
          value={c.risk_score ?? "not scored"}
          tone={
            c.risk_score == null
              ? "neutral"
              : c.risk_score >= 70
                ? "critical"
                : c.risk_score >= 40
                  ? "warn"
                  : "clear"
          }
        />
        {rec?.model_risk != null && (
          <Row label="Model alone" value={rec.model_risk} />
        )}
        {rec?.floor != null && <Row label="Rules floor" value={rec.floor} />}
        {vetoed && (
          <p className="rounded-md border border-risk-warn/30 bg-risk-warn/[0.07] px-2.5 py-2 text-[11.5px] leading-relaxed text-risk-warn">
            The deterministic floor overruled the model here. The model may raise
            risk but never lower it, so this score is arithmetic rather than
            judgement.
          </p>
        )}
        {denied && (
          <p className="rounded-md border border-risk-critical/30 bg-risk-critical/[0.07] px-2.5 py-2 text-[11.5px] leading-relaxed text-risk-critical">
            The delegation boundary refused{" "}
            {c.gate_denials?.map((d) => lowerFirst(actionLabel(d.action))).join(", ")}.
            The outcome above stayed a proposal and the case went to a human.
          </p>
        )}
        {c.review && (
          <div className="rounded-md border border-white/[0.08] bg-black/30 px-2.5 py-2">
            <p className="text-[11.5px] text-white/85">
              {c.review.action ? actionLabel(c.review.action) : "Reviewed"} by{" "}
              {c.review.reviewer}
            </p>
            {c.review.note && (
              <p className="mt-0.5 text-[11px] leading-relaxed text-dim">
                {c.review.note}
              </p>
            )}
          </div>
        )}
      </div>
    </Block>
  );
}

/** Per-case cost, from the denormalised rollups rather than summed here. */
function Economics({ case: c }: { case: Case }) {
  const calls = c._agent_calls ?? 0;
  const cost = c._estimated_cost_usd ?? 0;

  return (
    <Block
      title="Economics"
      note={
        calls === 0
          ? "No model was called. The deterministic pre-filter resolved this case on its own, which is what it exists to do."
          : undefined
      }
    >
      <dl className="code-surface grid grid-cols-2 gap-x-4 gap-y-1.5 px-3 py-2.5">
        <Mono label="agent calls" value={calls} />
        <Mono label="cost" value={`$${cost.toFixed(6)}`} />
        <Mono label="input tokens" value={(c._input_tokens ?? 0).toLocaleString()} />
        <Mono label="output tokens" value={(c._output_tokens ?? 0).toLocaleString()} />
        <Mono
          label="latency"
          value={c._sum_latency_ms != null ? `${c._sum_latency_ms} ms` : "—"}
        />
        <Mono label="source" value={c.source ?? "—"} />
      </dl>
    </Block>
  );
}

/** Each agent hop, expandable to the exact text sent and returned. */
function Hops({ steps }: { steps: CaseStep[] }) {
  const [open, setOpen] = useState<number | null>(null);

  if (steps.length === 0) {
    return (
      <Block title="Agent hops">
        <p className="text-[12px] text-dim">
          Nothing has run yet. The case is queued for the first agent.
        </p>
      </Block>
    );
  }

  return (
    <Block title="Agent hops">
      <ol className="space-y-1.5">
        {steps.map((step, i) => {
          const isOpen = open === i;
          const hasDetail = Boolean(step.prompt || step.raw_response || step.result);

          return (
            <li key={`${step.agent}-${i}`} className="rounded-lg border border-white/[0.07] bg-black/25">
              <button
                type="button"
                onClick={() => setOpen(isOpen ? null : i)}
                disabled={!hasDetail}
                className={cn(
                  "flex w-full items-center gap-2 px-2.5 py-2 text-left",
                  hasDetail && "hover:bg-white/[0.03]",
                )}
              >
                <span className="w-4 shrink-0 font-mono text-[10.5px] text-faint">
                  {i + 1}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[12px] text-white/90">
                    {humaniseAgent(step.agent)}
                    {step.parse_error && (
                      <AlertTriangle
                        className="ml-1.5 inline size-3 text-risk-warn"
                        aria-label="the model's reply did not parse"
                      />
                    )}
                  </span>
                  <span className="block truncate font-mono text-[10.5px] text-faint">
                    {step.model ?? "no model"}
                    {step.latency_ms != null && ` · ${step.latency_ms} ms`}
                    {step.input_tokens != null &&
                      ` · ${step.input_tokens}→${step.output_tokens ?? 0} tok`}
                  </span>
                </span>
                {hasDetail && (
                  <ChevronRight
                    className={cn(
                      "size-3.5 shrink-0 text-faint transition-transform",
                      isOpen && "rotate-90",
                    )}
                    aria-hidden
                  />
                )}
              </button>

              {isOpen && (
                <div className="space-y-2 border-t border-white/[0.06] px-2.5 py-2">
                  {step.prompt && (
                    <Payload label="Prompt sent" text={step.prompt} />
                  )}
                  {step.raw_response && (
                    <Payload label="Raw reply" text={step.raw_response} />
                  )}
                  {step.result && (
                    <Payload
                      label="Parsed result"
                      text={JSON.stringify(step.result, null, 2)}
                    />
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </Block>
  );
}

function Payload({ label, text }: { label: string; text: string }) {
  return (
    <div>
      <p className="mb-1 text-[10.5px] uppercase tracking-wide text-faint">
        {label}
      </p>
      <pre className="code-surface max-h-56 overflow-auto whitespace-pre-wrap break-words px-2.5 py-2 text-white/80 scrollbar-thin">
        {text}
      </pre>
    </div>
  );
}

/** Tavily searches and the citations they returned. */
function Evidence({ case: c }: { case: Case }) {
  const searches = c.tavily_searches ?? [];
  if (searches.length === 0 && !c.route_intelligence) return null;

  return (
    <Block
      title="Live evidence"
      note="Public web search run at decision time. The citations are what a customs authority would be shown, so they are reproduced rather than summarised."
    >
      {c.route_intelligence && (
        <pre className="code-surface mb-2 max-h-40 overflow-auto whitespace-pre-wrap px-2.5 py-2 text-white/80 scrollbar-thin">
          {c.route_intelligence}
        </pre>
      )}
      <ul className="space-y-1.5">
        {searches.map((s, i) => {
          const urls = Array.isArray(s.urls) ? (s.urls as string[]) : [];
          return (
            <li
              key={i}
              className="rounded-lg border border-white/[0.07] bg-black/25 px-2.5 py-2"
            >
              <p className="text-[11.5px] text-white/85">
                {String(s.type ?? "search")}
                <span className="ml-1.5 text-faint">
                  {String(s.results ?? 0)} result(s)
                </span>
              </p>
              {urls.map((url) => (
                <a
                  key={url}
                  href={url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="mt-1 flex items-center gap-1 truncate text-[11px] text-brand hover:underline"
                >
                  <ExternalLink className="size-3 shrink-0" aria-hidden />
                  <span className="truncate">{url}</span>
                </a>
              ))}
            </li>
          );
        })}
      </ul>
    </Block>
  );
}

/**
 * Action receipts, including refusals.
 *
 * A denial is recorded exactly like a success upstream, and it is rendered that
 * way here: an action the boundary refused is as much a governance fact as one
 * that was taken, and a console that showed only successes would be unauditable
 * in the one direction that matters.
 */
function Receipts({
  actions,
  denials,
}: {
  actions: ActionReceipt[];
  denials: Array<{ action: string; reason?: string | null }>;
}) {
  if (actions.length === 0 && denials.length === 0) return null;

  return (
    <Block title="Actions">
      <ul className="space-y-1.5">
        {actions.map((a, i) => (
          <li
            key={a.audit_id ?? `${a.action}-${i}`}
            className="flex items-start gap-2 rounded-lg border border-white/[0.07] bg-black/25 px-2.5 py-2"
          >
            <span className="mt-[2px] shrink-0">
              {a.status === "done" ? (
                <Check className="size-3.5 text-risk-clear" aria-hidden />
              ) : a.status === "denied" ? (
                <Ban className="size-3.5 text-risk-critical" aria-hidden />
              ) : (
                <AlertTriangle className="size-3.5 text-risk-warn" aria-hidden />
              )}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-[12px] text-white/90">
                {actionLabel(a.action)}
              </span>
              <span className="block text-[11px] leading-relaxed text-dim">
                {auditStatusLabel(a.status)}
                {a.gate_reason ? ` — ${a.gate_reason}` : ""}
                {typeof a.detail?.gate_reason === "string"
                  ? ` — ${a.detail.gate_reason}`
                  : ""}
                {typeof a.detail?.reason === "string"
                  ? ` — ${a.detail.reason}`
                  : ""}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </Block>
  );
}

function Row({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string | number;
  tone?: "neutral" | "warn" | "critical" | "clear";
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-[11.5px] text-faint">{label}</span>
      <span
        className={cn(
          "text-right font-mono text-[12px] tabular-nums",
          tone === "neutral" && "text-white/85",
          tone === "warn" && "text-risk-warn",
          tone === "critical" && "text-risk-critical",
          tone === "clear" && "text-risk-clear",
        )}
      >
        {value}
      </span>
    </div>
  );
}

function Mono({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="text-faint">{label}</dt>
      <dd className="tabular-nums text-white/85">{value}</dd>
    </div>
  );
}
