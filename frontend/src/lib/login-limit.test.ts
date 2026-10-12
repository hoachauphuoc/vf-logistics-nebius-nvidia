// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ACCOUNT_LIMIT,
  canonicalEmail,
  loginAttemptVerdict,
  type LoginLimitVerdict,
  resetLocalLoginLimits,
  SOURCE_LIMIT,
} from "./login-limit";
import { limitKey } from "./rate-limit";

/**
 * Authorization review finding A04, and re-review finding R01.
 *
 * A04: the limiter keyed on `${ip}|${email.toLowerCase()}` while verifyOperator
 * looked the account up by `email.trim().toLowerCase()`. Twelve spellings of one
 * address that differed only in leading spaces were one account and twelve
 * allowances. And the single combined key bounded neither the account (change
 * IP) nor the source (change account).
 *
 * R01: the source was the caller-written FIRST X-Forwarded-For entry, and any
 * ledger failure -- a 400 from an over-long key was enough -- fell through to a
 * local counter that had never seen the ledger's attempts.
 */

const BASE = "http://127.0.0.1:9090";

function from(xff: string): Request {
  return new Request("https://vf.example/api/auth/login", {
    method: "POST",
    headers: { "x-forwarded-for": xff },
  });
}

/** No API key, so the shared counter is skipped and the local fallback decides. */
async function localAttempt(email: string, ip = "203.0.113.7"): Promise<LoginLimitVerdict> {
  return loginAttemptVerdict(canonicalEmail(email), from(ip), BASE, undefined);
}

const allowed = (verdicts: LoginLimitVerdict[]) => verdicts.filter((v) => v === "allowed");

describe("one account is one allowance however it is spelt", () => {
  beforeEach(() => resetLocalLoginLimits());

  it("the review's twelve padded spellings exhaust one allowance", async () => {
    const results: LoginLimitVerdict[] = [];
    for (let pad = 0; pad < 12; pad += 1) {
      results.push(await localAttempt(`${" ".repeat(pad)}Judge@VF-Logistics.demo`));
    }
    expect(allowed(results)).toHaveLength(ACCOUNT_LIMIT);
    expect(results.slice(ACCOUNT_LIMIT).every((v) => v === "limited")).toBe(true);
  });

  it("canonicalises exactly as the account lookup does", () => {
    expect(canonicalEmail("  Judge@VF-Logistics.Demo \t")).toBe("judge@vf-logistics.demo");
  });
});

describe("the account and the source are limited independently", () => {
  beforeEach(() => resetLocalLoginLimits());

  it("a new address does not buy the same account a fresh allowance", async () => {
    const results: LoginLimitVerdict[] = [];
    for (let i = 0; i < ACCOUNT_LIMIT + 3; i += 1) {
      results.push(await localAttempt("judge@vf-logistics.demo", `198.51.100.${i}`));
    }
    expect(allowed(results)).toHaveLength(ACCOUNT_LIMIT);
  });

  it("a new account does not buy the same address a fresh allowance", async () => {
    const results: LoginLimitVerdict[] = [];
    for (let i = 0; i < SOURCE_LIMIT + 3; i += 1) {
      results.push(await localAttempt(`person${i}@vf-logistics.demo`, "203.0.113.9"));
    }
    expect(allowed(results)).toHaveLength(SOURCE_LIMIT);
  });

  it("one account being locked does not lock a different account on the same address", async () => {
    for (let i = 0; i < ACCOUNT_LIMIT + 1; i += 1) await localAttempt("judge@vf-logistics.demo");
    expect(await localAttempt("reviewer@vf-logistics.demo")).toBe("allowed");
  });
});

/** A stand-in for Flask's ledger: one Map that every "instance" consults. */
function sharedLedger() {
  const ledger = new Map<string, number>();
  let failing: (() => Response | never) | null = null;
  const spy = vi.fn(async (_url: string, init?: RequestInit) => {
    if (failing) return failing();
    const body = JSON.parse(String(init?.body)) as {
      checks: Array<{ key: string; limit: number }>;
    };
    // Flask's own validation: a key over 300 characters is a 400.
    if (body.checks.some(({ key }) => key.length > 300)) {
      return Response.json({ error: "bad key" }, { status: 400 });
    }
    const results = body.checks.map(({ key, limit }) => {
      const used = ledger.get(key) ?? 0;
      if (used >= limit) return true;
      ledger.set(key, used + 1);
      return false;
    });
    return Response.json({ limited: results.some(Boolean), results });
  });
  globalThis.fetch = spy as unknown as typeof fetch;
  return {
    ledger,
    spy,
    failWith(reply: () => Response | never) {
      failing = reply;
    },
  };
}

