import { describe, expect, it } from "vitest";

import {
  AWAITING_STATES,
  BOARD_COLUMNS,
  COLUMN_PAGE_SIZE,
  POLL_BUSY_MS,
  POLL_IDLE_MS,
  SORT_LABELS,
  STATES_IN_COLUMN,
  bucketCases,
  casePriority,
  columnFor,
  columnTotal,
  formatDuration,
  hasWorkInFlight,
  isTerminal,
  matchesPriority,
  matchesSearch,
  slaDeadline,
  slaStatus,
  sortCases,
} from "@/lib/pipeline";
import type { Case } from "@/lib/types";

const HOUR = 3_600_000;
const T0 = Date.parse("2026-01-01T00:00:00Z");

function iso(ms: number): string {
  return new Date(ms).toISOString();
}

function makeCase(overrides: Partial<Case> = {}): Case {
  return { case_id: "c-1", state: "INGESTED", ...overrides };
}

function cardsIn(
  buckets: { column: { state: string }; cases: Case[] }[],
  state: string,
): string[] {
  return buckets.find((b) => b.column.state === state)?.cases.map((c) => c.case_id) ?? [];
}

describe("casePriority", () => {
  it("is CRITICAL at a risk score of 90 and above", () => {
    expect(casePriority(makeCase({ risk_score: 90 }))).toBe("CRITICAL");
    expect(casePriority(makeCase({ risk_score: 89 }))).toBe("HIGH");
  });

  it("is CRITICAL for a BLOCKED compliance status whatever the score", () => {
    // The status is upper-cased before the comparison, so case does not matter.
    expect(casePriority(makeCase({ compliance_status: "blocked", risk_score: 5 }))).toBe(
      "CRITICAL",
    );
  });

  it("is HIGH at 70 or above, for REVIEW_REQUIRED, or for an ESCALATED state", () => {
    expect(casePriority(makeCase({ risk_score: 70 }))).toBe("HIGH");
    expect(casePriority(makeCase({ risk_score: 69 }))).toBe("MEDIUM");
    expect(casePriority(makeCase({ compliance_status: "review_required", risk_score: 10 }))).toBe(
      "HIGH",
    );
    expect(casePriority(makeCase({ state: "ESCALATED", risk_score: 10 }))).toBe("HIGH");
  });

  it("treats an unscored case as MEDIUM, not LOW", () => {
    // Unknown is not the same as low: an ungraded case must not sink to the bottom.
    expect(casePriority(makeCase({ risk_score: null }))).toBe("MEDIUM");
    expect(casePriority(makeCase())).toBe("MEDIUM");
  });

  it("is MEDIUM from 40 to 69 and LOW below 40", () => {
    expect(casePriority(makeCase({ risk_score: 40 }))).toBe("MEDIUM");
    expect(casePriority(makeCase({ risk_score: 39 }))).toBe("LOW");
  });
});

describe("slaDeadline", () => {
  it("is null when the case has no created_at or an unparseable one", () => {
    expect(slaDeadline(makeCase())).toBeNull();
    expect(slaDeadline(makeCase({ created_at: "not-a-date" }))).toBeNull();
  });

  it("adds the priority's SLA hours to created_at", () => {
    // CRITICAL allows 2 hours.
    const critical = slaDeadline(makeCase({ created_at: iso(T0), risk_score: 95 }));
    expect(critical?.getTime()).toBe(T0 + 2 * HOUR);
    // An unscored case is MEDIUM, which allows 24 hours.
    const medium = slaDeadline(makeCase({ created_at: iso(T0) }));
    expect(medium?.getTime()).toBe(T0 + 24 * HOUR);
  });
});

describe("slaStatus", () => {
  it("reports a terminal case as resolved", () => {
    expect(slaStatus(makeCase({ state: "AUTO_CLEARED", created_at: iso(T0) }), T0)).toEqual({
      text: "Resolved",
      tone: "done",
    });
  });

  it("has no SLA text for a case without a usable created_at", () => {
    expect(slaStatus(makeCase(), T0)).toEqual({ text: "", tone: "none" });
  });

  it("is ok with the time left when more than an hour remains", () => {
    const c = makeCase({ created_at: iso(T0), risk_score: 95 });
    expect(slaStatus(c, T0)).toEqual({ text: "2h 0m left", tone: "ok" });
    // Exactly one hour left is not yet urgent.
    expect(slaStatus(c, T0 + HOUR)).toEqual({ text: "1h 0m left", tone: "ok" });
  });

  it("is urgent when less than an hour remains", () => {
    const c = makeCase({ created_at: iso(T0), risk_score: 95 });
    expect(slaStatus(c, T0 + 1.5 * HOUR)).toEqual({ text: "30m left", tone: "urgent" });
  });

  it("is overdue, with how long ago the deadline passed, once the deadline is gone", () => {
    const c = makeCase({ created_at: iso(T0), risk_score: 95 });
    expect(slaStatus(c, T0 + 3 * HOUR)).toEqual({ text: "Overdue 1h 0m", tone: "overdue" });
  });
});

