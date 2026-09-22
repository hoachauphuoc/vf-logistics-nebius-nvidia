"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { Loader2, ShieldAlert, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { HelpDot } from "@/components/help/HelpDot";
import { PageHeading } from "@/components/layout/PageHeading";
import { ErrorState } from "@/components/layout/States";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  fetchAttackLog,
  fetchModelConfig,
  fetchSnapshot,
  queryKeys,
  screenText,
} from "@/lib/api";
import { humaniseAgent } from "@/lib/format";
import { useTenant } from "@/lib/tenant-context";
import { cn } from "@/lib/utils";

export default function AgentConsolePage() {
  const { tenant } = useTenant();

  const config = useQuery({
    queryKey: queryKeys.modelConfig(tenant.id),
    queryFn: fetchModelConfig,
    retry: false,
  });

  /**
   * Worker health and per-agent economics come from the board snapshot.
   *
   * There is no `/worker/status` route -- worker state is part of `/health`,
   * which is unauthenticated, outside `/api/v1` and therefore not proxied. The
   * snapshot carries `worker` and `tokens_by_agent`, which is everything this
   * screen needs.
   *
   * `drain: false` matters: this screen must not advance the pipeline. Only the
   * Pipeline board does that, or the console becomes several competing advancers.
   */
  const snapshot = useQuery({
    queryKey: queryKeys.snapshot(tenant.id, false),
    queryFn: () => fetchSnapshot({ drain: false, limit: 60 }),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
    retry: false,
  });

  const attacks = useQuery({
    queryKey: queryKeys.attacks(tenant.id),
    queryFn: fetchAttackLog,
    retry: false,
  });

  if (config.isError && snapshot.isError) {
    return (
      <>
        <PageHeading title="Agent Console">
          Which models are running, what they cost, and what the input filters
          caught.
        </PageHeading>
        <ErrorState error={config.error ?? snapshot.error} />
      </>
    );
  }

  const worker = snapshot.data?.worker;
  const byAgent = snapshot.data?.tokens_by_agent ?? {};

  return (
    <>
      <PageHeading title="Agent Console">
        Which models are running, what they cost per agent, and what the input
        filters caught before any model read it.
      </PageHeading>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="bento-card p-4">
          <div className="flex items-center gap-1.5">
            <h3 className="text-[12px] font-medium text-white">Worker</h3>
            <HelpDot id="agents.worker" />
          </div>
          {snapshot.isLoading ? (
            <Skeleton className="mt-2 h-24 rounded-lg bg-white/[0.04]" />
          ) : (
            <>
              <p className="mt-1 text-[11.5px] leading-relaxed text-dim">
                {worker?.mode === "poll"
                  ? "Polling mode: the background loop drives the pipeline unattended, which needs --no-cpu-throttling and --min-instances=1 to stay alive between requests."
                  : "On-demand mode: request handlers advance the pipeline, so no always-on CPU is needed and the service can scale to zero."}
              </p>
              <dl className="code-surface mt-2 grid grid-cols-2 gap-x-4 gap-y-1.5 px-3 py-2.5">
                <Mono label="mode" value={worker?.mode ?? "—"} />
                <Mono label="running" value={worker?.running ? "yes" : "no"} />
                <Mono label="ticks" value={worker?.ticks ?? 0} />
                <Mono label="advanced" value={worker?.advanced ?? 0} />
                <Mono label="failed" value={worker?.failed ?? 0} />
                <Mono label="in flight" value={snapshot.data?.in_flight ?? 0} />
              </dl>
              {worker?.last_tick_error && (
                <p className="mt-2 rounded-md border border-risk-critical/30 bg-risk-critical/[0.07] px-2.5 py-2 font-mono text-[11px] leading-relaxed text-risk-critical">
                  {worker.last_tick_error}
                </p>
              )}
            </>
          )}
        </div>

        <div className="bento-card p-4">
          <div className="flex items-center gap-1.5">
            <h3 className="text-[12px] font-medium text-white">Models</h3>
            <HelpDot id="agents.models" />
          </div>
          {config.isError ? (
            <div className="mt-2">
              <ErrorState error={config.error} />
            </div>
          ) : config.isLoading ? (
            <Skeleton className="mt-2 h-24 rounded-lg bg-white/[0.04]" />
          ) : (
            <>
              <p className="mt-1 text-[11.5px] leading-relaxed text-dim">
                Read-only here. Changing the model is a service-wide setting
                rather than a per-tenant one, so it is not exposed to this
                console — one customer must not be able to move every other
                customer onto a different model.
              </p>
              <pre className="code-surface mt-2 max-h-56 overflow-auto whitespace-pre-wrap px-2.5 py-2 text-[11px] text-white/80 scrollbar-thin">
                {JSON.stringify(config.data, null, 2)}
              </pre>
            </>
          )}
        </div>

        <div className="bento-card p-4">
          <div className="flex items-center gap-1.5">
            <h3 className="text-[12px] font-medium text-white">Cost by agent</h3>
            <HelpDot id="agents.cost-by-agent" />
          </div>
          <p className="mt-1 text-[11.5px] leading-relaxed text-dim">
            Windowed over the cases on the board, not the whole collection — a
            per-agent breakdown would need a denormalised field per agent per
            case. The headline totals on the Pipeline board are exact.
          </p>
          {Object.keys(byAgent).length === 0 ? (
            <p className="mt-2 text-[11.5px] text-faint">
              No model has been called on the current window.
            </p>
          ) : (
            <ul className="mt-2 space-y-1">
              {Object.entries(byAgent)
                .sort((a, b) => b[1].input + b[1].output - (a[1].input + a[1].output))
                .map(([agent, t]) => (
                  <li
                    key={agent}
                    className="flex items-baseline justify-between gap-2 rounded border border-white/[0.06] px-2 py-1.5"
                  >
                    <span className="min-w-0 truncate text-[11.5px] text-white/85">
                      {humaniseAgent(agent)}
                    </span>
                    <span className="shrink-0 font-mono text-[11px] tabular-nums text-dim">
                      {t.calls} call(s) · {t.input.toLocaleString()}→
                      {t.output.toLocaleString()} tok
                    </span>
                  </li>
                ))}
            </ul>
          )}
        </div>

        <InjectionProbe />
      </div>

      <div className="mt-4 bento-card p-4">
        <h3 className="text-[12px] font-medium text-white">
          Injection patterns the filters know
        </h3>
        {attacks.isError ? (
          <div className="mt-2">
            <ErrorState error={attacks.error} />
          </div>
        ) : attacks.isLoading ? (
          <Skeleton className="mt-2 h-32 rounded-lg bg-white/[0.04]" />
        ) : (
          <>
            <p className="mt-1 text-[11.5px] leading-relaxed text-dim">
              {String(attacks.data?.pattern_count ?? 0)} pattern(s) and{" "}
              {String(attacks.data?.invisible_char_count ?? 0)} invisible
              character class(es), plus Model Armor if configured. The samples
              below are real payloads — paste one into the probe to see both
              stages run.
            </p>
            <ul className="mt-2 space-y-1.5">
              {(Array.isArray(attacks.data?.samples) ? attacks.data.samples : []).map(
                (s, i) => {
                  const sample = s as { label?: string; text?: string };
                  return (
                    <li
                      key={i}
                      className="rounded border border-white/[0.06] px-2 py-1.5"
                    >
                      <p className="text-[11.5px] text-white/85">{sample.label}</p>
                      <pre className="mt-0.5 whitespace-pre-wrap break-words font-mono text-[10.5px] leading-relaxed text-faint">
                        {sample.text}
                      </pre>
                    </li>
                  );
                },
              )}
            </ul>
          </>
        )}
      </div>
    </>
  );
}

