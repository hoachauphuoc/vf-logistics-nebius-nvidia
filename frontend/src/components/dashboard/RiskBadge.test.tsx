import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import type { AuditFinding, ComplianceAuditResponse, Severity } from "@/lib/types";

import { RiskBadge, SeverityBadge } from "./RiskBadge";

// Radix measures the floating tooltip content with ResizeObserver, which jsdom does not provide.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

function finding(code: string, severity: Severity = "HIGH"): AuditFinding {
  return {
    code,
    severity,
    detail: "",
    floor: 0,
    source_entity_ids: [],
  };
}

function makeAudit(overrides: Partial<ComplianceAuditResponse> = {}): ComplianceAuditResponse {
  return {
    audit_id: "audit-1",
    case_id: "case-1",
    shipment_id: "shipment-1",
    client_reference: null,
    outcome: "CLEARED",
    effective_risk: 10,
    model_risk: 10,
    risk_floor: 0,
    score_disputed: false,
    findings: [],
    requires_human_review: false,
    review_reason: null,
    lineage: {
      audit_id: "audit-1",
      prompt_hashes: {},
      model_versions: {},
      sanctions_synced_at: null,
      sanctions_list_age_days: null,
      ruleset_version: null,
    },
    usage: {
      input_tokens: 0,
      output_tokens: 0,
      estimated_cost_usd: 0,
      agent_calls: 0,
      latency_ms: null,
    },
    created_at: "2026-10-01T00:00:00Z",
    completed_at: null,
    idempotent_replay: false,
    ...overrides,
  };
}

function renderBadge(audit: ComplianceAuditResponse) {
  return render(
    <TooltipProvider>
      <RiskBadge audit={audit} />
    </TooltipProvider>,
  );
}

// The status text is the badge's own text node, so it is the element that owns data-state.
function getBadge(label: string): HTMLElement {
  return screen.getByText(label);
}

