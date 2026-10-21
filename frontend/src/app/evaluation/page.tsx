"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, FlaskConical } from "lucide-react";

import { HelpDot } from "@/components/help/HelpDot";
import { PageHeading } from "@/components/layout/PageHeading";
import { ErrorState } from "@/components/layout/States";
import { Skeleton } from "@/components/ui/skeleton";
import {
  type CasePair,
  type CountedRate,
  type DebateCorpus,
  type Detection,
  type EvaluationSummary,
  type FraudFloorZero,
  type HsResult,
  type Interval,
  type Intervals,
  type OperatingCurve,
  type PipelineResult,
  type WorkloadEnd,
  fetchEvaluation,
} from "@/lib/api";
import { formatInterval, formatUsd, humaniseCode } from "@/lib/format";
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

const whole = (v: number | undefined | null) => (v == null ? "—" : v.toFixed(0));

/** F1 has no interval of its own; the three rates with counts behind them do. */
function intervalOf(intervals: Intervals | undefined, key: string): Interval | null {
  return intervals && key in intervals ? intervals[key as keyof Intervals] : null;
}

/**
 * A rate with its 95% interval beside it, "93.5% (90–96)".
 *
 * The bracket is omitted rather than shown empty when a report has no counts:
 * an interval that cannot be computed is not one of zero width.
 */
function Rate({
  value,
  interval,
  rangeClassName,
}: {
  value: number | undefined | null;
  interval?: Interval | null;
  rangeClassName?: string;
}) {
  return (
    <>
      {pct(value)}
      {interval ? (
        <span className={cn("text-faint", rangeClassName)}> ({formatInterval(interval)})</span>
      ) : null}
    </>
  );
}

/**
 * Held per real case at the two ends of the recall and false-alarm intervals.
 *
 * A worst case with no real case held at all (recall's interval reaching 0) has
 * no ratio, and is shown as unbounded rather than dropped: it is the widest
 * uncertainty there is, not the absence of one.
 */
function heldRange(best?: WorkloadEnd | null, worst?: WorkloadEnd | null): string | null {
  if (!best || !worst) return null;
  const top = worst.held_per_true_case == null ? "∞" : whole(worst.held_per_true_case);
  return `${whole(best.held_per_true_case)}–${top}`;
}

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
  const publicRules = byId.get("public_rules_all");
  const publicFull = byId.get("public_full_all");
  const hsHoldout = data.hs_classifier.holdout;
  const rulesCurve = data.operating_curve?.rules;
  const fraudFloor = data.model_comparison?.fraud_floor0;
  const debate = data.model_comparison?.debate_corpus;

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
      {after && <WorkloadCard results={[after, full, publicRules, publicFull]} />}
      {rulesCurve && <OperatingCurveCard curve={rulesCurve} />}
      {publicRules && publicFull && <PublicCases rules={publicRules} full={publicFull} />}
      {hsHoldout.length > 0 && <HsTable rows={hsHoldout} />}
      {(fraudFloor || debate) && <ModelComparisonCard fraudFloor={fraudFloor} debate={debate} />}
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
        <table className="w-full min-w-[34rem] text-left">
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
                  <td className="py-1.5 pr-3 text-right font-mono text-[12px] tabular-nums text-dim">
                    <Rate value={b} interval={intervalOf(before.intervals, key)} />
                  </td>
                  <td className="py-1.5 pr-3 text-right font-mono text-[12px] tabular-nums text-white">
                    <Rate value={a} interval={intervalOf(after.intervals, key)} />
                  </td>
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
            <dd className="mt-0.5 font-mono text-[18px] tabular-nums text-white">
              <Rate value={d[key]} interval={intervalOf(result.intervals, key)} rangeClassName="text-[11px]" />
            </dd>
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

const WORKLOAD_LABEL: Record<string, string> = {
  rules_holdout_after: "Rules, synthetic holdout",
  full_holdout_after: "Full pipeline, synthetic holdout",
  public_rules_all: "Rules, public cases",
  public_full_all: "Full pipeline, public cases",
};

