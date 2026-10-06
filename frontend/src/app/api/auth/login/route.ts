import { NextResponse } from "next/server";

import { verifyOperator } from "@/lib/operators";
import { clientIp, slidingWindowLimiter } from "@/lib/rate-limit";
import { cookieOptions, COOKIE_NAME, signSession, TTL_SECONDS } from "@/lib/session";

/**
 * Sign in an operator.
 *
 * Node runtime rather than Edge: this route runs 210,000 PBKDF2 iterations, which
 * is deliberate cost and wants a full runtime rather than an Edge CPU budget.
 */
export const runtime = "nodejs";

const REJECTED = "Email or password is incorrect.";

// Keyed on (IP, email): per-IP so a single source cannot exhaust the CPU with
// PBKDF2 iterations, and per-email so a distributed credential-stuff against
// one account is also bounded. Both halves must be present, because email-only
// keys let an attacker lock out a legitimate user by spraying their address.
const isRateLimited = slidingWindowLimiter(60_000, 5);

export async function POST(request: Request) {
  let email = "";
  let password = "";

  try {
    const body = (await request.json()) as { email?: unknown; password?: unknown };
    email = typeof body.email === "string" ? body.email : "";
    password = typeof body.password === "string" ? body.password : "";
  } catch {
    return NextResponse.json({ error: REJECTED }, { status: 400 });
  }

  if (!email || !password) {
    return NextResponse.json({ error: REJECTED }, { status: 400 });
  }

  // Rate check BEFORE PBKDF2 -- an attacker that hits the limit must not burn
  // server CPU. The decoy derivation in verifyOperator (which prevents user
  // enumeration via timing) is also skipped, but timing on a 429 is not a
  // signal because the response is instant regardless of whether the email
  // exists, and the status code already says "you are being throttled".
  if (isRateLimited(`${clientIp(request)}|${email.toLowerCase()}`)) {
    return NextResponse.json(
      { error: "Too many login attempts. Try again in a minute." },
      { status: 429 },
    );
  }

  const verified = await verifyOperator(email, password);
  if (!verified) {
    return NextResponse.json({ error: REJECTED }, { status: 401 });
  }

  // A password sign-in, and the token says so: the board can only be cleared
  // from a session carrying this claim.
  const token = await signSession(verified, "password");
  if (!token) {
    return NextResponse.json(
      { error: "Sign-in is not configured on this server." },
      { status: 500 },
    );
  }

  const response = NextResponse.json({ email: verified });
  response.cookies.set(COOKIE_NAME, token, cookieOptions(TTL_SECONDS));
  return response;
}
