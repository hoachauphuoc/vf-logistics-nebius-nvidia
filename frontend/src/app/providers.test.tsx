import { QueryClient, useQueryClient } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MotionConfigContext } from "framer-motion";
import { useContext } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Tooltip, TooltipTrigger } from "@/components/ui/tooltip";
import { useToast, type ToastInput } from "@/components/ui/toaster";

import { Providers } from "./providers";

function QueryClientProbe({ onRender }: { onRender: (client: QueryClient) => void }) {
  onRender(useQueryClient());
  return null;
}

function MotionProbe({ onRender }: { onRender: (reducedMotion: string | undefined) => void }) {
  onRender(useContext(MotionConfigContext).reducedMotion);
  return null;
}

function Pusher({ toasts }: { toasts: ToastInput[] }) {
  const push = useToast();
  return (
    <>
      {toasts.map((toast) => (
        <button key={toast.title} type="button" onClick={() => push(toast)}>
          Push {toast.title}
        </button>
      ))}
    </>
  );
}

describe("Providers", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders its children", () => {
    render(
      <Providers>
        <p>Child content</p>
      </Providers>,
    );
    expect(screen.getByText("Child content")).toBeInTheDocument();
  });

  it("gives children a query client with the console's default query options", () => {
    const seen: QueryClient[] = [];
    render(
      <Providers>
        <QueryClientProbe onRender={(client) => seen.push(client)} />
      </Providers>,
    );
    expect(seen[0].getDefaultOptions().queries).toMatchObject({
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    });
  });

  it("keeps the same query client when the provider re-renders", () => {
    const seen: QueryClient[] = [];
    const tree = () => (
      <Providers>
        <QueryClientProbe onRender={(client) => seen.push(client)} />
      </Providers>
    );
    const { rerender } = render(tree());
    rerender(tree());
    expect(seen.length).toBeGreaterThanOrEqual(2);
    expect(new Set(seen).size).toBe(1);
  });

  it("gives each mounted provider its own query client", () => {
    const first: QueryClient[] = [];
    const second: QueryClient[] = [];
    render(
      <Providers>
        <QueryClientProbe onRender={(client) => first.push(client)} />
      </Providers>,
    );
    render(
      <Providers>
        <QueryClientProbe onRender={(client) => second.push(client)} />
      </Providers>,
    );
    expect(first[0]).not.toBe(second[0]);
  });

  it("sets framer-motion to honour the operating system's reduce-motion setting", () => {
    const seen: (string | undefined)[] = [];
    render(
      <Providers>
        <MotionProbe onRender={(value) => seen.push(value)} />
      </Providers>,
    );
    expect(seen[0]).toBe("user");
  });

  it("lets a tooltip trigger render inside it", () => {
    render(
      <Providers>
        <Tooltip>
          <TooltipTrigger>Explain score</TooltipTrigger>
        </Tooltip>
      </Providers>,
    );
    expect(screen.getByRole("button", { name: "Explain score" })).toBeInTheDocument();
  });

  it("renders an empty notification region before anything is pushed", () => {
    render(
      <Providers>
        <Pusher toasts={[]} />
      </Providers>,
    );
    expect(screen.getByLabelText("Notifications")).toBeEmptyDOMElement();
  });

  it("shows a pushed notification with its title and description", () => {
    render(
      <Providers>
        <Pusher toasts={[{ title: "Decision saved", description: "Case C-1 is closed" }]} />
      </Providers>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Push Decision saved" }));
    expect(screen.getByText("Decision saved")).toBeInTheDocument();
    expect(screen.getByText("Case C-1 is closed")).toBeInTheDocument();
  });

  it("links a notification to its action", () => {
    render(
      <Providers>
        <Pusher toasts={[{ title: "Case created", action: { label: "Open case", href: "/cases/C-1" } }]} />
      </Providers>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Push Case created" }));
    expect(screen.getByRole("link", { name: "Open case" })).toHaveAttribute("href", "/cases/C-1");
  });

  it("removes a notification when its dismiss button is clicked", () => {
    render(
      <Providers>
        <Pusher toasts={[{ title: "Upload received" }]} />
      </Providers>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Push Upload received" }));
    expect(screen.getByText("Upload received")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss notification" }));
    expect(screen.queryByText("Upload received")).not.toBeInTheDocument();
  });

  it("keeps only the three newest notifications on screen", () => {
    const titles = ["one", "two", "three", "four"];
    render(
      <Providers>
        <Pusher toasts={titles.map((title) => ({ title }))} />
      </Providers>,
    );
    for (const title of titles) {
      fireEvent.click(screen.getByRole("button", { name: `Push ${title}` }));
    }
    expect(screen.queryByText("one")).not.toBeInTheDocument();
    expect(screen.getByText("two")).toBeInTheDocument();
    expect(screen.getByText("three")).toBeInTheDocument();
    expect(screen.getByText("four")).toBeInTheDocument();
  });

  it("removes a notification after six seconds and not before", () => {
    vi.useFakeTimers();
    render(
      <Providers>
        <Pusher toasts={[{ title: "Boundary published" }]} />
      </Providers>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Push Boundary published" }));

    vi.advanceTimersByTime(5_999);
    expect(screen.getByText("Boundary published")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.queryByText("Boundary published")).not.toBeInTheDocument();
  });
});
