import { NextResponse, type NextRequest } from "next/server";

import { COOKIE_NAME, loginRequired, publicReads, verifySession } from "@/lib/session";

/**
 * The door.
 *
 * Every request passes through here, and anything without a valid session is
 * turned away before it reaches a page or the API proxy. This is what stops the
 * deployed console handing GOVERNANCE_ADMIN to anonymous visitors: the API proxy
 * attaches VF_API_KEY server-side to every forwarded request, so without a door
 * in front of it the key is effectively public.
 *
 * NAMING, because there are now two things called "proxy" in this codebase and
 * they are unrelated:
 *
 *   - THIS file is Next 16's request interceptor, the convention that replaced
 *     `middleware.ts`. It runs on the Edge runtime before routing.
 *   - `src/app/api/proxy/[...path]/route.ts` is our own allow-listed forwarder to
 *     the Flask API. Nothing to do with this file beyond being protected by it.
 *
 * That route checks the session again for itself. The duplication is deliberate --
 * a mistake in the matcher below would otherwise silently reopen every write
 * route, and a matcher is exactly the kind of thing that gets edited without
 * being re-reasoned about.
 */

/** Paths reachable with no session. Kept short on purpose. */
const PUBLIC_PATHS = new Set([
  "/login",
  "/api/auth/login",
  "/api/auth/logout",
  // Terms a customer can only read after signing in are terms they cannot read
  // before agreeing to them.
  "/legal",
]);

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (PUBLIC_PATHS.has(pathname)) return NextResponse.next();

  // Development convenience only: with no VF_SESSION_SECRET configured and not
  // running a production build, there is no login. loginRequired() returns true
  // unconditionally in production, so this cannot disable the door where it
  // matters -- a missing secret there takes the console offline instead.
  if (!loginRequired()) return NextResponse.next();

  // Reads may be public; writes never are.
  //
  // Scoped to the METHOD rather than to a path list on purpose. A path list would
  // have to be kept in step with the API proxy's own allow-list, and the two
  // drifting apart is how a write route ends up readable by anyone. The HTTP
  // method is the one signal that cannot drift.
  //
  // HEAD is included because it is a GET without a body; OPTIONS is not, because
  // nothing here answers a preflight -- the browser talks to this origin only.
  if (publicReads() && (request.method === "GET" || request.method === "HEAD")) {
    return NextResponse.next();
  }

  const session = await verifySession(request.cookies.get(COOKIE_NAME)?.value);
  if (session) return NextResponse.next();

  // An API call gets a status, not a redirect. fetch() follows redirects
  // transparently, so answering /api/proxy/... with a 302 to /login hands the
  // caller an HTML page with status 200, and the UI reports a JSON parse error
  // instead of "signed out".
  if (pathname.startsWith("/api/")) {
    return NextResponse.json(
      { error: "not_authenticated", detail: "Sign in to continue." },
      { status: 401 },
    );
  }

  const login = request.nextUrl.clone();
  login.pathname = "/login";
  login.search = "";
  // Preserved so an expired session returns to the screen it was on. Path and
  // query only -- never the full URL, which would be echoed back into a redirect.
  login.searchParams.set("next", `${pathname}${request.nextUrl.search}`);
  return NextResponse.redirect(login);
}

export const config = {
  /**
   * Everything except Next's own static output and the files browsers request
   * unprompted.
   *
   * `_next/static` and `_next/image` are excluded because they are public build
   * artefacts and running an HMAC over every one of them would cost latency on
   * every page load for no gain. Note what is NOT excluded: `/api/*` is inside
   * the matcher, which is the point.
   */
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml).*)",
  ],
};
