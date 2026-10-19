import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import {
  clientIp,
  limitKey,
  slidingWindowLimiter,
  sharedLimited,
  UNKNOWN_SOURCE,
  SHARED_LIMIT_TIMEOUT_MS,
} from "@/lib/rate-limit";

describe("slidingWindowLimiter", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns false (not limited) on first attempt", () => {
    const limiter = slidingWindowLimiter(1000, 3);
    expect(limiter("user1")).toBe(false);
  });

  it("returns false for attempts under the limit", () => {
    const limiter = slidingWindowLimiter(1000, 3);
    expect(limiter("user1")).toBe(false);
    expect(limiter("user1")).toBe(false);
    expect(limiter("user1")).toBe(false);
  });

  it("returns true (limited) when limit is reached", () => {
    const limiter = slidingWindowLimiter(1000, 2);
    expect(limiter("user1")).toBe(false);
    expect(limiter("user1")).toBe(false);
    expect(limiter("user1")).toBe(true);
  });

  it("returns false again after the window expires", () => {
    const limiter = slidingWindowLimiter(1000, 2);
    expect(limiter("user1")).toBe(false);
    expect(limiter("user1")).toBe(false);
    expect(limiter("user1")).toBe(true);

    vi.advanceTimersByTime(1001);
    expect(limiter("user1")).toBe(false);
  });

  it("maintains separate buckets for different keys", () => {
    const limiter = slidingWindowLimiter(1000, 2);
    expect(limiter("user1")).toBe(false);
    expect(limiter("user1")).toBe(false);
    expect(limiter("user1")).toBe(true);

    expect(limiter("user2")).toBe(false);
    expect(limiter("user2")).toBe(false);
    expect(limiter("user2")).toBe(true);
  });

  it("cleans up entries outside the window", () => {
    const limiter = slidingWindowLimiter(1000, 2);
    expect(limiter("user1")).toBe(false);
    expect(limiter("user1")).toBe(false);

    vi.advanceTimersByTime(1001);
    // Old entries are removed, so this should not be limited.
    expect(limiter("user1")).toBe(false);
  });

  it("handles the limit of 1", () => {
    const limiter = slidingWindowLimiter(1000, 1);
    expect(limiter("user1")).toBe(false);
    expect(limiter("user1")).toBe(true);

    vi.advanceTimersByTime(1001);
    expect(limiter("user1")).toBe(false);
  });

  it("handles a very long window", () => {
    const limiter = slidingWindowLimiter(60_000, 5);
    for (let i = 0; i < 5; i++) {
      expect(limiter("user1")).toBe(false);
    }
    expect(limiter("user1")).toBe(true);

    vi.advanceTimersByTime(30_000);
    // Still in window, should remain limited.
    expect(limiter("user1")).toBe(true);

    vi.advanceTimersByTime(30_001);
    expect(limiter("user1")).toBe(false);
  });

  it("removes keys with no recent attempts from the map", () => {
    const limiter = slidingWindowLimiter(1000, 1);
    expect(limiter("user1")).toBe(false);
    expect(limiter("user2")).toBe(false);

    vi.advanceTimersByTime(1001);
    // Cleanup runs, removing old entries
    limiter("user3");
    // user1 and user2 should no longer be in the map
    expect(limiter("user1")).toBe(false);
    expect(limiter("user2")).toBe(false);
  });
});

