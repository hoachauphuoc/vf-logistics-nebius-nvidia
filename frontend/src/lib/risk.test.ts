import { describe, expect, it } from "vitest";

import {
  RISK_CLASS,
  derivePresentation,
  evidenceFindings,
  isUnverifiedCheck,
  screeningFindings,
  severityState,
  sortFindings,
  unverifiedChecks,
} from "@/lib/risk";
import type { AuditFinding, ComplianceAuditResponse } from "@/lib/types";

describe("isUnverifiedCheck", () => {
  it("matches codes ending with _UNAVAILABLE", () => {
    expect(isUnverifiedCheck("HS_DESCRIPTION_CHECK_UNAVAILABLE")).toBe(true);
    expect(isUnverifiedCheck("ZERO_DAY_CHECK_UNAVAILABLE")).toBe(true);
  });

  it("matches codes ending with _DID_NOT_RUN", () => {
    expect(isUnverifiedCheck("SOMETHING_DID_NOT_RUN")).toBe(true);
  });

  it("matches codes ending with _UNVERIFIED", () => {
    expect(isUnverifiedCheck("CUSTOM_CHECK_UNVERIFIED")).toBe(true);
  });

  it("matches codes ending with _MISSING", () => {
    expect(isUnverifiedCheck("REQUIRED_DATA_MISSING")).toBe(true);
  });

  it("matches codes ending with _UNSUPPORTED", () => {
    expect(isUnverifiedCheck("REGION_UNSUPPORTED")).toBe(true);
  });

  it("rejects codes that do not match any suffix", () => {
    expect(isUnverifiedCheck("SANCTIONS_MATCH")).toBe(false);
    expect(isUnverifiedCheck("BLOCKED")).toBe(false);
    expect(isUnverifiedCheck("SOMETHING_FAILED")).toBe(false);
  });

  it("is case-sensitive in the suffix", () => {
    expect(isUnverifiedCheck("SOMETHING_unavailable")).toBe(false);
  });
});

describe("unverifiedChecks", () => {
  it("filters to only unverified findings", () => {
    const findings: AuditFinding[] = [
      {
        code: "HS_DESCRIPTION_CHECK_UNAVAILABLE",
        severity: "LOW",
        detail: "Not available",
        floor: 0,
        source_entity_ids: [],
      },
      {
        code: "SANCTIONS_MATCH",
        severity: "CRITICAL",
        detail: "Hit",
        floor: 95,
        source_entity_ids: ["id1"],
      },
      {
        code: "ZERO_DAY_CHECK_UNVERIFIED",
        severity: "LOW",
        detail: "Not checked",
        floor: 0,
        source_entity_ids: [],
      },
    ];
    const result = unverifiedChecks(findings);
    expect(result).toHaveLength(2);
    expect(result[0]?.code).toBe("HS_DESCRIPTION_CHECK_UNAVAILABLE");
    expect(result[1]?.code).toBe("ZERO_DAY_CHECK_UNVERIFIED");
  });

  it("returns empty array when no findings are unverified", () => {
    const findings: AuditFinding[] = [
      {
        code: "SANCTIONS_MATCH",
        severity: "CRITICAL",
        detail: "Hit",
        floor: 95,
        source_entity_ids: ["id1"],
      },
    ];
    expect(unverifiedChecks(findings)).toEqual([]);
  });

  it("returns empty array for empty input", () => {
    expect(unverifiedChecks([])).toEqual([]);
  });
});

