"use client";

import { motion } from "framer-motion";
import {
  ExternalLink,
  Gavel,
  Newspaper,
  SearchX,
  ShieldAlert,
  Terminal,
} from "lucide-react";

import { SeverityBadge } from "@/components/dashboard/RiskBadge";
import { RiskBadge } from "@/components/dashboard/RiskBadge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  formatClock,
  formatLatency,
  formatTokens,
  formatUsd,
  humaniseAgent,
  humaniseCode,
  shortModelName,
} from "@/lib/format";
import {
  evidenceFindings,
  isUnverifiedCheck,
  screeningFindings,
  sortFindings,
} from "@/lib/risk";
import type { AuditFinding, ComplianceAuditResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Props {
  audit: ComplianceAuditResponse | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function AuditDetailSheet({ audit, open, onOpenChange }: Props) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-full gap-0 border-white/10 bg-[#05091a]/95 p-0 backdrop-blur-2xl sm:max-w-[34rem]"
      >
        {audit ? (
          <>
            <SheetHeader className="gap-2 border-b border-white/[0.07] px-5 py-4">
              <div className="flex items-start justify-between gap-3 pr-6">
                <div className="min-w-0">
                  <SheetTitle className="truncate text-[15px] font-semibold tracking-display text-white">
                    {audit.shipment_id}
                  </SheetTitle>
                  <SheetDescription className="mt-0.5 truncate text-[12px] text-faint">
                    {audit.client_reference
                      ? `${audit.client_reference} · ${audit.case_id}`
                      : audit.case_id}
                  </SheetDescription>
                </div>
                <RiskBadge audit={audit} />
              </div>

              {audit.review_reason ? (
                <p className="text-[12px] leading-relaxed text-dim">
                  {audit.review_reason}
                </p>
              ) : null}
            </SheetHeader>

            <ScrollArea className="scrollbar-thin h-[calc(100svh-5.5rem)]">
              <div className="space-y-5 px-5 py-5">
                <Block
                  index={0}
                  icon={Gavel}
                  title="Matched rules"
                  caption="Deterministic checks: list screening, classification, pricing and counterparty history"
                >
                  <MatchedRules findings={audit.findings} />
                </Block>

                <Block
                  index={1}
                  icon={Terminal}
                  title="Inference metadata"
                  caption="Which model produced which part of this verdict"
                >
                  <InferenceMetadata audit={audit} />
                </Block>

                <Block
                  index={2}
                  icon={Newspaper}
                  title="Live evidence"
                  caption="Adverse-media citations retrieved at audit time"
                >
                  <LiveEvidence findings={audit.findings} />
                </Block>
              </div>
            </ScrollArea>
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

function Block({
  index,
  icon: Icon,
  title,
  caption,
  children,
}: {
  index: number;
  icon: typeof Gavel;
  title: string;
  caption: string;
  children: React.ReactNode;
}) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.26, delay: 0.05 + index * 0.07, ease: "easeOut" }}
    >
      <div className="mb-2.5 flex items-center gap-2">
        <Icon className="size-3.5 text-dim" aria-hidden />
        <h3 className="text-[11px] font-medium uppercase tracking-wider text-dim">
          {title}
        </h3>
      </div>
      <p className="mb-3 text-[12px] leading-snug text-faint">{caption}</p>
      {children}
    </motion.section>
  );
}

/* ----------------------------- Block 1 ----------------------------------- */

function MatchedRules({ findings }: { findings: AuditFinding[] }) {
  const relevant = sortFindings(screeningFindings(findings));

  if (relevant.length === 0) {
    return (
      <p className="rounded-lg border border-white/[0.07] bg-black/30 px-3 py-2.5 text-[12px] text-faint">
        No deterministic finding. Nothing on OFAC, the EU consolidated list or
        the tenant lists corresponded to a party on this declaration, and the
        pricing, routing and counterparty checks all passed.
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {relevant.map((finding) => (
        <li
          key={finding.code}
          className="rounded-lg border border-white/[0.07] bg-black/30 p-3"
        >
          <div className="flex items-start justify-between gap-2">
            <span className="text-[12px] font-medium text-white">
              {humaniseCode(finding.code)}
            </span>
            <SeverityBadge severity={finding.severity} />
          </div>

          <p className="mt-1.5 text-[12px] leading-relaxed text-dim">
            {finding.detail}
          </p>

          <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5">
            <span className="text-[11px] text-faint">
              Risk floor{" "}
              <span className="tnum text-white/80">{finding.floor}</span>
            </span>
            {finding.source_entity_ids.length > 0 ? (
              <span className="flex flex-wrap items-center gap-1.5">
                {/* The list record ids. Without these a match is an assertion;
                    with them a reviewer can pull the underlying entry. */}
                {finding.source_entity_ids.map((id) => (
                  <code
                    key={id}
                    className="rounded border border-white/10 bg-white/[0.04] px-1.5 py-0.5 font-mono text-[10.5px] text-white/75"
                  >
                    {id}
                  </code>
                ))}
              </span>
            ) : null}
          </div>
        </li>
      ))}
    </ul>
  );
}

/* ----------------------------- Block 2 ----------------------------------- */

/**
 * Per-agent model attribution, rendered as a code block.
 *
 * Read off `lineage.model_versions`, which is keyed by agent, rather than
 * printing one model name for the whole audit. Fraud detection, compliance
 * screening, HS classification and zero-day screening all run on Nano; only the
 * investigation debate runs on Super. A single hardcoded model label would be
 * wrong on most audits, and wrong specifically in the panel whose job is to let
 * someone defend the verdict.
 */
function InferenceMetadata({ audit }: { audit: ComplianceAuditResponse }) {
  const agents = Object.keys(audit.lineage.model_versions);

  return (
    <div className="code-surface overflow-hidden">
      <div className="flex items-center gap-1.5 border-b border-white/[0.07] px-3 py-2">
        <span className="size-2 rounded-full bg-[#ff5f57]" aria-hidden />
        <span className="size-2 rounded-full bg-[#febc2e]" aria-hidden />
        <span className="size-2 rounded-full bg-[#28c840]" aria-hidden />
        <span className="ml-1.5 text-[10.5px] text-faint">
          lineage · {audit.lineage.audit_id}
        </span>
      </div>

      <div className="space-y-0.5 px-3 py-3">
        {agents.length === 0 ? (
          <Line k="models" v="none — settled by deterministic rules" accent />
        ) : (
          agents.map((agent) => (
            <Line
              key={agent}
              k={humaniseAgent(agent)}
              v={shortModelName(audit.lineage.model_versions[agent])}
              accent
            />
          ))
        )}

        <Separator />

        <Line k="latency" v={formatLatency(audit.usage.latency_ms)} />
        <Line
          k="tokens"
          v={`${formatTokens(audit.usage.input_tokens)} in · ${formatTokens(audit.usage.output_tokens)} out`}
        />
        <Line k="agent_calls" v={String(audit.usage.agent_calls)} />
        <Line k="cost" v={formatUsd(audit.usage.estimated_cost_usd)} />

        <Separator />

        <Line
          k="risk"
          v={`${audit.effective_risk} effective · ${audit.risk_floor} floor · ${
            audit.model_risk === null ? "no model score" : `${audit.model_risk} model`
          }`}
        />
        <Line
          k="sanctions_list"
          v={
            audit.lineage.sanctions_synced_at
              ? `synced ${formatClock(audit.lineage.sanctions_synced_at)} · ${audit.lineage.sanctions_list_age_days}d old`
              : "not recorded"
          }
        />
        <Line
          k="ruleset"
          v={
            audit.lineage.ruleset_version === null
              ? "unversioned"
              : `v${audit.lineage.ruleset_version}`
          }
        />
        <Line k="completed" v={audit.completed_at ? formatClock(audit.completed_at) : "—"} />

        {Object.keys(audit.lineage.prompt_hashes).length > 0 ? (
          <>
            <Separator />
            {Object.entries(audit.lineage.prompt_hashes).map(([agent, digest]) => (
              // The agent name moves to the label and "sha256" to the value, so
              // the row reads without an underscore. Writing sha256(Fraud
              // detection) instead would be worse than untidy -- it would name a
              // string the digest was not computed over.
              <Line
                key={agent}
                k={humaniseAgent(agent)}
                v={`sha256 ${digest.slice(0, 16)}…`}
                muted
              />
            ))}
          </>
        ) : null}
      </div>
    </div>
  );
}

function Line({
  k,
  v,
  accent,
  muted,
}: {
  k: string;
  v: string;
  accent?: boolean;
  muted?: boolean;
}) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="shrink-0 text-[#7d8799]">{k}</span>
      <span className="text-[#4b5563]">:</span>
      <span
        className={cn(
          "min-w-0 break-all",
          accent ? "text-[#5fdda6]" : muted ? "text-[#6b7280]" : "text-white/85",
        )}
      >
        {v}
      </span>
    </div>
  );
}

