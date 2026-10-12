import { NextResponse } from "next/server";

import { cookieOptions, COOKIE_NAME } from "@/lib/session";
import { EXPIRED_TENANT_CHOICE, TENANT_COOKIE } from "@/lib/tenant-choice";

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
  // The organisation choice was this person's; the next one chooses their own.
  response.cookies.set(TENANT_COOKIE, "", EXPIRED_TENANT_CHOICE);
  return response;
}
