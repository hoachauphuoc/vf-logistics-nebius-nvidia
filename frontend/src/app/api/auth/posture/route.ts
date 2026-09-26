import { NextResponse } from "next/server";

import { loginRequired, publicReads, verifySession } from "@/lib/session";

const ROLE_HIERARCHY = [
  { role: "viewer", includes: ["viewer"] },
  { role: "reviewer", includes: ["viewer", "reviewer"] },
  { role: "operator", includes: ["viewer", "reviewer", "operator"] },
  {
    role: "governance_admin",
    includes: ["viewer", "reviewer", "operator", "governance_admin"],
  },
];

const PROXY_READS = [
  "orchestrator/state",
  "cases",
  "events",
  "metrics/summary",
  "review/queue",
  "audit",
  "governance/agent",
  "governance/drift",
  "governance/boundaries",
  "governance/prefilter-rules",
  "config/model",
  "security/attacks",
  "compliance/reports",
  "billing/usage",
];

const PROXY_WRITES = [
  "review/{id}/decide",
  "review/{id}/deep-review",
  "governance/publish",
  "governance/revoke",
  "governance/simulate",
  "governance/verify-entity",
  "governance/prefilter-rules (PUT)",
  "simulate",
  "simulate/bulk",
  "events/shipment",
  "events/document",
  "security/screen",
];

export async function GET(request: Request) {
  const cookie = request.headers.get("cookie") ?? "";
  const match = cookie.match(/vf_session=([^;]+)/);
  const session = match ? await verifySession(match[1]) : null;

  return NextResponse.json({
    auth: {
      login_required: loginRequired(),
      public_reads: publicReads(),
      session: session
        ? { email: session.email, expires: session.exp }
        : null,
    },
    roles: ROLE_HIERARCHY,
    proxy: {
      reads: PROXY_READS,
      writes: PROXY_WRITES,
    },
  });
}
