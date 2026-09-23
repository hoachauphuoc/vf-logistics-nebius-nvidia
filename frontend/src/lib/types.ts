/**
 * TypeScript mirrors of the published audit contract.
 *
 * These follow src/vf_logistics/schemas.py field for field. Where the Python
 * model allows a null the type here is `| null` rather than optional, because
 * the API sends the key with a null value and `undefined` would let a missing
 * key pass unnoticed through an `if (x)` check that was meant to test for null.
 *
 * Regenerate against docs/swagger.json if the backend contract moves.
 */

/** Terminal outcomes an integrator branches on. Five, not two. */
export type AuditOutcome =
  | "CLEARED"
  | "HELD_FOR_REVIEW"
  | "BLOCKED"
  | "PENDING_HUMAN"
  | "ERROR";

export type Severity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO" | "CLEAR";

export interface AuditFinding {
  code: string;
  severity: Severity;
  detail: string;
  /** Minimum risk this finding alone forces. The model cannot lower it. */
  floor: number;
  /**
   * Sanctions list entity ids behind a match. Empty for findings derived from
   * arithmetic, which have no list record to point at.
   */
  source_entity_ids: string[];
  /**
   * Public news citations behind an adverse-media finding.
   *
   * `null` and `[]` are different facts and must not be collapsed: null means
   * no search result was recorded for this finding, [] means a search ran and
   * returned nothing. Optional as well as nullable because an older backend
   * omits the key entirely, which carries the same meaning as null.
   */
  evidence_urls?: string[] | null;
}

export interface AuditLineage {
  audit_id: string;
  /** Keyed by agent name. */
  prompt_hashes: Record<string, string>;
  /** Keyed by agent name, so each part of a verdict traces to its own model. */
  model_versions: Record<string, string>;
  sanctions_synced_at: string | null;
  sanctions_list_age_days: number | null;
  ruleset_version: number | null;
}

export interface AuditUsage {
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
  agent_calls: number;
  latency_ms: number | null;
}

export interface ComplianceAuditResponse {
  audit_id: string;
  case_id: string;
  shipment_id: string;
  client_reference: string | null;

  outcome: AuditOutcome;
  effective_risk: number;
  /** What the model alone scored, before the deterministic floor. */
  model_risk: number | null;
  /** Deterministic minimum. The model may raise this, never lower it. */
  risk_floor: number;
  /** Model and floor disagreed by 15 points or more. */
  score_disputed: boolean;

  findings: AuditFinding[];
  requires_human_review: boolean;
  review_reason: string | null;

  lineage: AuditLineage;
  usage: AuditUsage;

  created_at: string;
  completed_at: string | null;
  idempotent_replay: boolean;
}