function Separator() {
  return <div className="my-2 h-px bg-white/[0.06]" />;
}

/* ----------------------------- Block 3 ----------------------------------- */

/**
 * Adverse-media citations.
 *
 * Four states, and the order they are tested in matters. The finding code is
 * authoritative about whether the search ran; `evidence_urls` is authoritative
 * only about citations. Deciding from the array alone renders
 * ZERO_DAY_SEARCH_DID_NOT_RUN -- which carries an empty array -- as "the search
 * ran and returned no citations", directly contradicting the finding printed
 * two lines above it and reporting an absent search as a clean result.
 */
function LiveEvidence({ findings }: { findings: AuditFinding[] }) {
  const relevant = evidenceFindings(findings);

  if (relevant.length === 0) {
    return (
      <p className="rounded-lg border border-white/[0.07] bg-black/30 px-3 py-2.5 text-[12px] text-faint">
        Adverse-media screening was not triggered for this declaration. The gate
        runs it only when an indicator is present.
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {relevant.map((finding) => {
        const urls = finding.evidence_urls ?? [];
        // Codes in the unverified family mean the screening produced no answer,
        // whatever the citation array happens to contain.
        const didNotComplete = isUnverifiedCheck(finding.code);
        const hasCitations = !didNotComplete && urls.length > 0;
        // `!= null` on purpose: the backend sends null for "no search recorded"
        // and an older one omits the key, and both must read as no record.
        const searchedAndFoundNothing =
          !didNotComplete &&
          urls.length === 0 &&
          finding.evidence_urls != null;

        return (
          <li
            key={finding.code}
            className="rounded-lg border border-white/[0.07] bg-black/30 p-3"
          >
            <div className="flex items-start justify-between gap-2">
              <span className="text-[12px] font-medium text-white">
                {humaniseCode(finding.code)}
              </span>
              <SeverityBadge severity={finding.severity} />
            </div>

            <p className="mt-1.5 text-[12px] leading-relaxed text-dim">
              {finding.detail}
            </p>

            {hasCitations ? (
              <ul className="mt-2.5 space-y-1">
                {urls.map((url) => (
                  <li key={url}>
                    <a
                      href={url}
                      target="_blank"
                      rel="noreferrer noopener"
                      className={cn(
                        "group -mx-1.5 flex items-start gap-1.5 rounded px-1.5 py-1",
                        "text-[11.5px] text-[#8ab4f8] transition-colors hover:bg-white/[0.04]",
                      )}
                    >
                      <ExternalLink
                        className="mt-0.5 size-3 shrink-0 opacity-60"
                        aria-hidden
                      />
                      <span className="break-all group-hover:underline">
                        {hostOf(url)}
                        <span className="text-[#5a6b85]">{pathOf(url)}</span>
                      </span>
                    </a>
                  </li>
                ))}
              </ul>
            ) : didNotComplete ? (
              <p className="mt-2.5 flex items-start gap-1.5 text-[11.5px] text-[#f7bc5c]">
                <ShieldAlert className="mt-px size-3 shrink-0" aria-hidden />
                No citations, because the search did not complete. This is not a
                finding that nothing exists.
              </p>
            ) : searchedAndFoundNothing ? (
              <p className="mt-2.5 flex items-start gap-1.5 text-[11.5px] text-faint">
                <SearchX className="mt-px size-3 shrink-0" aria-hidden />
                The search ran and returned no citations.
              </p>
            ) : (
              <p className="mt-2.5 flex items-start gap-1.5 text-[11.5px] text-[#f7bc5c]">
                <ShieldAlert className="mt-px size-3 shrink-0" aria-hidden />
                No citation record on this response. Not the same as finding
                nothing — the audit API does not return evidence URLs yet.
              </p>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

function pathOf(url: string): string {
  try {
    const u = new URL(url);
    return u.pathname === "/" ? "" : u.pathname;
  } catch {
    return "";
  }
}
