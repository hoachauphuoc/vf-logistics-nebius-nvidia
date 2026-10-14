// Negative paths of the verification loop, driven through the deployed console's API.
//
// run.mjs walks the happy path in a browser (38 checks). This covers what Rev2 asked for
// that the happy path cannot: a re-evaluate outside the loop, a forged or missing link,
// a one-click session at the password-only routes, and a partial set of documents. Every
// step is a request and a status, so it needs no browser.
//
//   CLOSED_CASES=CASE-REV2-E2E-A-123,CASE-REV2-E2E-B-123 node negative.mjs        # zero model spend
//   RUN_S1=1 node negative.mjs                                                    # adds S1, see below
//
// S2  re-evaluate a case that is already released/blocked -> 409 naming its state, case untouched;
//     an unknown id -> 404; no session -> 401.                                      (no model spend)
// S3  a forged, tampered or missing evidence link -> 403, nothing stored.            (no model spend)
// S4  a one-click guest session at approve and execute -> 403 required_auth=password. (no model spend;
//     skipped, and said so, when the one-click door is closed on the target.)
// S1  RUN_S1=1: seeds a case, requests 3 documents, uploads ONE (one model extraction), re-evaluates:
//     the request stays SENT, the evaluation is "missing" with the other two unresolved, approve is a
//     409 "open request"; cancel the request, then a release with no note is a 400. Nothing is executed,
//     so no Pub/Sub message. It leaves one case held for review on the target.
//
// Reads E2E_REVIEWER_PASSWORD (and E2E_JUDGE_PASSWORD for S1) from the environment; never prints them.
import fs from "node:fs";

const E = process.env, BASE = E.BASE ?? "https://vf-app-350828852747.asia-southeast1.run.app";
const RUN = E.RUN_TAG ?? String(Date.now()).slice(-6), OUT = E.OUT ?? "results";
const CLOSED = (E.CLOSED_CASES ?? "").split(",").map((s) => s.trim()).filter(Boolean).map((s) => (s.startsWith("CASE-") ? s : `CASE-${s}`));
if (!E.E2E_REVIEWER_PASSWORD || (E.RUN_S1 === "1" && !E.E2E_JUDGE_PASSWORD)) { console.error("Set E2E_REVIEWER_PASSWORD (and E2E_JUDGE_PASSWORD for RUN_S1=1)"); process.exit(2); }
fs.mkdirSync(OUT, { recursive: true });

const res = [], finds = [];
const ck = (n, ok, x = "") => { res.push({ name: n, ok, extra: x }); console.log(`${ok ? "PASS" : "FAIL"}  ${n} ${x}`); };
const skip = (n, why) => { res.push({ name: n, ok: true, skipped: true, extra: why }); console.log(`SKIP  ${n} (${why})`); };

const login = async (email, pw) => {
  const r = await fetch(`${BASE}/api/auth/login`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ email, password: pw }) });
  if (!r.ok) throw new Error(`login ${email}: HTTP ${r.status}`);
  return (r.headers.getSetCookie?.() ?? []).map((c) => c.split(";")[0]).join("; ");
};
const api = async (method, path, { cookie, body, headers } = {}) => {
  const r = await fetch(`${BASE}/api/${path}`, { method, headers: { ...(body && !(body instanceof FormData) ? { "content-type": "application/json" } : {}), ...(cookie ? { cookie } : {}), ...headers }, body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined });
  const text = await r.text(); let json = null; try { json = JSON.parse(text); } catch { /* not json */ }
  return { status: r.status, json, text: text.slice(0, 200) };
};
const getCase = async (cookie, id) => { const { json } = await api("GET", `proxy/orchestrator/case/${id}`, { cookie }); return json?.case ?? json ?? {}; };
const fingerprint = (c) => JSON.stringify({ state: c.state, v: c._version, evals: (c.verification?.evaluations ?? []).length, approvals: (c.verification?.approvals ?? []).length });
const pdf = () => { const f = ["docs/A-certificate_of_origin.pdf"].find((p) => fs.existsSync(p)); if (!f) throw new Error("run `node gen.mjs` first (docs/*.pdf)"); return fs.readFileSync(f); };
const upload = (token) => { const fd = new FormData(); fd.append("file", new Blob([pdf()], { type: "application/pdf" }), "cert.pdf"); return api("POST", "proxy/evidence/respond", { body: fd, headers: token == null ? {} : { "X-VF-Evidence-Token": token } }); };

