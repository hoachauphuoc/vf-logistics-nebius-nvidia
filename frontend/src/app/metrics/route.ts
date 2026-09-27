import { passThrough } from "@/lib/upstream";

/** Flask's in-process metrics. Viewer on the backend, like every other read. */
export const dynamic = "force-dynamic";

export function GET(request: Request): Promise<Response> {
  return passThrough(request, "/metrics");
}
