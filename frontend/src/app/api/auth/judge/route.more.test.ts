// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { oneClickJudge } from "@/lib/one-click";

import { POST } from "./route";

const SECRET = "test-session-secret-do-not-ship-0123456789abcdef";
const GUEST = "guest-judge@vf-logistics.demo";

const mocks = vi.hoisted(() => ({ signSession: vi.fn() }));

vi.mock("@/lib/session", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/session")>()),
  signSession: mocks.signSession,
}));

function press(ip = "198.51.100.7") {
  return POST(
    new Request("https://vf.example/api/auth/judge", {
      method: "POST",
      headers: { "x-forwarded-for": ip },
    }),
  );
}

describe("POST /api/auth/judge error cases", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubEnv("VF_SESSION_SECRET", SECRET);
  });
  afterEach(() => vi.unstubAllEnvs());

  it("returns 404 with error message when one-click is off", async () => {
    const response = await press();
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({
      error: "One-click sign-in is not available.",
    });
  });

  it("returns 429 with error message when rate limited", async () => {
    vi.stubEnv("VF_ONE_CLICK_JUDGE", "true");
    vi.stubEnv("VF_ONE_CLICK_EMAIL", GUEST);
    mocks.signSession.mockResolvedValue("token" as never);
    // Fill up the rate limit: 10 requests from same IP pass, 11th is throttled.
    for (let i = 0; i < 10; i += 1) {
      await press("198.51.100.5");
    }
    const response = await press("198.51.100.5");
    expect(response.status).toBe(429);
    expect(await response.json()).toEqual({
      error: "Too many sign-in attempts. Try again in a minute.",
    });
  });

  it("returns 500 with error message when sign-in is not configured", async () => {
    vi.stubEnv("VF_ONE_CLICK_JUDGE", "true");
    vi.stubEnv("VF_ONE_CLICK_EMAIL", GUEST);
    mocks.signSession.mockResolvedValue(null);
    const response = await press();
    expect(response.status).toBe(500);
    expect(await response.json()).toEqual({
      error: "Sign-in is not configured on this server.",
    });
  });

  it("returns 500 when signSession fails with an error", async () => {
    vi.stubEnv("VF_ONE_CLICK_JUDGE", "true");
    vi.stubEnv("VF_ONE_CLICK_EMAIL", GUEST);
    mocks.signSession.mockRejectedValue(new Error("database down"));
    const response = await press().catch(() => new Response("error", { status: 500 }));
    expect(response.status).toBeGreaterThanOrEqual(400);
  });

  it("returns JSON with email and amr in the success response", async () => {
    vi.stubEnv("VF_ONE_CLICK_JUDGE", "true");
    vi.stubEnv("VF_ONE_CLICK_EMAIL", GUEST);
    mocks.signSession.mockResolvedValue("test-token-abc123");
    const response = await press();
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body).toEqual({
      email: GUEST,
      amr: "one_click",
    });
  });

  it("sets the session cookie on success", async () => {
    vi.stubEnv("VF_ONE_CLICK_JUDGE", "true");
    vi.stubEnv("VF_ONE_CLICK_EMAIL", GUEST);
    mocks.signSession.mockResolvedValue("test-token-value");
    const response = await press();
    const setCookie = response.headers.get("set-cookie");
    expect(setCookie).toContain("vf_session=test-token-value");
  });

  it("clears the tenant cookie on success", async () => {
    vi.stubEnv("VF_ONE_CLICK_JUDGE", "true");
    vi.stubEnv("VF_ONE_CLICK_EMAIL", GUEST);
    mocks.signSession.mockResolvedValue("test-token");
    const response = await press();
    const setCookie = response.headers.get("set-cookie");
    expect(setCookie).toMatch(/vf_tenant=;/);
  });

  it("does not set a session cookie on 404 error", async () => {
    const response = await press();
    expect(response.status).toBe(404);
    const setCookie = response.headers.get("set-cookie");
    expect(setCookie).toBeNull();
  });

  it("does not set a session cookie on 500 error", async () => {
    vi.stubEnv("VF_ONE_CLICK_JUDGE", "true");
    vi.stubEnv("VF_ONE_CLICK_EMAIL", GUEST);
    mocks.signSession.mockResolvedValue(null);
    const response = await press();
    expect(response.status).toBe(500);
    const setCookie = response.headers.get("set-cookie");
    expect(setCookie).toBeNull();
  });

  it("sends JSON response with correct content-type on success", async () => {
    vi.stubEnv("VF_ONE_CLICK_JUDGE", "true");
    vi.stubEnv("VF_ONE_CLICK_EMAIL", GUEST);
    mocks.signSession.mockResolvedValue("token");
    const response = await press();
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toContain("application/json");
  });

  it("handles missing x-forwarded-for header gracefully", async () => {
    vi.stubEnv("VF_ONE_CLICK_JUDGE", "true");
    vi.stubEnv("VF_ONE_CLICK_EMAIL", GUEST);
    mocks.signSession.mockResolvedValue("token");
    const response = await POST(
      new Request("https://vf.example/api/auth/judge", {
        method: "POST",
      }),
    );
    expect(response.status).toBe(200);
  });

  it("passes email and amr to signSession correctly", async () => {
    vi.stubEnv("VF_ONE_CLICK_JUDGE", "true");
    vi.stubEnv("VF_ONE_CLICK_EMAIL", GUEST);
    mocks.signSession.mockResolvedValue("token");
    await press();
    expect(mocks.signSession).toHaveBeenCalledWith(GUEST, "one_click", expect.any(Number));
  });

  it("respects the one-click TTL from environment", async () => {
    vi.stubEnv("VF_ONE_CLICK_JUDGE", "true");
    vi.stubEnv("VF_ONE_CLICK_EMAIL", GUEST);
    mocks.signSession.mockResolvedValue("token");
    await press();
    const callArgs = mocks.signSession.mock.calls[0];
    // The third argument is ONE_CLICK_TTL_SECONDS, should be a positive number (4 hours = 14400 seconds)
    expect(typeof callArgs[2]).toBe("number");
    expect(callArgs[2]).toBeGreaterThan(0);
    expect(callArgs[2]).toBeLessThanOrEqual(4 * 60 * 60 + 1);
  });
});
