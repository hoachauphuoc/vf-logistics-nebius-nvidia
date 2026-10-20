import { render, screen, within } from "@testing-library/react";
import { Tooltip as TooltipPrimitive } from "radix-ui";
import { describe, expect, it } from "vitest";

import { KpiCards } from "@/components/dashboard/KpiCards";
import { ApiError } from "@/lib/api";
import { NO_VALUE } from "@/lib/format";
import type { ComplianceAuditResponse, TenantUsageResponse } from "@/lib/types";

type Props = Parameters<typeof KpiCards>[0];

const USAGE: TenantUsageResponse = {
  tenant_id: "default",
  agent_calls: 70,
  input_tokens: 1000,
  output_tokens: 500,
  estimated_cost_usd: 0.0844,
  cost_per_call_usd: 0.00121,
  auto_cleared: 0,
  cleared_by_rules: 0,
  cleared_by_ai: 0,
  avg_latency_ms: 800,
};

function audit(outcome: string, findings: unknown[] = []): ComplianceAuditResponse {
  return {
    audit_id: `A-${outcome}`,
    shipment_id: "VF-1",
    outcome,
    findings,
    effective_risk: 10,
  } as never;
}

// A check that did not return an answer: its code ends in a suffix the component counts
// as unverified.
const UNVERIFIED = [{ code: "SCREEN_UNAVAILABLE" }];

function renderCards(props: Props) {
  return render(
    <TooltipPrimitive.Provider>
      <KpiCards {...props} />
    </TooltipPrimitive.Provider>,
  );
}

// The stat tile whose label is given. The label and the value share the card element.
function tile(label: string): HTMLElement {
  return screen.getByText(label).closest(".bento-card") as HTMLElement;
}

describe("KpiCards while loading", () => {
  it("shows placeholder skeletons in place of the stat tiles", () => {
    const { container } = renderCards({ audits: [], usage: undefined, loading: true });
    // Four cards with three skeleton lines each.
    expect(container.querySelectorAll('[data-slot="skeleton"]')).toHaveLength(12);
    expect(screen.queryByText("Blocked")).toBeNull();
  });
});

describe("KpiCards outcome counts", () => {
  it("counts blocked audits and shows the held and cleared figures beside them", () => {
    renderCards({
      audits: [audit("BLOCKED"), audit("BLOCKED"), audit("CLEARED")],
      usage: USAGE,
      loading: false,
    });
    expect(within(tile("Blocked")).getByText("2")).toBeInTheDocument();
    expect(screen.getByText("0 held for review · 1 cleared")).toBeInTheDocument();
  });

  it("counts held-for-review and pending-human audits together as held", () => {
    renderCards({
      audits: [audit("HELD_FOR_REVIEW"), audit("PENDING_HUMAN"), audit("CLEARED")],
      usage: USAGE,
      loading: false,
    });
    expect(within(tile("Blocked")).getByText("0")).toBeInTheDocument();
    expect(screen.getByText("2 held for review · 1 cleared")).toBeInTheDocument();
  });

  it("shows zero everywhere when there are no audits", () => {
    renderCards({ audits: [], usage: USAGE, loading: false });
    expect(within(tile("Blocked")).getByText("0")).toBeInTheDocument();
    expect(screen.getByText("0 held for review · 0 cleared")).toBeInTheDocument();
    expect(screen.getByText("0 of 0 audited cleared")).toBeInTheDocument();
  });

  it("uses the singular for a single audit that returned no verdict", () => {
    renderCards({ audits: [audit("ERROR")], usage: USAGE, loading: false });
    expect(screen.getByText("1 audit returned no verdict")).toBeInTheDocument();
  });

  it("uses the plural for several audits that returned no verdict", () => {
    renderCards({
      audits: [audit("ERROR"), audit("ERROR")],
      usage: USAGE,
      loading: false,
    });
    expect(screen.getByText("2 audits returned no verdict")).toBeInTheDocument();
  });
});

