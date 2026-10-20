import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { TimelineEvent, TimelineKind } from "@/lib/operations";

import { CaseTimeline } from "./CaseTimeline";

function event(overrides: Partial<TimelineEvent>): TimelineEvent {
  return { kind: "arrived", at: "2026-10-20T09:05:00Z", title: "Arrived", ...overrides };
}

const KINDS: TimelineKind[] = [
  "arrived",
  "finding",
  "agent",
  "refused",
  "request",
  "decision",
  "action",
  "audit",
  "evidence_request",
  "evidence_received",
  "evidence_eval",
  "evidence_approval",
  "evidence_execution",
];

describe("CaseTimeline", () => {
  it("says nothing has been recorded when the case has no events", () => {
    render(<CaseTimeline events={[]} />);
    expect(screen.getByText("Nothing has been recorded on this case.")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Case history" })).not.toBeInTheDocument();
  });

  it("labels the events as the case history", () => {
    render(<CaseTimeline events={[event({ title: "Arrived" })]} />);
    expect(screen.getByRole("list", { name: "Case history" })).toBeInTheDocument();
  });

  it("lists the events in the order they were given", () => {
    render(
      <CaseTimeline
        events={[
          event({ kind: "arrived", title: "Case arrived" }),
          event({ kind: "finding", title: "Sanctions match" }),
          event({ kind: "decision", title: "Released by reviewer" }),
        ]}
      />,
    );
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent("Case arrived");
    expect(items[1]).toHaveTextContent("Sanctions match");
    expect(items[2]).toHaveTextContent("Released by reviewer");
  });

  it("shows who recorded an event under its title", () => {
    render(<CaseTimeline events={[event({ title: "Released", who: "reviewer@example.test" })]} />);
    expect(screen.getByText("reviewer@example.test")).toBeInTheDocument();
  });

  it("shows no who line when the event has no one attached", () => {
    render(<CaseTimeline events={[event({ title: "Arrived", who: null })]} />);
    const item = screen.getByRole("listitem");
    expect(item.querySelectorAll("p")).toHaveLength(1);
  });

  it("shows the detail text of an event", () => {
    render(<CaseTimeline events={[event({ title: "Refused", detail: "Gate refused: missing invoice" })]} />);
    expect(screen.getByText("Gate refused: missing invoice")).toHaveClass("whitespace-pre-wrap");
  });

  it("shows no detail line when the detail is empty or missing", () => {
    render(
      <CaseTimeline
        events={[
          event({ title: "Empty detail", detail: "" }),
          event({ title: "Null detail", detail: null }),
        ]}
      />,
    );
    for (const item of screen.getAllByRole("listitem")) {
      expect(item.querySelectorAll("p")).toHaveLength(1);
    }
  });

  it("shows the time as a UTC clock with the ISO datetime attribute", () => {
    render(<CaseTimeline events={[event({ at: "2026-10-20T09:05:00Z" })]} />);
    const time = screen.getByText("2026-10-20 09:05:00Z");
    expect(time.tagName).toBe("TIME");
    expect(time).toHaveAttribute("datetime", "2026-10-20T09:05:00Z");
  });

  it("shows a dash instead of a time when the event has none", () => {
    render(<CaseTimeline events={[event({ at: null })]} />);
    const time = screen.getByText("—");
    expect(time.tagName).toBe("TIME");
    expect(time).not.toHaveAttribute("datetime");
  });

  it("shows an unparseable time as it was recorded", () => {
    render(<CaseTimeline events={[event({ at: "not-a-date" })]} />);
    expect(screen.getByText("not-a-date")).toHaveAttribute("datetime", "not-a-date");
  });

  it("colours a bad event title critical", () => {
    render(<CaseTimeline events={[event({ title: "Shipment blocked", tone: "bad" })]} />);
    expect(screen.getByText("Shipment blocked")).toHaveClass("text-risk-critical");
  });

  it("colours a good event title clear", () => {
    render(<CaseTimeline events={[event({ title: "Released", tone: "good" })]} />);
    expect(screen.getByText("Released")).toHaveClass("text-risk-clear");
  });

  it("keeps a neutral or untoned event title in the default colour", () => {
    render(
      <CaseTimeline
        events={[
          event({ title: "Neutral step", tone: "neutral" }),
          event({ title: "Untoned step" }),
        ]}
      />,
    );
    expect(screen.getByText("Neutral step")).toHaveClass("text-white/90");
    expect(screen.getByText("Untoned step")).toHaveClass("text-white/90");
  });

  it("draws the icon badge in the colour of the event tone", () => {
    render(
      <CaseTimeline
        events={[event({ title: "Blocked", tone: "bad" }), event({ title: "Plain" })]}
      />,
    );
    const [bad, plain] = screen.getAllByRole("listitem");
    expect(bad.querySelector("span[aria-hidden]")).toHaveClass("bg-risk-critical/10");
    expect(plain.querySelector("span[aria-hidden]")).toHaveClass("bg-white/[0.04]");
  });

  it("renders an icon for every kind of event and hides it from assistive technology", () => {
    render(<CaseTimeline events={KINDS.map((kind) => event({ kind, title: `Step ${kind}` }))} />);
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(KINDS.length);
    for (const item of items) {
      const badge = item.querySelector("span[aria-hidden]");
      expect(badge?.querySelector("svg")).not.toBeNull();
    }
  });

  it("gives each event its own row when two share a kind and a time", () => {
    render(
      <CaseTimeline
        events={[
          event({ kind: "finding", title: "First finding" }),
          event({ kind: "finding", title: "Second finding" }),
        ]}
      />,
    );
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("First finding")).toBeInTheDocument();
    expect(screen.getByText("Second finding")).toBeInTheDocument();
  });
});
