import { DEMO_MODE } from "./config";
import { demoAudits, demoUsage } from "./demo-data";
import type {
  AgentReadiness,
  AuditRecord,
  Case,
  CaseEvent,
  ComplianceAuditResponse,
  ComplianceReportsResponse,
  DeepReviewResult,
  DelegationBoundary,
  DriftCheck,
  HumanAction,
  MetricsSummary,
  OrchestratorSnapshot,
  Page,
  PrefilterRules,
  ReviewDecisionResult,
  TenantUsageResponse,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly kind: "unreachable" | "http" | "parse",
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * Thrown when a screen that needs live data is asked for it in demo mode.
 *
 * Demo mode has fixtures for the two B2B reads only. Rather than invent
 * plausible operational data for the other five screens, they say they need the
 * live API. A console that renders a fabricated pipeline is the same liability
 * the demo pill exists to prevent -- and a fabricated *governance boundary*
 * would be worse, because it would show an authority that was never delegated.
 */
export class DemoModeUnavailable extends ApiError {
  constructor(what: string) {
    super(
      `${what} has no demo fixture. Set NEXT_PUBLIC_DEMO_MODE=false and point ` +
        `FLASK_API_BASE at a running API to use this screen.`,
      501,
      "http",
    );
    this.name = "DemoModeUnavailable";
  }
}

async function request(
  path: string,
  init?: RequestInit,
): Promise<{ text: string; status: number; ok: boolean }> {
  let response: Response;
  try {
    response = await fetch(`/api/proxy/${path}`, {
      ...init,
      headers: { Accept: "application/json", ...(init?.headers ?? {}) },
    });
  } catch (error) {
    throw new ApiError(
      error instanceof Error ? error.message : String(error),
      0,
      "unreachable",
    );
  }
  return {
    text: await response.text(),
    status: response.status,
    ok: response.ok,
  };
}

function parseOrThrow<T>(text: string, status: number, ok: boolean): T {
  if (!ok) {
    // Prefer the upstream's own error text; a bare status code tells an operator
    // nothing about whether the API is down or the request was wrong.
    let detail = `HTTP ${status}`;
    try {
      const parsed = JSON.parse(text) as {
        error?: string;
        detail?: string;
        details?: string[];
        supported?: string[];
      };
      detail =
        parsed.details?.join("; ") ?? parsed.detail ?? parsed.error ?? detail;

      // A 415 from the document route answers "what should I have sent?" in a
      // `supported` array. Appended rather than dropped: without it the message
      // reads "Unsupported file type: contract.docx" and leaves the user to
      // guess. Handled here rather than at the upload call site so any route
      // that starts returning a supported list gets the same treatment.
      if (parsed.supported?.length) {
        detail = `${detail} — accepted: ${parsed.supported.join(", ")}`;
      }
    } catch {
      /* keep the status */
    }
    throw new ApiError(detail, status, status === 502 ? "unreachable" : "http");
  }

  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError("Response was not JSON", status, "parse");
  }
}