describe("KpiCards incomplete checks", () => {
  it("counts audits that have an unverified check and says how many of them cleared", () => {
    renderCards({
      audits: [
        audit("CLEARED", UNVERIFIED),
        audit("BLOCKED", UNVERIFIED),
        audit("CLEARED", []),
      ],
      usage: USAGE,
      loading: false,
    });
    expect(within(tile("Incomplete checks")).getByText("2")).toBeInTheDocument();
    expect(screen.getByText("1 of them cleared anyway")).toBeInTheDocument();
  });

  it("reports zero cleared anyway when every audit with a gap was blocked", () => {
    renderCards({
      audits: [audit("BLOCKED", UNVERIFIED)],
      usage: USAGE,
      loading: false,
    });
    expect(screen.getByText("0 of them cleared anyway")).toBeInTheDocument();
  });

  it("says every check returned a verdict when no audit has a gap", () => {
    renderCards({ audits: [audit("CLEARED", [])], usage: USAGE, loading: false });
    expect(within(tile("Incomplete checks")).getByText("0")).toBeInTheDocument();
    expect(screen.getByText("every check returned a verdict")).toBeInTheDocument();
  });

  it("makes the incomplete checks tile focusable because it carries an explanation", () => {
    renderCards({ audits: [], usage: USAGE, loading: false });
    expect(tile("Incomplete checks")).toHaveAttribute("tabindex", "0");
  });

  it("keeps the blocked tile out of the tab order because it has no explanation", () => {
    renderCards({ audits: [], usage: USAGE, loading: false });
    expect(tile("Blocked")).not.toHaveAttribute("tabindex");
  });
});

describe("KpiCards spend and latency", () => {
  it("shows the cost per call and the number of agent calls under the spend figure", () => {
    renderCards({ audits: [], usage: USAGE, loading: false });
    expect(within(tile("Estimated spend")).getByText("$0.0844")).toBeInTheDocument();
    expect(
      screen.getByText("$0.00121 per agent call · 70 calls"),
    ).toBeInTheDocument();
  });

  it("renders a latency under one second in milliseconds", () => {
    renderCards({ audits: [], usage: USAGE, loading: false });
    expect(within(tile("Mean latency")).getByText("800 ms")).toBeInTheDocument();
  });

  it("shows the absent sentinel for spend and latency before usage has arrived", () => {
    renderCards({ audits: [], usage: undefined, loading: false });
    expect(within(tile("Estimated spend")).getByText(NO_VALUE)).toBeInTheDocument();
    expect(within(tile("Mean latency")).getByText(NO_VALUE)).toBeInTheDocument();
    expect(
      screen.getByText(`${NO_VALUE} per agent call · ${NO_VALUE} calls`),
    ).toBeInTheDocument();
  });

  it("names the role for a 401 refusal as well as a 403", () => {
    renderCards({
      audits: [audit("CLEARED")],
      usage: undefined,
      loading: false,
      usageError: new ApiError("Unauthorized", 401, "http", null),
    });
    expect(screen.getAllByText(/needs the operator role/i).length).toBeGreaterThan(0);
    expect(screen.queryByText(/billing read failed/i)).toBeNull();
  });

  it("reports a server error as a failed billing read rather than a role refusal", () => {
    renderCards({
      audits: [audit("CLEARED")],
      usage: undefined,
      loading: false,
      usageError: new ApiError("Server error", 500, "http", null),
    });
    expect(screen.getAllByText(/not a measured zero/i).length).toBeGreaterThan(0);
    expect(screen.queryByText(/needs the/i)).toBeNull();
  });
});

