import { describe, expect, it } from "vitest";

import {
  ALLOWED_GET,
  ALLOWED_POST,
  describedReads,
  describedWrites,
  matchRead,
  matchWrite,
} from "./proxy-policy";

describe("matchRead", () => {
  it("allows the exact reads and the id-carrying ones", () => {
    expect(matchRead("orchestrator/state")).toBe(true);
    expect(matchRead("auth/whoami")).toBe(true);
    expect(matchRead("auth/policy")).toBe(true);
    expect(matchRead("orchestrator/case/CASE-1")).toBe(true);
    expect(matchRead("review/CASE-1/document")).toBe(true);
    expect(matchRead("compliance/audit/AUD-9")).toBe(true);
  });

  it("refuses traversal hidden in an id and routes nobody listed", () => {
    expect(matchRead("orchestrator/case/..")).toBe(false);
    expect(matchRead("review/../document")).toBe(false);
    expect(matchRead("orchestrator/reset")).toBe(false);
    expect(matchRead("review/CASE-1/decide")).toBe(false);
  });
});

describe("matchWrite", () => {
  it("resolves the review routes by shape", () => {
    expect(matchWrite("review/CASE-1/decide", ALLOWED_POST)).toBe(true);
    expect(matchWrite("review/CASE-1/deep-review", ALLOWED_POST)).toBe(true);
  });

  it("does not forward the id-less templates as routes of their own", () => {
    expect(matchWrite("review/decide", ALLOWED_POST)).toBe(false);
    expect(matchWrite("review/deep-review", ALLOWED_POST)).toBe(false);
  });

  it("refuses a destructive route and a traversal", () => {
    expect(matchWrite("orchestrator/reset", ALLOWED_POST)).toBe(false);
    expect(matchWrite("review/../../orchestrator/reset/decide", ALLOWED_POST)).toBe(false);
    expect(matchWrite("review/CASE-1/document", ALLOWED_POST)).toBe(false);
  });

  it("forwards the sanctions-news scan the Governance screen offers", () => {
    expect(matchWrite("governance/tavily-scan", ALLOWED_POST)).toBe(true);
  });
});

describe("the lists the Access Control screen shows", () => {
  it("include every read the proxy forwards, id routes too", () => {
    const shown = describedReads();
    // The hand-copied list this replaced showed 14 of 17.
    expect(shown).toHaveLength(ALLOWED_GET.size + 3);
    expect(shown).toContain("orchestrator/case/<id>");
    expect(shown).toContain("review/<id>/document");
  });

  it("spell the review writes with their id segment", () => {
    const shown = describedWrites().map((w) => `${w.method} ${w.path}`);
    expect(shown).toContain("POST review/<id>/decide");
    expect(shown).toContain("PUT governance/prefilter-rules");
    expect(shown).not.toContain("POST review/decide");
  });
});
