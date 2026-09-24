/**
 * What Help mode says.
 *
 * Every entry is derived from the backend that actually implements the behaviour
 * -- the check functions and thresholds in `verifier.py`, the state tuples in
 * `orchestrator.py` -- rather than written from an idea of what the console
 * probably does. Help that describes behaviour the code does not have is worse
 * than no help: it is the one text on screen a reader has no way to verify, so it
 * gets believed.
 *
 * Numbers quoted here (500 USD/kg, 70% of the lane baseline, 100 USD) are the
 * live defaults. They are tenant-configurable through the Governance screen, so
 * the wording says "by default" wherever a rule can be re-tuned.
 *
 * Kept as plain data, separate from the components, so the copy can be reviewed
 * as prose without reading JSX.
 */

export type HelpEntry = {
  title: string;
  body: string;
  /** Optional second paragraph, for the "and why it is done that way" part. */
  note?: string;
};

// ---------------------------------------------------------------------------
// Screens, keyed by route. Extends the one-line `blurb` already on NAV_ITEMS.
// ---------------------------------------------------------------------------

export const NAV_HELP: Record<string, HelpEntry> = {
  "/": {
    title: "Pipeline",
    body:
      "The live board. Each card is one shipment moving through the workflow, and each column is the stage it has reached. Cards advance on their own; the ones that stop in an awaiting column are the ones needing a person.",
    note:
      "Columns fold several internal states together. Cleared holds shipments released automatically and shipments a reviewer released, because both mean cleared to ship.",
  },
  "/radar": {
    title: "Radar",
    body:
      "Completed audits, newest first, with the risk verdict and what drove it. Use this to look back at decisions; use Pipeline to watch work in progress.",
  },
  "/review": {
    title: "Review queue",
    body:
      "Only the cases waiting on a human decision. Each one shows the findings, the paperwork the decision was made from, and the outcome the agent proposed but did not execute.",
    note:
      "A decision here is recorded against your name and writes two audit entries. It cannot be undone from this console.",
  },
  "/audit": {
    title: "Audit trail",
    body:
      "Every action the system took or was refused, in order, with its outcome. Records here are immutable once written -- they can be read and filtered but never edited or deleted.",
  },
  "/governance": {
    title: "Governance",
    body:
      "The rules the agent operates under: what it may execute on its own, and the pre-filter lists that decide what gets fast-tracked or stopped before any model runs.",
    note:
      "Changes can be simulated against recent cases before publishing, so you can see what a new boundary would have changed without writing anything.",
  },
  "/devops": {
    title: "Operations",
    body:
      "Submit a shipment or upload a document to watch it run end to end, and inspect the health of the worker and the model layer.",
  },
  "/agents": {
    title: "Agents",
    body:
      "Which model answered which question, how many tokens it used, and what it cost. Also the prompt-injection screen that every uploaded document passes through.",
  },
};

// ---------------------------------------------------------------------------
// Case states
// ---------------------------------------------------------------------------

export const STATE_HELP: Record<string, HelpEntry> = {
  INGESTED: {
    title: "Queued",
    body:
      "Accepted and waiting for the first pass. The deterministic checks -- freight, value density, HS code, counterparty lists -- run here, before any model is called.",
  },
  SPECIALISTS_DONE: {
    title: "Fraud and compliance done",
    body:
      "The fraud and compliance agents have both answered. If either raised something serious the case goes on to a full investigation rather than clearing.",
  },
  INVESTIGATED: {
    title: "Investigated",
    body:
      "The investigation agent has written its assessment and the case is about to be routed to an outcome.",
  },
  AUTO_CLEARED: {
    title: "Cleared automatically",
    body:
      "Low risk, compliance clear, and inside the authority the agent has been delegated. No person was required.",
    note:
      "Cases cleared by the pre-filter alone never reach a model, which is why some cleared cases show no token cost at all.",
  },
  HELD_FOR_REVIEW: {
    title: "Held for review",
    body:
      "Middling risk with nothing disqualifying. An analyst is assigned, but this is a queue rather than an alarm.",
  },
  ESCALATED: {
    title: "Escalated",
    body:
      "Either compliance refused it or the risk score cleared the investigation bar. The proposed outcome was not executed and the case is waiting on a person.",
  },
  PENDING_HUMAN: {
    title: "Awaiting a person",
    body:
      "Nothing leaves this state without a named reviewer making a decision. The agent has finished its work and stopped.",
  },
  RELEASED_BY_HUMAN: {
    title: "Released by a reviewer",
    body:
      "A named reviewer cleared this shipment to ship, and their name and reason are on the audit trail.",
  },
  BLOCKED_BY_HUMAN: {
    title: "Blocked by a reviewer",
    body:
      "A named reviewer refused the shipment. There is no automatic block: this outcome only ever comes from a person.",
  },
  DEAD_LETTER: {
    title: "Abandoned after retries",
    body:
      "The workflow failed repeatedly and gave up rather than looping. This is work for a person, and the last error is recorded on the case.",
  },
};

