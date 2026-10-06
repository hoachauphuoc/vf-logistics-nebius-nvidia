// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { oneClickJudge } from "@/lib/one-click";
import { verifySession } from "@/lib/session";

import { POST } from "./route";

/**
 * The one-click judge button: off unless switched on, a guest session when on,
 * and that session marked so it cannot clear the board.
 */

const SECRET = "test-session-secret-do-not-ship-0123456789abcdef";
const GUEST = "guest-judge@vf-logistics.demo";

function press(ip = "198.51.100.7") {
  return POST(new Request("https://vf.example/api/auth/judge", {
    method: "POST",
    headers: { "x-forwarded-for": ip },
  }));
}

function sessionCookie(response: Response): string | null {
  const header = response.headers.get("set-cookie") ?? "";
  const match = /vf_session=([^;]+)/.exec(header);
  return match ? match[1] : null;
}

describe("oneClickJudge", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("is off unless explicitly switched on with an account", () => {
    expect(oneClickJudge()).toBeNull();
    vi.stubEnv("VF_ONE_CLICK_JUDGE", "true");
    expect(oneClickJudge()).toBeNull();
    vi.stubEnv("VF_ONE_CLICK_EMAIL", "not-an-address");
    expect(oneClickJudge()).toBeNull();
    vi.stubEnv("VF_ONE_CLICK_EMAIL", ` ${GUEST.toUpperCase()} `);
    expect(oneClickJudge()).toEqual({ email: GUEST });
  });

  it("closes on its end date, and on an end date it cannot read", () => {
    vi.stubEnv("VF_ONE_CLICK_JUDGE", "true");
    vi.stubEnv("VF_ONE_CLICK_EMAIL", GUEST);
    vi.stubEnv("VF_ONE_CLICK_UNTIL", "2026-12-16");
    expect(oneClickJudge(new Date("2026-12-15T12:00:00Z"))).toEqual({ email: GUEST });
    expect(oneClickJudge(new Date("2026-12-16T00:00:00Z"))).toBeNull();
    vi.stubEnv("VF_ONE_CLICK_UNTIL", "after judging");
    expect(oneClickJudge(new Date("2026-10-01T00:00:00Z"))).toBeNull();
  });
});

describe("POST /api/auth/judge", () => {
  beforeEach(() => vi.stubEnv("VF_SESSION_SECRET", SECRET));
  afterEach(() => vi.unstubAllEnvs());

  it("does not exist while switched off", async () => {
    const response = await press();
    expect(response.status).toBe(404);
    expect(sessionCookie(response)).toBeNull();
  });

  it("signs in the guest account with a one-click session", async () => {
    vi.stubEnv("VF_ONE_CLICK_JUDGE", "true");
    vi.stubEnv("VF_ONE_CLICK_EMAIL", GUEST);
    const response = await press("198.51.100.8");
    expect(response.status).toBe(200);

    const session = await verifySession(sessionCookie(response));
    expect(session?.email).toBe(GUEST);
    expect(session?.amr).toBe("one_click");
    // Four hours, not the twelve a password sign-in gets.
    expect(session!.exp - Math.floor(Date.now() / 1000)).toBeLessThanOrEqual(4 * 60 * 60 + 1);
    expect(response.headers.get("set-cookie")).toMatch(/HttpOnly/i);
  });

  it("throttles one address pressing it in a loop", async () => {
    vi.stubEnv("VF_ONE_CLICK_JUDGE", "true");
    vi.stubEnv("VF_ONE_CLICK_EMAIL", GUEST);
    const statuses: number[] = [];
    for (let i = 0; i < 11; i += 1) statuses.push((await press("198.51.100.9")).status);
    expect(statuses.slice(0, 10).every((s) => s === 200)).toBe(true);
    expect(statuses[10]).toBe(429);
  });
});
