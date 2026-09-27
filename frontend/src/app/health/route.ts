import { passThrough } from "@/lib/upstream";

/**
 * Flask's liveness endpoint, through Next.
 *
 * Answering here proves both processes are up: Next served the request and Flask
 * answered it. That is what the uptime check and the container smoke test want,
 * and why neither probes Flask's port directly.
 */
export const dynamic = "force-dynamic";

export function GET(request: Request): Promise<Response> {
  return passThrough(request, "/health");
}

export function HEAD(request: Request): Promise<Response> {
  return passThrough(request, "/health");
}