/**
 * What a reviewer's queue looks like at the fraud rates a forwarder actually sees.
 *
 * The corpora are 20-80% fraud by construction, so their precision says nothing
 * about the queue. At 0.2% -- the Vietnam corridor's measured rate -- even a good
 * recall and a modest false-alarm rate put hundreds of honest shipments in front
 * of a reviewer for every real one. Shown because it is the number that decides
 * whether the product's value is "hold fewer" or "decide each hold faster", and
 * on this evidence it is the second.
 */
function WorkloadCard({ results }: { results: Array<PipelineResult | undefined> }) {
  const rows = results.filter((r): r is PipelineResult => Boolean(r?.workload?.length));
  if (!rows.length) return null;
  const prevalences = rows[0].workload!.map((w) => w.prevalence);
  return (
    <div className="bento-card p-4">
      <CardTitle help="evaluation.workload">Reviewer workload at real fraud rates</CardTitle>
      <p className="mt-1.5 max-w-3xl text-[12px] leading-relaxed text-dim">
        Shipments held per 1,000, and how many of those are real, if fraud were as rare
        as it is in practice. 0.2% is Vietnam Customs&rsquo; 2024 rate: a violation found
        in 29,849 of 16.84 million declarations. Computed from each report&rsquo;s recall and
        false-alarm rate, so it carries their small-sample limits: the range under each
        figure is shipments held per real case with both rates at the favourable, then the
        unfavourable, end of their 95% intervals.
      </p>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[34rem] text-left">
          <thead>
            <tr className="text-[10.5px] uppercase tracking-wide text-faint">
              <th className="py-1.5 pr-3 font-medium">Report</th>
              {prevalences.map((p) => (
                <th key={p} className="py-1.5 pr-3 text-right font-medium">
                  {(p * 100).toFixed(1)}% fraud
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t border-white/[0.05]">
                <td className="py-1.5 pr-3 text-[12px] text-white/85">{WORKLOAD_LABEL[r.id] ?? r.id}</td>
                {r.workload!.map((w) => {
                  const range = heldRange(w.best_case, w.worst_case);
                  return (
                    <td key={w.prevalence} className="py-1.5 pr-3 text-right font-mono text-[12px] tabular-nums">
                      <span className="text-white">{w.held_per_1000.toFixed(0)}</span>
                      <span className="text-faint"> held, {w.true_per_1000.toFixed(1)} real</span>
                      {w.held_per_true_case != null && (
                        <span className="block text-[10.5px] text-faint">
                          {whole(w.held_per_true_case)} per real case{range ? ` (${range})` : ""}
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11.5px] leading-relaxed text-faint">
        A screen that holds hundreds of honest shipments per real one is not saved by
        holding fewer: the cost is in deciding each one. That is what the case trace and
        the due-diligence dossier are for.
      </p>
    </div>
  );
}

/**
 * The rules arm at every review threshold, not only at the one in use.
 *
 * One recall and one false-alarm rate say how the current threshold does; the
 * neighbouring rows say what moving it would buy, in the unit the decision is
 * made in -- shipments held per real case at the measured fraud rate. The
 * threshold was set on dev, so dev sits beside holdout: a row that only looks
 * good on dev is a row that was fitted.
 */
function OperatingCurveCard({ curve }: { curve: OperatingCurve }) {
  const holdout = curve.splits.holdout;
  if (!holdout?.points.length) return null;
  const devAt = new Map((curve.splits.dev?.points ?? []).map((p) => [p.threshold, p]));
  return (
    <div className="bento-card p-4">
      <CardTitle help="evaluation.curve">Rules at every review threshold</CardTitle>
      <p className="mt-1.5 max-w-3xl text-[12px] leading-relaxed text-dim">
        What the deterministic layer would hold on the {holdout.cases_run} holdout cases if a
        shipment were held once its risk floor reached the threshold. Floors take a few fixed
        values, so each row stands for every threshold in its range; the one in use is{" "}
        {curve.review_threshold}. Held per real case is at {(curve.prevalence * 100).toFixed(1)}%
        fraud.
      </p>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[46rem] text-left">
          <thead>
            <tr className="text-[10.5px] uppercase tracking-wide text-faint">
              <th className="py-1.5 pr-3 font-medium">Threshold</th>
              <th className="py-1.5 pr-3 text-right font-medium">Recall</th>
              <th className="py-1.5 pr-3 text-right font-medium">False alarms</th>
              <th className="py-1.5 pr-3 text-right font-medium">Precision</th>
              <th className="py-1.5 pr-3 text-right font-medium">Held per real case</th>
              <th className="py-1.5 text-right font-medium">Dev recall / false alarms</th>
            </tr>
          </thead>
          <tbody>
            {holdout.points.map((p) => {
              const dev = devAt.get(p.threshold);
              const range = heldRange(p.best_case, p.worst_case);
              return (
                <tr
                  key={p.threshold}
                  className={cn("border-t border-white/[0.05]", p.current && "bg-brand/[0.06]")}
                >
                  <td className="py-1.5 pr-3 font-mono text-[12px] tabular-nums text-white/85">
                    {p.thresholds[0]}&ndash;{p.thresholds[1]}
                    {p.current && <span className="font-sans text-[10.5px] text-brand"> in use</span>}
                  </td>
                  <td className="py-1.5 pr-3 text-right font-mono text-[12px] tabular-nums text-white">
                    <Rate value={p.recall} interval={p.intervals?.recall} />
                  </td>
                  <td className="py-1.5 pr-3 text-right font-mono text-[12px] tabular-nums text-white">
                    <Rate value={p.false_positive_rate} interval={p.intervals?.false_positive_rate} />
                  </td>
                  <td className="py-1.5 pr-3 text-right font-mono text-[12px] tabular-nums text-dim">
                    <Rate value={p.precision} interval={p.intervals?.precision} />
                  </td>
                  <td className="py-1.5 pr-3 text-right font-mono text-[12px] tabular-nums text-white">
                    {whole(p.held_per_true_case)}
                    {range && <span className="text-faint"> ({range})</span>}
                  </td>
                  <td className="py-1.5 text-right font-mono text-[12px] tabular-nums text-dim">
                    {pct(dev?.recall)} / {pct(dev?.false_positive_rate)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11.5px] leading-relaxed text-faint">
        A false-alarm rate of 0% is {holdout.clean} clean cases with none held, not a screen
        that never holds an honest shipment; its range, and the held-per-real-case range that
        follows from it, is what a sample that size cannot rule out.
      </p>
    </div>
  );
}

const PAIR_VERDICT: Record<string, { label: string; tone: string }> = {
  separated: { label: "Separated", tone: "text-risk-clear" },
  both: { label: "Both held", tone: "text-risk-warn" },
  missed: { label: "Missed", tone: "text-risk-critical" },
  variance: { label: "Model variance", tone: "text-faint" },
  false_alarm: { label: "Honest held only", tone: "text-risk-critical" },
};

function pairVerdict(p: CasePair): keyof typeof PAIR_VERDICT {
  if (p.model_variance) return "variance";
  if (p.separated) return "separated";
  if (p.attack_flagged && p.honest_flagged) return "both";
  if (p.honest_flagged) return "false_alarm";
  return "missed";
}

/**
 * Nineteen public enforcement cases, each beside the honest trade it imitated.
 *
 * Read as pairs because only a pair says anything: holding both halves is holding
 * a commodity, not detecting a fraud. Every row links to the regulator's own page.
 */
function PublicCases({ rules, full }: { rules: PipelineResult; full: PipelineResult }) {
  const fullByRef = new Map((full.pairs ?? []).map((p) => [p.ref, p]));
  const count = (r: PipelineResult, v: keyof typeof PAIR_VERDICT) =>
    (r.pairs ?? []).filter((p) => pairVerdict(p) === v).length;
  return (
    <div className="bento-card p-4">
      <CardTitle help="evaluation.public">Public enforcement cases</CardTitle>
      <p className="mt-1.5 max-w-3xl text-[12px] leading-relaxed text-dim">
        {(rules.pairs ?? []).length} cases from BIS, OFAC, US Commerce, EPPO and OLAF, each
        rebuilt as the shipment the paperwork showed and paired with the honest trade it
        imitated. Rules alone separated {count(rules, "separated")}; the full pipeline
        separated {count(full, "separated")} and caught{" "}
        {full.detection.tp} of {full.detection.tp + full.detection.fn} frauds, for{" "}
        {formatUsd(full.cost?.total_usd)}.
      </p>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[44rem] text-left">
          <thead>
            <tr className="text-[10.5px] uppercase tracking-wide text-faint">
              <th className="py-1.5 pr-3 font-medium">Case</th>
              <th className="py-1.5 pr-3 font-medium">Rules</th>
              <th className="py-1.5 pr-3 font-medium">Full pipeline</th>
              <th className="py-1.5 font-medium">What fired on the fraud</th>
            </tr>
          </thead>
          <tbody>
            {(rules.pairs ?? []).map((p) => {
              const f = fullByRef.get(p.ref);
              const rv = PAIR_VERDICT[pairVerdict(p)];
              const fv = f ? PAIR_VERDICT[pairVerdict(f)] : null;
              return (
                <tr key={p.ref} className="border-t border-white/[0.05] align-top">
                  <td className="max-w-[22rem] py-1.5 pr-3 text-[11.5px] text-white/85">
                    {p.source_url ? (
                      <a href={p.source_url} target="_blank" rel="noreferrer" className="hover:underline">
                        {p.title ?? p.ref}
                      </a>
                    ) : (
                      p.title ?? p.ref
                    )}
                    <span className="block font-mono text-[10px] text-faint">
                      {p.ref} · {humaniseCode(p.typology)}
                    </span>
                  </td>
                  <td className={cn("py-1.5 pr-3 text-[11.5px]", rv.tone)}>{rv.label}</td>
                  <td className={cn("py-1.5 pr-3 text-[11.5px]", fv?.tone)}>{fv?.label ?? "—"}</td>
                  <td className="py-1.5 font-mono text-[10.5px] text-dim">
                    {(f?.attack_codes ?? p.attack_codes).map(humaniseCode).join(", ") || "nothing"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {full.notes?.length ? (
        <ul className="mt-3 space-y-0.5 text-[11px] leading-relaxed text-faint">
          {[...(rules.notes ?? []), ...full.notes].map((n) => (
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

/** "46/52 (88%) [77–95]": the count first, because a small count is the point. */
function Counted({ value }: { value: CountedRate }) {
  if (!value.of) return <>—</>;
  const ci = value.ci95;
  return (
    <>
      {value.count}/{value.of}{" "}
      <span className="text-faint">
        ({pct(value.rate)}
        {ci ? `, ${Math.round(ci[0] * 100)}–${Math.round(ci[1] * 100)}` : ""})
      </span>
    </>
  );
}

const MODEL_NAME: Record<string, string> = {
  nano: "Nemotron 3 Nano",
  super: "Nemotron 3 Super",
  ultra: "Nemotron 3 Ultra",
};

const usdSmall = (v: number | null | undefined) => (v == null ? "—" : `$${v.toFixed(4)}`);

function ModelComparisonCard({ fraudFloor, debate }: { fraudFloor?: FraudFloorZero; debate?: DebateCorpus }) {
  return (
    <div className="bento-card p-4">
      <CardTitle help="evaluation.models">Model choices, tested</CardTitle>

      {fraudFloor && (
        <div className="mt-3">
          <h4 className="text-[12px] font-medium text-white/85">Fraud screening where the rules see nothing</h4>
          <p className="mt-1 max-w-3xl text-[12px] leading-relaxed text-dim">
            Corpus cases the deterministic checks score 0, so the model is the only check. Recall is the
            share of frauds it flags; false alarms the share of honest shipments it holds. A reply that
            failed to parse counts as a hold, as the orchestrator treats it.
            {fraudFloor.partial ? " This report is partial." : ""}
          </p>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full min-w-[42rem] text-left">
              <thead>
                <tr className="text-[10.5px] uppercase tracking-wide text-faint">
                  <th className="py-1.5 pr-3 font-medium">Model</th>
                  <th className="py-1.5 pr-3 text-right font-medium">Frauds flagged</th>
                  <th className="py-1.5 pr-3 text-right font-medium">Honest held</th>
                  <th className="py-1.5 pr-3 text-right font-medium">Failed replies</th>
                  <th className="py-1.5 text-right font-medium">Cost per case</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(fraudFloor.results).map(([key, arm]) => (
                  <tr key={key} className="border-t border-white/[0.05]">
                    <td className="py-1.5 pr-3 text-[12px] text-white/85">{MODEL_NAME[key] ?? arm.model}</td>
                    <td className="py-1.5 pr-3 text-right font-mono text-[12px] tabular-nums text-white">
                      <Counted value={arm.all.recall_as_held} />
                    </td>
                    <td className="py-1.5 pr-3 text-right font-mono text-[12px] tabular-nums text-dim">
                      <Counted value={arm.all.false_alarm_as_held} />
                    </td>
                    <td className="py-1.5 pr-3 text-right font-mono text-[12px] tabular-nums text-dim">
                      <Counted value={arm.all.failed_reply_rate} />
                    </td>
                    <td className="py-1.5 text-right font-mono text-[12px] tabular-nums text-dim">
                      {usdSmall(arm.all.cost_per_case_usd)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {debate && (
        <div className="mt-4">
          <h4 className="text-[12px] font-medium text-white/85">The debate: which model argues disputed cases</h4>
          <p className="mt-1 max-w-3xl text-[12px] leading-relaxed text-dim">
            {debate.debated.fraud + debate.debated.honest} disputed cases ({debate.debated.fraud} fraud,{" "}
            {debate.debated.honest} honest), each debated by every model. A DISAGREE sends a held case to
            investigation; nothing the debate says can clear one. A model that tells fraud from honest trade
            would say DISAGREE far more often on the first than the second.
            {debate.partial ? " This report is partial." : ""}
          </p>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full min-w-[42rem] text-left">
              <thead>
                <tr className="text-[10.5px] uppercase tracking-wide text-faint">
                  <th className="py-1.5 pr-3 font-medium">Model</th>
                  <th className="py-1.5 pr-3 text-right font-medium">Reached a verdict</th>
                  <th className="py-1.5 pr-3 text-right font-medium">DISAGREE on fraud</th>
                  <th className="py-1.5 pr-3 text-right font-medium">DISAGREE on honest</th>
                  <th className="py-1.5 pr-3 text-right font-medium">Cost per debate</th>
                  <th className="py-1.5 text-right font-medium">Median time</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(debate.results).map(([key, arm]) => (
                  <tr key={key} className="border-t border-white/[0.05]">
                    <td className="py-1.5 pr-3 text-[12px] text-white/85">{MODEL_NAME[key] ?? arm.model}</td>
                    <td className="py-1.5 pr-3 text-right font-mono text-[12px] tabular-nums text-white">
                      <Counted value={arm.reached_a_verdict} />
                    </td>
                    <td className="py-1.5 pr-3 text-right font-mono text-[12px] tabular-nums text-dim">
                      <Counted value={arm.disagree_on_fraud} />
                    </td>
                    <td className="py-1.5 pr-3 text-right font-mono text-[12px] tabular-nums text-dim">
                      <Counted value={arm.disagree_on_honest} />
                    </td>
                    <td className="py-1.5 pr-3 text-right font-mono text-[12px] tabular-nums text-dim">
                      {usdSmall(arm.cost_per_debate_usd)}
                    </td>
                    <td className="py-1.5 text-right font-mono text-[12px] tabular-nums text-dim">
                      {arm.median_seconds == null ? "—" : `${arm.median_seconds.toFixed(1)} s`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

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
        <table className="w-full min-w-[42rem] text-left">
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
                <td className="py-1.5 pr-3 text-right font-mono text-[12px] tabular-nums text-white">
                  <Rate value={row.recall} interval={row.intervals?.recall} />
                </td>
                <td className="py-1.5 pr-3 text-right font-mono text-[12px] tabular-nums text-dim">
                  {row.arm === "rules" ? "—" : <Rate value={row.precision} interval={row.intervals?.precision} />}
                </td>
                <td className="py-1.5 pr-3 text-right font-mono text-[12px] tabular-nums text-dim">
                  <Rate value={row.false_positive_rate} interval={row.intervals?.false_positive_rate} />
                </td>
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
        <span className="font-mono">scripts/publish_benchmark.py</span>. The threshold sweep is{" "}
        <span className="font-mono">scripts/operating_curve.py</span>, which writes{" "}
        <span className="font-mono">data/operating_curve/rules.json</span>.
      </p>
    </div>
  );
}
