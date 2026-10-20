import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "./card";

describe("Card", () => {
  it("renders its children inside a div marked as a card", () => {
    render(<Card>Body text</Card>);

    const card = screen.getByText("Body text");
    expect(card.tagName).toBe("DIV");
    expect(card).toHaveAttribute("data-slot", "card");
  });

  it("uses the default size when no size is given", () => {
    render(<Card>Default</Card>);

    expect(screen.getByText("Default")).toHaveAttribute("data-size", "default");
  });

  it("marks the card as small when size is sm", () => {
    render(<Card size="sm">Small</Card>);

    expect(screen.getByText("Small")).toHaveAttribute("data-size", "sm");
  });

  it("keeps the base card classes and appends a caller className", () => {
    render(<Card className="my-card">Styled</Card>);

    const card = screen.getByText("Styled");
    expect(card).toHaveClass("my-card");
    expect(card).toHaveClass("rounded-xl");
  });

  it("passes extra attributes through to the DOM element", () => {
    render(
      <Card data-testid="case-card" aria-label="Shipment case">
        Attributes
      </Card>
    );

    const card = screen.getByTestId("case-card");
    expect(card).toHaveAttribute("aria-label", "Shipment case");
    expect(card).toHaveTextContent("Attributes");
  });
});

describe("CardHeader", () => {
  it("renders a header slot with its children", () => {
    render(<CardHeader>Header text</CardHeader>);

    const header = screen.getByText("Header text");
    expect(header).toHaveAttribute("data-slot", "card-header");
  });

  it("appends a caller className to the header", () => {
    render(<CardHeader className="extra-header">Header</CardHeader>);

    const header = screen.getByText("Header");
    expect(header).toHaveClass("extra-header");
    expect(header).toHaveClass("grid");
  });
});

describe("CardTitle", () => {
  it("renders the title text in a title slot", () => {
    render(<CardTitle>Shipment 42</CardTitle>);

    const title = screen.getByText("Shipment 42");
    expect(title).toHaveAttribute("data-slot", "card-title");
    expect(title).toHaveClass("font-medium");
  });

  it("appends a caller className to the title", () => {
    render(<CardTitle className="big-title">Title</CardTitle>);

    expect(screen.getByText("Title")).toHaveClass("big-title");
  });
});

describe("CardDescription", () => {
  it("renders the description in a muted description slot", () => {
    render(<CardDescription>Explains the case</CardDescription>);

    const description = screen.getByText("Explains the case");
    expect(description).toHaveAttribute("data-slot", "card-description");
    expect(description).toHaveClass("text-muted-foreground");
  });

  it("appends a caller className to the description", () => {
    render(<CardDescription className="tight">Desc</CardDescription>);

    expect(screen.getByText("Desc")).toHaveClass("tight");
  });
});

describe("CardAction", () => {
  it("renders the action slot and runs its click handler", () => {
    const onClick = vi.fn();
    render(
      <CardAction>
        <button type="button" onClick={onClick}>
          Review
        </button>
      </CardAction>
    );

    const action = screen.getByRole("button", { name: "Review" }).parentElement;
    expect(action).toHaveAttribute("data-slot", "card-action");

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("appends a caller className to the action slot", () => {
    render(
      <CardAction className="action-extra" data-testid="action">
        Act
      </CardAction>
    );

    expect(screen.getByTestId("action")).toHaveClass("action-extra");
  });
});

describe("CardContent", () => {
  it("renders the content slot with its children", () => {
    render(<CardContent>Main content</CardContent>);

    expect(screen.getByText("Main content")).toHaveAttribute(
      "data-slot",
      "card-content"
    );
  });

  it("appends a caller className to the content", () => {
    render(<CardContent className="pad-more">Content</CardContent>);

    expect(screen.getByText("Content")).toHaveClass("pad-more");
  });
});

describe("CardFooter", () => {
  it("renders the footer slot with a top border", () => {
    render(<CardFooter>Footer text</CardFooter>);

    const footer = screen.getByText("Footer text");
    expect(footer).toHaveAttribute("data-slot", "card-footer");
    expect(footer).toHaveClass("border-t");
  });

  it("appends a caller className to the footer", () => {
    render(<CardFooter className="footer-extra">Footer</CardFooter>);

    expect(screen.getByText("Footer")).toHaveClass("footer-extra");
  });
});

describe("composed card", () => {
  it("renders header, title, description, action, content and footer inside the card", () => {
    render(
      <Card data-testid="full-card">
        <CardHeader>
          <CardTitle>Case A</CardTitle>
          <CardDescription>Flagged for review</CardDescription>
          <CardAction>
            <button type="button">Open</button>
          </CardAction>
        </CardHeader>
        <CardContent>Evidence list</CardContent>
        <CardFooter>Updated today</CardFooter>
      </Card>
    );

    const card = screen.getByTestId("full-card");
    expect(card).toHaveAttribute("data-slot", "card");
    expect(card).toContainElement(screen.getByText("Case A"));
    expect(card).toContainElement(screen.getByText("Flagged for review"));
    expect(card).toContainElement(screen.getByRole("button", { name: "Open" }));
    expect(card).toContainElement(screen.getByText("Evidence list"));
    expect(card).toContainElement(screen.getByText("Updated today"));
  });
});
