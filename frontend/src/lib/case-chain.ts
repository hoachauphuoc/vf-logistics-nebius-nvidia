import { actionLabel, humaniseAgent, lowerFirst, shortModelName } from "./format";
import type { Case } from "./types";

/**
 * A case's whole journey as one ordered chain: every hop that ran, with what ran
 * it, then the delegation gate, then the actions that were taken or refused.
 *
 * The trace already held all of this, split across "Agent hops" and "Actions"
 * further down the sheet, so the one thing this product is -- a multi-step
 * workflow that chains screening, several models, live search, a policy gate and
 * real tools -- could only be seen by scrolling and assembling it yourself.
 *
 * Pure and total: a case with no steps returns an empty chain, and an unknown
 * agent is labelled from its own name rather than dropped.
 */

export type ChainStatus = "done" | "blocked" | "denied" | "skipped" | "failed";

export interface ChainLink {
  key: string;
  label: string;
  /** What ran this link: a model, Model Armor, the rules, the boundary, a tool. */
  engine: string;
  status: ChainStatus;
  /** One short line: latency, sources read, why it was refused. */
  detail: string | null;
}

/** Names that read better than the humanised agent id. */
const AGENT_LABEL: Record<string, string> = {
  model_armor: "Model Armor screen",
  document_intake: "Document intake",
  sql_prefilter: "Rules pre-filter",
  hs_classifier: "HS classifier",
  zero_day: "Zero-day radar",
  fraud_detection: "Fraud detection",
  compliance: "Compliance",
  investigation: "Investigation",
  auto_debate: "Senior Auditor debate",
  debate: "Senior Auditor debate (requested)",
};

function engineFor(agent: string, model: string | null | undefined): string {
  if (agent === "model_armor" || model === "google-cloud-model-armor") return "Google Model Armor";
  if (agent === "sql_prefilter") return "Deterministic rules, no model";
  if (!model) return "no model";
  // shortModelName turns the three Nemotron ids into "Nemotron 3 Nano/Super/Ultra"
  // and leaves anything else (MiniCPM-V) as its own name.
  const short = shortModelName(model);
  return short.startsWith("Nemotron") ? `NVIDIA ${short}` : short;
}

function blockedByArmor(result: Record<string, unknown> | null | undefined): boolean {
  const armor = (result?.model_armor ?? null) as { blocked?: boolean } | null;
  return armor?.blocked === true;
}

export function buildChain(c: Pick<Case, "steps" | "actions" | "gate_denials">): ChainLink[] {
  const links: ChainLink[] = [];

  (c.steps ?? []).forEach((step, i) => {
    const agent = step.agent ?? "unknown";
    const sources = (step.external_search_results ?? []).filter((r) => r?.url).length;
    const parts: string[] = [];
    if (step.latency_ms != null && step.latency_ms > 0) {
      parts.push(step.latency_ms >= 1000 ? `${(step.latency_ms / 1000).toFixed(1)} s` : `${step.latency_ms} ms`);
    }
    if (sources > 0) parts.push(`Tavily: ${sources} source${sources === 1 ? "" : "s"}`);

    const blocked = blockedByArmor(step.result);
    links.push({
      key: `step-${i}-${agent}`,
      label: AGENT_LABEL[agent] ?? humaniseAgent(agent),
      engine: engineFor(agent, step.model),
      status: blocked ? "blocked" : step.parse_error ? "failed" : "done",
      detail: blocked ? "Stopped before any model read it" : parts.join(" · ") || null,
    });
  });

  const denials = c.gate_denials ?? [];
  const actions = c.actions ?? [];

  if (denials.length > 0 || actions.length > 0) {
    links.push({
      key: "gate",
      label: "Delegation gate",
      engine: "Published boundary",
      status: denials.length > 0 ? "denied" : "done",
      detail:
        denials.length > 0
          ? `Refused: ${denials.map((d) => lowerFirst(actionLabel(d.action))).join(", ")}`
          : "Every action inside the boundary",
    });
  }

  actions.forEach((a, i) => {
    const status: ChainStatus =
      a.status === "done" || a.status === "denied" || a.status === "skipped" || a.status === "failed"
        ? a.status
        : "done";
    links.push({
      key: `action-${i}-${a.action}`,
      label: actionLabel(a.action),
      engine: "Tool",
      status,
      detail: null,
    });
  });

  return links;
}
