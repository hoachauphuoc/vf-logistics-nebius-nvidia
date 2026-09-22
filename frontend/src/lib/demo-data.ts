import type {
  ComplianceAuditResponse,
  Tenant,
  TenantUsageResponse,
} from "./types";

/**
 * Demo fixtures.
 *
 * Every entity in here is invented. Adverse-media fixtures are attached only to
 * fictional companies, never to a real one, because a screenshot of this console
 * showing a real firm next to a sanctions badge is a defamation risk and not a
 * demo.
 *
 * Finding codes are the real ones emitted by verifier.py and model ids are the
 * real ones from config.py, so what the console renders matches what the
 * backend would actually return. The numbers are drawn from the measured
 * benchmark: about $0.00095 of tokens per audit that reaches the model layer,
 * and $0 for an audit the deterministic rules settle on their own.
 */

/** The real model ids, from src/vf_logistics/config.py. */
const NANO = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B";
const SUPER = "nvidia/nemotron-3-super-120b-a12b";

export const DEMO_TENANTS: Tenant[] = [
  { id: "apex-logistics", name: "Apex Logistics", descriptor: "Freight forwarder · EU/APAC" },
  { id: "meridian-freight", name: "Meridian Freight", descriptor: "3PL · high volume" },
  { id: "kestrel-shipping", name: "Kestrel Shipping", descriptor: "Project cargo · dual-use" },
];

export const DEFAULT_TENANT_ID = DEMO_TENANTS[0].id;

interface AuditSeed {
  ref: string;
  shipment: string;
  outcome: ComplianceAuditResponse["outcome"];
  effective: number;
  floor: number;
  modelRisk: number | null;
  findings: ComplianceAuditResponse["findings"];
  minutesAgo: number;
  usage: Partial<ComplianceAuditResponse["usage"]>;
  agents?: string[];
  disputed?: boolean;
  reviewReason?: string | null;
}

function build(
  tenantId: string,
  index: number,
  seed: AuditSeed,
): ComplianceAuditResponse {
  const agents = seed.agents ?? ["fraud_detection", "compliance_screening"];
  const modelVersions: Record<string, string> = {};
  const promptHashes: Record<string, string> = {};
  agents.forEach((agent, i) => {
    modelVersions[agent] = agent === "investigation_debate" ? SUPER : NANO;
    // Deterministic stand-in for a real sha256, so the same fixture always
    // renders the same hash instead of churning on every reload.
    promptHashes[agent] = stableHash(`${tenantId}:${seed.ref}:${agent}:${i}`);
  });

  const created = new Date(Date.now() - seed.minutesAgo * 60_000);
  const completed = new Date(created.getTime() + (seed.usage.latency_ms ?? 1800));

  return {
    audit_id: `aud_${stableHash(`${tenantId}:${seed.ref}`).slice(0, 24)}`,
    case_id: `CASE-${tenantId.slice(0, 3).toUpperCase()}-${1000 + index}`,
    shipment_id: seed.shipment,
    client_reference: seed.ref,
    outcome: seed.outcome,
    effective_risk: seed.effective,
    model_risk: seed.modelRisk,
    risk_floor: seed.floor,
    score_disputed: seed.disputed ?? false,
    findings: seed.findings,
    requires_human_review:
      seed.outcome === "HELD_FOR_REVIEW" || seed.outcome === "PENDING_HUMAN",
    review_reason: seed.reviewReason ?? null,
    lineage: {
      audit_id: `aud_${stableHash(`${tenantId}:${seed.ref}`).slice(0, 24)}`,
      prompt_hashes: promptHashes,
      model_versions: modelVersions,
      sanctions_synced_at: new Date(Date.now() - 86_400_000 * 2).toISOString(),
      sanctions_list_age_days: 2,
      ruleset_version: 7,
    },
    usage: {
      input_tokens: seed.usage.input_tokens ?? 0,
      output_tokens: seed.usage.output_tokens ?? 0,
      estimated_cost_usd: seed.usage.estimated_cost_usd ?? 0,
      agent_calls: seed.usage.agent_calls ?? 0,
      latency_ms: seed.usage.latency_ms ?? null,
    },
    created_at: created.toISOString(),
    completed_at: completed.toISOString(),
    idempotent_replay: false,
  };
}

