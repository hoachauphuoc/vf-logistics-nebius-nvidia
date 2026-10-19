import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Badge, badgeVariants } from "./badge";

describe("Badge component", () => {
  it("renders as a span by default", () => {
    render(<Badge data-testid="badge">Content</Badge>);
    const badge = screen.getByTestId("badge");
    expect(badge.tagName).toBe("SPAN");
  });

  it("renders with the correct data-slot attribute", () => {
    render(<Badge data-testid="badge">Content</Badge>);
    const badge = screen.getByTestId("badge");
    expect(badge.getAttribute("data-slot")).toBe("badge");
  });

  it("renders with default variant when not specified", () => {
    render(<Badge data-testid="badge">Content</Badge>);
    const badge = screen.getByTestId("badge");
    expect(badge.getAttribute("data-variant")).toBe("default");
  });

  describe("variant prop", () => {
    const variants = ["default", "secondary", "destructive", "outline", "ghost", "link"] as const;

    for (const variant of variants) {
      it(`renders with ${variant} variant`, () => {
        render(
          <Badge variant={variant} data-testid="badge">
            Content
          </Badge>,
        );
        const badge = screen.getByTestId("badge");
        expect(badge.getAttribute("data-variant")).toBe(variant);
      });

      it(`applies ${variant} variant styles`, () => {
        render(
          <Badge variant={variant} data-testid="badge">
            Content
          </Badge>,
        );
        const badge = screen.getByTestId("badge");
        const classes = badge.className;
        expect(classes).toBeTruthy();
        // Base badge classes should be present for all variants
        expect(classes).toContain("group/badge");
        expect(classes).toContain("inline-flex");
      });
    }
  });

  it("renders with custom className merged alongside variant styles", () => {
    render(
      <Badge className="custom-class" data-testid="badge">
        Content
      </Badge>,
    );
    const badge = screen.getByTestId("badge");
    expect(badge.className).toContain("custom-class");
    expect(badge.className).toContain("group/badge");
  });

  it("renders with multiple custom classes", () => {
    render(
      <Badge className="class-one class-two" data-testid="badge">
        Content
      </Badge>,
    );
    const badge = screen.getByTestId("badge");
    expect(badge.className).toContain("class-one");
    expect(badge.className).toContain("class-two");
  });

  it("renders text content", () => {
    render(<Badge>Badge Text</Badge>);
    expect(screen.getByText("Badge Text")).toBeInTheDocument();
  });

  it("renders element children", () => {
    render(
      <Badge>
        <span data-testid="icon">→</span>
        Label
      </Badge>,
    );
    expect(screen.getByTestId("icon")).toBeInTheDocument();
    expect(screen.getByText("Label")).toBeInTheDocument();
  });

  it("passes through HTML attributes", () => {
    render(
      <Badge
        data-testid="badge"
        aria-label="Important"
        title="Tooltip text"
        id="custom-id"
      >
        Content
      </Badge>,
    );
    const badge = screen.getByTestId("badge");
    expect(badge.getAttribute("aria-label")).toBe("Important");
    expect(badge.getAttribute("title")).toBe("Tooltip text");
    expect(badge.getAttribute("id")).toBe("custom-id");
  });

  it("applies aria-invalid attribute when passed", () => {
    render(
      <Badge aria-invalid="true" data-testid="badge">
        Invalid
      </Badge>,
    );
    const badge = screen.getByTestId("badge");
    expect(badge.getAttribute("aria-invalid")).toBe("true");
  });

  it("handles aria-invalid false", () => {
    render(
      <Badge aria-invalid="false" data-testid="badge">
        Valid
      </Badge>,
    );
    const badge = screen.getByTestId("badge");
    expect(badge.getAttribute("aria-invalid")).toBe("false");
  });

  it("combines variant and custom className without losing either", () => {
    render(
      <Badge variant="secondary" className="override" data-testid="badge">
        Combined
      </Badge>,
    );
    const badge = screen.getByTestId("badge");
    expect(badge.getAttribute("data-variant")).toBe("secondary");
    expect(badge.className).toContain("override");
    // Base styles should still be present
    expect(badge.className).toContain("inline-flex");
  });

  it("preserves variant when className is provided", () => {
    const variants = ["default", "secondary", "destructive", "outline", "ghost", "link"] as const;
    for (const variant of variants) {
      const { unmount } = render(
        <Badge variant={variant} className="custom" data-testid="badge">
          Test
        </Badge>,
      );
      const badge = screen.getByTestId("badge");
      expect(badge.getAttribute("data-variant")).toBe(variant);
      unmount();
    }
  });

  it("handles empty content", () => {
    render(<Badge data-testid="badge" />);
    const badge = screen.getByTestId("badge");
    expect(badge).toBeInTheDocument();
  });

  it("handles whitespace-only content", () => {
    render(<Badge data-testid="badge">   </Badge>);
    const badge = screen.getByTestId("badge");
    expect(badge).toBeInTheDocument();
  });

  it("renders with asChild prop", () => {
    render(
      <Badge asChild data-testid="badge">
        <button>Click me</button>
      </Badge>,
    );
    // When asChild is true, Slot.Root merges props to the child
    const button = screen.getByRole("button");
    expect(button).toBeInTheDocument();
  });

  it("applies variant to asChild element", () => {
    render(
      <Badge asChild variant="destructive" data-testid="custom-element">
        <div>Custom</div>
      </Badge>,
    );
    const element = screen.getByText("Custom");
    expect(element.getAttribute("data-variant")).toBe("destructive");
  });

  it("applies data-slot to asChild element", () => {
    render(
      <Badge asChild data-testid="custom-element">
        <div>Custom</div>
      </Badge>,
    );
    const element = screen.getByText("Custom");
    expect(element.getAttribute("data-slot")).toBe("badge");
  });

  it("applies custom className with asChild", () => {
    render(
      <Badge asChild className="custom" data-testid="custom-element">
        <div>Custom</div>
      </Badge>,
    );
    const element = screen.getByText("Custom");
    expect(element.className).toContain("custom");
  });

  it("preserves asChild element's own attributes", () => {
    render(
      <Badge asChild>
        <button type="submit" data-testid="submit-btn">
          Submit
        </button>
      </Badge>,
    );
    const button = screen.getByTestId("submit-btn");
    expect(button.getAttribute("type")).toBe("submit");
  });

  it("handles asChild with link element", () => {
    render(
      <Badge asChild variant="link">
        <a href="/test" data-testid="link-badge">
          Link Badge
        </a>
      </Badge>,
    );
    const link = screen.getByTestId("link-badge");
    expect(link.getAttribute("href")).toBe("/test");
    expect(link.getAttribute("data-variant")).toBe("link");
  });

  it("does not require className prop", () => {
    render(
      <Badge variant="default" data-testid="badge">
        No className
      </Badge>,
    );
    const badge = screen.getByTestId("badge");
    expect(badge).toBeInTheDocument();
    expect(badge.className).toBeTruthy();
  });

  it("does not require variant prop", () => {
    render(
      <Badge className="only-class" data-testid="badge">
        Only className
      </Badge>,
    );
    const badge = screen.getByTestId("badge");
    expect(badge).toBeInTheDocument();
    expect(badge.getAttribute("data-variant")).toBe("default");
  });
});

describe("badgeVariants CVA export", () => {
  it("exports badgeVariants function", () => {
    expect(typeof badgeVariants).toBe("function");
  });

  it("generates class strings for each variant", () => {
    const variants = ["default", "secondary", "destructive", "outline", "ghost", "link"] as const;
    for (const variant of variants) {
      const classes = badgeVariants({ variant });
      expect(typeof classes).toBe("string");
      expect(classes.length).toBeGreaterThan(0);
    }
  });

  it("generates classes for default variant when no variant is specified", () => {
    const classes = badgeVariants({});
    expect(typeof classes).toBe("string");
    expect(classes.length).toBeGreaterThan(0);
    // Should include base badge classes
    expect(classes).toContain("group/badge");
  });

  it("returns consistent classes for the same variant", () => {
    const classes1 = badgeVariants({ variant: "secondary" });
    const classes2 = badgeVariants({ variant: "secondary" });
    expect(classes1).toBe(classes2);
  });

  it("returns different classes for different variants", () => {
    const defaultClasses = badgeVariants({ variant: "default" });
    const destructiveClasses = badgeVariants({ variant: "destructive" });
    expect(defaultClasses).not.toBe(destructiveClasses);
  });
});
