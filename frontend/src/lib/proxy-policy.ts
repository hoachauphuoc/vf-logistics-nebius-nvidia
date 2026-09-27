/**
 * What the console's BFF (`app/api/proxy/[...path]/route.ts`) forwards to Flask.
 *
 * The single source of truth for the allow-lists. The proxy enforces them, and
 * the Access Control screen reports them (`app/api/auth/posture/route.ts`); both
 * import from here, so the screen cannot show a list the proxy no longer uses.
 *
 * An allow-list per method, not a pass-through. A catch-all forwarding any path
 * would hand the browser every route on the Flask app with the console's key
 * attached for a signed-in user, and several of those are destructive or
 * expensive. Each entry below is a route a console screen actually needs; a route
 * absent from these sets is a 404 at the proxy even though it exists upstream.
 * (The public API at /api/v1/* is a different path: it carries the caller's own
 * credential and never the console's -- see lib/upstream.ts.)
 *
 * What is deliberately NOT proxied, and why:
 *
 * - `orchestrator/reset` wipes every case, event and audit record for the
 *   tenant. There is no undo, and no screen needs it -- it exists for clearing a
 *   demo from a terminal. A button for it on a page a customer can open is a
 *   button that eventually gets clicked.
 * - `orchestrator/drain` and `orchestrator/tick` advance the pipeline. The
 *   Pipeline screen already advances it as a side effect of polling
 *   `orchestrator/state?drain=1`, and a second explicit advancer racing the
 *   first is how the optimistic-lock conflicts in the last round were produced.
 * - `admin/backfill-rollups` is a one-off migration that rewrites every case in
 *   the tenant. An operator runs it deliberately, once.
 * - `internal/execute` is the cross-identity executor hop, not a browser route.
 * - `config/model` (POST) changes which model every subsequent audit runs on, for
 *   the whole service rather than per tenant.
 * - `demo` spends Nebius tokens and Tavily credits on a GET.
 */

/** Reads. Cheap, idempotent, and safe to poll. */
export const ALLOWED_GET = new Set([
  // Board and pipeline
  "orchestrator/state",
  "cases",
  "events",
  "metrics/summary",
  // Review
  "review/queue",
  // Audit trail
  "audit",
  // Governance
  "governance/agent",
  "governance/drift",
  "governance/boundaries",
  "governance/prefilter-rules",
  // Agent console
  "config/model",
  "security/attacks",
  // B2B contract surface the original console was built on
  "compliance/reports",
  "billing/usage",
  // Identity and access: who the backend thinks the caller is, and the policy it
  // enforces. Every role-dependent control on every screen is drawn from these.
  "auth/whoami",
  "auth/policy",
  // The committed benchmark and HS-classifier reports (evaluation.py), for the
  // Evaluation panel. Aggregates only.
  "evaluation",
]);

/**
 * Reads that carry an id in the path.
 *
 * Kept separate from the exact set so the id segment can be shape-checked. The
 * value is the trailing segment, or "" when the id is last.
 */
export const ALLOWED_GET_BY_ID: ReadonlyArray<readonly [string, string]> = [
  ["review", "document"], // the scanned bill of lading, for the review iframe
  ["orchestrator/case", ""], // full case trace, for the Case screen
  ["compliance/audit", ""], // one B2B audit record
];

/**
 * Writes. Each one is an action a named human takes.
 *
 * The two review routes carry a case id between segments, as in
 * `review/CASE-123/decide`, so they are matched by pattern rather than by exact
 * string -- see matchWrite.
 */
export const ALLOWED_POST = new Set([
  // Review decisions
  "review/decide",
  "review/deep-review",
  // Governance
  "governance/publish",
  "governance/revoke",
  "governance/simulate",
  "governance/verify-entity",
  // Tavily sweep for sanctions and enforcement news, from the Governance screen.
  // Governance admin upstream and rate-limited to 5/min there.
  "governance/tavily-scan",
  // DevOps
  "simulate",
  "simulate/bulk",
  "events/shipment",
  "events/document",
  // Agent console: the manual Model Armor / injection probe. Named `screen`
  // upstream; there is no `security/redteam` route despite the old dashboard's
  // label for the panel.
  "security/screen",
]);

