// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { proxy } from "./proxy";

/**
 * The middleware runs before the BFF route. Rev2 N08 was reported as "the public
 * upload gets a 401", and a fix in the route alone did not reach it: this layer
 * answered first. Found by driving the real upload page in a browser.
 */

const passes = (res: Response) => res.headers.get("x-middleware-next") === "1";

describe("proxy (middleware) for anonymous callers", () => {
  beforeEach(() => {
    vi.stubEnv("VF_SESSION_SECRET", "test-session-secret-do-not-ship-0123456789abcdef");
    vi.stubEnv("VF_PUBLIC_READS", "true");
  });
  afterEach(() => vi.unstubAllEnvs());

  const req = (path: string, method: string) =>
    new NextRequest(new URL(`https://vf.example${path}`), { method });

  it("lets a shipper's token upload through without a session", async () => {
    expect(passes(await proxy(req("/api/proxy/evidence/respond", "POST")))).toBe(true);
  });

  it("lets the upload page itself load", async () => {
    expect(passes(await proxy(req("/respond/some.token", "GET")))).toBe(true);
  });

  it.each([
    "/api/proxy/review/CASE-1/approve",
    "/api/proxy/review/CASE-1/execute",
    "/api/proxy/review/CASE-1/request-evidence",
    "/api/proxy/evidence/respond/extra",
    "/api/proxy/evidence/respondx",
  ])("still answers an anonymous POST to %s with 401", async (path) => {
    const res = await proxy(req(path, "POST"));
    expect(passes(res)).toBe(false);
    expect(res.status).toBe(401);
  });

  it("does not open other methods on the upload path", async () => {
    for (const method of ["PUT", "DELETE", "PATCH"]) {
      const res = await proxy(req("/api/proxy/evidence/respond", method));
      expect(res.status).toBe(401);
    }
  });
});
