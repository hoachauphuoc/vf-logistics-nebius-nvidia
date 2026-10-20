import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "./tooltip";

// Radix measures the floating content with ResizeObserver, which jsdom does not provide.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

function renderTooltip({
  contentClassName,
  rootProps = {},
}: {
  contentClassName?: string;
  rootProps?: Partial<ComponentProps<typeof Tooltip>>;
} = {}) {
  return render(
    <TooltipProvider>
      <Tooltip {...rootProps}>
        <TooltipTrigger>Info</TooltipTrigger>
        <TooltipContent className={contentClassName}>Explains the field</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

function getTrigger() {
  return screen.getByRole("button", { name: "Info" });
}

function openByFocus() {
  act(() => {
    getTrigger().focus();
  });
}

describe("tooltip", () => {
  beforeEach(() => {
    vi.stubGlobal("ResizeObserver", ResizeObserverStub);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the trigger as a button with its label and the tooltip slot marker", () => {
    renderTooltip();

    const trigger = getTrigger();
    expect(trigger.tagName).toBe("BUTTON");
    expect(trigger).toHaveAttribute("data-slot", "tooltip-trigger");
  });

  it("keeps the tooltip content out of the document until the trigger is opened", () => {
    renderTooltip();

    expect(screen.queryByText("Explains the field")).not.toBeInTheDocument();
    expect(document.querySelector('[data-slot="tooltip-content"]')).toBeNull();
  });

  it("shows the tooltip content when the trigger receives focus", async () => {
    renderTooltip();

    openByFocus();

    const content = await waitFor(() => {
      const element = document.querySelector('[data-slot="tooltip-content"]');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });
    expect(content).toHaveTextContent("Explains the field");
    expect(screen.getAllByText("Explains the field").length).toBeGreaterThan(0);
  });

  it("hides the tooltip content again when Escape is pressed", async () => {
    renderTooltip();
    openByFocus();
    await screen.findAllByText("Explains the field");

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => {
      expect(document.querySelector('[data-slot="tooltip-content"]')).toBeNull();
    });
  });

  it("renders the arrow inside the tooltip content", async () => {
    renderTooltip();
    openByFocus();
    await screen.findAllByText("Explains the field");

    const content = document.querySelector('[data-slot="tooltip-content"]') as HTMLElement;
    expect(content.querySelector("svg")).not.toBeNull();
  });

  it("merges a custom className into the default tooltip content classes", async () => {
    renderTooltip({ contentClassName: "custom-tip" });
    openByFocus();
    await screen.findAllByText("Explains the field");

    const content = document.querySelector('[data-slot="tooltip-content"]') as HTMLElement;
    expect(content).toHaveClass("custom-tip");
    expect(content).toHaveClass("rounded-md");
    expect(content).toHaveClass("bg-foreground");
  });

  it("shows the content immediately when the root is rendered with defaultOpen", async () => {
    renderTooltip({ rootProps: { defaultOpen: true } });

    expect(await screen.findAllByText("Explains the field")).not.toHaveLength(0);
  });

  it("stays closed on focus when the root is controlled with open set to false", async () => {
    renderTooltip({ rootProps: { open: false } });

    openByFocus();

    expect(document.querySelector('[data-slot="tooltip-content"]')).toBeNull();
    expect(screen.queryByText("Explains the field")).not.toBeInTheDocument();
  });

  it("reports onOpenChange with true when the trigger is focused", async () => {
    const onOpenChange = vi.fn();
    renderTooltip({ rootProps: { onOpenChange } });

    openByFocus();

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(true));
  });

  it("reports onOpenChange with false when Escape closes the tooltip", async () => {
    const onOpenChange = vi.fn();
    renderTooltip({ rootProps: { onOpenChange } });
    openByFocus();
    await screen.findAllByText("Explains the field");

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(onOpenChange).toHaveBeenLastCalledWith(false));
  });
});
