"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, FlaskConical } from "lucide-react";

import { HelpDot } from "@/components/help/HelpDot";
import { PageHeading } from "@/components/layout/PageHeading";
import { ErrorState } from "@/components/layout/States";
import { Skeleton } from "@/components/ui/skeleton";
import {
  type Detection,
  type EvaluationSummary,
  type HsResult,
  type PipelineResult,
  fetchEvaluation,
} from "@/lib/api";
import { formatUsd, humaniseCode } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * What was measured, read from the reports the harnesses wrote.
 *
 * Every number on this page comes from GET /api/v1/evaluation, which serves the
 * files in data/benchmark_results/ and data/eval_results/ committed beside the
 * code that produced them. Nothing here is typed in. The caveats come from the
 * same response and are shown first, because a precision figure on a synthetic
 * corpus without that sentence beside it is a claim this project does not make.
 */

const pct = (v: number | undefined | null) =>
  v == null ? "—" : `${(v * 100).toFixed(1)}%`;

export default function EvaluationPage() {
  const query = useQuery({
    queryKey: ["evaluation"],
    queryFn: fetchEvaluation,
    retry: false,
    staleTime: 10 * 60_000,
  });

  return (
    <>
      <PageHeading title="Evaluation">
        What the pipeline catches and what it holds by mistake, measured on a fixed
        corpus with a dev/holdout split — including what the tuning gave up.
      </PageHeading>

      {query.isError && <ErrorState error={query.error} />}
      {query.isLoading && <Skeleton className="h-64 rounded-xl bg-white/[0.04]" />}
      {query.data && <Report data={query.data} />}
    </>
  );
}

function Report({ data }: { data: EvaluationSummary }) {
  const byId = new Map(data.pipeline.map((p) => [p.id, p]));
  const before = byId.get("rules_holdout_before");
  const after = byId.get("rules_holdout_after");
  const full = byId.get("full_holdout_after");
  const hsHoldout = data.hs_classifier.holdout;

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3 rounded-xl border border-risk-warn/30 bg-risk-warn/[0.06] px-4 py-3">
        <AlertTriangle className="mt-[2px] size-4 shrink-0 text-risk-warn" aria-hidden />
        <ul className="space-y-1 text-[12px] leading-relaxed text-dim">
          {data.caveats.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      </div>

      {before && after && <TuningComparison before={before} after={after} />}
      {full && <FullArm result={full} />}
      {hsHoldout.length > 0 && <HsTable rows={hsHoldout} />}
      <Sources results={data.pipeline} />
    </div>
  );
}

function CardTitle({ children, help }: { children: React.ReactNode; help?: string }) {
  return (
    <div className="flex items-center gap-2">
      <FlaskConical className="size-3.5 text-brand" aria-hidden />
      <h3 className="text-[11px] font-medium uppercase tracking-wider text-dim">{children}</h3>
      {help && <HelpDot id={help} />}
    </div>
  );
}

const ROWS: Array<[keyof Detection, string, "higher" | "lower"]> = [
  ["false_positive_rate", "Clean shipments held", "lower"],
  ["precision", "Precision", "higher"],
  ["recall", "Recall", "higher"],
  ["f1", "F1", "higher"],
];