/**
 * Run one text through both input filters by hand.
 *
 * Reports a single `blocked` field rather than two, matching the backend: either
 * stage is sufficient to stop the text, so showing them separately invites
 * reading a pass from one as an overall pass.
 */
function InjectionProbe() {
  const [text, setText] = useState("");

  const probe = useMutation({
    mutationFn: () => screenText(text),
  });

  const blocked = probe.data?.blocked === true;

  return (
    <div className="bento-card p-4">
      <div className="flex items-center gap-1.5">
        <h3 className="text-[12px] font-medium text-white">Injection probe</h3>
        <HelpDot id="agents.injection-probe" />
      </div>
      <p className="mt-1 text-[11.5px] leading-relaxed text-dim">
        Runs the pattern screen and Model Armor over text you supply, without
        creating a case. Nothing here reaches a model.
      </p>

      <Textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={4}
        placeholder="Paste a document excerpt or an injection payload"
        className="mt-2 border-white/10 bg-black/30 font-mono text-[11.5px]"
      />

      <Button
        size="sm"
        disabled={!text.trim() || probe.isPending}
        onClick={() => probe.mutate()}
        className="mt-2 h-8 text-[12px]"
      >
        {probe.isPending && <Loader2 className="mr-1.5 size-3.5 animate-spin" />}
        Screen it
      </Button>

      {probe.isError && (
        <div className="mt-3">
          <ErrorState error={probe.error} />
        </div>
      )}

      {probe.data && (
        <>
          <div
            className={cn(
              "mt-3 flex items-start gap-2 rounded-md border px-2.5 py-2",
              blocked
                ? "border-risk-critical/30 bg-risk-critical/[0.07]"
                : "border-risk-clear/25 bg-risk-clear/[0.06]",
            )}
          >
            {blocked ? (
              <ShieldAlert className="mt-[1px] size-3.5 shrink-0 text-risk-critical" aria-hidden />
            ) : (
              <ShieldCheck className="mt-[1px] size-3.5 shrink-0 text-risk-clear" aria-hidden />
            )}
            <p
              className={cn(
                "text-[11.5px] leading-relaxed",
                blocked ? "text-risk-critical" : "text-risk-clear",
              )}
            >
              {blocked
                ? "Blocked. At least one stage refused this text, which is enough — the document would never reach a model."
                : "Passed both stages. Note that passing is not a guarantee: these are filters, not proofs."}
            </p>
          </div>
          <pre className="code-surface mt-2 max-h-56 overflow-auto whitespace-pre-wrap px-2.5 py-2 text-[10.5px] text-white/75 scrollbar-thin">
            {JSON.stringify(probe.data, null, 2)}
          </pre>
        </>
      )}
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
