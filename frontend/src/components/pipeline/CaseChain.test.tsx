import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Case } from "@/lib/types";

import { CaseChain } from "./CaseChain";

function caseWith(over: Partial<Case>): Case {
  return { case_id: "CASE-1", state: "ESCALATED" as never, ...over };
}

/** Every link carries a "Step N:" label, so the Nth row is found by its number. */
function rowFor(step: number): HTMLElement {
  const row = screen.getByText(`Step ${step}:`).closest("li");
  if (!row) throw new Error(`no row for step ${step}`);
  return row;
}

describe("CaseChain", () => {
  it("renders nothing when the case has no steps, actions or gate denials", () => {
    const { container } = render(<CaseChain case={caseWith({ steps: [], actions: [], gate_denials: [] })} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the fat fields are absent altogether", () => {
    const { container } = render(<CaseChain case={caseWith({})} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("titles the chain and explains what it lists", () => {
    render(<CaseChain case={caseWith({ steps: [{ agent: "compliance" }] })} />);
    expect(screen.getByRole("heading", { name: "End to end" })).toBeInTheDocument();
    expect(
      screen.getByText("Every step this case went through, in order, and what ran it."),
    ).toBeInTheDocument();
  });

  it("labels a known agent with its friendly name and numbers the step from 1", () => {
    render(<CaseChain case={caseWith({ steps: [{ agent: "model_armor" }] })} />);
    expect(screen.getByText("Step 1:")).toBeInTheDocument();
    expect(screen.getByText("Model Armor screen")).toBeInTheDocument();
  });

  it("humanises an agent that has no friendly name rather than dropping it", () => {
    render(<CaseChain case={caseWith({ steps: [{ agent: "widget_scorer" }] })} />);
    expect(screen.getByText("Widget scorer")).toBeInTheDocument();
  });

  it("labels a step with no agent as unknown", () => {
    render(<CaseChain case={caseWith({ steps: [{ agent: null as never }] })} />);
    expect(screen.getByText("Unknown")).toBeInTheDocument();
  });

  it("names Model Armor as the engine for a Model Armor step", () => {
    render(<CaseChain case={caseWith({ steps: [{ agent: "model_armor", model: "google-cloud-model-armor" }] })} />);
    expect(within(rowFor(1)).getByText("Google Model Armor")).toBeInTheDocument();
  });

  it("says the pre-filter step runs without a model", () => {
    render(<CaseChain case={caseWith({ steps: [{ agent: "sql_prefilter", model: null }] })} />);
    expect(within(rowFor(1)).getByText("Deterministic rules, no model")).toBeInTheDocument();
  });

  it("prefixes a Nemotron model with NVIDIA and its short name", () => {
    render(
      <CaseChain
        case={caseWith({ steps: [{ agent: "fraud_detection", model: "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B" }] })}
      />,
    );
    expect(within(rowFor(1)).getByText("NVIDIA Nemotron 3 Nano")).toBeInTheDocument();
  });

  it("shows the vision model under its short name without an NVIDIA prefix", () => {
    render(<CaseChain case={caseWith({ steps: [{ agent: "document_intake", model: "openbmb/MiniCPM-V-4_5" }] })} />);
    expect(within(rowFor(1)).getByText("MiniCPM-V 4.5")).toBeInTheDocument();
  });

  it("says no model ran when a model step records none", () => {
    render(<CaseChain case={caseWith({ steps: [{ agent: "compliance", model: null }] })} />);
    expect(within(rowFor(1)).getByText("no model")).toBeInTheDocument();
  });

  it("shows latency in seconds at one second or more and in milliseconds below it", () => {
    render(
      <CaseChain
        case={caseWith({
          steps: [
            { agent: "compliance", latency_ms: 1500 },
            { agent: "investigation", latency_ms: 420 },
          ],
        })}
      />,
    );
    expect(within(rowFor(1)).getByText("1.5 s")).toBeInTheDocument();
    expect(within(rowFor(2)).getByText("420 ms")).toBeInTheDocument();
  });

  it("counts only cited sources that have a url and joins them to the latency", () => {
    render(
      <CaseChain
        case={caseWith({
          steps: [
            {
              agent: "investigation",
              latency_ms: 1500,
              external_search_results: [{ title: "A", url: "https://a.example" }, { title: "no link" }],
            },
          ],
        })}
      />,
    );
    expect(within(rowFor(1)).getByText("1.5 s · Tavily: 1 source")).toBeInTheDocument();
  });

  it("uses the plural for more than one cited source", () => {
    render(
      <CaseChain
        case={caseWith({
          steps: [
            {
              agent: "compliance",
              external_search_results: [
                { title: "A", url: "https://a.example" },
                { title: "B", url: "https://b.example" },
              ],
            },
          ],
        })}
      />,
    );
    expect(within(rowFor(1)).getByText("Tavily: 2 sources")).toBeInTheDocument();
  });

  it("shows a finished step as done with no detail when it has no latency or sources", () => {
    render(<CaseChain case={caseWith({ steps: [{ agent: "compliance", latency_ms: 0 }] })} />);
    const row = rowFor(1);
    expect(within(row).getByText("done")).toBeInTheDocument();
    expect(within(row).queryByText(/ms|Tavily/)).toBeNull();
  });

  it("marks a step that Model Armor blocked as blocked and says no model read it", () => {
    render(
      <CaseChain
        case={caseWith({
          steps: [{ agent: "model_armor", result: { model_armor: { blocked: true } }, latency_ms: 300 }],
        })}
      />,
    );
    const row = rowFor(1);
    expect(within(row).getByText("blocked")).toBeInTheDocument();
    expect(within(row).getByText("Stopped before any model read it")).toBeInTheDocument();
    expect(within(row).queryByText("300 ms")).toBeNull();
  });

  it("marks a step whose output would not parse as failed", () => {
    render(<CaseChain case={caseWith({ steps: [{ agent: "compliance", parse_error: true }] })} />);
    expect(within(rowFor(1)).getByText("failed")).toBeInTheDocument();
  });

  it("adds a delegation gate row that names every refused action", () => {
    render(
      <CaseChain
        case={caseWith({
          gate_denials: [{ action: "release_shipment" }, { action: "publish_decision" }],
        })}
      />,
    );
    const row = rowFor(1);
    expect(within(row).getByText("Delegation gate")).toBeInTheDocument();
    expect(within(row).getByText("Published boundary")).toBeInTheDocument();
    expect(within(row).getByText("refused")).toBeInTheDocument();
    expect(within(row).getByText("Refused: release shipment, publish decision")).toBeInTheDocument();
  });

  it("marks the delegation gate as done when actions ran and nothing was refused", () => {
    render(<CaseChain case={caseWith({ actions: [{ action: "hold_shipment", status: "done" }] })} />);
    const row = rowFor(1);
    expect(within(row).getByText("Delegation gate")).toBeInTheDocument();
    expect(within(row).getByText("done")).toBeInTheDocument();
    expect(within(row).getByText("Every action inside the boundary")).toBeInTheDocument();
  });

  it("renders each action as a tool row with its own status", () => {
    render(
      <CaseChain
        case={caseWith({
          actions: [
            { action: "notify_webhook", status: "failed" },
            { action: "draft_sar", status: "skipped" },
          ],
        })}
      />,
    );
    const first = rowFor(2);
    expect(within(first).getByText("Notify webhook")).toBeInTheDocument();
    expect(within(first).getByText("Tool")).toBeInTheDocument();
    expect(within(first).getByText("failed")).toBeInTheDocument();
    expect(within(rowFor(3)).getByText("skipped")).toBeInTheDocument();
  });

  it("treats an action with an unrecognised status as done", () => {
    render(<CaseChain case={caseWith({ actions: [{ action: "hold_shipment", status: "pending" }] })} />);
    expect(within(rowFor(2)).getByText("done")).toBeInTheDocument();
  });

  it("lists steps, the gate and actions in that order, one row each", () => {
    render(
      <CaseChain
        case={caseWith({
          steps: [{ agent: "model_armor" }, { agent: "compliance" }],
          gate_denials: [{ action: "release_shipment" }],
          actions: [{ action: "hold_shipment", status: "done" }],
        })}
      />,
    );
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(4);
    expect(within(rows[0]).getByText("Model Armor screen")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Compliance")).toBeInTheDocument();
    expect(within(rows[2]).getByText("Delegation gate")).toBeInTheDocument();
    expect(within(rows[3]).getByText("Hold shipment")).toBeInTheDocument();
  });
});