async function getJson<T>(path: string): Promise<T> {
  const { text, status, ok } = await request(path);
  return parseOrThrow<T>(text, status, ok);
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const { text, status, ok } = await request(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  return parseOrThrow<T>(text, status, ok);
}

async function putJson<T>(path: string, body: unknown): Promise<T> {
  const { text, status, ok } = await request(path, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseOrThrow<T>(text, status, ok);
}

function liveOnly(what: string): never {
  throw new DemoModeUnavailable(what);
}

// --------------------------------------------------------------------------
// B2B contract reads (the two the console was originally built on)
// --------------------------------------------------------------------------

/**
 * Audits for a tenant.
 *
 * `tenantId` is used as a fixture key in demo mode and as a cache key in live
 * mode -- it is never sent to the API, because the API decides the tenant from
 * the authenticated identity and would ignore it. Keeping it in the query key
 * anyway is what makes a tenant switch discard the previous tenant's rows
 * instead of showing them under a new name.
 */
export async function fetchAudits(
  tenantId: string,
): Promise<ComplianceAuditResponse[]> {
  if (DEMO_MODE) return demoAudits(tenantId);
  const page = await getJson<ComplianceReportsResponse>(
    "compliance/reports?limit=50",
  );
  return page.audits;
}

export async function fetchUsage(
  tenantId: string,
): Promise<TenantUsageResponse> {
  if (DEMO_MODE) return demoUsage(tenantId);
  return getJson<TenantUsageResponse>("billing/usage");
}

// --------------------------------------------------------------------------
// Pipeline
// --------------------------------------------------------------------------

/**
 * The board snapshot.
 *
 * `drain` defaults to 0 and is opt-in for one reason: GET
 * /api/v1/orchestrator/state *mutates* when drain=1 -- it advances one case per
 * request in ondemand mode. Every screen polls this endpoint, so a default of 1
 * would make six screens six competing pipeline advancers, which is exactly how
 * the optimistic-lock conflicts in the last round were produced. Only the
 * Pipeline screen asks for it.
 */
export async function fetchSnapshot(
  { drain = false, limit = 60 }: { drain?: boolean; limit?: number } = {},
): Promise<OrchestratorSnapshot> {
  if (DEMO_MODE) liveOnly("The pipeline board");
  return getJson<OrchestratorSnapshot>(
    `orchestrator/state?limit=${limit}&drain=${drain ? 1 : 0}`,
  );
}

export async function fetchMetrics(): Promise<MetricsSummary> {
  if (DEMO_MODE) liveOnly("Exact metrics");
  return getJson<MetricsSummary>("metrics/summary");
}

export async function fetchCases(
  { states, cursor, limit = 50 }:
    { states?: string[]; cursor?: string | null; limit?: number } = {},
): Promise<Page<Case>> {
  if (DEMO_MODE) liveOnly("The case list");
  const params = new URLSearchParams({ limit: String(limit) });
  // `state`, singular, even though it accepts a comma-separated list. The route
  // reads request.args.get("state") and splits on commas; sending `states` is
  // silently ignored, which returns every case rather than an error.
  if (states?.length) params.set("state", states.join(","));
  if (cursor) params.set("cursor", cursor);
  return getJson<Page<Case>>(`cases?${params}`);
}

export async function fetchCase(caseId: string): Promise<Case> {
  if (DEMO_MODE) liveOnly("The case trace");
  return getJson<Case>(`orchestrator/case/${encodeURIComponent(caseId)}`);
}

export async function fetchEvents(
  { cursor, limit = 80 }: { cursor?: string | null; limit?: number } = {},
): Promise<Page<CaseEvent>> {
  if (DEMO_MODE) liveOnly("The event feed");
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor) params.set("cursor", cursor);
  return getJson<Page<CaseEvent>>(`events?${params}`);
}

// --------------------------------------------------------------------------
// Review queue
// --------------------------------------------------------------------------

/**
 * Cases waiting on a person.
 *
 * Note the response key: this route returns `{cases, next_cursor}` while
 * `/cases`, `/audit` and `/events` all return `{items, next_cursor}`. It is the
 * only one that differs, and typing it as `Page<Case>` made `items` undefined --
 * which rendered as an empty queue rather than as an error, so a reviewer would
 * have been shown "nothing to review" with cases sitting in it. Normalised here
 * so no screen has to remember the exception.
 */
export async function fetchReviewQueue(
  { cursor, limit = 40 }: { cursor?: string | null; limit?: number } = {},
): Promise<Page<Case>> {
  if (DEMO_MODE) liveOnly("The review queue");
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor) params.set("cursor", cursor);
  const page = await getJson<{ cases: Case[]; next_cursor: string | null }>(
    `review/queue?${params}`,
  );
  return { items: page.cases ?? [], next_cursor: page.next_cursor };
}

/**
 * Record a named human's decision.
 *
 * `reviewer` is deliberately NOT sent. The server reads the acting person from the
 * verified console session and ignores any name in the body, so sending one would
 * be a field that looks authoritative and is discarded -- which is how a caller
 * ends up believing they set something they did not. A note is still sent: the
 * backend requires one for anything other than a plain release.
 *
 * Returns `{ok: false, error}` with a 400 rather than throwing on a refused
 * decision. Both shapes are handled by the caller, because a refusal here is a
 * normal outcome and not an error.
 */
export async function decideReview(args: {
  caseId: string;
  action: HumanAction;
  note: string;
}): Promise<ReviewDecisionResult> {
  if (DEMO_MODE) liveOnly("Recording a review decision");
  return postJson<ReviewDecisionResult>(
    `review/${encodeURIComponent(args.caseId)}/decide`,
    { action: args.action, note: args.note },
  );
}

/** Nemotron Super re-reads the case. Expensive and explicitly opt-in. */
export async function requestDeepReview(
  caseId: string,
): Promise<DeepReviewResult> {
  if (DEMO_MODE) liveOnly("Deep review");
  return postJson<DeepReviewResult>(
    `review/${encodeURIComponent(caseId)}/deep-review`,
  );
}

/** The archived paperwork, for the review iframe. Returns a proxy URL. */
export function reviewDocumentUrl(caseId: string): string {
  return `/api/proxy/review/${encodeURIComponent(caseId)}/document`;
}

// --------------------------------------------------------------------------
// Audit trail
// --------------------------------------------------------------------------

