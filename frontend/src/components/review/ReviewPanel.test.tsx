import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Tooltip as TooltipPrimitive } from "radix-ui";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  reevaluateCase: vi.fn(async () => ({ state: "HELD_FOR_REVIEW" })),
  approveCase: vi.fn(async () => ({ approval: { approval_id: "evapr-9" }, state: "APPROVED" })),
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

import { approveCase, cancelEvidenceRequest, decideReview, executeApproval, reevaluateCase, requestEvidence } from "@/lib/api";
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

  it.each(["AWAITING_EVIDENCE", "HELD_FOR_REVIEW", "ESCALATED", "PENDING_HUMAN"])(
    "offers Re-evaluate for a verification case in %s and calls it",
    async (state) => {
      const onDecided = renderPanel(makeCase(state));
      fireEvent.click(screen.getByRole("button", { name: "Re-evaluate" }));
      await waitFor(() => expect(reevaluateCase).toHaveBeenCalledWith("CASE-1"));
      await waitFor(() => expect(onDecided).toHaveBeenCalled());
    },
  );

  it.each(["RELEASED_BY_HUMAN", "BLOCKED_BY_HUMAN", "APPROVED", "EXECUTING", "EXECUTION_FAILED"])(
    "does not offer Re-evaluate once the case is %s (the API answers 409 there)",
    (state) => {
      renderPanel(makeCase(state));
      expect(screen.queryByRole("button", { name: "Re-evaluate" })).toBeNull();
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
    // Full addresses a reviewer can paste into an email, not bare paths.
    const origin = window.location.origin;
    expect(banner.textContent).toContain(`certificate_of_origin: ${origin}/respond/cert-token`);
    expect(banner.textContent).toContain(`producer_declaration: ${origin}/respond/decl-token`);
  });

  it("shows the request-level link as a full address when the API sends no per-document links", async () => {
    vi.mocked(requestEvidence).mockResolvedValueOnce({ path: "/respond/request-level" });
    renderPanel(makeCase("HELD_FOR_REVIEW"));
    fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: "need papers" } });
    fireEvent.click(screen.getByRole("button", { name: "Request info" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    const banner = await screen.findByTestId("evidence-links");
    expect(banner.textContent).toContain(`${window.location.origin}/respond/request-level`);
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

  it("reloads the case when approve-then-execute ends in EXECUTION_FAILED, so Retry can appear", async () => {
    const onDecided = renderPanel(makeCase("HELD_FOR_REVIEW"));
    fireEvent.click(screen.getByRole("button", { name: "Release" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(executeApproval).toHaveBeenCalledWith("CASE-1", "evapr-9"));
    await waitFor(() => expect(onDecided).toHaveBeenCalledTimes(1));
    expect((await screen.findByRole("alert")).textContent).toMatch(/execution failed/i);
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


const THREE_DOCS = ["certificate_of_origin", "producer_declaration", "input_purchase_invoices"];

function evaluated(state: string, evaluation: Record<string, unknown>, extra: Record<string, unknown> = {}): Case {
  return makeCase(state, {
    evidence_version: 3,
    evaluations: [{
      evaluation_id: "eveval-1", evidence_version: 3, at: "2026-10-14T04:16:54Z", risk_floor: 45,
      status: "provided", clarified: THREE_DOCS, unresolved: [], contradictions: [], ...evaluation,
    }],
    ...extra,
  });
}

const CONTRADICTED = {
  status: "contradicted", risk_floor: 80,
  contradictions: [{
    kind: "input_origin",
    detail: "An input purchase invoice is for China-origin goods from Linyi Veneer Co., Ltd.",
  }],
};

describe("ReviewPanel shows what the papers said", () => {
  beforeEach(() => vi.clearAllMocks());

  it("names the contradiction and its paper in the evidence check", () => {
    renderPanel(evaluated("ESCALATED", CONTRADICTED));
    const check = screen.getByTestId("evidence-check");
    expect(check.textContent).toMatch(/Evidence check\s*·\s*v3\s*·\s*contradicted/);
    expect(check.textContent).toContain("floor 80");
    expect(check.textContent).toContain("Origin of the inputs:");
    expect(check.textContent).toContain("An input purchase invoice is for China-origin goods from Linyi Veneer Co., Ltd.");
  });

  it("explains that good papers do not lower the floor, and shows no warning", () => {
    renderPanel(evaluated("HELD_FOR_REVIEW", { status: "provided", risk_floor: 45 }));
    const check = screen.getByTestId("evidence-check");
    expect(check.textContent).toMatch(/consistent with the declared origin/);
    expect(check.textContent).toMatch(/floor stays at 45/);
    expect(screen.queryByTestId("contradiction-warning")).toBeNull();
  });

  it("lists what is still missing", () => {
    renderPanel(evaluated("HELD_FOR_REVIEW", { status: "missing", unresolved: ["producer_declaration"], clarified: [] }));
    expect(screen.getByTestId("evidence-check").textContent).toMatch(/Still missing or unreadable:\s*Producer declaration/);
  });

  it("shows nothing for an evaluation that predates the latest papers", () => {
    // v4 has arrived since the v3 evaluation, so v3's verdict is not the case's state.
    renderPanel(evaluated("HELD_FOR_REVIEW", CONTRADICTED, { evidence_version: 4 }));
    expect(screen.queryByTestId("evidence-check")).toBeNull();
    expect(screen.queryByTestId("contradiction-warning")).toBeNull();
  });

  it("shows nothing before anything has been evaluated", () => {
    renderPanel(makeCase("HELD_FOR_REVIEW"));
    expect(screen.queryByTestId("evidence-check")).toBeNull();
  });
});

describe("ReviewPanel: releasing against contradicting papers (Rev2 C3)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("warns above the buttons and says blocking is the expected action", () => {
    renderPanel(evaluated("ESCALATED", CONTRADICTED));
    const warning = screen.getByTestId("contradiction-warning");
    expect(warning.textContent).toMatch(/contradict the declared origin/);
    expect(warning.textContent).toMatch(/Blocking is the expected action/);
  });

  it("will not open the release confirmation without a reason", async () => {
    renderPanel(evaluated("ESCALATED", CONTRADICTED));
    fireEvent.click(screen.getByRole("button", { name: "Release" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/reason is required to release/i);
    expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();
    expect(approveCase).not.toHaveBeenCalled();
  });

  it("releases with a reason, after a confirmation that says it is an exception", async () => {
    renderPanel(evaluated("ESCALATED", CONTRADICTED));
    fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: "Certificate misread; checked the original" } });
    fireEvent.click(screen.getByRole("button", { name: "Release" }));
    expect((await screen.findByTestId("contradiction-confirm")).textContent).toMatch(/recorded as an exception/);
    expect(approveCase).not.toHaveBeenCalled(); // nothing is sent before Confirm
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() =>
      expect(approveCase).toHaveBeenCalledWith("CASE-1", "release", "Certificate misread; checked the original"),
    );
  });

  it("still needs a note to block, as before", async () => {
    renderPanel(evaluated("ESCALATED", CONTRADICTED));
    fireEvent.click(screen.getByRole("button", { name: "Block" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/note is required to block/i);
  });

  it("leaves a clean release as it was: no warning, no reason needed, a plain confirmation", async () => {
    renderPanel(evaluated("HELD_FOR_REVIEW", { status: "provided", risk_floor: 45 }));
    expect(screen.queryByTestId("contradiction-warning")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Release" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    expect(screen.queryByTestId("contradiction-confirm")).toBeNull();
    await waitFor(() => expect(approveCase).toHaveBeenCalledWith("CASE-1", "release", ""));
  });
});

describe("ReviewPanel: a partial re-evaluate leaves the request open (Rev2 N04)", () => {
  beforeEach(() => vi.clearAllMocks());

  const partial = (state: string) =>
    makeCase(state, {
      requests: [{
        request_id: "evreq-1", status: "SENT", documents: THREE_DOCS, owner: "", created_at: "",
        received_docs: { certificate_of_origin: "d1", producer_declaration: "d2" },
      }],
    });

  it("says why Release and Block are refused, and offers Cancel request, outside AWAITING_EVIDENCE", async () => {
    renderPanel(partial("HELD_FOR_REVIEW"));
    expect(screen.getByTestId("open-request-hint").textContent).toMatch(/2 of 3 received/);
    expect(screen.getByTestId("open-request-hint").textContent).toMatch(/cancel the request/);
    fireEvent.click(screen.getByRole("button", { name: "Cancel request" }));
    await waitFor(() =>
      expect(cancelEvidenceRequest).toHaveBeenCalledWith("CASE-1", "evreq-1", expect.any(String)),
    );
  });

  it("does not repeat the hint while the case is waiting for documents anyway", () => {
    renderPanel(partial("AWAITING_EVIDENCE"));
    expect(screen.queryByTestId("open-request-hint")).toBeNull();
    expect(screen.getByRole("button", { name: "Cancel request" })).toBeTruthy();
  });

  it("shows no hint once the request is closed", () => {
    renderPanel(makeCase("HELD_FOR_REVIEW", {
      requests: [{ request_id: "evreq-1", status: "RECEIVED", documents: THREE_DOCS, owner: "", created_at: "" }],
    }));
    expect(screen.queryByTestId("open-request-hint")).toBeNull();
    expect(screen.queryByRole("button", { name: "Cancel request" })).toBeNull();
  });
});