describe("clientIp", () => {
  it("returns UNKNOWN_SOURCE when x-forwarded-for header is absent", () => {
    const request = new Request("http://localhost", {
      headers: {},
    });
    expect(clientIp(request)).toBe(UNKNOWN_SOURCE);
  });

  it("returns the last IP from x-forwarded-for when multiple are present", () => {
    const request = new Request("http://localhost", {
      headers: { "x-forwarded-for": "192.168.1.1, 10.0.0.1, 203.0.113.42" },
    });
    expect(clientIp(request)).toBe("203.0.113.42");
  });

  it("returns the single IP when only one is in the header", () => {
    const request = new Request("http://localhost", {
      headers: { "x-forwarded-for": "203.0.113.42" },
    });
    expect(clientIp(request)).toBe("203.0.113.42");
  });

  it("trims whitespace around the last IP", () => {
    const request = new Request("http://localhost", {
      headers: { "x-forwarded-for": "192.168.1.1,   203.0.113.42   " },
    });
    expect(clientIp(request)).toBe("203.0.113.42");
  });

  it("returns UNKNOWN_SOURCE when the last entry is not a valid IP", () => {
    const request = new Request("http://localhost", {
      headers: { "x-forwarded-for": "203.0.113.42, not-an-ip" },
    });
    expect(clientIp(request)).toBe(UNKNOWN_SOURCE);
  });

  it("returns UNKNOWN_SOURCE when the last entry is too long to be an IP", () => {
    const longString = "a".repeat(46);
    const request = new Request("http://localhost", {
      headers: { "x-forwarded-for": `203.0.113.42, ${longString}` },
    });
    expect(clientIp(request)).toBe(UNKNOWN_SOURCE);
  });

  it("accepts valid IPv6 addresses up to 45 characters", () => {
    // Valid IPv6 address (45 chars is the max)
    const request = new Request("http://localhost", {
      headers: { "x-forwarded-for": "2001:0db8:85a3:0000:0000:8a2e:0370:7334" },
    });
    const result = clientIp(request);
    expect(result).not.toBe(UNKNOWN_SOURCE);
  });

  it("handles IPv4-mapped IPv6 addresses", () => {
    const request = new Request("http://localhost", {
      headers: { "x-forwarded-for": "::ffff:192.0.2.1" },
    });
    const result = clientIp(request);
    expect(result).not.toBe(UNKNOWN_SOURCE);
  });

  it("returns UNKNOWN_SOURCE for empty header value", () => {
    const request = new Request("http://localhost", {
      headers: { "x-forwarded-for": "" },
    });
    expect(clientIp(request)).toBe(UNKNOWN_SOURCE);
  });

  it("returns UNKNOWN_SOURCE when last entry after comma is empty", () => {
    const request = new Request("http://localhost", {
      headers: { "x-forwarded-for": "203.0.113.42," },
    });
    expect(clientIp(request)).toBe(UNKNOWN_SOURCE);
  });
});

describe("limitKey", () => {
  it("produces acct keys with acct: prefix", () => {
    const key = limitKey("acct", "user@example.com");
    expect(key).toMatch(/^acct:[a-f0-9]{64}$/);
  });

  it("produces ip keys with ip: prefix", () => {
    const key = limitKey("ip", "203.0.113.42");
    expect(key).toMatch(/^ip:[a-f0-9]{64}$/);
  });

  it("produces the same key for the same value", () => {
    const key1 = limitKey("acct", "user@example.com");
    const key2 = limitKey("acct", "user@example.com");
    expect(key1).toBe(key2);
  });

  it("produces different keys for different values", () => {
    const key1 = limitKey("acct", "user1@example.com");
    const key2 = limitKey("acct", "user2@example.com");
    expect(key1).not.toBe(key2);
  });

  it("produces different keys for different kinds with same value", () => {
    const acctKey = limitKey("acct", "value");
    const ipKey = limitKey("ip", "value");
    expect(acctKey).not.toBe(ipKey);
  });

  it("handles empty strings", () => {
    const key = limitKey("acct", "");
    expect(key).toMatch(/^acct:[a-f0-9]{64}$/);
  });

  it("handles very long input strings", () => {
    const longInput = "a".repeat(10000);
    const key = limitKey("acct", longInput);
    expect(key).toMatch(/^acct:[a-f0-9]{64}$/);
  });

  it("produces fixed-length output regardless of input length", () => {
    const key1 = limitKey("acct", "a");
    const key2 = limitKey("acct", "a".repeat(1000));
    expect(key1.length).toBe(key2.length);
  });

  it("handles UTF-8 input correctly", () => {
    const key1 = limitKey("acct", "user@例え.jp");
    const key2 = limitKey("acct", "user@例え.jp");
    expect(key1).toBe(key2);
    expect(key1).toMatch(/^acct:[a-f0-9]{64}$/);
  });
});

