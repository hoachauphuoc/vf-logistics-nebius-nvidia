import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  passThrough: vi.fn(),
}));

vi.mock("@/lib/upstream", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/upstream")>()),
  passThrough: mocks.passThrough,
}));

import * as route from "./route";
import { GET, HEAD, POST, PUT, PATCH, DELETE, OPTIONS } from "./route";

const BASE = "https://vf.example/api/v1";

function ctx(path: string[] | undefined) {
  return { params: Promise.resolve({ path }) };
}

describe("public API catch-all route", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.passThrough.mockResolvedValue(new Response("ok", { status: 200 }));
  });

  it("is forced dynamic so the API is never served from a cache", () => {
    expect(route.dynamic).toBe("force-dynamic");
  });

  it("forwards a nested path to /api/v1 with the caller's request", async () => {
    const request = new Request(`${BASE}/cases/42/documents`);
    await GET(request, ctx(["cases", "42", "documents"]));

    expect(mocks.passThrough).toHaveBeenCalledWith(request, "/api/v1/cases/42/documents");
  });

  it.each([
    ["GET", GET],
    ["HEAD", HEAD],
    ["POST", POST],
    ["PUT", PUT],
    ["PATCH", PATCH],
    ["DELETE", DELETE],
    ["OPTIONS", OPTIONS],
  ])("forwards %s requests instead of answering them itself", async (method, handler) => {
    const request = new Request(`${BASE}/shipments`, { method });
    const response = await handler(request, ctx(["shipments"]));

    expect(mocks.passThrough).toHaveBeenCalledTimes(1);
    expect(mocks.passThrough).toHaveBeenCalledWith(request, "/api/v1/shipments");
    expect(response.status).toBe(200);
  });

  it("percent-encodes each segment before building the upstream path", async () => {
    const request = new Request(`${BASE}/parties/a%20b`);
    await GET(request, ctx(["parties", "a b", "c?d"]));

    expect(mocks.passThrough).toHaveBeenCalledWith(request, "/api/v1/parties/a%20b/c%3Fd");
  });

  it("returns the upstream response unchanged, including a 405 from Flask", async () => {
    mocks.passThrough.mockResolvedValueOnce(
      new Response("method not allowed", { status: 405, headers: { allow: "GET" } }),
    );

    const response = await DELETE(new Request(`${BASE}/cases/1`, { method: "DELETE" }), ctx(["cases", "1"]));

    expect(response.status).toBe(405);
    expect(response.headers.get("allow")).toBe("GET");
    expect(await response.text()).toBe("method not allowed");
  });

  it("passes an upstream 502 through rather than rewriting it", async () => {
    mocks.passThrough.mockResolvedValueOnce(
      Response.json({ error: "upstream_unreachable", detail: "down" }, { status: 502 }),
    );

    const response = await GET(new Request(`${BASE}/cases`), ctx(["cases"]));

    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({ error: "upstream_unreachable", detail: "down" });
  });

  it("answers 404 with a JSON error when the path is absent", async () => {
    const response = await GET(new Request(`${BASE}`), ctx(undefined));

    expect(response.status).toBe(404);
    expect(response.headers.get("content-type")).toContain("application/json");
    expect(await response.json()).toEqual({ error: "not_found" });
    expect(mocks.passThrough).not.toHaveBeenCalled();
  });

  it("answers 404 when the path is an empty list", async () => {
    const response = await GET(new Request(`${BASE}/`), ctx([]));

    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ error: "not_found" });
    expect(mocks.passThrough).not.toHaveBeenCalled();
  });

  it.each([
    ["an empty segment", ["cases", ""]],
    ["a dot segment", [".", "cases"]],
    ["a dot-dot segment that would leave /api/v1", ["..", "internal", "execute"]],
    ["a segment containing a forward slash", ["cases/42"]],
    ["a segment containing a backslash", ["cases\\42"]],
  ])("refuses a path with %s without contacting Flask", async (_label, segments) => {
    const response = await POST(new Request(`${BASE}/x`, { method: "POST" }), ctx(segments));

    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ error: "not_found" });
    expect(mocks.passThrough).not.toHaveBeenCalled();
  });

  it("still forwards a single valid segment", async () => {
    const request = new Request(`${BASE}/health`);
    await GET(request, ctx(["health"]));

    expect(mocks.passThrough).toHaveBeenCalledWith(request, "/api/v1/health");
  });
});
