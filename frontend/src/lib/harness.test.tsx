import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

/**
 * Proves the harness itself works before anything depends on it.
 *
 * Three separate things have to be wired correctly for a component test to run here --
 * the jsdom environment, the esbuild JSX transform, and the `@/` path alias -- and a
 * failure in any of them produces a confusing error in an unrelated test file. This
 * asserts each one directly.
 */
describe("test harness", () => {
  it("renders JSX through the esbuild transform", () => {
    render(<p>harness is alive</p>);
    expect(screen.getByText("harness is alive")).toBeInTheDocument();
  });

  it("has jest-dom matchers registered", () => {
    render(<button disabled>nope</button>);
    expect(screen.getByRole("button")).toBeDisabled();
  });

  it("resolves the @/ alias", async () => {
    const mod = await import("@/lib/format");
    expect(typeof mod.formatUsd).toBe("function");
  });
});