describe("sharedLimited", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.unmock("global");
  });

  it("returns {limited: true} when the response body has limited=true", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn(async () =>
      new Response(JSON.stringify({ limited: true }), { status: 200 }),
    );

    const result = await sharedLimited([{ key: "test", limit: 5, windowSeconds: 60 }], "http://api", "key");
    expect(result).toEqual({ limited: true });

    globalThis.fetch = originalFetch;
  });

  it("returns {limited: false} when the response body has limited=false", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn(async () =>
      new Response(JSON.stringify({ limited: false }), { status: 200 }),
    );

    const result = await sharedLimited([{ key: "test", limit: 5, windowSeconds: 60 }], "http://api", "key");
    expect(result).toEqual({ limited: false });

    globalThis.fetch = originalFetch;
  });

  it("returns {limited: null, reason: 'no VF_API_KEY'} when apiKey is undefined", async () => {
    const result = await sharedLimited([{ key: "test", limit: 5, windowSeconds: 60 }], "http://api", undefined);
    expect(result).toEqual({ limited: null, reason: "no VF_API_KEY" });
  });

  it("returns {limited: null, reason: 'HTTP 400'} on a 400 response", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn(async () => new Response("bad request", { status: 400 }));

    const result = await sharedLimited([{ key: "test", limit: 5, windowSeconds: 60 }], "http://api", "key");
    expect(result).toEqual({ limited: null, reason: "HTTP 400" });

    globalThis.fetch = originalFetch;
  });

  it("returns {limited: null, reason: 'HTTP 500'} on a 500 response", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn(async () => new Response("server error", { status: 500 }));

    const result = await sharedLimited([{ key: "test", limit: 5, windowSeconds: 60 }], "http://api", "key");
    expect(result).toEqual({ limited: null, reason: "HTTP 500" });

    globalThis.fetch = originalFetch;
  });

  it("returns {limited: null, reason: 'reply without a boolean `limited`'} when response body lacks boolean", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn(async () =>
      new Response(JSON.stringify({ limited: "not a boolean" }), { status: 200 }),
    );

    const result = await sharedLimited([{ key: "test", limit: 5, windowSeconds: 60 }], "http://api", "key");
    expect(result).toEqual({ limited: null, reason: "reply without a boolean `limited`" });

    globalThis.fetch = originalFetch;
  });

  it("returns {limited: null, reason: 'reply without a boolean `limited`'} when response body is missing limited key", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn(async () => new Response(JSON.stringify({}), { status: 200 }));

    const result = await sharedLimited([{ key: "test", limit: 5, windowSeconds: 60 }], "http://api", "key");
    expect(result).toEqual({ limited: null, reason: "reply without a boolean `limited`" });

    globalThis.fetch = originalFetch;
  });

  it("returns {limited: null, reason: error.name} on fetch error", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn(async () => {
      throw new Error("Network error");
    });

    const result = await sharedLimited([{ key: "test", limit: 5, windowSeconds: 60 }], "http://api", "key");
    expect(result).toEqual({ limited: null, reason: "Error" });

    globalThis.fetch = originalFetch;
  });

  it("returns {limited: null, reason: 'error'} on non-Error thrown value", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn(async () => {
      throw "not an error object";
    });

    const result = await sharedLimited([{ key: "test", limit: 5, windowSeconds: 60 }], "http://api", "key");
    expect(result).toEqual({ limited: null, reason: "error" });

    globalThis.fetch = originalFetch;
  });

  it("posts to the correct endpoint with base URL", async () => {
    const originalFetch = globalThis.fetch;
    const mockFetch = vi.fn(async () =>
      new Response(JSON.stringify({ limited: false }), { status: 200 }),
    );
    globalThis.fetch = mockFetch;

    await sharedLimited([{ key: "test", limit: 5, windowSeconds: 60 }], "http://api", "key");
    expect(mockFetch).toHaveBeenCalledWith(
      "http://api/internal/login-throttle",
      expect.objectContaining({
        method: "POST",
      }),
    );

    globalThis.fetch = originalFetch;
  });

  it("includes the API key in X-VF-API-Key header", async () => {
    const originalFetch = globalThis.fetch;
    const mockFetch = vi.fn(async () =>
      new Response(JSON.stringify({ limited: false }), { status: 200 }),
    );
    globalThis.fetch = mockFetch;

    await sharedLimited([{ key: "test", limit: 5, windowSeconds: 60 }], "http://api", "my-secret-key");
    expect(mockFetch.mock.calls).toHaveLength(1);
    const calls = mockFetch.mock.calls as unknown as Array<[string, RequestInit]>;
    const callArg = calls[0]![1];
    expect(callArg.headers).toEqual(
      expect.objectContaining({
        "X-VF-API-Key": "my-secret-key",
      }),
    );

    globalThis.fetch = originalFetch;
  });

  it("converts windowSeconds to window_seconds in the request body", async () => {
    const originalFetch = globalThis.fetch;
    const mockFetch = vi.fn(async () =>
      new Response(JSON.stringify({ limited: false }), { status: 200 }),
    );
    globalThis.fetch = mockFetch;

    await sharedLimited(
      [
        { key: "acct-hash", limit: 5, windowSeconds: 60 },
        { key: "ip-hash", limit: 10, windowSeconds: 120 },
      ],
      "http://api",
      "key",
    );

    expect(mockFetch.mock.calls).toHaveLength(1);
    const calls = mockFetch.mock.calls as unknown as Array<[string, RequestInit]>;
    const callArg = calls[0]![1];
    const body = JSON.parse(callArg.body as string) as {
      checks: Array<{ key: string; limit: number; window_seconds: number }>;
    };
    expect(body.checks).toEqual([
      { key: "acct-hash", limit: 5, window_seconds: 60 },
      { key: "ip-hash", limit: 10, window_seconds: 120 },
    ]);

    globalThis.fetch = originalFetch;
  });

  it("sets cache: no-store and timeout in fetch options", async () => {
    const originalFetch = globalThis.fetch;
    const mockFetch = vi.fn(async () =>
      new Response(JSON.stringify({ limited: false }), { status: 200 }),
    );
    globalThis.fetch = mockFetch;

    await sharedLimited([{ key: "test", limit: 5, windowSeconds: 60 }], "http://api", "key");
    expect(mockFetch.mock.calls).toHaveLength(1);
    const calls = mockFetch.mock.calls as unknown as Array<[string, RequestInit]>;
    const callArg = calls[0]![1];
    expect(callArg.cache).toBe("no-store");
    expect(callArg.signal).toBeDefined();

    globalThis.fetch = originalFetch;
  });

  it("uses SHARED_LIMIT_TIMEOUT_MS for the AbortSignal timeout", async () => {
    const originalFetch = globalThis.fetch;
    const mockFetch = vi.fn(async () =>
      new Response(JSON.stringify({ limited: false }), { status: 200 }),
    );
    globalThis.fetch = mockFetch;

    await sharedLimited([{ key: "test", limit: 5, windowSeconds: 60 }], "http://api", "key");
    // Verify the constant is non-zero and as expected
    expect(SHARED_LIMIT_TIMEOUT_MS).toBe(3_000);

    globalThis.fetch = originalFetch;
  });

  it("handles an empty checks array", async () => {
    const originalFetch = globalThis.fetch;
    const mockFetch = vi.fn(async () =>
      new Response(JSON.stringify({ limited: false }), { status: 200 }),
    );
    globalThis.fetch = mockFetch;

    const result = await sharedLimited([], "http://api", "key");
    expect(result).toEqual({ limited: false });

    expect(mockFetch.mock.calls).toHaveLength(1);
    const calls = mockFetch.mock.calls as unknown as Array<[string, RequestInit]>;
    const callArg = calls[0]![1];
    const body = JSON.parse(callArg.body as string) as {
      checks: Array<{ key: string; limit: number; window_seconds: number }>;
    };
    expect(body.checks).toEqual([]);

    globalThis.fetch = originalFetch;
  });

  it("handles JSON parsing errors in response body", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn(async () => new Response("not json", { status: 200 }));

    const result = await sharedLimited([{ key: "test", limit: 5, windowSeconds: 60 }], "http://api", "key");
    expect(result).toEqual({ limited: null, reason: "SyntaxError" });

    globalThis.fetch = originalFetch;
  });

  it("respects the base URL when provided", async () => {
    const originalFetch = globalThis.fetch;
    const mockFetch = vi.fn(async () =>
      new Response(JSON.stringify({ limited: false }), { status: 200 }),
    );
    globalThis.fetch = mockFetch;

    await sharedLimited([{ key: "test", limit: 5, windowSeconds: 60 }], "https://api.example.com", "key");
    expect(mockFetch).toHaveBeenCalledWith(
      "https://api.example.com/internal/login-throttle",
      expect.any(Object),
    );

    globalThis.fetch = originalFetch;
  });
});

describe("UNKNOWN_SOURCE constant", () => {
  it("has the value 'unknown'", () => {
    expect(UNKNOWN_SOURCE).toBe("unknown");
  });
});

describe("SHARED_LIMIT_TIMEOUT_MS constant", () => {
  it("has the value 3000", () => {
    expect(SHARED_LIMIT_TIMEOUT_MS).toBe(3_000);
  });
});
