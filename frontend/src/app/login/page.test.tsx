import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ posture: { current: null as unknown } }));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/login",
}));
vi.mock("@/lib/console-posture", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/console-posture")>()),
  useConsolePosture: () => ({ data: mocks.posture.current }),
  signInAsGuestJudge: vi.fn(),
}));

import LoginPage from "./page";

function posture(publicReads: boolean) {
  return { auth: { login_required: true, public_reads: publicReads, session: null, one_click_judge: true } } as never;
}

/**
 * The sign-in screen tells a visitor whether they can look around without an account. That depends on the
 * deployment: with public reads off (ANONYMOUS_ROLE=none upstream, VF_PUBLIC_READS unset on the console) the
 * board answers "sign in", so the page must not promise it is public.
 */
describe("Login page: what a visitor can see without signing in", () => {
  beforeEach(() => {
    mocks.posture.current = null;
  });

  it("says looking around needs a sign-in when public reads are off", () => {
    mocks.posture.current = posture(false);
    render(<LoginPage />);
    expect(screen.getByText(/Sign in to look around\./)).toBeInTheDocument();
    expect(screen.queryByText(/You do not need an account to look around/)).not.toBeInTheDocument();
  });

  it("says the board is public when public reads are on", () => {
    mocks.posture.current = posture(true);
    render(<LoginPage />);
    expect(screen.getByText(/You do not need an account to look around\./)).toBeInTheDocument();
    expect(screen.queryByText(/Sign in to look around\./)).not.toBeInTheDocument();
  });

  it("promises nothing about public access before the posture has loaded", () => {
    render(<LoginPage />);
    expect(screen.queryByText(/You do not need an account to look around/)).not.toBeInTheDocument();
    expect(screen.getByText(/Sign in to look around\./)).toBeInTheDocument();
  });
});