describe("RiskBadge", () => {
  beforeEach(() => {
    vi.stubGlobal("ResizeObserver", ResizeObserverStub);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows Clear with the clear state for a cleared audit with no findings", () => {
    renderBadge(makeAudit({ outcome: "CLEARED" }));

    const badge = getBadge("Clear");
    expect(badge).toHaveAttribute("data-state", "clear");
    expect(badge).toHaveClass("badge-risk", "badge-clear");
  });

  it("shows OFAC Sanction in the critical state for a blocked audit", () => {
    renderBadge(makeAudit({ outcome: "BLOCKED", effective_risk: 95 }));

    const badge = getBadge("OFAC Sanction");
    expect(badge).toHaveAttribute("data-state", "critical");
    expect(badge).toHaveClass("badge-critical");
  });

  it("shows Held for review in the warn state for a held audit", () => {
    renderBadge(makeAudit({ outcome: "HELD_FOR_REVIEW", effective_risk: 70 }));

    const badge = getBadge("Held for review");
    expect(badge).toHaveAttribute("data-state", "warn");
    expect(badge).toHaveClass("badge-warn");
  });

  it("shows Awaiting officer in the warn state for an audit pending a person", () => {
    renderBadge(makeAudit({ outcome: "PENDING_HUMAN" }));

    expect(getBadge("Awaiting officer")).toHaveAttribute("data-state", "warn");
  });

  it("shows Audit failed in the warn state, never the clear state, when the audit errored", () => {
    renderBadge(makeAudit({ outcome: "ERROR" }));

    const badge = getBadge("Audit failed");
    expect(badge).toHaveAttribute("data-state", "warn");
    expect(badge).not.toHaveAttribute("data-state", "clear");
  });

  it("replaces the outcome label with OFAC Sanction when a sanctions match is present", () => {
    renderBadge(
      makeAudit({
        outcome: "HELD_FOR_REVIEW",
        findings: [finding("SANCTIONS_MATCH", "CRITICAL")],
      }),
    );

    expect(screen.getByText("OFAC Sanction")).toHaveAttribute("data-state", "warn");
    expect(screen.queryByText("Held for review")).not.toBeInTheDocument();
  });

  it("shows Zero-Day Risk for a held audit that carries adverse media", () => {
    renderBadge(
      makeAudit({
        outcome: "HELD_FOR_REVIEW",
        findings: [finding("ZERO_DAY_ADVERSE_MEDIA")],
      }),
    );

    expect(screen.getByText("Zero-Day Risk")).toHaveAttribute("data-state", "warn");
  });

  it("keeps Clear for a cleared audit that carries adverse media", () => {
    renderBadge(
      makeAudit({
        outcome: "CLEARED",
        findings: [finding("ZERO_DAY_ADVERSE_MEDIA")],
      }),
    );

    expect(screen.getByText("Clear")).toHaveAttribute("data-state", "clear");
    expect(screen.queryByText("Zero-Day Risk")).not.toBeInTheDocument();
  });

  it("labels a cleared audit with an unverified check as warn, not clear", () => {
    renderBadge(
      makeAudit({
        outcome: "CLEARED",
        findings: [finding("HS_DESCRIPTION_CHECK_UNAVAILABLE", "INFO")],
      }),
    );

    const badge = screen.getByText("Clear, 1 unverified");
    expect(badge).toHaveAttribute("data-state", "warn");
    expect(badge).not.toHaveAttribute("data-state", "clear");
  });

  it("counts every unverified check in the label", () => {
    renderBadge(
      makeAudit({
        outcome: "CLEARED",
        findings: [
          finding("HS_DESCRIPTION_CHECK_UNAVAILABLE", "INFO"),
          finding("ZERO_DAY_CHECK_UNAVAILABLE", "INFO"),
          finding("FREIGHT_ANOMALY", "LOW"),
        ],
      }),
    );

    expect(screen.getByText("Clear, 2 unverified")).toBeInTheDocument();
  });

  it("ignores findings whose code does not mean an unverified check", () => {
    renderBadge(
      makeAudit({
        outcome: "CLEARED",
        findings: [finding("FREIGHT_ANOMALY", "LOW")],
      }),
    );

    expect(screen.getByText("Clear")).toHaveAttribute("data-state", "clear");
  });

  it("explains a cleared audit with an unverified check in the tooltip", async () => {
    renderBadge(
      makeAudit({
        outcome: "CLEARED",
        findings: [finding("ZERO_DAY_CHECK_UNAVAILABLE", "INFO")],
      }),
    );

    fireEvent.pointerMove(getBadge("Clear, 1 unverified"), { pointerType: "mouse" });

    expect(await screen.findByText(/1 check\(s\) did not complete/)).toBeInTheDocument();
    expect(
      screen.getByText("An incomplete check is not a clearance."),
    ).toBeInTheDocument();
  });

  it("shows the default clear reason in the tooltip for a clean cleared audit", async () => {
    renderBadge(makeAudit({ outcome: "CLEARED" }));

    expect(
      screen.queryByText("All deterministic and model checks completed with no adverse finding."),
    ).not.toBeInTheDocument();

    fireEvent.pointerMove(getBadge("Clear"), { pointerType: "mouse" });

    expect(
      await screen.findByText(
        "All deterministic and model checks completed with no adverse finding.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("An incomplete check is not a clearance.")).not.toBeInTheDocument();
  });

  it("shows the review reason in the tooltip when the audit carries one", async () => {
    renderBadge(
      makeAudit({
        outcome: "HELD_FOR_REVIEW",
        review_reason: "Consignee name is a close match to a listed entity.",
      }),
    );

    fireEvent.pointerMove(getBadge("Held for review"), { pointerType: "mouse" });

    expect(
      await screen.findByText("Consignee name is a close match to a listed entity."),
    ).toBeInTheDocument();
  });

  it("builds an outcome reason from the effective risk when there is no review reason", async () => {
    renderBadge(makeAudit({ outcome: "HELD_FOR_REVIEW", effective_risk: 70 }));

    fireEvent.pointerMove(getBadge("Held for review"), { pointerType: "mouse" });

    expect(await screen.findByText(/at effective risk 70\./)).toBeInTheDocument();
  });

  it("does not show the tooltip reason before the trigger is hovered", () => {
    renderBadge(makeAudit({ outcome: "CLEARED" }));

    expect(
      screen.queryByText("All deterministic and model checks completed with no adverse finding."),
    ).not.toBeInTheDocument();
  });
});

describe("SeverityBadge", () => {
  it("labels a CRITICAL finding and gives it the critical style", () => {
    render(<SeverityBadge severity="CRITICAL" />);

    const badge = screen.getByText("Critical");
    expect(badge).toHaveClass("badge-critical");
  });

  it("labels a HIGH finding and gives it the warn style", () => {
    render(<SeverityBadge severity="HIGH" />);

    expect(screen.getByText("High")).toHaveClass("badge-warn");
  });

  it("labels a MEDIUM finding and gives it the warn style", () => {
    render(<SeverityBadge severity="MEDIUM" />);

    expect(screen.getByText("Medium")).toHaveClass("badge-warn");
  });

  it("labels a LOW finding and gives it the neutral style", () => {
    render(<SeverityBadge severity="LOW" />);

    expect(screen.getByText("Low")).toHaveClass("badge-neutral");
  });

  it("labels an INFO finding as Informational with the neutral style", () => {
    render(<SeverityBadge severity="INFO" />);

    expect(screen.getByText("Informational")).toHaveClass("badge-neutral");
  });

  it("labels a CLEAR finding as Clear with the clear style", () => {
    render(<SeverityBadge severity="CLEAR" />);

    expect(screen.getByText("Clear")).toHaveClass("badge-clear");
  });
});
