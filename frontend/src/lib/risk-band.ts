import type { Case } from "./types";

/**
 * One definition of the score bands, for every screen that colours a 0-100 risk
 * score. (lib/risk.ts presents an audit VERDICT; this is about the number.)
 *
 * The board and the case trace called 70 "high" while the Risk Radar table
 * waited until 80, so the same case could be red on one screen and amber on the
 * next. Below 40 is low, 70 and above is high.
 */
export type RiskBand = "high" | "medium" | "low" | "unknown";

export const RISK_HIGH = 70;
export const RISK_MEDIUM = 40;

export function riskBand(score: number | null | undefined): RiskBand {
  if (score == null || Number.isNaN(score)) return "unknown";
  if (score >= RISK_HIGH) return "high";
  if (score >= RISK_MEDIUM) return "medium";
  return "low";
}

/** Text colour per band, from the theme tokens rather than hard-coded hex. */
export const RISK_TEXT: Record<RiskBand, string> = {
  high: "text-risk-critical",
  medium: "text-risk-warn",
  low: "text-risk-clear",
  unknown: "text-risk-unknown",
};

/** Fill colour per band, for bars and dots. */
export const RISK_FILL: Record<RiskBand, string> = {
  high: "bg-risk-critical",
  medium: "bg-risk-warn",
  low: "bg-risk-clear",
  unknown: "bg-risk-unknown",
};

/**
 * Whether intake caught the document trying to instruct the agents: the
 * injection screen, Model Armor, or a field the document is never allowed to set.
 *
 * The same signals governance.py counts toward the injection-rate drift metric,
 * so a card tagged here is a case that metric counted.
 */
export function injectionCaught(c: Pick<Case, "input_security">): boolean {
  const security = (c.input_security ?? {}) as {
    injection_screening?: { blocked?: boolean } | null;
    model_armor?: { blocked?: boolean } | null;
    forbidden_fields_attempted?: unknown[] | null;
  };
  return Boolean(
    security.injection_screening?.blocked ||
      security.model_armor?.blocked ||
      (security.forbidden_fields_attempted?.length ?? 0) > 0,
  );
}
