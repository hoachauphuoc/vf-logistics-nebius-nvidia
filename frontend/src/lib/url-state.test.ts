import { act, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ search: "" }));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(mocks.search),
}));

import { CaseParamListener, useLate, writeCaseParam } from "./url-state";

function Late({ active, ms }: { active: boolean; ms: number }) {
  const late = useLate(active, ms);
  return createElement("p", null, late ? "late" : "not late");
}

// This file is .ts, so JSX is not available; createElement builds the same elements.
function lateEl(active: boolean, ms: number) {
  return createElement(Late, { active, ms });
}

function listenerEl(onChange: (caseId: string | null) => void) {
  return createElement(CaseParamListener, { onChange });
}

describe("CaseParamListener", () => {
  afterEach(() => {
    mocks.search = "";
  });

  it("reports the case id from the address bar", () => {
    mocks.search = "case=CASE-42";
    const onChange = vi.fn();
    render(listenerEl(onChange));
    expect(onChange).toHaveBeenCalledWith("CASE-42");
  });

  it("reports null when the address bar has no case parameter", () => {
    mocks.search = "tab=risk";
    const onChange = vi.fn();
    render(listenerEl(onChange));
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("renders nothing on screen", () => {
    const { container } = render(listenerEl(vi.fn()));
    expect(container).toBeEmptyDOMElement();
  });

  it("reports the new case id when the parameter changes", () => {
    mocks.search = "case=A1";
    const onChange = vi.fn();
    const { rerender } = render(listenerEl(onChange));
    mocks.search = "case=B2";
    rerender(listenerEl(onChange));
    expect(onChange).toHaveBeenLastCalledWith("B2");
  });
});

describe("writeCaseParam", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.history.replaceState(null, "", "/");
  });

  it("sets the case parameter and keeps the other parameters and the hash", () => {
    window.history.replaceState(null, "", "/cases?case=old&tab=risk#top");
    writeCaseParam("NEW-7");
    expect(window.location.pathname).toBe("/cases");
    expect(window.location.search).toBe("?case=NEW-7&tab=risk");
    expect(window.location.hash).toBe("#top");
  });

  it("adds the case parameter to a bare address", () => {
    window.history.replaceState(null, "", "/cases");
    writeCaseParam("C-1");
    expect(window.location.search).toBe("?case=C-1");
  });

  it("removes the case parameter and keeps the other parameters", () => {
    window.history.replaceState(null, "", "/cases?case=old&tab=risk");
    writeCaseParam(null);
    expect(window.location.search).toBe("?tab=risk");
  });

  it("leaves no query string when the case parameter was the only one", () => {
    window.history.replaceState(null, "", "/cases?case=old#top");
    writeCaseParam(null);
    expect(window.location.search).toBe("");
    expect(window.location.hash).toBe("#top");
  });

  it("treats an empty case id as no case", () => {
    window.history.replaceState(null, "", "/cases?case=old");
    writeCaseParam("");
    expect(window.location.search).toBe("");
  });

  it("replaces the history entry instead of pushing a new one", () => {
    const replace = vi.spyOn(window.history, "replaceState");
    const push = vi.spyOn(window.history, "pushState");
    window.history.replaceState(null, "", "/cases");
    replace.mockClear();
    writeCaseParam("C-2");
    expect(replace).toHaveBeenCalledWith(null, "", "/cases?case=C-2");
    expect(push).not.toHaveBeenCalled();
  });
});

describe("useLate", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("is not late while inactive, even after the delay", () => {
    vi.useFakeTimers();
    render(lateEl(false, 1000));
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(screen.getByText("not late")).toBeInTheDocument();
  });

  it("is not late before the delay has passed", () => {
    vi.useFakeTimers();
    render(lateEl(true, 1000));
    act(() => {
      vi.advanceTimersByTime(999);
    });
    expect(screen.getByText("not late")).toBeInTheDocument();
  });

  it("becomes late once it has stayed active for the delay", () => {
    vi.useFakeTimers();
    render(lateEl(true, 1000));
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByText("late")).toBeInTheDocument();
  });

  it("goes back to not late as soon as it becomes inactive", () => {
    vi.useFakeTimers();
    const { rerender } = render(lateEl(true, 1000));
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    rerender(lateEl(false, 1000));
    expect(screen.getByText("not late")).toBeInTheDocument();
  });

  it("starts the delay again when it becomes active a second time", () => {
    vi.useFakeTimers();
    const { rerender } = render(lateEl(true, 1000));
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    rerender(lateEl(false, 1000));
    rerender(lateEl(true, 1000));
    act(() => {
      vi.advanceTimersByTime(999);
    });
    expect(screen.getByText("not late")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.getByText("late")).toBeInTheDocument();
  });
});
