import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkItem } from "@/lib/types";

import { WorkCard } from "./WorkCard";

const HOUR = 3_600_000;
const NOW = Date.parse("2026-10-20T12:00:00Z");

function at(msFromNow: number): string {
  return new Date(NOW + msFromNow).toISOString();
}

function makeItem(overrides: Partial<WorkItem> = {}): WorkItem {
  return {
    case_id: "CASE-1",
    state: "HELD_FOR_REVIEW",
    bucket: "awaiting_review",
    owner: { kind: "person", name: "Dana Reyes" },
    next_action: null,
    information_rounds: 0,
    finding_count: 0,
    ...overrides,
  };
}

describe("WorkCard", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe("identity and link", () => {
    it("links the card to the page of its case, with the case id encoded", () => {
      render(<WorkCard item={makeItem({ case_id: "CASE 1/2" })} />);
      expect(screen.getByRole("link")).toHaveAttribute("href", "/cases/CASE%201%2F2");
    });

    it("shows the shipment id when there is one", () => {
      render(<WorkCard item={makeItem({ case_id: "CASE-1", shipment_id: "SHP-100" })} />);
      expect(screen.getByText("SHP-100")).toBeInTheDocument();
      expect(screen.queryByText("CASE-1")).not.toBeInTheDocument();
    });

    it("falls back to the case id when there is no shipment id", () => {
      render(<WorkCard item={makeItem({ case_id: "CASE-7", shipment_id: null })} />);
      expect(screen.getByText("CASE-7")).toBeInTheDocument();
    });
  });

  describe("risk and state", () => {
    it("shows the risk score when one is set", () => {
      render(<WorkCard item={makeItem({ risk_score: 87 })} />);
      expect(screen.getByText("risk 87")).toBeInTheDocument();
    });

    it("shows no risk score when it is null", () => {
      render(<WorkCard item={makeItem({ risk_score: null })} />);
      expect(screen.queryByText(/^risk /)).not.toBeInTheDocument();
    });

    it("shows the state label followed by the humanised top finding", () => {
      render(<WorkCard item={makeItem({ state: "HELD_FOR_REVIEW", top_finding: "SANCTIONS_HIT" })} />);
      expect(screen.getByText("Held for review · Sanctions hit")).toBeInTheDocument();
    });

    it("shows only the state label when there is no top finding", () => {
      render(<WorkCard item={makeItem({ state: "HELD_FOR_REVIEW", top_finding: null })} />);
      expect(screen.getByText("Held for review")).toBeInTheDocument();
      expect(screen.queryByText(/·/)).not.toBeInTheDocument();
    });

    it("humanises a state the label map does not know", () => {
      render(<WorkCard item={makeItem({ state: "SOME_NEW_STATE" })} />);
      expect(screen.getByText("Some new state")).toBeInTheDocument();
    });
  });

  describe("next action", () => {
    it("shows the text of the next action", () => {
      render(
        <WorkCard item={makeItem({ next_action: { code: "REQUEST_DOC", text: "Ask shipper for invoice" } })} />,
      );
      expect(screen.getByText("Ask shipper for invoice")).toBeInTheDocument();
    });

    it("shows no next action line when there is none", () => {
      const { container } = render(<WorkCard item={makeItem({ next_action: null })} />);
      expect(container.querySelector(".text-brand")).toBeNull();
    });
  });

  describe("owner", () => {
    it("names a person owner", () => {
      render(<WorkCard item={makeItem({ owner: { kind: "person", name: "Dana Reyes" } })} />);
      expect(screen.getByText("Dana Reyes")).toBeInTheDocument();
    });

    it("names a queue owner as a queue", () => {
      render(<WorkCard item={makeItem({ owner: { kind: "queue", name: "fraud_review" } })} />);
      expect(screen.getByText("Fraud review queue")).toBeInTheDocument();
    });

    it("shows an unassigned case as unassigned", () => {
      render(<WorkCard item={makeItem({ owner: { kind: "unassigned", name: null } })} />);
      expect(screen.getByText("Unassigned")).toBeInTheDocument();
    });
  });

  describe("SLA", () => {
    it("shows the time left in the neutral tone when more than an hour remains", () => {
      render(<WorkCard item={makeItem({ due_at: at(2 * HOUR) })} />);
      expect(screen.getByText("2h 0m left")).toHaveClass("text-dim");
    });

    it("warns in the warning tone when less than an hour remains", () => {
      render(<WorkCard item={makeItem({ due_at: at(30 * 60_000) })} />);
      expect(screen.getByText("30m left")).toHaveClass("text-risk-warn");
    });

    it("shows how long a case is overdue in the critical tone", () => {
      render(<WorkCard item={makeItem({ due_at: at(-90 * 60_000) })} />);
      expect(screen.getByText("Overdue 1h 30m")).toHaveClass("text-risk-critical");
    });

    it("judges the SLA against the now prop when one is given", () => {
      render(<WorkCard item={makeItem({ due_at: at(2 * HOUR) })} now={NOW + 10 * HOUR} />);
      expect(screen.getByText("Overdue 8h 0m")).toHaveClass("text-risk-critical");
    });

    it("says there is no SLA when no due date is set", () => {
      render(<WorkCard item={makeItem({ due_at: null })} />);
      expect(screen.getByText("No SLA")).toHaveClass("text-faint");
    });

    it("says there is no SLA when the due date cannot be read", () => {
      render(<WorkCard item={makeItem({ due_at: "not-a-date" })} />);
      expect(screen.getByText("No SLA")).toBeInTheDocument();
    });
  });

  describe("waiting time and information requests", () => {
    it("shows how long the case has been waiting", () => {
      render(<WorkCard item={makeItem({ waiting_since: at(-2 * HOUR) })} />);
      expect(screen.getByText("since 2h ago")).toBeInTheDocument();
    });

    it("shows no waiting time when none is recorded", () => {
      render(<WorkCard item={makeItem({ waiting_since: null })} />);
      expect(screen.queryByText(/^since /)).not.toBeInTheDocument();
    });

    it("says one information request in the singular", () => {
      render(<WorkCard item={makeItem({ information_rounds: 1 })} />);
      expect(screen.getByText("1 request")).toBeInTheDocument();
    });

    it("says several information requests in the plural", () => {
      render(<WorkCard item={makeItem({ information_rounds: 3 })} />);
      expect(screen.getByText("3 requests")).toBeInTheDocument();
    });

    it("shows no request count when no information was requested", () => {
      render(<WorkCard item={makeItem({ information_rounds: 0 })} />);
      expect(screen.queryByText(/request/)).not.toBeInTheDocument();
    });
  });
});
