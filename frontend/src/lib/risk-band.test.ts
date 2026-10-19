import { describe, expect, it } from "vitest";

import {
  RISK_FILL,
  RISK_HIGH,
  RISK_MEDIUM,
  RISK_TEXT,
  injectionCaught,
  riskBand,
  type RiskBand,
} from "@/lib/risk-band";
import type { Case } from "@/lib/types";

describe("constants", () => {
  it("RISK_HIGH is 70", () => {
    expect(RISK_HIGH).toBe(70);
  });

  it("RISK_MEDIUM is 40", () => {
    expect(RISK_MEDIUM).toBe(40);
  });

  it("RISK_MEDIUM < RISK_HIGH", () => {
    expect(RISK_MEDIUM).toBeLessThan(RISK_HIGH);
  });
});

describe("riskBand", () => {
  describe("when score is high", () => {
    it("returns 'high' for score at RISK_HIGH (70)", () => {
      expect(riskBand(70)).toBe("high");
    });

    it("returns 'high' for score above RISK_HIGH", () => {
      expect(riskBand(75)).toBe("high");
      expect(riskBand(100)).toBe("high");
      expect(riskBand(150)).toBe("high");
    });
  });

  describe("when score is medium", () => {
    it("returns 'medium' for score at RISK_MEDIUM (40)", () => {
      expect(riskBand(40)).toBe("medium");
    });

    it("returns 'medium' for score between RISK_MEDIUM and RISK_HIGH", () => {
      expect(riskBand(50)).toBe("medium");
      expect(riskBand(69)).toBe("medium");
    });

    it("returns 'medium' for score just below RISK_HIGH", () => {
      expect(riskBand(69.99)).toBe("medium");
    });
  });

  describe("when score is low", () => {
    it("returns 'low' for score below RISK_MEDIUM", () => {
      expect(riskBand(0)).toBe("low");
      expect(riskBand(20)).toBe("low");
      expect(riskBand(39)).toBe("low");
    });

    it("returns 'low' for score just below RISK_MEDIUM", () => {
      expect(riskBand(39.99)).toBe("low");
    });

    it("returns 'low' for negative scores", () => {
      expect(riskBand(-10)).toBe("low");
      expect(riskBand(-100)).toBe("low");
    });
  });

  describe("when score is absent or invalid", () => {
    it("returns 'unknown' for null", () => {
      expect(riskBand(null)).toBe("unknown");
    });

    it("returns 'unknown' for undefined", () => {
      expect(riskBand(undefined)).toBe("unknown");
    });

    it("returns 'unknown' for NaN", () => {
      expect(riskBand(NaN)).toBe("unknown");
    });
  });

  describe("edge cases", () => {
    it("handles 0 correctly as low", () => {
      expect(riskBand(0)).toBe("low");
    });

    it("handles boundary between low and medium", () => {
      expect(riskBand(40)).toBe("medium");
      expect(riskBand(40.01)).toBe("medium");
    });

    it("handles boundary between medium and high", () => {
      expect(riskBand(70)).toBe("high");
      expect(riskBand(70.01)).toBe("high");
    });
  });
});

describe("RISK_TEXT", () => {
  it("has entry for 'high' band", () => {
    expect(RISK_TEXT.high).toBe("text-risk-critical");
  });

  it("has entry for 'medium' band", () => {
    expect(RISK_TEXT.medium).toBe("text-risk-warn");
  });

  it("has entry for 'low' band", () => {
    expect(RISK_TEXT.low).toBe("text-risk-clear");
  });

  it("has entry for 'unknown' band", () => {
    expect(RISK_TEXT.unknown).toBe("text-risk-unknown");
  });

  it("contains all four risk bands", () => {
    expect(RISK_TEXT).toEqual({
      high: "text-risk-critical",
      medium: "text-risk-warn",
      low: "text-risk-clear",
      unknown: "text-risk-unknown",
    });
  });

  it("all values are strings", () => {
    const bands: RiskBand[] = ["high", "medium", "low", "unknown"];
    for (const band of bands) {
      expect(typeof RISK_TEXT[band]).toBe("string");
    }
  });
});

describe("RISK_FILL", () => {
  it("has entry for 'high' band", () => {
    expect(RISK_FILL.high).toBe("bg-risk-critical");
  });

  it("has entry for 'medium' band", () => {
    expect(RISK_FILL.medium).toBe("bg-risk-warn");
  });

  it("has entry for 'low' band", () => {
    expect(RISK_FILL.low).toBe("bg-risk-clear");
  });

  it("has entry for 'unknown' band", () => {
    expect(RISK_FILL.unknown).toBe("bg-risk-unknown");
  });

  it("contains all four risk bands", () => {
    expect(RISK_FILL).toEqual({
      high: "bg-risk-critical",
      medium: "bg-risk-warn",
      low: "bg-risk-clear",
      unknown: "bg-risk-unknown",
    });
  });

  it("all values are strings", () => {
    const bands: RiskBand[] = ["high", "medium", "low", "unknown"];
    for (const band of bands) {
      expect(typeof RISK_FILL[band]).toBe("string");
    }
  });
});

