// @vitest-environment node
import { describe, expect, it } from "vitest";

import { clientIp, limitKey, UNKNOWN_SOURCE } from "./rate-limit";

/**
 * Re-review finding R01: the source address a sign-in is counted against.
 *
 * Cloud Run's front end appends the address it saw to whatever X-Forwarded-For
 * the caller sent, so only the LAST entry was written by the infrastructure.
 */

function withXff(xff?: string): Request {
  return new Request("https://vf.example/api/auth/login", {
    method: "POST",
    headers: xff === undefined ? {} : { "x-forwarded-for": xff },
  });
}

describe("clientIp", () => {
  it("is the entry the front end appended, not the one the caller wrote", () => {
    expect(clientIp(withXff("6.6.6.6, 203.0.113.9"))).toBe("203.0.113.9");
    expect(clientIp(withXff("203.0.113.9"))).toBe("203.0.113.9");
  });

  it("does not move when the caller changes the entries in front of it", () => {
    const seen = new Set(
      ["1.1.1.1", "2.2.2.2, 3.3.3.3", "x".repeat(10_000), "", "not-an-ip"].map((forged) =>
        clientIp(withXff(`${forged}, 198.51.100.4`)),
      ),
    );
    expect([...seen]).toEqual(["198.51.100.4"]);
  });

  it("accepts IPv6", () => {
    expect(clientIp(withXff("2001:db8::1"))).toBe("2001:db8::1");
    expect(clientIp(withXff("1.2.3.4, ::ffff:203.0.113.9"))).toBe("::ffff:203.0.113.9");
  });

  it.each([
    ["no header", undefined],
    ["an empty header", ""],
    ["a non-address", "evil"],
    ["a 10 KB value", "1".repeat(10_000)],
    ["an address with a port", "203.0.113.9:443"],
    ["a trailing comma", "203.0.113.9,"],
  ])("is unknown for %s", (_name, xff) => {
    expect(clientIp(withXff(xff))).toBe(UNKNOWN_SOURCE);
  });
});

describe("limitKey", () => {
  it("has one length whatever the value, well inside the ledger's 300", () => {
    const lengths = new Set(["", "a", "x".repeat(5_000), "人".repeat(1_000)].map((v) => limitKey("acct", v).length));
    expect(lengths.size).toBe(1);
    expect([...lengths][0]).toBeLessThanOrEqual(300);
  });

  it("keeps the kinds apart and does not carry the raw value", () => {
    expect(limitKey("acct", "203.0.113.9")).not.toBe(limitKey("ip", "203.0.113.9"));
    expect(limitKey("acct", "judge@x.example")).not.toContain("judge");
    expect(limitKey("ip", "203.0.113.9")).toMatch(/^ip:[0-9a-f]{64}$/);
  });
});
