import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";

import RouteError from "@/app/error";

/**
 * A boundary that has never been seen to catch anything is a claim.
 *
 * These render the boundary directly with the props Next passes it, rather than throwing
 * inside a child and relying on React's boundary machinery. That is deliberate: React
 * error boundaries in a test environment swallow the throw and print a large stack, which
 * makes the suite output unreadable without proving anything extra. What matters is that
 * the boundary renders something useful given an error, and that it wires `reset`.
 */
describe("route error boundary", () => {
  beforeEach(() => {
    // The boundary logs the error on mount by design. Silenced so the suite output stays
    // readable, and asserted below so the logging is not accidentally removed.
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("names the failure without blaming the user", () => {
    render(<RouteError error={new Error("boom")} reset={() => {}} />);
    expect(screen.getByText("This screen failed to render")).toBeInTheDocument();
  });

  it("surfaces the error message so the failure is diagnosable", () => {
    render(<RouteError error={new Error("cannot read cost_usd")} reset={() => {}} />);
    expect(screen.getByText(/cannot read cost_usd/)).toBeInTheDocument();
  });

  it("does not render an empty message block when the error has none", () => {
    // `new Error()` has `message === ""`. Rendering nothing there leaves a bare panel
    // that looks like a layout bug rather than an error.
    render(<RouteError error={new Error()} reset={() => {}} />);
    expect(screen.getByText(/No message on the error object/)).toBeInTheDocument();
  });

  it("offers a recovery path", () => {
    const reset = vi.fn();
    render(<RouteError error={new Error("boom")} reset={reset} />);
    const button = screen.getByRole("button", { name: /try this screen again/i });
    button.click();
    expect(reset).toHaveBeenCalledOnce();
  });

  it("logs the error rather than swallowing it", () => {
    const error = new Error("boom");
    render(<RouteError error={error} reset={() => {}} />);
    expect(console.error).toHaveBeenCalledWith("[route-error]", error);
  });

  it("states that nothing was written, because that is the reviewer's first question", () => {
    render(<RouteError error={new Error("boom")} reset={() => {}} />);
    expect(screen.getByText(/no case was changed/i)).toBeInTheDocument();
  });
});
