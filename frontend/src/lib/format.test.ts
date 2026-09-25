import { describe, expect, it } from "vitest";

import {
  NO_VALUE,
  actionLabel,
  auditStatusLabel,
  caseStateLabel,
  complianceStatusLabel,
  formatClock,
  formatLatency,
  formatRelative,
  formatTokens,
  formatUsd,
  humaniseAgent,
  humaniseCode,
  lowerFirst,
  severityLabel,
  shortModelName,
} from "@/lib/format";

/**
 * The property this file exists for: NOTHING in format.ts throws on absent input.
 *
 * `formatUsd` was typed `(value: number)`, received `undefined` from a step that had no
 * `cost_usd`, and `undefined.toLocaleString()` threw during render. There is no React
 * error boundary in this app, so the whole tree unmounted -- a white page where a dash
 * belonged. The guard was then added to that one function while three others sat
 * immediately below with the same bug and five label helpers delegating to them.
 *
 * The table-driven test below is deliberate. Testing the helpers one at a time is how
 * the gap happened the first time: each new helper needs someone to remember to test the
 * absent case. Here a new export shows up as a missing entry.
 */

// Every exported helper that takes a single value and returns a display string.
const HELPERS: Array<[string, (v: never) => string]> = [
  ["formatUsd", formatUsd as (v: never) => string],
  ["formatTokens", formatTokens as (v: never) => string],
  ["formatLatency", formatLatency as (v: never) => string],
  ["formatRelative", formatRelative as (v: never) => string],
  ["formatClock", formatClock as (v: never) => string],
  ["shortModelName", shortModelName as (v: never) => string],
  ["humaniseAgent", humaniseAgent as (v: never) => string],
  ["humaniseCode", humaniseCode as (v: never) => string],
  ["caseStateLabel", caseStateLabel as (v: never) => string],
  ["actionLabel", actionLabel as (v: never) => string],
  ["severityLabel", severityLabel as (v: never) => string],
  ["auditStatusLabel", auditStatusLabel as (v: never) => string],
  ["complianceStatusLabel", complianceStatusLabel as (v: never) => string],
  ["lowerFirst", lowerFirst as (v: never) => string],
];

describe("no format helper throws on absent input", () => {
  for (const [name, fn] of HELPERS) {
    it(`${name}(undefined) returns a string`, () => {
      // The assertion is that this line does not throw. A helper that throws here
      // unmounts the page it was rendering.
      const out = fn(undefined as never);
      expect(typeof out).toBe("string");
    });

    it(`${name}(null) returns a string`, () => {
      const out = fn(null as never);
      expect(typeof out).toBe("string");
    });
  }

  it("covers every helper exported from format.ts", async () => {
    // Guards the guard: if someone adds a helper and forgets to list it above, the
    // table passes vacuously for the new function. Comparing against the module's own
    // exports makes that show up as a failure here rather than as a white page later.
    const mod = await import("@/lib/format");
    const exportedFns = Object.entries(mod)
      .filter(([, v]) => typeof v === "function")
      .map(([k]) => k);
    const tested = HELPERS.map(([name]) => name);
    const untested = exportedFns.filter((name) => !tested.includes(name));
    expect(untested).toEqual([]);
  });
});

describe("formatUsd", () => {
  it("renders a measured zero as $0, distinctly from absent", () => {
    // These two must not collapse into the same string. A compliance console that shows
    // "$0" when the billing API is down is asserting a number nobody measured.
    expect(formatUsd(0)).toBe("$0");
    expect(formatUsd(undefined)).toBe(NO_VALUE);
    expect(formatUsd(0)).not.toBe(formatUsd(undefined));
  });

  it("keeps five decimals for fractions of a cent", () => {
    // Two decimals would render every audit as $0.00 and make the column useless.
    expect(formatUsd(0.00236)).toBe("$0.00236");
  });

  it("returns the sentinel for NaN and Infinity", () => {
    expect(formatUsd(NaN)).toBe(NO_VALUE);
    expect(formatUsd(Infinity)).toBe(NO_VALUE);
  });
});