// ---------------------------------------------------------------------------
// Severities
// ---------------------------------------------------------------------------

export const SEVERITY_HELP: Record<string, HelpEntry> = {
  CRITICAL: {
    title: "Critical",
    body:
      "On its own, enough to stop the shipment. A single critical finding sets the risk score at or near the top of the scale regardless of what else is clean.",
  },
  HIGH: {
    title: "High",
    body:
      "Pushes the case past the investigation bar on its own, so it will not clear automatically.",
  },
  MEDIUM: {
    title: "Medium",
    body:
      "Raises the floor into the review band. One of these queues the case for a person; several together escalate it.",
  },
  LOW: {
    title: "Low",
    body: "Recorded and shown, but does not raise the risk floor by itself.",
  },
  INFO: {
    title: "Informational",
    body:
      "Context rather than a concern -- most often a note that a check was skipped or could not run.",
  },
  CLEAR: {
    title: "Clear",
    body:
      "A positive signal, such as a match against the trusted-counterparty list. These can allow a case to skip the models entirely.",
  },
};

// ---------------------------------------------------------------------------
// Findings. Wording and thresholds taken from the matching check in verifier.py.
// ---------------------------------------------------------------------------

export const FINDING_HELP: Record<string, HelpEntry> = {
  SANCTIONS_MATCH: {
    title: "Sanctions match",
    body:
      "A counterparty on this shipment matches an entry in the sanctions index. Treated as disqualifying on its own.",
  },
  SANCTIONS_SCREENING_UNAVAILABLE: {
    title: "Sanctions screening unavailable",
    body:
      "The screening step could not complete, so nothing was checked against the index.",
    note:
      "Recorded as a concern rather than ignored. The absence of a finding from a check that did not run is not a clearance.",
  },
  BLACKLIST_MATCH: {
    title: "Blacklist match",
    body:
      "The company name appears on this tenant's internal blacklist, maintained on the Governance screen. Stops the case before any model runs.",
  },
  BLACKLIST_TAX_ID: {
    title: "Blacklisted tax ID",
    body:
      "The tax ID appears on the internal blacklist even though the company name does not. Catches a blocked counterparty trading under a new name.",
  },
  WHITELIST_MATCH: {
    title: "Trusted counterparty",
    body:
      "The shipper matches the trusted-counterparty register, so the case can be cleared without calling a model.",
    note:
      "The fast path is withdrawn if anything else on the record is seriously adverse, so naming a trusted company does not buy a free pass.",
  },
  WHITELIST_IDENTITY_MISMATCH: {
    title: "Trusted identity mismatch",
    body:
      "The company and the tax ID each match a trusted entry, but not the same one. A half-correct identity claim is treated as worse than an unknown counterparty, not better.",
  },
  SHIPPER_IDENTITY_MISMATCH: {
    title: "Shipper identity mismatch",
    body:
      "The tax ID on the paperwork is one we hold, but under a different company name -- the cheapest way to try to inherit another counterparty's good history.",
  },
  SHIPPER_NO_HISTORY: {
    title: "No shipping history",
    body: "This counterparty has no prior shipments on file.",
  },
  SHIPPER_THIN_HISTORY: {
    title: "Thin shipping history",
    body:
      "Only a handful of prior shipments, which is not enough of a pattern for an anomaly to stand out against.",
  },
  SHIPPER_HISTORY_UNVERIFIED: {
    title: "History unverified",
    body:
      "No transaction history was available from internal records, and it cannot be taken from the document.",
    note:
      "A document is not allowed to assert its own shipper's history, because a forged one would simply claim a long record.",
  },
  RECENTLY_REGISTERED_SHIPPER: {
    title: "Recently registered shipper",
    body:
      "The counterparty was registered very recently. Common in shell-company patterns, where a new entity is created for a single consignment.",
  },
  HIGH_RISK_DESTINATION: {
    title: "High-risk destination",
    body:
      "The destination country is on the restricted list: Afghanistan, Belarus, Cuba, Iran, Myanmar, North Korea, Pakistan, Russia, Sudan, Syria or Venezuela.",
  },
  MULTIPLE_DIVERSION_HUBS: {
    title: "Multiple transhipment hubs",
    body:
      "The routing passes through more than one known diversion hub -- Busan, Dubai, Hong Kong, Jebel Ali, Kaohsiung, Port Klang, Singapore or the UAE. Each is a legitimate port; stacking several is how a shipment's real destination gets obscured.",
  },
  ROUTE_CHANGED_AFTER_BOOKING: {
    title: "Route changed after booking",
    body:
      "The routing was amended after the booking was made, which is how a consignment reaches a destination it was not approved for.",
  },
  DUAL_USE_HS_CODE: {
    title: "Dual-use HS code",
    body:
      "The declared heading falls in a category with both civilian and military application, so it may need an export licence regardless of the stated use.",
  },
  HS_CODE_MALFORMED: {
    title: "Malformed HS code",
    body:
      "The declared code is not a valid Harmonized System heading, so nothing downstream can classify the goods from it.",
  },
  HS_DESCRIPTION_MISMATCH_DUAL_USE: {
    title: "Description does not match a dual-use heading",
    body:
      "The goods described and the heading declared disagree, and the correct heading appears to be a controlled one. The most serious form of misdeclaration.",
  },
  HS_DESCRIPTION_MISMATCH_LOW_CONFIDENCE: {
    title: "Possible description mismatch",
    body:
      "The classifier thinks the description and the declared heading disagree, but is not confident. Recorded without raising the risk floor on its own.",
  },
  HS_DESCRIPTION_CHECK_UNAVAILABLE: {
    title: "Classification check unavailable",
    body:
      "The description-to-heading check could not run, so the declared code was accepted as given.",
  },
  FREIGHT_MISSING: {
    title: "No freight charge",
    body:
      "No shipping cost was stated, so the pricing cannot be validated at all. Treated as a data-quality problem rather than a pricing one, and it applies at any shipment size.",
  },
  FREIGHT_ANOMALY: {
    title: "Freight out of line",
    body:
      "The freight charge is far from the baseline for this lane. Below 70% is a concern, below 50% is serious, and below 25% is treated as critical; more than three times the baseline is also flagged, as over-invoicing is its own way of moving value.",
    note:
      "Skipped entirely below the low-value threshold. A parcel is not an underpriced container, and applying the lane baseline to one made the low-value fast path unreachable.",
  },
  VALUE_DENSITY_HIGH: {
    title: "Value per kilogram too high",
    body:
      "Above 500 USD/kg by default, which is consistent with high-value or controlled goods rather than the general cargo declared.",
  },
  VALUE_DENSITY_LOW: {
    title: "Value per kilogram too low",
    body:
      "Below 1 USD/kg by default -- a classic under-invoicing pattern, where duty is paid on a fraction of the real value.",
  },
  LOW_VALUE_DOMESTIC: {
    title: "Low-value domestic shipment",
    body:
      "Under 100 USD by default, on a known domestic route, with no dual-use heading. Cleared by arithmetic without calling a model.",
  },
  ZERO_DAY_ADVERSE_MEDIA: {
    title: "Adverse media found",
    body:
      "A live search found recent reporting against this counterparty that no static sanctions list would yet carry.",
  },
  ZERO_DAY_ADVERSE_MEDIA_LOW_CONFIDENCE: {
    title: "Possible adverse media",
    body:
      "Something was found but the match to this counterparty is weak. Shown for context without raising the risk floor.",
  },
  ZERO_DAY_CHECK_UNAVAILABLE: {
    title: "Adverse-media check unavailable",
    body: "The search provider could not be reached, so no live check was made.",
  },
  ZERO_DAY_SEARCH_DID_NOT_RUN: {
    title: "Adverse-media search did not run",
    body:
      "The case qualified for a live search but none was performed, so this counterparty has not been checked against current reporting.",
  },
  EXPOSURE_CLAIM_UNSUPPORTED: {
    title: "Exposure figure unsupported",
    body:
      "The investigation quoted a financial exposure that the record does not support. Recorded so a number nobody can source does not end up in a filing.",
  },
};

