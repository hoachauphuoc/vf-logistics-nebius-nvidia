import { NextResponse } from "next/server";

import { flaskBase } from "@/lib/config";
import {
  COOKIE_NAME,
  loginRequired,
  publicReads,
  verifySession,
} from "@/lib/session";

/**
 * Proxy to the Flask API.
 *
 * The browser talks only to this origin, which is why no CORS configuration is
 * needed on the Flask side, and why the upstream credential stays on the server
 * where the browser cannot read it.
 *
 * An allow-list per method, not a pass-through. A catch-all forwarding any path
 * would hand the browser every route on the Flask app, and several of those are
 * destructive or expensive. Each entry below is a route one of the six console
 * screens actually needs; a route absent from these sets is a 404 here even
 * though it exists upstream.
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
 * - `internal/execute` is the cross-identity executor hop. It is reachable only
 *   with `run.invoker` on a service deployed --no-allow-unauthenticated, and
 *   proxying it from a browser origin would be the one thing that design exists
 *   to prevent.
 * - `config/model` (PUT) changes which model every subsequent audit runs on, for
 *   the whole service rather than per tenant.
 * - `demo` spends Nebius tokens and Tavily credits on an unauthenticated GET.
 */

/** Reads. Cheap, idempotent, and safe to poll. */
const ALLOWED_GET = new Set([
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
]);

/**
 * Reads that carry an id in the path.
 *
 * Kept separate from the exact set so the id segment can be shape-checked. The
 * value is the trailing segment, or "" when the id is last.
 */
const ALLOWED_GET_BY_ID: Array<[string, string]> = [
  ["review", "document"], // the scanned bill of lading, for the review iframe
  ["orchestrator/case", ""], // full case trace, for the Case screen
  ["compliance/audit", ""], // one B2B audit record
];

/**
 * Writes the six screens need. Each one is an action a named human takes.
 *
 * The two review routes carry a case id between segments, as in
 * `review/CASE-123/decide`, so they are matched by pattern rather than by exact
 * string -- see matchWrite.
 */