describe("formatDuration", () => {
  it("renders minutes under an hour", () => {
    expect(formatDuration(0)).toBe("0m");
    expect(formatDuration(25 * 60_000)).toBe("25m");
  });

  it("renders hours and minutes under a day", () => {
    expect(formatDuration(90 * 60_000)).toBe("1h 30m");
  });

  it("renders days and hours from 24 hours up", () => {
    expect(formatDuration(49 * HOUR)).toBe("2d 1h");
  });
});

describe("matchesSearch", () => {
  it("matches everything for an empty or blank query", () => {
    expect(matchesSearch(makeCase(), "")).toBe(true);
    expect(matchesSearch(makeCase(), "   ")).toBe(true);
  });

  it("ignores case and surrounding whitespace", () => {
    expect(matchesSearch(makeCase({ case_id: "VF-ABC123" }), "  abc123 ")).toBe(true);
  });

  it("finds a shipper company in the nested shipment", () => {
    const c = makeCase({ shipment: { shipper_company: "Acme Exports" } as never });
    expect(matchesSearch(c, "exports")).toBe(true);
    expect(matchesSearch(c, "zzz")).toBe(false);
  });

  it("finds an HS code in the nested shipment", () => {
    const c = makeCase({ shipment: { hs_code: "8471.30" } as never });
    expect(matchesSearch(c, "8471")).toBe(true);
  });

  it("finds a state and a compliance status", () => {
    const c = makeCase({ state: "HELD_FOR_REVIEW", compliance_status: "REVIEW_REQUIRED" });
    expect(matchesSearch(c, "held")).toBe(true);
    expect(matchesSearch(c, "review_req")).toBe(true);
  });

  it("finds a shipment id even when there is no shipment document", () => {
    // A paged /cases row has no shipment at all, so the nested fields must be optional.
    const c = makeCase({ shipment_id: "SHP-9" });
    expect(matchesSearch(c, "shp-9")).toBe(true);
    expect(matchesSearch(c, "acme")).toBe(false);
  });

  it("does not match a null field by its text", () => {
    const c = makeCase({ shipment: { origin: null } as never });
    expect(matchesSearch(c, "null")).toBe(false);
  });
});

describe("matchesPriority", () => {
  it("accepts every case when no filter is set", () => {
    expect(matchesPriority(makeCase({ risk_score: 5 }), "")).toBe(true);
  });

  it("CRITICAL keeps only critical cases", () => {
    expect(matchesPriority(makeCase({ risk_score: 95 }), "CRITICAL")).toBe(true);
    expect(matchesPriority(makeCase({ risk_score: 75 }), "CRITICAL")).toBe(false);
  });

  it("HIGH is a floor: it keeps critical and high cases", () => {
    expect(matchesPriority(makeCase({ risk_score: 95 }), "HIGH")).toBe(true);
    expect(matchesPriority(makeCase({ risk_score: 75 }), "HIGH")).toBe(true);
    expect(matchesPriority(makeCase({ risk_score: 50 }), "HIGH")).toBe(false);
  });

  it("MEDIUM keeps everything except low cases", () => {
    expect(matchesPriority(makeCase({ risk_score: 50 }), "MEDIUM")).toBe(true);
    expect(matchesPriority(makeCase({ risk_score: 75 }), "MEDIUM")).toBe(true);
    expect(matchesPriority(makeCase({ risk_score: 10 }), "MEDIUM")).toBe(false);
  });
});