describe("formatTokens", () => {
  it("does not render the string 'undefined'", () => {
    // What it used to do. Worse than a dash: it reads as a rendering bug rather than as
    // missing data, and it appeared in the Agent Console as "undefined in / undefined out".
    expect(formatTokens(undefined)).toBe(NO_VALUE);
    expect(formatTokens(undefined)).not.toContain("undefined");
  });

  it("abbreviates thousands and millions", () => {
    expect(formatTokens(35_076)).toBe("35.1k");
    expect(formatTokens(2_400_000)).toBe("2.40M");
    expect(formatTokens(512)).toBe("512");
  });

  it("renders a measured zero as 0, not as absent", () => {
    expect(formatTokens(0)).toBe("0");
  });
});

describe("formatLatency", () => {
  it("does not render 'NaN s' for an absent latency", () => {
    // The original guard was `ms === null`, so undefined fell through to arithmetic.
    expect(formatLatency(undefined)).toBe(NO_VALUE);
    expect(formatLatency(null)).toBe(NO_VALUE);
    expect(formatLatency(undefined)).not.toContain("NaN");
  });

  it("switches to seconds above a thousand milliseconds", () => {
    expect(formatLatency(640)).toBe("640 ms");
    expect(formatLatency(13_690)).toBe("13.69 s");
  });
});

describe("humaniseCode", () => {
  it("preserves domain acronyms", () => {
    // "Hs code malformed" reads as a typo in a product whose claim is care with customs
    // vocabulary.
    expect(humaniseCode("HS_CODE_MALFORMED")).toBe("HS code malformed");
    expect(humaniseCode("OFAC_MATCH")).toBe("OFAC match");
    expect(humaniseCode("DRAFT_SAR")).toBe("Draft SAR");
  });

  it("sentence-cases an ordinary code", () => {
    expect(humaniseCode("SANCTIONS_MATCH")).toBe("Sanctions match");
  });
});

describe("label helpers fall through rather than vanishing", () => {
  it("caseStateLabel renders an unknown state readably", () => {
    expect(caseStateLabel("AUTO_CLEARED")).toBe("Cleared automatically");
    // A state this file has never heard of must degrade to readable text, not disappear.
    expect(caseStateLabel("SOME_NEW_STATE")).toBe("Some new state");
  });

  it("actionLabel renders an unknown action readably", () => {
    expect(actionLabel("draft_sar")).toBe("Draft SAR");
    expect(actionLabel("some_new_action")).toBe("Some new action");
  });

  it("auditStatusLabel renders an unknown status readably", () => {
    expect(auditStatusLabel("denied")).toBe("Denied");
    expect(auditStatusLabel("partially_done")).toBe("Partially done");
  });
});

describe("shortModelName", () => {
  it("shortens the Nemotron ids", () => {
    expect(shortModelName("nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B")).toBe("Nemotron 3 Nano");
    expect(shortModelName("nvidia/nemotron-3-super-120b-a12b")).toBe("Nemotron 3 Super");
  });

  it("returns the tail of an unrecognised id rather than throwing", () => {
    expect(shortModelName("some-vendor/some-model")).toBe("some-model");
  });
});

describe("lowerFirst", () => {
  it("lowercases a sentence-case label for use mid-sentence", () => {
    expect(lowerFirst("Released by a reviewer")).toBe("released by a reviewer");
  });

  it("leaves an acronym-initial label alone", () => {
    // "HS code malformed" must not become "hS code malformed".
    expect(lowerFirst("HS code malformed")).toBe("HS code malformed");
  });
});

describe("date helpers", () => {
  it("return the sentinel for absent input", () => {
    expect(formatRelative(undefined)).toBe(NO_VALUE);
    expect(formatClock(undefined)).toBe(NO_VALUE);
  });

  it("echo an unparseable string rather than rendering 'Invalid Date'", () => {
    expect(formatRelative("not-a-date")).toBe("not-a-date");
    expect(formatClock("not-a-date")).toBe("not-a-date");
  });

  it("formats a real timestamp", () => {
    expect(formatClock("2026-01-01T00:00:00Z")).toBe("2026-01-01 00:00:00Z");
  });
});