const reviewer = await login(E.REVIEWER_EMAIL ?? "reviewer@vf-logistics.demo", E.E2E_REVIEWER_PASSWORD);

// ---- S2: re-evaluate outside the loop -------------------------------------------------
console.log("\n=== S2: re-evaluate outside the verification loop ===");
if (!CLOSED.length) skip("S2: re-evaluate a released/blocked case is refused", "set CLOSED_CASES to cases already released or blocked");
for (const id of CLOSED) {
  const before = await getCase(reviewer, id), r = await api("POST", `proxy/review/${id}/reevaluate`, { cookie: reviewer, body: {} }), after = await getCase(reviewer, id);
  ck(`S2: ${id} (${before.state}) re-evaluate is a 409 that names the state`, r.status === 409 && (r.json?.error ?? "").includes(before.state), `${r.status} ${r.text}`);
  ck(`S2: ${id} is untouched by the refused call`, fingerprint(before) === fingerprint(after), fingerprint(after));
}
{
  const r = await api("POST", `proxy/review/CASE-NOPE-${RUN}/reevaluate`, { cookie: reviewer, body: {} });
  ck("S2: an unknown case is a 404", r.status === 404, `${r.status} ${r.text}`);
  const anon = await api("POST", `proxy/review/CASE-NOPE-${RUN}/reevaluate`, { body: {} });
  ck("S2: no session is a 401, never a 404 or 200", anon.status === 401, `${anon.status} ${anon.text}`);
}

// ---- S3: links that are not ours ------------------------------------------------------
console.log("\n=== S3: forged and missing evidence links ===");
for (const [label, token] of [["forged", "forged.token"], ["no signature", "eyJ0IjoiZGVmYXVsdCJ9"], ["missing", null], ["empty", ""]]) {
  const r = await upload(token);
  ck(`S3: a ${label} link is a 403 and stores nothing`, r.status === 403 && !r.json?.received, `${r.status} ${r.text}`);
}

// ---- S4: one-click guest at the password-only routes ----------------------------------
console.log("\n=== S4: a one-click session at approve and execute ===");
{
  const door = await fetch(`${BASE}/api/auth/judge`, { method: "POST" });
  const cookie = door.status === 200 ? (door.headers.getSetCookie?.() ?? []).map((c) => c.split(";")[0]).join("; ") : null;
  if (!cookie) skip("S4: one-click session is refused at approve and execute", `one-click door is closed on this target (HTTP ${door.status})`);
  else for (const [path, body] of [["approve", { action: "release", note: "x" }], ["execute", { approval_id: "evapr-none" }]]) {
    const r = await api("POST", `proxy/review/CASE-NOPE-${RUN}/${path}`, { cookie, body });
    ck(`S4: one-click ${path} is a 403 asking for a password`, r.status === 403 && r.json?.required_auth === "password", `${r.status} ${r.text}`);
  }
}

