import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { Tooltip as TooltipPrimitive } from "radix-ui";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

// Live mode: the switcher only consults the API outside the demo.
vi.mock("@/lib/config", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/config")>()),
  DEMO_MODE: false,
}));
vi.mock("@/lib/tenant-choice", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/tenant-choice")>()),
  chooseTenant: vi.fn(),
}));

import { chooseTenant } from "@/lib/tenant-choice";

import { TenantSwitcher } from "./TenantSwitcher";

/**
 * Re-review finding R03: a person in two organisations, signing in for the first
 * time, got whoami's 403 "choose one" with the choices in its body -- and no
 * chooser, because the switcher only read a successful whoami. The review
 * reproduced exactly this: 403 with choices showed nothing; 200 with
 * memberships showed the selector.
 */

beforeAll(() => {
  // Radix Select asks for these; jsdom does not implement them.
  Element.prototype.hasPointerCapture ??= () => false;
  Element.prototype.releasePointerCapture ??= () => {};
  Element.prototype.scrollIntoView ??= () => {};
});

function whoamiAnswers(status: number, body: unknown) {
  globalThis.fetch = vi.fn(async () => Response.json(body, { status })) as unknown as typeof fetch;
}

function renderSwitcher() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TooltipPrimitive.Provider>
        <TenantSwitcher />
      </TooltipPrimitive.Provider>
    </QueryClientProvider>,
  );
}

describe("TenantSwitcher when the API asks for a choice", () => {
  beforeEach(() => vi.mocked(chooseTenant).mockClear());
  afterEach(() => vi.restoreAllMocks());

  it("offers the person's own organisations on first sign-in, and the pick is remembered", async () => {
    whoamiAnswers(403, {
      error: "Not a member of this organisation",
      reason: "tenant_choice_required",
      choices: ["acme", "beta-shipping"],
    });
    renderSwitcher();
    const trigger = await screen.findByLabelText("Choose organisation");
    expect(screen.getByText("2 available to you")).toBeInTheDocument();

    fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false, pointerType: "mouse" });
    const option = await screen.findByRole("option", { name: /beta-shipping/ });
    expect(screen.getByRole("option", { name: /acme/ })).toBeInTheDocument();
    fireEvent.click(option);
    expect(chooseTenant).toHaveBeenCalledWith("beta-shipping");
  });

  it("says a remembered choice is not available, rather than leaving the person stuck", async () => {
    whoamiAnswers(403, {
      error: "Not a member of this organisation",
      reason: "not_member_of_requested",
      choices: ["acme"],
    });
    renderSwitcher();
    expect(await screen.findByLabelText("Choose organisation")).toBeInTheDocument();
    expect(screen.getByText("Your previous choice is not available")).toBeInTheDocument();
  });

  it("shows no chooser for a 403 that is not about the organisation", async () => {
    whoamiAnswers(403, { error: "Insufficient permissions", required_role: "operator" });
    renderSwitcher();
    // Give the query a turn to settle, inside act so React's update is flushed.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(globalThis.fetch).toHaveBeenCalled();
    expect(screen.queryByLabelText("Choose organisation")).toBeNull();
  });

  it("still offers the switch from a successful whoami with several memberships", async () => {
    whoamiAnswers(200, {
      email: "a@acme.com",
      authenticated_by: "console_session",
      acts_for_a_person: true,
      role: "operator",
      roles: ["viewer", "operator"],
      grants: ["viewer", "reviewer", "operator"],
      role_source: "VF_TENANT_MEMBERS",
      tenant_id: "acme",
      memberships: { acme: "operator", "beta-shipping": "viewer" },
    });
    renderSwitcher();
    expect(await screen.findByLabelText("Switch organisation")).toBeInTheDocument();
    expect(screen.queryByLabelText("Choose organisation")).toBeNull();
  });
});