function TuningComparison({ before, after }: { before: PipelineResult; after: PipelineResult }) {
  return (
    <div className="bento-card p-4">
      <CardTitle help="evaluation.tuning">Deterministic layer, before and after tuning</CardTitle>
      <p className="mt-1.5 max-w-3xl text-[12px] leading-relaxed text-dim">
        The rules alone, on the {after.cases_run} holdout cases that played no part
        in choosing the change. Two signals that separated nothing were turned
        into context rather than findings: freight above a per-consignment lane
        figure, and a trading record of 2–9 shipments.
      </p>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[28rem] text-left">
          <thead>
            <tr className="text-[10.5px] uppercase tracking-wide text-faint">
              <th className="py-1.5 pr-3 font-medium">Holdout</th>
              <th className="py-1.5 pr-3 text-right font-medium">Before</th>
              <th className="py-1.5 pr-3 text-right font-medium">After</th>
              <th className="py-1.5 text-right font-medium">Change</th>
            </tr>
          </thead>
          <tbody>
            {ROWS.map(([key, label, better]) => {
              const b = before.detection[key];
              const a = after.detection[key];
              const delta = a - b;
              const improved = better === "higher" ? delta > 0 : delta < 0;
              return (
                <tr key={key} className="border-t border-white/[0.05]">
                  <td className="py-1.5 pr-3 text-[12px] text-white/85">{label}</td>
                  <td className="py-1.5 pr-3 text-right font-mono text-[12px] tabular-nums text-dim">{pct(b)}</td>
                  <td className="py-1.5 pr-3 text-right font-mono text-[12px] tabular-nums text-white">{pct(a)}</td>
                  <td
                    className={cn(
                      "py-1.5 text-right font-mono text-[12px] tabular-nums",
                      Math.abs(delta) < 0.0005 ? "text-faint" : improved ? "text-risk-clear" : "text-risk-warn",
                    )}
                  >
                    {delta >= 0 ? "+" : ""}
                    {(delta * 100).toFixed(1)} pts
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11.5px] leading-relaxed text-faint">
        The recall given up is HS substitutions the rules cannot see anyway; the
        full pipeline below catches them with the HS classifier.
      </p>
    </div>
  );
}

function FullArm({ result }: { result: PipelineResult }) {
  const d = result.detection;
  const r = result.rules_only_baseline;
  return (
    <div className="bento-card p-4">
      <CardTitle help="evaluation.full">Full pipeline on holdout</CardTitle>
      <p className="mt-1.5 max-w-3xl text-[12px] leading-relaxed text-dim">
        Rules, the HS classifier and the zero-day radar through the real gate, on{" "}
        {result.cases_run} holdout cases, for {formatUsd(result.cost?.total_usd)} in
        model calls ({formatUsd(result.cost?.projected_usd_per_1000_cases)} per
        thousand cases).
      </p>
      <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {ROWS.map(([key, label]) => (
          <div key={key} className="rounded-lg border border-white/[0.07] bg-black/25 px-3 py-2">
            <dt className="text-[10.5px] uppercase tracking-wide text-faint">{label}</dt>
            <dd className="mt-0.5 font-mono text-[18px] tabular-nums text-white">{pct(d[key])}</dd>
            {r && (
              <dd className="text-[10.5px] text-faint">rules alone {pct(r[key])}</dd>
            )}
          </div>
        ))}
      </dl>
      {result.by_attack_type && (
        <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-[11.5px]">
          {Object.entries(result.by_attack_type)
            .filter(([attack]) => attack !== "None")
            .map(([attack, s]) => (
              <li key={attack} className="text-dim">
                {humaniseCode(attack)}:{" "}
                <span className="font-mono tabular-nums text-white/85">
                  {s.detected}/{s.cases}
                </span>
              </li>
            ))}
        </ul>
      )}
      {result.notes?.length ? (
        <ul className="mt-3 space-y-0.5 text-[11px] leading-relaxed text-faint">
          {result.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

const ARM_LABEL: Record<string, string> = {
  rules: "Rules only",
  base: "Nano, plain prompt",
  few_shot: "Nano, few-shot",
  cot_zero: "Nano, reasoning, no examples",
  cot: "Nano, reasoning with examples",
  cot_strict: "Nano, strict reasoning (production)",
  cot_ref: "Nano, with the reference table",
  teacher: "Nemotron Super, plain prompt",
};

function HsTable({ rows }: { rows: HsResult[] }) {
  return (
    <div className="bento-card p-4">
      <CardTitle help="evaluation.hs">HS classifier on unseen substitutions</CardTitle>
      <p className="mt-1.5 max-w-3xl text-[12px] leading-relaxed text-dim">
        Controlled goods declared under a benign heading, on the holdout set: {rows[0]?.n ?? 0}{" "}
        cases whose substitutions appear nowhere in the reference table the method
        was developed on. The rules cannot catch these at all — the declared code
        is the evader&rsquo;s choice.
      </p>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[34rem] text-left">
          <thead>
            <tr className="text-[10.5px] uppercase tracking-wide text-faint">
              <th className="py-1.5 pr-3 font-medium">Arm</th>
              <th className="py-1.5 pr-3 text-right font-medium">Recall</th>
              <th className="py-1.5 pr-3 text-right font-medium">Precision</th>
              <th className="py-1.5 pr-3 text-right font-medium">False alarms</th>
              <th className="py-1.5 text-right font-medium">Cost</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.arm}
                className={cn(
                  "border-t border-white/[0.05]",
                  row.arm === "cot_strict" && "bg-brand/[0.06]",
                )}
              >
                <td className="py-1.5 pr-3 text-[12px] text-white/85">{ARM_LABEL[row.arm] ?? row.arm}</td>
                <td className="py-1.5 pr-3 text-right font-mono text-[12px] tabular-nums text-white">{pct(row.recall)}</td>
                <td className="py-1.5 pr-3 text-right font-mono text-[12px] tabular-nums text-dim">{row.arm === "rules" ? "—" : pct(row.precision)}</td>
                <td className="py-1.5 pr-3 text-right font-mono text-[12px] tabular-nums text-dim">{pct(row.false_positive_rate)}</td>
                <td className="py-1.5 text-right font-mono text-[12px] tabular-nums text-dim">{formatUsd(row.total_cost_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Sources({ results }: { results: PipelineResult[] }) {
  return (
    <div className="bento-card p-4">
      <CardTitle>Every report behind this page</CardTitle>
      <ul className="mt-2 space-y-1">
        {results.map((r) => (
          <li key={r.id} className="flex flex-wrap items-baseline gap-x-3 text-[11.5px]">
            <span className="font-mono text-white/85">data/benchmark_results/{r.id}.json</span>
            <span className="text-faint">
              {r.arm} arm · {r.split} split · {r.cases_run} cases · {r.verifier}
              {r.generated_at ? ` · ${r.generated_at.slice(0, 10)}` : ""}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[11px] leading-relaxed text-faint">
        Rerun with <span className="font-mono">scripts/run_massive_benchmark.py --split holdout</span>{" "}
        (the rules arm is free) and publish with{" "}
        <span className="font-mono">scripts/publish_benchmark.py</span>.
      </p>
    </div>
  );
}
