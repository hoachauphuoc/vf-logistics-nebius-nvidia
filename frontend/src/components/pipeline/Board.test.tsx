import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BOARD_COLUMNS, COLUMN_PAGE_SIZE, type BoardBucket } from "@/lib/pipeline";
import type { Case, CaseState } from "@/lib/types";

import { Board } from "./Board";

function makeCase(fields: Partial<Case> & Pick<Case, "case_id">): Case {
  return { state: "INGESTED", ...fields };
}

function makeCases(state: CaseState, count: number, prefix: string): Case[] {
  return Array.from({ length: count }, (_, i) =>
    makeCase({ case_id: `${prefix}${i}`, shipment_id: `SHP-${prefix}${i}`, state }),
  );
}

function bucket(state: CaseState, cases: Case[], total = cases.length): BoardBucket {
  const column = BOARD_COLUMNS.find((c) => c.state === state);
  if (!column) throw new Error(`no board column for ${state}`);
  return { column, cases, total };
}

function columnSection(label: string): HTMLElement {
  const section = screen.getByRole("heading", { name: label }).closest("section");
  if (!section) throw new Error(`no section for column ${label}`);
  return section;
}

function cardButtons(section: HTMLElement): HTMLElement[] {
  return within(section).queryAllByRole("button", { name: /^Open / });
}

