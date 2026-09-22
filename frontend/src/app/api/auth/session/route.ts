import { NextResponse } from "next/server";

import { COOKIE_NAME, verifySession } from "@/lib/session";

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
  const cookie = request.headers.get("cookie") ?? "";
  const match = cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${COOKIE_NAME}=`));

  const session = await verifySession(
    match ? match.slice(COOKIE_NAME.length + 1) : null,
  );
  if (!session) {
    return NextResponse.json({ error: "not_authenticated" }, { status: 401 });
  }

  // `exp` is returned so the UI could warn before a session lapses mid-review.
  return NextResponse.json({ email: session.email, exp: session.exp });
}
