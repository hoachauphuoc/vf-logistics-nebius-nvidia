import { chromium } from "playwright-core";
import fs from "node:fs";
const E = process.env, BASE = E.BASE ?? "https://vf-app-350828852747.asia-southeast1.run.app";
const RUN = E.RUN_TAG ?? String(Date.now()).slice(-6), OUT = E.OUT ?? "results", SLOW = +(E.SLOW_MS ?? 60000);
const IDS = (E.CASE_IDS ?? `REV2-E2E-A-${RUN},REV2-E2E-B-${RUN}`).split(","), SKIP = E.SKIP_SEED === "1";
if (!E.E2E_REVIEWER_PASSWORD || (!SKIP && !E.E2E_JUDGE_PASSWORD)) { console.error("Set E2E_REVIEWER_PASSWORD and E2E_JUDGE_PASSWORD"); process.exit(2); }
fs.mkdirSync(OUT, { recursive: true });
const res = [], finds = [];
const ck = (n, ok, x = "") => { res.push({ name: n, ok, extra: x }); console.log(`${ok ? "PASS" : "FAIL"}  ${n} ${x}`); };
const SHIP = (id) => ({ shipment_id: id, shipper_name: "Saigon Plywood Co., Ltd.", shipper_company: "Saigon Plywood Co., Ltd.", shipper_tax_id: "VN0300999001", shipper_country: "Vietnam", receiver_name: "US Hardwood Imports LLC", receiver_company: "US Hardwood Imports LLC", receiver_country: "United States", origin: "Hai Phong Port, Vietnam", destination: "Long Beach, United States", hs_code: "4412.33", cargo_description: "Hardwood plywood, 18 mm, declared Vietnam origin", declared_value: 28000.0, weight_kg: 22000.0, currency: "USD", shipping_cost: 3200.0, transport_mode: "sea", route_details: "Hai Phong to Long Beach via direct sea freight", shipper_tx_count: 35 });
const br = await chromium.launch({ executablePath: E.CHROME_PATH || (fs.existsSync("/opt/pw-browsers/chromium") ? "/opt/pw-browsers/chromium" : undefined) });
const login = async (email, pw) => {
  const ctx = await br.newContext({ viewport: { width: 1400, height: 1000 } }), p = await ctx.newPage();
  await p.goto(`${BASE}/login?next=/today`); await p.fill("#email", email); await p.fill("#password", pw);
  await p.getByRole("button", { name: /sign in/i }).last().click();
  await p.waitForURL((u) => u.pathname === "/today", { timeout: 90000 });
  return { ctx, p };
};
if (!SKIP) {
  const { ctx, p } = await login(E.JUDGE_EMAIL ?? "judge@vf-logistics.demo", E.E2E_JUDGE_PASSWORD);
  for (const id of IDS) {
    const r = await p.request.post(`${BASE}/api/proxy/events/shipment`, { data: SHIP(id), timeout: 300000 }), b = await r.json().catch(() => ({}));
    ck(`seed ${id}`, r.ok(), `HTTP ${r.status()} state=${b.state} risk=${b.risk_score}`);
  }
  await ctx.close();
}
const { p: page } = await login(E.REVIEWER_EMAIL ?? "reviewer@vf-logistics.demo", E.E2E_REVIEWER_PASSWORD);
const writes = [];
page.on("response", (r) => { const m = r.request().method(); if (r.url().includes("/api/proxy/") && m !== "GET") writes.push(`${m} ${r.url().replace(BASE + "/api/proxy/", "")} -> ${r.status()}`); });
const caseOf = async (id) => { const b = await (await page.request.get(`${BASE}/api/proxy/orchestrator/case/${id}`)).json(); return b.case ?? b; };
const open = async (id) => { await page.goto(`${BASE}/cases/${id}`); await page.waitForSelector("#note", { timeout: 120000 }); };
const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png`, fullPage: true });
const wait = async (ms, f) => { const t = Date.now(); while (Date.now() - t < ms) { await page.waitForTimeout(2000); if (f()) return; } };
const HELD = ["HELD_FOR_REVIEW", "PENDING_HUMAN", "ESCALATED"];

async function run(id, t, d) {
  console.log(`\n=== ${id} ===`);
  const c0 = await caseOf(id), held = HELD.includes(c0.state) && (c0.validation?.findings ?? []).some((f) => f.code === "ORIGIN_INPUTS_UNVERIFIED");
  ck(`${t}: held for a person with ORIGIN_INPUTS_UNVERIFIED`, held, c0.state);
  if (!held) return finds.push(`${id}: not held for review (${c0.state}); stopped.`);
  await open(id); await page.fill("#note", "Need the origin papers for the plywood inputs"); writes.length = 0;
  await page.getByRole("button", { name: "Request info" }).click(); await page.waitForTimeout(1000);
  ck(`${t}: nothing sent before Confirm`, writes.length === 0, JSON.stringify(writes)); await shot(`${t}-1-confirm`);
  await page.getByRole("button", { name: "Confirm" }).click();
  const bn = page.getByTestId("evidence-links"), shown = await bn.waitFor({ timeout: 30000 }).then(() => true, () => false);
  ck(`${t}: request-evidence 201, not decide`, writes.some((w) => /request-evidence -> 201/.test(w)) && !writes.some((w) => w.includes("/decide")), JSON.stringify(writes));
  ck(`${t}: links shown to reviewer`, shown); await shot(`${t}-2-links`);
  const links = Object.fromEntries([...(shown ? await bn.innerText() : "").matchAll(/(\w+): (\/respond\/\S+)/g)].map((m) => [m[1], m[2]]));
  ck(`${t}: three links`, Object.keys(links).length === 3, Object.keys(links).join(","));
  ck(`${t}: AWAITING_EVIDENCE`, (await caseOf(id)).state === "AWAITING_EVIDENCE");
  const sh = await br.newContext({ viewport: { width: 900, height: 900 } }), sp = await sh.newPage(), order = Object.keys(links).reverse();
  const up = async (dt) => { await sp.goto(`${BASE}${links[dt]}`); await sp.setInputFiles('input[type="file"]', `docs/${t}-${dt}.pdf`); await sp.getByRole("button", { name: /^Upload/ }).click(); };
  for (const [i, dt] of order.entries()) {
    await up(dt); await sp.getByText(/Document received|flagged|failed|invalid|already|not_authenticated/i).first().waitFor({ timeout: SLOW * 3 });
    const m = await sp.locator("body").innerText();
    ck(`${t}: shipper (no login) uploads ${dt}`, /Document received/.test(m), (m.match(/Document received[^\n]*|Upload failed[^\n]*|not_authenticated|[^\n]*invalid[^\n]*/) ?? [""])[0]);
    if (!i) await sp.screenshot({ path: `${OUT}/${t}-3-shipper.png` });
  }
  await up(order[0]); await sp.waitForTimeout(5000);
  ck(`${t}: reused link refused`, !/Document received/.test(await sp.locator("body").innerText())); await sh.close();
  let c = await caseOf(id); const docs = c.verification?.documents ?? [];
  console.log("  MODEL EXTRACTED: " + JSON.stringify(docs.map((x) => ({ type: x.doc_type, extracted: x.extracted, model: x.extraction?.model, cost_usd: x.extraction?.cost_usd }))));
  ck(`${t}: 3 documents stored by type`, docs.map((x) => x.doc_type).sort().join() === "certificate_of_origin,input_purchase_invoices,producer_declaration");
  ck(`${t}: every document read by the model`, docs.length === 3 && docs.every((x) => x.extracted && Object.keys(x.extracted).length), docs.filter((x) => !x.extracted).map((x) => x.doc_type).join(","));
  await open(id); const re = page.getByRole("button", { name: "Re-evaluate" });
  ck(`${t}: Re-evaluate shown`, await re.isVisible()); writes.length = 0; await re.click();
  await wait(SLOW * 2, () => writes.some((w) => /reevaluate -> /.test(w)));
  ck(`${t}: Re-evaluate succeeds`, writes.some((w) => /reevaluate -> 200/.test(w)), JSON.stringify(writes));
  c = await caseOf(id); const ev = (c.verification?.evaluations ?? []).at(-1) ?? {};
  console.log(`  EVALUATION: status=${ev.status} unresolved=${JSON.stringify(ev.unresolved)} contradictions=${JSON.stringify((ev.contradictions ?? []).map((x) => x.kind))} state=${c.state}`);
  ck(`${t}: evaluation ${d.status}`, ev.status === d.status, `got ${ev.status}`); await shot(`${t}-5-reevaluated`);
  if (ev.status !== d.status) finds.push(`${id}: expected ${d.status}, model gave ${ev.status} (unresolved ${JSON.stringify(ev.unresolved)}).`);
  await open(id); await page.fill("#note", d.note); writes.length = 0;
  await page.getByRole("button", { name: d.button, exact: true }).click(); await page.waitForTimeout(1000);
  ck(`${t}: ${d.button} sends nothing before Confirm`, writes.length === 0, JSON.stringify(writes));
  await page.getByRole("button", { name: "Confirm" }).click();
  await wait(SLOW, () => writes.some((w) => /execute -> /.test(w) || /approve -> [45]/.test(w)));
  ck(`${t}: approve then execute`, writes.some((w) => /approve -> 200/.test(w)) && writes.some((w) => /execute -> 200/.test(w)), JSON.stringify(writes));
  c = await caseOf(id); const ex = (c.verification?.executions ?? []).at(-1) ?? {};
  ck(`${t}: final ${d.end}`, c.state === d.end, c.state);
  ck(`${t}: Pub/Sub message id`, ex.status === "sent" && !!ex.message_id, `${ex.status} ${ex.message_id}`);
  await page.reload(); await page.waitForTimeout(5000); await shot(`${t}-6-final`);
  console.log(`  cost=${c._estimated_cost_usd} latency_ms=${c._sum_latency_ms}`);
}
await run(IDS[0], "A", { button: "Release", note: "Papers agree: Vietnam origin throughout", end: "RELEASED_BY_HUMAN", status: "provided" });
await run(IDS[1], "B", { button: "Block", note: "Invoice shows China-origin veneer", end: "BLOCKED_BY_HUMAN", status: "contradicted" });
const bad = res.filter((r) => !r.ok);
fs.writeFileSync(`${OUT}/summary.json`, JSON.stringify({ base: BASE, run: RUN, cases: IDS, total: res.length, failed: bad.length, findings: finds, results: res }, null, 2));
console.log(`\n${res.length - bad.length}/${res.length} passed. Findings: ${finds.length ? "\n  - " + finds.join("\n  - ") : "none"}\nSaved ./${OUT}/summary.json`);
await br.close(); process.exitCode = bad.length ? 1 : 0;