describe("derivePresentation", () => {
  const baseAudit: ComplianceAuditResponse = {
    audit_id: "a1",
    case_id: "c1",
    shipment_id: "s1",
    client_reference: null,
    outcome: "CLEARED",
    effective_risk: 10,
    model_risk: null,
    risk_floor: 5,
    score_disputed: false,
    findings: [],
    requires_human_review: false,
    review_reason: null,
    lineage: {
      audit_id: "a1",
      prompt_hashes: {},
      model_versions: {},
      sanctions_synced_at: null,
      sanctions_list_age_days: null,
      ruleset_version: null,
    },
    usage: {
      input_tokens: 100,
      output_tokens: 50,
      estimated_cost_usd: 0.001,
      agent_calls: 1,
      latency_ms: 500,
    },
    created_at: "2026-01-01T00:00:00Z",
    completed_at: "2026-01-01T00:00:05Z",
    idempotent_replay: false,
  };

  it("maps CLEARED outcome to clear state", () => {
    const audit: ComplianceAuditResponse = {
      ...baseAudit,
      outcome: "CLEARED",
    };
    const result = derivePresentation(audit);
    expect(result.state).toBe("clear");
    expect(result.label).toBe("Clear");
  });

  it("maps BLOCKED outcome to critical state", () => {
    const audit: ComplianceAuditResponse = {
      ...baseAudit,
      outcome: "BLOCKED",
    };
    const result = derivePresentation(audit);
    expect(result.state).toBe("critical");
    expect(result.label).toBe("OFAC Sanction");
  });

  it("maps HELD_FOR_REVIEW outcome to warn state", () => {
    const audit: ComplianceAuditResponse = {
      ...baseAudit,
      outcome: "HELD_FOR_REVIEW",
    };
    const result = derivePresentation(audit);
    expect(result.state).toBe("warn");
    expect(result.label).toBe("Held for review");
  });

  it("maps PENDING_HUMAN outcome to warn state", () => {
    const audit: ComplianceAuditResponse = {
      ...baseAudit,
      outcome: "PENDING_HUMAN",
    };
    const result = derivePresentation(audit);
    expect(result.state).toBe("warn");
    expect(result.label).toBe("Awaiting officer");
  });

  it("maps ERROR outcome to warn state", () => {
    const audit: ComplianceAuditResponse = {
      ...baseAudit,
      outcome: "ERROR",
    };
    const result = derivePresentation(audit);
    expect(result.state).toBe("warn");
    expect(result.label).toBe("Audit failed");
  });

  it("uses review_reason when provided", () => {
    const audit: ComplianceAuditResponse = {
      ...baseAudit,
      outcome: "HELD_FOR_REVIEW",
      review_reason: "Custom review reason",
    };
    const result = derivePresentation(audit);
    expect(result.reason).toBe("Custom review reason");
  });

  it("provides default reason for clear outcome without review_reason", () => {
    const audit: ComplianceAuditResponse = {
      ...baseAudit,
      outcome: "CLEARED",
    };
    const result = derivePresentation(audit);
    expect(result.reason).toContain("All deterministic and model checks");
  });

  it("includes effective risk in reason for non-clear outcomes", () => {
    const audit: ComplianceAuditResponse = {
      ...baseAudit,
      outcome: "HELD_FOR_REVIEW",
      effective_risk: 65,
    };
    const result = derivePresentation(audit);
    expect(result.reason).toContain("65");
  });

  describe("SANCTIONS_MATCH override", () => {
    it("overrides label to OFAC Sanction when found, regardless of outcome", () => {
      const audit: ComplianceAuditResponse = {
        ...baseAudit,
        outcome: "HELD_FOR_REVIEW",
        findings: [
          {
            code: "SANCTIONS_MATCH",
            severity: "CRITICAL",
            detail: "Match",
            floor: 95,
            source_entity_ids: ["id1"],
          },
        ],
      };
      const result = derivePresentation(audit);
      expect(result.label).toBe("OFAC Sanction");
    });

    it("keeps state as warn when outcome is HELD_FOR_REVIEW and sanctions hit", () => {
      const audit: ComplianceAuditResponse = {
        ...baseAudit,
        outcome: "HELD_FOR_REVIEW",
        findings: [
          {
            code: "SANCTIONS_MATCH",
            severity: "CRITICAL",
            detail: "Match",
            floor: 95,
            source_entity_ids: ["id1"],
          },
        ],
      };
      const result = derivePresentation(audit);
      expect(result.state).toBe("warn");
    });
  });

  describe("ZERO_DAY_ADVERSE_MEDIA override", () => {
    it("overrides label when found and state is not clear", () => {
      const audit: ComplianceAuditResponse = {
        ...baseAudit,
        outcome: "HELD_FOR_REVIEW",
        findings: [
          {
            code: "ZERO_DAY_ADVERSE_MEDIA",
            severity: "HIGH",
            detail: "Adverse media",
            floor: 50,
            source_entity_ids: [],
          },
        ],
      };
      const result = derivePresentation(audit);
      expect(result.label).toBe("Zero-Day Risk");
    });

    it("does not override label when state is clear", () => {
      const audit: ComplianceAuditResponse = {
        ...baseAudit,
        outcome: "CLEARED",
        findings: [
          {
            code: "ZERO_DAY_ADVERSE_MEDIA",
            severity: "LOW",
            detail: "Adverse media",
            floor: 0,
            source_entity_ids: [],
          },
        ],
      };
      const result = derivePresentation(audit);
      expect(result.label).toBe("Clear");
    });
  });

  describe("unverified findings", () => {
    it("returns unverified findings array", () => {
      const audit: ComplianceAuditResponse = {
        ...baseAudit,
        findings: [
          {
            code: "HS_DESCRIPTION_CHECK_UNAVAILABLE",
            severity: "LOW",
            detail: "Not available",
            floor: 0,
            source_entity_ids: [],
          },
        ],
      };
      const result = derivePresentation(audit);
      expect(result.unverified).toHaveLength(1);
      expect(result.unverified[0]?.code).toBe("HS_DESCRIPTION_CHECK_UNAVAILABLE");
    });

    it("changes state to warn when CLEARED with unverified findings", () => {
      const audit: ComplianceAuditResponse = {
        ...baseAudit,
        outcome: "CLEARED",
        findings: [
          {
            code: "HS_DESCRIPTION_CHECK_UNAVAILABLE",
            severity: "LOW",
            detail: "Not available",
            floor: 0,
            source_entity_ids: [],
          },
        ],
      };
      const result = derivePresentation(audit);
      expect(result.state).toBe("warn");
      expect(result.label).toContain("Clear, 1 unverified");
    });

    it("includes unverified count in label for cleared with unverified", () => {
      const audit: ComplianceAuditResponse = {
        ...baseAudit,
        outcome: "CLEARED",
        findings: [
          {
            code: "HS_DESCRIPTION_CHECK_UNAVAILABLE",
            severity: "LOW",
            detail: "Not available",
            floor: 0,
            source_entity_ids: [],
          },
          {
            code: "ZERO_DAY_CHECK_DID_NOT_RUN",
            severity: "LOW",
            detail: "Not run",
            floor: 0,
            source_entity_ids: [],
          },
        ],
      };
      const result = derivePresentation(audit);
      expect(result.label).toContain("2 unverified");
    });

    it("includes unverified codes in reason when cleared with unverified", () => {
      const audit: ComplianceAuditResponse = {
        ...baseAudit,
        outcome: "CLEARED",
        findings: [
          {
            code: "HS_DESCRIPTION_CHECK_UNAVAILABLE",
            severity: "LOW",
            detail: "Not available",
            floor: 0,
            source_entity_ids: [],
          },
        ],
      };
      const result = derivePresentation(audit);
      expect(result.reason).toContain("HS description check unavailable");
      expect(result.reason).toContain("did not complete");
    });
  });

  it("handles unknown outcome gracefully", () => {
    const audit: ComplianceAuditResponse = {
      ...baseAudit,
      outcome: "CLEARED",
    };
    (audit as { outcome: string }).outcome = "UNKNOWN_OUTCOME";
    const result = derivePresentation(audit);
    expect(result.state).toBe("neutral");
    expect(result.label).toBe("UNKNOWN_OUTCOME");
  });
});

