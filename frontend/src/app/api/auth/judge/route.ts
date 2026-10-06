import { NextResponse } from "next/server";

import { ONE_CLICK_TTL_SECONDS, oneClickJudge } from "@/lib/one-click";
import { clientIp, slidingWindowLimiter } from "@/lib/rate-limit";
import { cookieOptions, COOKIE_NAME, signSession } from "@/lib/session";

/**
 * Sign in as the guest judge with one click. See lib/one-click.ts.
 *
 * POST, not GET. A GET that sets a session cookie can be triggered by an <img>
 * tag on any page, which would sign a visitor in without asking -- login CSRF.
 * The session cookie is SameSite=Lax, so a cross-site POST here cannot ride on an
 * existing session either; it can only mint a guest one, which is the button's
 * whole purpose.
 *
 * The session carries `amr: "one_click"`, so it is refused on the routes that
 * want a password, and it lives four hours rather than twelve.
 */
export const runtime = "nodejs";

// Generous for a person, low for a script. Every guest shares one account, and
// the backend keys its own rate limits on that account, so a script minting
// sessions in a loop gains nothing the first one did not already have.
const isRateLimited = slidingWindowLimiter(60_000, 10);

export async function POST(request: Request) {
  const judge = oneClickJudge();
  if (!judge) {
    // 404 rather than 403: when it is off, as far as a caller can tell it does
    // not exist.
    return NextResponse.json({ error: "One-click sign-in is not available." }, { status: 404 });
  }

  if (isRateLimited(clientIp(request))) {
    return NextResponse.json(
      { error: "Too many sign-in attempts. Try again in a minute." },
      { status: 429 },
    );
  }

  const token = await signSession(judge.email, "one_click", ONE_CLICK_TTL_SECONDS);
  if (!token) {
    return NextResponse.json(
      { error: "Sign-in is not configured on this server." },
      { status: 500 },
    );
  }

  const response = NextResponse.json({ email: judge.email, amr: "one_click" });
  response.cookies.set(COOKIE_NAME, token, cookieOptions(ONE_CLICK_TTL_SECONDS));
  return response;
}
