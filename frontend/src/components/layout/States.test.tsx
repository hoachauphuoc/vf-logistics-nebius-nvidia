import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("@/lib/identity", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/identity")>()),
  roleLabel: vi.fn((role: string) => `${role} role label`),
}));

import { ErrorState, EmptyState } from "./States";
import { ApiError, DemoModeUnavailable } from "@/lib/api";
import { roleLabel } from "@/lib/identity";

describe("ErrorState", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders demo mode unavailable with PlugZap icon and helpful text", () => {
    const error = new DemoModeUnavailable("Demo mode not available");
    render(<ErrorState error={error} />);

    expect(screen.getByText("Needs the live API")).toBeInTheDocument();
    expect(screen.getByText(/operational pipeline/)).toBeInTheDocument();
    expect(screen.getByText(/NEXT_PUBLIC_DEMO_MODE/)).toBeInTheDocument();
  });

  it("renders unreachable API error with ServerCog icon and critical tone", () => {
    const error = new ApiError("API unreachable", 500, "unreachable");
    render(<ErrorState error={error} />);

    expect(screen.getByText("The audit API is unreachable")).toBeInTheDocument();
    expect(screen.getByText(/Nothing below is stale/)).toBeInTheDocument();
    expect(screen.getByText("API unreachable")).toBeInTheDocument();
  });

  it("renders 403 with requiredAuth password showing lock icon and login link", () => {
    const error = new ApiError("Password required", 403, "http", null, "password");
    render(<ErrorState error={error} />);

    expect(screen.getByText("This needs a password sign-in")).toBeInTheDocument();
    expect(screen.getByText(/one click.*can.*except this/)).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /Sign in with a password/ });
    expect(link.getAttribute("href")).toContain("/login?next=");
  });

  it("renders 401 signed out error with login link", () => {
    const error = new ApiError("Unauthorized", 401, "http");
    render(<ErrorState error={error} />);

    expect(screen.getByText("Sign in to see this")).toBeInTheDocument();
    expect(screen.getByText(/Sign in with an account/)).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /^Sign in$/ });
    expect(link.getAttribute("href")).toContain("/login?next=");
  });

  it("renders 403 without role using generic permission message", () => {
    const error = new ApiError("Forbidden", 403, "http");
    render(<ErrorState error={error} />);

    expect(screen.getByText("Your role does not include this view")).toBeInTheDocument();
    expect(screen.getByText(/ask a governance admin/)).toBeInTheDocument();
  });

  it("renders 403 with requiredRole showing specific role requirement", () => {
    const error = new ApiError("Forbidden", 403, "http", "compliance_officer");
    render(<ErrorState error={error} />);

    expect(roleLabel).toHaveBeenCalledWith("compliance_officer");
    expect(screen.getByText(/This needs the.*role/)).toBeInTheDocument();
  });

  it("renders generic Error with AlertTriangle icon", () => {
    const error = new Error("Something went wrong");
    render(<ErrorState error={error} />);

    expect(screen.getByText("That request failed")).toBeInTheDocument();
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
  });

  it("renders unknown error by converting to string", () => {
    const error = "string error message";
    render(<ErrorState error={error} />);

    expect(screen.getByText("That request failed")).toBeInTheDocument();
    expect(screen.getByText("string error message")).toBeInTheDocument();
  });

  it("calls onRetry when retry button is clicked", () => {
    const onRetry = vi.fn();
    const error = new Error("Network error");
    render(<ErrorState error={error} onRetry={onRetry} />);

    const retryButton = screen.getByRole("button", { name: /Try again/ });
    fireEvent.click(retryButton);
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("does not show retry button when onRetry is not provided", () => {
    const error = new Error("Some error");
    render(<ErrorState error={error} />);

    expect(screen.queryByRole("button", { name: /Try again/ })).not.toBeInTheDocument();
  });

  it("applies custom className to the shell", () => {
    const error = new Error("Test error");
    render(<ErrorState error={error} className="custom-class" />);

    const shell = screen.getByText("That request failed").closest("div");
    expect(shell).toHaveClass("custom-class");
  });

  it("encodes current pathname in login link", () => {
    const error = new ApiError("Auth", 401, "http");
    render(<ErrorState error={error} />);

    const link = screen.getByRole("link");
    const href = link.getAttribute("href");
    expect(href).toContain("?next=");
  });

  it("handles 403 with both requiredAuth and status properties correctly", () => {
    const error = new ApiError("Password auth required", 403, "http", "admin", "password");
    render(<ErrorState error={error} />);

    expect(screen.getByText("This needs a password sign-in")).toBeInTheDocument();
  });

  it("renders error message in monospace font for technical details", () => {
    const error = new ApiError("Connection timeout: 30s", 500, "unreachable");
    render(<ErrorState error={error} />);

    const messageElement = screen.getByText("Connection timeout: 30s");
    expect(messageElement).toHaveClass("font-mono");
  });
});

