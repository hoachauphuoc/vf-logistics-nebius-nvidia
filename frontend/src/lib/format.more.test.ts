import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import {
  NO_VALUE,
  actionLabel,
  auditStatusLabel,
  caseStateLabel,
  complianceStatusLabel,
  formatClock,
  formatInterval,
  formatLatency,
  formatRelative,
  formatTokens,
  formatUsd,
  humaniseAgent,
  humaniseCode,
  lowerFirst,
  severityLabel,
  shortModelName,
  AUDIT_ACTION_LABEL,
  AUDIT_STATUS_LABEL,
  CASE_STATE_LABEL,
  COMPLIANCE_STATUS_LABEL,
  SEVERITY_LABEL,
} from "@/lib/format";

describe("formatUsd: edge cases", () => {
  it("handles negative values", () => {
    expect(formatUsd(-10.5)).toBe("$-10.50000");
    expect(formatUsd(-0.00236)).toBe("$-0.00236");
  });

  it("renders very large numbers with thousands separators", () => {
    expect(formatUsd(1000)).toBe("$1,000.00");
    expect(formatUsd(1_000_000)).toBe("$1,000,000.00");
  });

  it("rounds correctly for values between 0.01 and 1", () => {
    expect(formatUsd(0.5)).toBe("$0.5000");
    expect(formatUsd(0.0099)).toBe("$0.00990");
  });
});

describe("formatTokens: edge cases", () => {
  it("handles negative numbers", () => {
    expect(formatTokens(-1000)).toBe("-1000");
    expect(formatTokens(-512)).toBe("-512");
  });

  it("handles boundary values", () => {
    expect(formatTokens(999)).toBe("999");
    expect(formatTokens(1000)).toBe("1.0k");
    expect(formatTokens(999_999)).toBe("1000.0k");
    expect(formatTokens(1_000_000)).toBe("1.00M");
  });

  it("returns the sentinel for NaN and Infinity", () => {
    expect(formatTokens(NaN)).toBe(NO_VALUE);
    expect(formatTokens(Infinity)).toBe(NO_VALUE);
    expect(formatTokens(-Infinity)).toBe(NO_VALUE);
  });
});

describe("formatLatency: edge cases", () => {
  it("handles the 1000ms boundary", () => {
    expect(formatLatency(999)).toBe("999 ms");
    expect(formatLatency(1000)).toBe("1.00 s");
    expect(formatLatency(1001)).toBe("1.00 s");
  });

  it("handles very large latencies", () => {
    expect(formatLatency(3_600_000)).toBe("3600.00 s");
  });

  it("returns the sentinel for Infinity", () => {
    expect(formatLatency(Infinity)).toBe(NO_VALUE);
    expect(formatLatency(-Infinity)).toBe(NO_VALUE);
  });
});

describe("formatInterval: edge cases", () => {
  it("handles intervals with floating point noise at boundaries", () => {
    expect(formatInterval({ low: 0, high: 0 })).toBe("0–0");
    expect(formatInterval({ low: 1, high: 1 })).toBe("100–100");
  });

  it("returns the sentinel when high is not finite", () => {
    expect(formatInterval({ low: 0.5, high: NaN })).toBe(NO_VALUE);
    expect(formatInterval({ low: 0.5, high: Infinity })).toBe(NO_VALUE);
  });

  it("returns the sentinel when low is not finite", () => {
    expect(formatInterval({ low: -Infinity, high: 0.5 })).toBe(NO_VALUE);
    expect(formatInterval({ low: NaN, high: 0.5 })).toBe(NO_VALUE);
  });
});