// ---- S1: a partial set of documents ---------------------------------------------------
console.log("\n=== S1: one of three documents, then re-evaluate ===");
if (E.RUN_S1 !== "1") skip("S1: partial set of documents", "set RUN_S1=1 (one model extraction, leaves a held case)");
else {
  const judge = await login(E.JUDGE_EMAIL ?? "judge@vf-logistics.demo", E.E2E_JUDGE_PASSWORD);
  const shipment = { shipment_id: `REV2-E2E-C-${RUN}`, shipper_name: "Saigon Plywood Co., Ltd.", shipper_company: "Saigon Plywood Co., Ltd.", shipper_tax_id: "VN0300999001", shipper_country: "Vietnam", receiver_name: "US Hardwood Imports LLC", receiver_company: "US Hardwood Imports LLC", receiver_country: "United States", origin: "Hai Phong Port, Vietnam", destination: "Long Beach, United States", hs_code: "4412.33", cargo_description: "Hardwood plywood, 18 mm, declared Vietnam origin", declared_value: 28000.0, weight_kg: 22000.0, currency: "USD", shipping_cost: 3200.0, transport_mode: "sea", route_details: "Hai Phong to Long Beach via direct sea freight", shipper_tx_count: 35 };
  const seed = await api("POST", "proxy/events/shipment", { cookie: judge, body: shipment });
  const id = seed.json?.case_id ?? `CASE-${shipment.shipment_id}`;
  ck(`S1: seed ${id}`, seed.status === 202, `${seed.status} state=${seed.json?.state}`);
  const ask = await api("POST", `proxy/review/${id}/request-evidence`, { cookie: reviewer, body: {} });
  const links = Object.fromEntries((ask.json?.links ?? []).map((l) => [l.doc_type, String(l.path ?? "").split("/").pop()]));
  const rid = ask.json?.request?.request_id;
  ck("S1: three links for a three-document request", ask.status === 201 && Object.keys(links).length === 3 && !!rid, `${ask.status} ${Object.keys(links).join(",")}`);
  const up = await upload(links.certificate_of_origin);
  ck("S1: one document received (the other two links still work)", up.status === 201 && up.json?.received === true, `${up.status} ${up.text}`);
  const re = await api("POST", `proxy/review/${id}/reevaluate`, { cookie: reviewer, body: {} });
  ck("S1: re-evaluate with one of three is accepted", re.status === 200, `${re.status} ${re.text}`);
  const c = await getCase(reviewer, id), req = (c.verification?.requests ?? [])[0] ?? {}, ev = (c.verification?.evaluations ?? []).at(-1) ?? {};
  console.log(`  request=${req.status} received=${Object.keys(req.received_docs ?? {})} evaluation=${ev.status} unresolved=${JSON.stringify(ev.unresolved)} state=${c.state}`);
  ck("S1: the request is still open", ["SENT", "OPEN"].includes(req.status), req.status);
  ck("S1: the evaluation is missing, with the other two unresolved", ev.status === "missing" && [...(ev.unresolved ?? [])].sort().join() === "input_purchase_invoices,producer_declaration", `${ev.status} ${JSON.stringify(ev.unresolved)}`);
  ck("S1: the case waits for a person", ["HELD_FOR_REVIEW", "ESCALATED"].includes(c.state), c.state);
  for (const action of ["block", "release"]) {
    const a = await api("POST", `proxy/review/${id}/approve`, { cookie: reviewer, body: { action, note: "x" } });
    ck(`S1: approving a ${action} with the request open is a 409 that says why`, a.status === 409 && /open request/i.test(a.json?.error ?? ""), `${a.status} ${a.text}`);
  }
  const cancel = await api("POST", `proxy/review/${id}/evidence/${rid}/cancel`, { cookie: reviewer, body: { reason: "Rev2 negative-path test" } });
  ck("S1: cancelling the request is the way out", cancel.status === 200, `${cancel.status} ${cancel.text}`);
  const rel = await api("POST", `proxy/review/${id}/approve`, { cookie: reviewer, body: { action: "release", note: "" } });
  ck("S1: a release with documents still missing needs a note", rel.status === 400 && /unresolved|note/i.test(rel.json?.error ?? ""), `${rel.status} ${rel.text}`);
  finds.push(`S1 left ${id} held for review with a cancelled request (nothing executed, no Pub/Sub message).`);
}

const bad = res.filter((r) => !r.ok);
fs.writeFileSync(`${OUT}/negative-summary.json`, JSON.stringify({ base: BASE, run: RUN, total: res.length, failed: bad.length, skipped: res.filter((r) => r.skipped).length, notes: finds, results: res }, null, 2));
console.log(`\n${res.length - bad.length}/${res.length} passed (${res.filter((r) => r.skipped).length} skipped).${finds.length ? "\n  - " + finds.join("\n  - ") : ""}\nSaved ./${OUT}/negative-summary.json`);
process.exitCode = bad.length ? 1 : 0;