describe("Board", () => {
  it("draws one section per bucket, headed by the column label", () => {
    render(
      <Board
        buckets={[bucket("INGESTED", []), bucket("AUTO_CLEARED", [])]}
        onOpen={vi.fn()}
        selectedCaseId={null}
      />,
    );

    expect(screen.getByRole("heading", { name: "Queued" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Cleared" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Blocked" })).not.toBeInTheDocument();
  });

  it("shows 'No cases' in a column that has none", () => {
    render(<Board buckets={[bucket("BLOCKED_BY_HUMAN", [])]} onOpen={vi.fn()} selectedCaseId={null} />);

    expect(within(columnSection("Blocked")).getByText("No cases")).toBeInTheDocument();
  });

  it("shows the page count with the exact column total when the page is a subset", () => {
    const cases = makeCases("INGESTED", 2, "Q");
    render(<Board buckets={[bucket("INGESTED", cases, 5)]} onOpen={vi.fn()} selectedCaseId={null} />);

    const section = columnSection("Queued");
    expect(within(section).getByText("/5").parentElement).toHaveTextContent("2/5");
  });

  it("shows a bare count, with no total, when the column holds all of its cases", () => {
    const cases = makeCases("INGESTED", 2, "Q");
    render(<Board buckets={[bucket("INGESTED", cases, 2)]} onOpen={vi.fn()} selectedCaseId={null} />);

    const section = columnSection("Queued");
    expect(within(section).getByText("2")).toBeInTheDocument();
    expect(within(section).queryByText(/^\/\d+$/)).not.toBeInTheDocument();
  });

  it("colours the count for a populated cleared column and leaves an empty one muted", () => {
    render(
      <Board
        buckets={[bucket("AUTO_CLEARED", makeCases("AUTO_CLEARED", 1, "C")), bucket("PENDING_HUMAN", [])]}
        onOpen={vi.fn()}
        selectedCaseId={null}
      />,
    );

    expect(within(columnSection("Cleared")).getByText("1")).toHaveClass("text-risk-clear");
    expect(within(columnSection("Awaiting a person")).getByText("0")).toHaveClass("text-faint");
  });

  it("shows at most one page of cards and a button naming how many are hidden", () => {
    const cases = makeCases("INGESTED", COLUMN_PAGE_SIZE + 2, "Q");
    render(<Board buckets={[bucket("INGESTED", cases)]} onOpen={vi.fn()} selectedCaseId={null} />);

    const section = columnSection("Queued");
    expect(cardButtons(section)).toHaveLength(COLUMN_PAGE_SIZE);
    expect(within(section).getByRole("button", { name: "Show 2 more" })).toBeInTheDocument();
  });

  it("expands a column to all its cards when 'Show more' is clicked, then collapses it again", () => {
    const cases = makeCases("INGESTED", COLUMN_PAGE_SIZE + 2, "Q");
    render(<Board buckets={[bucket("INGESTED", cases)]} onOpen={vi.fn()} selectedCaseId={null} />);
    const section = columnSection("Queued");

    fireEvent.click(within(section).getByRole("button", { name: "Show 2 more" }));
    expect(cardButtons(section)).toHaveLength(COLUMN_PAGE_SIZE + 2);

    fireEvent.click(within(section).getByRole("button", { name: "Collapse" }));
    expect(cardButtons(section)).toHaveLength(COLUMN_PAGE_SIZE);
    expect(within(section).getByRole("button", { name: "Show 2 more" })).toBeInTheDocument();
  });

  it("offers no expand button when the column fits in one page", () => {
    const cases = makeCases("INGESTED", COLUMN_PAGE_SIZE, "Q");
    render(<Board buckets={[bucket("INGESTED", cases)]} onOpen={vi.fn()} selectedCaseId={null} />);

    const section = columnSection("Queued");
    expect(cardButtons(section)).toHaveLength(COLUMN_PAGE_SIZE);
    expect(within(section).queryByRole("button", { name: /Show|Collapse/ })).not.toBeInTheDocument();
  });

  it("expands one column without expanding the others", () => {
    const first = makeCases("INGESTED", COLUMN_PAGE_SIZE + 1, "A");
    const second = makeCases("SPECIALISTS_DONE", COLUMN_PAGE_SIZE + 1, "B");
    render(
      <Board
        buckets={[bucket("INGESTED", first), bucket("SPECIALISTS_DONE", second)]}
        onOpen={vi.fn()}
        selectedCaseId={null}
      />,
    );

    fireEvent.click(within(columnSection("Queued")).getByRole("button", { name: "Show 1 more" }));

    expect(cardButtons(columnSection("Queued"))).toHaveLength(COLUMN_PAGE_SIZE + 1);
    expect(cardButtons(columnSection("Fraud + compliance"))).toHaveLength(COLUMN_PAGE_SIZE);
  });

  it("calls onOpen with the case id when a card is clicked", () => {
    const onOpen = vi.fn();
    const cases = makeCases("INGESTED", 2, "Q");
    render(<Board buckets={[bucket("INGESTED", cases)]} onOpen={onOpen} selectedCaseId={null} />);

    fireEvent.click(screen.getByRole("button", { name: "Open SHP-Q1" }));

    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen).toHaveBeenCalledWith("Q1");
  });

  it("marks only the selected card as selected", () => {
    const cases = makeCases("INGESTED", 2, "Q");
    render(<Board buckets={[bucket("INGESTED", cases)]} onOpen={vi.fn()} selectedCaseId="Q1" />);

    const selected = screen.getByRole("button", { name: "Open SHP-Q1" });
    const other = screen.getByRole("button", { name: "Open SHP-Q0" });
    expect(selected).toHaveClass("bg-white/[0.06]");
    expect(other.className).not.toBe(selected.className);
  });

  it("marks no card as selected when no case is selected", () => {
    const cases = makeCases("INGESTED", 2, "Q");
    render(<Board buckets={[bucket("INGESTED", cases)]} onOpen={vi.fn()} selectedCaseId={null} />);

    expect(screen.getByRole("button", { name: "Open SHP-Q0" })).not.toHaveClass("border-glow");
    expect(screen.getByRole("button", { name: "Open SHP-Q1" })).not.toHaveClass("border-glow");
  });

  it("puts the risk score in the card's accessible name when it is known", () => {
    const cases = [
      makeCase({ case_id: "R1", shipment_id: "SHP-R1", risk_score: 72 }),
      makeCase({ case_id: "R2", shipment_id: "SHP-R2", risk_score: null }),
    ];
    render(<Board buckets={[bucket("INGESTED", cases)]} onOpen={vi.fn()} selectedCaseId={null} />);

    expect(screen.getByRole("button", { name: "Open SHP-R1, risk 72" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open SHP-R2" })).toBeInTheDocument();
  });

  it("names the card by its case id when it has no shipment id", () => {
    const cases = [makeCase({ case_id: "CASE-9", shipment_id: null })];
    render(<Board buckets={[bucket("INGESTED", cases)]} onOpen={vi.fn()} selectedCaseId={null} />);

    expect(screen.getByRole("button", { name: "Open CASE-9" })).toBeInTheDocument();
    expect(screen.getByText("CASE-9")).toBeInTheDocument();
  });

  it("shows the route and declared value taken from the shipment", () => {
    const cases = [
      makeCase({
        case_id: "S1",
        shipment_id: "SHP-S1",
        shipment: { origin: "Rotterdam", destination: "Singapore", declared_value: 12500 } as never,
      }),
    ];
    render(<Board buckets={[bucket("INGESTED", cases)]} onOpen={vi.fn()} selectedCaseId={null} />);

    expect(screen.getByText("Rotterdam → Singapore")).toBeInTheDocument();
    expect(screen.getByText("$12,500")).toBeInTheDocument();
  });

  it("says 'awaiting first agent' on a card with no notes yet", () => {
    const cases = [makeCase({ case_id: "N1", shipment_id: "SHP-N1" })];
    render(<Board buckets={[bucket("INGESTED", cases)]} onOpen={vi.fn()} selectedCaseId={null} />);

    expect(screen.getByText("awaiting first agent")).toBeInTheDocument();
  });

  it("lists the source and the compliance verdict as notes on a card", () => {
    const cases = [
      makeCase({
        case_id: "N2",
        shipment_id: "SHP-N2",
        state: "AUTO_CLEARED",
        source: "document",
        compliance_status: "CLEARED",
      }),
    ];
    render(<Board buckets={[bucket("AUTO_CLEARED", cases)]} onOpen={vi.fn()} selectedCaseId={null} />);

    expect(screen.getByText("from document · compliance: cleared")).toBeInTheDocument();
  });

  it("shows the model and floor scores, and flags when the floor raised the risk", () => {
    const cases = [
      makeCase({
        case_id: "F1",
        shipment_id: "SHP-F1",
        risk_score: 70,
        reconciliation: { model_risk: 40, risk_floor: 70 } as never,
      }),
    ];
    render(<Board buckets={[bucket("INGESTED", cases)]} onOpen={vi.fn()} selectedCaseId={null} />);

    const line = screen.getByText("model 40 · floor 70");
    expect(line).toHaveTextContent("floor applied");
  });

  it("shows the processing spinner on a claimed case that is still active", () => {
    const cases = [makeCase({ case_id: "P1", shipment_id: "SHP-P1", claimed: true })];
    render(<Board buckets={[bucket("INGESTED", cases)]} onOpen={vi.fn()} selectedCaseId={null} />);

    expect(screen.getByLabelText("processing")).toBeInTheDocument();
  });

  it("does not show the processing spinner on a claimed case that is already terminal", () => {
    const cases = [
      makeCase({ case_id: "P2", shipment_id: "SHP-P2", state: "AUTO_CLEARED", claimed: true }),
    ];
    render(<Board buckets={[bucket("AUTO_CLEARED", cases)]} onOpen={vi.fn()} selectedCaseId={null} />);

    expect(screen.queryByLabelText("processing")).not.toBeInTheDocument();
  });
});
