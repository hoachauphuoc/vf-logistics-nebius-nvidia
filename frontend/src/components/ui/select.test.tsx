import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "./select";

// Radix measures the open list with ResizeObserver and scrolls the selected item into view;
// jsdom provides neither.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

const originalScrollIntoView = Element.prototype.scrollIntoView;

function selectTree(
  rootProps: ComponentProps<typeof Select> = {},
  triggerProps: ComponentProps<typeof SelectTrigger> = {},
  contentProps: ComponentProps<typeof SelectContent> = {}
) {
  return (
    <Select {...rootProps}>
      <SelectTrigger aria-label="Status" {...triggerProps}>
        <SelectValue placeholder="Pick one" />
      </SelectTrigger>
      <SelectContent {...contentProps}>
        <SelectGroup>
          <SelectLabel>Options</SelectLabel>
          <SelectItem value="a">Alpha</SelectItem>
          <SelectItem value="b">Beta</SelectItem>
          <SelectSeparator />
          <SelectItem value="c" disabled>
            Gamma
          </SelectItem>
        </SelectGroup>
      </SelectContent>
    </Select>
  );
}

function getTrigger() {
  return screen.getByRole("combobox", { name: "Status" });
}

function openList() {
  fireEvent.keyDown(getTrigger(), { key: "Enter" });
  return screen.getByRole("listbox");
}

describe("select", () => {
  beforeEach(() => {
    vi.stubGlobal("ResizeObserver", ResizeObserverStub);
    Element.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    Element.prototype.scrollIntoView = originalScrollIntoView;
  });

  it("shows the placeholder in the trigger when nothing is selected", () => {
    render(selectTree());

    expect(getTrigger()).toHaveTextContent("Pick one");
  });

  it("shows the label of the default value in the trigger", () => {
    render(selectTree({ defaultValue: "b" }));

    expect(getTrigger()).toHaveTextContent("Beta");
    expect(getTrigger()).not.toHaveTextContent("Pick one");
  });

  it("marks the trigger with the default size and the select-trigger slot", () => {
    render(selectTree());

    expect(getTrigger()).toHaveAttribute("data-slot", "select-trigger");
    expect(getTrigger()).toHaveAttribute("data-size", "default");
  });

  it("passes the sm size and the caller's class name through to the trigger", () => {
    render(selectTree({}, { size: "sm", className: "my-custom-class" }));

    expect(getTrigger()).toHaveAttribute("data-size", "sm");
    expect(getTrigger()).toHaveClass("my-custom-class");
  });

  it("reports the trigger as collapsed until the list is opened", () => {
    render(selectTree());
    // Radix hides the rest of the page from assistive tech while the list is open,
    // so the trigger is looked up before opening and checked through that reference.
    const trigger = getTrigger();

    expect(trigger).toHaveAttribute("aria-expanded", "false");
    openList();
    expect(trigger).toHaveAttribute("aria-expanded", "true");
  });

  it("opens the option list with the Enter key and shows every item", () => {
    render(selectTree());

    const listbox = openList();

    expect(within(listbox).getByRole("option", { name: "Alpha" })).toBeInTheDocument();
    expect(within(listbox).getByRole("option", { name: "Beta" })).toBeInTheDocument();
    expect(within(listbox).getByRole("option", { name: "Gamma" })).toBeInTheDocument();
  });

  it("shows the group label and the separator inside the open list", () => {
    render(selectTree());

    openList();

    expect(screen.getByRole("group")).toHaveTextContent("Options");
    expect(document.querySelector('[data-slot="select-separator"]')).toBeInTheDocument();
  });

  it("shows no options when the select has no items", () => {
    render(
      <Select>
        <SelectTrigger aria-label="Status">
          <SelectValue placeholder="Pick one" />
        </SelectTrigger>
        <SelectContent />
      </Select>
    );

    const listbox = openList();

    expect(listbox).toBeInTheDocument();
    expect(within(listbox).queryAllByRole("option")).toHaveLength(0);
  });

  it("reports the chosen value and shows its label in the trigger after a click", async () => {
    const onValueChange = vi.fn();
    render(selectTree({ onValueChange }));

    const listbox = openList();
    fireEvent.click(within(listbox).getByRole("option", { name: "Alpha" }));

    expect(onValueChange).toHaveBeenCalledWith("a");
    await waitFor(() => expect(screen.queryByRole("listbox")).not.toBeInTheDocument());
    expect(getTrigger()).toHaveTextContent("Alpha");
  });

  it("does not select a disabled item", () => {
    const onValueChange = vi.fn();
    render(selectTree({ onValueChange }));

    const listbox = openList();
    const gamma = within(listbox).getByRole("option", { name: "Gamma" });
    expect(gamma).toHaveAttribute("data-disabled");

    fireEvent.click(gamma);

    expect(onValueChange).not.toHaveBeenCalled();
  });

  it("closes the list on Escape without changing the value", async () => {
    const onValueChange = vi.fn();
    render(selectTree({ defaultValue: "a", onValueChange }));

    const listbox = openList();
    fireEvent.keyDown(listbox, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("listbox")).not.toBeInTheDocument());
    expect(onValueChange).not.toHaveBeenCalled();
    expect(getTrigger()).toHaveTextContent("Alpha");
  });

  it("reports open and close changes through onOpenChange", async () => {
    const onOpenChange = vi.fn();
    render(selectTree({ onOpenChange }));

    const listbox = openList();
    expect(onOpenChange).toHaveBeenLastCalledWith(true);

    fireEvent.keyDown(listbox, { key: "Escape" });
    await waitFor(() => expect(onOpenChange).toHaveBeenLastCalledWith(false));
  });

  it("shows the value passed through the value prop and follows later changes to it", () => {
    const { rerender } = render(selectTree({ value: "a" }));
    expect(getTrigger()).toHaveTextContent("Alpha");

    rerender(selectTree({ value: "b" }));

    expect(getTrigger()).toHaveTextContent("Beta");
  });

  it("does not open when the select is disabled", () => {
    render(selectTree({ disabled: true }));

    expect(getTrigger()).toBeDisabled();
    fireEvent.keyDown(getTrigger(), { key: "Enter" });

    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("lays the list out against the item by default", () => {
    render(selectTree());

    openList();

    expect(document.querySelector('[data-position="item-aligned"]')).toBeInTheDocument();
  });

  it("lays the list out in popper mode when position is popper", () => {
    render(selectTree({}, {}, { position: "popper" }));

    openList();

    expect(document.querySelector('[data-position="popper"]')).toBeInTheDocument();
    expect(document.querySelector('[data-position="item-aligned"]')).not.toBeInTheDocument();
  });
});