describe("formatRelative: time ranges", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: false });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows seconds for recent events", () => {
    vi.setSystemTime(new Date("2026-10-19T12:00:00Z").getTime());
    expect(formatRelative("2026-10-19T11:59:30Z")).toBe("30s ago");
    expect(formatRelative("2026-10-19T11:59:59Z")).toBe("1s ago");
  });

  it("shows minutes for events up to an hour ago", () => {
    vi.setSystemTime(new Date("2026-10-19T12:00:00Z").getTime());
    expect(formatRelative("2026-10-19T11:45:00Z")).toBe("15m ago");
    expect(formatRelative("2026-10-19T11:01:00Z")).toBe("59m ago");
  });

  it("shows hours for events up to a day ago", () => {
    vi.setSystemTime(new Date("2026-10-19T12:00:00Z").getTime());
    expect(formatRelative("2026-10-19T08:00:00Z")).toBe("4h ago");
    expect(formatRelative("2026-10-19T00:00:00Z")).toBe("12h ago");
  });

  it("shows days for older events", () => {
    vi.setSystemTime(new Date("2026-10-19T12:00:00Z").getTime());
    expect(formatRelative("2026-10-18T12:00:00Z")).toBe("1d ago");
    expect(formatRelative("2026-10-12T12:00:00Z")).toBe("7d ago");
  });

  it("rounds fractional seconds and minutes", () => {
    vi.setSystemTime(new Date("2026-10-19T12:00:30Z").getTime());
    expect(formatRelative("2026-10-19T12:00:00Z")).toBe("30s ago");
  });
});

describe("formatClock: formatting", () => {
  it("formats a clock time with timezone Z", () => {
    expect(formatClock("2026-10-19T15:30:45.123Z")).toBe("2026-10-19 15:30:45Z");
  });

  it("formats a clock time without milliseconds", () => {
    expect(formatClock("2026-01-15T08:05:00Z")).toBe("2026-01-15 08:05:00Z");
  });

  it("handles various input formats and normalizes them", () => {
    expect(formatClock("2026-10-19T23:59:59Z")).toBe("2026-10-19 23:59:59Z");
  });
});

describe("shortModelName: edge cases", () => {
  it("handles model ids without a slash", () => {
    expect(shortModelName("just-a-model")).toBe("just-a-model");
  });

  it("handles various Nemotron variants", () => {
    expect(shortModelName("nvidia/NVIDIA-Nemotron-3-Ultra-106B-A22B")).toBe("Nemotron 3 Ultra");
    expect(shortModelName("test/nemotron-3-nano-30b")).toBe("Nemotron 3 Nano");
  });

  it("returns the tail when there is no match", () => {
    expect(shortModelName("vendor/model-name-here")).toBe("model-name-here");
  });

  it("handles vision model variant", () => {
    expect(shortModelName("openbmb/MiniCPM-V-3_2")).toBe("MiniCPM-V 3.2");
    expect(shortModelName("openbmb/MiniCPM-V-2_0")).toBe("MiniCPM-V 2.0");
  });
});

describe("humaniseCode: transformation edge cases", () => {
  it("preserves multiple acronyms in sequence", () => {
    expect(humaniseCode("HS_EU_MATCH")).toBe("HS EU match");
    expect(humaniseCode("US_OFAC_BLOCKED")).toBe("US OFAC blocked");
  });

  it("preserves acronyms at the end", () => {
    expect(humaniseCode("CODE_HS")).toBe("Code HS");
    expect(humaniseCode("BLOCKED_BY_EU")).toBe("Blocked by EU");
  });

  it("capitalizes only the first word", () => {
    expect(humaniseCode("RULE_ONE_TWO")).toBe("Rule one two");
  });
});

describe("humaniseAgent: basic transformation", () => {
  it("uppercases before delegating to humaniseCode", () => {
    expect(humaniseAgent("fraud_detection")).toBe("Fraud detection");
    expect(humaniseAgent("hs_classifier")).toBe("HS classifier");
  });

  it("handles mixed case input", () => {
    expect(humaniseAgent("FraudDetection")).toBe("Frauddetection");
  });
});

describe("lowerFirst: edge cases", () => {
  it("handles single character strings as acronyms", () => {
    expect(lowerFirst("A")).toBe("A");
    expect(lowerFirst("H")).toBe("H");
  });

  it("returns null/undefined as NO_VALUE", () => {
    expect(lowerFirst(null)).toBe(NO_VALUE);
    expect(lowerFirst(undefined)).toBe(NO_VALUE);
  });

  it("returns empty string as empty string", () => {
    expect(lowerFirst("")).toBe("");
  });

  it("preserves two-letter acronyms followed by space", () => {
    expect(lowerFirst("EU code malformed")).toBe("EU code malformed");
    expect(lowerFirst("AI model failed")).toBe("AI model failed");
  });

  it("lowercases when the second character is not uppercase", () => {
    expect(lowerFirst("Cleared automatically")).toBe("cleared automatically");
  });
});

