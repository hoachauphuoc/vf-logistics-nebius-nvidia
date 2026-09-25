import { NextResponse } from "next/server";

import { verifyOperator } from "@/lib/operators";
import { cookieOptions, COOKIE_NAME, signSession, TTL_SECONDS } from "@/lib/session";

/**
 * Sign in an operator.
 *
 * Node runtime rather than Edge: this route runs 210,000 PBKDF2 iterations, which
 * is deliberate cost and wants a full runtime rather than an Edge CPU budget.
 */
export const runtime = "nodejs";

const REJECTED = "Email or password is incorrect.";

// ---------------------------------------------------------------------------
// In-memory sliding-window rate limiter.
//
// Keyed on (IP, email): per-IP so a single source cannot exhaust the CPU with
// PBKDF2 iterations, and per-email so a distributed credential-stuff against
// one account is also bounded. Both halves must be present, because email-only
// keys let an attacker lock out a legitimate user by spraying their address.
//
// Per-instance (not shared across Cloud Run instances), same trade-off as the
// backend's memory:// limiter -- the real ceiling is LIMIT * instance count.
// ---------------------------------------------------------------------------
const WINDOW_MS = 60_000;
const LIMIT = 5;
const attempts = new Map<string, number[]>();

function isRateLimited(ip: string, email: string): boolean {
  const now = Date.now();
  const key = `${ip}|${email.toLowerCase()}`;
  let timestamps = attempts.get(key);
  if (!timestamps) {
    timestamps = [];
    attempts.set(key, timestamps);
  }
  // Evict expired entries.
  while (timestamps.length > 0 && timestamps[0] <= now - WINDOW_MS) {
    timestamps.shift();
  }
  if (timestamps.length >= LIMIT) return true;
  timestamps.push(now);
  return false;
}

// Periodic cleanup so the map does not grow unbounded on a long-lived instance.
setInterval(() => {
  const cutoff = Date.now() - WINDOW_MS;
  for (const [key, ts] of attempts) {
    while (ts.length > 0 && ts[0] <= cutoff) ts.shift();
    if (ts.length === 0) attempts.delete(key);
  }
}, WINDOW_MS);

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
  const ip =
    request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ?? "unknown";
  if (isRateLimited(ip, email)) {
    return NextResponse.json(
      { error: "Too many login attempts. Try again in a minute." },
      { status: 429 },
    );
  }

  const verified = await verifyOperator(email, password);
  if (!verified) {
    return NextResponse.json({ error: REJECTED }, { status: 401 });
  }

  const token = await signSession(verified);
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
