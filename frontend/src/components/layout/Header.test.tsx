import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";

import { Header } from "./Header";

const mocks = vi.hoisted(() => ({ demo: true }));

// The header's own status pills read DEMO_MODE on every render, so the getter lets each
// test switch between the demo pill and the live pill without re-importing the module.
vi.mock("@/lib/config", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/config")>()),
  get DEMO_MODE(): boolean {
    return mocks.demo;
  },
}));

// The child controls have their own tests; here they are stubbed so the assertions stay
// about what the header itself renders and passes down.
vi.mock("@/components/layout/TenantSwitcher", () => ({
  TenantSwitcher: ({ display }: { display?: { name: string } }) => (
    <div data-testid="tenant-switcher">{display ? display.name : "no tenant"}</div>
  ),
}));
vi.mock("@/components/layout/AccountMenu", () => ({
  AccountMenu: () => <div data-testid="account-menu" />,
}));
vi.mock("@/components/layout/HelpModeToggle", () => ({
  HelpModeToggle: () => <div data-testid="help-mode-toggle" />,
}));

// Radix popper measures the trigger and content with ResizeObserver, which jsdom does not
// implement. Opening either tooltip would throw without this stub.
class ResizeObserverStub {
  observe(): void {
    // jsdom has no layout, so there is nothing to observe.
  }
  unobserve(): void {
    // See observe().
  }
  disconnect(): void {
    // See observe().
  }
}

const MODELS_TOOLTIP = /Every agent runs on Nebius Token Factory/;
const DEMO_TOOLTIP = /Audits below are synthetic fixtures/;

function renderHeader(display?: { name: string }) {
  return render(
    <TooltipProvider>
      <Header display={display as never} />
    </TooltipProvider>,
  );
}

describe("Header", () => {
  beforeEach(() => {
    vi.stubGlobal("ResizeObserver", ResizeObserverStub);
    mocks.demo = true;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("is the page banner landmark", () => {
    renderHeader();

    expect(screen.getByRole("banner")).toBeInTheDocument();
  });

  it("names the product Floorline", () => {
    renderHeader();

    expect(screen.getByText("Floorline")).toBeInTheDocument();
  });

  it("passes the tenant it is given to the tenant switcher", () => {
    renderHeader({ name: "Acme Logistics" });

    expect(screen.getByTestId("tenant-switcher")).toHaveTextContent("Acme Logistics");
  });

  it("renders the tenant switcher without a tenant when none is given", () => {
    renderHeader();

    expect(screen.getByTestId("tenant-switcher")).toHaveTextContent("no tenant");
  });

  it("renders the account menu and the help toggle", () => {
    renderHeader();

    expect(screen.getByTestId("account-menu")).toBeInTheDocument();
    expect(screen.getByTestId("help-mode-toggle")).toBeInTheDocument();
  });

  it("links the models chip to the agents console", () => {
    renderHeader();

    expect(screen.getByRole("link", { name: /NVIDIA Nemotron 3/ })).toHaveAttribute(
      "href",
      "/agents",
    );
  });

  it("shows the demo pill, not the live pill, in demo mode", () => {
    renderHeader();

    expect(screen.getByText("Demo data")).toBeInTheDocument();
    expect(screen.queryByText("Live", { exact: true })).toBeNull();
  });

  it("shows the live pill, not the demo pill, when demo mode is off", () => {
    mocks.demo = false;
    renderHeader();

    expect(screen.getByText("Live", { exact: true })).toBeInTheDocument();
    expect(screen.queryByText("Demo data")).toBeNull();
  });

  it("shows no tooltip text before the models chip or a pill is used", () => {
    renderHeader();

    expect(screen.queryByText(MODELS_TOOLTIP)).toBeNull();
    expect(screen.queryByText(DEMO_TOOLTIP)).toBeNull();
  });

  it("explains the models chip when it is focused", async () => {
    renderHeader();

    act(() => {
      screen.getByRole("link", { name: /NVIDIA Nemotron 3/ }).focus();
    });

    const tooltips = await screen.findAllByText(MODELS_TOOLTIP);
    expect(tooltips[0]).toBeInTheDocument();
  });

  it("warns that the figures are synthetic when the demo pill is hovered", async () => {
    renderHeader();

    fireEvent.pointerMove(screen.getByText("Demo data"));

    const tooltips = await screen.findAllByText(DEMO_TOOLTIP);
    expect(tooltips[0]).toBeInTheDocument();
  });
});