describe("caseStateLabel: all states and unknown fallback", () => {
  it("renders all known states from CASE_STATE_LABEL", () => {
    Object.entries(CASE_STATE_LABEL).forEach(([state, label]) => {
      expect(caseStateLabel(state)).toBe(label);
    });
  });

  it("falls back to humaniseCode for unknown states", () => {
    expect(caseStateLabel("CUSTOM_STATE")).toBe("Custom state");
    expect(caseStateLabel("FUTURE_STATE_NAME")).toBe("Future state name");
  });
});

describe("actionLabel: all actions and unknown fallback", () => {
  it("renders all known actions from AUDIT_ACTION_LABEL", () => {
    Object.entries(AUDIT_ACTION_LABEL).forEach(([action, label]) => {
      expect(actionLabel(action)).toBe(label);
    });
  });

  it("falls back to humaniseAgent for unknown actions", () => {
    expect(actionLabel("new_custom_action")).toBe("New custom action");
  });

  it("handles snake_case unknown actions", () => {
    expect(actionLabel("future_action")).toBe("Future action");
  });
});

describe("severityLabel: all severities and unknown fallback", () => {
  it("renders all known severities from SEVERITY_LABEL", () => {
    Object.entries(SEVERITY_LABEL).forEach(([severity, label]) => {
      expect(severityLabel(severity)).toBe(label);
    });
  });

  it("falls back to humaniseCode for unknown severities", () => {
    expect(severityLabel("CUSTOM_SEVERITY")).toBe("Custom severity");
  });

  it("renders CRITICAL, HIGH, MEDIUM, LOW, INFO correctly", () => {
    expect(severityLabel("CRITICAL")).toBe("Critical");
    expect(severityLabel("HIGH")).toBe("High");
    expect(severityLabel("MEDIUM")).toBe("Medium");
    expect(severityLabel("LOW")).toBe("Low");
    expect(severityLabel("INFO")).toBe("Informational");
  });
});

describe("auditStatusLabel: all statuses and unknown fallback", () => {
  it("renders all known statuses from AUDIT_STATUS_LABEL", () => {
    Object.entries(AUDIT_STATUS_LABEL).forEach(([status, label]) => {
      expect(auditStatusLabel(status)).toBe(label);
    });
  });

  it("falls back to humaniseAgent for unknown statuses", () => {
    expect(auditStatusLabel("partially_done")).toBe("Partially done");
    expect(auditStatusLabel("custom_status")).toBe("Custom status");
  });
});

describe("complianceStatusLabel: all statuses and unknown fallback", () => {
  it("renders all known statuses from COMPLIANCE_STATUS_LABEL", () => {
    Object.entries(COMPLIANCE_STATUS_LABEL).forEach(([status, label]) => {
      expect(complianceStatusLabel(status)).toBe(label);
    });
  });

  it("falls back to humaniseCode for unknown statuses", () => {
    expect(complianceStatusLabel("PENDING_REVIEW")).toBe("Pending review");
  });

  it("renders CLEARED, REVIEW_REQUIRED, BLOCKED correctly", () => {
    expect(complianceStatusLabel("CLEARED")).toBe("Cleared");
    expect(complianceStatusLabel("REVIEW_REQUIRED")).toBe("Review required");
    expect(complianceStatusLabel("BLOCKED")).toBe("Blocked");
  });
});

describe("NO_VALUE constant", () => {
  it("is an em dash", () => {
    expect(NO_VALUE).toBe("—");
  });

  it("is used consistently across all helpers", () => {
    expect(formatUsd(null)).toBe(NO_VALUE);
    expect(shortModelName(undefined)).toBe(NO_VALUE);
    expect(caseStateLabel(null)).toBe(NO_VALUE);
  });
});
