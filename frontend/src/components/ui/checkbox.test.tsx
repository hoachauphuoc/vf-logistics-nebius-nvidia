import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Checkbox } from "./checkbox";

describe("Checkbox", () => {
  it("renders an unchecked checkbox with the slot marker", () => {
    render(<Checkbox aria-label="Accept terms" />);
    const box = screen.getByRole("checkbox", { name: "Accept terms" });
    expect(box).toHaveAttribute("aria-checked", "false");
    expect(box).toHaveAttribute("data-state", "unchecked");
    expect(box).toHaveAttribute("data-slot", "checkbox");
  });

  it("draws no check indicator while unchecked", () => {
    const { container } = render(<Checkbox aria-label="Accept terms" />);
    expect(container.querySelector('[data-slot="checkbox-indicator"]')).toBeNull();
  });

  it("starts checked when defaultChecked is set and draws the indicator", () => {
    const { container } = render(<Checkbox aria-label="Accept terms" defaultChecked />);
    expect(screen.getByRole("checkbox", { name: "Accept terms" })).toHaveAttribute(
      "aria-checked",
      "true"
    );
    expect(container.querySelector('[data-slot="checkbox-indicator"]')).not.toBeNull();
  });

  it("becomes checked when the user clicks an unchecked box", () => {
    render(<Checkbox aria-label="Accept terms" />);
    fireEvent.click(screen.getByRole("checkbox", { name: "Accept terms" }));
    expect(screen.getByRole("checkbox", { name: "Accept terms" })).toHaveAttribute(
      "aria-checked",
      "true"
    );
  });

  it("returns to checked after a second click on a default-checked box", () => {
    render(<Checkbox aria-label="Accept terms" defaultChecked />);
    const box = screen.getByRole("checkbox", { name: "Accept terms" });
    fireEvent.click(box);
    expect(box).toHaveAttribute("aria-checked", "false");
    fireEvent.click(box);
    expect(box).toHaveAttribute("aria-checked", "true");
  });

  it("reports the new checked value through onCheckedChange", () => {
    const onCheckedChange = vi.fn();
    render(<Checkbox aria-label="Accept terms" onCheckedChange={onCheckedChange} />);
    fireEvent.click(screen.getByRole("checkbox", { name: "Accept terms" }));
    expect(onCheckedChange).toHaveBeenCalledTimes(1);
    expect(onCheckedChange).toHaveBeenCalledWith(true);
  });

  it("reports false when a checked box is clicked", () => {
    const onCheckedChange = vi.fn();
    render(
      <Checkbox aria-label="Accept terms" defaultChecked onCheckedChange={onCheckedChange} />
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "Accept terms" }));
    expect(onCheckedChange).toHaveBeenCalledWith(false);
  });

  it("stays unchecked when the parent keeps checked false (controlled)", () => {
    const onCheckedChange = vi.fn();
    render(
      <Checkbox aria-label="Accept terms" checked={false} onCheckedChange={onCheckedChange} />
    );
    const box = screen.getByRole("checkbox", { name: "Accept terms" });
    fireEvent.click(box);
    expect(onCheckedChange).toHaveBeenCalledWith(true);
    expect(box).toHaveAttribute("aria-checked", "false");
  });

  it("shows the indeterminate state as mixed", () => {
    const { container } = render(
      <Checkbox aria-label="Select all" checked="indeterminate" />
    );
    const box = screen.getByRole("checkbox", { name: "Select all" });
    expect(box).toHaveAttribute("aria-checked", "mixed");
    expect(box).toHaveAttribute("data-state", "indeterminate");
    expect(container.querySelector('[data-slot="checkbox-indicator"]')).not.toBeNull();
  });

  it("does not change or report a click while disabled", () => {
    const onCheckedChange = vi.fn();
    render(
      <Checkbox aria-label="Accept terms" disabled onCheckedChange={onCheckedChange} />
    );
    const box = screen.getByRole("checkbox", { name: "Accept terms" });
    expect(box).toBeDisabled();
    fireEvent.click(box);
    expect(onCheckedChange).not.toHaveBeenCalled();
    expect(box).toHaveAttribute("aria-checked", "false");
  });

  it("merges a caller className with the base classes", () => {
    render(<Checkbox aria-label="Accept terms" className="custom-class" />);
    const box = screen.getByRole("checkbox", { name: "Accept terms" });
    expect(box).toHaveClass("custom-class");
    expect(box).toHaveClass("rounded-[4px]");
  });

  it("passes id through to the rendered button", () => {
    render(<Checkbox id="terms" aria-label="Accept terms" />);
    const box = screen.getByRole("checkbox", { name: "Accept terms" });
    expect(box).toHaveAttribute("id", "terms");
  });

  it("is reachable by its label text", () => {
    render(
      <>
        <label htmlFor="newsletter">Subscribe</label>
        <Checkbox id="newsletter" />
      </>
    );
    fireEvent.click(screen.getByLabelText("Subscribe"));
    expect(screen.getByLabelText("Subscribe")).toHaveAttribute("aria-checked", "true");
  });
});
