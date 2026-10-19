// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  tokenFromCookieHeader: vi.fn(),
  verifySession: vi.fn(),
}));

vi.mock("@/lib/session", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/session")>()),
  tokenFromCookieHeader: mocks.tokenFromCookieHeader,
  verifySession: mocks.verifySession,
}));

import { GET } from "./route";

describe("GET /api/auth/session", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns 401 with error when there is no session", async () => {
    mocks.tokenFromCookieHeader.mockReturnValue(null);
    mocks.verifySession.mockResolvedValue(null);

    const response = await GET(new Request("http://localhost/api/auth/session"));

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ error: "not_authenticated" });
  });

  it("returns 401 when session verification fails", async () => {
    mocks.tokenFromCookieHeader.mockReturnValue("invalid.token");
    mocks.verifySession.mockResolvedValue(null);

    const response = await GET(new Request("http://localhost/api/auth/session"));

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ error: "not_authenticated" });
  });

  it("returns 200 with session data when session is valid", async () => {
    mocks.tokenFromCookieHeader.mockReturnValue("valid.token");
    mocks.verifySession.mockResolvedValue({
      email: "user@example.com",
      exp: 1700000000,
      amr: "password",
    } as never);

    const response = await GET(new Request("http://localhost/api/auth/session"));

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      email: "user@example.com",
      exp: 1700000000,
      amr: "password",
    });
  });

  it("returns 200 with amr: null when session has no amr", async () => {
    mocks.tokenFromCookieHeader.mockReturnValue("valid.token");
    mocks.verifySession.mockResolvedValue({
      email: "user@example.com",
      exp: 1700000000,
    } as never);

    const response = await GET(new Request("http://localhost/api/auth/session"));

    expect(response.status).toBe(200);
    const data = await response.json();
    expect(data).toEqual({
      email: "user@example.com",
      exp: 1700000000,
      amr: null,
    });
  });

  it("returns 401 when cookie header is missing", async () => {
    mocks.tokenFromCookieHeader.mockReturnValue(null);
    mocks.verifySession.mockResolvedValue(null);

    const req = new Request("http://localhost/api/auth/session");
    const response = await GET(req);

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ error: "not_authenticated" });
  });

  it("extracts token from cookie header", async () => {
    mocks.tokenFromCookieHeader.mockReturnValue("extracted.token");
    mocks.verifySession.mockResolvedValue({
      email: "user@example.com",
      exp: 1700000000,
    } as never);

    const req = new Request("http://localhost/api/auth/session", {
      headers: { cookie: "vf_session=extracted.token" },
    });

    await GET(req);

    expect(mocks.tokenFromCookieHeader).toHaveBeenCalledWith("vf_session=extracted.token");
  });

  it("calls verifySession with the extracted token", async () => {
    mocks.tokenFromCookieHeader.mockReturnValue("test.token");
    mocks.verifySession.mockResolvedValue({
      email: "user@example.com",
      exp: 1700000000,
    } as never);

    await GET(new Request("http://localhost/api/auth/session"));

    expect(mocks.verifySession).toHaveBeenCalledWith("test.token");
  });

  it("returns session with one_click amr when present", async () => {
    mocks.tokenFromCookieHeader.mockReturnValue("valid.token");
    mocks.verifySession.mockResolvedValue({
      email: "judge@example.com",
      exp: 1700000000,
      amr: "one_click",
    } as never);

    const response = await GET(new Request("http://localhost/api/auth/session"));

    expect(response.status).toBe(200);
    const data = await response.json();
    expect(data.amr).toBe("one_click");
  });

  it("returns response with Content-Type application/json", async () => {
    mocks.tokenFromCookieHeader.mockReturnValue(null);
    mocks.verifySession.mockResolvedValue(null);

    const response = await GET(new Request("http://localhost/api/auth/session"));

    expect(response.headers.get("content-type")).toContain("application/json");
  });

  it("calls tokenFromCookieHeader with null when request has no cookie header", async () => {
    mocks.tokenFromCookieHeader.mockReturnValue(null);
    mocks.verifySession.mockResolvedValue(null);

    const req = new Request("http://localhost/api/auth/session");
    await GET(req);

    expect(mocks.tokenFromCookieHeader).toHaveBeenCalledWith(null);
  });

  it("returns only email, exp, and amr fields in response", async () => {
    mocks.tokenFromCookieHeader.mockReturnValue("token");
    mocks.verifySession.mockResolvedValue({
      email: "test@example.com",
      exp: 1234567890,
      amr: "password",
    } as never);

    const response = await GET(new Request("http://localhost/api/auth/session"));
    const data = await response.json();

    const keys = Object.keys(data).sort();
    expect(keys).toEqual(["amr", "email", "exp"]);
  });

  it("includes amr as null when session has no amr property", async () => {
    mocks.tokenFromCookieHeader.mockReturnValue("token");
    mocks.verifySession.mockResolvedValue({
      email: "test@example.com",
      exp: 1234567890,
    } as never);

    const response = await GET(new Request("http://localhost/api/auth/session"));
    const data = await response.json();

    expect(data.amr).toBeNull();
    expect("amr" in data).toBe(true);
  });

  it("passes the cookie header value directly to tokenFromCookieHeader", async () => {
    const cookieValue = "session_id=abc123; path=/";
    mocks.tokenFromCookieHeader.mockReturnValue("token");
    mocks.verifySession.mockResolvedValue({ email: "test@example.com", exp: 1234567890 } as never);

    const req = new Request("http://localhost/api/auth/session", {
      headers: { cookie: cookieValue },
    });
    await GET(req);

    expect(mocks.tokenFromCookieHeader).toHaveBeenCalledWith(cookieValue);
  });

  it("preserves email value exactly as returned by session", async () => {
    const testEmail = "User+Test@Example.Com";
    mocks.tokenFromCookieHeader.mockReturnValue("token");
    mocks.verifySession.mockResolvedValue({
      email: testEmail,
      exp: 1234567890,
      amr: "password",
    } as never);

    const response = await GET(new Request("http://localhost/api/auth/session"));
    const data = await response.json();

    expect(data.email).toBe(testEmail);
  });

  it("returns 401 with not_authenticated error when session is falsy", async () => {
    mocks.tokenFromCookieHeader.mockReturnValue("token");
    mocks.verifySession.mockResolvedValue(null);

    const response = await GET(new Request("http://localhost/api/auth/session"));

    expect(response.status).toBe(401);
    const data = await response.json();
    expect(data.error).toBe("not_authenticated");
  });

  it("awaits verifySession before checking if session exists", async () => {
    mocks.tokenFromCookieHeader.mockReturnValue("token");
    mocks.verifySession.mockResolvedValue({
      email: "async@example.com",
      exp: 1234567890,
    } as never);

    const response = await GET(new Request("http://localhost/api/auth/session"));

    expect(response.status).toBe(200);
    const data = await response.json();
    expect(data.email).toBe("async@example.com");
  });

  it("returns numeric exp value in response", async () => {
    const expValue = 9999999999;
    mocks.tokenFromCookieHeader.mockReturnValue("token");
    mocks.verifySession.mockResolvedValue({
      email: "test@example.com",
      exp: expValue,
      amr: "password",
    } as never);

    const response = await GET(new Request("http://localhost/api/auth/session"));
    const data = await response.json();

    expect(data.exp).toBe(expValue);
    expect(typeof data.exp).toBe("number");
  });
});
