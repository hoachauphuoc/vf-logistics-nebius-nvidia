import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Session } from "@/lib/session";

const mocks = vi.hoisted(() => ({
  verifySession: vi.fn(),
  tokenFromCookieHeader: vi.fn(),
  loginRequired: vi.fn(),
  publicReads: vi.fn(),
  oneClickJudge: vi.fn(),
  describedReads: vi.fn(),
  describedWrites: vi.fn(),
}));

vi.mock("@/lib/session", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/session")>()),
  verifySession: mocks.verifySession,
  tokenFromCookieHeader: mocks.tokenFromCookieHeader,
  loginRequired: mocks.loginRequired,
  publicReads: mocks.publicReads,
}));
vi.mock("@/lib/one-click", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/one-click")>()),
  oneClickJudge: mocks.oneClickJudge,
}));
vi.mock("@/lib/proxy-policy", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/proxy-policy")>()),
  describedReads: mocks.describedReads,
  describedWrites: mocks.describedWrites,
}));

import { GET } from "./route";

type Posture = {
  auth: {
    login_required: boolean;
    public_reads: boolean;
    session: { email: string; exp: number; amr: string | null } | null;
    one_click_judge: boolean;
  };
  proxy: {
    reads: string[];
    writes: Array<{ method: string; path: string }>;
  };
};

function request(cookie?: string): Request {
  return new Request(
    "http://localhost/api/auth/posture",
    cookie === undefined ? {} : { headers: { cookie } },
  );
}

async function readPosture(cookie?: string): Promise<Posture> {
  const response = await GET(request(cookie));
  return (await response.json()) as Posture;
}

describe("GET /api/auth/posture", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.tokenFromCookieHeader.mockReturnValue(null);
    mocks.verifySession.mockResolvedValue(null);
    mocks.loginRequired.mockReturnValue(true);
    mocks.publicReads.mockReturnValue(false);
    mocks.oneClickJudge.mockReturnValue(null);
    mocks.describedReads.mockReturnValue(["/api/cases"]);
    mocks.describedWrites.mockReturnValue([{ method: "POST", path: "/api/cases" }]);
  });

  it("answers 200 with the auth and proxy sections", async () => {
    const response = await GET(request());

    expect(response.status).toBe(200);
    const body = (await response.json()) as Record<string, unknown>;
    expect(Object.keys(body).sort()).toEqual(["auth", "proxy"]);
  });

  it("reports sign-in as required and anonymous reads as off when the console says so", async () => {
    mocks.loginRequired.mockReturnValue(true);
    mocks.publicReads.mockReturnValue(false);

    const posture = await readPosture();

    expect(posture.auth.login_required).toBe(true);
    expect(posture.auth.public_reads).toBe(false);
  });

  it("reports anonymous reads as on when the console allows them", async () => {
    mocks.loginRequired.mockReturnValue(false);
    mocks.publicReads.mockReturnValue(true);

    const posture = await readPosture();

    expect(posture.auth.login_required).toBe(false);
    expect(posture.auth.public_reads).toBe(true);
  });

  it("reads the session token from the cookie header of the request", async () => {
    mocks.tokenFromCookieHeader.mockReturnValue("token-value");

    await GET(request("theme=dark; session=token-value"));

    expect(mocks.tokenFromCookieHeader).toHaveBeenCalledWith("theme=dark; session=token-value");
    expect(mocks.verifySession).toHaveBeenCalledWith("token-value");
  });

  it("passes a null cookie header when the request carries no cookie", async () => {
    await GET(request());

    expect(mocks.tokenFromCookieHeader).toHaveBeenCalledWith(null);
  });

  it("reports no session when the token does not verify", async () => {
    mocks.verifySession.mockResolvedValue(null);

    const posture = await readPosture("session=forged");

    expect(posture.auth.session).toBeNull();
  });

  it("reports the caller's own session with email, expiry and sign-in method", async () => {
    const session: Session = { email: "analyst@example.test", exp: 1_900_000_000, amr: "password" };
    mocks.verifySession.mockResolvedValue(session);

    const posture = await readPosture("session=good");

    expect(posture.auth.session).toEqual({
      email: "analyst@example.test",
      exp: 1_900_000_000,
      amr: "password",
    });
  });

  it("reports a null sign-in method for a session minted before the claim existed", async () => {
    const session: Session = { email: "old@example.test", exp: 1_900_000_000 };
    mocks.verifySession.mockResolvedValue(session);

    const posture = await readPosture("session=old");

    expect(posture.auth.session).toEqual({
      email: "old@example.test",
      exp: 1_900_000_000,
      amr: null,
    });
  });

  it("reports a one-click sign-in method as one_click", async () => {
    const session: Session = { email: "judge@example.test", exp: 1_900_000_000, amr: "one_click" };
    mocks.verifySession.mockResolvedValue(session);

    const posture = await readPosture("session=judge");

    expect(posture.auth.session?.amr).toBe("one_click");
  });

  it("never echoes the session token back in the response body", async () => {
    mocks.tokenFromCookieHeader.mockReturnValue("super-secret-token");
    mocks.verifySession.mockResolvedValue({ email: "a@example.test", exp: 1 } as Session);

    const response = await GET(request("session=super-secret-token"));

    expect(await response.text()).not.toContain("super-secret-token");
  });

  it("offers the judge button when a one-click account is configured", async () => {
    mocks.oneClickJudge.mockReturnValue({ email: "judge@example.test" });

    const posture = await readPosture();

    expect(posture.auth.one_click_judge).toBe(true);
  });

  it("does not offer the judge button when no one-click account is configured", async () => {
    mocks.oneClickJudge.mockReturnValue(null);

    const posture = await readPosture();

    expect(posture.auth.one_click_judge).toBe(false);
  });

  it("does not expose the judge account email", async () => {
    mocks.oneClickJudge.mockReturnValue({ email: "judge@example.test" });

    const response = await GET(request());

    expect(await response.text()).not.toContain("judge@example.test");
  });

  it("lists the proxy reads and writes exactly as the proxy policy describes them", async () => {
    mocks.describedReads.mockReturnValue(["/api/cases", "/api/cases/:id"]);
    mocks.describedWrites.mockReturnValue([
      { method: "POST", path: "/api/cases" },
      { method: "PUT", path: "/api/cases/:id" },
    ]);

    const posture = await readPosture();

    expect(posture.proxy.reads).toEqual(["/api/cases", "/api/cases/:id"]);
    expect(posture.proxy.writes).toEqual([
      { method: "POST", path: "/api/cases" },
      { method: "PUT", path: "/api/cases/:id" },
    ]);
  });

  it("reports an empty proxy policy as empty lists rather than omitting them", async () => {
    mocks.describedReads.mockReturnValue([]);
    mocks.describedWrites.mockReturnValue([]);

    const posture = await readPosture();

    expect(posture.proxy).toEqual({ reads: [], writes: [] });
  });
});
