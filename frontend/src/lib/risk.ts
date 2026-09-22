import { humaniseCode, lowerFirst } from "./format";
import type {
  AuditFinding,
  AuditOutcome,
  ComplianceAuditResponse,
  Severity,
} from "./types";

/**
 * Presentation states for a verdict.
 *
 * Three, not two. The backend distinguishes "I checked and found nothing" from
 * "I could not check", and collapsing that distinction here would undo it at
 * the exact point a human reads the result. A screening that failed to run is
 * not a clearance, and a green badge over an unscreened shipment produces the
 * worst artefact this product can emit: paperwork asserting a check that never
 * happened.
 */
export type RiskState = "critical" | "warn" | "clear" | "neutral";

/**
 * Findings whose meaning is "this check did not produce an answer".
 *
 * Matched by suffix rather than an explicit list so that a new
 * `SOMETHING_UNAVAILABLE` code added to verifier.py is treated as unverified on
 * arrival instead of silently falling through to the clear branch. The default
 * for an unrecognised code has to be the cautious one.
 */
const UNVERIFIED_SUFFIXES = [
  "_UNAVAILABLE",
  "_DID_NOT_RUN",
  "_UNVERIFIED",
  "_MISSING",
  "_UNSUPPORTED",
] as const;

export function isUnverifiedCheck(code: string): boolean {
  return UNVERIFIED_SUFFIXES.some((suffix) => code.endsWith(suffix));
}

/** Findings that mean a check could not be completed. */
export function unverifiedChecks(findings: AuditFinding[]): AuditFinding[] {
  return findings.filter((f) => isUnverifiedCheck(f.code));
}

const OUTCOME_STATE: Record<AuditOutcome, RiskState> = {
  BLOCKED: "critical",
  HELD_FOR_REVIEW: "warn",
  PENDING_HUMAN: "warn",
  // Not "clear": an audit that errored has no verdict, and the absence of a
  // verdict is not a pass.
  ERROR: "warn",
  CLEARED: "clear",
};

const OUTCOME_LABEL: Record<AuditOutcome, string> = {
  BLOCKED: "OFAC Sanction",
  HELD_FOR_REVIEW: "Held for review",
  PENDING_HUMAN: "Awaiting officer",
  ERROR: "Audit failed",
  CLEARED: "Clear",
};

export interface RiskPresentation {
  state: RiskState;
  label: string;
  /**
   * Set when the verdict rests on at least one check that did not run. Kept
   * separate from `state` so a cleared-but-incomplete audit still reads as
   * cleared while showing that it is not a complete clearance.
   */
  unverified: AuditFinding[];
  /** Long-form reason, for a tooltip. */
  reason: string;
}

/**
 * Map an audit to what the badge should say.
 *
 * The interesting branch is CLEARED with unverified findings. It is reachable:
 * HS_DESCRIPTION_CHECK_UNAVAILABLE and ZERO_DAY_CHECK_UNAVAILABLE both carry
 * floor 0, so they do not push the score to the review threshold and the audit
 * clears with a check missing. Those cases are labelled "Clear, N unverified"
 * rather than "Clear".
 */
export function derivePresentation(
  audit: ComplianceAuditResponse,
): RiskPresentation {
  const unverified = unverifiedChecks(audit.findings);
  const state = OUTCOME_STATE[audit.outcome] ?? "neutral";

  // A sanctions hit is the headline when there is one, regardless of how the
  // score resolved -- "Held for review" understates a name on the SDN list.
  const sanctionsHit = audit.findings.some((f) => f.code === "SANCTIONS_MATCH");
  const zeroDay = audit.findings.some(
    (f) => f.code === "ZERO_DAY_ADVERSE_MEDIA",
  );

  let label = OUTCOME_LABEL[audit.outcome] ?? audit.outcome;
  if (sanctionsHit) {
    label = "OFAC Sanction";
  } else if (zeroDay && state !== "clear") {
    label = "Zero-Day Risk";
  }

  if (state === "clear" && unverified.length > 0) {
    return {
      state: "warn",
      label: `Clear, ${unverified.length} unverified`,
      unverified,
      reason:
        `Cleared on the checks that ran, but ${unverified.length} check(s) did ` +
        `not complete: ${unverified.map((f) => lowerFirst(humaniseCode(f.code))).join(", ")}. ` +
        `The absence of a finding from a check that did not run is not a clearance.`,
    };
  }

  return {
    state,
    label,
    unverified,
    reason:
      audit.review_reason ??
      (state === "clear"
        ? "All deterministic and model checks completed with no adverse finding."
        : `Outcome ${lowerFirst(OUTCOME_LABEL[audit.outcome] ?? humaniseCode(audit.outcome))} at effective risk ${audit.effective_risk}.`),
  };
}

const SEVERITY_RANK: Record<Severity, number> = {
  CRITICAL: 0,
  HIGH: 1,
  MEDIUM: 2,
  LOW: 3,
  INFO: 4,
  CLEAR: 5,
};

/** Most serious first, then by the floor each finding forces. */
export function sortFindings(findings: AuditFinding[]): AuditFinding[] {
  return [...findings].sort((a, b) => {
    const bySeverity =
      (SEVERITY_RANK[a.severity] ?? 9) - (SEVERITY_RANK[b.severity] ?? 9);
    return bySeverity !== 0 ? bySeverity : b.floor - a.floor;
  });
}

export function severityState(severity: Severity): RiskState {
  if (severity === "CRITICAL") return "critical";
  if (severity === "HIGH" || severity === "MEDIUM") return "warn";
  if (severity === "CLEAR") return "clear";
  return "neutral";
}

/** Findings backed by news citations, which get their own block. */
function isEvidenceFinding(finding: AuditFinding): boolean {
  return finding.code.startsWith("ZERO_DAY");
}

/**
 * Every deterministic finding except the adverse-media ones.
 *
 * Written as the complement of the evidence block rather than as an allow-list,
 * so that the two blocks together account for all of `findings`. The allow-list
 * version matched SANCTIONS / BLACKLIST / WHITELIST / DUAL_USE / HIGH_RISK
 * prefixes and quietly dropped the rest: an audit whose table row read
 * "5 findings" opened onto two, with FREIGHT_ANOMALY, VALUE_DENSITY_HIGH and a
 * floor-65 SHIPPER_NO_HISTORY appearing in no block at all. A reviewer asking
 * why a shipment scored 90 was shown less than half the answer.
 *
 * The complement also fails safe as verifier.py grows: a new code appears here
 * on arrival instead of needing a prefix added to a list nobody remembers.
 */
export function screeningFindings(findings: AuditFinding[]): AuditFinding[] {
  return findings.filter((f) => !isEvidenceFinding(f));
}

export function evidenceFindings(findings: AuditFinding[]): AuditFinding[] {
  return findings.filter(isEvidenceFinding);
}

export const RISK_CLASS: Record<RiskState, string> = {
  critical: "badge-risk badge-critical",
  warn: "badge-risk badge-warn",
  clear: "badge-risk badge-clear",
  neutral: "badge-risk badge-neutral",
};
