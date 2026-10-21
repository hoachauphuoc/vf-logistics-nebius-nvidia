import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CurvePoint, EvaluationSummary, PipelineResult } from "@/lib/api";

const payload = vi.hoisted(() => ({ current: null as unknown }));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  fetchEvaluation: vi.fn(async () => payload.current),
}));

import EvaluationPage from "./page";

/**
 * The Evaluation page shows each rate with the interval its sample size allows,
 * and the rules arm at every threshold. Both arrive from GET /api/v1/evaluation;
 * a backend that predates them must still render the figures it does send.
 */

const iv = (low: number, high: number, successes: number, n: number) => ({ low, high, successes, n });

function report(id: string, d: Partial<PipelineResult["detection"]>, extra: Partial<PipelineResult> = {}): PipelineResult {
  return {
    id,
    arm: "rules",
    split: "holdout",
    cases_run: 453,
    verifier: "test",
    detection: { precision: 0, recall: 0, f1: 0, false_positive_rate: 0, tp: 0, fp: 0, fn: 0, tn: 0, ...d },
    ...extra,
  };
}

function point(threshold: number, from: number, over: Partial<CurvePoint> = {}): CurvePoint {
  return {
    threshold, thresholds: [from, threshold], current: false,
    tp: 0, fp: 0, fn: 0, tn: 0, precision: null, recall: null, false_positive_rate: null,
    held_per_1000: 0, held_per_true_case: null, ...over,
  };
}

const AFTER = report(
  "rules_holdout_after",
  { precision: 0.9122, recall: 0.9346, f1: 0.9233, false_positive_rate: 0.3837, tp: 343, fp: 33, fn: 24, tn: 53 },
  {
    intervals: {
      precision: iv(0.8793, 0.9368, 343, 376),
      recall: iv(0.9045, 0.9557, 343, 367),
      false_positive_rate: iv(0.288, 0.4894, 33, 86),
    },
    workload: [{
      prevalence: 0.002, held_per_1000: 384.8, true_per_1000: 1.87, missed_per_1000: 0.13,
      precision_at_prevalence: 0.0049, held_per_true_case: 205.9,
      best_case: { recall: 0.9557, false_positive_rate: 0.288, precision_at_prevalence: 0.0066, held_per_true_case: 151.4 },
      worst_case: { recall: 0.9045, false_positive_rate: 0.4894, precision_at_prevalence: 0.0037, held_per_true_case: 271.0 },
    }],
  },
);

const CURRENT: EvaluationSummary = {
  pipeline: [
    report("rules_holdout_before", { precision: 0.841, recall: 0.951, f1: 0.8926, false_positive_rate: 0.7674 }),
    AFTER,
  ],
  hs_classifier: {
    pairs: [],
    holdout: [{
      arm: "cot_strict", model: "m", n: 24, precision: 1, recall: 0.9167, f1: 0.9565,
      false_positive_rate: 0, redirect_accuracy: 0.9091, total_cost_usd: 0.011, avg_latency_ms: 1,
      intervals: { precision: iv(0.7412, 1, 11, 11), recall: iv(0.6461, 0.9851, 11, 12), false_positive_rate: iv(0, 0.2425, 0, 12) },
    }],
  },
  operating_curve: {
    rules: {
      arm: "rules", review_threshold: 40, prevalence: 0.002,
      splits: {
        holdout: {
          cases_run: 453, attacks: 367, clean: 86,
          points: [
            point(50, 1, {
              current: true, recall: 0.9346, false_positive_rate: 0.3837, precision: 0.9122,
              held_per_true_case: 205.9, intervals: AFTER.intervals,
              best_case: AFTER.workload![0].best_case, worst_case: AFTER.workload![0].worst_case,
            }),
            // Holds nothing at all: no attack and no clean case reaches it.
            point(100, 51, {
              fn: 367, tn: 86, recall: 0, false_positive_rate: 0, precision: null, held_per_true_case: null,
              intervals: { precision: null, recall: iv(0, 0.0104, 0, 367), false_positive_rate: iv(0, 0.0428, 0, 86) },
              best_case: { recall: 0.0104, false_positive_rate: 0, precision_at_prevalence: 1, held_per_true_case: 1 },
              worst_case: { recall: 0, false_positive_rate: 0.0428, precision_at_prevalence: 0, held_per_true_case: null },
            }),
          ],
        },
        dev: {
          cases_run: 547, attacks: 433, clean: 114,
          points: [point(50, 1, { recall: 0.9353, false_positive_rate: 0.3509 }), point(100, 51)],
        },
      },
    },
  },
  caveats: ["synthetic corpus"],
};

const counted = (count: number, of: number, ci: [number, number]) => ({ count, of, rate: count / of, ci95: ci });
const FRAUD_ARM = (recall: ReturnType<typeof counted>, cost: number) => ({
  cases: 179, unusable_replies: 0, recall, false_alarm_rate: counted(75, 122, [0.52, 0.7]),
  recall_as_held: recall, false_alarm_as_held: counted(80, 127, [0.54, 0.71]),
  failed_reply_rate: counted(5, 179, [0.01, 0.06]), cost_per_case_usd: cost, median_seconds: 11,
});

