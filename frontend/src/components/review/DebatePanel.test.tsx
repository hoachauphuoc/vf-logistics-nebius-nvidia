import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DebatePanel, readVerdict } from "./DebatePanel";

/**
 * The debate panel replaced a JSON dump, so the risk is that it misreads the
 * record: shows a verdict that is not there, hides that one was forced, or says
 * the debate changed a case it did not. Each test below is one of those.
 */

const disagree = {
  debate_trace: [
    { round: 1, tool: "search_tavily", arguments: { query: "Lotus Garment Works sanctions" } },
    { round: 2, tool: "render_final_verdict", arguments: {} },
  ],
  verdict: {
    verdict: "DISAGREE",
    confidence: 0.85,
    rationale: "One prior shipment and a round-number declared value.",
    recommended_action: "escalate",
    adjusted_risk_score: 78,
    forced: false,
  },
  rounds_used: 2,
};

describe("readVerdict", () => {
  it("reads the verdict at either depth it has lived at", () => {
    expect(readVerdict(disagree)?.verdict).toBe("DISAGREE");
    expect(readVerdict({ result: disagree })?.verdict).toBe("DISAGREE");
  });

  it("renders nothing rather than guessing at an unknown shape", () => {
    expect(readVerdict({ verdict: "maybe" })).toBeNull();
    expect(readVerdict({ verdict: { verdict: "disagree" } })).toBeNull();
    expect(readVerdict({})).toBeNull();
  });
});

describe("DebatePanel", () => {
  it("says the debate escalated the case, and by how much", () => {
    render(
      <DebatePanel
        debate={disagree}
        automatic
        effect={{ escalated: true, reason: "DISAGREE at 0.85 (threshold 0.70)", threshold: 0.7, risk_before: 65, risk_after: 78 }}
      />,
    );
    expect(screen.getByText("DISAGREE")).toBeInTheDocument();
    expect(screen.getByText(/escalated this case/i)).toBeInTheDocument();
    expect(screen.getByText(/65 → 78/)).toBeInTheDocument();
    expect(screen.getByText(/85% confident/)).toBeInTheDocument();
  });

  it("says when the debate changed nothing, and why", () => {
    render(
      <DebatePanel
        debate={{ verdict: { verdict: "CONFIRM", confidence: 0.9, forced: false } }}
        automatic
        effect={{ escalated: false, reason: "the Senior Auditor confirmed the junior analyst's assessment", threshold: 0.7, risk_before: 65, risk_after: 65 }}
      />,
    );
    expect(screen.getByText(/changed nothing/i)).toBeInTheDocument();
  });

  it("marks a forced verdict as a default, not a judgement", () => {
    render(
      <DebatePanel
        debate={{ verdict: { verdict: "CONFIRM", confidence: 0.4, forced: true, forced_reason: "rounds_exhausted" } }}
        automatic
      />,
    );
    expect(screen.getByText(/this is a default, not a judgement/i)).toBeInTheDocument();
    expect(screen.getByText(/used every round/i)).toBeInTheDocument();
  });

  it("lists what the auditor did in each round", () => {
    render(<DebatePanel debate={disagree} automatic={false} />);
    expect(screen.getByText(/Lotus Garment Works sanctions/)).toBeInTheDocument();
    expect(screen.getByText(/requested by a reviewer/i)).toBeInTheDocument();
  });

  it("keeps the raw record one click away", () => {
    render(<DebatePanel debate={disagree} automatic />);
    expect(screen.queryByText(/"rounds_used": 2/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /show the raw debate record/i }));
    expect(screen.getByText(/"rounds_used": 2/)).toBeInTheDocument();
  });
});