describe("sortFindings", () => {
  it("sorts by severity rank first", () => {
    const findings: AuditFinding[] = [
      {
        code: "INFO_CODE",
        severity: "INFO",
        detail: "Info",
        floor: 0,
        source_entity_ids: [],
      },
      {
        code: "CRITICAL_CODE",
        severity: "CRITICAL",
        detail: "Critical",
        floor: 50,
        source_entity_ids: [],
      },
      {
        code: "HIGH_CODE",
        severity: "HIGH",
        detail: "High",
        floor: 30,
        source_entity_ids: [],
      },
    ];
    const result = sortFindings(findings);
    expect(result[0]?.code).toBe("CRITICAL_CODE");
    expect(result[1]?.code).toBe("HIGH_CODE");
    expect(result[2]?.code).toBe("INFO_CODE");
  });

  it("sorts by floor when severity is equal", () => {
    const findings: AuditFinding[] = [
      {
        code: "HIGH_LOW_FLOOR",
        severity: "HIGH",
        detail: "High low floor",
        floor: 20,
        source_entity_ids: [],
      },
      {
        code: "HIGH_HIGH_FLOOR",
        severity: "HIGH",
        detail: "High high floor",
        floor: 80,
        source_entity_ids: [],
      },
      {
        code: "HIGH_MID_FLOOR",
        severity: "HIGH",
        detail: "High mid floor",
        floor: 50,
        source_entity_ids: [],
      },
    ];
    const result = sortFindings(findings);
    expect(result[0]?.code).toBe("HIGH_HIGH_FLOOR");
    expect(result[1]?.code).toBe("HIGH_MID_FLOOR");
    expect(result[2]?.code).toBe("HIGH_LOW_FLOOR");
  });

  it("handles unknown severity gracefully", () => {
    const findings: AuditFinding[] = [
      {
        code: "KNOWN_HIGH",
        severity: "HIGH",
        detail: "Known high",
        floor: 30,
        source_entity_ids: [],
      },
      {
        code: "UNKNOWN_SEVERITY",
        severity: "HIGH",
        detail: "Unknown severity",
        floor: 50,
        source_entity_ids: [],
      },
    ];
    (findings[1] as { severity: string }).severity = "UNKNOWN";
    const result = sortFindings(findings);
    expect(result).toHaveLength(2);
    expect(result[0]?.code).toBe("KNOWN_HIGH");
  });

  it("does not mutate the original array", () => {
    const findings: AuditFinding[] = [
      {
        code: "A",
        severity: "LOW",
        detail: "Low",
        floor: 10,
        source_entity_ids: [],
      },
      {
        code: "B",
        severity: "CRITICAL",
        detail: "Critical",
        floor: 90,
        source_entity_ids: [],
      },
    ];
    const original = [...findings];
    sortFindings(findings);
    expect(findings).toEqual(original);
  });

  it("sorts CRITICAL > HIGH > MEDIUM > LOW > INFO > CLEAR", () => {
    const findings: AuditFinding[] = [
      { code: "i", severity: "INFO", detail: "", floor: 0, source_entity_ids: [] },
      { code: "c", severity: "CRITICAL", detail: "", floor: 0, source_entity_ids: [] },
      { code: "cl", severity: "CLEAR", detail: "", floor: 0, source_entity_ids: [] },
      { code: "m", severity: "MEDIUM", detail: "", floor: 0, source_entity_ids: [] },
      { code: "h", severity: "HIGH", detail: "", floor: 0, source_entity_ids: [] },
      { code: "l", severity: "LOW", detail: "", floor: 0, source_entity_ids: [] },
    ];
    const result = sortFindings(findings);
    expect(result.map((f) => f.code)).toEqual(["c", "h", "m", "l", "i", "cl"]);
  });
});

