import { describe, expect, it, vi, beforeEach } from "vitest";
import { NextResponse } from "next/server";

const mocks = vi.hoisted(() => ({
  verifySession: vi.fn(),
  loginRequired: vi.fn(() => true),
  publicReads: vi.fn(() => false),
  isApiPassThrough: vi.fn(() => false),
}));

vi.mock("@/lib/session", () => ({
  COOKIE_NAME: "session",
  verifySession: mocks.verifySession,
  loginRequired: mocks.loginRequired,
  publicReads: mocks.publicReads,
}));

vi.mock("@/lib/upstream", () => ({
  isApiPassThrough: mocks.isApiPassThrough,
}));

import { proxy, config } from "./proxy";

function createRequest(
  pathname: string,
  method: string = "GET",
  search: string = "",
  cookie?: string,
): Request & { method: string; nextUrl: { pathname: string; search: string; clone: () => unknown } } {
  const url = `http://localhost${pathname}${search}`;
  const request = new Request(url, { method });

  const nextUrl = {
    pathname,
    search,
    clone: function () {
      const clonedUrl = new URL(`http://localhost${this.pathname}${this.search}`);
      return clonedUrl;
    },
    searchParams: new URLSearchParams(search),
  };

  const cookieMap = {
    get: (name: string) => (cookie && name === "session" ? { value: cookie } : undefined),
  };

  Object.defineProperty(request, "nextUrl", {
    value: nextUrl,
    writable: false,
  });

  Object.defineProperty(request, "cookies", {
    value: cookieMap,
    writable: false,
  });

  Object.defineProperty(request, "method", {
    value: method,
    writable: false,
  });

  return request as never;
}

