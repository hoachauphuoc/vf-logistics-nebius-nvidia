import { NextResponse } from "next/server";

import { flaskBase } from "@/lib/config";
import { canonicalEmail, loginAttemptVerdict } from "@/lib/login-limit";
import { verifyOperator } from "@/lib/operators";
import { cookieOptions, COOKIE_NAME, signSession, TTL_SECONDS } from "@/lib/session";
import { EXPIRED_TENANT_CHOICE, TENANT_COOKIE } from "@/lib/tenant-choice";

/**
 * Sign in an operator.
 *
 * Node runtime rather than Edge: this route runs 210,000 PBKDF2 iterations, which
 * is deliberate cost and wants a full runtime rather than an Edge CPU budget.
 */
export const runtime = "nodejs";

const REJECTED = "Email or password is incorrect.";

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

  // Normalised once, here, and this one value is what is both counted and
  // checked -- see lib/login-limit.ts for the bypass two normalisations allowed.
  const account = canonicalEmail(email);
  if (!account || !password) {
    return NextResponse.json({ error: REJECTED }, { status: 400 });
  }

  // Rate check BEFORE PBKDF2 -- an attacker that hits the limit must not burn
  // server CPU. The decoy derivation in verifyOperator (which prevents user
  // enumeration via timing) is also skipped, but timing on a 429 is not a
  // signal because the response is instant regardless of whether the email
  // exists, and the status code already says "you are being throttled".
  const verdict = await loginAttemptVerdict(account, request, flaskBase(), process.env.VF_API_KEY);
  if (verdict === "limited") {
    return NextResponse.json(
      { error: "Too many login attempts. Try again in a minute." },
      { status: 429 },
    );
  }
  if (verdict === "unavailable") {
    // No limit could be established, so no password is checked (finding R01).
    return NextResponse.json(
      { error: "Sign-in is temporarily unavailable. Try again shortly." },
      { status: 503, headers: { "Retry-After": "5" } },
    );
  }

  const verified = await verifyOperator(account, password);
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
  // A choice left by whoever signed in here before is not this person's
  // (finding R03); with several organisations the switcher asks afresh.
  response.cookies.set(TENANT_COOKIE, "", EXPIRED_TENANT_CHOICE);
  return response;
}
