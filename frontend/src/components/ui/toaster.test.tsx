import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider, useToast, type ToastInput } from "./toaster";

/** Renders one button per input; clicking it pushes that notification. */
function Notifier({ inputs }: { inputs: ToastInput[] }) {
  const push = useToast();
  return (
    <>
      {inputs.map((input) => (
        <button key={input.title} type="button" onClick={() => push(input)}>
          Notify {input.title}
        </button>
      ))}
    </>
  );
}

function renderWith(inputs: ToastInput[]) {
  return render(
    <ToastProvider>
      <Notifier inputs={inputs} />
    </ToastProvider>,
  );
}

function notify(title: string) {
  fireEvent.click(screen.getByRole("button", { name: `Notify ${title}` }));
}

describe("ToastProvider", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders a polite live region with no notifications before anything is pushed", () => {
    renderWith([]);

    const region = screen.getByLabelText("Notifications");
    expect(region).toHaveAttribute("aria-live", "polite");
    expect(screen.queryAllByRole("status")).toHaveLength(0);
  });

  it("shows the title of a pushed notification as a status message", () => {
    renderWith([{ title: "Decision recorded" }]);

    notify("Decision recorded");

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Decision recorded");
  });

  it("shows the description under the title when one is given", () => {
    renderWith([{ title: "Published", description: "Boundary v2 is live" }]);

    notify("Published");

    expect(screen.getByText("Boundary v2 is live")).toBeInTheDocument();
  });

  it("omits the description line when none is given", () => {
    renderWith([{ title: "Uploaded" }]);

    notify("Uploaded");

    expect(screen.getByRole("status").querySelectorAll("p")).toHaveLength(1);
  });

  it("uses the success colour by default", () => {
    renderWith([{ title: "Saved" }]);

    notify("Saved");

    expect(screen.getByRole("status").className).toContain("border-risk-clear/30");
  });

  it("uses the warning colour for a warn tone", () => {
    renderWith([{ title: "Needs attention", tone: "warn" }]);

    notify("Needs attention");

    expect(screen.getByRole("status").className).toContain("border-risk-warn/35");
  });

  it("renders the action as a link to its href", () => {
    renderWith([
      { title: "Case created", action: { label: "Open case", href: "/review?case=CASE-9" } },
    ]);

    notify("Case created");

    const link = screen.getByRole("link", { name: "Open case" });
    expect(link).toHaveAttribute("href", "/review?case=CASE-9");
  });

  it("renders no link when the notification has no action", () => {
    renderWith([{ title: "Plain" }]);

    notify("Plain");

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("removes a notification when its dismiss button is clicked", () => {
    renderWith([{ title: "Closable" }]);
    notify("Closable");

    fireEvent.click(screen.getByRole("button", { name: "Dismiss notification" }));

    expect(screen.queryByText("Closable")).not.toBeInTheDocument();
  });

  it("removes a notification by itself six seconds after it was pushed", () => {
    renderWith([{ title: "Fading" }]);
    notify("Fading");

    act(() => {
      vi.advanceTimersByTime(5_999);
    });
    expect(screen.getByText("Fading")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.queryByText("Fading")).not.toBeInTheDocument();
  });

  it("keeps the newest notifications in the order they were pushed", () => {
    renderWith([{ title: "First" }, { title: "Second" }]);

    notify("First");
    notify("Second");

    const titles = screen.getAllByRole("status").map((status) => status.textContent);
    expect(titles).toEqual(["First", "Second"]);
  });

  it("shows at most three notifications and drops the oldest first", () => {
    renderWith([{ title: "One" }, { title: "Two" }, { title: "Three" }, { title: "Four" }]);

    notify("One");
    notify("Two");
    notify("Three");
    notify("Four");

    expect(screen.getAllByRole("status")).toHaveLength(3);
    expect(screen.queryByText("One")).not.toBeInTheDocument();
    expect(screen.getByText("Two")).toBeInTheDocument();
    expect(screen.getByText("Three")).toBeInTheDocument();
    expect(screen.getByText("Four")).toBeInTheDocument();
  });
});

describe("useToast", () => {
  it("returns a function that does nothing outside a ToastProvider", () => {
    function Lonely() {
      const push = useToast();
      return <button type="button" onClick={() => push({ title: "Ghost" })}>Notify</button>;
    }
    render(<Lonely />);

    fireEvent.click(screen.getByRole("button", { name: "Notify" }));

    expect(screen.queryByText("Ghost")).not.toBeInTheDocument();
    expect(screen.queryAllByRole("status")).toHaveLength(0);
  });
});
