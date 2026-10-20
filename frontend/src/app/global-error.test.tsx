import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import GlobalError from "./global-error";

function errorWith(message: string, digest?: string): Error & { digest?: string } {
  const error = new Error(message);
  if (digest !== undefined) {
    Object.assign(error, { digest });
  }
  return error;
}

describe("GlobalError", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("tells the user the console failed to start and that reloading is the only recovery", () => {
    render(<GlobalError error={errorWith("boom")} />);

    expect(screen.getByRole("heading", { name: "The console failed to start" })).toBeInTheDocument();
    expect(screen.getByText(/reloading is the only recovery from here/)).toBeInTheDocument();
  });

  it("shows the error message in the details line", () => {
    render(<GlobalError error={errorWith("Failed to fetch config")} />);

    expect(screen.getByText("Failed to fetch config")).toBeInTheDocument();
  });

  it("appends the digest to the message when the error carries one", () => {
    render(<GlobalError error={errorWith("boom", "3141592")} />);

    expect(screen.getByText("boom · digest 3141592")).toBeInTheDocument();
  });

  it("shows no digest when the error has none", () => {
    render(<GlobalError error={errorWith("boom")} />);

    expect(screen.getByText("boom")).toBeInTheDocument();
    expect(screen.queryByText(/digest/)).not.toBeInTheDocument();
  });

  it("shows a fallback line when the error has an empty message", () => {
    render(<GlobalError error={errorWith("")} />);

    expect(screen.getByText("No message on the error object.")).toBeInTheDocument();
  });

  it("logs the error to the console when it is rendered", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const error = errorWith("boom");

    render(<GlobalError error={error} />);

    expect(consoleError).toHaveBeenCalledWith("[global-error]", error);
  });

  it("logs again when the boundary receives a different error", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const first = errorWith("first");
    const second = errorWith("second");

    const { rerender } = render(<GlobalError error={first} />);
    rerender(<GlobalError error={second} />);

    expect(consoleError).toHaveBeenLastCalledWith("[global-error]", second);
    expect(screen.getByText("second")).toBeInTheDocument();
  });

  it("offers a reload button that does not throw when clicked", () => {
    render(<GlobalError error={errorWith("boom")} />);

    const button = screen.getByRole("button", { name: "Reload the console" });
    expect(button).toHaveAttribute("type", "button");
    expect(() => fireEvent.click(button)).not.toThrow();
  });
});
