// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/operators", () => ({ verifyOperator: vi.fn(async () => null) }));

import { resetLocalLoginLimits } from "@/lib/login-limit";
import { verifyOperator } from "@/lib/operators";

import { POST } from "./route";

/**
 * Re-review finding R01 at the route: when the shared attempt counter cannot
 * answer, the password is not checked at all -- a 503, not a 401 from a
 * PBKDF2 run that a weaker counter let through.
 */

function signIn(email = "judge@x.example") {
  return POST(new Request("https://vf.example/api/auth/login", {
    method: "POST",
    headers: { "content-type": "application/json", "x-forwarded-for": "203.0.113.20" },
    body: JSON.stringify({ email, password: "wrong" }),
  }));
}

describe("POST /api/auth/login", () => {
  beforeEach(() => {
    resetLocalLoginLimits();
    vi.mocked(verifyOperator).mockClear();
    vi.stubEnv("VF_API_KEY", "console-key");
    vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it("refuses with 503 and checks no password when the counter cannot answer", async () => {
    globalThis.fetch = vi.fn(async () => new Response("no", { status: 400 })) as unknown as typeof fetch;
    const response = await signIn();
    expect(response.status).toBe(503);
    expect(response.headers.get("retry-after")).toBe("5");
    expect(verifyOperator).not.toHaveBeenCalled();
  });

  it("refuses with 429 and checks no password when the counter says limited", async () => {
    globalThis.fetch = vi.fn(async () => Response.json({ limited: true })) as unknown as typeof fetch;
    expect((await signIn()).status).toBe(429);
    expect(verifyOperator).not.toHaveBeenCalled();
  });

  it("checks the password when the counter allows the attempt", async () => {
    globalThis.fetch = vi.fn(async () => Response.json({ limited: false })) as unknown as typeof fetch;
    expect((await signIn()).status).toBe(401);
    expect(verifyOperator).toHaveBeenCalledWith("judge@x.example", "wrong");
  });

  it("forgets the previous person's organisation choice on a successful sign-in (R03)", async () => {
    vi.stubEnv("VF_SESSION_SECRET", "test-session-secret-do-not-ship-0123456789abcdef");
    vi.mocked(verifyOperator).mockResolvedValueOnce("judge@x.example");
    globalThis.fetch = vi.fn(async () => Response.json({ limited: false })) as unknown as typeof fetch;
    const response = await signIn();
    expect(response.status).toBe(200);
    expect(response.headers.get("set-cookie")).toMatch(/vf_tenant=;[^,]*Max-Age=0/i);
  });
});

describe("POST /api/auth/logout", () => {
  it("expires the session and the organisation choice", async () => {
    const { POST: logout } = await import("../logout/route");
    const cookies = (await logout()).headers.get("set-cookie") ?? "";
    expect(cookies).toMatch(/vf_session=;[^,]*Max-Age=0/i);
    expect(cookies).toMatch(/vf_tenant=;[^,]*Path=\/[^,]*/i);
    expect(cookies).toMatch(/vf_tenant=;[^,]*Max-Age=0/i);
  });
});
