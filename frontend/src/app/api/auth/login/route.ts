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

/**
 * A single message for every rejection.
 *
 * "No such operator" and "wrong password" are the same answer on purpose --
 * distinguishing them turns the login into a directory of who has an account,
 * which for this product is also the customer list.
 */
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

  if (!email || !password) {
    return NextResponse.json({ error: REJECTED }, { status: 400 });
  }

  const verified = await verifyOperator(email, password);
  if (!verified) {
    return NextResponse.json({ error: REJECTED }, { status: 401 });
  }

  const token = await signSession(verified);
  if (!token) {
    // A correct password that cannot be turned into a session is a server fault,
    // not a failed login, and saying so plainly is what makes it fixable. It
    // means VF_SESSION_SECRET is unset or shorter than 32 characters.
    return NextResponse.json(
      { error: "Sign-in is not configured on this server." },
      { status: 500 },
    );
  }

  const response = NextResponse.json({ email: verified });
  response.cookies.set(COOKIE_NAME, token, cookieOptions(TTL_SECONDS));
  return response;
}
