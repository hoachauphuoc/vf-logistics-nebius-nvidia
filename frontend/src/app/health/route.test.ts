import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  passThrough: vi.fn(),
}));

vi.mock("@/lib/upstream", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/upstream")>()),
  passThrough: mocks.passThrough,
}));

import { GET, HEAD } from "./route";

describe("GET /health", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("forwards the request to passThrough with /health path", async () => {
    const mockResponse = new Response("ok", { status: 200 });
    mocks.passThrough.mockResolvedValueOnce(mockResponse);

    const request = new Request("https://vf.example/health");
    const response = await GET(request);

    expect(mocks.passThrough).toHaveBeenCalledWith(request, "/health");
    expect(response.status).toBe(200);
  });

  it("returns the response from passThrough directly", async () => {
    const mockResponse = new Response("healthy", {
      status: 200,
      headers: { "content-type": "text/plain" },
    });
    mocks.passThrough.mockResolvedValueOnce(mockResponse);

    const request = new Request("https://vf.example/health");
    const response = await GET(request);

    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("text/plain");
  });

  it("returns a 200 response on success", async () => {
    mocks.passThrough.mockResolvedValueOnce(new Response("", { status: 200 }));

    const request = new Request("https://vf.example/health");
    const response = await GET(request);

    expect(response.status).toBe(200);
  });

  it("returns a 503 response when upstream is unavailable", async () => {
    mocks.passThrough.mockResolvedValueOnce(new Response("", { status: 503 }));

    const request = new Request("https://vf.example/health");
    const response = await GET(request);

    expect(response.status).toBe(503);
  });

  it("handles empty response body", async () => {
    mocks.passThrough.mockResolvedValueOnce(new Response("", { status: 200 }));

    const request = new Request("https://vf.example/health");
    const response = await GET(request);

    expect(await response.text()).toBe("");
  });

  it("preserves headers from upstream response", async () => {
    const mockResponse = new Response("data", {
      status: 200,
      headers: {
        "x-custom-header": "custom-value",
        "cache-control": "no-cache",
      },
    });
    mocks.passThrough.mockResolvedValueOnce(mockResponse);

    const request = new Request("https://vf.example/health");
    const response = await GET(request);

    expect(response.headers.get("x-custom-header")).toBe("custom-value");
    expect(response.headers.get("cache-control")).toBe("no-cache");
  });
});

describe("HEAD /health", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("forwards the request to passThrough with /health path", async () => {
    const mockResponse = new Response("ok", { status: 200 });
    mocks.passThrough.mockResolvedValueOnce(mockResponse);

    const request = new Request("https://vf.example/health", { method: "HEAD" });
    const response = await HEAD(request);

    expect(mocks.passThrough).toHaveBeenCalledWith(request, "/health");
    expect(response.status).toBe(200);
  });

  it("returns the response from passThrough directly", async () => {
    const mockResponse = new Response("healthy", {
      status: 200,
      headers: { "content-type": "text/plain" },
    });
    mocks.passThrough.mockResolvedValueOnce(mockResponse);

    const request = new Request("https://vf.example/health", { method: "HEAD" });
    const response = await HEAD(request);

    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("text/plain");
  });

  it("returns a 200 response on success", async () => {
    mocks.passThrough.mockResolvedValueOnce(new Response("", { status: 200 }));

    const request = new Request("https://vf.example/health", { method: "HEAD" });
    const response = await HEAD(request);

    expect(response.status).toBe(200);
  });

  it("returns a 503 response when upstream is unavailable", async () => {
    mocks.passThrough.mockResolvedValueOnce(new Response("", { status: 503 }));

    const request = new Request("https://vf.example/health", { method: "HEAD" });
    const response = await HEAD(request);

    expect(response.status).toBe(503);
  });

  it("preserves headers from upstream response", async () => {
    const mockResponse = new Response("data", {
      status: 200,
      headers: {
        "x-custom-header": "custom-value",
        "cache-control": "no-cache",
      },
    });
    mocks.passThrough.mockResolvedValueOnce(mockResponse);

    const request = new Request("https://vf.example/health", { method: "HEAD" });
    const response = await HEAD(request);

    expect(response.headers.get("x-custom-header")).toBe("custom-value");
    expect(response.headers.get("cache-control")).toBe("no-cache");
  });
});
