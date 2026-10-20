import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DebatePanel, readVerdict } from "./DebatePanel";

/**
 * Branches of the debate panel that the main suite does not reach: the verdict at
 * the nested depth, malformed fields that must read as absent, every trace row
 * label, the forced-reason fallback, and the raw-record toggle.
 */

describe("readVerdict fields", () => {
  it("reads every field of a full verdict record", () => {
    expect(
      readVerdict({
        verdict: {
          verdict: "DISAGREE",
          confidence: 0.91,
          rationale: "Round-number declared value.",
          recommended_action: "escalate",
          adjusted_risk_score: 78,
          forced: true,
          forced_reason: "no_tool_call",
        },
      }),
    ).toEqual({
      verdict: "DISAGREE",
      confidence: 0.91,
      rationale: "Round-number declared value.",
      recommended: "escalate",
      adjusted: 78,
      forced: true,
      forcedReason: "no_tool_call",
    });
  });

  it("falls back to the nested result when the top-level verdict is not a record", () => {
    const verdict = readVerdict({ verdict: "DISAGREE", result: { verdict: { verdict: "CONFIRM" } } });
    expect(verdict?.verdict).toBe("CONFIRM");
  });

  it("treats absent or wrongly typed fields as null, and forced only when it is exactly true", () => {
    const verdict = readVerdict({
      verdict: {
        verdict: "CONFIRM",
        confidence: "high",
        rationale: 42,
        recommended_action: null,
        adjusted_risk_score: "78",
        forced: "true",
        forced_reason: 1,
      },
    });
    expect(verdict).toEqual({
      verdict: "CONFIRM",
      confidence: null,
      rationale: null,
      recommended: null,
      adjusted: null,
      forced: false,
      forcedReason: null,
    });
  });

  it("treats a non-finite score as absent", () => {
    expect(readVerdict({ verdict: { verdict: "CONFIRM", adjusted_risk_score: Infinity } })?.adjusted).toBeNull();
  });

  it("returns null for an array or null in the verdict slot", () => {
    expect(readVerdict({ verdict: [{ verdict: "CONFIRM" }] })).toBeNull();
    expect(readVerdict({ verdict: null })).toBeNull();
  });
});

