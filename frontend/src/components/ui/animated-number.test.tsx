import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

const mocks = vi.hoisted(() => ({
  useSpring: vi.fn(),
  useTransform: vi.fn(),
  motion: {
    span: vi.fn(),
  },
}));

vi.mock("framer-motion", () => ({
  useSpring: mocks.useSpring,
  useTransform: mocks.useTransform,
  motion: {
    span: mocks.motion.span,
  },
}));

import { AnimatedNumber } from "./animated-number";

describe("AnimatedNumber", () => {
  const mockSpringValue = { set: vi.fn() };

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.useSpring.mockReturnValue(mockSpringValue);
    // useTransform returns a function that creates a display value
    mocks.useTransform.mockImplementation(
      (_spring: unknown, fn: (v: number) => string) => fn(0),
    );
    // motion.span is a real React component that renders children
    mocks.motion.span.mockImplementation(
      ({ children, className }: { children: ReactNode; className?: string }) => (
        <span className={className}>{children}</span>
      ),
    );
  });

  it("initializes spring with zero and correct options", () => {
    render(<AnimatedNumber value={50} />);
    expect(mocks.useSpring).toHaveBeenCalledWith(0, { bounce: 0, duration: 600 });
  });

  it("calls spring.set() with value prop on mount", () => {
    render(<AnimatedNumber value={100} />);
    expect(mockSpringValue.set).toHaveBeenCalledWith(100);
  });

  it("calls spring.set() when value prop changes", () => {
    const { rerender } = render(<AnimatedNumber value={50} />);
    mockSpringValue.set.mockClear();
    rerender(<AnimatedNumber value={75} />);
    expect(mockSpringValue.set).toHaveBeenCalledWith(75);
  });

  it("uses custom format function when provided", () => {
    const customFormat = vi.fn((n: number) => `$${n.toFixed(2)}`);
    mocks.useTransform.mockImplementation(
      (_spring: unknown, fn: (v: number) => string) => fn(42.5),
    );
    render(<AnimatedNumber value={42} format={customFormat} />);
    expect(customFormat).toHaveBeenCalled();
  });

  it("uses default format (Math.round + toLocaleString) when format not provided", () => {
    mocks.useTransform.mockImplementation(
      (_spring: unknown, fn: (v: number) => string) => fn(42.7),
    );
    render(<AnimatedNumber value={42} />);
    const [, transformFn] = mocks.useTransform.mock.calls[0] as [unknown, (v: number) => string];
    const result = transformFn(42.7);
    expect(result).toBe("43");
  });

  it("applies className prop to span", () => {
    const { container } = render(<AnimatedNumber value={42} className="text-lg" />);
    expect(container.querySelector(".text-lg")).toBeInTheDocument();
  });

  it("handles zero value", () => {
    render(<AnimatedNumber value={0} />);
    expect(mockSpringValue.set).toHaveBeenCalledWith(0);
  });

  it("handles negative values", () => {
    render(<AnimatedNumber value={-42} />);
    expect(mockSpringValue.set).toHaveBeenCalledWith(-42);
  });

  it("formats large numbers with commas", () => {
    mocks.useTransform.mockImplementation(
      (_spring: unknown, fn: (v: number) => string) => fn(1000000),
    );
    render(<AnimatedNumber value={1000000} />);
    const [, transformFn] = mocks.useTransform.mock.calls[0] as [unknown, (v: number) => string];
    const result = transformFn(1000000);
    expect(result).toBe("1,000,000");
  });

  it("renders motion.span with className", () => {
    render(<AnimatedNumber value={42} className="custom" />);
    expect(mocks.motion.span).toHaveBeenCalledWith(
      expect.objectContaining({ className: "custom", children: expect.any(String) }),
      undefined,
    );
  });

  it("sequential value updates trigger spring animation each time", () => {
    const { rerender } = render(<AnimatedNumber value={10} />);
    expect(mockSpringValue.set).toHaveBeenCalledWith(10);

    mockSpringValue.set.mockClear();
    rerender(<AnimatedNumber value={20} />);
    expect(mockSpringValue.set).toHaveBeenCalledWith(20);

    mockSpringValue.set.mockClear();
    rerender(<AnimatedNumber value={30} />);
    expect(mockSpringValue.set).toHaveBeenCalledWith(30);
  });

  it("passes spring value to transform for animation", () => {
    render(<AnimatedNumber value={42} />);
    expect(mocks.useTransform).toHaveBeenCalled();
    const [springArg] = mocks.useTransform.mock.calls[0] as [unknown, (v: number) => string];
    expect(springArg).toBe(mockSpringValue);
  });

  it("renders without className when not provided", () => {
    const { container } = render(<AnimatedNumber value={42} />);
    const span = container.querySelector("span");
    expect(span).toBeInTheDocument();
    expect(span).not.toHaveAttribute("class");
  });
});