describe("the shared counter", () => {
  beforeEach(() => {
    resetLocalLoginLimits();
    vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it("sends fixed-length keys for the canonical account and the source, with the console key", async () => {
    const { spy } = sharedLedger();
    await loginAttemptVerdict(canonicalEmail(" Judge@X.example "), from("203.0.113.1"), BASE, "k");
    const [url, init] = spy.mock.calls[0];
    expect(url).toBe(`${BASE}/internal/login-throttle`);
    expect(new Headers(init?.headers).get("x-vf-api-key")).toBe("k");
    expect(JSON.parse(String(init?.body)).checks.map((c: { key: string }) => c.key)).toEqual([
      limitKey("acct", "judge@x.example"),
      limitKey("ip", "203.0.113.1"),
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

    const results: LoginLimitVerdict[] = [];
    for (let i = 0; i < ACCOUNT_LIMIT + 2; i += 1) {
      const instance = i % 2 === 0 ? instanceA : instanceB;
      results.push(
        await instance.loginAttemptVerdict("judge@x.example", from(`198.51.100.${i}`), BASE, "k"),
      );
    }
    expect(allowed(results)).toHaveLength(ACCOUNT_LIMIT);
    expect(results.slice(ACCOUNT_LIMIT).every((v) => v === "limited")).toBe(true);
  });

  it("the review's case: a long first header entry no longer buys five more attempts", async () => {
    sharedLedger();
    const results: LoginLimitVerdict[] = [];
    for (let i = 0; i < ACCOUNT_LIMIT; i += 1) {
      results.push(await loginAttemptVerdict("judge@x.example", from("203.0.113.4"), BASE, "k"));
    }
    for (let i = 0; i < ACCOUNT_LIMIT + 1; i += 1) {
      const forged = `${"9".repeat(400 + i)}, 203.0.113.4`;
      results.push(await loginAttemptVerdict("judge@x.example", from(forged), BASE, "k"));
    }
    expect(allowed(results)).toHaveLength(ACCOUNT_LIMIT);
    expect(results.slice(ACCOUNT_LIMIT).every((v) => v === "limited")).toBe(true);
  });

  it("an over-long account cannot make the ledger refuse the count", async () => {
    const { spy } = sharedLedger();
    const results: LoginLimitVerdict[] = [];
    for (let i = 0; i < ACCOUNT_LIMIT + 1; i += 1) {
      results.push(await loginAttemptVerdict(`${"a".repeat(1000)}@x.example`, from("203.0.113.5"), BASE, "k"));
    }
    expect(results.at(-1)).toBe("limited");
    for (const [, init] of spy.mock.calls) {
      for (const check of JSON.parse(String(init?.body)).checks as Array<{ key: string }>) {
        expect(check.key.length).toBeLessThanOrEqual(300);
      }
    }
  });

  it("the review's case: one real source changing the forged prefix and the account stays one bucket", async () => {
    sharedLedger();
    const results: LoginLimitVerdict[] = [];
    for (let i = 0; i < 25; i += 1) {
      results.push(
        await loginAttemptVerdict(`person${i}@x.example`, from(`10.0.${i}.1, 203.0.113.6`), BASE, "k"),
      );
    }
    expect(allowed(results)).toHaveLength(SOURCE_LIMIT);
    expect(results.slice(SOURCE_LIMIT).every((v) => v === "limited")).toBe(true);
  });

  it.each([
    ["a 400", () => Response.json({ error: "bad" }, { status: 400 })],
    ["a 403", () => Response.json({ error: "choose a tenant", choices: ["a", "b"] }, { status: 403 })],
    ["a 500", () => new Response("boom", { status: 500 })],
    ["a body without a boolean", () => Response.json({ limited: "no" })],
    ["a refused connection", () => {
      throw new TypeError("fetch failed");
    }],
    ["a timeout", () => {
      throw new DOMException("timed out", "TimeoutError");
    }],
  ])("%s from the ledger refuses the attempt rather than counting it locally", async (_name, reply) => {
    const { failWith } = sharedLedger();
    failWith(reply);
    const results: LoginLimitVerdict[] = [];
    for (let i = 0; i < ACCOUNT_LIMIT + 2; i += 1) {
      results.push(await loginAttemptVerdict("judge@x.example", from("203.0.113.7"), BASE, "k"));
    }
    expect(results.every((v) => v === "unavailable")).toBe(true);
    expect(console.error).toHaveBeenCalled();
  });

  it("the ledger failing after it has counted five opens no further attempt", async () => {
    const { failWith } = sharedLedger();
    const results: LoginLimitVerdict[] = [];
    for (let i = 0; i < ACCOUNT_LIMIT; i += 1) {
      results.push(await loginAttemptVerdict("judge@x.example", from("203.0.113.8"), BASE, "k"));
    }
    failWith(() => Response.json({ error: "bad" }, { status: 400 }));
    for (let i = 0; i < ACCOUNT_LIMIT; i += 1) {
      results.push(await loginAttemptVerdict("judge@x.example", from("203.0.113.8"), BASE, "k"));
    }
    expect(allowed(results)).toHaveLength(ACCOUNT_LIMIT);
    expect(results.slice(ACCOUNT_LIMIT).every((v) => v === "unavailable")).toBe(true);
  });
});

describe("counting locally", () => {
  beforeEach(() => resetLocalLoginLimits());
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it("is refused on a production server even without a key", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.spyOn(console, "error").mockImplementation(() => {});
    const fetchSpy = vi.fn();
    globalThis.fetch = fetchSpy as unknown as typeof fetch;
    expect(await localAttempt("judge@x.example")).toBe("unavailable");
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
