import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  fetchReviewQueue: vi.fn(),
  fetchCase: vi.fn(),
  writeCaseParam: vi.fn(),
  scrollIntoView: vi.fn(),
  // The ?case= value the page is opened with; null means no case in the address bar.
  urlCase: null as string | null,
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  fetchReviewQueue: mocks.fetchReviewQueue,
  fetchCase: mocks.fetchCase,
}));
vi.mock("@/lib/tenant-context", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/tenant-context")>()),
  useTenant: () => ({ tenant: { id: "tenant-a" } }),
}));
vi.mock("@/lib/url-state", async (importOriginal) => {
  const { useEffect } = await import("react");
  return {
    ...(await importOriginal<typeof import("@/lib/url-state")>()),
    CaseParamListener: ({ onChange }: { onChange: (caseId: string | null) => void }) => {
      useEffect(() => onChange(mocks.urlCase), [onChange]);
      return null;
    },
    writeCaseParam: mocks.writeCaseParam,
  };
});
// The panel has its own tests. Here it shows what the page handed it, and has a
// Decide button that reports a decision back to the page.
vi.mock("@/components/review/ReviewPanel", () => ({
  ReviewPanel: ({
    summary,
    detail,
    detailLoading,
    detailError,
    onDecided,
  }: {
    summary: { case_id: string };
    detail?: { state?: string };
    detailLoading: boolean;
    detailError: Error | null;
    onDecided: () => void;
  }) => (
    <div data-testid="panel">
      <span data-testid="panel-case">{summary.case_id}</span>
      <span data-testid="panel-state">{detail?.state ?? "none"}</span>
      {detailLoading && <span>detail loading</span>}
      {detailError && <span>{detailError.message}</span>}
      <button type="button" onClick={onDecided}>
        Decide
      </button>
    </div>
  ),
}));
vi.mock("@/components/help/HelpDot", () => ({ HelpDot: () => null }));

import { fetchCase, fetchReviewQueue, queryKeys } from "@/lib/api";

import ReviewQueuePage from "./page";

function caseSummary(caseId: string, shipmentId: string, risk: number) {
  return { case_id: caseId, shipment_id: shipmentId, state: "PENDING_HUMAN", risk_score: risk } as never;
}

function matchMediaFor(narrow: boolean, reduce: boolean) {
  return (query: string) => {
    let matches = false;
    if (query === "(max-width: 1023px)") matches = narrow;
    if (query === "(prefers-reduced-motion: reduce)") matches = reduce;
    return { matches, media: query } as never;
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <ReviewQueuePage />
    </QueryClientProvider>,
  );
  return { invalidate };
}