describe("severityState", () => {
  it("maps CRITICAL to critical", () => {
    expect(severityState("CRITICAL")).toBe("critical");
  });

  it("maps HIGH to warn", () => {
    expect(severityState("HIGH")).toBe("warn");
  });

  it("maps MEDIUM to warn", () => {
    expect(severityState("MEDIUM")).toBe("warn");
  });

  it("maps LOW to neutral", () => {
    expect(severityState("LOW")).toBe("neutral");
  });

  it("maps INFO to neutral", () => {
    expect(severityState("INFO")).toBe("neutral");
  });

  it("maps CLEAR to clear", () => {
    expect(severityState("CLEAR")).toBe("clear");
  });

  it("maps unknown severity to neutral", () => {
    expect(severityState("UNKNOWN" as never)).toBe("neutral");
  });
});

describe("screeningFindings", () => {
  it("filters out evidence findings (ZERO_DAY prefix)", () => {
    const findings: AuditFinding[] = [
      {
        code: "ZERO_DAY_ADVERSE_MEDIA",
        severity: "HIGH",
        detail: "Adverse media",
        floor: 50,
        source_entity_ids: [],
      },
      {
        code: "SANCTIONS_MATCH",
        severity: "CRITICAL",
        detail: "Match",
        floor: 95,
        source_entity_ids: [],
      },
      {
        code: "ZERO_DAY_SOMETHING",
        severity: "MEDIUM",
        detail: "Zero day",
        floor: 40,
        source_entity_ids: [],
      },
    ];
    const result = screeningFindings(findings);
    expect(result).toHaveLength(1);
    expect(result[0]?.code).toBe("SANCTIONS_MATCH");
  });

  it("includes all non-ZERO_DAY findings", () => {
    const findings: AuditFinding[] = [
      {
        code: "SANCTIONS_MATCH",
        severity: "CRITICAL",
        detail: "Match",
        floor: 95,
        source_entity_ids: [],
      },
      {
        code: "HIGH_RISK_COUNTRY",
        severity: "HIGH",
        detail: "High risk",
        floor: 30,
        source_entity_ids: [],
      },
      {
        code: "SHIPPER_NO_HISTORY",
        severity: "MEDIUM",
        detail: "No history",
        floor: 20,
        source_entity_ids: [],
      },
    ];
    const result = screeningFindings(findings);
    expect(result).toEqual(findings);
  });

  it("returns empty array when all findings are evidence findings", () => {
    const findings: AuditFinding[] = [
      {
        code: "ZERO_DAY_ADVERSE_MEDIA",
        severity: "HIGH",
        detail: "Adverse",
        floor: 50,
        source_entity_ids: [],
      },
    ];
    expect(screeningFindings(findings)).toEqual([]);
  });

  it("handles empty input", () => {
    expect(screeningFindings([])).toEqual([]);
  });
});