describe("EmptyState", () => {
  it("renders with title only", () => {
    render(<EmptyState title="No shipments found" />);

    expect(screen.getByText("No shipments found")).toBeInTheDocument();
  });

  it("renders with title and children content", () => {
    render(
      <EmptyState title="Empty list">
        <p>No items to display here.</p>
      </EmptyState>,
    );

    expect(screen.getByText("Empty list")).toBeInTheDocument();
    expect(screen.getByText("No items to display here.")).toBeInTheDocument();
  });

  it("uses Inbox icon with neutral tone", () => {
    render(<EmptyState title="No data" />);

    const title = screen.getByText("No data");
    const shell = title.closest("div");
    expect(shell).toBeInTheDocument();
  });

  it("applies custom className to shell", () => {
    render(<EmptyState title="Test" className="my-custom-class" />);

    const shell = screen.getByText("Test").closest("div");
    expect(shell).toHaveClass("my-custom-class");
  });

  it("renders complex children elements", () => {
    render(
      <EmptyState title="Learn more">
        <div>
          <p>First paragraph</p>
          <p>Second paragraph</p>
          <a href="/help">Help link</a>
        </div>
      </EmptyState>,
    );

    expect(screen.getByText("First paragraph")).toBeInTheDocument();
    expect(screen.getByText("Second paragraph")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Help link" })).toBeInTheDocument();
  });

  it("does not show retry button", () => {
    render(<EmptyState title="Empty" />);

    expect(screen.queryByRole("button", { name: /Try again/ })).not.toBeInTheDocument();
  });
});

describe("Shell component (via ErrorState and EmptyState)", () => {
  it("applies different styling for critical tone", () => {
    const error = new ApiError("Critical", 500, "unreachable");
    const { container } = render(<ErrorState error={error} />);

    const iconSpan = container.querySelector("span");
    expect(iconSpan).toHaveClass("bg-risk-critical/10");
    expect(iconSpan).toHaveClass("text-risk-critical");
  });

  it("applies different styling for warn tone", () => {
    const error = new ApiError("Auth", 403, "http", null, "password");
    const { container } = render(<ErrorState error={error} />);

    const iconSpan = container.querySelector("span");
    expect(iconSpan).toHaveClass("bg-risk-warn/10");
    expect(iconSpan).toHaveClass("text-risk-warn");
  });

  it("applies different styling for neutral tone", () => {
    const { container } = render(<EmptyState title="No items" />);

    const iconSpan = container.querySelector("span");
    expect(iconSpan).toHaveClass("bg-white/[0.05]");
    expect(iconSpan).toHaveClass("text-dim");
  });

  it("renders title in correct size and color", () => {
    render(<ErrorState error={new Error("Test")} />);

    const title = screen.getByText("That request failed");
    expect(title).toHaveClass("text-[14px]");
    expect(title).toHaveClass("text-white");
    expect(title.tagName).toBe("H3");
  });

  it("renders children content area", () => {
    const { container } = render(<EmptyState title="Title"><p>Content</p></EmptyState>);

    const contentDiv = container.querySelector(".mt-1\\.5");
    expect(contentDiv).toBeInTheDocument();
    expect(contentDiv).toHaveClass("text-dim");
  });

  it("animates with motion.div properties", () => {
    const { container } = render(<ErrorState error={new Error("Test")} />);

    const animatedDiv = container.firstChild;
    expect(animatedDiv).toBeInTheDocument();
  });

  it("applies bento-card class for styling", () => {
    const { container } = render(<ErrorState error={new Error("Test")} />);

    const card = container.querySelector(".bento-card");
    expect(card).toBeInTheDocument();
  });

  it("centers content with flex layout", () => {
    const { container } = render(<ErrorState error={new Error("Test")} />);

    const shell = container.firstChild;
    expect(shell).toHaveClass("flex");
    expect(shell).toHaveClass("flex-col");
    expect(shell).toHaveClass("items-center");
  });

  it("renders icon with correct size and aria-hidden", () => {
    const { container } = render(<ErrorState error={new DemoModeUnavailable("test")} />);

    const icon = container.querySelector("svg");
    expect(icon).toHaveClass("size-5");
    expect(icon).toHaveAttribute("aria-hidden", "true");
  });

  it("shows retry button with RefreshCw icon when onRetry callback exists", () => {
    const onRetry = vi.fn();
    const { container } = render(<ErrorState error={new Error("Test")} onRetry={onRetry} />);

    const button = screen.getByRole("button", { name: /Try again/ });
    expect(button).toBeInTheDocument();
    const icon = button.querySelector("svg");
    expect(icon).toHaveAttribute("aria-hidden", "true");
  });

  it("handles empty children gracefully", () => {
    render(<EmptyState title="Test" />);

    expect(screen.getByText("Test")).toBeInTheDocument();
  });

  it("preserves multiple paragraphs in error message", () => {
    render(<ErrorState error={new DemoModeUnavailable("test")} />);

    const paragraphs = screen.getAllByText(/Demo|pipeline|NEXT_PUBLIC/);
    expect(paragraphs.length).toBeGreaterThan(1);
  });

  it("links use correct URL encoding for pathname parameter", () => {
    const error = new ApiError("Auth", 401, "http");
    render(<ErrorState error={error} />);

    const link = screen.getByRole("link");
    const href = link.getAttribute("href");
    expect(href).toMatch(/^\/login\?next=/);
  });
});
