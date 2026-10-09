import { describe, expect, it } from "vitest";

import { buildChain } from "./case-chain";
import type { Case } from "./types";

type ChainInput = Pick<Case, "steps" | "actions" | "gate_denials">;

const NANO = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B";
const SUPER = "nvidia/nemotron-3-super-120b-a12b";
const ULTRA = "nvidia/Nemotron-3-Ultra-550b-a55b";

describe("buildChain", () => {
  it("lays out a full run in order, naming the NVIDIA model on each hop", () => {
    const c: ChainInput = {
      steps: [
        { agent: "document_intake", model: "openbmb/MiniCPM-V-4_5", latency_ms: 4200 },
        { agent: "fraud_detection", model: NANO, latency_ms: 900 },
        {
          agent: "compliance",
          model: NANO,
          latency_ms: 1100,
          external_search_results: [{ url: "https://a.example" }, { url: "https://b.example" }, { title: "no url" }],
        },
        { agent: "investigation", model: SUPER, latency_ms: 2500 },
        { agent: "auto_debate", model: ULTRA, latency_ms: 30_000 },
      ],
      actions: [
        { action: "hold_shipment", status: "done" },
        { action: "draft_sar", status: "done" },
      ],
      gate_denials: [],
    };

    const chain = buildChain(c);
    expect(chain.map((l) => l.label)).toEqual([
      "Document intake",
      "Fraud detection",
      "Compliance",
      "Investigation",
      "Senior Auditor debate",
      "Delegation gate",
      "Hold shipment",
      "Draft SAR",
    ]);
    expect(chain[1].engine).toBe("NVIDIA Nemotron 3 Nano");
    expect(chain[3].engine).toBe("NVIDIA Nemotron 3 Super");
    expect(chain[4].engine).toBe("NVIDIA Nemotron 3 Ultra");
    // MiniCPM-V is not an NVIDIA model and must not be labelled as one.
    expect(chain[0].engine).not.toMatch(/NVIDIA/);
    // Only citations with a URL count as sources read.
    expect(chain[2].detail).toContain("Tavily: 2 sources");
    expect(chain[4].detail).toBe("30.0 s");
  });

  it("shows a pre-filter case as rules only, with no model", () => {
    const chain = buildChain({
      steps: [{ agent: "sql_prefilter", model: null, latency_ms: 0 }],
      actions: [{ action: "release_shipment", status: "done" }],
      gate_denials: [],
    });
    expect(chain[0]).toMatchObject({ label: "Rules pre-filter", engine: "Deterministic rules, no model", detail: null });
    expect(chain[1]).toMatchObject({ label: "Delegation gate", status: "done" });
  });

  it("marks a document Model Armor stopped as blocked", () => {
    const chain = buildChain({
      steps: [
        {
          agent: "model_armor",
          model: "google-cloud-model-armor",
          latency_ms: null,
          result: { model_armor: { blocked: true } },
        },
      ],
      actions: [],
      gate_denials: [],
    });
    expect(chain).toHaveLength(1);
    expect(chain[0]).toMatchObject({ engine: "Google Model Armor", status: "blocked" });
    expect(chain[0].detail).toMatch(/before any model/);
  });

  it("records the gate's refusal and the refused action", () => {
    const chain = buildChain({
      steps: [{ agent: "fraud_detection", model: NANO }],
      actions: [{ action: "release_shipment", status: "denied" }],
      gate_denials: [{ action: "release_shipment", reason: "no active boundary" }],
    });
    const gate = chain.find((l) => l.key === "gate");
    expect(gate).toMatchObject({ status: "denied" });
    expect(gate?.detail).toMatch(/release shipment/i);
    expect(chain[chain.length - 1]).toMatchObject({ label: "Release shipment", status: "denied" });
  });

  it("is empty for a case nothing has run on yet", () => {
    expect(buildChain({ steps: [], actions: [], gate_denials: [] })).toEqual([]);
    expect(buildChain({})).toEqual([]);
  });
});
