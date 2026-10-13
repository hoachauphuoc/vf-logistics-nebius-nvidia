import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Tooltip as TooltipPrimitive } from "radix-ui";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  reevaluateCase: vi.fn(async () => ({ state: "HELD_FOR_REVIEW" })),
  requestEvidence: vi.fn(async () => ({
    path: "/respond/request-level",
    links: [
      { doc_type: "certificate_of_origin", path: "/respond/cert-token" },
      { doc_type: "producer_declaration", path: "/respond/decl-token" },
    ],
  })),
  executeApproval: vi.fn(async () => ({ state: "EXECUTION_FAILED" })),
  decideReview: vi.fn(async () => ({ ok: true, state: "PENDING_HUMAN" })),
  cancelEvidenceRequest: vi.fn(async () => ({ state: "HELD_FOR_REVIEW" })),
}));
vi.mock("@/lib/identity", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/identity")>()),
  useIdentity: () => ({
    data: {
      email: "reviewer@forwarder.example",
      authenticated_by: "console_session",
      acts_for_a_person: true,
      role: "reviewer",
      roles: ["reviewer"],
      grants: ["viewer", "reviewer"],
      role_source: "test",
      tenant_id: null,
      session_method: "password",
    },
  }),
}));

import { cancelEvidenceRequest, decideReview, executeApproval, reevaluateCase, requestEvidence } from "@/lib/api";
import type { Case } from "@/lib/types";

import { ReviewPanel } from "./ReviewPanel";

/**
 * Rev2 N08: the verification loop was reachable from the API but not from the
 * panel -- no Re-evaluate, the request link never shown, no way to cancel,
 * execute or retry. Each test below is one of those gaps.
 */

function makeCase(state: string, verification: Record<string, unknown> | null = {}): Case {
  return {
    case_id: "CASE-1",
    shipment_id: "CASE-1",
    state,
    verification: verification === null ? null : {
      evidence_version: 1,
      requests: [],
      documents: [],
      evaluations: [],
      approvals: [],
      ...verification,
    },
  } as unknown as Case;
}

function renderPanel(c: Case, onDecided = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipPrimitive.Provider>
        <ReviewPanel
          summary={c}
          detail={c}
          detailLoading={false}
          detailError={null}
          onDecided={onDecided}
        />
      </TooltipPrimitive.Provider>
    </QueryClientProvider>,
  );
  return onDecided;
}

describe("ReviewPanel verification actions", () => {
  beforeEach(() => vi.clearAllMocks());

  it.each(["AWAITING_EVIDENCE", "HELD_FOR_REVIEW"])(
    "offers Re-evaluate for a verification case in %s and calls it",
    async (state) => {
      const onDecided = renderPanel(makeCase(state));
      fireEvent.click(screen.getByRole("button", { name: "Re-evaluate" }));
      await waitFor(() => expect(reevaluateCase).toHaveBeenCalledWith("CASE-1"));
      await waitFor(() => expect(onDecided).toHaveBeenCalled());
    },
  );

  it("does not offer Re-evaluate for a case with no verification record", () => {
    renderPanel(makeCase("HELD_FOR_REVIEW", null));
    expect(screen.queryByRole("button", { name: "Re-evaluate" })).toBeNull();
  });

  it("shows the per-document links after Request info", async () => {
    renderPanel(makeCase("HELD_FOR_REVIEW"));
    fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: "need papers" } });
    fireEvent.click(screen.getByRole("button", { name: "Request info" }));
    // Nothing is sent before the confirmation.
    expect(requestEvidence).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    const banner = await screen.findByTestId("evidence-links");
    expect(banner.textContent).toContain("certificate_of_origin: /respond/cert-token");
    expect(banner.textContent).toContain("producer_declaration: /respond/decl-token");
  });

  it("says it is waiting for the shipper and offers Cancel while awaiting evidence", async () => {
    renderPanel(makeCase("AWAITING_EVIDENCE", {
      requests: [{ request_id: "evreq-1", status: "SENT", documents: [], owner: "", created_at: "" }],
    }));
    expect(screen.getByTestId("state-hint").textContent).toMatch(/Waiting for the shipper/);
    fireEvent.click(screen.getByRole("button", { name: "Cancel request" }));
    await waitFor(() =>
      expect(cancelEvidenceRequest).toHaveBeenCalledWith("CASE-1", "evreq-1", expect.any(String)),
    );
  });

  it("offers Retry, and says so, when execution failed", async () => {
    renderPanel(makeCase("EXECUTION_FAILED", {
      approvals: [{ approval_id: "evapr-1", action: "release", approver: "r", evidence_version: 1, status: "VALID", at: "" }],
    }));
    expect(screen.getByTestId("state-hint").textContent).toMatch(/Execution failed/);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(executeApproval).toHaveBeenCalledWith("CASE-1", "evapr-1"));
    expect(await screen.findByRole("alert")).toBeTruthy();
  });

  it("offers Execute for an approved case", () => {
    renderPanel(makeCase("APPROVED", {
      approvals: [{ approval_id: "evapr-1", action: "release", approver: "r", evidence_version: 1, status: "VALID", at: "" }],
    }));
    expect(screen.getByRole("button", { name: "Execute" })).toBeTruthy();
  });

  it("starts the verification loop on a fresh case whose finding asks for documents", async () => {
    // Found in a browser run: the first Request info went to the legacy decide.
    const fresh = {
      ...makeCase("HELD_FOR_REVIEW", null),
      validation: { findings: [{
        code: "ORIGIN_INPUTS_UNVERIFIED", severity: "MEDIUM", detail: "d", floor: 45,
        source_entity_ids: [], measured: { documents_needed: ["certificate_of_origin"] },
      }] },
    } as unknown as Case;
    renderPanel(fresh);
    fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: "need papers" } });
    fireEvent.click(screen.getByRole("button", { name: "Request info" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(requestEvidence).toHaveBeenCalledWith("CASE-1"));
    expect(decideReview).not.toHaveBeenCalled();
  });

  it("keeps the legacy request for a case with nothing to ask documents for", async () => {
    renderPanel(makeCase("HELD_FOR_REVIEW", null));
    fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: "call the shipper" } });
    fireEvent.click(screen.getByRole("button", { name: "Request info" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(decideReview).toHaveBeenCalled());
    expect(requestEvidence).not.toHaveBeenCalled();
  });
});