// ---------------------------------------------------------------------------
// Reviewer actions
// ---------------------------------------------------------------------------

export const REVIEWER_ACTION_HELP: Record<string, HelpEntry> = {
  release: {
    title: "Release",
    body:
      "Clears the shipment to ship. Your name and note go on the case, and any drafted SAR on it is marked as signed off.",
    note: "Recorded immediately and cannot be undone from this console.",
  },
  block: {
    title: "Block",
    body:
      "Refuses the shipment. A note is required: a refusal nobody has to justify is not a control.",
    note: "Recorded immediately and cannot be undone from this console.",
  },
  request_info: {
    title: "Request information",
    body:
      "Leaves the case open and records what is missing. Use this rather than blocking when the paperwork is incomplete rather than wrong. A note is required.",
  },
};

// ---------------------------------------------------------------------------
// KPI tiles and panels, keyed by a stable id passed at the call site.
// ---------------------------------------------------------------------------

export const PANEL_HELP: Record<string, HelpEntry> = {
  // Pipeline KPIs
  "kpi.in-flight": {
    title: "In flight",
    body:
      "Cases the worker will pick up on its next pass: queued, fraud and compliance done, and investigated. A number that stays still while work is arriving means the worker is not running.",
  },
  "kpi.awaiting-human": {
    title: "Awaiting human",
    body:
      "Cases stopped on a person: awaiting a person, held for review, and escalated. Nothing leaves these states without a named reviewer.",
  },
  "kpi.agent-calls": {
    title: "Agent calls",
    body:
      "Model invocations across every case in the collection, counted exactly rather than over the fetched window.",
  },
  "kpi.spend": {
    title: "Spend",
    body:
      "Estimated from token counts and per-model pricing. Cases the pre-filter cleared contribute nothing, which is the point of having a pre-filter.",
  },
  "kpi.delegated-authority": {
    title: "Delegated authority",
    body:
      "Whether the agent may execute protected actions on its own. With no published boundary it is suspended, every outcome stays a proposal, and each case lands on a human.",
    note:
      "That is correct fail-closed behaviour, not a fault -- but it explains a board where nothing ever clears.",
  },

  // Board
  "board.columns": {
    title: "The board",
    body:
      "One card per shipment, in the column for the stage it has reached. Click a card for the full trace: every agent hop, every action, and every finding.",
    note:
      "Columns group several internal states. Awaiting a person also holds held-for-review, escalated and abandoned cases; Cleared holds both automatic and reviewer releases.",
  },

  // Agents screen
  "agents.cost-by-agent": {
    title: "Cost by agent",
    body:
      "One row per agent, ordered by spend. The dollar figure is summed from each call's own rate rather than from these token totals, because the rate depends on which model ran the step: Nano on fraud and compliance, Super on investigation, Ultra on the debate. Calls is how many times that agent was invoked; the two token figures are input then output. Windowed over the cases currently on the board, not the whole collection.",
    note:
      "Ordered by money rather than by tokens on purpose — Ultra costs roughly 13x Nano per call, so the most expensive agent is usually not the one that produced the most tokens. The headline totals on the Pipeline board are exact. A per-agent breakdown across every case would need a stored field per agent per case.",
  },
  "agents.injection-probe": {
    title: "Prompt-injection screen",
    body:
      "Runs text through the same two-stage defence every uploaded document passes: a pattern screen in code, then Model Armor. These are the exact functions the document pipeline calls, not a demonstration of them.",
  },
  "agents.worker": {
    title: "Worker",
    body:
      "The process that advances cases. On-demand mode runs the whole workflow inside the request that submitted it, which is what makes scale-to-zero viable; a stopped worker in polling mode means cases will sit in flight.",
  },
  "agents.models": {
    title: "Models",
    body:
      "Which model answers which question, and what each costs per million tokens. Document reading needs vision, so it uses a different model from the reasoning steps.",
  },

  // Review screen
  "review.queue": {
    title: "Queue",
    body:
      "Cases waiting on a decision, oldest first. The count here should match the Awaiting human tile on the Pipeline board.",
  },
  "review.findings": {
    title: "Findings",
    body:
      "What the checks found, each with the minimum risk score that finding justifies on its own -- its floor. The case's score is at least the highest floor present.",
  },
  "review.paperwork": {
    title: "Paperwork",
    body:
      "The bill of lading the decision is being made from. For a submitted shipment this is rendered from the record; for an upload it is the file as received.",
  },
  "review.decision": {
    title: "Decision",
    body:
      "Release, block, or ask for more information. A reviewer name is always required, and a note is required for anything other than a plain release.",
  },

  // Audit screen
  "audit.trail": {
    title: "Audit trail",
    body:
      "Every action attempted, with its outcome and the reason it was refused where it was. Filters are exact-match on one indexed field at a time.",
    note:
      "Rows are immutable once written. The store refuses an update or a delete on an audit record, so this trail cannot be tidied after the fact.",
  },

  // Governance screen
  "governance.boundary": {
    title: "Delegation boundary",
    body:
      "The list of actions the agent may execute without a person. Anything outside it stays a proposal, and the refusal is recorded against the case.",
  },
  "governance.simulate": {
    title: "Simulate",
    body:
      "Replays a candidate boundary against recent cases and reports what would change. Nothing is written and no action runs.",
  },
  "governance.history": {
    title: "History",
    body:
      "Every boundary ever published, including superseded and revoked versions, because \u201cwhat was the agent allowed to do in March\u201d is a question an auditor asks.",
  },
  "governance.prefilter": {
    title: "Pre-filter rules",
    body:
      "The trusted-counterparty register, the blacklists, the safe domestic routes and the low-value threshold. These decide what is cleared or stopped by arithmetic, before any model is called.",
    note:
      "Held per tenant. They used to be module globals, which meant one tenant's blacklist edit changed what every tenant was screened against.",
  },

  // Operations screen
  "devops.scripted-batch": {
    title: "Scripted batch",
    // Three cases, not four branches. This said "a sanctions hit, an export-control name,
    // an HS mismatch and a clean low-value parcel" -- `simulator.scripted_shipments`
    // returns CLEAN, MID and DIRTY, there is no HS-mismatch case, and the clean one sails
    // internationally for USD 9,600. Kept in step with the panel note in app/devops/page.tsx.
    body:
      "Three shipments, one per outcome, so a single click shows all three ways the pipeline can end: cleared by the agents, held for a human, escalated. Cotton garments to Singapore from a shipper with 412 prior shipments and a tax ID on file. Furniture to Busan whose paperwork is clean but whose freight sits under the route average, from a shipper with nine shipments behind it. And frequency converters to Karachi declared as agricultural end use, from a company registered eleven days ago with no tax ID, booked at 14% of the route's normal freight with two transhipments added after booking.",
    note:
      "Fixed rather than random on purpose, so two runs are comparable. Re-running it does not create duplicates -- a case id derives from the shipment, so the same shipment reuses its case.",
  },
  "devops.bulk-load": {
    title: "Bulk load",
    body:
      "Randomised shipments, for watching the board under load and seeing the real cost per case at volume.",
    note:
      "Every shipment that reaches an agent spends tokens. This is the one control on this screen that can run up a bill.",
  },
  "devops.submit": {
    title: "Submit one by hand",
    body:
      "Posts a single shipment and runs it end to end, exactly as an integration would. Useful for reproducing one specific finding.",
    note:
      "Blank fields are omitted rather than sent empty, because an absent field and an empty one produce different findings.",
  },
  "devops.upload": {
    title: "Upload a document",
    body:
      "Accepts a PDF or an image (.png, .jpg, .jpeg, .webp). The file passes the injection screen and Model Armor before any model reads it, then goes through extraction and the full workflow.",
    note:
      "Only the first page of a PDF is read today. If a document has more, the case records that the remaining pages were not examined rather than implying they were clean.",
  },
  "devops.health": {
    title: "Health",
    body:
      "Whether the state store and the worker are reachable, and which models are configured. If the store fell back to memory, this says so -- cases will not survive a restart.",
  },

  // Radar screen
  "radar.audits": {
    title: "Completed audits",
    body:
      "Finished verdicts, newest first. The badge shows the risk state; hover or open a row for what drove it.",
  },
};

// ---------------------------------------------------------------------------

/**
 * Every topic in one lookup, so a call site passes a single id.
 *
 * Prefixed namespaces rather than one flat object: a finding code and a panel id
 * could otherwise collide, and the collision would silently show the wrong
 * explanation, which is the failure mode this feature can least afford.
 */
export function helpFor(id: string): HelpEntry | undefined {
  if (id.startsWith("state:")) return STATE_HELP[id.slice(6)];
  if (id.startsWith("finding:")) return FINDING_HELP[id.slice(8)];
  if (id.startsWith("severity:")) return SEVERITY_HELP[id.slice(9)];
  if (id.startsWith("action:")) return REVIEWER_ACTION_HELP[id.slice(7)];
  if (id.startsWith("nav:")) return NAV_HELP[id.slice(4)];
  return PANEL_HELP[id];
}