describe("sortCases", () => {
  const early = makeCase({ case_id: "early", created_at: iso(T0), risk_score: 10 });
  const middle = makeCase({ case_id: "middle", created_at: iso(T0 + HOUR), risk_score: null });
  const late = makeCase({ case_id: "late", created_at: iso(T0 + 2 * HOUR), risk_score: 90 });
  const ids = (cases: Case[]) => cases.map((c) => c.case_id);

  it("sorts newest first and oldest first by created_at", () => {
    expect(ids(sortCases([early, late, middle], "newest"))).toEqual(["late", "middle", "early"]);
    expect(ids(sortCases([early, late, middle], "oldest"))).toEqual(["early", "middle", "late"]);
  });

  it("sorts by risk, highest first, with unscored cases last", () => {
    expect(ids(sortCases([early, middle, late], "risk-high"))).toEqual([
      "late",
      "early",
      "middle",
    ]);
  });

  it("sorts by risk, lowest first, among scored cases", () => {
    const scored = [early, late];
    expect(ids(sortCases(scored, "risk-low"))).toEqual(["early", "late"]);
  });

  it("sorts CRITICAL before MEDIUM before LOW by priority", () => {
    const low = makeCase({ case_id: "low", risk_score: 10 });
    const critical = makeCase({ case_id: "critical", risk_score: 95 });
    const medium = makeCase({ case_id: "medium", risk_score: null });
    expect(ids(sortCases([low, medium, critical], "priority"))).toEqual([
      "critical",
      "medium",
      "low",
    ]);
  });

  it("sorts by SLA deadline, earliest first, with no deadline last", () => {
    // due (CRITICAL, 2h) is due at T0 + 2h, later (LOW, 72h) at T0 + 73h.
    const noDeadline = makeCase({ case_id: "none", risk_score: 95 });
    const criticalEarly = makeCase({ case_id: "due", created_at: iso(T0), risk_score: 95 });
    const lowLater = makeCase({ case_id: "later", created_at: iso(T0 + HOUR), risk_score: 10 });
    expect(ids(sortCases([noDeadline, lowLater, criticalEarly], "sla"))).toEqual([
      "due",
      "later",
      "none",
    ]);
  });

  it("falls back to newest first for an unknown key", () => {
    expect(ids(sortCases([early, late, middle], "bogus" as never))).toEqual([
      "late",
      "middle",
      "early",
    ]);
  });

  it("returns a new array and leaves the input order alone", () => {
    const input = [early, late, middle];
    const sorted = sortCases(input, "oldest");
    expect(sorted).not.toBe(input);
    expect(ids(input)).toEqual(["early", "late", "middle"]);
  });
});

describe("columnFor", () => {
  it("folds held, escalated and dead-lettered cases into the awaiting column", () => {
    expect(columnFor("HELD_FOR_REVIEW")).toBe("PENDING_HUMAN");
    expect(columnFor("ESCALATED")).toBe("PENDING_HUMAN");
    expect(columnFor("DEAD_LETTER")).toBe("PENDING_HUMAN");
  });

  it("folds a released case into the cleared column", () => {
    expect(columnFor("RELEASED_BY_HUMAN")).toBe("AUTO_CLEARED");
  });

  it("keeps a blocked case in its own column", () => {
    expect(columnFor("BLOCKED_BY_HUMAN")).toBe("BLOCKED_BY_HUMAN");
  });

  it("returns a state no rule folds unchanged", () => {
    expect(columnFor("AWAITING_EVIDENCE")).toBe("AWAITING_EVIDENCE");
  });
});

describe("columnTotal", () => {
  it("is zero when the counts are absent", () => {
    expect(columnTotal({}, "PENDING_HUMAN")).toBe(0);
  });

  it("adds every raw state folded into the column", () => {
    const counts = { PENDING_HUMAN: 2, HELD_FOR_REVIEW: 1, DEAD_LETTER: 1, ESCALATED: 3 };
    expect(columnTotal(counts, "PENDING_HUMAN")).toBe(7);
  });

  it("reads the count of a column that folds nothing in", () => {
    expect(columnTotal({ AWAITING_EVIDENCE: 4 }, "AWAITING_EVIDENCE")).toBe(4);
  });
});

