import { NextResponse } from "next/server";

import { describedReads, describedWrites } from "@/lib/proxy-policy";
import { COOKIE_NAME, loginRequired, publicReads, verifySession } from "@/lib/session";

/**
 * The console half of the access posture, for the Access Control screen.
 *
 * Only what the CONSOLE decides lives here: whether sign-in is required, whether
 * anonymous reads are allowed, the caller's own session, and what the BFF will
 * forward. The roles and which routes need which role are the backend's to
 * report (`/api/proxy/auth/whoami`, `/api/proxy/auth/policy`), and they used to
 * be hand-copied into this file -- the reads list here was already missing the
 * three id-carrying routes the proxy forwarded. The lists now come from
 * lib/proxy-policy.ts, which the proxy itself enforces.
 */
export async function GET(request: Request) {
  const header = request.headers.get("cookie") ?? "";
  const match = header
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${COOKIE_NAME}=`));
  const session = await verifySession(match ? match.slice(COOKIE_NAME.length + 1) : null);

  return NextResponse.json({
    auth: {
      login_required: loginRequired(),
      public_reads: publicReads(),
      // Epoch seconds, under the same name the session route uses.
      session: session ? { email: session.email, exp: session.exp } : null,
    },
    proxy: {
      reads: describedReads(),
      writes: describedWrites(),
    },
  });
}
