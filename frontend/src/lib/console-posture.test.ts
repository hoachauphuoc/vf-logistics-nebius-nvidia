import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { Fragment, type ReactElement, createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { type ConsolePosture, signInAsGuestJudge, useConsolePosture } from "./console-posture";

const ORIGIN = "https://console.example";

const signedOut: ConsolePosture = {
  auth: { login_required: true, public_reads: false, session: null, one_click_judge: true },
};

const signedIn: ConsolePosture = {
  auth: {
    login_required: true,
    public_reads: false,
    session: { email: "judge@example.com", exp: 1900000000, amr: "one_click" },
    one_click_judge: true,
  },
};

const fetchMock = vi.fn();

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

function stubLocation(): ReturnType<typeof vi.fn> {
  const assign = vi.fn();
  vi.stubGlobal("location", { origin: ORIGIN, assign });
  return assign;
}

function Probe() {
  const posture = useConsolePosture();
  if (posture.isPending) return createElement("p", null, "loading");
  if (posture.isError) return createElement("p", null, "error");
  if (!posture.data) return createElement("p", null, "server refused");
  return createElement(
    Fragment,
    null,
    createElement("p", null, posture.data.auth.login_required ? "login required" : "public"),
    createElement("p", null, posture.data.auth.session?.email ?? "anonymous"),
  );
}

function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(createElement(QueryClientProvider, { client }, ui));
}

describe("useConsolePosture", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a loading state until the posture request finishes", () => {
    fetchMock.mockReturnValue(new Promise(() => {}));
    renderWithClient(createElement(Probe));
    expect(screen.getByText("loading")).toBeInTheDocument();
  });

  it("requests the posture from the console API without caching it", async () => {
    fetchMock.mockResolvedValue(json(signedIn));
    renderWithClient(createElement(Probe));
    await screen.findByText("judge@example.com");
    expect(fetchMock).toHaveBeenCalledWith("/api/auth/posture", { cache: "no-store" });
  });

  it("shows the signed-in session email and the login requirement", async () => {
    fetchMock.mockResolvedValue(json(signedIn));
    renderWithClient(createElement(Probe));
    expect(await screen.findByText("judge@example.com")).toBeInTheDocument();
    expect(screen.getByText("login required")).toBeInTheDocument();
  });

  it("shows anonymous when the posture has no session", async () => {
    fetchMock.mockResolvedValue(json(signedOut));
    renderWithClient(createElement(Probe));
    expect(await screen.findByText("anonymous")).toBeInTheDocument();
  });

  it("resolves to null when the server refuses the posture request", async () => {
    fetchMock.mockResolvedValue(json({ error: "unauthorized" }, 401));
    renderWithClient(createElement(Probe));
    expect(await screen.findByText("server refused")).toBeInTheDocument();
  });

  it("shows an error when the posture request cannot be sent", async () => {
    fetchMock.mockRejectedValue(new Error("offline"));
    renderWithClient(createElement(Probe));
    expect(await screen.findByText("error")).toBeInTheDocument();
  });
});

describe("signInAsGuestJudge", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts to the guest judge endpoint", async () => {
    fetchMock.mockResolvedValue(json({}));
    stubLocation();
    await signInAsGuestJudge();
    expect(fetchMock).toHaveBeenCalledWith("/api/auth/judge", { method: "POST" });
  });

  it("returns an empty string and navigates to the home page by default", async () => {
    fetchMock.mockResolvedValue(json({}));
    const assign = stubLocation();
    const result = await signInAsGuestJudge();
    expect(result).toBe("");
    expect(assign).toHaveBeenCalledWith(`${ORIGIN}/`);
  });

  it("navigates to the requested path after signing in", async () => {
    fetchMock.mockResolvedValue(json({}));
    const assign = stubLocation();
    await signInAsGuestJudge("/review?case=7");
    expect(assign).toHaveBeenCalledWith(`${ORIGIN}/review?case=7`);
  });

  it("returns the server's error message and does not navigate when sign-in is refused", async () => {
    fetchMock.mockResolvedValue(json({ error: "Guest access is switched off." }, 403));
    const assign = stubLocation();
    const result = await signInAsGuestJudge();
    expect(result).toBe("Guest access is switched off.");
    expect(assign).not.toHaveBeenCalled();
  });

  it("returns a generic message when the refusal has no JSON body", async () => {
    fetchMock.mockResolvedValue(new Response("<html>oops</html>", { status: 500 }));
    const assign = stubLocation();
    const result = await signInAsGuestJudge();
    expect(result).toBe("One-click sign-in failed.");
    expect(assign).not.toHaveBeenCalled();
  });

  it("returns a generic message when the refusal JSON has no error field", async () => {
    fetchMock.mockResolvedValue(json({}, 500));
    stubLocation();
    expect(await signInAsGuestJudge()).toBe("One-click sign-in failed.");
  });

  it("reports that the server could not be reached when the request fails", async () => {
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));
    const assign = stubLocation();
    const result = await signInAsGuestJudge();
    expect(result).toBe("Could not reach the server.");
    expect(assign).not.toHaveBeenCalled();
  });
});
