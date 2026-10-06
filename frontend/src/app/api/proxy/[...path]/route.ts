import { NextResponse } from "next/server";

import { flaskBase } from "@/lib/config";
import {
  ALLOWED_POST,
  ALLOWED_PUT,
  FORWARDED_PARAMS,
  matchRead,
  matchWrite,
  PASSWORD_ONLY_POST,
} from "@/lib/proxy-policy";
import {
  isPasswordSession,
  loginRequired,
  publicReads,
  type Session,
  tokenFromCookieHeader,
  verifySession,
} from "@/lib/session";
import { forwardedHeaders } from "@/lib/upstream";

/**
 * The console's BFF: the browser's only route to Flask for the screens.
 *
 * The browser talks only to this origin, which is why no CORS configuration is
 * needed on the Flask side, and why the console's credential stays on the server
 * where the browser cannot read it. What may be forwarded is in
 * lib/proxy-policy.ts; this file decides WITH WHICH CREDENTIAL.
 *
 * WHO THE REQUEST RUNS AS
 *
 * A signed-in person's request carries the console's API key plus their verified
 * session, and Flask assigns their role from its own role lists (auth.py,
 * _api_key_context). An anonymous visitor's request carries neither, so Flask
 * treats it exactly as it treats any anonymous caller: ANONYMOUS_ROLE, viewer.
 *
 * That second half is the change. The key used to be attached to every request,
 * anonymous reads included, which made every visitor a governance admin upstream
 * -- the review queue, billing and any future admin-only read were public by
 * accident, and a visitor's poll of the board ran the pipeline on the console's
 * Nebius balance. Attaching the key only alongside a verified session means the
 * console can no longer lend its authority to someone who has not signed in.
 */

function upstreamHeaders(
  request: Request,
  contentType: string | null | undefined,
  sessionToken: string | null,
): Record<string, string> {
  // The caller's address, so Flask's rate limiter keys an anonymous reader on
  // their own IP. Without it every console visitor arrives from 127.0.0.1 and
  // they share one bucket: a handful of open Pipeline tabs polling the board
  // would exhaust `orchestrator/state`'s 120/min for everyone.
  const headers: Record<string, string> = {
    ...forwardedHeaders(request),
    Accept: "application/json",
  };
  if (contentType) headers["content-type"] = contentType;

  // Only for a verified session: see the header comment. The key and the session
  // travel together or not at all. Flask refuses a session it cannot verify
  // (401) rather than falling back to the key, so sending an unverified one
  // would turn a stale cookie into an error instead of an anonymous read.
  if (sessionToken) {
    // Read from the server-side environment, never from NEXT_PUBLIC_*, so it is
    // not inlined into the browser bundle.
    const apiKey = process.env.VF_API_KEY;
    if (apiKey) headers["X-VF-API-Key"] = apiKey;

    // WHO is acting. Forwarded as the signed token rather than a bare email,
    // because a bare email is an assertion and this is evidence: Flask holds the
    // same VF_SESSION_SECRET and re-verifies the HMAC and the expiry itself.
    headers["X-VF-Session"] = sessionToken;
  }

  // Set when the console runs behind IAP with a service credential.
  const token = process.env.FLASK_API_TOKEN;
  if (token) headers.Authorization = `Bearer ${token}`;
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
 * The caller's VERIFIED session and its token, or null.
 *
 * Authorisation is checked here, not delegated to a middleware layer. The route
 * does not rely on any external matcher to protect its write paths.
 */
async function verified(
  request: Request,
): Promise<{ token: string; session: Session } | null> {
  const token = tokenFromCookieHeader(request.headers.get("cookie"));
  const session = await verifySession(token);
  return token && session ? { token, session } : null;
}

async function verifiedToken(request: Request): Promise<string | null> {
  return (await verified(request))?.token ?? null;
}

function notAuthenticated() {
  return NextResponse.json(
    { error: "not_authenticated", detail: "Sign in to continue." },
    { status: 401 },
  );
}

/** Shaped like Flask's own refusal, so the UI reads one message either way. */
function passwordRequired(session: Session) {
  return NextResponse.json(
    {
      error: "password_session_required",
      detail: "This action needs a password sign-in. Sign in with your email and password.",
      required_auth: "password",
      session_method: session.amr ?? "unknown",
    },
    { status: 403 },
  );
}

// Pinned for non-JSON responses. The backend already validates via
// SUPPORTED_MIME; duplicating the check means this origin never serves text/html
// from upstream regardless of what the backend does.
const SAFE_BINARY = new Set([
  "application/pdf",
  "image/png",
  "image/jpeg",
  "image/webp",
]);

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
      headers: upstreamHeaders(
        request,
        method === "GET" ? null : contentType,
        sessionToken,
      ),
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

  const token = await verifiedToken(request);
  // Reads may be public. An anonymous read goes upstream with no credential and
  // is answered as Flask answers any anonymous caller -- as a viewer.
  if (loginRequired() && !publicReads() && !token) return notAuthenticated();

  return forward(request, joined, "GET", token);
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  const joined = (path ?? []).join("/");

  if (!matchWrite(joined, ALLOWED_POST)) return notProxied(joined, "POST");

  const caller = await verified(request);
  // Deliberately NOT relaxed by publicReads(). Every route below either moves
  // cargo, changes the rules that decide what auto-clears, or spends money.
  if (loginRequired() && !caller) return notAuthenticated();

  // Clearing the board wants a password sign-in on top of the role. A caller
  // with no session at all only gets here in development without a secret, and
  // then reaches Flask without the key, as a viewer, and is refused there.
  if (PASSWORD_ONLY_POST.has(joined) && caller && !isPasswordSession(caller.session)) {
    return passwordRequired(caller.session);
  }

  return forward(request, joined, "POST", caller?.token ?? null);
}

export async function PUT(
  request: Request,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  const joined = (path ?? []).join("/");

  if (!ALLOWED_PUT.has(joined)) return notProxied(joined, "PUT");

  const token = await verifiedToken(request);
  if (loginRequired() && !token) return notAuthenticated();

  return forward(request, joined, "PUT", token);
}
