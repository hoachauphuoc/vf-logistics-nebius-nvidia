import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import type { ComplianceAuditResponse, TenantUsageResponse } from "@/lib/types";

const mocks = vi.hoisted(() => ({
  fetchAudits: vi.fn(),
  fetchUsage: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  fetchAudits: mocks.fetchAudits,
  fetchUsage: mocks.fetchUsage,
}));
vi.mock("@/lib/tenant-context", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/tenant-context")>()),
  useTenant: () => ({ tenant: { id: "tenant-a", name: "Tenant A", descriptor: "Test tenant" } }),
}));
vi.mock("@/lib/identity", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/identity")>()),
  useIdentity: () => ({ data: undefined, isError: false }),
}));

import RiskRadarPage from "./page";

// Radix measures floating content with ResizeObserver, which jsdom does not provide.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

function makeAudit(overrides: Partial<ComplianceAuditResponse> = {}): ComplianceAuditResponse {
  return {
    audit_id: "audit-1",
    case_id: "CASE-1",
    shipment_id: "SHP-100",
    client_reference: "ACME-REF",
    outcome: "BLOCKED",
    effective_risk: 90,
    model_risk: 85,
    risk_floor: 80,
    score_disputed: false,
    findings: [
      {
        code: "SANCTIONS_HIT",
        severity: "CRITICAL",
        detail: "List match",
        floor: 80,
        source_entity_ids: ["OFAC-1"],
      },
    ],
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

const CLEARED_AUDIT = makeAudit({
  audit_id: "audit-2",
  case_id: "CASE-2",
  shipment_id: "SHP-200",
  client_reference: null,
  outcome: "CLEARED",
  effective_risk: 10,
  risk_floor: 0,
  findings: [],
});

const USAGE: TenantUsageResponse = {
  tenant_id: "tenant-a",
  agent_calls: 7,
  input_tokens: 0,
  output_tokens: 0,
  estimated_cost_usd: 1.5,
  cost_per_call_usd: 0.25,
  auto_cleared: 0,
  cleared_by_rules: 0,
  cleared_by_ai: 0,
  avg_latency_ms: 1200,
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <RiskRadarPage />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("Risk Radar page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("ResizeObserver", ResizeObserverStub);
    mocks.fetchAudits.mockResolvedValue([makeAudit(), CLEARED_AUDIT]);
    mocks.fetchUsage.mockResolvedValue(USAGE);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows a loading state while the audits and usage are still being read", () => {
    mocks.fetchAudits.mockReturnValue(new Promise(() => {}));
    mocks.fetchUsage.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByText("loading…")).toBeInTheDocument();
    expect(screen.getByText("Completed audits")).toBeInTheDocument();
  });

  it("names the selected tenant in the heading", async () => {
    renderPage();
    expect(await screen.findByRole("button", { name: "Open audit for SHP-100" })).toBeInTheDocument();
    expect(screen.getByText("Tenant A")).toBeInTheDocument();
  });

  it("lists every audit the API returned and counts them", async () => {
    renderPage();
    expect(await screen.findByRole("button", { name: "Open audit for SHP-100" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open audit for SHP-200" })).toBeInTheDocument();
    expect(screen.getByText("2 declarations")).toBeInTheDocument();
  });

  it("summarises the held and cleared outcomes in the blocked card", async () => {
    renderPage();
    expect(await screen.findByText("0 held for review · 1 cleared")).toBeInTheDocument();
  });

  it("reports that the single clearance went through a reviewer when no check cleared automatically", async () => {
    renderPage();
    expect(
      await screen.findByText(/No automatic clearances\. All 1 went through a reviewer/),
    ).toBeInTheDocument();
    expect(screen.getByText(/1 of 2 audited cleared/)).toBeInTheDocument();
  });

  it("shows the agent call count and per-call cost once billing answers", async () => {
    renderPage();
    expect(await screen.findByText(/per agent call · 7 calls/)).toBeInTheDocument();
  });

  it("says the spend is not a measured zero when the billing read fails", async () => {
    mocks.fetchUsage.mockRejectedValue(new Error("billing down"));
    renderPage();
    expect(await screen.findByText("Billing read failed — this is not a measured zero")).toBeInTheDocument();
    expect(screen.getByText(/The billing read failed, so the rules-versus-model split/)).toBeInTheDocument();
  });

  it("shows an error instead of an empty table when the audits cannot be read", async () => {
    mocks.fetchAudits.mockRejectedValue(new Error("gateway timeout"));
    renderPage();
    expect(await screen.findByText("Could not load audits.")).toBeInTheDocument();
    expect(screen.getByText("gateway timeout")).toBeInTheDocument();
    expect(screen.queryByText("No declarations in this window.")).not.toBeInTheDocument();
  });

  it("says there are no declarations when the window is empty", async () => {
    mocks.fetchAudits.mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText("No declarations in this window.")).toBeInTheDocument();
    expect(screen.getByText("0 declarations")).toBeInTheDocument();
  });

  it("keeps the detail sheet closed until an audit row is chosen", async () => {
    renderPage();
    expect(await screen.findByRole("button", { name: "Open audit for SHP-100" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens the detail sheet for the audit whose row was clicked", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Open audit for SHP-100" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("SHP-100")).toBeInTheDocument();
    expect(within(dialog).getByText("ACME-REF · CASE-1")).toBeInTheDocument();
    expect(within(dialog).getByText("List match")).toBeInTheDocument();
  });

  it("closes the detail sheet when Escape is pressed", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Open audit for SHP-100" }));
    await screen.findByRole("dialog");
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("shows the newly chosen audit, not the previous one, when the sheet is reopened", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Open audit for SHP-100" }));
    await screen.findByRole("dialog");
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Open audit for SHP-200" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("CASE-2")).toBeInTheDocument();
    expect(within(dialog).queryByText("SHP-100")).not.toBeInTheDocument();
  });
});
