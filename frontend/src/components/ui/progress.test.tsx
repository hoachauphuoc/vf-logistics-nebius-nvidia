import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Progress } from "./progress";

function indicatorOf(bar: HTMLElement): HTMLElement {
  const indicator = bar.querySelector<HTMLElement>('[data-slot="progress-indicator"]');
  if (!indicator) throw new Error("no progress indicator rendered");
  return indicator;
}

// Progress does not forward `value` to the Radix root, so value-driven ARIA
// and indicator assertions are left out until the source passes it through.
describe("Progress", () => {
  it("renders a progressbar tagged with the progress slot", () => {
    render(<Progress value={40} />);

    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("data-slot", "progress");
  });

  it("exposes a progressbar range from 0 to 100 by default", () => {
    render(<Progress value={40} />);

    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuemin", "0");
    expect(bar).toHaveAttribute("aria-valuemax", "100");
  });

  it("reports an absent value as indeterminate with no aria-valuenow", () => {
    render(<Progress />);

    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("data-state", "indeterminate");
    expect(bar).not.toHaveAttribute("aria-valuenow");
    expect(bar).not.toHaveAttribute("data-value");
  });

  it("reports a null value as indeterminate", () => {
    render(<Progress value={null} />);

    expect(screen.getByRole("progressbar")).toHaveAttribute("data-state", "indeterminate");
  });

  it("moves the indicator fully out of view when the value is absent", () => {
    render(<Progress />);

    const indicator = indicatorOf(screen.getByRole("progressbar"));
    expect(indicator).toHaveStyle({ transform: "translateX(-100%)" });
    expect(indicator).toHaveAttribute("data-state", "indeterminate");
  });

  it("gives the indicator the primary colour and transition classes", () => {
    render(<Progress value={10} />);

    const indicator = indicatorOf(screen.getByRole("progressbar"));
    expect(indicator).toHaveClass("bg-primary");
    expect(indicator).toHaveClass("transition-all");
  });

  it("merges a caller className with the base track classes", () => {
    render(<Progress value={10} className="h-3 custom-track" />);

    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveClass("custom-track");
    expect(bar).toHaveClass("h-3");
    expect(bar).toHaveClass("bg-muted");
    expect(bar).toHaveClass("rounded-full");
  });

  it("forwards extra props such as aria-label to the progressbar", () => {
    render(<Progress value={25} aria-label="Upload progress" />);

    expect(screen.getByRole("progressbar", { name: "Upload progress" })).toBeInTheDocument();
  });

  it("uses the caller's max for the progressbar range", () => {
    render(<Progress value={50} max={200} />);

    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuemax", "200");
    expect(bar).toHaveAttribute("data-max", "200");
  });
});