/**
 * The audit log, filtered server-side.
 *
 * `case_id`, `action` and `status` are mutually exclusive upstream -- the route
 * applies whichever it finds and a wider combination would need a composite
 * index this project does not declare. Enforced here by sending exactly one, in
 * that order of precedence, rather than sending several and hoping.
 */
export async function fetchAuditTrail(
  { caseId, action, status, cursor, limit = 60 }: {
    caseId?: string | null;
    action?: string | null;
    status?: string | null;
    cursor?: string | null;
    limit?: number;
  } = {},
): Promise<Page<AuditRecord>> {
  if (DEMO_MODE) liveOnly("The audit trail");
  const params = new URLSearchParams({ limit: String(limit) });
  if (caseId) params.set("case_id", caseId);
  else if (action) params.set("action", action);
  else if (status) params.set("status", status);
  if (cursor) params.set("cursor", cursor);
  return getJson<Page<AuditRecord>>(`audit?${params}`);
}

// --------------------------------------------------------------------------
// Governance
// --------------------------------------------------------------------------

export async function fetchAgentReadiness(): Promise<AgentReadiness> {
  if (DEMO_MODE) liveOnly("Agent readiness");
  return getJson<AgentReadiness>("governance/agent");
}

/**
 * Drift metrics alone.
 *
 * This route returns the drift object at the top level -- `{material, reason,
 * reasons, metrics}` -- not `{agent, drift}`. Typing it the other way made
 * `data.agent` undefined, which rendered the governance banner as "Operating
 * under undefined" while reporting the agent as ready: the fail-closed state
 * would have been displayed as the healthy one, on the screen whose whole job is
 * to say whether the agent may act.
 *
 * Note `metrics` is absent entirely when no boundary has been published -- the
 * route falls back to `{material: false, reasons: []}` -- so it is optional here
 * rather than defaulted, because a zeroed metrics block would read as "we
 * measured and found nothing" instead of "we did not measure".
 */
export async function fetchDrift(): Promise<DriftCheck> {
  if (DEMO_MODE) liveOnly("Drift detection");
  return getJson<DriftCheck>("governance/drift");
}

export async function fetchBoundaries(): Promise<{
  boundaries: DelegationBoundary[];
  proposed_template: Record<string, unknown>;
}> {
  if (DEMO_MODE) liveOnly("Delegation boundaries");
  // Note the response has no `active` key. The active boundary is whichever one
  // has status ACTIVE, and `proposed_template` is a starting point for the form,
  // not something that has been granted -- rendering it as the current authority
  // would show a delegation nobody published.
  return getJson<{
    boundaries: DelegationBoundary[];
    proposed_template: Record<string, unknown>;
  }>("governance/boundaries");
}

export async function publishBoundary(args: {
  permissions: Record<string, unknown>;
  author: string;
  note: string;
}): Promise<{ published: boolean; boundary: DelegationBoundary }> {
  if (DEMO_MODE) liveOnly("Publishing a delegation boundary");
  return postJson("governance/publish", args);
}

/**
 * The kill switch.
 *
 * The response is flat -- `{revoked, reason, agent}` -- not `{result, agent}`.
 * `author` is required upstream and a missing one is a 400, which is why the form
 * checks for it before calling.
 */
export async function revokeBoundary(args: {
  author: string;
  note: string;
}): Promise<{
  revoked: boolean;
  reason: string;
  agent: AgentReadiness;
}> {
  if (DEMO_MODE) liveOnly("Revoking a delegation boundary");
  return postJson("governance/revoke", args);
}

/**
 * Replay recent cases against a candidate boundary. Writes nothing.
 *
 * `check()` is pure, so this is safe to call freely -- no boundary is published
 * and no action is executed. The candidate is wrapped in a throwaway envelope
 * carrying version null, which is why the per-case rows report a decision rather
 * than a version.
 */
export async function simulateBoundary(
  permissions: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  if (DEMO_MODE) liveOnly("Boundary simulation");
  return postJson("governance/simulate", { permissions });
}

export async function fetchPrefilterRules(): Promise<PrefilterRules> {
  if (DEMO_MODE) liveOnly("Pre-filter rules");
  return getJson<PrefilterRules>("governance/prefilter-rules");
}

/**
 * Save a partial rule update.
 *
 * Partial on purpose: the backend leaves any key absent from the body as it was,
 * so a screen editing the blacklist does not have to resubmit the VIP registry
 * and risk clobbering a concurrent edit to it.
 *
 * No `author` is sent. The backend derives it from the authenticated identity
 * and ignores a body field, because a self-declared author on a control that
 * decides which shipments skip screening is worth nothing.
 */
export async function savePrefilterRules(
  patch: Partial<PrefilterRules>,
): Promise<{ ok: boolean; rules: PrefilterRules }> {
  if (DEMO_MODE) liveOnly("Editing pre-filter rules");
  return putJson("governance/prefilter-rules", patch);
}

