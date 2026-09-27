import { flaskBase } from "@/lib/config";

/**
 * Transport to the Flask process, shared by the two ways a request reaches it.
 *
 * - `/api/proxy/*` is the console's BFF (`app/api/proxy/[...path]/route.ts`): an
 *   allow-list, and the only place the console's own credential is ever attached.
 * - `/api/v1/*`, `/health`, `/metrics` and `/demo` are the public API, passed
 *   through with the CALLER'S credential and nothing else. An integrator's API key
 *   reaches Flask exactly as they sent it; a request without one reaches Flask
 *   without one, where auth.py treats it as anonymous. Flask was public on its own
 *   Cloud Run service before the two were merged, so this is the same surface at
 *   one URL -- not a wider one.
 *
 * Flask binds 127.0.0.1 inside the container (entrypoint.sh), so these two routes
 * are the only way in.
 */

/**
 * Request headers this hop must not pass along.
 *
 * Hop-by-hop headers (RFC 9110 section 7.6.1) belong to the connection they
 * arrived on. `host` and `content-length` are recomputed by fetch for the new
 * connection. `cookie` is the console's session: Flask never reads cookies, and
 * an API caller's request has no business carrying a console session into it.
 * The two x-forwarded headers are replaced below with values this hop can vouch
 * for, because a client-supplied X-Forwarded-Host would otherwise become the
 * `servers` URL in the OpenAPI document Flask builds from `request.url_root`.
 */
const DROP_REQUEST = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-length",
  "cookie",
  "x-forwarded-host",
  "x-forwarded-proto",
]);

/**
 * Response headers not copied back. `content-encoding` and `content-length`
 * describe the upstream bytes, and fetch has already decoded them. Flask sets no
 * cookies; dropping `set-cookie` keeps it that way if one ever appears.
 */
const DROP_RESPONSE = new Set([
  "connection",
  "keep-alive",
  "transfer-encoding",
  "trailer",
  "upgrade",
  "content-encoding",
  "content-length",
  "set-cookie",
]);

/** gunicorn's --timeout. A document upload runs extraction plus two agent hops. */
export const PASS_THROUGH_TIMEOUT_MS = 300_000;

/**
 * Whether a path belongs to the public API pass-through rather than the console.
 *
 * Flask authorises these itself -- an integrator presents X-VF-API-Key, an
 * anonymous caller is a viewer -- so a console session means nothing here, and a
 * redirect to /login would break every API client. proxy.ts consults this AND
 * excludes the same paths in its matcher: the matcher is what stops Next
 * buffering an upload's body for that function, and this check is what stops a
 * matcher edit from putting the login wall in front of the API.
 */
export function isApiPassThrough(pathname: string): boolean {
  return (
    pathname === "/api/v1" ||
    pathname.startsWith("/api/v1/") ||
    pathname === "/health" ||
    pathname === "/metrics" ||
    pathname === "/demo"
  );
}

/**
 * The client's address and the public origin, for Flask's ProxyFix.
 *
 * X-Forwarded-For is passed on UNCHANGED. Cloud Run's front end appends the
 * address it saw, and app.py trusts exactly one hop (`x_for=1`), i.e. that last
 * entry. Appending this hop's own peer would make every caller look like the
 * front end, and put them all in one rate-limit bucket -- the failure app.py's
 * ProxyFix comment describes. Without this header at all, every anonymous caller
 * would share `ip:127.0.0.1`.
 *
 * The host is the one the request arrived with, which Cloud Run routes on and a
 * client cannot choose freely. The scheme is the last X-Forwarded-Proto entry,
 * or the URL's own when there is none (local development).
 */
export function forwardedHeaders(request: Request): Record<string, string> {
  const out: Record<string, string> = {};
  const forwardedFor = request.headers.get("x-forwarded-for");
  if (forwardedFor) out["x-forwarded-for"] = forwardedFor;

  const host = request.headers.get("host");
  if (host) out["x-forwarded-host"] = host;

  const claimed = request.headers.get("x-forwarded-proto");
  const proto = claimed
    ? (claimed.split(",").pop() ?? "").trim()
    : new URL(request.url).protocol.replace(/:$/, "");
  if (proto === "http" || proto === "https") out["x-forwarded-proto"] = proto;
  return out;
}

/**
 * Validate the segments of a catch-all route before they become a path.
 *
 * The upstream path is built from these segments, never from the raw request
 * path, so a percent-encoded `..` cannot walk out of `/api/v1/` and into a route
 * that is deliberately not exposed (`/internal/execute`, `/legacy`).
 */
export function safeSegments(segments: string[] | undefined): string[] | null {
  const parts = segments ?? [];
  if (parts.length === 0) return null;
  for (const part of parts) {
    if (part === "" || part === "." || part === "..") return null;
    if (part.includes("/") || part.includes("\\")) return null;
  }
  return parts;
}

export function upstreamPath(prefix: string, segments: string[]): string {
  return `${prefix}/${segments.map(encodeURIComponent).join("/")}`;
}

function failure(status: 502 | 504, error: string, detail: string): Response {
  return Response.json({ error, detail }, { status });
}

/**
 * Forward `request` to Flask at `path`, streaming both bodies.
 *
 * `redirect: "manual"` so an upstream redirect reaches the caller as a redirect
 * rather than being followed here with the caller's credential attached.
 */
export async function passThrough(request: Request, path: string): Promise<Response> {
  const incoming = new URL(request.url);
  const target = `${flaskBase()}${path}${incoming.search}`;

  const headers = new Headers();
  request.headers.forEach((value, name) => {
    if (!DROP_REQUEST.has(name.toLowerCase())) headers.set(name, value);
  });
  for (const [name, value] of Object.entries(forwardedHeaders(request))) {
    headers.set(name, value);
  }

  const method = request.method.toUpperCase();
  const init: RequestInit & { duplex?: "half" } = {
    method,
    headers,
    redirect: "manual",
    cache: "no-store",
    signal: AbortSignal.timeout(PASS_THROUGH_TIMEOUT_MS),
  };
  if (method !== "GET" && method !== "HEAD") {
    init.body = request.body;
    // Required by undici whenever a stream is the body.
    init.duplex = "half";
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, init);
  } catch (error) {
    const timedOut = error instanceof Error && error.name === "TimeoutError";
    return timedOut
      ? failure(504, "upstream_timeout", `No answer within ${PASS_THROUGH_TIMEOUT_MS / 1000}s.`)
      : failure(502, "upstream_unreachable", error instanceof Error ? error.message : String(error));
  }

  const out = new Headers();
  upstream.headers.forEach((value, name) => {
    if (!DROP_RESPONSE.has(name.toLowerCase())) out.set(name, value);
  });
  return new Response(method === "HEAD" ? null : upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: out,
  });
}
