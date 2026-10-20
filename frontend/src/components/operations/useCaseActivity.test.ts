import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  reportCaseActivity: vi.fn<(caseId: string, activeMs: number) => Promise<void>>(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  reportCaseActivity: mocks.reportCaseActivity,
}));

import { useCaseActivity } from "./useCaseActivity";

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
}

// Total milliseconds sent across every report, whatever the split between reports.
function reportedMs() {
  return mocks.reportCaseActivity.mock.calls.reduce((sum, [, ms]) => sum + ms, 0);
}

describe("useCaseActivity: when nothing is reported", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.reportCaseActivity.mockResolvedValue(undefined);
    vi.useFakeTimers();
    setVisibility("visible");
  });

  afterEach(() => {
    vi.useRealTimers();
    Reflect.deleteProperty(document, "visibilityState");
  });

  it("reports nothing when no case is open", () => {
    renderHook(() => useCaseActivity(null, true));
    vi.advanceTimersByTime(60_000);
    expect(mocks.reportCaseActivity).not.toHaveBeenCalled();
  });

  it("reports nothing when the API would refuse the reviewer (enabled is false)", () => {
    renderHook(() => useCaseActivity("case-1", false));
    vi.advanceTimersByTime(60_000);
    expect(mocks.reportCaseActivity).not.toHaveBeenCalled();
  });

  it("reports nothing when the page is hidden for the whole time", () => {
    setVisibility("hidden");
    renderHook(() => useCaseActivity("case-1", true));
    vi.advanceTimersByTime(60_000);
    expect(mocks.reportCaseActivity).not.toHaveBeenCalled();
  });

  it("reports nothing when the reviewer leaves before any time has passed", () => {
    const { unmount } = renderHook(() => useCaseActivity("case-1", true));
    unmount();
    expect(mocks.reportCaseActivity).not.toHaveBeenCalled();
  });
});

describe("useCaseActivity: reporting the time spent on a case", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.reportCaseActivity.mockResolvedValue(undefined);
    vi.useFakeTimers();
    setVisibility("visible");
  });

  afterEach(() => {
    vi.useRealTimers();
    Reflect.deleteProperty(document, "visibilityState");
  });

  it("reports the time spent on the case every 30 seconds", () => {
    renderHook(() => useCaseActivity("case-1", true));
    vi.advanceTimersByTime(30_000);
    expect(mocks.reportCaseActivity).toHaveBeenCalledWith("case-1", 30_000);
    vi.advanceTimersByTime(30_000);
    expect(mocks.reportCaseActivity).toHaveBeenCalledTimes(2);
    expect(reportedMs()).toBe(60_000);
  });

  it("stops counting after a minute with no input", () => {
    renderHook(() => useCaseActivity("case-1", true));
    vi.advanceTimersByTime(90_000);
    expect(reportedMs()).toBe(60_000);
  });

  it.each(["pointerdown", "keydown", "scroll", "wheel", "pointermove"])(
    "keeps counting while the reviewer is active (%s)",
    (eventName) => {
      const { unmount } = renderHook(() => useCaseActivity("case-1", true));
      vi.advanceTimersByTime(50_000);
      window.dispatchEvent(new Event(eventName));
      vi.advanceTimersByTime(50_000);
      unmount();
      expect(reportedMs()).toBe(100_000);
    },
  );

  it("reports the remaining time when the reviewer leaves the case", () => {
    const { unmount } = renderHook(() => useCaseActivity("case-1", true));
    vi.advanceTimersByTime(5_000);
    unmount();
    expect(mocks.reportCaseActivity).toHaveBeenCalledTimes(1);
    expect(mocks.reportCaseActivity).toHaveBeenCalledWith("case-1", 5_000);
  });

  it("reports the time so far and stops when enabled turns off", () => {
    const { rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) => useCaseActivity("case-1", enabled),
      { initialProps: { enabled: true } },
    );
    vi.advanceTimersByTime(5_000);
    rerender({ enabled: false });
    vi.advanceTimersByTime(60_000);
    expect(mocks.reportCaseActivity.mock.calls).toEqual([["case-1", 5_000]]);
  });

  it("reports the time spent on the previous case under its own id when the case changes", () => {
    const { rerender } = renderHook(
      ({ caseId }: { caseId: string }) => useCaseActivity(caseId, true),
      { initialProps: { caseId: "case-1" } },
    );
    vi.advanceTimersByTime(5_000);
    rerender({ caseId: "case-2" });
    expect(mocks.reportCaseActivity.mock.calls).toEqual([["case-1", 5_000]]);
    vi.advanceTimersByTime(30_000);
    expect(mocks.reportCaseActivity).toHaveBeenLastCalledWith("case-2", 30_000);
  });

  it("drops a report that fails without interrupting the review", () => {
    mocks.reportCaseActivity.mockRejectedValueOnce(new Error("network down"));
    const { unmount } = renderHook(() => useCaseActivity("case-1", true));
    vi.advanceTimersByTime(5_000);
    expect(() => unmount()).not.toThrow();
    expect(mocks.reportCaseActivity).toHaveBeenCalledWith("case-1", 5_000);
  });
});

describe("useCaseActivity: page visibility", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.reportCaseActivity.mockResolvedValue(undefined);
    vi.useFakeTimers();
    setVisibility("visible");
  });

  afterEach(() => {
    vi.useRealTimers();
    Reflect.deleteProperty(document, "visibilityState");
  });

  it("sends what it has and stops counting when the page is hidden", () => {
    renderHook(() => useCaseActivity("case-1", true));
    vi.advanceTimersByTime(10_000);
    setVisibility("hidden");
    document.dispatchEvent(new Event("visibilitychange"));
    expect(mocks.reportCaseActivity.mock.calls).toEqual([["case-1", 10_000]]);
    vi.advanceTimersByTime(40_000);
    expect(mocks.reportCaseActivity.mock.calls).toEqual([["case-1", 10_000]]);
  });

  it("resumes counting when the page becomes visible again", () => {
    renderHook(() => useCaseActivity("case-1", true));
    vi.advanceTimersByTime(10_000);
    setVisibility("hidden");
    document.dispatchEvent(new Event("visibilitychange"));
    setVisibility("visible");
    document.dispatchEvent(new Event("visibilitychange"));
    vi.advanceTimersByTime(20_000);
    expect(mocks.reportCaseActivity.mock.calls).toEqual([
      ["case-1", 10_000],
      ["case-1", 20_000],
    ]);
  });
});
