import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ScrollArea, ScrollBar } from "./scroll-area";

// Radix measures the scrollbars with ResizeObserver; jsdom provides none.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

function scrollbars(container: HTMLElement) {
  return Array.from(
    container.querySelectorAll<HTMLElement>('[data-slot="scroll-area-scrollbar"]')
  );
}

describe("ScrollArea", () => {
  beforeEach(() => {
    vi.stubGlobal("ResizeObserver", ResizeObserverStub);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders its children inside the scrollable viewport", () => {
    const { container } = render(
      <ScrollArea>
        <p>Audit row 1</p>
      </ScrollArea>
    );

    const viewport = container.querySelector<HTMLElement>('[data-slot="scroll-area-viewport"]');
    expect(viewport).not.toBeNull();
    expect(viewport).toContainElement(screen.getByText("Audit row 1"));
  });

  it("marks the root and merges a custom class with the default one", () => {
    const { container } = render(<ScrollArea className="h-40 custom-root">text</ScrollArea>);

    const root = container.firstElementChild as HTMLElement;
    expect(root).toHaveAttribute("data-slot", "scroll-area");
    expect(root).toHaveClass("relative", "h-40", "custom-root");
  });

  it("passes extra root props such as data-testid through to the root element", () => {
    render(<ScrollArea data-testid="audit-panel">text</ScrollArea>);

    expect(screen.getByTestId("audit-panel")).toHaveAttribute("data-slot", "scroll-area");
  });

  it("makes the viewport fill the root and keeps its focus ring classes", () => {
    const { container } = render(<ScrollArea>text</ScrollArea>);

    const viewport = container.querySelector<HTMLElement>('[data-slot="scroll-area-viewport"]');
    expect(viewport).toHaveClass("size-full", "rounded-[inherit]", "focus-visible:ring-[3px]");
  });

  it("hides the default scrollbar until the pointer is over the area", () => {
    const { container } = render(<ScrollArea>text</ScrollArea>);

    expect(scrollbars(container)).toHaveLength(0);
  });

  it("renders a vertical scrollbar when the scrollbar is always shown", () => {
    const { container } = render(<ScrollArea type="always">text</ScrollArea>);

    const bars = scrollbars(container);
    expect(bars).toHaveLength(1);
    expect(bars[0]).toHaveAttribute("data-orientation", "vertical");
    expect(bars[0]).toHaveClass("data-vertical:w-2.5");
  });

  it("renders a horizontal ScrollBar when one is passed as a child", () => {
    const { container } = render(
      <ScrollArea type="always">
        <ScrollBar orientation="horizontal" />
      </ScrollArea>
    );

    const orientations = scrollbars(container)
      .map((bar) => bar.getAttribute("data-orientation"))
      .sort();
    expect(orientations).toEqual(["horizontal", "vertical"]);
  });

  it("merges a custom class onto a passed ScrollBar and keeps its default classes", () => {
    const { container } = render(
      <ScrollArea type="always">
        <ScrollBar className="custom-bar" />
      </ScrollArea>
    );

    const customBars = scrollbars(container).filter((bar) => bar.classList.contains("custom-bar"));
    expect(customBars).toHaveLength(1);
    expect(customBars[0]).toHaveClass("data-vertical:w-2.5", "touch-none");
  });
});