describe("injectionCaught", () => {
  describe("when no input_security is present", () => {
    it("returns false when input_security is undefined", () => {
      const c: Pick<Case, "input_security"> = { input_security: undefined };
      expect(injectionCaught(c)).toBe(false);
    });

    it("returns false when input_security is null", () => {
      const c = { input_security: null } as never;
      expect(injectionCaught(c)).toBe(false);
    });

    it("returns false when input_security is empty object", () => {
      const c: Pick<Case, "input_security"> = { input_security: {} as never };
      expect(injectionCaught(c)).toBe(false);
    });
  });

  describe("when injection_screening is blocked", () => {
    it("returns true when injection_screening.blocked is true", () => {
      const c: Pick<Case, "input_security"> = {
        input_security: {
          injection_screening: { blocked: true },
        } as never,
      };
      expect(injectionCaught(c)).toBe(true);
    });

    it("returns false when injection_screening.blocked is false", () => {
      const c: Pick<Case, "input_security"> = {
        input_security: {
          injection_screening: { blocked: false },
        } as never,
      };
      expect(injectionCaught(c)).toBe(false);
    });

    it("returns false when injection_screening is null", () => {
      const c: Pick<Case, "input_security"> = {
        input_security: {
          injection_screening: null,
        } as never,
      };
      expect(injectionCaught(c)).toBe(false);
    });

    it("returns false when injection_screening is empty object", () => {
      const c: Pick<Case, "input_security"> = {
        input_security: {
          injection_screening: {},
        } as never,
      };
      expect(injectionCaught(c)).toBe(false);
    });
  });

  describe("when model_armor is blocked", () => {
    it("returns true when model_armor.blocked is true", () => {
      const c: Pick<Case, "input_security"> = {
        input_security: {
          model_armor: { blocked: true },
        } as never,
      };
      expect(injectionCaught(c)).toBe(true);
    });

    it("returns false when model_armor.blocked is false", () => {
      const c: Pick<Case, "input_security"> = {
        input_security: {
          model_armor: { blocked: false },
        } as never,
      };
      expect(injectionCaught(c)).toBe(false);
    });

    it("returns false when model_armor is null", () => {
      const c: Pick<Case, "input_security"> = {
        input_security: {
          model_armor: null,
        } as never,
      };
      expect(injectionCaught(c)).toBe(false);
    });

    it("returns false when model_armor is empty object", () => {
      const c: Pick<Case, "input_security"> = {
        input_security: {
          model_armor: {},
        } as never,
      };
      expect(injectionCaught(c)).toBe(false);
    });
  });

  describe("when forbidden_fields_attempted has items", () => {
    it("returns true with one field", () => {
      const c: Pick<Case, "input_security"> = {
        input_security: {
          forbidden_fields_attempted: ["field1"],
        } as never,
      };
      expect(injectionCaught(c)).toBe(true);
    });

    it("returns true with multiple fields", () => {
      const c: Pick<Case, "input_security"> = {
        input_security: {
          forbidden_fields_attempted: ["field1", "field2", "field3"],
        } as never,
      };
      expect(injectionCaught(c)).toBe(true);
    });

    it("returns false when forbidden_fields_attempted is empty", () => {
      const c: Pick<Case, "input_security"> = {
        input_security: {
          forbidden_fields_attempted: [],
        } as never,
      };
      expect(injectionCaught(c)).toBe(false);
    });

    it("returns false when forbidden_fields_attempted is null", () => {
      const c: Pick<Case, "input_security"> = {
        input_security: {
          forbidden_fields_attempted: null,
        } as never,
      };
      expect(injectionCaught(c)).toBe(false);
    });
  });

  describe("with multiple security signals", () => {
    it("returns true when injection_screening is blocked", () => {
      const c: Pick<Case, "input_security"> = {
        input_security: {
          injection_screening: { blocked: true },
          model_armor: { blocked: false },
          forbidden_fields_attempted: [],
        } as never,
      };
      expect(injectionCaught(c)).toBe(true);
    });

    it("returns true when model_armor is blocked", () => {
      const c: Pick<Case, "input_security"> = {
        input_security: {
          injection_screening: { blocked: false },
          model_armor: { blocked: true },
          forbidden_fields_attempted: [],
        } as never,
      };
      expect(injectionCaught(c)).toBe(true);
    });

    it("returns true when forbidden_fields_attempted has items", () => {
      const c: Pick<Case, "input_security"> = {
        input_security: {
          injection_screening: { blocked: false },
          model_armor: { blocked: false },
          forbidden_fields_attempted: ["field1"],
        } as never,
      };
      expect(injectionCaught(c)).toBe(true);
    });

    it("returns false when all signals are absent", () => {
      const c: Pick<Case, "input_security"> = {
        input_security: {
          injection_screening: { blocked: false },
          model_armor: { blocked: false },
          forbidden_fields_attempted: [],
        } as never,
      };
      expect(injectionCaught(c)).toBe(false);
    });

    it("returns true when all signals are present and at least one is active", () => {
      const c: Pick<Case, "input_security"> = {
        input_security: {
          injection_screening: { blocked: true },
          model_armor: { blocked: true },
          forbidden_fields_attempted: ["field1", "field2"],
        } as never,
      };
      expect(injectionCaught(c)).toBe(true);
    });
  });
});