export interface ComplianceReportsResponse {
  audits: ComplianceAuditResponse[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface TenantUsageResponse {
  tenant_id: string;
  agent_calls: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
  cost_per_call_usd: number;
  auto_cleared: number;
  cleared_by_rules: number;
  cleared_by_ai: number;
  avg_latency_ms: number;
}

/** A tenant the console can display. */
export interface Tenant {
  id: string;
  name: string;
  /** Shown under the name in the switcher. */
  descriptor: string;
}

// ==========================================================================
// Operational surface
//
// The types above mirror the published B2B audit contract in schemas.py, which
// is versioned and validated. Everything below describes the *internal*
// dashboard API, which is not: those routes return whatever the store holds.
//
// So these are written defensively -- almost every field is nullable, and none
// of them is trusted to exist. A case written before a field was introduced
// simply lacks it, and `slim_case()` projects only eight keys, so the same
// `Case` shape arrives thin from `/cases` and fat from `/orchestrator/case/<id>`.
// ==========================================================================

/**
 * Case lifecycle states, exactly as orchestrator.py defines them.
 *
 * Kept as a union rather than a string so a screen cannot silently handle a
 * state that does not exist. Note that BLOCKED is absent on purpose: it is an
 * *audit outcome*, not a case state -- a case reaches BLOCKED_BY_HUMAN and the
 * audit projection reports BLOCKED. There is no autonomous block.
 */
export type CaseState =
  // actionable
  | "INGESTED"
  | "SPECIALISTS_DONE"
  | "INVESTIGATED"
  // terminal
  | "AUTO_CLEARED"
  | "HELD_FOR_REVIEW"
  | "ESCALATED"
  | "PENDING_HUMAN"
  | "RELEASED_BY_HUMAN"
  | "BLOCKED_BY_HUMAN"
  | "DEAD_LETTER";

/** Cases sitting in a person's queue. Mirrors AWAITING_HUMAN. */
export const AWAITING_HUMAN: readonly CaseState[] = [
  "PENDING_HUMAN",
  "HELD_FOR_REVIEW",
  "ESCALATED",
];

/** States the worker will pick up. Mirrors ACTIONABLE. */
export const ACTIONABLE: readonly CaseState[] = [
  "INGESTED",
  "SPECIALISTS_DONE",
  "INVESTIGATED",
];

/** The self-reported shipment record. Every field is caller-supplied. */
export interface Shipment {
  shipment_id?: string | null;
  shipper_company?: string | null;
  shipper_name?: string | null;
  shipper_tax_id?: string | null;
  consignee_name?: string | null;
  origin?: string | null;
  destination?: string | null;
  transit_country?: string | null;
  goods_description?: string | null;
  hs_code?: string | null;
  declared_value?: number | null;
  shipping_cost?: number | null;
  weight_kg?: number | null;
  quantity?: number | null;
  currency?: string | null;
  incoterms?: string | null;
  [key: string]: unknown;
}

/** One agent hop, with its own economics. */
export interface CaseStep {
  agent: string;
  model?: string | null;
  latency_ms?: number | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  at?: string | null;
  parse_error?: boolean | null;
  /** The agent's raw payload. Shape varies per agent, so it stays unknown. */
  result?: Record<string, unknown> | null;
  /** Exact text sent to and returned by the model, when recorded. */
  prompt?: string | null;
  raw_response?: string | null;
  /**
   * Citations the agent actually read, as {title, url}.
   *
   * This lives on the STEP, not on the case: it is evidence a particular agent
   * fetched, and attributing it to the case would lose which reasoning it fed.
   * compliance and investigation are the two that populate it.
   */
  external_search_results?: ExternalCitation[] | null;
}

/** One web source an agent read at decision time. */
export interface ExternalCitation {
  title?: string | null;
  url?: string | null;
}

/** A receipt from tools.py, or a governance denial. */
export interface ActionReceipt {
  audit_id?: string | null;
  case_id?: string | null;
  action: string;
  status: "done" | "denied" | "skipped" | "failed" | string;
  at?: string | null;
  detail?: Record<string, unknown> | null;
  gate_reason?: string | null;
}

export interface GateDenial {
  action: string;
  reason?: string | null;
  human_triggers?: string[] | null;
}

/**
 * How the deterministic floor and the model score were combined.
 *
 * `source` says which one won. "deterministic floor" means the model was
 * overruled, which is the case a reviewer most needs to see.
 */
export interface Reconciliation {
  model_risk?: number | null;
  effective_risk?: number | null;
  floor?: number | null;
  source?: string | null;
  vetoed?: boolean | null;
  veto_reasons?: string[] | null;
  auto_clear_permitted?: boolean | null;
}

export interface Validation {
  findings?: AuditFinding[] | null;
  risk_floor?: number | null;
  skip_ai?: boolean | null;
  auto_clear_by_rules?: boolean | null;
  auto_reject_by_rules?: boolean | null;
  hs_floor_effect?: number | null;
  [key: string]: unknown;
}

export interface HumanReview {
  action?: string | null;
  reviewer?: string | null;
  note?: string | null;
  at?: string | null;
  decided_by?: string | null;
}

/**
 * A case, thin or fat.
 *
 * `/cases` returns the eight `slim_case()` keys; `/orchestrator/case/<id>`
 * returns the whole document. One type covers both because the fat fields are
 * optional, which means a component reading `case.steps` has to cope with it
 * being absent -- and that is the honest situation, not a modelling compromise.
 */
export interface Case {
  case_id: string;
  shipment_id?: string | null;
  state: CaseState;
  source?: string | null;
  risk_score?: number | null;
  model_risk_score?: number | null;
  risk_level?: string | null;
  compliance_status?: string | null;
  compliance_score?: number | null;
  claimed?: boolean | null;
  created_at?: string | null;
  updated_at?: string | null;

  // Fat fields, present only on the per-case fetch.
  shipment?: Shipment | null;
  steps?: CaseStep[] | null;
  actions?: ActionReceipt[] | null;
  validation?: Validation | null;
  reconciliation?: Reconciliation | null;
  decision?: { outcome?: string; rationale?: string } | null;
  proposed_outcome?: string | null;
  gate_denials?: GateDenial[] | null;
  review?: HumanReview | null;
  requires_human?: boolean | null;
  provenance?: Record<string, unknown> | null;
  input_security?: Record<string, unknown> | null;
  route_intelligence?: string | null;
  /**
   * Per-search METADATA: {type, results, cached, status, at}. Counts, not citations.
   *
   * Deliberately not `urls`. An earlier version of the trace sheet read `s.urls` from
   * these entries, which never existed on them, so the citation list silently rendered
   * empty for every case while the section claimed to reproduce sources. The URLs are on
   * CaseStep.external_search_results.
   */
  tavily_searches?: Array<Record<string, unknown>> | null;
  debate?: Record<string, unknown> | null;
  attempts?: number | null;
  last_error?: string | null;
  lineage_audit_id?: string | null;

  // Rollups, denormalised for aggregation.
  _agent_calls?: number | null;
  _input_tokens?: number | null;
  _output_tokens?: number | null;
  _estimated_cost_usd?: number | null;
  _sum_latency_ms?: number | null;
}

export interface CaseEvent {
  event_id: string;
  case_id: string;
  kind: string;
  message: string;
  at: string;
  [key: string]: unknown;
}

export interface AuditRecord {
  audit_id: string;
  case_id: string;
  action: string;
  status: string;
  at: string;
  detail?: Record<string, unknown> | null;
}

export interface WorkerStatus {
  mode?: string | null;
  running?: boolean | null;
  started_at?: string | null;
  ticks?: number | null;
  advanced?: number | null;
  failed?: number | null;
  last_tick_error?: string | null;
  thresholds?: Record<string, number> | null;
}

export interface DelegationBoundary {
  boundary_id: string;
  version: number | null;
  status: "ACTIVE" | "SUPERSEDED" | "REVOKED" | "SIMULATED" | string;
  permissions: Record<string, unknown>;
  published_by?: string | null;
  note?: string | null;
  published_at?: string | null;
  supersedes?: string | null;
  revoked_by?: string | null;
  revoked_at?: string | null;
  revocation_note?: string | null;
}

export interface DriftMetrics {
  sample: number;
  auto_release_rate: number;
  veto_rate: number;
  injection_rate: number;
  boundary_version?: number | null;
}

export interface DriftCheck {
  material: boolean;
  reason?: string | null;
  reasons: string[];
  /**
   * Absent when no boundary has been published, because there was nothing to
   * measure drift against. Not defaulted to zeros: "we did not measure" and "we
   * measured and found nothing" are different facts, and a zeroed sample would
   * read as the second.
   */
  metrics?: DriftMetrics | null;
}

/**
 * Whether the agent may act at all.
 *
 * SUSPENDED with no boundary is the fail-closed default, not an error: with no
 * published delegation boundary every outcome stays a proposal and the case
 * goes to a human. A console that renders this as a warning badge and nothing
 * else leaves the operator wondering why nothing auto-clears.
 */
export interface AgentReadiness {
  state: "READY" | "SUSPENDED" | string;
  reason: string;
  boundary: DelegationBoundary | null;
  drift?: DriftCheck | null;
}

/** The pre-AI screening rule set, per tenant. */
export interface PrefilterRules {
  vip_registry: Array<{ company: string; tax_id: string }>;
  blacklist_companies: string[];
  blacklist_tax_ids: string[];
  safe_routes: Array<{ origin: string; destination: string }>;
  low_value_threshold_usd: number;
}

/** GET /api/v1/orchestrator/state */
export interface OrchestratorSnapshot {
  cases: Case[];
  events: CaseEvent[];
  audit: AuditRecord[];
  counts: Partial<Record<CaseState, number>>;
  in_flight: number;
  awaiting_human: number;
  agent: AgentReadiness;
  agent_calls: number;
  avg_latency_ms: number;
  total_input_tokens: number;
  total_output_tokens: number;
  tokens_by_agent: Record<
    string,
    { calls: number; input: number; output: number }
  >;
  estimated_cost_usd: number;
  worker: WorkerStatus;
  at: string;
  /** Present only when the request drained a case. */
  drained_this_request?: { drained: number; case_ids: string[] } | null;
}

/** GET /api/v1/metrics/summary -- the exact whole-collection totals. */
export interface MetricsSummary {
  counts: Partial<Record<CaseState, number>>;
  in_flight: number;
  awaiting_human: number;
  agent_calls: number;
  avg_latency_ms: number;
  total_input_tokens: number;
  total_output_tokens: number;
  estimated_cost_usd: number;
  cleared_by_rules: number;
  cleared_by_ai: number;
  cleared_by_unknown: number;
  total_auto_cleared: number;
  at: string;
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

/** POST /api/v1/review/<id>/decide */
export interface ReviewDecisionResult {
  ok: boolean;
  error?: string | null;
  case_id?: string | null;
  state?: CaseState | null;
  review?: HumanReview | null;
  receipts?: ActionReceipt[] | null;
}

/** POST /api/v1/review/<id>/deep-review */
export interface DeepReviewResult {
  ok: boolean;
  error?: string | null;
  case_id?: string | null;
  debate?: Record<string, unknown> | null;
  verdict?: {
    verdict?: string;
    confidence?: number;
    rationale?: string;
  } | null;
  latency_ms?: number | null;
}

/**
 * The human actions the review form offers. Mirrors HUMAN_ACTIONS exactly.
 *
 * Three, not four. There is no "hold" or "escalate" action a reviewer can take:
 * HELD_FOR_REVIEW and ESCALATED are states the *workflow* puts a case into, and
 * the only way out of them is one of these three. `request_info` keeps the case
 * in PENDING_HUMAN and records why, which is how a reviewer parks something
 * without pretending to have decided it.
 */
export type HumanAction = "release" | "block" | "request_info";

/** Where each action leaves the case, for the confirmation copy. */
export const HUMAN_ACTION_RESULT: Record<HumanAction, CaseState> = {
  release: "RELEASED_BY_HUMAN",
  block: "BLOCKED_BY_HUMAN",
  request_info: "PENDING_HUMAN",
};

