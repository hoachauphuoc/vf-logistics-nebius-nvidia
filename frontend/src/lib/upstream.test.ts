// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  forwardedHeaders,
  isApiPassThrough,
  passThrough,
  safeSegments,
  upstreamPath,
} from "./upstream";

/** The request fetch was called with, as a real Request. */
function sentRequest(spy: ReturnType<typeof vi.fn>): { url: string; headers: Headers; init: RequestInit } {
  const [url, init] = spy.mock.calls[0] as [string, RequestInit];
  return { url, headers: new Headers(init.headers), init };
}

describe("passThrough", () => {
  let spy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.stubEnv("FLASK_API_BASE", "http://127.0.0.1:9090");
    // Set on purpose: the console's key is in the environment of every request
    // this process handles, and the pass-through must never reach for it.
    vi.stubEnv("VF_API_KEY", "console-secret-key");
    spy = vi.fn(async () => Response.json({ ok: true }, { status: 200 }));
    globalThis.fetch = spy as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it("never attaches the console's own API key", async () => {
    await passThrough(new Request("https://vf.example/api/v1/cases"), "/api/v1/cases");
    const { headers } = sentRequest(spy);
    expect(headers.get("x-vf-api-key")).toBeNull();
    expect(headers.get("authorization")).toBeNull();
  });

  it("forwards the caller's own credential unchanged", async () => {
    await passThrough(
      new Request("https://vf.example/api/v1/cases", {
        headers: { "X-VF-API-Key": "integrator-key" },
      }),
      "/api/v1/cases",
    );
    expect(sentRequest(spy).headers.get("x-vf-api-key")).toBe("integrator-key");
  });

  it("drops the console session cookie and the inbound host", async () => {
    await passThrough(
      new Request("https://vf.example/api/v1/cases", {
        headers: { cookie: "vf_session=abc.def", host: "vf.example" },
      }),
      "/api/v1/cases",
    );
    const { headers } = sentRequest(spy);
    expect(headers.get("cookie")).toBeNull();
    // The inbound host survives only as X-Forwarded-Host, which ProxyFix reads.
    expect(headers.get("x-forwarded-host")).toBe("vf.example");
  });

  it("keeps the query string and targets the internal Flask address", async () => {
    await passThrough(
      new Request("https://vf.example/api/v1/cases?limit=5&state=ESCALATED"),
      "/api/v1/cases",
    );
    expect(sentRequest(spy).url).toBe(
      "http://127.0.0.1:9090/api/v1/cases?limit=5&state=ESCALATED",
    );
  });

  it("does not follow an upstream redirect with the caller's credential", async () => {
    await passThrough(new Request("https://vf.example/demo"), "/demo");
    expect(sentRequest(spy).init.redirect).toBe("manual");
  });

  it("streams a write body through", async () => {
    await passThrough(
      new Request("https://vf.example/api/v1/simulate", {
        method: "POST",
        body: JSON.stringify({ count: 3 }),
        headers: { "content-type": "application/json" },
      }),
      "/api/v1/simulate",
    );
    const { init, headers } = sentRequest(spy);
    expect(init.method).toBe("POST");
    expect(init.body).toBeTruthy();
    expect(headers.get("content-type")).toBe("application/json");
  });

  it("reports an unreachable backend as 502, not as an empty answer", async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new TypeError("fetch failed");
    }) as unknown as typeof fetch;
    const response = await passThrough(new Request("https://vf.example/health"), "/health");
    expect(response.status).toBe(502);
    expect(await response.json()).toMatchObject({ error: "upstream_unreachable" });
  });

  it("reports a timeout as 504", async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new DOMException("The operation timed out.", "TimeoutError");
    }) as unknown as typeof fetch;
    const response = await passThrough(new Request("https://vf.example/health"), "/health");
    expect(response.status).toBe(504);
  });

  it("copies status and content type back, minus hop-by-hop headers", async () => {
    globalThis.fetch = vi.fn(
      async () =>
        new Response("nope", {
          status: 403,
          headers: { "content-type": "application/json", "set-cookie": "x=1", connection: "close" },
        }),
    ) as unknown as typeof fetch;
    const response = await passThrough(new Request("https://vf.example/api/v1/billing/usage"), "/api/v1/billing/usage");
    expect(response.status).toBe(403);
    expect(response.headers.get("content-type")).toBe("application/json");
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(response.headers.get("connection")).toBeNull();
  });
});

describe("forwardedHeaders", () => {
  it("passes X-Forwarded-For through unchanged, so Flask trusts only the front end's entry", () => {
    const out = forwardedHeaders(
      new Request("https://vf.example/", {
        headers: { "x-forwarded-for": "6.6.6.6, 203.0.113.9" },
      }),
    );
    // ProxyFix(x_for=1) takes the LAST entry, the one Cloud Run appended. A
    // client can prepend whatever it likes; it cannot replace that one.
    expect(out["x-forwarded-for"]).toBe("6.6.6.6, 203.0.113.9");
  });

  it("uses the last X-Forwarded-Proto entry and ignores a nonsense scheme", () => {
    const ok = forwardedHeaders(
      new Request("http://vf.example/", { headers: { "x-forwarded-proto": "http, https" } }),
    );
    expect(ok["x-forwarded-proto"]).toBe("https");
    const bad = forwardedHeaders(
      new Request("http://vf.example/", { headers: { "x-forwarded-proto": "javascript" } }),
    );
    expect(bad["x-forwarded-proto"]).toBeUndefined();
  });
});

describe("safeSegments and upstreamPath", () => {
  it("rejects segments that could walk out of /api/v1", () => {
    expect(safeSegments([".."])).toBeNull();
    expect(safeSegments(["cases", "..", "internal"])).toBeNull();
    expect(safeSegments(["."])).toBeNull();
    expect(safeSegments([""])).toBeNull();
    expect(safeSegments(["a/b"])).toBeNull();
    expect(safeSegments(["a\\b"])).toBeNull();
    expect(safeSegments([])).toBeNull();
    expect(safeSegments(undefined)).toBeNull();
  });

  it("accepts ordinary segments and re-encodes them", () => {
    const parts = safeSegments(["review", "CASE-1", "decide"]);
    expect(parts).toEqual(["review", "CASE-1", "decide"]);
    expect(upstreamPath("/api/v1", parts!)).toBe("/api/v1/review/CASE-1/decide");
    expect(upstreamPath("/api/v1", ["a b"])).toBe("/api/v1/a%20b");
  });
});

describe("isApiPassThrough", () => {
  it("covers the public API and nothing that is a console page", () => {
    for (const path of ["/api/v1", "/api/v1/cases", "/health", "/metrics", "/demo"]) {
      expect(isApiPassThrough(path)).toBe(true);
    }
    // /agents is the Agent Console page; the JSON list is /api/v1/agents.
    for (const path of ["/", "/agents", "/api/proxy/cases", "/api/auth/login", "/healthz", "/api/v10"]) {
      expect(isApiPassThrough(path)).toBe(false);
    }
  });
});