const ALLOWED_POST = new Set([
  // Review decisions
  "review/decide",
  "review/deep-review",
  // Governance
  "governance/publish",
  "governance/revoke",
  "governance/simulate",
  "governance/verify-entity",
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

const ALLOWED_PUT = new Set(["governance/prefilter-rules"]);

/**
 * Whether a path is an allowed write, resolving the two review routes that
 * carry a case id.
 *
 * Matched by shape rather than by substring: a `.includes("decide")` test would
 * also pass `review/../../orchestrator/reset/decide`. The id segment is checked
 * against the case-id shape the backend issues so a path traversal cannot hide
 * in it.
 */
const CASE_ID = /^[A-Za-z0-9_-]{1,80}$/;

function matchWrite(joined: string, allowed: Set<string>): boolean {
  if (allowed.has(joined)) return true;

  const parts = joined.split("/");
  if (parts.length === 3 && parts[0] === "review" && CASE_ID.test(parts[1])) {
    if (parts[2] === "decide" || parts[2] === "deep-review") {
      return allowed.has(`review/${parts[2]}`);
    }
  }
  return false;
}

/**
 * Whether a path is an allowed read, including the id-carrying ones.
 *
 * The id is shape-checked against what the backend issues rather than merely
 * being non-empty, so `..` cannot appear in it. Note that a passing shape check
 * is not an authorisation check and is not pretending to be one: the backend
 * scopes every lookup to the caller's tenant and answers a foreign id with the
 * same 404 as a missing one.
 */
function matchRead(joined: string): boolean {
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
const FORWARDED_PARAMS = [
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

function upstreamHeaders(
  contentType: string | null | undefined,
  sessionToken: string | null,
): Record<string, string> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (contentType) headers["content-type"] = contentType;

  // The shared secret that makes a write reachable from the console and not by
  // curling the backend directly.
  //
  // Read from the server-side environment, never from NEXT_PUBLIC_*, so it is
  // not inlined into the browser bundle. This is the whole reason the console
  // proxies rather than letting the browser talk to Flask: the browser cannot
  // hold a credential it must not leak.
  //
  // Absent in local development, where the backend's ANONYMOUS_ROLE grants what
  // is needed against a memory store. Absent in production means reads work and
  // every write returns 403 -- so if the console can list cases but cannot
  // decide one, VF_API_KEY is missing here.
  const apiKey = process.env.VF_API_KEY;
  if (apiKey) headers["X-VF-API-Key"] = apiKey;

  // Set when the console runs behind IAP with a service credential. Absent in
  // local development, where Flask synthesises a dev identity.
  const token = process.env.FLASK_API_TOKEN;
  if (token) headers.Authorization = `Bearer ${token}`;

  // WHO is acting, as distinct from WHAT is calling.
  //
  // The API key above answers "this request came from our console". It cannot
  // answer "this person clicked it", and before this header every console action
  // was recorded in the audit trail as `service:api-key` -- so a compliance
  // product sold on its audit trail could not say who released a shipment.
  //
  // The session token is forwarded rather than a bare email header because a bare
  // email is an assertion and this is evidence: the backend holds the same
  // VF_SESSION_SECRET and re-verifies the HMAC and the expiry itself. A caller who
  // stole the API key still cannot name a person without also forging a signature.
  if (sessionToken) headers["X-VF-Session"] = sessionToken;
  return headers;
}

function unreachable(error: unknown) {
  // Surfaced as a distinct status so the UI can say "the API is unreachable"
  // rather than rendering an empty table, which would read as "no audits".
  return NextResponse.json(
    {
      error: "upstream_unreachable",
      detail: error instanceof Error ? error.message : String(error),
    },
    { status: 502 },
  );
}

function notProxied(joined: string, method: string) {
  return NextResponse.json(
    { error: `Path not proxied for ${method}: ${joined}` },
    { status: 404 },
  );
}

/**
 * The caller's session, or null.
 *
 * Authorisation is checked here, not delegated to a middleware layer. The route
 * does not rely on any external matcher to protect its write paths.
 */
async function session(request: Request) {
  const header = request.headers.get("cookie") ?? "";
  const match = header
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${COOKIE_NAME}=`));
  const token = match ? match.slice(COOKIE_NAME.length + 1) : null;
  return { token, value: await verifySession(token) };
}

function notAuthenticated() {
  return NextResponse.json(
    { error: "not_authenticated", detail: "Sign in to continue." },
    { status: 401 },
  );
}

async function forward(
  request: Request,
  joined: string,
  method: "GET" | "POST" | "PUT",
  sessionToken: string | null,
) {
  const incoming = new URL(request.url);
  const upstream = new URL(`${flaskBase()}/api/v1/${joined}`);
  // No tenant parameter is forwarded, and adding one would not work: the server
  // derives the tenant from the authenticated identity and ignores any supplied
  // value. That is the whole point of deriving it there.
  for (const key of FORWARDED_PARAMS) {
    const value = incoming.searchParams.get(key);
    if (value !== null) upstream.searchParams.set(key, value);
  }

  const contentType = request.headers.get("content-type");

  try {
    const init: RequestInit = {
      method,
      headers: upstreamHeaders(method === "GET" ? null : contentType, sessionToken),
      cache: "no-store",
      // Longer than the read timeout. A document upload runs extraction and two
      // agent hops before it answers, and a 15s ceiling turned a working upload
      // into a client-side error while the server carried on and created the case.
      signal: AbortSignal.timeout(method === "GET" ? 15_000 : 120_000),
    };

    if (method !== "GET") {
      // Streamed rather than buffered, so a multipart upload does not have to be
      // read into memory here to be passed along.
      init.body = request.body;
      // Required by undici whenever a stream is used as a body.
      (init as RequestInit & { duplex: "half" }).duplex = "half";
    }

    const response = await fetch(upstream, init);

    // The upstream content type is preserved rather than asserted as JSON.
    // `review/<id>/document` returns the scanned bill of lading as a PDF, and
    // labelling that application/json made the browser download it instead of
    // rendering it in the review iframe. Bytes rather than text for the same
    // reason -- decoding a PDF as UTF-8 corrupts it.
    const rawContentType =
      response.headers.get("content-type") ?? "application/json";

    // Pin non-JSON responses to safe MIME types. The backend already validates
    // via SUPPORTED_MIME, but duplicating the check here means the console's
    // own origin never serves text/html from upstream regardless of what the
    // backend does (defence-in-depth, not belt-and-suspenders).
    const SAFE_BINARY = new Set([
      "application/pdf",
      "image/png",
      "image/jpeg",
      "image/webp",
    ]);
    const isJson = rawContentType.includes("json");
    const contentTypeOut = isJson
      ? rawContentType
      : SAFE_BINARY.has(rawContentType.split(";")[0].trim())
        ? rawContentType
        : "application/octet-stream";

    const headersOut: Record<string, string> = {
      "content-type": contentTypeOut,
      "x-content-type-options": "nosniff",
    };
    // Needed for the PDF to render inline rather than prompting a save.
    const disposition = response.headers.get("content-disposition");
    if (disposition) headersOut["content-disposition"] = disposition;

    const payload = isJson
      ? await response.text()
      : await response.arrayBuffer();

    return new NextResponse(payload, {
      status: response.status,
      headers: headersOut,
    });
  } catch (error) {
    return unreachable(error);
  }
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  const joined = (path ?? []).join("/");

  if (!matchRead(joined)) return notProxied(joined, "GET");

  const { token, value } = await session(request);
  // Reads may be public. The token is still forwarded when there IS one, so a
  // signed-in reader's requests stay attributable even though an anonymous
  // reader's are not.
  if (loginRequired() && !publicReads() && !value) return notAuthenticated();

  return forward(request, joined, "GET", token);
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  const joined = (path ?? []).join("/");

  if (!matchWrite(joined, ALLOWED_POST)) return notProxied(joined, "POST");

  const { token, value } = await session(request);
  // Deliberately NOT relaxed by publicReads(). Every route below either moves
  // cargo, changes the rules that decide what auto-clears, or spends money.
  if (loginRequired() && !value) return notAuthenticated();

  return forward(request, joined, "POST", token);
}

export async function PUT(
  request: Request,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  const joined = (path ?? []).join("/");

  if (!ALLOWED_PUT.has(joined)) return notProxied(joined, "PUT");

  const { token, value } = await session(request);
  if (loginRequired() && !value) return notAuthenticated();

  return forward(request, joined, "PUT", token);
}
