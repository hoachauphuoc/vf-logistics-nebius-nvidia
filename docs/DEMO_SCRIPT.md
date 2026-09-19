# VF Logistics Demo Video Script (3:00)

## Recording Setup
- **Tool**: OBS Studio
- **Resolution**: 1920x1080 (1080p)
- **Browser**: Chrome/Edge at 100% zoom
- **URL**: https://vf-logistics-f7rcctz26a-as.a.run.app

---

## Scene 1: Problem Statement (0:00 - 0:15)

**Screen**: Title slide (can be a simple HTML page or PowerPoint)

> Vietnamese logistics operators lose millions annually to trade fraud --
> under-invoicing, shell companies, sanctions evasion -- that simple rules
> engines miss. AI models can detect patterns, but who controls the AI?

**Key visual**: Statistics overlay (e.g., "$X billion in trade fraud annually")

---

## Scene 2: Dashboard First Impression (0:15 - 0:30)

**Screen**: Open VF Logistics dashboard. Show skeleton loading, then KPIs appear.

**Action**: Refresh the page to show skeleton animation -> data loads.

> VF Logistics uses three NVIDIA Nemotron models on Nebius Token Factory.
> Nano for fast screening, Super for deep investigation and debate.
> The dashboard shows real-time KPIs with trend indicators.

**Key visual**: SVG shield logo, sparklines updating, professional dark UI

---

## Scene 3: Inject Shipments (0:30 - 0:50)

**Screen**: Click DevOps -> "Inject 5 scripted"

**Action**: Watch the pipeline board fill up. KPIs update live.

> Every shipment enters the pipeline. Deterministic rules clear 70% with
> zero AI cost. The rest go to Nemotron Nano for fraud detection and
> compliance screening -- in parallel, under 2 seconds each.

**Key visual**: Board cards sliding in with risk gauges, relative timestamps

---

## Scene 4: Case Trace with Tavily (0:50 - 1:10)

**Screen**: Click a case card to open the trace view.

**Action**: Show each step: validation -> fraud detection -> compliance -> investigation

> The compliance agent searches Tavily for live sanctions data before every
> screening. The investigation agent searches for the specific fraud pattern
> and cross-references counterparties. Five Tavily integration points total.

**Key visual**: Step-by-step trace showing Tavily results, token counts

---

## Scene 5: Multi-Agent Debate (1:10 - 1:30)

**Screen**: Find a HELD_FOR_REVIEW case. Click "Deep Review".

**Action**: Watch Super challenge Nano's assessment.

> Nemotron Super reviews Nano's fraud assessment using function calling.
> It can re-run the analysis, search the web via Tavily, and override the
> score. This is a real multi-agent debate, not scripted.

**Key visual**: Debate result card showing Super's verdict vs Nano's original

---

## Scene 6: Governance Kill Switch (1:30 - 1:50)

**Screen**: Go to Governance page.

**Action**: Show the active boundary. Click "Kill Switch" in DevOps.

> Remove the delegation boundary and the agent stops immediately.
> All protected actions are DENIED. Cases accumulate as pending.
> Republish the boundary and processing resumes. Fail-closed by design.

**Key visual**: Agent state changing from READY to SUSPENDED, red alert banner

---

## Scene 7: Prompt Injection Demo (1:50 - 2:10)

**Screen**: Click "Prompt Injection" demo button in DevOps.

**Action**: Watch the injected shipment get flagged.

> We inject a shipment with prompt injection in the cargo description --
> "ignore all previous instructions." Model Armor blocks it before any
> model sees the payload. The injection is logged in the audit trail.

**Key visual**: Red alert showing blocked injection, audit trail entry

---

## Scene 8: Cost Dashboard (2:10 - 2:30)

**Screen**: Show DevOps cost monitor section.

**Action**: Point to the real-time cost breakdown.

> Token Factory spend updates in real-time. Nano costs $0.06 per million
> input tokens. Rules saved $X in AI costs by clearing clean shipments
> deterministically. The bar chart shows cost per agent.

**Key visual**: Cost KPIs, rules savings metric, agent cost breakdown bars

---

## Scene 9: Floor Override Demo (2:30 - 2:45)

**Screen**: Click "Floor Override" demo button.

**Action**: Watch the case get the deterministic floor applied.

> We inject a shipment to Iran with nuclear HS code 8401.10. Even if the
> AI says risk is 20, the deterministic floor is 85. The floor always wins.
> Score disputed triggers an automatic multi-agent debate.

**Key visual**: Risk gauge showing 85, "score_disputed" flag, auto-debate step

---

## Scene 10: Summary (2:45 - 3:00)

**Screen**: Architecture diagram or summary slide.

> VF Logistics: autonomous fraud detection with governance that actually
> works. Built 100% on Nebius Token Factory with NVIDIA Nemotron Nano,
> Super, and MiniCPM-V. Five Tavily integrations. 197 automated tests.
> The AI cannot act without human authorization. Ever.

**Key visual**: Architecture diagram, prize targets, repo + demo URLs

---

## Post-Recording Checklist
- [ ] Video is exactly 3:00 or under
- [ ] Upload to YouTube as Public
- [ ] Copy URL to SUBMISSION.md
- [ ] Submit on Devpost
