import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Tooltip as TooltipPrimitive } from "radix-ui";

import { KpiCards } from "@/components/dashboard/KpiCards";
import { NO_VALUE } from "@/lib/format";
import type { ComplianceAuditResponse, TenantUsageResponse } from "@/lib/types";

/**
 * The console must not state a number nobody measured.
 *
 * `KpiCards` read `formatUsd(usage?.estimated_cost_usd ?? 0)`. `formatUsd` returns an em
 * dash for nullish input -- that guard exists precisely so an absent figure shows as
 * absent -- but `?? 0` converted the unknown into a confident `0` before the helper ever
 * saw it. Since `formatUsd(0)` renders `"$0"` for a genuinely measured zero, a dead
 * billing API and a real zero produced identical pixels: "Token spend $0" in 26px
 * semibold on a compliance console.
 *
 * This is the mirror image of the documented recurring defect. There, a guarded read
 * (`rec.floor != null`) silently rendered nothing. Here, a fallback silently renders
 * something. Both turn "unknown" into an answer.
 */

const USAGE: TenantUsageResponse = {
  tenant_id: "default",
  estimated_cost_usd: 0.0844,
  cost_per_call_usd: 0.00121,
  agent_calls: 70,
  avg_latency_ms: 13_690,
  cleared_by_rules: 2,
  cleared_by_ai: 0,
} as TenantUsageResponse;

function audit(outcome: string): ComplianceAuditResponse {
  return {
    audit_id: `A-${outcome}-${Math.random()}`,
    shipment_id: "VF-1",
    outcome,
    findings: [],
    effective_risk: 10,
  } as unknown as ComplianceAuditResponse;
}

/**
 * The stat tiles carry `hint` text through a radix Tooltip, which throws outside a
 * provider. Wrapping here rather than mocking the tooltip away, so the component under
 * test is the real one.
 */
function renderCards(props: React.ComponentProps<typeof KpiCards>) {
  return render(
    <TooltipPrimitive.Provider>
      <KpiCards {...props} />
    </TooltipPrimitive.Provider>,
  );
}

describe("KpiCards when the billing read fails", () => {
  const failed = { usageError: new Error("HTTP 502"), usage: undefined };

  it("does not render $0 for a spend it never measured", () => {
    renderCards({ audits: [audit("CLEARED")], loading: false, ...failed });
    // The assertion that matters. "$0" here is a claim about money.
    expect(screen.queryByText("$0")).toBeNull();
  });

  it("renders the absent sentinel instead", () => {
    renderCards({ audits: [audit("CLEARED")], loading: false, ...failed });
    expect(screen.getAllByText(NO_VALUE).length).toBeGreaterThan(0);
  });

  it("says the billing read failed rather than leaving the reader to infer it", () => {
    renderCards({ audits: [audit("CLEARED")], loading: false, ...failed });
    expect(screen.getByText(/not a measured zero/i)).toBeInTheDocument();
  });

  it("refuses to draw the clearance split rather than drawing an empty bar", () => {
    // An empty bar reads as "no automatic clearances", which is a claim about the
    // pipeline rather than about the request that failed.
    renderCards({ audits: [audit("CLEARED")], loading: false, ...failed });
    expect(
      screen.getByText(/rules-versus-model split cannot be shown/i),
    ).toBeInTheDocument();
  });
});

describe("KpiCards with real usage", () => {
  it("renders the measured spend", () => {
    renderCards({ audits: [audit("CLEARED")], usage: USAGE, loading: false });
    expect(screen.getByText("$0.0844")).toBeInTheDocument();
  });

  it("renders a genuinely measured zero as $0", () => {
    // The other half of the distinction: a real zero must still say $0, or the fix has
    // just moved the lie to the other side.
    renderCards({
      audits: [audit("CLEARED")],
      usage: { ...USAGE, estimated_cost_usd: 0 },
      loading: false,
    });
    expect(screen.getByText("$0")).toBeInTheDocument();
  });

  it("renders the mean latency in seconds", () => {
    renderCards({ audits: [audit("CLEARED")], usage: USAGE, loading: false });
    expect(screen.getByText("13.69 s")).toBeInTheDocument();
  });
});

describe("KpiCards while loading", () => {
  it("shows skeletons rather than zeroes", () => {
    const { container } = renderCards({
      audits: [],
      usage: undefined,
      loading: true,
    });
    expect(container.querySelectorAll('[data-slot="skeleton"]').length).toBeGreaterThan(0);
    expect(screen.queryByText("$0")).toBeNull();
  });
});
