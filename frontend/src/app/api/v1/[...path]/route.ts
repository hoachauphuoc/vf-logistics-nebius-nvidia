import { passThrough, safeSegments, upstreamPath } from "@/lib/upstream";

/**
 * The public B2B API, at the same URL as the console.
 *
 * Passed through with the caller's own credential, never the console's: see
 * lib/upstream.ts. Authorisation is Flask's -- an integrator's X-VF-API-Key is
 * checked there, and a request without one is anonymous (viewer) there. Nothing
 * in this file decides who may do what.
 *
 * Every method is exported so Flask, not Next, answers an unsupported one: a 405
 * from the API is the API's own statement about the route, where a 404 from here
 * would claim the route does not exist.
 */
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ path?: string[] }> };

async function handle(request: Request, { params }: Params): Promise<Response> {
  const segments = safeSegments((await params).path);
  if (!segments) {
    return Response.json({ error: "not_found" }, { status: 404 });
  }
  return passThrough(request, upstreamPath("/api/v1", segments));
}

export const GET = handle;
export const HEAD = handle;
export const POST = handle;
export const PUT = handle;
export const PATCH = handle;
export const DELETE = handle;
export const OPTIONS = handle;
