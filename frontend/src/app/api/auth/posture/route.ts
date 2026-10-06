import { NextResponse } from "next/server";

import { describedReads, describedWrites } from "@/lib/proxy-policy";
import { oneClickJudge } from "@/lib/one-click";
import { loginRequired, publicReads, tokenFromCookieHeader, verifySession } from "@/lib/session";

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
  const session = await verifySession(tokenFromCookieHeader(request.headers.get("cookie")));

  return NextResponse.json({
    auth: {
      login_required: loginRequired(),
      public_reads: publicReads(),
      // Epoch seconds, under the same name the session route uses.
      session: session
        ? { email: session.email, exp: session.exp, amr: session.amr ?? null }
        : null,
      // Whether the login page and the board should offer the judge button.
      // A boolean only: which account it signs in as is not the screen's business.
      one_click_judge: oneClickJudge() !== null,
    },
    proxy: {
      reads: describedReads(),
      writes: describedWrites(),
    },
  });
}
