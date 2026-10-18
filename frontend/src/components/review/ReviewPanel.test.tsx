import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Tooltip as TooltipPrimitive } from "radix-ui";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  reevaluateCase: vi.fn(async () => ({ state: "HELD_FOR_REVIEW" })),
  approveCase: vi.fn(async () => ({ approval: { approval_id: "evapr-9" }, state: "APPROVED" })),
  approveException: vi.fn(async () => ({ approval: { approval_id: "evapr-9" }, state: "APPROVED" })),
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
const identityGrants = vi.hoisted(() => ({ list: ["viewer", "reviewer", "operator"] }));
vi.mock("@/lib/identity", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/identity")>()),
  useIdentity: () => ({
    data: {
      email: "reviewer@forwarder.example",
      authenticated_by: "console_session",
      acts_for_a_person: true,
      role: "reviewer",
      roles: ["reviewer"],
      grants: identityGrants.list,
      role_source: "test",
      tenant_id: null,
      session_method: "password",
    },
  }),
}));

import { ApiError, approveCase, approveException, cancelEvidenceRequest, decideReview, executeApproval, reevaluateCase, requestEvidence } from "@/lib/api";
import { type Case, VERIFICATION_LOOP_STATES } from "@/lib/types";

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
    expect(approveException).not.toHaveBeenCalled(); // nothing is sent before Confirm
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() =>
      expect(approveException).toHaveBeenCalledWith("CASE-1", "Certificate misread; checked the original", ["contradiction:input_origin"]),
    );
    expect(approveCase).not.toHaveBeenCalled();
  });

  it("releases over an unresolved paper through the exception operation, naming it", async () => {
    renderPanel(evaluated("HELD_FOR_REVIEW", { status: "missing", unresolved: ["producer_declaration"], clarified: [] }));
    fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: "Verified by phone" } });
    fireEvent.click(screen.getByRole("button", { name: "Release" }));
    expect((await screen.findByTestId("exception-confirm")).textContent).toMatch(/recorded as an exception/);
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() =>
      expect(approveException).toHaveBeenCalledWith("CASE-1", "Verified by phone", ["producer_declaration"]),
    );
    expect(approveCase).not.toHaveBeenCalled();
  });

  it("will not open the release confirmation over an unresolved paper without a reason", async () => {
    renderPanel(evaluated("HELD_FOR_REVIEW", { status: "missing", unresolved: ["producer_declaration"], clarified: [] }));
    fireEvent.click(screen.getByRole("button", { name: "Release" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/reason is required to release over unresolved or contradicting evidence/i);
    expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();
    expect(approveException).not.toHaveBeenCalled();
    expect(approveCase).not.toHaveBeenCalled();
  });

  it("tells a reviewer without the operator role that an exception needs it, and sends nothing", async () => {
    identityGrants.list = ["viewer", "reviewer"];
    try {
      renderPanel(evaluated("ESCALATED", CONTRADICTED));
      fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: "Certificate misread; checked the original" } });
      fireEvent.click(screen.getByRole("button", { name: "Release" }));
      expect((await screen.findByRole("alert")).textContent).toMatch(/Needs the Operator role/);
      expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();
      expect(approveException).not.toHaveBeenCalled();
      expect(approveCase).not.toHaveBeenCalled();
    } finally {
      identityGrants.list = ["viewer", "reviewer", "operator"];
    }
  });

  it("a block over contradicting papers still goes through approveCase", async () => {
    renderPanel(evaluated("ESCALATED", CONTRADICTED));
    fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: "Papers contradict the declaration" } });
    fireEvent.click(screen.getByRole("button", { name: "Block" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    await waitFor(() =>
      expect(approveCase).toHaveBeenCalledWith("CASE-1", "block", "Papers contradict the declaration"),
    );
    expect(approveException).not.toHaveBeenCalled();
  });

  it("sends nothing when the reviewer cancels the confirmation (Release, then Cancel)", async () => {
    renderPanel(evaluated("HELD_FOR_REVIEW", { status: "provided", risk_floor: 45 }));
    fireEvent.click(screen.getByRole("button", { name: "Release" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull());
    expect(approveCase).not.toHaveBeenCalled();
    expect(executeApproval).not.toHaveBeenCalled();
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


/**
 * N08-B display: an EXECUTING case is either being worked on (the claim's lease is
 * still running) or interrupted (the lease has run out, so evidence.execute_approval
 * would resume it). The panel says which, from data the case already carries.
 * `claim_expires_epoch` is Unix SECONDS, as the backend writes it.
 */
function executing(claimExpiresEpoch?: number): Case {
  return makeCase("EXECUTING", {
    approvals: [
      { approval_id: "evapr-1", action: "release", approver: "r", evidence_version: 1, status: "CLAIMING", at: "" },
    ],
    executions: [
      {
        execution_id: "evexe-1", approval_id: "evapr-1", executor: "r", status: "claiming", at: "",
        ...(claimExpiresEpoch === undefined ? {} : { claim_expires_epoch: claimExpiresEpoch }),
      },
    ],
  });
}

const inSeconds = (s: number) => Math.floor(Date.now() / 1000) + s;

describe("ReviewPanel: an execution in flight or interrupted (N08-B)", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.useRealTimers());

  it("says the execution is in progress while the claim's lease is still running", () => {
    renderPanel(executing(inSeconds(300)));
    const hint = screen.getByTestId("state-hint").textContent ?? "";
    expect(hint).toMatch(/Execution in progress/);
    expect(hint).not.toMatch(/interrupted/);
  });

  it("says the execution is interrupted once the lease has expired", () => {
    renderPanel(executing(inSeconds(-60)));
    const hint = screen.getByTestId("state-hint").textContent ?? "";
    expect(hint).toMatch(/Execution interrupted - claim expired/);
    expect(hint).not.toMatch(/in progress/);
  });

  it("treats a claim with no recorded expiry as expired, as the backend does", () => {
    renderPanel(executing(undefined));
    expect(screen.getByTestId("state-hint").textContent).toMatch(/Execution interrupted - claim expired/);
  });

  it("does not call an EXECUTING case interrupted when there is no claim to read", () => {
    renderPanel(makeCase("EXECUTING"));
    expect(screen.getByTestId("state-hint").textContent).toMatch(/Execution in progress/);
  });

  it.each([
    ["running", 300],
    ["expired", -60],
  ])("offers no Execute, Retry or decision button for an EXECUTING case whose lease is %s", (_label, offset) => {
    renderPanel(executing(inSeconds(offset)));
    for (const name of ["Execute", "Retry", "Release", "Block", "Request info", "Re-evaluate"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
  });

  it("moves from in progress to interrupted when the lease runs out while the page is open", () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(new Date("2026-10-15T10:00:00Z"));
    renderPanel(executing(Math.floor(Date.now() / 1000) + 20));
    expect(screen.getByTestId("state-hint").textContent).toMatch(/Execution in progress/);
    act(() => {
      vi.advanceTimersByTime(30_000);
    });
    expect(screen.getByTestId("state-hint").textContent).toMatch(/Execution interrupted - claim expired/);
  });

  it("lets the case page mount the panel for an EXECUTING case", () => {
    // The page shows "Nobody owes this case anything" instead of the panel for any
    // state this list lacks.
    expect(VERIFICATION_LOOP_STATES).toContain("EXECUTING");
  });
});


/**
 * N08-B action: Resume continues an interrupted execution -- a CLAIMING approval on
 * an EXECUTING case whose claim has expired -- through the same executeApproval call
 * as Execute and Retry. The button is a hint that the lease is over; the backend stays
 * the authority and answers 409 while the claim is still live.
 */
describe("ReviewPanel: resuming an interrupted execution (N08-B)", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.useRealTimers());

  it("offers Resume, and calls executeApproval with the claimed approval, once the claim has expired", async () => {
    vi.mocked(executeApproval).mockResolvedValueOnce({ state: "RELEASED_BY_HUMAN" });
    const onDecided = renderPanel(executing(inSeconds(-60)));
    expect(screen.getByTestId("state-hint").textContent).toMatch(/Resume continues it/);
    fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    await waitFor(() => expect(executeApproval).toHaveBeenCalledWith("CASE-1", "evapr-1"));
    await waitFor(() => expect(onDecided).toHaveBeenCalled());
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("offers Resume for a claim with no recorded expiry", () => {
    renderPanel(executing(undefined));
    expect(screen.getByRole("button", { name: "Resume" })).toBeTruthy();
  });

  it("does not offer Resume while the claim's lease is still running", () => {
    renderPanel(executing(inSeconds(300)));
    expect(screen.queryByRole("button", { name: "Resume" })).toBeNull();
    expect(executeApproval).not.toHaveBeenCalled();
  });

  it("does not offer Resume for an EXECUTING case with no claim to read", () => {
    renderPanel(makeCase("EXECUTING"));
    expect(screen.queryByRole("button", { name: "Resume" })).toBeNull();
  });

  it.each(["APPROVED", "EXECUTION_FAILED", "HELD_FOR_REVIEW", "RELEASED_BY_HUMAN"])(
    "does not offer Resume on a %s case, whatever its approvals say",
    (state) => {
      const stale = executing(inSeconds(-60));
      renderPanel({ ...stale, state } as unknown as Case);
      expect(screen.queryByRole("button", { name: "Resume" })).toBeNull();
    },
  );

  it("shows the backend's refusal when the claim is still live there", async () => {
    const refusal =
      "Another execution of this approval is in progress. Try again after it finishes or its claim expires.";
    vi.mocked(executeApproval).mockRejectedValueOnce(new ApiError(refusal, 409, "http"));
    const onDecided = renderPanel(executing(inSeconds(-60)));
    fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    expect((await screen.findByRole("alert")).textContent).toContain(refusal);
    expect(onDecided).toHaveBeenCalledTimes(1);
    // The reviewer can try again later: the button is not left disabled.
    expect((screen.getByRole("button", { name: "Resume" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("offers Resume only after the lease runs out while the page is open", () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(new Date("2026-10-15T10:00:00Z"));
    renderPanel(executing(Math.floor(Date.now() / 1000) + 20));
    expect(screen.queryByRole("button", { name: "Resume" })).toBeNull();
    act(() => {
      vi.advanceTimersByTime(30_000);
    });
    expect(screen.getByRole("button", { name: "Resume" })).toBeTruthy();
  });

  it("reloads the case when Release's execute step loses the connection, and still shows the error", async () => {
    vi.mocked(executeApproval).mockRejectedValueOnce(
      new ApiError("The request took longer than 20s and was abandoned.", 0, "unreachable"),
    );
    const onDecided = renderPanel(makeCase("HELD_FOR_REVIEW"));
    fireEvent.click(screen.getByRole("button", { name: "Release" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(onDecided).toHaveBeenCalledTimes(1));
    expect((await screen.findByRole("alert")).textContent).toMatch(/took longer than 20s/);
  });

  it("reloads the case when Retry loses the connection", async () => {
    vi.mocked(executeApproval).mockRejectedValueOnce(new ApiError("Failed to fetch", 0, "unreachable"));
    const approval = { approval_id: "evapr-1", action: "release", approver: "r", evidence_version: 1, status: "VALID", at: "" };
    const onDecided = renderPanel(makeCase("EXECUTION_FAILED", { approvals: [approval] }));
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(onDecided).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole("alert")).toBeTruthy();
  });

  it("does not reload for a refusal the server sent, which is an answer and not a lost connection", async () => {
    vi.mocked(approveCase).mockRejectedValueOnce(new ApiError("Re-evaluate first.", 409, "http"));
    const onDecided = renderPanel(makeCase("HELD_FOR_REVIEW"));
    fireEvent.click(screen.getByRole("button", { name: "Release" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Re-evaluate first.");
    expect(onDecided).not.toHaveBeenCalled();
    expect(executeApproval).not.toHaveBeenCalled();
  });

  it("reads the case again when Execute is refused because the case has moved on", async () => {
    vi.mocked(executeApproval).mockRejectedValueOnce(
      new ApiError("Approval evapr-1 is not executable: case is RELEASED_BY_HUMAN, not APPROVED or EXECUTION_FAILED", 409, "http"),
    );
    const approval = { approval_id: "evapr-1", action: "release", approver: "r", evidence_version: 1, status: "VALID", at: "" };
    const onDecided = renderPanel(makeCase("APPROVED", { approvals: [approval] }));
    fireEvent.click(screen.getByRole("button", { name: "Execute" }));
    expect((await screen.findByRole("alert")).textContent).toContain("not executable");
    expect(onDecided).toHaveBeenCalledTimes(1);
  });

  it("reads the case again when Release's execute step is refused with 409", async () => {
    vi.mocked(executeApproval).mockRejectedValueOnce(
      new ApiError("Another execution of this approval is in progress.", 409, "http"),
    );
    const onDecided = renderPanel(makeCase("HELD_FOR_REVIEW"));
    fireEvent.click(screen.getByRole("button", { name: "Release" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    expect((await screen.findByRole("alert")).textContent).toContain("in progress");
    expect(onDecided).toHaveBeenCalledTimes(1);
  });

  it("does not read the case again when execute is refused for another reason than a moved case", async () => {
    vi.mocked(executeApproval).mockRejectedValueOnce(new ApiError("Releasing needs a password sign-in.", 403, "http"));
    const approval = { approval_id: "evapr-1", action: "release", approver: "r", evidence_version: 1, status: "VALID", at: "" };
    const onDecided = renderPanel(makeCase("APPROVED", { approvals: [approval] }));
    fireEvent.click(screen.getByRole("button", { name: "Execute" }));
    expect((await screen.findByRole("alert")).textContent).toContain("password sign-in");
    expect(onDecided).not.toHaveBeenCalled();
  });

  it("keeps Execute for an approved case, with no Resume beside it", () => {
    const approval = { approval_id: "evapr-1", action: "release", approver: "r", evidence_version: 1, status: "VALID", at: "" };
    renderPanel(makeCase("APPROVED", { approvals: [approval] }));
    expect(screen.getByRole("button", { name: "Execute" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Resume" })).toBeNull();
  });
});