export async function verifyEntity(args: {
  type: "company" | "tax_id";
  value: string;
  country?: string;
}): Promise<{
  verified: boolean;
  confidence: string;
  results: Array<{ title: string; url: string; snippet: string }>;
  summary: string;
}> {
  if (DEMO_MODE) liveOnly("Entity verification");
  return postJson("governance/verify-entity", args);
}

// --------------------------------------------------------------------------
// DevOps
// --------------------------------------------------------------------------

/**
 * Inject the scripted demo batch.
 *
 * Takes no shipment. The route builds `simulator.scripted_shipments()` and
 * ignores the request body entirely, so a signature accepting a custom shipment
 * would be a lie that silently discarded it. Use submitShipmentEvent for a
 * hand-written one.
 *
 * Returns 202 with the ids it queued, not a finished case: the workflow runs
 * afterwards and the Pipeline board is where the outcome appears.
 */
export async function injectScriptedBatch(): Promise<{
  injected: number;
  case_ids: string[];
  note?: string;
}> {
  if (DEMO_MODE) liveOnly("Injecting the demo batch");
  return postJson("simulate");
}

export async function injectBulk(
  count: number,
): Promise<{ queued: number; case_ids: string[]; note?: string }> {
  if (DEMO_MODE) liveOnly("Bulk injection");
  return postJson("simulate/bulk", { count });
}

/** Submit a shipment event, as Pub/Sub would. */
export async function submitShipmentEvent(
  shipment: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  if (DEMO_MODE) liveOnly("Submitting a shipment event");
  return postJson("events/shipment", shipment);
}

/**
 * Upload a shipping document.
 *
 * multipart/form-data, streamed through the proxy rather than buffered, and with
 * a much longer timeout than a read: this runs Model Armor, extraction and two
 * agent hops before it answers.
 */
export async function uploadDocument(file: File): Promise<Record<string, unknown>> {
  if (DEMO_MODE) liveOnly("Document upload");
  const form = new FormData();
  form.append("file", file);
  // No content-type header: the browser must set it, because it has to append
  // the multipart boundary. Setting it by hand produces a body the server
  // cannot parse, and the failure looks like a corrupt file.
  const { text, status, ok } = await request("events/document", {
    method: "POST",
    body: form,
  });
  return parseOrThrow<Record<string, unknown>>(text, status, ok);
}

// --------------------------------------------------------------------------
// Agent console
// --------------------------------------------------------------------------

export async function fetchModelConfig(): Promise<Record<string, unknown>> {
  if (DEMO_MODE) liveOnly("Model configuration");
  return getJson<Record<string, unknown>>("config/model");
}

export async function fetchAttackLog(): Promise<Record<string, unknown>> {
  if (DEMO_MODE) liveOnly("The attack log");
  return getJson<Record<string, unknown>>("security/attacks");
}

/** Run one text through Model Armor by hand. */
export async function screenText(
  text: string,
): Promise<Record<string, unknown>> {
  if (DEMO_MODE) liveOnly("Manual injection screening");
  return postJson("security/screen", { text });
}

// --------------------------------------------------------------------------
// Query keys
//
// Every key carries the tenant id, even though the tenant is never sent. That
// is what makes a tenant switch discard the previous tenant's cache rather than
// relabel it, which is the one cross-tenant leak a client-side console can
// create without the server's help.
// --------------------------------------------------------------------------

export const queryKeys = {
  audits: (tenantId: string) => ["audits", tenantId] as const,
  usage: (tenantId: string) => ["usage", tenantId] as const,
  snapshot: (tenantId: string, drain: boolean) =>
    ["snapshot", tenantId, drain] as const,
  metrics: (tenantId: string) => ["metrics", tenantId] as const,
  cases: (tenantId: string, states?: string[]) =>
    ["cases", tenantId, states ?? []] as const,
  case: (tenantId: string, caseId: string) =>
    ["case", tenantId, caseId] as const,
  events: (tenantId: string) => ["events", tenantId] as const,
  reviewQueue: (tenantId: string) => ["review-queue", tenantId] as const,
  auditTrail: (
    tenantId: string,
    filter: { caseId?: string | null; action?: string | null },
  ) => ["audit-trail", tenantId, filter.caseId ?? "", filter.action ?? ""] as const,
  agent: (tenantId: string) => ["agent", tenantId] as const,
  drift: (tenantId: string) => ["drift", tenantId] as const,
  boundaries: (tenantId: string) => ["boundaries", tenantId] as const,
  prefilter: (tenantId: string) => ["prefilter", tenantId] as const,
  modelConfig: (tenantId: string) => ["model-config", tenantId] as const,
  attacks: (tenantId: string) => ["attacks", tenantId] as const,
};