describe("DebatePanel verdict display", () => {
  it("reads a verdict nested under result and shows it", () => {
    render(
      <DebatePanel
        debate={{ result: { verdict: { verdict: "CONFIRM", confidence: 0.5, forced: false } } }}
        automatic
      />,
    );
    expect(screen.getByText("CONFIRM")).toBeInTheDocument();
    expect(screen.getByText("50% confident")).toBeInTheDocument();
    expect(screen.getByTitle(/agreed with the junior analyst/i)).toBeInTheDocument();
  });

  it("explains a disagreement in the badge tooltip", () => {
    render(<DebatePanel debate={{ verdict: { verdict: "DISAGREE", forced: false } }} automatic />);
    expect(screen.getByTitle(/found something the junior analyst missed/i)).toBeInTheDocument();
  });

  it("shows no confidence figure when the verdict carries none", () => {
    render(<DebatePanel debate={{ verdict: { verdict: "CONFIRM", forced: false } }} automatic />);
    expect(screen.queryByText(/confident/)).toBeNull();
  });

  it("shows the rationale, the recommended action and the rounded auditor score", () => {
    render(
      <DebatePanel
        debate={{
          verdict: {
            verdict: "DISAGREE",
            rationale: "Ownership changed two weeks before the shipment.",
            recommended_action: "escalate",
            adjusted_risk_score: 78.6,
            forced: false,
          },
        }}
        automatic
      />,
    );
    expect(screen.getByText("Ownership changed two weeks before the shipment.")).toBeInTheDocument();
    expect(screen.getByText("recommends")).toBeInTheDocument();
    expect(screen.getByText("escalate")).toBeInTheDocument();
    expect(screen.getByText(/auditor.s score/)).toBeInTheDocument();
    expect(screen.getByText("79")).toBeInTheDocument();
  });

  it("omits the recommendation and score rows when neither is present", () => {
    render(<DebatePanel debate={{ verdict: { verdict: "CONFIRM", forced: false } }} automatic />);
    expect(screen.queryByText("recommends")).toBeNull();
    expect(screen.queryByText(/auditor.s score/)).toBeNull();
  });

  it("says no verdict was recognised when the record has none", () => {
    render(<DebatePanel debate={{ verdict: "maybe" }} automatic />);
    expect(screen.getByText(/no verdict in a recognised shape/i)).toBeInTheDocument();
    expect(screen.queryByText("CONFIRM")).toBeNull();
    expect(screen.queryByText("DISAGREE")).toBeNull();
  });

  it("names the reason a forced verdict was filled in", () => {
    render(
      <DebatePanel
        debate={{ verdict: { verdict: "CONFIRM", forced: true, forced_reason: "unparseable_verdict" } }}
        automatic
      />,
    );
    expect(screen.getByText(/the model's verdict could not be read/)).toBeInTheDocument();
  });

  it("falls back to a generic reason when a forced verdict gives no known reason", () => {
    render(
      <DebatePanel
        debate={{ verdict: { verdict: "CONFIRM", forced: true, forced_reason: "something_new" } }}
        automatic
      />,
    );
    expect(screen.getByText(/no usable verdict was rendered/)).toBeInTheDocument();
  });
});

describe("DebatePanel effect", () => {
  const disagree = { verdict: { verdict: "DISAGREE", confidence: 0.9, forced: false } };

  it("does not say the case was escalated when the risk did not rise", () => {
    render(
      <DebatePanel
        debate={disagree}
        automatic
        effect={{ escalated: true, reason: "DISAGREE at 0.90", threshold: 0.7, risk_before: 78, risk_after: 78 }}
      />,
    );
    expect(screen.getByText(/escalated this case/i)).toBeInTheDocument();
    expect(screen.queryByText(/raised/)).toBeNull();
    expect(screen.getByText(/a person still decides it/i)).toBeInTheDocument();
  });

  it("states the threshold when the debate changed nothing", () => {
    render(
      <DebatePanel
        debate={disagree}
        automatic
        effect={{ escalated: false, reason: "confidence was below the threshold", threshold: 0.7, risk_before: 40, risk_after: 40 }}
      />,
    );
    expect(screen.getByText(/confidence was below the threshold/)).toBeInTheDocument();
    expect(screen.getByText(/at 70% confidence or more/)).toBeInTheDocument();
    expect(screen.queryByText(/escalated this case/i)).toBeNull();
  });

  it("shows no effect line when the effect is absent or null", () => {
    const { rerender } = render(<DebatePanel debate={disagree} automatic />);
    expect(screen.queryByText(/changed nothing/i)).toBeNull();
    expect(screen.queryByText(/escalated this case/i)).toBeNull();

    rerender(<DebatePanel debate={disagree} automatic effect={null} />);
    expect(screen.queryByText(/changed nothing/i)).toBeNull();
    expect(screen.queryByText(/escalated this case/i)).toBeNull();
  });
});

describe("DebatePanel trace", () => {
  it("labels each kind of trace step and keeps its round and detail", () => {
    const { container } = render(
      <DebatePanel
        debate={{
          debate_trace: [
            { round: 1, tool: "search_tavily", arguments: { query: "Lotus Garment Works sanctions" } },
            { round: 2, tool: "request_nano_reevaluation", arguments: { focus_areas: ["ownership", "routing"] } },
            { round: 2, tool: "render_final_verdict", arguments: {}, arguments_unparseable: true },
            { round: null, tool: "forced_verdict" },
            { type: "no_tool_call", round: 3 },
            { tool: "lookup_registry", round: 1 },
            { round: 4 },
            "not a record",
          ],
          verdict: { verdict: "CONFIRM", forced: false },
        }}
        automatic
      />,
    );

    expect(screen.getByText("Searched the web")).toBeInTheDocument();
    expect(screen.getByText(/Lotus Garment Works sanctions/)).toBeInTheDocument();
    expect(screen.getByText("Asked the junior analyst to look again")).toBeInTheDocument();
    expect(screen.getByText(/ownership, routing/)).toBeInTheDocument();
    expect(screen.getByText("Rendered the verdict")).toBeInTheDocument();
    expect(screen.getByText(/arguments were not valid JSON/)).toBeInTheDocument();
    expect(screen.getByText("Verdict filled in by the system")).toBeInTheDocument();
    expect(screen.getByText("Answered without using a tool")).toBeInTheDocument();
    expect(screen.getByText("lookup_registry")).toBeInTheDocument();
    expect(screen.getByText("step")).toBeInTheDocument();
    expect(screen.getByText("round 4")).toBeInTheDocument();
    expect(container.querySelectorAll("li")).toHaveLength(7);
  });

  it("reads the trace nested under result when the top level has none", () => {
    render(
      <DebatePanel
        debate={{ result: { debate_trace: [{ round: 1, tool: "search_tavily", arguments: { query: "nested query" } }] } }}
        automatic
      />,
    );
    expect(screen.getByText("Searched the web")).toBeInTheDocument();
    expect(screen.getByText(/nested query/)).toBeInTheDocument();
  });

  it("leaves out the detail of a search that has no query and the round of a step that has none", () => {
    const { container } = render(
      <DebatePanel
        debate={{ debate_trace: [{ tool: "search_tavily", arguments: {} }], verdict: { verdict: "CONFIRM", forced: false } }}
        automatic
      />,
    );
    expect(screen.getByText("Searched the web")).toBeInTheDocument();
    expect(screen.queryByText(/:/)).toBeNull();
    expect(container.querySelector("li span")?.textContent).toBe("");
  });

  it("leaves out the focus list when the re-evaluation names no focus areas", () => {
    render(
      <DebatePanel
        debate={{ debate_trace: [{ round: 1, tool: "request_nano_reevaluation", arguments: { focus_areas: "routing" } }] }}
        automatic
      />,
    );
    expect(screen.getByText("Asked the junior analyst to look again")).toBeInTheDocument();
    expect(screen.queryByText(/routing/)).toBeNull();
  });

  it("renders no trace list when the trace is not an array", () => {
    const { container } = render(
      <DebatePanel debate={{ debate_trace: "round 1 search" }} automatic />,
    );
    expect(container.querySelector("ol")).toBeNull();
  });
});

describe("DebatePanel provenance and raw record", () => {
  it("says a reviewer requested the debate when it was not automatic", () => {
    render(<DebatePanel debate={{}} automatic={false} />);
    expect(screen.getByText("requested by a reviewer")).toBeInTheDocument();
    expect(screen.queryByText("fired automatically")).toBeNull();
  });

  it("says the debate fired automatically when it was automatic", () => {
    render(<DebatePanel debate={{}} automatic />);
    expect(screen.getByText("fired automatically")).toBeInTheDocument();
  });

  it("hides the raw record again on a second click", () => {
    render(<DebatePanel debate={{ rounds_used: 3 }} automatic />);
    const toggle = screen.getByRole("button", { name: /show the raw debate record/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: /hide the raw debate record/i })).toBeInTheDocument();
    expect(screen.getByText(/"rounds_used": 3/)).toBeInTheDocument();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/"rounds_used": 3/)).toBeNull();
  });
});