describe("proxy", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.loginRequired.mockReturnValue(true);
    mocks.publicReads.mockReturnValue(false);
    mocks.isApiPassThrough.mockReturnValue(false);
    mocks.verifySession.mockResolvedValue(null);
  });

  describe("token-authenticated POST to /api/proxy/evidence/respond", () => {
    it("allows POST without a session", async () => {
      const request = createRequest("/api/proxy/evidence/respond", "POST");
      const response = await proxy(request as never);
      expect(response).toBeInstanceOf(NextResponse);
      expect(response.status).toBe(200);
    });

    it("does not bypass other checks for non-POST requests to that path", async () => {
      const request = createRequest("/api/proxy/evidence/respond", "GET");
      mocks.verifySession.mockResolvedValue(null);
      const response = await proxy(request as never);
      expect(response.status).toBe(401);
    });
  });

  describe("PUBLIC_PATHS", () => {
    it("allows /login", async () => {
      const request = createRequest("/login", "POST");
      const response = await proxy(request as never);
      expect(response.status).toBe(200);
    });

    it("allows /api/auth/login", async () => {
      const request = createRequest("/api/auth/login", "POST");
      const response = await proxy(request as never);
      expect(response.status).toBe(200);
    });

    it("allows /api/auth/logout", async () => {
      const request = createRequest("/api/auth/logout", "POST");
      const response = await proxy(request as never);
      expect(response.status).toBe(200);
    });

    it("allows /api/auth/judge POST (one-click)", async () => {
      const request = createRequest("/api/auth/judge", "POST");
      const response = await proxy(request as never);
      expect(response.status).toBe(200);
    });

    it("allows /legal", async () => {
      const request = createRequest("/legal", "GET");
      const response = await proxy(request as never);
      expect(response.status).toBe(200);
    });
  });

  describe("/respond/* prefix (signed-link evidence)", () => {
    it("allows /respond/token123", async () => {
      const request = createRequest("/respond/token123", "POST");
      const response = await proxy(request as never);
      expect(response.status).toBe(200);
    });

    it("allows /respond/abc/nested", async () => {
      const request = createRequest("/respond/abc/nested", "GET");
      const response = await proxy(request as never);
      expect(response.status).toBe(200);
    });
  });

  describe("isApiPassThrough public API", () => {
    it("allows a pass-through API path when enabled", async () => {
      mocks.isApiPassThrough.mockReturnValue(true);
      const request = createRequest("/api/v1/shipments", "GET");
      const response = await proxy(request as never);
      expect(response.status).toBe(200);
    });

    it("checks isApiPassThrough for the request pathname", async () => {
      mocks.isApiPassThrough.mockReturnValue(false);
      const request = createRequest("/api/v1/shipments", "GET");
      mocks.verifySession.mockResolvedValue(null);
      await proxy(request as never);
      expect(mocks.isApiPassThrough).toHaveBeenCalledWith("/api/v1/shipments");
    });
  });

  describe("loginRequired (development mode without secrets)", () => {
    it("bypasses session check if loginRequired returns false", async () => {
      mocks.loginRequired.mockReturnValue(false);
      const request = createRequest("/protected-page", "POST");
      const response = await proxy(request as never);
      expect(response.status).toBe(200);
      expect(mocks.verifySession).not.toHaveBeenCalled();
    });

    it("enforces session check if loginRequired returns true", async () => {
      mocks.loginRequired.mockReturnValue(true);
      mocks.verifySession.mockResolvedValue(null);
      const request = createRequest("/protected-page", "POST");
      await proxy(request as never);
      expect(mocks.verifySession).toHaveBeenCalled();
    });
  });

  describe("publicReads (read-only mode)", () => {
    it("allows GET when publicReads is true", async () => {
      mocks.publicReads.mockReturnValue(true);
      const request = createRequest("/api/proxy/cases", "GET");
      const response = await proxy(request as never);
      expect(response.status).toBe(200);
    });

    it("allows HEAD when publicReads is true", async () => {
      mocks.publicReads.mockReturnValue(true);
      const request = createRequest("/api/proxy/cases", "HEAD");
      const response = await proxy(request as never);
      expect(response.status).toBe(200);
    });

    it("does not allow POST even when publicReads is true", async () => {
      mocks.publicReads.mockReturnValue(true);
      mocks.verifySession.mockResolvedValue(null);
      const request = createRequest("/api/proxy/cases", "POST");
      const response = await proxy(request as never);
      expect(response.status).toBe(401);
    });

    it("does not allow DELETE even when publicReads is true", async () => {
      mocks.publicReads.mockReturnValue(true);
      mocks.verifySession.mockResolvedValue(null);
      const request = createRequest("/api/proxy/cases/123", "DELETE");
      const response = await proxy(request as never);
      expect(response.status).toBe(401);
    });

    it("does not allow PUT even when publicReads is true", async () => {
      mocks.publicReads.mockReturnValue(true);
      mocks.verifySession.mockResolvedValue(null);
      const request = createRequest("/api/proxy/cases/123", "PUT");
      const response = await proxy(request as never);
      expect(response.status).toBe(401);
    });
  });

  describe("session verification", () => {
    it("allows requests with a valid session", async () => {
      mocks.verifySession.mockResolvedValue({ user_id: "user-123" } as never);
      const request = createRequest("/api/proxy/cases", "POST", "", "valid-session-cookie");
      const response = await proxy(request as never);
      expect(response.status).toBe(200);
    });

    it("reads the session cookie from the request", async () => {
      mocks.verifySession.mockResolvedValue(null);
      const request = createRequest("/protected", "GET", "", "my-cookie-value");
      await proxy(request as never);
      expect(mocks.verifySession).toHaveBeenCalledWith("my-cookie-value");
    });

    it("handles missing cookie gracefully", async () => {
      mocks.verifySession.mockResolvedValue(null);
      const request = createRequest("/protected", "GET");
      await proxy(request as never);
      expect(mocks.verifySession).toHaveBeenCalledWith(undefined);
    });
  });

  describe("rejection paths", () => {
    beforeEach(() => {
      mocks.verifySession.mockResolvedValue(null);
    });

    describe("API calls without a session", () => {
      it("returns 401 JSON for /api/ paths", async () => {
        const request = createRequest("/api/proxy/cases", "POST");
        const response = await proxy(request as never);
        expect(response.status).toBe(401);
        const json = await response.json();
        expect(json).toEqual({
          error: "not_authenticated",
          detail: "Sign in to continue.",
        });
      });

      it("returns 401 for /api/proxy/... without session", async () => {
        const request = createRequest("/api/proxy/cases/123/approve", "POST");
        const response = await proxy(request as never);
        expect(response.status).toBe(401);
      });

      it("returns 401 for nested /api/ paths", async () => {
        const request = createRequest("/api/deeply/nested/path", "POST");
        const response = await proxy(request as never);
        expect(response.status).toBe(401);
      });
    });

    describe("page redirects without a session", () => {
      it("redirects to /login when no session on a page request", async () => {
        const request = createRequest("/dashboard", "GET");
        const response = await proxy(request as never);
        expect(response.status).toBe(307);
        const location = response.headers.get("location");
        expect(location).toContain("/login");
      });

      it("preserves pathname in next parameter", async () => {
        const request = createRequest("/dashboard", "GET");
        const response = await proxy(request as never);
        const location = response.headers.get("location");
        expect(location).toContain("next=%2Fdashboard");
      });

      it("preserves query string in next parameter", async () => {
        const request = createRequest("/dashboard", "GET", "?case=CASE-1&view=detail");
        const response = await proxy(request as never);
        const location = response.headers.get("location");
        expect(location).toContain("next=%2Fdashboard%3Fcase%3DCASE-1%26view%3Ddetail");
      });

      it("clears the search params in the redirect (not in next)", async () => {
        const request = createRequest("/page", "GET", "?sensitive=value");
        const response = await proxy(request as never);
        const location = response.headers.get("location");
        expect(location).toContain("/login?");
        expect(location).not.toContain("sensitive=value");
      });

      it("redirects page requests with POST method", async () => {
        const request = createRequest("/form-page", "POST");
        const response = await proxy(request as never);
        expect(response.status).toBe(307);
        const location = response.headers.get("location");
        expect(location).toContain("/login");
      });
    });
  });

  describe("precedence and edge cases", () => {
    it("checks token-authenticated POST before public reads", async () => {
      mocks.publicReads.mockReturnValue(true);
      const request = createRequest("/api/proxy/evidence/respond", "POST");
      const response = await proxy(request as never);
      expect(response.status).toBe(200);
    });

    it("checks PUBLIC_PATHS before session verification", async () => {
      mocks.verifySession.mockResolvedValue(null);
      const request = createRequest("/login", "POST");
      const response = await proxy(request as never);
      expect(response.status).toBe(200);
      expect(mocks.verifySession).not.toHaveBeenCalled();
    });

    it("checks /respond/* before session verification", async () => {
      mocks.verifySession.mockResolvedValue(null);
      const request = createRequest("/respond/token", "GET");
      const response = await proxy(request as never);
      expect(response.status).toBe(200);
      expect(mocks.verifySession).not.toHaveBeenCalled();
    });

    it("allows OPTIONS preflight if it matches another rule", async () => {
      // OPTIONS is not special-cased, so it only passes if it matches another rule
      const request = createRequest("/login", "OPTIONS");
      const response = await proxy(request as never);
      expect(response.status).toBe(200);
    });

    it("blocks OPTIONS on a protected endpoint", async () => {
      mocks.verifySession.mockResolvedValue(null);
      const request = createRequest("/api/proxy/cases", "OPTIONS");
      const response = await proxy(request as never);
      expect(response.status).toBe(401);
    });

    it("distinguishes /respond from /respondent", async () => {
      // /respondent does not match /respond/* prefix, so it's a protected page path.
      // Without session, page paths redirect to login (307), not 401.
      mocks.verifySession.mockResolvedValue(null);
      const request = createRequest("/respondent/info", "GET");
      const response = await proxy(request as never);
      expect(response.status).toBe(307);
    });
  });

  describe("config matcher", () => {
    it("exports a config object with a matcher", () => {
      expect(config).toBeDefined();
      expect(config.matcher).toBeDefined();
      expect(Array.isArray(config.matcher)).toBe(true);
    });

    it("config matcher is an array of strings", () => {
      expect(config.matcher.every((m: unknown) => typeof m === "string")).toBe(true);
    });
  });
});