const WITH_COMPARISON: EvaluationSummary = {
  ...CURRENT,
  model_comparison: {
    fraud_floor0: {
      kind: "fraud_floor_zero", question: "q", total_cost_usd: 0.25, notes: [],
      results: {
        nano: { model: "nano-id", holdout: FRAUD_ARM(counted(21, 24, [0.69, 0.96]), 0.00026), dev: FRAUD_ARM(counted(25, 28, [0.73, 0.96]), 0.00026), all: FRAUD_ARM(counted(46, 52, [0.77, 0.95]), 0.00026) },
        super: { model: "super-id", holdout: FRAUD_ARM(counted(20, 24, [0.64, 0.93]), 0.00114), dev: FRAUD_ARM(counted(27, 28, [0.82, 0.99]), 0.00114), all: FRAUD_ARM(counted(47, 52, [0.79, 0.96]), 0.00114) },
      },
    },
    debate_corpus: {
      kind: "debate_corpus", question: "q", total_cost_usd: 0.7, notes: [], debated: { fraud: 25, honest: 21 },
      results: {
        super: { model: "s", debates: 46, reached_a_verdict: counted(40, 46, [0.74, 0.94]), disagree_on_fraud: counted(16, 22, [0.52, 0.87]), disagree_on_honest: counted(13, 18, [0.49, 0.88]), cost_per_debate_usd: 0.002077, median_seconds: 6.4, mean_input_tokens: 5201 },
        ultra: { model: "u", debates: 46, reached_a_verdict: counted(37, 46, [0.67, 0.89]), disagree_on_fraud: counted(18, 19, [0.75, 0.99]), disagree_on_honest: counted(17, 18, [0.74, 0.99]), cost_per_debate_usd: 0.010776, median_seconds: 13.5, mean_input_tokens: 7281 },
      },
    },
  },
};

async function renderWith(data: EvaluationSummary) {
  payload.current = data;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <EvaluationPage />
    </QueryClientProvider>,
  );
  await screen.findByText(/before and after tuning/i);
  return document.body.textContent ?? "";
}

describe("the Evaluation page", () => {
  it("puts each rate's 95% interval beside it", async () => {
    const text = await renderWith(CURRENT);
    expect(text).toContain("93.5% (90–96)"); // holdout recall, 343 of 367
    expect(text).toContain("38.4% (28–49)"); // clean shipments held, 33 of 86
    expect(text).toContain("91.7% (64–99)"); // HS recall, 11 of 12
    expect(text).toContain("0.0% (0–25)"); // HS false alarms, 0 of 12
    expect(text).toContain("206 per real case (151–271)");
  });

  it("shows the operating curve with the threshold in use marked", async () => {
    const text = await renderWith(CURRENT);
    expect(screen.getByText(/rules at every review threshold/i)).toBeInTheDocument();
    expect(text).toContain("1–50 in use");
    expect(text).toContain("93.5% / 35.1%"); // dev beside holdout
    // A threshold that holds nothing has no ratio, and its worst case is shown as
    // unbounded rather than dropped.
    expect(text).toContain("— (1–∞)");
  });

  it("still renders the figures from a backend that sends no intervals or curve", async () => {
    const old: EvaluationSummary = {
      ...CURRENT,
      pipeline: CURRENT.pipeline.map((r) => ({ ...r, intervals: undefined, workload: undefined })),
      hs_classifier: { pairs: [], holdout: CURRENT.hs_classifier.holdout.map((r) => ({ ...r, intervals: undefined })) },
      operating_curve: undefined,
    };
    const text = await renderWith(old);
    expect(text).toContain("93.5%");
    expect(text).not.toContain("(90–96)");
    expect(screen.queryByText(/rules at every review threshold/i)).toBeNull();
  });

  it("shows the model comparisons with their counts and intervals", async () => {
    const text = await renderWith(WITH_COMPARISON);
    expect(screen.getByText(/model choices, tested/i)).toBeInTheDocument();
    expect(text).toContain("46/52 (88.5%, 77–95)"); // Nano, frauds flagged
    expect(text).toContain("47/52 (90.4%, 79–96)"); // Super
    expect(text).toContain("$0.0011"); // Super per case
    expect(text).toContain("18/19 (94.7%, 75–99)"); // Ultra DISAGREE on fraud
    expect(text).toContain("17/18 (94.4%, 74–99)"); // ... and on honest, about the same
    expect(text).toContain("$0.0108");
    expect(text).toContain("25 fraud, 21 honest");
  });

  it("omits the comparison card when the backend sends none", async () => {
    await renderWith(CURRENT);
    expect(screen.queryByText(/model choices, tested/i)).toBeNull();
  });
});