export const ALLOWED_PUT = new Set(["governance/prefilter-rules"]);

/**
 * The id segment is checked against the case-id shape the backend issues, so a
 * path traversal cannot hide in it.
 */
export const CASE_ID = /^[A-Za-z0-9_-]{1,80}$/;

/**
 * Whether a path is an allowed write, resolving the two review routes that carry
 * a case id.
 *
 * Matched by shape rather than by substring: a `.includes("decide")` test would
 * also pass `review/../../orchestrator/reset/decide`.
 */
export function matchWrite(joined: string, allowed: Set<string>): boolean {
  const parts = joined.split("/");
  if (parts.length === 3 && parts[0] === "review" && CASE_ID.test(parts[1])) {
    if (parts[2] === "decide" || parts[2] === "deep-review") {
      return allowed.has(`review/${parts[2]}`);
    }
    return false;
  }
  // `review/decide` and `review/deep-review` are templates for the id-carrying
  // form above, not routes of their own; Flask has neither without an id.
  if (joined === "review/decide" || joined === "review/deep-review") return false;
  return allowed.has(joined);
}

/**
 * Whether a path is an allowed read, including the id-carrying ones.
 *
 * A passing shape check is not an authorisation check and is not pretending to
 * be one: the backend scopes every lookup to the caller's tenant and role, and
 * answers a foreign id with the same 404 as a missing one.
 */
export function matchRead(joined: string): boolean {
  if (ALLOWED_GET.has(joined)) return true;

  for (const [prefix, suffix] of ALLOWED_GET_BY_ID) {
    const head = `${prefix}/`;
    if (!joined.startsWith(head)) continue;
    const rest = joined.slice(head.length).split("/");

    if (suffix === "") {
      if (rest.length === 1 && CASE_ID.test(rest[0])) return true;
    } else if (rest.length === 2 && CASE_ID.test(rest[0]) && rest[1] === suffix) {
      return true;
    }
  }
  return false;
}

/**
 * Query parameters forwarded on reads. Anything else is dropped.
 *
 * `state` is singular because that is what `/cases` reads; `states` is here only
 * so a future rename does not silently return every case. `status` is the third
 * mutually-exclusive audit filter alongside `case_id` and `action` -- omitting it
 * made the Audit Trail's status filter appear to work and return unfiltered rows.
 *
 * `since` and `until` bound a billing period on `billing/usage`. Safe to forward
 * even though the tenant is not: they narrow the caller's own window and cannot
 * widen its scope.
 */
export const FORWARDED_PARAMS = [
  "limit",
  "cursor",
  "state",
  "states",
  "status",
  "case_id",
  "action",
  "min_risk",
  "outcome",
  "drain",
  "prefix",
  "since",
  "until",
];

/** Human-readable read list for the Access Control screen, id routes included. */
export function describedReads(): string[] {
  return [
    ...ALLOWED_GET,
    ...ALLOWED_GET_BY_ID.map(([prefix, suffix]) =>
      suffix ? `${prefix}/<id>/${suffix}` : `${prefix}/<id>`,
    ),
  ].sort();
}

/** Human-readable write list for the Access Control screen. */
export function describedWrites(): Array<{ method: "POST" | "PUT"; path: string }> {
  const posts = [...ALLOWED_POST].map((path) => ({
    method: "POST" as const,
    path: path.startsWith("review/") ? path.replace("review/", "review/<id>/") : path,
  }));
  const puts = [...ALLOWED_PUT].map((path) => ({ method: "PUT" as const, path }));
  return [...posts, ...puts].sort((a, b) => a.path.localeCompare(b.path));
}
