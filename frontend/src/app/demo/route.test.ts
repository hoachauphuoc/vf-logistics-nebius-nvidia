import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/upstream", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/upstream")>()),
  passThrough: vi.fn(),
}));

import { passThrough } from "@/lib/upstream";
import { dynamic, GET } from "./route";

describe("demo route", () => {
  it("exports dynamic as force-dynamic", () => {
    expect(dynamic).toBe("force-dynamic");
  });

  it("GET calls passThrough with the request and /demo path", async () => {
    const mockResponse = new Response(JSON.stringify({ status: "ok" }), { status: 200 });
    vi.mocked(passThrough).mockResolvedValue(mockResponse);

    const mockRequest = new Request("http://localhost:3000/demo", {
      method: "GET",
    });

    const result = await GET(mockRequest);

    expect(passThrough).toHaveBeenCalledWith(mockRequest, "/demo");
    expect(passThrough).toHaveBeenCalledTimes(1);
    expect(result).toBe(mockResponse);
  });

  it("GET returns the response from passThrough unchanged", async () => {
    const mockResponse = new Response("test body", {
      status: 201,
      statusText: "Created",
      headers: { "content-type": "text/plain" },
    });
    vi.mocked(passThrough).mockResolvedValue(mockResponse);

    const mockRequest = new Request("http://localhost:3000/demo", {
      method: "POST",
      body: "data",
    });

    const result = await GET(mockRequest);

    expect(result).toBe(mockResponse);
    expect(result.status).toBe(201);
    expect(result.statusText).toBe("Created");
  });

  it("GET handles error responses from passThrough", async () => {
    const mockResponse = new Response(
      JSON.stringify({ error: "upstream_unreachable" }),
      { status: 502 },
    );
    vi.mocked(passThrough).mockResolvedValue(mockResponse);

    const mockRequest = new Request("http://localhost:3000/demo", {
      method: "GET",
    });

    const result = await GET(mockRequest);

    expect(result.status).toBe(502);
  });

  it("GET is async and returns a Promise", () => {
    const mockRequest = new Request("http://localhost:3000/demo");
    vi.mocked(passThrough).mockResolvedValue(new Response("ok"));

    const result = GET(mockRequest);

    expect(result instanceof Promise).toBe(true);
  });

  it("GET forwards request with different HTTP methods", async () => {
    const mockResponse = new Response("ok", { status: 200 });
    vi.mocked(passThrough).mockResolvedValue(mockResponse);

    const methods = ["GET", "POST", "PUT", "DELETE", "PATCH"];

    for (const method of methods) {
      vi.mocked(passThrough).mockClear();
      const mockRequest = new Request("http://localhost:3000/demo", {
        method,
      });

      await GET(mockRequest);

      expect(passThrough).toHaveBeenCalledWith(mockRequest, "/demo");
    }
  });

  it("GET preserves request body and headers", async () => {
    const mockResponse = new Response("ok");
    vi.mocked(passThrough).mockResolvedValue(mockResponse);

    const mockRequest = new Request("http://localhost:3000/demo", {
      method: "POST",
      body: JSON.stringify({ key: "value" }),
      headers: { "authorization": "Bearer token123" },
    });

    await GET(mockRequest);

    expect(passThrough).toHaveBeenCalledWith(mockRequest, "/demo");
  });

  it("GET uses request with query parameters", async () => {
    const mockResponse = new Response("ok");
    vi.mocked(passThrough).mockResolvedValue(mockResponse);

    const mockRequest = new Request("http://localhost:3000/demo?param1=value1&param2=value2", {
      method: "GET",
    });

    await GET(mockRequest);

    expect(passThrough).toHaveBeenCalledWith(mockRequest, "/demo");
  });

  it("GET is exported as a named export", async () => {
    expect(typeof GET).toBe("function");
    expect(GET.name).toBe("GET");
  });

  it("GET always passes /demo as the path", async () => {
    const mockResponse = new Response("ok");
    vi.mocked(passThrough).mockResolvedValue(mockResponse);

    const mockRequest = new Request("http://localhost:3000/different/path", {
      method: "GET",
    });

    await GET(mockRequest);

    const calls = vi.mocked(passThrough).mock.calls;
    expect(calls[calls.length - 1][1]).toBe("/demo");
  });
});
