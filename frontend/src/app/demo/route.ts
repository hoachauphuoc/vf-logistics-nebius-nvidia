import { passThrough } from "@/lib/upstream";

/**
 * One sample shipment through the agents. Operator on the backend, because every
 * call is a Nebius bill -- passed through with the caller's credential, so the
 * console's own key never pays for an anonymous GET here.
 */
export const dynamic = "force-dynamic";

export function GET(request: Request): Promise<Response> {
  return passThrough(request, "/demo");
}