/** FNV-1a, hex-padded. Not cryptographic -- it only has to be stable. */
function stableHash(input: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < input.length; i += 1) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  let out = "";
  let cur = h;
  for (let i = 0; i < 8; i += 1) {
    cur = Math.imul(cur ^ (cur >>> 15), 0x2545f491) >>> 0;
    out += cur.toString(16).padStart(8, "0");
  }
  return out;
}

const SEEDS: Record<string, AuditSeed[]> = {
  "apex-logistics": [
    {
      ref: "APEX-PO-88421",
      shipment: "SHP-2026-441029",
      outcome: "BLOCKED",
      effective: 100,
      floor: 100,
      modelRisk: 92,
      minutesAgo: 12,
      agents: ["fraud_detection", "compliance_screening", "hs_classifier"],
      usage: {
        input_tokens: 4120,
        output_tokens: 610,
        estimated_cost_usd: 0.00121,
        agent_calls: 3,
        latency_ms: 2740,
      },
      reviewReason: "Sanctions match on the consignee; cleared routes are not applicable.",
      findings: [
        {
          code: "SANCTIONS_MATCH",
          severity: "CRITICAL",
          detail:
            "Consignee 'Zarubin Handelsgesellschaft mbH' matches OFAC SDN entry " +
            "under program RUSSIA-EO14024. Match on registration number and " +
            "normalised company name.",
          floor: 100,
          source_entity_ids: ["ofac-sdn-38821", "eu-fsf-2024-1174"],
        },
        {
          code: "HIGH_RISK_DESTINATION",
          severity: "HIGH",
          detail: "Declared destination routes through a designated diversion hub.",
          floor: 70,
          source_entity_ids: [],
        },
        {
          code: "DUAL_USE_HS_CODE",
          severity: "HIGH",
          detail: "HS 854231 appears on EU Annex I (dual-use), category 3A001.",
          floor: 80,
          source_entity_ids: [],
        },
      ],
    },
    {
      ref: "APEX-PO-88433",
      shipment: "SHP-2026-441055",
      outcome: "HELD_FOR_REVIEW",
      effective: 78,
      floor: 70,
      modelRisk: 78,
      minutesAgo: 34,
      agents: ["fraud_detection", "compliance_screening", "zero_day"],
      usage: {
        input_tokens: 6890,
        output_tokens: 1240,
        estimated_cost_usd: 0.00214,
        agent_calls: 4,
        latency_ms: 8310,
      },
      reviewReason: "Adverse media on the shipper, absent from all screening lists.",
      findings: [
        {
          code: "ZERO_DAY_ADVERSE_MEDIA",
          severity: "HIGH",
          detail:
            "Shipper 'Northwind Components Ltd' appears in procurement-network " +
            "reporting published 9 days ago. Not present on any screening list.",
          floor: 70,
          source_entity_ids: [],
          evidence_urls: [
            "https://www.reuters.com/markets/commodities/demo-procurement-network-report",
            "https://www.tradewindsnews.com/regulation/demo-shell-intermediary-filing",
          ],
        },
        {
          code: "RECENTLY_REGISTERED_SHIPPER",
          severity: "MEDIUM",
          detail: "Shipper registered 71 days ago against a 2-year lane history.",
          floor: 40,
          source_entity_ids: [],
        },
      ],
    },
    {
      ref: "APEX-PO-88440",
      shipment: "SHP-2026-441090",
      outcome: "CLEARED",
      effective: 12,
      floor: 0,
      modelRisk: 12,
      minutesAgo: 51,
      usage: {
        input_tokens: 3010,
        output_tokens: 430,
        estimated_cost_usd: 0.00088,
        agent_calls: 2,
        latency_ms: 2110,
      },
      findings: [
        {
          code: "WHITELIST_MATCH",
          severity: "CLEAR",
          detail: "Shipper on the tenant allow-list with 148 prior clean movements.",
          floor: 0,
          source_entity_ids: [],
        },
      ],
    },
    {
      // The branch worth demonstrating: a clearance resting on a check that did
      // not run. Both codes carry floor 0, so the score never reaches the review
      // threshold and the audit clears with a gap in it.
      ref: "APEX-PO-88447",
      shipment: "SHP-2026-441112",
      outcome: "CLEARED",
      effective: 18,
      floor: 0,
      modelRisk: 18,
      minutesAgo: 68,
      agents: ["fraud_detection", "compliance_screening", "zero_day"],
      usage: {
        input_tokens: 3440,
        output_tokens: 520,
        estimated_cost_usd: 0.00097,
        agent_calls: 3,
        latency_ms: 2480,
      },
      findings: [
        {
          code: "ZERO_DAY_SEARCH_DID_NOT_RUN",
          severity: "HIGH",
          detail:
            "Negative-news search did not execute: the search provider returned " +
            "rate_limited. No conclusion about adverse media can be drawn.",
          floor: 40,
          source_entity_ids: [],
          evidence_urls: [],
        },
        {
          code: "HS_DESCRIPTION_CHECK_UNAVAILABLE",
          severity: "MEDIUM",
          detail: "HS classification call failed; declared heading was not corroborated.",
          floor: 0,
          source_entity_ids: [],
        },
      ],
    },
    {
      ref: "APEX-PO-88451",
      shipment: "SHP-2026-441130",
      outcome: "HELD_FOR_REVIEW",
      effective: 84,
      floor: 80,
      modelRisk: 61,
      disputed: true,
      minutesAgo: 95,
      agents: [
        "fraud_detection",
        "compliance_screening",
        "hs_classifier",
        "investigation_debate",
      ],
      usage: {
        input_tokens: 12_400,
        output_tokens: 2980,
        estimated_cost_usd: 0.01042,
        agent_calls: 6,
        latency_ms: 19_450,
      },
      reviewReason:
        "Declared heading inconsistent with cargo description on a dual-use item; " +
        "model scored below the deterministic floor.",
      findings: [
        {
          code: "HS_DESCRIPTION_MISMATCH_DUAL_USE",
          severity: "CRITICAL",
          detail:
            "Declared HS 8473 (parts of office machines) against a description of " +
            "frequency converters. Suggested heading 8504.40, which is dual-use " +
            "controlled.",
          floor: 80,
          source_entity_ids: [],
        },
        {
          code: "VALUE_DENSITY_HIGH",
          severity: "MEDIUM",
          detail: "Declared value per kg is 6.2x the lane median.",
          floor: 40,
          source_entity_ids: [],
        },
      ],
    },
    {
      ref: "APEX-PO-88455",
      shipment: "SHP-2026-441144",
      outcome: "CLEARED",
      effective: 5,
      floor: 0,
      modelRisk: null,
      minutesAgo: 121,
      agents: [],
      usage: {
        input_tokens: 0,
        output_tokens: 0,
        estimated_cost_usd: 0,
        agent_calls: 0,
        latency_ms: 40,
      },
      findings: [
        {
          code: "LOW_VALUE_DOMESTIC",
          severity: "CLEAR",
          detail:
            "Declared value below the low-value threshold on a safe domestic " +
            "route. Settled by deterministic rules; no model tokens spent.",
          floor: 0,
          source_entity_ids: [],
        },
      ],
    },
  ],

  "meridian-freight": [
    {
      ref: "MER-3391-A",
      shipment: "MF-2026-770412",
      outcome: "CLEARED",
      effective: 8,
      floor: 0,
      modelRisk: null,
      minutesAgo: 6,
      agents: [],
      usage: {
        input_tokens: 0,
        output_tokens: 0,
        estimated_cost_usd: 0,
        agent_calls: 0,
        latency_ms: 32,
      },
      findings: [
        {
          code: "WHITELIST_MATCH",
          severity: "CLEAR",
          detail: "Known shipper, 1,204 prior movements on this lane.",
          floor: 0,
          source_entity_ids: [],
        },
      ],
    },
    {
      ref: "MER-3391-B",
      shipment: "MF-2026-770488",
      outcome: "HELD_FOR_REVIEW",
      effective: 62,
      floor: 60,
      modelRisk: 44,
      minutesAgo: 23,
      usage: {
        input_tokens: 3980,
        output_tokens: 560,
        estimated_cost_usd: 0.00104,
        agent_calls: 2,
        latency_ms: 2390,
      },
      reviewReason: "Freight cost absent; the ratio check could not be computed.",
      findings: [
        {
          code: "FREIGHT_MISSING",
          severity: "HIGH",
          detail:
            "No freight cost on the declaration, so the freight-to-value ratio " +
            "could not be evaluated.",
          floor: 60,
          source_entity_ids: [],
        },
      ],
    },
    {
      ref: "MER-3392-C",
      shipment: "MF-2026-770501",
      outcome: "CLEARED",
      effective: 15,
      floor: 0,
      modelRisk: 15,
      minutesAgo: 47,
      usage: {
        input_tokens: 2870,
        output_tokens: 390,
        estimated_cost_usd: 0.00081,
        agent_calls: 2,
        latency_ms: 1960,
      },
      findings: [],
    },
    {
      ref: "MER-3392-D",
      shipment: "MF-2026-770540",
      outcome: "ERROR",
      effective: 60,
      floor: 60,
      modelRisk: null,
      minutesAgo: 62,
      agents: ["fraud_detection"],
      usage: {
        input_tokens: 1240,
        output_tokens: 0,
        estimated_cost_usd: 0.00021,
        agent_calls: 1,
        latency_ms: 30_120,
      },
      reviewReason: "Screening index failed to load; audit returned no verdict.",
      findings: [
        {
          code: "SANCTIONS_SCREENING_UNAVAILABLE",
          severity: "HIGH",
          detail:
            "The sanctions index could not be loaded. The absence of a match " +
            "below is not a clearance.",
          floor: 60,
          source_entity_ids: [],
        },
      ],
    },
    {
      ref: "MER-3393-E",
      shipment: "MF-2026-770577",
      outcome: "CLEARED",
      effective: 11,
      floor: 0,
      modelRisk: 11,
      minutesAgo: 88,
      usage: {
        input_tokens: 3110,
        output_tokens: 420,
        estimated_cost_usd: 0.00089,
        agent_calls: 2,
        latency_ms: 2050,
      },
      findings: [],
    },
  ],

  "kestrel-shipping": [
    {
      ref: "KES-DU-0071",
      shipment: "KS-2026-119003",
      outcome: "BLOCKED",
      effective: 100,
      floor: 100,
      modelRisk: 96,
      minutesAgo: 18,
      agents: [
        "fraud_detection",
        "compliance_screening",
        "hs_classifier",
        "investigation_debate",
      ],
      usage: {
        input_tokens: 14_200,
        output_tokens: 3410,
        estimated_cost_usd: 0.01188,
        agent_calls: 6,
        latency_ms: 21_900,
      },
      reviewReason: "Sanctioned intermediary plus a controlled heading.",
      findings: [
        {
          code: "SANCTIONS_MATCH",
          severity: "CRITICAL",
          detail:
            "Intermediary 'Orient Bay Trading FZE' matches an EU consolidated " +
            "list entry under EU-SYRIA. Matched on transliterated name variant.",
          floor: 100,
          source_entity_ids: ["eu-fsf-2023-0912"],
        },
        {
          code: "MULTIPLE_DIVERSION_HUBS",
          severity: "HIGH",
          detail: "Routing passes through two designated diversion hubs.",
          floor: 75,
          source_entity_ids: [],
        },
      ],
    },
    {
      ref: "KES-DU-0074",
      shipment: "KS-2026-119041",
      outcome: "HELD_FOR_REVIEW",
      effective: 80,
      floor: 80,
      modelRisk: 72,
      minutesAgo: 41,
      agents: ["fraud_detection", "compliance_screening", "hs_classifier"],
      usage: {
        input_tokens: 5240,
        output_tokens: 880,
        estimated_cost_usd: 0.00152,
        agent_calls: 3,
        latency_ms: 4120,
      },
      reviewReason: "Dual-use heading with a thin shipper history.",
      findings: [
        {
          code: "DUAL_USE_HS_CODE",
          severity: "HIGH",
          detail: "HS 901380 on EU Annex I, category 6A002 (imaging sensors).",
          floor: 80,
          source_entity_ids: [],
        },
        {
          code: "SHIPPER_THIN_HISTORY",
          severity: "MEDIUM",
          detail: "4 prior movements; below the 10-movement confidence floor.",
          floor: 40,
          source_entity_ids: [],
        },
      ],
    },
    {
      ref: "KES-DU-0079",
      shipment: "KS-2026-119077",
      outcome: "PENDING_HUMAN",
      effective: 70,
      floor: 70,
      modelRisk: 70,
      minutesAgo: 73,
      agents: ["fraud_detection", "compliance_screening", "zero_day"],
      usage: {
        input_tokens: 7100,
        output_tokens: 1310,
        estimated_cost_usd: 0.00228,
        agent_calls: 4,
        latency_ms: 9240,
      },
      reviewReason: "Awaiting a licensing officer on an export-control question.",
      findings: [
        {
          code: "ZERO_DAY_ADVERSE_MEDIA",
          severity: "HIGH",
          detail:
            "Receiver 'Seabright Instruments SA' named in export-control " +
            "reporting 3 weeks ago; no list entry exists.",
          floor: 70,
          source_entity_ids: [],
          evidence_urls: [
            "https://www.ft.com/content/demo-export-control-enforcement-review",
          ],
        },
      ],
    },
    {
      ref: "KES-DU-0083",
      shipment: "KS-2026-119102",
      outcome: "CLEARED",
      effective: 22,
      floor: 0,
      modelRisk: 22,
      minutesAgo: 110,
      usage: {
        input_tokens: 3320,
        output_tokens: 470,
        estimated_cost_usd: 0.00093,
        agent_calls: 2,
        latency_ms: 2230,
      },
      findings: [],
    },
  ],
};

