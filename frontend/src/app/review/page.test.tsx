import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  fetchReviewQueue: vi.fn(async () => ({ items: [], next_cursor: null })),
  fetchCase: vi.fn(),
}));
vi.mock("@/lib/tenant-context", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/tenant-context")>()),
  useTenant: () => ({ tenant: { id: "tenant-a" } }),
}));
vi.mock("@/lib/url-state", async (importOriginal) => {
  const { useEffect } = await import("react");
  return {
    ...(await importOriginal<typeof import("@/lib/url-state")>()),
    // The page is opened on ?case=CASE-1.
    CaseParamListener: ({ onChange }: { onChange: (caseId: string | null) => void }) => {
      useEffect(() => onChange("CASE-1"), [onChange]);
      return null;
    },
    writeCaseParam: vi.fn(),
  };
});
// The panel has its own tests; here it only shows which state the page handed it.
vi.mock("@/components/review/ReviewPanel", () => ({
  ReviewPanel: ({ detail }: { detail?: { state: string } }) => <p data-testid="panel-state">{detail?.state ?? "none"}</p>,
}));
vi.mock("@/components/help/HelpDot", () => ({ HelpDot: () => null }));

import { fetchCase } from "@/lib/api";

import ReviewQueuePage from "./page";

/**
 * N08: the review page shows the case a link opened. An execution ends on the server
 * without anyone asking the page, so while the case is EXECUTING the page reads it again
 * every 15 seconds; once it has finished, the polling stops.
 */
describe("Review page: an executing case is read again (N08)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => vi.useRealTimers());

  it("reads an executing case again after 15 seconds and stops once it has finished", async () => {
    vi.mocked(fetchCase)
      .mockResolvedValueOnce({ case_id: "CASE-1", state: "EXECUTING" } as never)
      .mockResolvedValue({ case_id: "CASE-1", state: "RELEASED_BY_HUMAN" } as never);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ReviewQueuePage />
      </QueryClientProvider>,
    );
    expect((await screen.findByTestId("panel-state")).textContent).toBe("EXECUTING");
    expect(fetchCase).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    expect(fetchCase).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(screen.getByTestId("panel-state").textContent).toBe("RELEASED_BY_HUMAN"));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(fetchCase).toHaveBeenCalledTimes(2);
  });
});
