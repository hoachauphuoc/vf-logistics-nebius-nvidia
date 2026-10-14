import fs from "node:fs";
const esc = (s) => s.replace(/[\\()]/g, "\\$&");
const pdf = (title, lines) => {
  const ops = [`BT /F2 18 Tf 50 780 Td (${esc(title)}) Tj ET`, ...lines.map((l, i) => `BT /F1 12 Tf 50 ${740 - i * 24} Td (${esc(l)}) Tj ET`)].join("\n");
  const objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>",
    `<< /Length ${Buffer.byteLength(ops)} >>\nstream\n${ops}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"];
  let out = "%PDF-1.4\n"; const offs = [];
  objs.forEach((o, i) => { offs.push(Buffer.byteLength(out)); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = Buffer.byteLength(out);
  out += `xref\n0 7\n0000000000 65535 f \n${offs.map((o) => String(o).padStart(10, "0") + " 00000 n \n").join("")}trailer\n<< /Size 7 /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
  return Buffer.from(out, "latin1");
};
const cert = ["Certificate No.: VN-CO-2026-104233", "Exporter / Producer: Saigon Plywood Co., Ltd., Binh Duong, Vietnam", "Consignee: US Hardwood Imports LLC, Long Beach, United States", "Goods: Hardwood plywood, 18 mm, HS 4412.33", "Country of origin: Vietnam", "Issued by: VCCI, 2026-10-01"];
const decl = ["Producer: Saigon Plywood Co., Ltd.", "Product: Hardwood plywood, 18 mm", "The veneers and cores used in this product originate in: Vietnam", "Input origins: Vietnam", "Signed: Production Director, 2026-10-02"];
fs.mkdirSync("docs", { recursive: true });
for (const [t, sup, org] of [["A", "VN Timber JSC, Quang Nam, Vietnam", "Vietnam"], ["B", "Linyi Veneer Co., Ltd., Shandong, China", "China"]]) {
  fs.writeFileSync(`docs/${t}-certificate_of_origin.pdf`, pdf("CERTIFICATE OF ORIGIN", cert));
  fs.writeFileSync(`docs/${t}-producer_declaration.pdf`, pdf("PRODUCER'S DECLARATION", decl));
  fs.writeFileSync(`docs/${t}-input_purchase_invoices.pdf`, pdf("COMMERCIAL INVOICE (INPUT PURCHASE)", ["Invoice No.: INV-2026-0877", `Supplier: ${sup}`, "Buyer: Saigon Plywood Co., Ltd.", "Goods: Rotary-cut hardwood veneer, 1.7 mm", `Country of origin of goods: ${org}`, `Supplier country: ${org}`, "Amount: USD 14,200.00"]));
}
console.log("6 PDFs ok");
