import { NextRequest } from "next/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/session", () => ({
  COOKIE_NAME: "session",
  verifySession: vi.fn(async () => null),
  loginRequired: () => true,
  publicReads: () => false,
}));

import { proxy } from "./proxy";

/**
 * With public reads off, a visitor has no session yet. The login page asks /api/auth/posture whether to offer
 * the one-click judge button; if the middleware refuses that read, the button never appears and the demo has
 * no way in without a password.
 */
describe("Console middleware with public reads off", () => {
  it("lets an anonymous visitor read the sign-in posture", async () => {
    const response = await proxy(new NextRequest("http://localhost/api/auth/posture"));
    expect(response.status).not.toBe(401);
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("still refuses an anonymous read of anything else behind the console", async () => {
    const response = await proxy(new NextRequest("http://localhost/api/auth/whoami"));
    expect(response.status).toBe(401);
  });
});