export function demoAudits(tenantId: string): ComplianceAuditResponse[] {
  const seeds = SEEDS[tenantId] ?? [];
  return seeds.map((seed, i) => build(tenantId, i, seed));
}

export function demoUsage(tenantId: string): TenantUsageResponse {
  const audits = demoAudits(tenantId);
  const agentCalls = sum(audits.map((a) => a.usage.agent_calls));
  const cost = audits.reduce((acc, a) => acc + a.usage.estimated_cost_usd, 0);
  const latencies = audits
    .map((a) => a.usage.latency_ms)
    .filter((x): x is number => typeof x === "number");

  const cleared = audits.filter((a) => a.outcome === "CLEARED");
  // An audit with no agent calls was settled by the deterministic rules alone,
  // which is the pair of numbers that decides what an account costs to serve.
  const byRules = cleared.filter((a) => a.usage.agent_calls === 0).length;

  return {
    tenant_id: tenantId,
    agent_calls: agentCalls,
    input_tokens: sum(audits.map((a) => a.usage.input_tokens)),
    output_tokens: sum(audits.map((a) => a.usage.output_tokens)),
    estimated_cost_usd: round(cost, 8),
    cost_per_call_usd: agentCalls > 0 ? round(cost / agentCalls, 8) : 0,
    auto_cleared: cleared.length,
    cleared_by_rules: byRules,
    cleared_by_ai: cleared.length - byRules,
    avg_latency_ms:
      latencies.length > 0 ? round(sum(latencies) / latencies.length, 1) : 0,
  };
}

function sum(xs: number[]): number {
  return xs.reduce((a, b) => a + b, 0);
}

function round(x: number, places: number): number {
  const f = 10 ** places;
  return Math.round(x * f) / f;
}
