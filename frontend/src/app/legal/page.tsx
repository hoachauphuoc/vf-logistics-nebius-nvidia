"use client";

import { AlertTriangle } from "lucide-react";
import Link from "next/link";

/**
 * Terms, privacy, sub-processors and data retention, on one public page.
 *
 * PUBLIC ON PURPOSE. Listed in PUBLIC_PATHS in src/proxy.ts, because terms a
 * customer can only read after signing in are terms they cannot read before
 * agreeing to them.
 *
 * WHAT THIS IS AND IS NOT
 *
 * These are a drafting starting point written from what the system actually does --
 * which data it holds, which third parties see it, how long it is kept. That factual
 * part is accurate and was checked against the code and the deployed configuration.
 * The legal effect is NOT reviewed by a lawyer, and the banner at the top says so to
 * the reader rather than only in this comment. Shipping unreviewed terms while
 * implying they are settled would be worse than shipping none.
 *
 * The sub-processor list is the section most likely to be asked for first in a
 * procurement review, and it is the one that must never drift: every third party that
 * sees customer data belongs here. Today that is Nebius, Google Cloud and Tavily.
 */
export default function LegalPage() {
  return (
    <div className="mx-auto max-w-3xl px-4 py-12">
      <h1 className="text-[20px] font-semibold tracking-display text-white">
        Terms, privacy and data handling
      </h1>
      <p className="mt-1 text-[12px] text-faint">
        Trade Compliance Auditor &mdash; VF Logistics. Last updated 22 September
        2026.
      </p>

      <div className="mt-5 flex gap-2.5 rounded-lg border border-amber-500/25 bg-amber-500/[0.07] p-3.5">
        <AlertTriangle className="mt-[1px] size-4 shrink-0 text-amber-300" />
        <p className="text-[12px] leading-relaxed text-amber-100/90">
          <strong className="font-medium">Draft, pending legal review.</strong>{" "}
          The factual descriptions below &mdash; what data is held, who processes
          it, how long it is kept &mdash; are accurate to the current system. The
          legal wording has not been reviewed by a qualified lawyer and should be
          before it is put in front of a customer for signature.
        </p>
      </div>

      <Section title="1. What this service does">
        <p>
          The service screens import and export shipment declarations for
          sanctions exposure, dual-use export-control classification, freight and
          valuation anomalies, and adverse media. Each screening produces a
          decision, the evidence behind it, and an audit record.
        </p>
        <p>
          Screening output is decision support, not a legal determination. The
          operator remains responsible for customs and export-control compliance.
          Nothing the service produces transfers that responsibility, and a
          shipment the service clears may still breach a rule the service does not
          model.
        </p>
      </Section>

      <Section title="2. Data we process">
        <p>
          Shipment records: shipper and consignee names, addresses, tax
          identifiers, origin and destination, cargo descriptions, HS codes,
          declared values, weights and freight costs.
        </p>
        <p>
          Uploaded documents: bills of lading, invoices and similar commercial
          paperwork, including scans. The file is stored as provided.
        </p>
        <p>
          Screening output: risk scores, finding codes, model reasoning, external
          citations, and the full audit trail of every automated and human
          decision.
        </p>
        <p>
          Account data: the email address of each person authorised to use the
          console. No other personal data about users is collected. There is no
          analytics, advertising or tracking of any kind.
        </p>
      </Section>

      <Section title="3. Sub-processors">
        <p>
          Three third parties process customer data. This list is exhaustive as of
          the date above.
        </p>
        <Processor
          name="Nebius Token Factory"
          role="AI model inference"
          detail="Shipment text and transcribed document content are sent for
          inference. Includes the vision model used to read scanned documents."
        />
        <Processor
          name="Google Cloud (asia-southeast1, Singapore)"
          role="Hosting, database, file storage, content safety screening"
          detail="Cloud Run, Firestore, Cloud Storage and Model Armor. All
          customer data is stored here, in the Singapore region."
        />
        <Processor
          name="Tavily"
          role="Adverse media and open-source search"
          detail="Entity names are sent as search queries when an investigation
          runs. Shipment details and documents are not."
        />
        <p>
          We will give notice before adding a sub-processor that processes customer
          data.
        </p>
      </Section>

      <Section title="4. Where data is held">
        <p>
          All customer data is stored in Google Cloud&apos;s Singapore region
          (asia-southeast1). Inference requests to Nebius and search queries to
          Tavily are processed on their own infrastructure, which may be outside
          Singapore.
        </p>
      </Section>

      <Section title="5. Retention">
        <p>
          <strong className="font-medium text-white/90">
            Current behaviour, stated plainly:
          </strong>{" "}
          cases, audit records, events and archived documents are retained
          indefinitely. Nothing is deleted on a schedule today.
        </p>
        <p>
          That is deliberate for an audit trail, whose value depends on not being
          editable or disposable, but it is not a retention policy and a customer
          contract will need one. A retention period for archived documents in
          particular remains to be agreed &mdash; audit records and the commercial
          paperwork behind them do not necessarily warrant the same term.
        </p>
        <p>
          Backups: continuous point-in-time recovery for 7 days, daily backups
          retained 7 days, weekly backups retained 14 weeks. Deleted data may
          persist in backups until those windows pass.
        </p>
      </Section>

      <Section title="6. Security">
        <p>
          Access to the console requires an account we create; there is no public
          sign-up. Sessions are signed and expire after 12 hours. Every decision
          recorded through the console is attributed to the signed-in
          account&apos;s email address, taken from the verified session rather than
          from anything the browser supplies.
        </p>
        <p>
          Data is encrypted in transit and at rest by Google Cloud. Secrets are
          held in Google Secret Manager. Uploaded documents are screened by Model
          Armor before reaching a model, to blunt prompt injection carried inside
          commercial paperwork.
        </p>
        <p>
          The audit trail is append-only in use: decisions are added, never
          rewritten.
        </p>
      </Section>

      <Section title="7. Your data is yours">
        <p>
          Customer data is processed only to provide the service. It is not used to
          train models, not sold, and not shared with anyone outside the
          sub-processors listed above.
        </p>
        <p>
          On request we will export your cases and audit records in a machine
          readable form, or delete them, subject to the backup windows in section
          5.
        </p>
      </Section>

      <Section title="8. Availability">
        <p>
          No uptime commitment is offered at this stage. Availability is monitored
          and we will tell you about outages that affect you, but this is a pilot
          service and an SLA is not yet part of it. Do not build a process that
          cannot tolerate the service being briefly unavailable.
        </p>
      </Section>

      <Section title="9. Contact">
        <p>
          For a data protection agreement, a security questionnaire, an export
          request, a deletion request, or to report a vulnerability, contact your
          usual point of contact at VF Logistics.
        </p>
      </Section>

      <p className="mt-10 text-[12px] text-faint">
        <Link href="/login" className="text-brand hover:underline">
          Back to sign in
        </Link>
      </p>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mt-8">
      <h2 className="text-[14px] font-medium tracking-display text-white">
        {title}
      </h2>
      <div className="mt-2 space-y-2.5 text-[12.5px] leading-relaxed text-dim">
        {children}
      </div>
    </section>
  );
}

function Processor({
  name,
  role,
  detail,
}: {
  name: string;
  role: string;
  detail: string;
}) {
  return (
    <div className="rounded-lg border border-white/[0.08] bg-black/20 p-3">
      <p className="text-[12.5px] font-medium text-white/90">{name}</p>
      <p className="text-[11.5px] text-brand">{role}</p>
      <p className="mt-1 text-[12px] leading-relaxed text-dim">{detail}</p>
    </div>
  );
}
