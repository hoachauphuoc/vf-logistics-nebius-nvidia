// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/upstream", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/upstream")>()),
  passThrough: vi.fn(),
}));

import { passThrough } from "@/lib/upstream";
import { GET } from "./route";

describe("GET /metrics", () => {
  beforeEach(() => {
    vi.mocked(passThrough).mockClear();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("forwards the request to passThrough with /metrics path", async () => {
    const mockResponse = new Response("metrics data", { status: 200 });
    vi.mocked(passThrough).mockResolvedValueOnce(mockResponse);

    const request = new Request("https://vf.example/metrics");
    const response = await GET(request);

    expect(passThrough).toHaveBeenCalledWith(request, "/metrics");
    expect(response.status).toBe(200);
    expect(await response.text()).toBe("metrics data");
  });

  it("returns the response from passThrough directly", async () => {
    const testBody = "prometheus format metrics\nhttp_requests_total 42\n";
    const mockResponse = new Response(testBody, {
      status: 200,
      headers: { "content-type": "text/plain" },
    });
    vi.mocked(passThrough).mockResolvedValueOnce(mockResponse);

    const request = new Request("https://vf.example/metrics");
    const response = await GET(request);

    expect(await response.text()).toBe(testBody);
    expect(response.headers.get("content-type")).toBe("text/plain");
  });

  it("passes through query parameters in the request URL", async () => {
    const mockResponse = new Response("", { status: 200 });
    vi.mocked(passThrough).mockResolvedValueOnce(mockResponse);

    const request = new Request("https://vf.example/metrics?filter=latency&limit=100");
    await GET(request);

    expect(passThrough).toHaveBeenCalledWith(request, "/metrics");
  });

  it("handles upstream timeout error responses", async () => {
    const timeoutResponse = Response.json(
      { error: "upstream_timeout", detail: "No answer within 300s." },
      { status: 504 }
    );
    vi.mocked(passThrough).mockResolvedValueOnce(timeoutResponse);

    const request = new Request("https://vf.example/metrics");
    const response = await GET(request);

    expect(response.status).toBe(504);
    const body = await response.json();
    expect(body.error).toBe("upstream_timeout");
  });

  it("handles upstream connection error responses", async () => {
    const errorResponse = Response.json(
      { error: "upstream_unreachable", detail: "connect ECONNREFUSED" },
      { status: 502 }
    );
    vi.mocked(passThrough).mockResolvedValueOnce(errorResponse);

    const request = new Request("https://vf.example/metrics");
    const response = await GET(request);

    expect(response.status).toBe(502);
    const body = await response.json();
    expect(body.error).toBe("upstream_unreachable");
  });

  it("preserves custom headers from upstream response", async () => {
    const mockResponse = new Response("data", {
      status: 200,
      headers: {
        "x-custom-header": "custom-value",
        "cache-control": "no-cache",
      },
    });
    vi.mocked(passThrough).mockResolvedValueOnce(mockResponse);

    const request = new Request("https://vf.example/metrics");
    const response = await GET(request);

    expect(response.headers.get("x-custom-header")).toBe("custom-value");
    expect(response.headers.get("cache-control")).toBe("no-cache");
  });

  it("handles different upstream status codes", async () => {
    const statuses = [200, 201, 400, 401, 403, 404, 500, 503];
    for (const status of statuses) {
      vi.mocked(passThrough).mockResolvedValueOnce(new Response("", { status }));
      const request = new Request("https://vf.example/metrics");
      const response = await GET(request);
      expect(response.status).toBe(status);
    }
  });

  it("handles empty response body", async () => {
    const mockResponse = new Response("", { status: 200 });
    vi.mocked(passThrough).mockResolvedValueOnce(mockResponse);

    const request = new Request("https://vf.example/metrics");
    const response = await GET(request);

    expect(response.status).toBe(200);
    expect(await response.text()).toBe("");
  });

  it("handles large response bodies", async () => {
    const largeBody = "x".repeat(10_000);
    const mockResponse = new Response(largeBody, {
      status: 200,
      headers: { "content-type": "text/plain" },
    });
    vi.mocked(passThrough).mockResolvedValueOnce(mockResponse);

    const request = new Request("https://vf.example/metrics");
    const response = await GET(request);

    const responseText = await response.text();
    expect(responseText).toBe(largeBody);
    expect(responseText.length).toBe(10_000);
  });

  it("handles request with different origins and paths", async () => {
    const urls = [
      "https://vf.example/metrics",
      "http://localhost:3000/metrics",
      "https://api.prod.example/metrics",
    ];

    for (const url of urls) {
      vi.mocked(passThrough).mockResolvedValueOnce(new Response("", { status: 200 }));
      const request = new Request(url);
      await GET(request);
      expect(passThrough).toHaveBeenCalledWith(request, "/metrics");
    }
  });

  it("returns a Promise that resolves to a Response", async () => {
    vi.mocked(passThrough).mockResolvedValueOnce(new Response("test", { status: 200 }));
    const request = new Request("https://vf.example/metrics");
    const result = GET(request);

    expect(result instanceof Promise).toBe(true);
    const response = await result;
    expect(response instanceof Response).toBe(true);
  });

  it("always uses /metrics path regardless of request URL", async () => {
    vi.mocked(passThrough).mockResolvedValueOnce(new Response("", { status: 200 }));

    const request = new Request("https://vf.example/some/other/path?key=value");
    await GET(request);

    const [, path] = vi.mocked(passThrough).mock.calls[0];
    expect(path).toBe("/metrics");
  });

  it("handles response with JSON content type", async () => {
    const jsonData = { cpu: 0.45, memory: 0.72, requests: 1234 };
    const mockResponse = Response.json(jsonData, {
      status: 200,
      headers: { "content-type": "application/json" },
    });
    vi.mocked(passThrough).mockResolvedValueOnce(mockResponse);

    const request = new Request("https://vf.example/metrics");
    const response = await GET(request);

    expect(response.headers.get("content-type")).toBe("application/json");
    expect(await response.json()).toEqual(jsonData);
  });

  it("handles response status text", async () => {
    const mockResponse = new Response("Not Found", {
      status: 404,
      statusText: "Not Found",
    });
    vi.mocked(passThrough).mockResolvedValueOnce(mockResponse);

    const request = new Request("https://vf.example/metrics");
    const response = await GET(request);

    expect(response.status).toBe(404);
    expect(response.statusText).toBe("Not Found");
  });

  it("maintains request object integrity when forwarding", async () => {
    const mockResponse = new Response("", { status: 200 });
    vi.mocked(passThrough).mockResolvedValueOnce(mockResponse);

    const headers = new Headers({
      "user-agent": "test-agent",
      "x-custom": "custom-value",
    });
    const request = new Request("https://vf.example/metrics", {
      method: "GET",
      headers,
    });

    await GET(request);

    const [passedRequest] = vi.mocked(passThrough).mock.calls[0];
    expect(passedRequest).toBe(request);
    expect(passedRequest.method).toBe("GET");
  });

  it("handles response with multiple calls in sequence", async () => {
    vi.mocked(passThrough)
      .mockResolvedValueOnce(new Response("first", { status: 200 }))
      .mockResolvedValueOnce(new Response("second", { status: 200 }))
      .mockResolvedValueOnce(new Response("third", { status: 200 }));

    for (let i = 0; i < 3; i++) {
      const request = new Request("https://vf.example/metrics");
      const response = await GET(request);
      expect(response.status).toBe(200);
    }

    expect(vi.mocked(passThrough)).toHaveBeenCalledTimes(3);
  });
});
