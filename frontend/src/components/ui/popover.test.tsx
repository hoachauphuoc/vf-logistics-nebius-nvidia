import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  Popover,
  PopoverAnchor,
  PopoverClose,
  PopoverContent,
  PopoverTrigger,
} from "./popover";

// Radix positions the panel with ResizeObserver, which jsdom does not provide.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

function popoverTree(
  rootProps: ComponentProps<typeof Popover> = {},
  contentProps: ComponentProps<typeof PopoverContent> = {},
  triggerProps: ComponentProps<typeof PopoverTrigger> = {}
) {
  return (
    <Popover {...rootProps}>
      <PopoverTrigger {...triggerProps}>Open help</PopoverTrigger>
      <PopoverContent {...contentProps}>
        <p>Explanation text</p>
        <PopoverClose>Dismiss</PopoverClose>
      </PopoverContent>
    </Popover>
  );
}

function getTrigger() {
  return screen.getByRole("button", { name: "Open help" });
}

function openPanel() {
  fireEvent.click(getTrigger());
  return screen.getByRole("dialog");
}

describe("popover", () => {
  beforeEach(() => {
    vi.stubGlobal("ResizeObserver", ResizeObserverStub);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps the explanation out of the page until the trigger is clicked", () => {
    render(popoverTree());

    expect(screen.queryByText("Explanation text")).not.toBeInTheDocument();
    expect(getTrigger()).toHaveAttribute("aria-expanded", "false");
    expect(getTrigger()).toHaveAttribute("data-state", "closed");
  });

  it("opens the explanation in a dialog when the trigger is clicked", () => {
    render(popoverTree());

    const dialog = openPanel();

    expect(dialog).toHaveTextContent("Explanation text");
    expect(getTrigger()).toHaveAttribute("aria-expanded", "true");
    expect(getTrigger()).toHaveAttribute("data-state", "open");
  });

  it("closes the explanation when the trigger is clicked a second time", async () => {
    render(popoverTree());

    openPanel();
    fireEvent.click(getTrigger());

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(getTrigger()).toHaveAttribute("aria-expanded", "false");
  });

  it("closes on Escape and reports the change through onOpenChange", async () => {
    const onOpenChange = vi.fn();
    render(popoverTree({ onOpenChange }));

    const dialog = openPanel();
    expect(onOpenChange).toHaveBeenLastCalledWith(true);

    fireEvent.keyDown(dialog, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(onOpenChange).toHaveBeenLastCalledWith(false);
  });

  it("closes when the Dismiss button inside the panel is clicked", async () => {
    render(popoverTree());

    openPanel();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("starts open when defaultOpen is set", () => {
    render(popoverTree({ defaultOpen: true }));

    expect(screen.getByRole("dialog")).toHaveTextContent("Explanation text");
    expect(getTrigger()).toHaveAttribute("aria-expanded", "true");
  });

  it("shows the panel when open is true and hides it when the prop turns false", () => {
    const { rerender } = render(popoverTree({ open: true }));

    expect(screen.getByRole("dialog")).toHaveTextContent("Explanation text");

    rerender(popoverTree({ open: false }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("asks for the change but stays closed when open is controlled and false", () => {
    const onOpenChange = vi.fn();
    render(popoverTree({ open: false, onOpenChange }));

    fireEvent.click(getTrigger());

    expect(onOpenChange).toHaveBeenCalledWith(true);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("runs the caller's onClick on the trigger as well as opening the panel", () => {
    const onClick = vi.fn();
    render(popoverTree({}, {}, { onClick }));

    openPanel();

    expect(onClick).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("marks the trigger and the panel with their slot names", () => {
    render(popoverTree());

    expect(getTrigger()).toHaveAttribute("data-slot", "popover-trigger");
    expect(openPanel()).toHaveAttribute("data-slot", "popover-content");
  });

  it("keeps the panel's base styling and adds the caller's class name", () => {
    render(popoverTree({}, { className: "my-panel" }));

    const dialog = openPanel();

    expect(dialog).toHaveClass("my-panel");
    expect(dialog).toHaveClass("w-72", "rounded-lg", "bg-popover");
  });

  it("aligns the panel to the edge the caller asks for", () => {
    render(popoverTree({}, { align: "end" }));

    expect(openPanel()).toHaveAttribute("data-align", "end");
  });

  it("draws an arrow pointing back at the trigger", () => {
    render(popoverTree());

    expect(openPanel().querySelector("svg")).toBeInTheDocument();
  });

  it("anchors the panel to a PopoverAnchor element when one is given", () => {
    render(
      <Popover defaultOpen>
        <PopoverAnchor>
          <span>Shipment row</span>
        </PopoverAnchor>
        <PopoverContent>Row details</PopoverContent>
      </Popover>
    );

    const anchor = document.querySelector('[data-slot="popover-anchor"]');
    expect(anchor).toContainElement(screen.getByText("Shipment row"));
    expect(screen.getByRole("dialog")).toHaveTextContent("Row details");
  });
});
