import { act, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";

import { Gated } from "./Gated";

// Radix measures the floating tooltip content with ResizeObserver, which jsdom does not provide.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

const REASON = "Only a reviewer can release this case";

function renderGated(reason: string | null) {
  // Radix tooltips must sit under a provider; the app mounts one above the layout.
  return render(
    <TooltipProvider>
      <Gated reason={reason}>
        <button type="button">Release</button>
      </Gated>
    </TooltipProvider>,
  );
}

function openByFocus() {
  act(() => {
    screen.getByLabelText(REASON).focus();
  });
}

describe("Gated: no reason means the control is not locked", () => {
  beforeEach(() => {
    vi.stubGlobal("ResizeObserver", ResizeObserverStub);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the child untouched when the reason is null", () => {
    const { container } = renderGated(null);

    expect(screen.getByRole("button", { name: "Release" })).toBeInTheDocument();
    expect(container.querySelector('[tabindex="0"]')).toBeNull();
    expect(container.querySelector("[aria-label]")).toBeNull();
  });

  it("treats an empty reason the same as no reason", () => {
    const { container } = renderGated("");

    expect(screen.getByRole("button", { name: "Release" })).toBeInTheDocument();
    expect(container.querySelector('[tabindex="0"]')).toBeNull();
  });

  it("does not show a tooltip when there is no reason", () => {
    renderGated(null);

    expect(document.querySelector('[data-slot="tooltip-trigger"]')).toBeNull();
    expect(document.querySelector('[data-slot="tooltip-content"]')).toBeNull();
  });
});

describe("Gated: a reason locks the control and says why", () => {
  beforeEach(() => {
    vi.stubGlobal("ResizeObserver", ResizeObserverStub);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("wraps the child in a span labelled with the reason", () => {
    renderGated(REASON);

    const wrapper = screen.getByLabelText(REASON);
    expect(wrapper.tagName).toBe("SPAN");
    expect(wrapper).toContainElement(screen.getByRole("button", { name: "Release" }));
  });

  it("makes the wrapper reachable by keyboard", () => {
    renderGated(REASON);

    // A disabled button takes no focus, so the tooltip has to hang off a focusable span.
    expect(screen.getByLabelText(REASON)).toHaveAttribute("tabindex", "0");
  });

  it("does not render the reason as visible text until the wrapper is focused", () => {
    renderGated(REASON);

    expect(screen.queryByText(REASON)).not.toBeInTheDocument();
    expect(document.querySelector('[data-slot="tooltip-content"]')).toBeNull();
  });

  it("shows the reason in a tooltip when the wrapper receives focus", async () => {
    renderGated(REASON);

    openByFocus();

    const content = await waitFor(() => {
      const element = document.querySelector('[data-slot="tooltip-content"]');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });
    expect(within(content).getByText(REASON)).toBeInTheDocument();
  });

  it("shows the lock icon beside the reason in the tooltip", async () => {
    renderGated(REASON);

    openByFocus();

    const content = await waitFor(() => {
      const element = document.querySelector('[data-slot="tooltip-content"]');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });
    const icon = content.querySelector("svg");
    expect(icon).not.toBeNull();
    expect(icon).toHaveAttribute("aria-hidden");
  });

  it("keeps the reason verbatim, including punctuation from the API", async () => {
    const apiReason = "Blocked: 2 open N04 contradictions (see case) — ask a reviewer";
    render(
      <TooltipProvider>
        <Gated reason={apiReason}>
          <button type="button">Release</button>
        </Gated>
      </TooltipProvider>,
    );

    act(() => {
      screen.getByLabelText(apiReason).focus();
    });

    const content = await waitFor(() => {
      const element = document.querySelector('[data-slot="tooltip-content"]');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });
    expect(within(content).getByText(apiReason)).toBeInTheDocument();
  });
});
