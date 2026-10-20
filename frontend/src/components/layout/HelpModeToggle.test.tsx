import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import { setHelpMode } from "@/lib/help-mode";

import { HelpModeToggle } from "./HelpModeToggle";

// Radix popper measures the trigger and content with ResizeObserver, which jsdom
// does not implement. Opening the tooltip would throw without this stub.
class ResizeObserverStub {
  observe(): void {
    // jsdom has no layout, so there is nothing to observe.
  }
  unobserve(): void {
    // See observe().
  }
  disconnect(): void {
    // See observe().
  }
}

const STORAGE_KEY = "vf.console.help";
const OFF_TOOLTIP = "Adds a question mark beside each panel, tile and status label.";
const ON_TOOLTIP = "Help is on. Press the question mark beside anything";

function renderToggle() {
  return render(
    <TooltipProvider>
      <HelpModeToggle />
    </TooltipProvider>,
  );
}

function tooltipText(): string | null {
  return document.querySelector('[data-slot="tooltip-content"]')?.textContent ?? null;
}

describe("HelpModeToggle", () => {
  beforeEach(() => {
    vi.stubGlobal("ResizeObserver", ResizeObserverStub);
    window.localStorage.clear();
    setHelpMode(false);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("offers to turn help on, unpressed, while help mode is off", () => {
    renderToggle();

    const button = screen.getByRole("button", { name: "Turn help on" });
    expect(button).toHaveAttribute("aria-pressed", "false");
    expect(button).toHaveClass("text-dim");
  });

  it("offers to turn help off, pressed, while help mode is on", () => {
    setHelpMode(true);
    renderToggle();

    const button = screen.getByRole("button", { name: "Turn help off" });
    expect(button).toHaveAttribute("aria-pressed", "true");
    expect(button).toHaveClass("text-brand");
  });

  it("shows the word Help beside the icon", () => {
    renderToggle();

    expect(screen.getByText("Help")).toBeInTheDocument();
  });

  it("is a type=button so it never submits a surrounding form", () => {
    renderToggle();

    expect(screen.getByRole("button", { name: "Turn help on" })).toHaveAttribute(
      "type",
      "button",
    );
  });

  it("hides the question-mark icon from assistive technology", () => {
    renderToggle();

    const icon = screen.getByRole("button", { name: "Turn help on" }).querySelector("svg");
    expect(icon).toHaveAttribute("aria-hidden", "true");
  });

  it("turns help on and stores it when pressed while help is off", () => {
    renderToggle();

    fireEvent.click(screen.getByRole("button", { name: "Turn help on" }));

    expect(screen.getByRole("button", { name: "Turn help off" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("1");
  });

  it("turns help off and stores it when pressed while help is on", () => {
    setHelpMode(true);
    renderToggle();

    fireEvent.click(screen.getByRole("button", { name: "Turn help off" }));

    expect(screen.getByRole("button", { name: "Turn help on" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("0");
  });

  it("returns to off after being pressed twice", () => {
    renderToggle();

    fireEvent.click(screen.getByRole("button", { name: "Turn help on" }));
    fireEvent.click(screen.getByRole("button", { name: "Turn help off" }));

    expect(screen.getByRole("button", { name: "Turn help on" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("follows help mode when it is switched on from elsewhere while mounted", () => {
    renderToggle();

    act(() => {
      setHelpMode(true);
    });

    expect(screen.getByRole("button", { name: "Turn help off" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("shows no tooltip until the button receives focus", () => {
    renderToggle();

    expect(tooltipText()).toBeNull();
  });

  it("explains what the button does when it is focused while help is off", () => {
    renderToggle();

    act(() => {
      screen.getByRole("button", { name: "Turn help on" }).focus();
    });

    expect(tooltipText()).toContain(OFF_TOOLTIP);
  });

  it("explains that help is on when it is focused while help is on", () => {
    setHelpMode(true);
    renderToggle();

    act(() => {
      screen.getByRole("button", { name: "Turn help off" }).focus();
    });

    expect(tooltipText()).toContain(ON_TOOLTIP);
    expect(tooltipText()).not.toContain(OFF_TOOLTIP);
  });

  it("closes the tooltip when the button loses focus", async () => {
    renderToggle();
    const button = screen.getByRole("button", { name: "Turn help on" });

    act(() => {
      button.focus();
    });
    expect(tooltipText()).toContain(OFF_TOOLTIP);

    act(() => {
      button.blur();
    });

    await waitFor(() => expect(tooltipText()).toBeNull());
  });
});
