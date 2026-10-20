import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";

import { AccountMenu } from "./AccountMenu";

const mocks = vi.hoisted(() => ({
  identity: undefined as { authenticated_by: string; role: string; role_source: string } | undefined,
  fetch: vi.fn(),
}));

// The identity query is shared by every screen and runs in demo mode with no data, so the
// role chip is driven through the hook directly. roleLabel stays real.
vi.mock("@/lib/identity", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/identity")>()),
  useIdentity: () => ({ data: mocks.identity }),
}));

import { roleLabel } from "@/lib/identity";

// Radix popper measures the trigger and content with ResizeObserver, which jsdom does not
// implement. Opening a tooltip would throw without this stub.
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

const SESSION_URL = "/api/auth/session";
const LOGOUT_URL = "/api/auth/logout";

function answerSession(status: number, body: unknown = null) {
  mocks.fetch.mockImplementation(async (url: string) => {
    if (url === SESSION_URL) {
      return { ok: status >= 200 && status < 300, status, json: async () => body };
    }
    // The logout request stays in flight, so the busy state is observable.
    return new Promise(() => undefined);
  });
}

function renderMenu() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <AccountMenu />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

const SIGNED_IN = { email: "ada@example.com", exp: 1_900_000_000, amr: "password" };

describe("AccountMenu", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", mocks.fetch);
    vi.stubGlobal("ResizeObserver", ResizeObserverStub);
    mocks.fetch.mockReset();
    mocks.identity = undefined;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders nothing while the session is still loading", () => {
    mocks.fetch.mockImplementation(() => new Promise(() => undefined));

    const { container } = renderMenu();

    expect(container).toBeEmptyDOMElement();
  });

  it("asks the session endpoint for a fresh answer", async () => {
    answerSession(200, SIGNED_IN);

    renderMenu();

    await screen.findByText("ada@example.com");
    expect(mocks.fetch).toHaveBeenCalledWith(SESSION_URL, { cache: "no-store" });
  });

  it("offers a sign-in link that goes to the login page when nobody is signed in", async () => {
    answerSession(401);

    renderMenu();

    const link = await screen.findByRole("link", { name: "Sign in" });
    expect(link).toHaveAttribute("href", "/login");
    expect(screen.queryByRole("button", { name: "Sign out" })).toBeNull();
  });

  it("offers the sign-in link when the session request fails", async () => {
    answerSession(500);

    renderMenu();

    expect(await screen.findByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
  });

  it("shows the signed-in email and a sign-out button", async () => {
    answerSession(200, SIGNED_IN);

    renderMenu();

    expect(await screen.findByText("ada@example.com")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeEnabled();
    expect(screen.queryByRole("link", { name: "Sign in" })).toBeNull();
  });

  it("explains that decisions are recorded under the email when it is hovered", async () => {
    answerSession(200, SIGNED_IN);
    renderMenu();

    fireEvent.pointerMove(await screen.findByText("ada@example.com"));

    const tooltips = await screen.findAllByText(/audit trail under this address/);
    expect(tooltips[0]).toBeInTheDocument();
  });

  it("shows the role chip with the role label when the session is a console session", async () => {
    answerSession(200, SIGNED_IN);
    mocks.identity = { authenticated_by: "console_session", role: "reviewer", role_source: "REVIEWER_EMAILS" };

    renderMenu();

    const chip = await screen.findByRole("link", { name: `Your role: ${roleLabel("reviewer")}` });
    expect(chip).toHaveAttribute("href", "/admin");
  });

  it("explains where the role comes from when the role chip is focused", async () => {
    answerSession(200, SIGNED_IN);
    mocks.identity = { authenticated_by: "console_session", role: "reviewer", role_source: "REVIEWER_EMAILS" };
    renderMenu();

    const chip = await screen.findByRole("link", { name: /Your role/ });
    act(() => {
      chip.focus();
    });

    const tooltips = await screen.findAllByText(/Assigned by the API \(REVIEWER_EMAILS\)/);
    expect(tooltips[0]).toBeInTheDocument();
  });

  it("hides the role chip when the identity is not from a console session", async () => {
    answerSession(200, SIGNED_IN);
    mocks.identity = { authenticated_by: "api_key", role: "reviewer", role_source: "API_KEYS" };

    renderMenu();

    await screen.findByText("ada@example.com");
    expect(screen.queryByRole("link", { name: /Your role/ })).toBeNull();
  });

  it("hides the role chip while the identity is still unknown", async () => {
    answerSession(200, SIGNED_IN);

    renderMenu();

    await screen.findByText("ada@example.com");
    expect(screen.queryByRole("link", { name: /Your role/ })).toBeNull();
  });

  it("shows a one-click chip that links to a password sign-in when the session is one-click", async () => {
    answerSession(200, { ...SIGNED_IN, amr: "one_click" });

    renderMenu();

    const chip = await screen.findByRole("link", { name: /one.click/i });
    expect(chip).toHaveAttribute("href", "/login?next=/devops");
  });

  it("explains the one-click limits when the one-click chip is focused", async () => {
    answerSession(200, { ...SIGNED_IN, amr: "one_click" });
    renderMenu();

    const chip = await screen.findByRole("link", { name: /one.click/i });
    act(() => {
      chip.focus();
    });

    const tooltips = await screen.findAllByText(/Signed in with the judge button/);
    expect(tooltips[0]).toBeInTheDocument();
  });

  it("hides the one-click chip for a session signed in with a password", async () => {
    answerSession(200, SIGNED_IN);

    renderMenu();

    await screen.findByText("ada@example.com");
    expect(screen.queryByRole("link", { name: /one.click/i })).toBeNull();
  });

  it("sends the sign-out request when the sign-out button is pressed", async () => {
    answerSession(200, SIGNED_IN);
    renderMenu();

    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));

    expect(mocks.fetch).toHaveBeenCalledWith(LOGOUT_URL, { method: "POST" });
  });

  it("disables the sign-out button while the sign-out request is in flight", async () => {
    answerSession(200, SIGNED_IN);
    renderMenu();

    const button = await screen.findByRole("button", { name: "Sign out" });
    fireEvent.click(button);

    await waitFor(() => expect(button).toBeDisabled());
  });
});
