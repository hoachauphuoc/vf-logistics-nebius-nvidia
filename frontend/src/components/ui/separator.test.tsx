import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Separator } from "./separator";

function getSeparator(container: HTMLElement): HTMLElement {
  const element = container.querySelector('[data-slot="separator"]');
  expect(element).not.toBeNull();
  return element as HTMLElement;
}

describe("separator", () => {
  it("renders an empty element marked with the separator slot", () => {
    const { container } = render(<Separator />);

    const element = getSeparator(container);
    expect(element.tagName).toBe("DIV");
    expect(element).toBeEmptyDOMElement();
  });

  it("is decorative by default, so it exposes no separator role to assistive technology", () => {
    const { container } = render(<Separator />);

    const element = getSeparator(container);
    expect(element).toHaveAttribute("role", "none");
    expect(element).not.toHaveAttribute("aria-orientation");
    expect(screen.queryByRole("separator")).toBeNull();
  });

  it("is horizontal by default, with the horizontal sizing classes", () => {
    const { container } = render(<Separator />);

    const element = getSeparator(container);
    expect(element).toHaveAttribute("data-orientation", "horizontal");
    expect(element).toHaveClass("data-horizontal:h-px");
    expect(element).toHaveClass("data-horizontal:w-full");
  });

  it("applies the vertical orientation and its sizing classes when orientation is vertical", () => {
    const { container } = render(<Separator orientation="vertical" />);

    const element = getSeparator(container);
    expect(element).toHaveAttribute("data-orientation", "vertical");
    expect(element).toHaveClass("data-vertical:w-px");
    expect(element).toHaveClass("data-vertical:self-stretch");
  });

  it("exposes a separator role when decorative is false", () => {
    render(<Separator decorative={false} />);

    const separator = screen.getByRole("separator");
    expect(separator).toHaveAttribute("data-slot", "separator");
    expect(separator).not.toHaveAttribute("aria-orientation");
  });

  it("reports vertical aria-orientation when a non-decorative separator is vertical", () => {
    render(<Separator decorative={false} orientation="vertical" />);

    expect(screen.getByRole("separator")).toHaveAttribute("aria-orientation", "vertical");
  });

  it("keeps the role none when decorative is explicitly true", () => {
    const { container } = render(<Separator decorative={true} />);

    expect(getSeparator(container)).toHaveAttribute("role", "none");
  });

  it("merges a custom className with the default separator classes", () => {
    const { container } = render(<Separator className="my-4 custom-rule" />);

    const element = getSeparator(container);
    expect(element).toHaveClass("custom-rule");
    expect(element).toHaveClass("my-4");
    expect(element).toHaveClass("bg-border");
    expect(element).toHaveClass("shrink-0");
  });

  it("passes extra DOM attributes through to the element", () => {
    const { container } = render(<Separator id="section-rule" data-testid="rule" />);

    const element = getSeparator(container);
    expect(element).toHaveAttribute("id", "section-rule");
    expect(screen.getByTestId("rule")).toBe(element);
  });
});
