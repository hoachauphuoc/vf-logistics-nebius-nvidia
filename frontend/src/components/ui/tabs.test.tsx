import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  tabsListVariants,
} from "./tabs";

function tabsTree(
  rootProps: ComponentProps<typeof Tabs> = {},
  listProps: ComponentProps<typeof TabsList> = {}
) {
  return (
    <Tabs defaultValue="overview" {...rootProps}>
      <TabsList {...listProps}>
        <TabsTrigger value="overview">Overview</TabsTrigger>
        <TabsTrigger value="shipments">Shipments</TabsTrigger>
        <TabsTrigger value="disabled" disabled>
          Locked
        </TabsTrigger>
      </TabsList>
      <TabsContent value="overview">Overview panel</TabsContent>
      <TabsContent value="shipments">Shipments panel</TabsContent>
      <TabsContent value="disabled">Locked panel</TabsContent>
    </Tabs>
  );
}

// Radix activates a tab on mousedown with the primary button, not on click.
function selectTab(name: string) {
  fireEvent.mouseDown(screen.getByRole("tab", { name }), { button: 0, ctrlKey: false });
}

describe("Tabs", () => {
  it("renders the root with the horizontal orientation by default", () => {
    const { container } = render(tabsTree());
    const root = container.querySelector('[data-slot="tabs"]');
    expect(root).toHaveAttribute("data-orientation", "horizontal");
  });

  it("sets the vertical orientation when asked for it", () => {
    const { container } = render(tabsTree({ orientation: "vertical" }));
    const root = container.querySelector('[data-slot="tabs"]');
    expect(root).toHaveAttribute("data-orientation", "vertical");
  });

  it("keeps a caller className on the root next to the base classes", () => {
    const { container } = render(tabsTree({ className: "custom-root" }));
    const root = container.querySelector('[data-slot="tabs"]');
    expect(root).toHaveClass("custom-root");
    expect(root).toHaveClass("group/tabs");
  });

  it("shows the panel of the default tab and hides the others", () => {
    render(tabsTree());
    expect(screen.getByText("Overview panel")).toBeInTheDocument();
    expect(screen.queryByText("Shipments panel")).not.toBeInTheDocument();
  });

  it("switches to another tab when its trigger is pressed", () => {
    render(tabsTree());
    selectTab("Shipments");
    expect(screen.getByText("Shipments panel")).toBeInTheDocument();
    expect(screen.queryByText("Overview panel")).not.toBeInTheDocument();
  });

  it("marks only the selected trigger as selected", () => {
    render(tabsTree());
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Shipments" })).toHaveAttribute("aria-selected", "false");

    selectTab("Shipments");
    expect(screen.getByRole("tab", { name: "Shipments" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "false");
  });

  it("does not switch to a disabled tab", () => {
    render(tabsTree());
    selectTab("Locked");
    expect(screen.getByText("Overview panel")).toBeInTheDocument();
    expect(screen.queryByText("Locked panel")).not.toBeInTheDocument();
  });

  it("follows a controlled value and reports the requested change", () => {
    const onValueChange = vi.fn();
    render(
      <Tabs value="overview" onValueChange={onValueChange}>
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="shipments">Shipments</TabsTrigger>
        </TabsList>
        <TabsContent value="overview">Overview panel</TabsContent>
        <TabsContent value="shipments">Shipments panel</TabsContent>
      </Tabs>
    );

    selectTab("Shipments");
    expect(onValueChange).toHaveBeenCalledWith("shipments");
    // The value is controlled, so the panel stays on overview until the parent changes it.
    expect(screen.getByText("Overview panel")).toBeInTheDocument();
  });

  it("moves focus to the next trigger with the arrow key", async () => {
    render(tabsTree());
    fireEvent.keyDown(screen.getByRole("tab", { name: "Overview" }), { key: "ArrowRight" });
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "Shipments" })).toHaveFocus();
    });
  });

  it("renders the list with the default variant when none is given", () => {
    const { container } = render(tabsTree());
    const list = container.querySelector('[data-slot="tabs-list"]');
    expect(list).toHaveAttribute("data-variant", "default");
    expect(list).toHaveClass("bg-muted");
  });

  it("renders the list with the line variant when asked for it", () => {
    const { container } = render(tabsTree({}, { variant: "line" }));
    const list = container.querySelector('[data-slot="tabs-list"]');
    expect(list).toHaveAttribute("data-variant", "line");
    expect(list).toHaveClass("bg-transparent");
    expect(list).not.toHaveClass("bg-muted");
  });

  it("keeps a caller className on the list", () => {
    const { container } = render(tabsTree({}, { className: "custom-list" }));
    expect(container.querySelector('[data-slot="tabs-list"]')).toHaveClass("custom-list");
  });

  it("gives each trigger the tab role and its slot marker", () => {
    const { container } = render(tabsTree());
    const triggers = container.querySelectorAll('[data-slot="tabs-trigger"]');
    expect(triggers).toHaveLength(3);
    expect(screen.getAllByRole("tab")).toHaveLength(3);
  });

  it("gives the content the tabpanel role and its slot marker", () => {
    const { container } = render(tabsTree());
    const panel = container.querySelector('[data-slot="tabs-content"]');
    expect(panel).toHaveAttribute("role", "tabpanel");
    expect(panel).toHaveTextContent("Overview panel");
  });

  it("keeps a caller className on the trigger", () => {
    render(
      <Tabs defaultValue="a">
        <TabsList>
          <TabsTrigger value="a" className="custom-trigger">
            A
          </TabsTrigger>
        </TabsList>
      </Tabs>
    );
    expect(screen.getByRole("tab", { name: "A" })).toHaveClass("custom-trigger");
  });

  it("keeps a caller className on the content", () => {
    const { container } = render(
      <Tabs defaultValue="a">
        <TabsContent value="a" className="custom-content">
          Body
        </TabsContent>
      </Tabs>
    );
    expect(container.querySelector('[data-slot="tabs-content"]')).toHaveClass("custom-content");
  });
});

describe("tabsListVariants", () => {
  it("returns the default background when called without a variant", () => {
    expect(tabsListVariants()).toContain("bg-muted");
  });

  it("returns the transparent line style for the line variant", () => {
    const classes = tabsListVariants({ variant: "line" });
    expect(classes).toContain("bg-transparent");
    expect(classes).not.toContain("bg-muted");
  });
});
