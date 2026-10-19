// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  canonicalEmail: vi.fn(),
  loginAttemptVerdict: vi.fn(),
  verifyOperator: vi.fn(),
  signSession: vi.fn(),
  flaskBase: vi.fn(),
}));

vi.mock("@/lib/config", () => ({
  flaskBase: mocks.flaskBase,
}));
vi.mock("@/lib/login-limit", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/login-limit")>()),
  canonicalEmail: mocks.canonicalEmail,
  loginAttemptVerdict: mocks.loginAttemptVerdict,
}));
vi.mock("@/lib/operators", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/operators")>()),
  verifyOperator: mocks.verifyOperator,
}));
vi.mock("@/lib/session", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/session")>()),
  signSession: mocks.signSession,
}));

import { POST } from "./route";

describe("POST /api/auth/login comprehensive coverage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubEnv("VF_API_KEY", "test-api-key");
  });
  afterEach(() => vi.unstubAllEnvs());

  describe("request body parsing", () => {
    it("returns 400 when body is invalid JSON", async () => {
      const response = await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          body: "{invalid json",
        }),
      );
      expect(response.status).toBe(400);
      const body = await response.json();
      expect(body.error).toContain("Email or password is incorrect");
    });

    it("returns 400 when email is not a string", async () => {
      const response = await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: 123, password: "test" }),
        }),
      );
      expect(response.status).toBe(400);
      expect(await response.json()).toEqual({
        error: "Email or password is incorrect.",
      });
    });

    it("returns 400 when password is not a string", async () => {
      mocks.canonicalEmail.mockReturnValue("test@example.com");
      const response = await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: "test@example.com", password: false }),
        }),
      );
      expect(response.status).toBe(400);
    });

    it("returns 400 when email is null", async () => {
      mocks.canonicalEmail.mockReturnValue(null);
      const response = await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: null, password: "test" }),
        }),
      );
      expect(response.status).toBe(400);
    });

    it("returns 400 when password is null", async () => {
      mocks.canonicalEmail.mockReturnValue("test@example.com");
      const response = await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: "test@example.com", password: null }),
        }),
      );
      expect(response.status).toBe(400);
    });

    it("defaults to empty strings when email or password are missing", async () => {
      mocks.canonicalEmail.mockReturnValue(null);
      const response = await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({}),
        }),
      );
      expect(response.status).toBe(400);
      expect(mocks.canonicalEmail).toHaveBeenCalledWith("");
    });
  });

  describe("email canonicalization", () => {
    it("calls canonicalEmail with the email from request body", async () => {
      mocks.canonicalEmail.mockReturnValue(null);
      await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: "TEST@EXAMPLE.COM", password: "secret" }),
        }),
      );
      expect(mocks.canonicalEmail).toHaveBeenCalledWith("TEST@EXAMPLE.COM");
    });

    it("returns 400 when canonicalEmail returns null", async () => {
      mocks.canonicalEmail.mockReturnValue(null);
      const response = await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: "test@example.com", password: "secret" }),
        }),
      );
      expect(response.status).toBe(400);
    });

    it("returns 400 when canonicalEmail returns empty string", async () => {
      mocks.canonicalEmail.mockReturnValue("");
      const response = await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: "invalid", password: "secret" }),
        }),
      );
      expect(response.status).toBe(400);
    });

    it("returns 400 when password is empty but canonical email is valid", async () => {
      mocks.canonicalEmail.mockReturnValue("test@example.com");
      const response = await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: "test@example.com", password: "" }),
        }),
      );
      expect(response.status).toBe(400);
    });
  });

  describe("rate limiting integration", () => {
    beforeEach(() => {
      mocks.canonicalEmail.mockReturnValue("operator@example.com");
      mocks.flaskBase.mockReturnValue("http://flask-backend");
    });

    it("calls loginAttemptVerdict with canonical email, request, flask base and API key", async () => {
      mocks.loginAttemptVerdict.mockResolvedValue("allowed");
      mocks.verifyOperator.mockResolvedValue(null);
      const request = new Request("https://vf.example/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email: "test@example.com", password: "secret" }),
      });
      await POST(request);
      expect(mocks.loginAttemptVerdict).toHaveBeenCalledWith(
        "operator@example.com",
        request,
        "http://flask-backend",
        "test-api-key",
      );
    });

    it("returns 429 with retry message when verdict is limited", async () => {
      mocks.loginAttemptVerdict.mockResolvedValue("limited");
      const response = await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: "test@example.com", password: "secret" }),
        }),
      );
      expect(response.status).toBe(429);
      const body = await response.json();
      expect(body.error).toContain("Too many login attempts");
      expect(body.error).toContain("minute");
    });

    it("returns 503 with retry-after header when verdict is unavailable", async () => {
      mocks.loginAttemptVerdict.mockResolvedValue("unavailable");
      const response = await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: "test@example.com", password: "secret" }),
        }),
      );
      expect(response.status).toBe(503);
      expect(response.headers.get("Retry-After")).toBe("5");
      const body = await response.json();
      expect(body.error).toContain("temporarily unavailable");
    });

    it("continues to password verification when verdict is allowed", async () => {
      mocks.loginAttemptVerdict.mockResolvedValue("allowed");
      mocks.verifyOperator.mockResolvedValue(null);
      const response = await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: "test@example.com", password: "secret" }),
        }),
      );
      expect(response.status).toBe(401);
    });

    it("does not check password when rate limited (optimization check)", async () => {
      mocks.loginAttemptVerdict.mockResolvedValue("limited");
      await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: "test@example.com", password: "secret" }),
        }),
      );
      expect(mocks.verifyOperator).not.toHaveBeenCalled();
    });

    it("does not check password when rate limit unavailable (optimization check)", async () => {
      mocks.loginAttemptVerdict.mockResolvedValue("unavailable");
      await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: "test@example.com", password: "secret" }),
        }),
      );
      expect(mocks.verifyOperator).not.toHaveBeenCalled();
    });
  });

  describe("password verification", () => {
    beforeEach(() => {
      mocks.canonicalEmail.mockReturnValue("operator@example.com");
      mocks.loginAttemptVerdict.mockResolvedValue("allowed");
    });

    it("calls verifyOperator with canonical email and password", async () => {
      mocks.verifyOperator.mockResolvedValue(null);
      await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: "test@example.com", password: "mypassword" }),
        }),
      );
      expect(mocks.verifyOperator).toHaveBeenCalledWith("operator@example.com", "mypassword");
    });

    it("returns 401 when verifyOperator returns null", async () => {
      mocks.verifyOperator.mockResolvedValue(null);
      const response = await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: "test@example.com", password: "wrong" }),
        }),
      );
      expect(response.status).toBe(401);
      const body = await response.json();
      expect(body.error).toBe("Email or password is incorrect.");
    });

    it("returns 401 when verifyOperator returns false", async () => {
      mocks.verifyOperator.mockResolvedValue(false as unknown as string);
      const response = await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: "test@example.com", password: "wrong" }),
        }),
      );
      expect(response.status).toBe(401);
    });

    it("returns 401 for any falsy verifyOperator result", async () => {
      mocks.verifyOperator.mockResolvedValue(0 as unknown as string);
      const response = await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: "test@example.com", password: "wrong" }),
        }),
      );
      expect(response.status).toBe(401);
    });
  });

  describe("session token creation", () => {
    beforeEach(() => {
      mocks.canonicalEmail.mockReturnValue("user@example.com");
      mocks.loginAttemptVerdict.mockResolvedValue("allowed");
      mocks.verifyOperator.mockResolvedValue("user@example.com");
    });

    it("calls signSession with verified email and 'password' claim", async () => {
      mocks.signSession.mockResolvedValue("token-abc123");
      await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: "test@example.com", password: "secret" }),
        }),
      );
      expect(mocks.signSession).toHaveBeenCalledWith("user@example.com", "password");
    });

    it("returns 500 when signSession returns null", async () => {
      mocks.signSession.mockResolvedValue(null);
      const response = await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: "test@example.com", password: "secret" }),
        }),
      );
      expect(response.status).toBe(500);
      const body = await response.json();
      expect(body.error).toContain("not configured");
    });

    it("returns 500 when signSession returns empty string", async () => {
      mocks.signSession.mockResolvedValue("");
      const response = await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: "test@example.com", password: "secret" }),
        }),
      );
      expect(response.status).toBe(500);
    });

    it("returns 500 when signSession returns false", async () => {
      mocks.signSession.mockResolvedValue(false as unknown as string);
      const response = await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: "test@example.com", password: "secret" }),
        }),
      );
      expect(response.status).toBe(500);
    });
  });

  describe("successful login response", () => {
    beforeEach(() => {
      mocks.canonicalEmail.mockReturnValue("user@company.example");
      mocks.loginAttemptVerdict.mockResolvedValue("allowed");
      mocks.verifyOperator.mockResolvedValue("user@company.example");
      mocks.signSession.mockResolvedValue("session-token-xyz789");
    });

    it("returns 200 status on successful login", async () => {
      const response = await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: "user@company.example", password: "correct" }),
        }),
      );
      expect(response.status).toBe(200);
    });

    it("returns verified email in JSON response", async () => {
      const response = await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: "user@company.example", password: "correct" }),
        }),
      );
      const body = await response.json();
      expect(body).toEqual({ email: "user@company.example" });
    });

    it("sets session cookie with token", async () => {
      const response = await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: "user@company.example", password: "correct" }),
        }),
      );
      const setCookie = response.headers.get("set-cookie") ?? "";
      expect(setCookie).toContain("vf_session=session-token-xyz789");
    });

    it("clears tenant choice cookie on successful login", async () => {
      const response = await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: "user@company.example", password: "correct" }),
        }),
      );
      const setCookie = response.headers.get("set-cookie") ?? "";
      expect(setCookie).toContain("vf_tenant=");
      expect(setCookie).toMatch(/vf_tenant=;/);
    });

    it("has JSON content type in response", async () => {
      const response = await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: "user@company.example", password: "correct" }),
        }),
      );
      expect(response.headers.get("content-type")).toContain("application/json");
    });
  });

  describe("error response consistency", () => {
    it("always uses same error message for all invalid input cases", async () => {
      mocks.canonicalEmail.mockReturnValue(null);

      const invalidJsonResponse = await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          body: "{bad json",
        }),
      );
      const invalidEmailResponse = await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ password: "test" }),
        }),
      );

      const body1 = await invalidJsonResponse.json();
      const body2 = await invalidEmailResponse.json();
      expect(body1.error).toBe(body2.error);
      expect(body1.error).toBe("Email or password is incorrect.");
    });
  });

  describe("different verified email values", () => {
    beforeEach(() => {
      mocks.canonicalEmail.mockReturnValue("test@example.com");
      mocks.loginAttemptVerdict.mockResolvedValue("allowed");
    });

    it("uses the value returned by verifyOperator in response", async () => {
      mocks.verifyOperator.mockResolvedValue("verified.email@different.example");
      mocks.signSession.mockResolvedValue("token");
      const response = await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: "test@example.com", password: "secret" }),
        }),
      );
      const body = await response.json();
      expect(body.email).toBe("verified.email@different.example");
    });

    it("passes verified email to signSession", async () => {
      const verifiedEmail = "actual.verified@example.com";
      mocks.verifyOperator.mockResolvedValue(verifiedEmail);
      mocks.signSession.mockResolvedValue("token");
      await POST(
        new Request("https://vf.example/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email: "test@example.com", password: "secret" }),
        }),
      );
      expect(mocks.signSession).toHaveBeenCalledWith(verifiedEmail, "password");
    });
  });
});
