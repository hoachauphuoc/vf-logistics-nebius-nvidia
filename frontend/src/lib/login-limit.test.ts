// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ACCOUNT_LIMIT,
  canonicalEmail,
  isLoginRateLimited,
  resetLocalLoginLimits,
  SOURCE_LIMIT,
} from "./login-limit";

/**
 * Authorization review finding A04.
 *
 * The limiter keyed on `${ip}|${email.toLowerCase()}` while verifyOperator looked
 * the account up by `email.trim().toLowerCase()`. Twelve spellings of one address
 * that differed only in leading spaces were one account and twelve allowances --
 * the review counted 12 attempts, 1 account, 0 blocked. And the single combined
 * key bounded neither the account (change IP) nor the source (change account).
 */

const BASE = "http://127.0.0.1:9090";

function from(ip: string): Request {
  return new Request("https://vf.example/api/auth/login", {
    method: "POST",
    headers: { "x-forwarded-for": ip },
  });
}

/** No API key, so the shared counter is skipped and the local fallback decides. */
async function localAttempt(email: string, ip = "203.0.113.7"): Promise<boolean> {
  return isLoginRateLimited(canonicalEmail(email), from(ip), BASE, undefined);
}

describe("one account is one allowance however it is spelt", () => {
  beforeEach(() => resetLocalLoginLimits());

  it("the review's twelve padded spellings exhaust one allowance", async () => {
    const results: boolean[] = [];
    for (let pad = 0; pad < 12; pad += 1) {
      results.push(await localAttempt(`${" ".repeat(pad)}Judge@VF-Logistics.demo`));
    }
    expect(results.filter((limited) => !limited)).toHaveLength(ACCOUNT_LIMIT);
    expect(results.slice(ACCOUNT_LIMIT).every(Boolean)).toBe(true);
  });

  it("canonicalises exactly as the account lookup does", () => {
    expect(canonicalEmail("  Judge@VF-Logistics.Demo \t")).toBe("judge@vf-logistics.demo");
  });
});

describe("the account and the source are limited independently", () => {
  beforeEach(() => resetLocalLoginLimits());

  it("a new address does not buy the same account a fresh allowance", async () => {
    const results: boolean[] = [];
    for (let i = 0; i < ACCOUNT_LIMIT + 3; i += 1) {
      results.push(await localAttempt("judge@vf-logistics.demo", `198.51.100.${i}`));
    }
    expect(results.filter((limited) => !limited)).toHaveLength(ACCOUNT_LIMIT);
  });

  it("a new account does not buy the same address a fresh allowance", async () => {
    const results: boolean[] = [];
    for (let i = 0; i < SOURCE_LIMIT + 3; i += 1) {
      results.push(await localAttempt(`person${i}@vf-logistics.demo`, "203.0.113.9"));
    }
    expect(results.filter((limited) => !limited)).toHaveLength(SOURCE_LIMIT);
  });

  it("one account being locked does not lock a different account on the same address", async () => {
    for (let i = 0; i < ACCOUNT_LIMIT + 1; i += 1) await localAttempt("judge@vf-logistics.demo");
    expect(await localAttempt("reviewer@vf-logistics.demo")).toBe(false);
  });
});

describe("the shared counter", () => {
  beforeEach(() => resetLocalLoginLimits());
  afterEach(() => vi.restoreAllMocks());

  /** A stand-in for Flask's ledger: one Map that every \"instance\" consults. */
  function sharedLedger() {
    const ledger = new Map<string, number>();
    const spy = vi.fn(async (_url: string, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body)) as {
        checks: Array<{ key: string; limit: number }>;
      };
      const results = body.checks.map(({ key, limit }) => {
        const used = ledger.get(key) ?? 0;
        if (used >= limit) return true;
        ledger.set(key, used + 1);
        return false;
      });
      return Response.json({ limited: results.some(Boolean), results });
    });
    globalThis.fetch = spy as unknown as typeof fetch;
    return { ledger, spy };
  }

  it("sends the canonical account and the source, with the console key", async () => {
    const { spy } = sharedLedger();
    await isLoginRateLimited(canonicalEmail(" Judge@X.example "), from("203.0.113.1"), BASE, "k");
    const [url, init] = spy.mock.calls[0];
    expect(url).toBe(`${BASE}/internal/login-throttle`);
    expect(new Headers(init?.headers).get("x-vf-api-key")).toBe("k");
    expect(JSON.parse(String(init?.body)).checks.map((c: { key: string }) => c.key)).toEqual([
      "acct:judge@x.example",
      "ip:203.0.113.1",
    ]);
  });

  it("two console instances spend one allowance", async () => {
    sharedLedger();
    // Two module instances, so each has its own local Map -- as two Cloud Run
    // instances would. Only the shared ledger is common to both.
    vi.resetModules();
    const instanceA = await import("./login-limit");
    vi.resetModules();
    const instanceB = await import("./login-limit");

    const results: boolean[] = [];
    for (let i = 0; i < ACCOUNT_LIMIT + 2; i += 1) {
      const instance = i % 2 === 0 ? instanceA : instanceB;
      results.push(
        await instance.isLoginRateLimited("judge@x.example", from(`198.51.100.${i}`), BASE, "k"),
      );
    }
    expect(results.filter((limited) => !limited)).toHaveLength(ACCOUNT_LIMIT);
  });

  it("falls back to the local limiter when Flask cannot answer", async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new Error("connection refused");
    }) as unknown as typeof fetch;
    const results: boolean[] = [];
    for (let i = 0; i < ACCOUNT_LIMIT + 1; i += 1) {
      results.push(await isLoginRateLimited("judge@x.example", from("203.0.113.2"), BASE, "k"));
    }
    expect(results.at(-1)).toBe(true);
  });

  it("falls back on a non-2xx reply rather than reading it as allowed", async () => {
    globalThis.fetch = vi.fn(async () => new Response("no", { status: 403 })) as unknown as typeof fetch;
    for (let i = 0; i < ACCOUNT_LIMIT; i += 1) {
      await isLoginRateLimited("judge@x.example", from("203.0.113.3"), BASE, "k");
    }
    expect(await isLoginRateLimited("judge@x.example", from("203.0.113.3"), BASE, "k")).toBe(true);
  });
});
