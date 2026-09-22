import { NextResponse } from "next/server";

import { cookieOptions, COOKIE_NAME } from "@/lib/session";

/**
 * Sign out.
 *
 * POST rather than GET so a link or a prefetch cannot end someone's session.
 */
export async function POST() {
  const response = NextResponse.json({ ok: true });
  // Overwritten with an immediate expiry rather than deleted, so a client that
  // ignores deletion still holds a cookie the server will reject.
  response.cookies.set(COOKIE_NAME, "", cookieOptions(0));
  return response;
}
