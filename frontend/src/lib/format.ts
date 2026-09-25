/**
 * Presentation helpers. Kept out of components so the rules are testable.
 *
 * EVERY helper here accepts null/undefined and returns a sentinel rather than throwing.
 * That is not defensive habit, it is a scar: `formatUsd` was originally typed
 * `(value: number)`, a missing `cost_usd` arrived as `undefined`, and
 * `undefined.toLocaleString()` threw during render. With no React error boundary in the
 * app the whole tree unmounted -- a white page instead of a dash in one column.
 *
 * The guard was then added to `formatUsd` alone, while `shortModelName`,
 * `humaniseAgent` and `humaniseCode` sat eight lines below with the identical bug and
 * five label helpers routing through them. TypeScript did not catch it because the
 * types describe the API contract rather than what the API actually sends: lib/types.ts
 * says as much about the internal dashboard routes -- "those routes return whatever the
 * store holds".
 *
 * So the rule is the class, not the instance: nothing in this file throws on absent
 * input.
 */

/** What every helper returns when it has nothing to render. An em dash. */
export const NO_VALUE = "\u2014";

export function formatUsd(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return NO_VALUE;
  if (value === 0) return "$0";
  // Token costs land in the fractions of a cent; two decimal places would show
  // every audit as $0.00 and make the cost column useless.
  if (value < 0.01) return `$${value.toFixed(5)}`;
  if (value < 1) return `$${value.toFixed(4)}`;
  return `$${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatTokens(value: number | null | undefined): string {
  // Without the guard this returned the literal string "undefined", which is worse than
  // a dash because it reads as a rendering bug rather than as missing data.
  if (value == null || !Number.isFinite(value)) return NO_VALUE;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return String(value);
}

export function formatLatency(ms: number | null | undefined): string {
  // `ms === null` was the original check, so an undefined latency produced "NaN s".
  if (ms == null || !Number.isFinite(ms)) return NO_VALUE;
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return NO_VALUE;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function formatClock(iso: string | null | undefined): string {
  if (!iso) return NO_VALUE;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().replace("T", " ").slice(0, 19) + "Z";
}

/** "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B" -> "Nemotron 3 Nano" */
export function shortModelName(modelId: string | null | undefined): string {
  if (!modelId) return NO_VALUE;
  const tail = modelId.split("/").pop() ?? modelId;
  const match = tail.match(/Nemotron-3-(Nano|Super|Ultra)/i);
  if (match) return `Nemotron 3 ${match[1][0].toUpperCase()}${match[1].slice(1).toLowerCase()}`;
  return tail;
}

/** "fraud_detection" -> "Fraud detection", "hs_classifier" -> "HS classifier" */
export function humaniseAgent(agent: string | null | undefined): string {
  if (!agent) return NO_VALUE;
  return humaniseCode(agent.toUpperCase());
}

/**
 * "SANCTIONS_MATCH" -> "Sanctions match", but "HS_CODE_MALFORMED" ->
 * "HS code malformed".
 *
 * Acronyms are restored after lower-casing. In this domain HS, OFAC and EU are
 * terms of art, and rendering the Harmonized System as "Hs" reads as a typo in
 * a product whose whole claim is care with customs vocabulary.
 */
const ACRONYMS = new Set([
  "HS", "ID", "EU", "US", "UN", "OFAC", "BIS", "AI", "VAT",
  // SAR is the filing itself -- "Draft sar" reads as a misspelling of a legal
  // document, which is not a good look on an audit trail.
  "SAR",
]);

export function humaniseCode(code: string | null | undefined): string {
  if (!code) return NO_VALUE;
  const words = code.split("_");
  const rendered = words.map((word, i) => {
    if (ACRONYMS.has(word)) return word;
    const lower = word.toLowerCase();
    return i === 0 ? lower.charAt(0).toUpperCase() + lower.slice(1) : lower;
  });
  return rendered.join(" ");
}

/**
 * Display labels for the values that arrive from the backend as identifiers.
 *
 * Why maps on top of humaniseCode: mechanical de-snaking gets most of the way,
 * but some of these need domain wording rather than a transliteration --
 * "DEAD_LETTER" is not "Dead letter" to anyone outside the codebase, and
 * "human_request_info" reads as an instruction rather than something that
 * happened. Anything absent falls through to humaniseCode, so a value this file
 * has never heard of degrades to readable text instead of vanishing.
 *
 * These are for DISPLAY ONLY. The raw identifiers are load-bearing elsewhere --
 * React keys, Radix `value=` props that get sent to the API, and the className
 * lookup tables in risk.ts and CaseCard.tsx are all keyed by the raw string.
 * Never substitute a label into any of those.
 */

/**
 * Individual case states.
 *
 * Deliberately NOT the same as the board's column labels in pipeline.ts, and not
 * merged with them. A column folds several states together -- "Cleared" holds
 * both AUTO_CLEARED and RELEASED_BY_HUMAN, which is why it is no longer called
 * "Auto-cleared" -- so a column label is a statement about a group and these are
 * statements about one case. Collapsing the two would quietly undo the folding
 * documented at pipeline.ts:29.
 */
export const CASE_STATE_LABEL: Record<string, string> = {
  INGESTED: "Queued",
  SPECIALISTS_DONE: "Fraud and compliance done",
  INVESTIGATED: "Investigated",
  AUTO_CLEARED: "Cleared automatically",
  HELD_FOR_REVIEW: "Held for review",
  ESCALATED: "Escalated",
  PENDING_HUMAN: "Awaiting a person",
  RELEASED_BY_HUMAN: "Released by a reviewer",
  BLOCKED_BY_HUMAN: "Blocked by a reviewer",
  DEAD_LETTER: "Abandoned after retries",
};

export function caseStateLabel(state: string | null | undefined): string {
  if (!state) return NO_VALUE;
  return CASE_STATE_LABEL[state] ?? humaniseCode(state);
}

/** Actions as they appear in the audit trail. */
export const AUDIT_ACTION_LABEL: Record<string, string> = {
  release_shipment: "Release shipment",
  hold_shipment: "Hold shipment",
  assign_analyst: "Assign analyst",
  draft_sar: "Draft SAR",
  notify_webhook: "Notify webhook",
  publish_decision: "Publish decision",
  human_release: "Released by a reviewer",
  human_block: "Blocked by a reviewer",
  human_request_info: "More information requested",
  agent_decision: "Agent decision",
  gate_denied: "Refused by the delegation boundary",
  publish_delegation_boundary: "Publish delegation boundary",
  revoke_delegation_boundary: "Revoke delegation boundary",
  update_prefilter_rules: "Update pre-filter rules",
  superseded: "Superseded by a newer write",
  retry: "Retry scheduled",
  dead_letter: "Abandoned after retries",
};

export function actionLabel(action: string | null | undefined): string {
  if (!action) return NO_VALUE;
  return AUDIT_ACTION_LABEL[action] ?? humaniseAgent(action);
}

/** Finding and audit severities. */
export const SEVERITY_LABEL: Record<string, string> = {
  CRITICAL: "Critical",
  HIGH: "High",
  MEDIUM: "Medium",
  LOW: "Low",
  INFO: "Informational",
  CLEAR: "Clear",
};

export function severityLabel(severity: string | null | undefined): string {
  if (!severity) return NO_VALUE;
  return SEVERITY_LABEL[severity] ?? humaniseCode(severity);
}

/** Per-action outcome recorded on an audit row. */
export const AUDIT_STATUS_LABEL: Record<string, string> = {
  done: "Done",
  denied: "Denied",
  skipped: "Skipped",
  failed: "Failed",
  recorded: "Recorded",
};

export function auditStatusLabel(status: string | null | undefined): string {
  if (!status) return NO_VALUE;
  return AUDIT_STATUS_LABEL[status] ?? humaniseAgent(status);
}

/** The compliance agent's verdict. */
export const COMPLIANCE_STATUS_LABEL: Record<string, string> = {
  CLEARED: "Cleared",
  REVIEW_REQUIRED: "Review required",
  BLOCKED: "Blocked",
};

export function complianceStatusLabel(status: string | null | undefined): string {
  if (!status) return NO_VALUE;
  return COMPLIANCE_STATUS_LABEL[status] ?? humaniseCode(status);
}

/**
 * For dropping a sentence-case label into the middle of a sentence.
 *
 * The maps above are written sentence-case because that is what a chip, a column
 * header or a table cell wants. Prose wants the other thing: "This records
 * Released by a reviewer against the case" reads as a stray capital. Only the
 * first character is touched, so an acronym-initial label such as "HS code
 * malformed" is left alone.
 */
export function lowerFirst(text: string | null | undefined): string {
  if (!text) return text ?? NO_VALUE;
  const [first, ...rest] = text;
  // A deliberate acronym must survive: "HS ..." must not become "hS ...".
  if (first === first.toUpperCase() && rest[0] === rest[0]?.toUpperCase()) {
    return text;
  }
  return first.toLowerCase() + rest.join("");
}