describe("evidenceFindings", () => {
  it("filters to only evidence findings (ZERO_DAY prefix)", () => {
    const findings: AuditFinding[] = [
      {
        code: "ZERO_DAY_ADVERSE_MEDIA",
        severity: "HIGH",
        detail: "Adverse media",
        floor: 50,
        source_entity_ids: [],
      },
      {
        code: "SANCTIONS_MATCH",
        severity: "CRITICAL",
        detail: "Match",
        floor: 95,
        source_entity_ids: [],
      },
      {
        code: "ZERO_DAY_SOMETHING_ELSE",
        severity: "MEDIUM",
        detail: "Zero day",
        floor: 40,
        source_entity_ids: [],
      },
    ];
    const result = evidenceFindings(findings);
    expect(result).toHaveLength(2);
    expect(result[0]?.code).toBe("ZERO_DAY_ADVERSE_MEDIA");
    expect(result[1]?.code).toBe("ZERO_DAY_SOMETHING_ELSE");
  });

  it("returns empty array when no evidence findings", () => {
    const findings: AuditFinding[] = [
      {
        code: "SANCTIONS_MATCH",
        severity: "CRITICAL",
        detail: "Match",
        floor: 95,
        source_entity_ids: [],
      },
    ];
    expect(evidenceFindings(findings)).toEqual([]);
  });

  it("handles empty input", () => {
    expect(evidenceFindings([])).toEqual([]);
  });

  it("matches all codes starting with ZERO_DAY", () => {
    const findings: AuditFinding[] = [
      {
        code: "ZERO_DAY",
        severity: "HIGH",
        detail: "Zero day",
        floor: 50,
        source_entity_ids: [],
      },
      {
        code: "ZERO_DAY_A",
        severity: "HIGH",
        detail: "Zero day A",
        floor: 40,
        source_entity_ids: [],
      },
      {
        code: "ZERO_DAYS",
        severity: "HIGH",
        detail: "Zero days",
        floor: 30,
        source_entity_ids: [],
      },
    ];
    const result = evidenceFindings(findings);
    expect(result).toHaveLength(3);
    expect(result.every((f) => f.code.startsWith("ZERO_DAY"))).toBe(true);
  });
});

describe("RISK_CLASS constant", () => {
  it("maps critical to badge-risk badge-critical", () => {
    expect(RISK_CLASS.critical).toBe("badge-risk badge-critical");
  });

  it("maps warn to badge-risk badge-warn", () => {
    expect(RISK_CLASS.warn).toBe("badge-risk badge-warn");
  });

  it("maps clear to badge-risk badge-clear", () => {
    expect(RISK_CLASS.clear).toBe("badge-risk badge-clear");
  });

  it("maps neutral to badge-risk badge-neutral", () => {
    expect(RISK_CLASS.neutral).toBe("badge-risk badge-neutral");
  });

  it("contains all risk states", () => {
    expect(Object.keys(RISK_CLASS)).toEqual(["critical", "warn", "clear", "neutral"]);
  });
});
