import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setHelpMode } from "@/lib/help-mode";

import { HelpDot } from "./HelpDot";

// Radix popper measures the trigger and content with ResizeObserver, which jsdom
// does not implement. Opening the popover would throw without this stub.
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

describe("HelpDot", () => {
  beforeEach(() => {
    vi.stubGlobal("ResizeObserver", ResizeObserverStub);
    window.localStorage.clear();
    setHelpMode(false);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders nothing when help mode is off", () => {
    const { container } = render(<HelpDot id="nav:/today" />);

    expect(container).toBeEmptyDOMElement();
  });

  it("shows a button named after the entry title when help mode is on", () => {
    setHelpMode(true);
    render(<HelpDot id="nav:/today" />);

    expect(
      screen.getByRole("button", { name: "What is Today?" }),
    ).toBeInTheDocument();
  });

  it("makes the button a type=button so it never submits a surrounding form", () => {
    setHelpMode(true);
    render(<HelpDot id="nav:/today" />);

    expect(screen.getByRole("button", { name: "What is Today?" })).toHaveAttribute(
      "type",
      "button",
    );
  });

  it("hides the question-mark icon from assistive technology", () => {
    setHelpMode(true);
    render(<HelpDot id="nav:/today" />);

    const icon = screen.getByRole("button", { name: "What is Today?" }).querySelector("svg");
    expect(icon).toHaveAttribute("aria-hidden", "true");
  });

  it("applies the className prop to the button", () => {
    setHelpMode(true);
    render(<HelpDot id="nav:/today" className="ml-2" />);

    expect(screen.getByRole("button", { name: "What is Today?" })).toHaveClass("ml-2");
  });

  it("does not show the explanation until the button is clicked", () => {
    setHelpMode(true);
    render(<HelpDot id="nav:/today" />);

    expect(screen.queryByText(/Every case waiting on someone/)).not.toBeInTheDocument();
  });

  it("shows the title and body of the entry when the button is clicked", () => {
    setHelpMode(true);
    render(<HelpDot id="nav:/today" />);

    fireEvent.click(screen.getByRole("button", { name: "What is Today?" }));

    expect(screen.getByText("Today")).toBeInTheDocument();
    expect(screen.getByText(/Every case waiting on someone/)).toBeInTheDocument();
  });

  it("shows the note under the body when the entry has one", () => {
    setHelpMode(true);
    render(<HelpDot id="nav:/today" />);

    fireEvent.click(screen.getByRole("button", { name: "What is Today?" }));

    expect(screen.getByText(/The grouping comes from the API/)).toBeInTheDocument();
  });

  it("shows only the title and body when the entry has no note", () => {
    setHelpMode(true);
    render(<HelpDot id="state:INGESTED" />);

    fireEvent.click(screen.getByRole("button", { name: "What is Queued?" }));

    expect(screen.getByText("Queued")).toBeInTheDocument();
    expect(
      document.querySelectorAll('[data-slot="popover-content"] p'),
    ).toHaveLength(2);
  });

  it("closes the explanation when Escape is pressed", async () => {
    setHelpMode(true);
    render(<HelpDot id="nav:/today" />);

    fireEvent.click(screen.getByRole("button", { name: "What is Today?" }));
    expect(screen.getByText("Today")).toBeInTheDocument();

    fireEvent.keyDown(document.body, { key: "Escape" });

    await waitFor(() =>
      expect(screen.queryByText(/Every case waiting on someone/)).not.toBeInTheDocument(),
    );
  });

  it("does not let a click on the button reach the card it sits in", () => {
    const onCardClick = vi.fn();
    setHelpMode(true);
    render(
      <div onClick={onCardClick}>
        <HelpDot id="nav:/today" />
      </div>,
    );

    fireEvent.click(screen.getByRole("button", { name: "What is Today?" }));

    expect(onCardClick).not.toHaveBeenCalled();
  });

  it("renders nothing for a nav id that has no help entry", () => {
    setHelpMode(true);
    const { container } = render(<HelpDot id="nav:/does-not-exist" />);

    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for a plain id that has no help entry", () => {
    setHelpMode(true);
    const { container } = render(<HelpDot id="no.such.panel" />);

    expect(container).toBeEmptyDOMElement();
  });

  it("does not fall back to another table when the prefix does not match", () => {
    setHelpMode(true);
    // "/today" is a nav key, not a state key, so the state: prefix must not find it.
    const { container } = render(<HelpDot id="state:/today" />);

    expect(container).toBeEmptyDOMElement();
  });

  it("shows the button once help mode is switched on while mounted", () => {
    const { container } = render(<HelpDot id="nav:/today" />);
    expect(container).toBeEmptyDOMElement();

    act(() => {
      setHelpMode(true);
    });

    expect(
      screen.getByRole("button", { name: "What is Today?" }),
    ).toBeInTheDocument();
  });

  it("removes the button when help mode is switched off while mounted", () => {
    setHelpMode(true);
    const { container } = render(<HelpDot id="nav:/today" />);
    expect(screen.getByRole("button", { name: "What is Today?" })).toBeInTheDocument();

    act(() => {
      setHelpMode(false);
    });

    expect(container).toBeEmptyDOMElement();
  });
});
