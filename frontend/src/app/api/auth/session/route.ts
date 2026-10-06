import { NextResponse } from "next/server";

import { tokenFromCookieHeader, verifySession } from "@/lib/session";

/**
 * Who is signed in.
 *
 * Exists so the header can name the person whose address every decision will be
 * recorded under. Returns 401 rather than an empty body when there is no session,
 * so the UI can tell "signed out" from "not loaded yet".
 *
 * Note the cookie is HttpOnly and therefore unreadable from JavaScript -- which is
 * the reason this endpoint is needed at all rather than the client decoding its
 * own token.
 */
export async function GET(request: Request) {
  const session = await verifySession(tokenFromCookieHeader(request.headers.get("cookie")));
  if (!session) {
    return NextResponse.json({ error: "not_authenticated" }, { status: 401 });
  }

  // `exp` is returned so the UI could warn before a session lapses mid-review.
  // `amr` (how they signed in) is null for a token that predates the claim, which
  // the UI must read the same way the backend does: not a password sign-in.
  return NextResponse.json({ email: session.email, exp: session.exp, amr: session.amr ?? null });
}