describe("bucketCases", () => {
  const queued = makeCase({ case_id: "c-queued", state: "INGESTED", risk_score: 10, created_at: iso(T0) });
  const held = makeCase({ case_id: "c-held", state: "HELD_FOR_REVIEW", risk_score: 50, created_at: iso(T0 + HOUR) });
  const dead = makeCase({ case_id: "c-dead", state: "DEAD_LETTER", risk_score: 20, created_at: iso(T0 + 2 * HOUR) });
  const cleared = makeCase({ case_id: "c-cleared", state: "RELEASED_BY_HUMAN", risk_score: 5, created_at: iso(T0) });
  const blocked = makeCase({
    case_id: "c-blocked",
    state: "BLOCKED_BY_HUMAN",
    compliance_status: "BLOCKED",
    risk_score: 30,
    created_at: iso(T0),
  });
  const orphan = makeCase({ case_id: "c-orphan", state: "AWAITING_EVIDENCE", created_at: iso(T0) });
  const cases = [queued, held, dead, cleared, blocked, orphan];
  const options = { search: "", priority: "" as const, sort: "newest" as const };

  it("draws the six board columns in workflow order", () => {
    const { buckets } = bucketCases(cases, {}, options);
    expect(buckets.map((b) => b.column.state)).toEqual(BOARD_COLUMNS.map((c) => c.state));
  });

  it("puts folded states in their column, newest first", () => {
    const { buckets } = bucketCases(cases, {}, options);
    expect(cardsIn(buckets, "PENDING_HUMAN")).toEqual(["c-dead", "c-held"]);
    expect(cardsIn(buckets, "AUTO_CLEARED")).toEqual(["c-cleared"]);
    expect(cardsIn(buckets, "BLOCKED_BY_HUMAN")).toEqual(["c-blocked"]);
    expect(cardsIn(buckets, "INGESTED")).toEqual(["c-queued"]);
  });

  it("drops a case no column claims but still counts it as matched", () => {
    // The header and the cards disagree on purpose here, so the gap is visible.
    const { buckets, matched } = bucketCases(cases, {}, options);
    const shown = buckets.flatMap((b) => b.cases.map((c) => c.case_id));
    expect(shown).not.toContain("c-orphan");
    expect(matched).toBe(6);
  });

  it("filters by search text before bucketing", () => {
    const { buckets, matched } = bucketCases(cases, {}, { ...options, search: "dead" });
    expect(matched).toBe(1);
    expect(cardsIn(buckets, "PENDING_HUMAN")).toEqual(["c-dead"]);
    expect(cardsIn(buckets, "INGESTED")).toEqual([]);
  });

  it("filters by priority before bucketing", () => {
    const { buckets, matched } = bucketCases(cases, {}, { ...options, priority: "CRITICAL" });
    expect(matched).toBe(1);
    expect(cardsIn(buckets, "BLOCKED_BY_HUMAN")).toEqual(["c-blocked"]);
  });

  it("sorts the cards inside a column with the chosen key", () => {
    const { buckets } = bucketCases(cases, {}, { ...options, sort: "risk-high" });
    // held is risk 50 and dead is risk 20.
    expect(cardsIn(buckets, "PENDING_HUMAN")).toEqual(["c-held", "c-dead"]);
  });

  it("gives each column the exact total from the counts", () => {
    const counts = { PENDING_HUMAN: 2, HELD_FOR_REVIEW: 1, DEAD_LETTER: 1, RELEASED_BY_HUMAN: 3, AUTO_CLEARED: 1 };
    const { buckets } = bucketCases(cases, counts, options);
    expect(buckets.find((b) => b.column.state === "PENDING_HUMAN")?.total).toBe(4);
    expect(buckets.find((b) => b.column.state === "AUTO_CLEARED")?.total).toBe(4);
  });
});

describe("hasWorkInFlight", () => {
  it("is false when the aggregate is absent or zero", () => {
    expect(hasWorkInFlight(undefined)).toBe(false);
    expect(hasWorkInFlight(0)).toBe(false);
  });

  it("is true when any case is in flight", () => {
    expect(hasWorkInFlight(3)).toBe(true);
  });
});

describe("isTerminal", () => {
  it("treats a case that has been decided as terminal", () => {
    expect(isTerminal("AUTO_CLEARED")).toBe(true);
    expect(isTerminal("BLOCKED_BY_HUMAN")).toBe(true);
  });

  it("treats a case still moving through the workflow as not terminal", () => {
    expect(isTerminal("INGESTED")).toBe(false);
    expect(isTerminal("INVESTIGATED")).toBe(false);
  });
});

describe("board constants", () => {
  it("lists the states a reviewer can decide, without DEAD_LETTER", () => {
    // The decision route refuses DEAD_LETTER, so the board must not offer it.
    expect([...AWAITING_STATES].sort()).toEqual(["ESCALATED", "HELD_FOR_REVIEW", "PENDING_HUMAN"]);
    expect(AWAITING_STATES.has("DEAD_LETTER")).toBe(false);
  });

  it("lists every raw state a column folds in, including the column's own state", () => {
    expect(STATES_IN_COLUMN.PENDING_HUMAN).toEqual(
      expect.arrayContaining(["PENDING_HUMAN", "HELD_FOR_REVIEW", "ESCALATED", "DEAD_LETTER"]),
    );
    expect(STATES_IN_COLUMN.AUTO_CLEARED).toEqual(
      expect.arrayContaining(["AUTO_CLEARED", "RELEASED_BY_HUMAN"]),
    );
  });

  it("pages eight cards per column", () => {
    expect(COLUMN_PAGE_SIZE).toBe(8);
  });

  it("polls faster while work is in flight than when idle", () => {
    expect(POLL_BUSY_MS).toBeLessThan(POLL_IDLE_MS);
  });

  it("labels every sort key", () => {
    expect(SORT_LABELS["risk-high"]).toBe("Highest risk");
    expect(Object.keys(SORT_LABELS)).toHaveLength(6);
  });
});