describe("Review page: the queue", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.urlCase = null;
    mocks.fetchReviewQueue.mockResolvedValue({ items: [], next_cursor: null } as never);
    mocks.fetchCase.mockResolvedValue({ case_id: "CASE-1", state: "PENDING_HUMAN" } as never);
    Element.prototype.scrollIntoView = mocks.scrollIntoView;
    vi.stubGlobal("matchMedia", matchMediaFor(false, false));
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows skeletons, not the empty message, while the queue is loading", () => {
    mocks.fetchReviewQueue.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByRole("region", { name: "Cases awaiting a decision" })).toBeInTheDocument();
    expect(screen.queryByText("The queue is empty")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next 40" })).toBeDisabled();
  });

  it("says the queue is empty when no cases are waiting", async () => {
    renderPage();
    expect(await screen.findByText("The queue is empty")).toBeInTheDocument();
    expect(screen.getByText("Pick a case")).toBeInTheDocument();
  });

  it("lists each waiting case with its shipment and risk", async () => {
    mocks.fetchReviewQueue.mockResolvedValue({
      items: [caseSummary("CASE-1", "SHP-1", 80), caseSummary("CASE-2", "SHP-2", 40)],
      next_cursor: null,
    } as never);
    renderPage();
    expect(await screen.findByRole("button", { name: /^Open SHP-1, risk 80/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Open SHP-2, risk 40/ })).toBeInTheDocument();
    expect(screen.queryByText("The queue is empty")).not.toBeInTheDocument();
  });

  it("shows the request error and no cases when the queue fails", async () => {
    mocks.fetchReviewQueue.mockRejectedValue(new Error("queue down"));
    renderPage();
    expect(await screen.findByText("That request failed")).toBeInTheDocument();
    expect(screen.getByText("queue down")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Cases awaiting a decision" })).not.toBeInTheDocument();
  });

  it("disables Next 40 when the server gives no next cursor", async () => {
    mocks.fetchReviewQueue.mockResolvedValue({
      items: [caseSummary("CASE-1", "SHP-1", 80)],
      next_cursor: null,
    } as never);
    renderPage();
    await screen.findByRole("button", { name: /^Open SHP-1/ });
    expect(screen.getByRole("button", { name: "Next 40" })).toBeDisabled();
  });

  it("pages forward with the next cursor, and Start again returns to the first page", async () => {
    mocks.fetchReviewQueue.mockImplementation(async ({ cursor }: { cursor: string | null }) =>
      cursor === "CUR-2"
        ? { items: [caseSummary("CASE-2", "SHP-2", 40)], next_cursor: null }
        : { items: [caseSummary("CASE-1", "SHP-1", 80)], next_cursor: "CUR-2" },
    );
    renderPage();
    await screen.findByRole("button", { name: /^Open SHP-1/ });
    expect(screen.queryByRole("button", { name: "Start again" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next 40" }));
    expect(await screen.findByRole("button", { name: /^Open SHP-2/ })).toBeInTheDocument();
    expect(mocks.fetchReviewQueue).toHaveBeenLastCalledWith({ cursor: "CUR-2", limit: 40 });

    fireEvent.click(screen.getByRole("button", { name: "Start again" }));
    expect(await screen.findByRole("button", { name: /^Open SHP-1/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start again" })).not.toBeInTheDocument();
  });
});

describe("Review page: the selected case", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.urlCase = null;
    mocks.fetchReviewQueue.mockResolvedValue({
      items: [caseSummary("CASE-1", "SHP-1", 80)],
      next_cursor: null,
    } as never);
    mocks.fetchCase.mockResolvedValue({ case_id: "CASE-1", state: "PENDING_HUMAN" } as never);
    Element.prototype.scrollIntoView = mocks.scrollIntoView;
    vi.stubGlobal("matchMedia", matchMediaFor(false, false));
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("asks for a case when nothing is selected", async () => {
    renderPage();
    expect(await screen.findByText("Pick a case")).toBeInTheDocument();
    expect(screen.queryByTestId("panel")).not.toBeInTheDocument();
    expect(mocks.fetchCase).not.toHaveBeenCalled();
  });

  it("puts a clicked case in the panel and writes it to the address bar", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /^Open SHP-1/ }));
    expect(await screen.findByTestId("panel-case")).toHaveTextContent("CASE-1");
    expect(mocks.writeCaseParam).toHaveBeenCalledWith("CASE-1");
    expect(mocks.fetchCase).toHaveBeenCalledWith("CASE-1");
    await waitFor(() => expect(screen.getByTestId("panel-state")).toHaveTextContent("PENDING_HUMAN"));
  });

  it("shows a case opened from a link from its fetched document when the queue lacks it", async () => {
    mocks.urlCase = "CASE-9";
    mocks.fetchReviewQueue.mockResolvedValue({ items: [], next_cursor: null } as never);
    mocks.fetchCase.mockResolvedValue({ case_id: "CASE-9", state: "HELD_FOR_REVIEW" } as never);
    renderPage();
    expect(await screen.findByTestId("panel-case")).toHaveTextContent("CASE-9");
    expect(screen.getByTestId("panel-state")).toHaveTextContent("HELD_FOR_REVIEW");
  });

  it("shows neither the prompt nor the panel while a linked case is being fetched", async () => {
    mocks.urlCase = "CASE-9";
    mocks.fetchReviewQueue.mockResolvedValue({ items: [], next_cursor: null } as never);
    mocks.fetchCase.mockReturnValue(new Promise(() => {}));
    renderPage();
    await waitFor(() => expect(mocks.fetchCase).toHaveBeenCalledWith("CASE-9"));
    expect(screen.queryByText("Pick a case")).not.toBeInTheDocument();
    expect(screen.queryByTestId("panel")).not.toBeInTheDocument();
  });

  it("does not show a fetched document whose id is not the linked case", async () => {
    mocks.urlCase = "CASE-9";
    mocks.fetchReviewQueue.mockResolvedValue({ items: [], next_cursor: null } as never);
    mocks.fetchCase.mockResolvedValue({ case_id: "CASE-OTHER", state: "PENDING_HUMAN" } as never);
    renderPage();
    expect(await screen.findByText("Pick a case")).toBeInTheDocument();
    expect(screen.queryByTestId("panel")).not.toBeInTheDocument();
  });

  it("shows the request error when a linked case cannot be fetched", async () => {
    mocks.urlCase = "CASE-9";
    mocks.fetchReviewQueue.mockResolvedValue({ items: [], next_cursor: null } as never);
    mocks.fetchCase.mockRejectedValue(new Error("case gone"));
    renderPage();
    expect(await screen.findByText("That request failed")).toBeInTheDocument();
    expect(screen.getByText("case gone")).toBeInTheDocument();
  });

  it("refreshes the queue, the case and the snapshot when a reviewer decides", async () => {
    const { invalidate } = renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /^Open SHP-1/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Decide" }));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.reviewQueue("tenant-a") });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["case", "tenant-a"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.snapshot("tenant-a", true) });
  });

  it("scrolls the panel into view with smooth motion on a one-column layout", async () => {
    vi.stubGlobal("matchMedia", matchMediaFor(true, false));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /^Open SHP-1/ }));
    await waitFor(() =>
      expect(mocks.scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "start" }),
    );
  });

  it("scrolls the panel into view without motion when the reader prefers reduced motion", async () => {
    vi.stubGlobal("matchMedia", matchMediaFor(true, true));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /^Open SHP-1/ }));
    await waitFor(() =>
      expect(mocks.scrollIntoView).toHaveBeenCalledWith({ behavior: "auto", block: "start" }),
    );
  });

  it("does not scroll on a wide layout, where the panel sits beside the queue", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /^Open SHP-1/ }));
    expect(await screen.findByTestId("panel-case")).toHaveTextContent("CASE-1");
    expect(mocks.scrollIntoView).not.toHaveBeenCalled();
  });
});
