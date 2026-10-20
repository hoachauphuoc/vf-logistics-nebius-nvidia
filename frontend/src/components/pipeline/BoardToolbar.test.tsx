import { fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import type { PriorityFilter, SortKey } from "@/lib/pipeline";

import { BoardToolbar } from "./BoardToolbar";

type Props = ComponentProps<typeof BoardToolbar>;

beforeAll(() => {
  // Radix Select asks for these; jsdom does not implement them.
  Element.prototype.hasPointerCapture ??= () => false;
  Element.prototype.releasePointerCapture ??= () => {};
  Element.prototype.scrollIntoView ??= () => {};
});

// Radix measures floating content with ResizeObserver, which jsdom does not provide.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

function renderToolbar(overrides: Partial<Props> = {}) {
  const props: Props = {
    search: "",
    onSearch: vi.fn(),
    sort: "newest" as SortKey,
    onSort: vi.fn(),
    priority: "" as PriorityFilter,
    onPriority: vi.fn(),
    matched: 10,
    totalFetched: 10,
    ...overrides,
  };
  render(<BoardToolbar {...props} />);
  return props;
}

// Radix opens a select on ArrowDown while the trigger is focused.
function openSelect(name: string) {
  fireEvent.keyDown(screen.getByRole("combobox", { name }), { key: "ArrowDown" });
}

// Radix commits the highlighted option on Enter.
function chooseOption(name: string) {
  fireEvent.keyDown(screen.getByRole("option", { name }), { key: "Enter" });
}

describe("BoardToolbar result count", () => {
  it("says how many cases match out of how many were fetched when a filter is active", () => {
    renderToolbar({ matched: 3, totalFetched: 10 });
    expect(screen.getByText("3 of 10 shown")).toBeInTheDocument();
  });

  it("says how many cases are on the board when nothing is filtered out", () => {
    renderToolbar({ matched: 10, totalFetched: 10 });
    expect(screen.getByText("10 on board")).toBeInTheDocument();
  });

  it("shows zero of the fetched cases when the search matches nothing", () => {
    renderToolbar({ matched: 0, totalFetched: 4 });
    expect(screen.getByText("0 of 4 shown")).toBeInTheDocument();
  });

  it("shows zero on board when the fetch returned no cases", () => {
    renderToolbar({ matched: 0, totalFetched: 0 });
    expect(screen.getByText("0 on board")).toBeInTheDocument();
  });
});

describe("BoardToolbar search box", () => {
  it("shows the search text it was given with its placeholder and label", () => {
    renderToolbar({ search: "ACME" });
    const input = screen.getByRole("textbox", { name: "Search the board" });
    expect(input).toHaveValue("ACME");
    expect(input).toHaveAttribute("placeholder", "Case, shipment, company, route");
  });

  it("reports each typed value to onSearch", () => {
    const { onSearch } = renderToolbar();
    fireEvent.change(screen.getByRole("textbox", { name: "Search the board" }), {
      target: { value: "ROUTE-7" },
    });
    expect(onSearch).toHaveBeenCalledWith("ROUTE-7");
  });

  it("hides the clear button while the search box is empty", () => {
    renderToolbar({ search: "" });
    expect(screen.queryByRole("button", { name: "Clear search" })).not.toBeInTheDocument();
  });

  it("clears the search through onSearch when the clear button is pressed", () => {
    const { onSearch } = renderToolbar({ search: "ACME" });
    fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
    expect(onSearch).toHaveBeenCalledWith("");
    expect(onSearch).toHaveBeenCalledTimes(1);
  });
});

describe("BoardToolbar priority filter", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows All priorities when no priority filter is set", () => {
    renderToolbar({ priority: "" });
    expect(screen.getByRole("combobox", { name: "Filter by priority" })).toHaveTextContent(
      "All priorities",
    );
  });

  it("shows the label of the active priority filter", () => {
    renderToolbar({ priority: "HIGH" });
    expect(screen.getByRole("combobox", { name: "Filter by priority" })).toHaveTextContent(
      "High and above",
    );
  });

  it("lists the four priority choices when opened", () => {
    vi.stubGlobal("ResizeObserver", ResizeObserverStub);
    renderToolbar();
    openSelect("Filter by priority");
    for (const label of [
      "All priorities",
      "Critical only",
      "High and above",
      "Medium and above",
    ]) {
      expect(screen.getByRole("option", { name: label })).toBeInTheDocument();
    }
  });

  it("passes the raw priority value when a priority is chosen", () => {
    vi.stubGlobal("ResizeObserver", ResizeObserverStub);
    const { onPriority } = renderToolbar({ priority: "" });
    openSelect("Filter by priority");
    chooseOption("High and above");
    expect(onPriority).toHaveBeenCalledWith("HIGH");
  });

  it("passes CRITICAL when the critical-only choice is made", () => {
    vi.stubGlobal("ResizeObserver", ResizeObserverStub);
    const { onPriority } = renderToolbar({ priority: "" });
    openSelect("Filter by priority");
    chooseOption("Critical only");
    expect(onPriority).toHaveBeenCalledWith("CRITICAL");
  });

  it("maps the All priorities choice back to the empty no-filter value", () => {
    vi.stubGlobal("ResizeObserver", ResizeObserverStub);
    const { onPriority } = renderToolbar({ priority: "CRITICAL" });
    openSelect("Filter by priority");
    chooseOption("All priorities");
    expect(onPriority).toHaveBeenCalledWith("");
  });
});

describe("BoardToolbar sort", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the label of the current sort order", () => {
    renderToolbar({ sort: "risk-high" });
    expect(screen.getByRole("combobox", { name: "Sort cases" })).toHaveTextContent(
      "Highest risk",
    );
  });

  it("lists every sort order when opened", () => {
    vi.stubGlobal("ResizeObserver", ResizeObserverStub);
    renderToolbar();
    openSelect("Sort cases");
    for (const label of [
      "Newest first",
      "Oldest first",
      "Highest risk",
      "Lowest risk",
      "Priority",
      "SLA deadline",
    ]) {
      expect(screen.getByRole("option", { name: label })).toBeInTheDocument();
    }
  });

  it("passes the sort key of the chosen order to onSort", () => {
    vi.stubGlobal("ResizeObserver", ResizeObserverStub);
    const { onSort } = renderToolbar({ sort: "newest" });
    openSelect("Sort cases");
    chooseOption("SLA deadline");
    expect(onSort).toHaveBeenCalledWith("sla");
  });

  it("passes risk-low when the lowest-risk order is chosen", () => {
    vi.stubGlobal("ResizeObserver", ResizeObserverStub);
    const { onSort } = renderToolbar({ sort: "newest" });
    openSelect("Sort cases");
    chooseOption("Lowest risk");
    expect(onSort).toHaveBeenCalledWith("risk-low");
  });
});
