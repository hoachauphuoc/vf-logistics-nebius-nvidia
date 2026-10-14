const E = process.env, BASE = E.BASE ?? "https://vf-app-350828852747.asia-southeast1.run.app";
const [cmd, ...rest] = process.argv.slice(2);
// Cases are named CASE-<shipment id>; `seed` takes shipment ids, `show` takes either.
const caseId = (s) => (s.startsWith("CASE-") ? s : `CASE-${s}`);
const ids = cmd === "show" ? rest.map(caseId) : rest.map((s) => s.replace(/^CASE-/, ""));
const login = async (email, pw) => {
  const r = await fetch(`${BASE}/api/auth/login`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ email, password: pw }) });
  if (!r.ok) { console.log(`login ${email}: HTTP ${r.status}`); process.exitCode = 1; return null; }
  return (r.headers.getSetCookie?.() ?? []).map((c) => c.split(";")[0]).join("; ");
};
const SHIP = (id) => ({ shipment_id: id, shipper_name: "Saigon Plywood Co., Ltd.", shipper_company: "Saigon Plywood Co., Ltd.", shipper_tax_id: "VN0300999001", shipper_country: "Vietnam", receiver_name: "US Hardwood Imports LLC", receiver_company: "US Hardwood Imports LLC", receiver_country: "United States", origin: "Hai Phong Port, Vietnam", destination: "Long Beach, United States", hs_code: "4412.33", cargo_description: "Hardwood plywood, 18 mm, declared Vietnam origin", declared_value: 28000.0, weight_kg: 22000.0, currency: "USD", shipping_cost: 3200.0, transport_mode: "sea", route_details: "Hai Phong to Long Beach via direct sea freight", shipper_tx_count: 35 });
if (cmd === "seed") {
  const ck = await login(E.JUDGE_EMAIL ?? "judge@vf-logistics.demo", E.E2E_JUDGE_PASSWORD);
  if (ck) for (const id of ids) {
    const r = await fetch(`${BASE}/api/proxy/events/shipment`, { method: "POST", headers: { "content-type": "application/json", cookie: ck }, body: JSON.stringify(SHIP(id)) });
    const b = await r.json().catch(() => ({}));
    console.log(`seed ${id}: HTTP ${r.status} case=${b.case_id ?? caseId(id)} state=${b.state}`);
  }
} else if (cmd === "show") {
  const ck = await login(E.REVIEWER_EMAIL ?? "reviewer@vf-logistics.demo", E.E2E_REVIEWER_PASSWORD);
  if (ck) for (const id of ids) {
    const b = await (await fetch(`${BASE}/api/proxy/orchestrator/case/${id}`, { headers: { cookie: ck } })).json(), c = b.case ?? b, v = c.verification ?? {};
    console.log(`\n=== ${id} ===\nstate: ${c.state}   evidence_version: ${v.evidence_version}   cost: ${c._estimated_cost_usd}   model_latency_ms: ${c._sum_latency_ms}`);
    console.log("findings:", (c.validation?.findings ?? []).map((f) => f.code).join(", "));
    console.log("requests:", (v.requests ?? []).map((r) => `${r.status}[${(r.documents ?? []).join("+")}] received=${Object.keys(r.received_docs ?? {}).join("+")}`).join(" | "));
    for (const d of v.documents ?? []) console.log(`document ${d.doc_type}: model=${d.extraction?.model} cost=${d.extraction?.cost_usd} blocked=${d.blocked}\n   extracted=${JSON.stringify(d.extracted)}`);
    for (const e of v.evaluations ?? []) console.log(`evaluation v${e.evidence_version}: status=${e.status} unresolved=${JSON.stringify(e.unresolved)} contradictions=${JSON.stringify((e.contradictions ?? []).map((x) => x.kind))} floor=${e.risk_floor}`);
    for (const a of v.approvals ?? []) console.log(`approval ${a.action} by ${a.approver} (v${a.evidence_version}): ${a.status}${a.exception ? " EXCEPTION " + JSON.stringify(a.exception) : ""}`);
    for (const x of v.executions ?? []) console.log(`execution: ${x.status} message_id=${x.message_id ?? "-"} ${x.reason ?? ""}`);
  }
} else console.log("usage: node api.mjs seed <id> <id>   |   node api.mjs show <id> <id>");