describe("KpiCards clearance split", () => {
  it("shows the empty-window sentence when nothing was cleared", () => {
    renderCards({ audits: [audit("BLOCKED")], usage: USAGE, loading: false });
    expect(screen.getByText("No clearances in this window.")).toBeInTheDocument();
  });

  it("says every clearance went through a reviewer when none were automatic", () => {
    renderCards({
      audits: [audit("CLEARED"), audit("CLEARED")],
      usage: USAGE,
      loading: false,
    });
    expect(
      screen.getByText(
        "No automatic clearances. All 2 went through a reviewer, which is the expensive path in staff time even where it is free in tokens.",
      ),
    ).toBeInTheDocument();
  });

  it("splits automatic clearances between deterministic rules and the model layer", () => {
    renderCards({
      audits: [audit("CLEARED"), audit("CLEARED"), audit("CLEARED"), audit("CLEARED")],
      usage: { ...USAGE, cleared_by_rules: 3, cleared_by_ai: 1 },
      loading: false,
    });
    expect(screen.getByText(/by deterministic rules/)).toHaveTextContent(
      "3 by deterministic rules",
    );
    expect(screen.getByText(/after the model layer/)).toHaveTextContent(
      "1 after the model layer",
    );
    expect(screen.getByText("4 of 4 audited cleared")).toBeInTheDocument();
  });

  it("draws the bar in proportion to the rules and model split", () => {
    const { container } = renderCards({
      audits: [audit("CLEARED"), audit("CLEARED"), audit("CLEARED"), audit("CLEARED")],
      usage: { ...USAGE, cleared_by_rules: 3, cleared_by_ai: 1 },
      loading: false,
    });
    const bar = container.querySelector<HTMLElement>(".h-2");
    expect(bar?.children[0]).toHaveStyle({ width: "75%" });
    expect(bar?.children[1]).toHaveStyle({ width: "25%" });
  });

  it("reports reviewer releases separately from the automatic split", () => {
    renderCards({
      audits: [audit("CLEARED"), audit("CLEARED"), audit("CLEARED")],
      usage: { ...USAGE, cleared_by_rules: 1, cleared_by_ai: 1 },
      loading: false,
    });
    expect(
      screen.getByText("3 of 3 audited cleared, 2 of them automatically"),
    ).toBeInTheDocument();
    expect(screen.getByText(/released by a reviewer/)).toHaveTextContent(
      "1 released by a reviewer",
    );
  });

  it("omits the reviewer figure when every clearance was automatic", () => {
    renderCards({
      audits: [audit("CLEARED"), audit("CLEARED")],
      usage: { ...USAGE, cleared_by_rules: 2 },
      loading: false,
    });
    expect(screen.getByText("2 of 2 audited cleared")).toBeInTheDocument();
    expect(screen.queryByText(/released by a reviewer/)).toBeNull();
  });

  it("never counts more automatic clearances than were actually cleared", () => {
    renderCards({
      audits: [audit("CLEARED")],
      usage: { ...USAGE, cleared_by_rules: 2 },
      loading: false,
    });
    // One audit cleared, so no reviewer releases, and the bar is filled by the
    // automatic figure alone.
    expect(screen.getByText("1 of 1 audited cleared")).toBeInTheDocument();
    expect(screen.queryByText(/released by a reviewer/)).toBeNull();
  });
});

describe("KpiCards outcome donut", () => {
  it("draws the outcome donut when there are audits", () => {
    const { container } = renderCards({
      audits: [audit("BLOCKED")],
      usage: USAGE,
      loading: false,
    });
    expect(container.querySelector('div[style*="width: 80px"]')).not.toBeNull();
  });

  it("omits the donut when there are no audits", () => {
    const { container } = renderCards({ audits: [], usage: USAGE, loading: false });
    expect(container.querySelector('div[style*="width: 80px"]')).toBeNull();
  });

  it("omits the donut when no audit has an outcome the chart plots", () => {
    const { container } = renderCards({
      audits: [audit("SOMETHING_NEW")],
      usage: USAGE,
      loading: false,
    });
    expect(container.querySelector('div[style*="width: 80px"]')).toBeNull();
  });
});
