"use client";

import { motion } from "framer-motion";
import { AlertCircle, ChevronRight, FileSearch, Inbox } from "lucide-react";

import { RiskBadge } from "@/components/dashboard/RiskBadge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ApiError } from "@/lib/api";
import { formatRelative, formatUsd, humaniseCode } from "@/lib/format";
import { sortFindings } from "@/lib/risk";
import type { ComplianceAuditResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Props {
  audits: ComplianceAuditResponse[];
  loading: boolean;
  error: unknown;
  selectedId: string | null;
  onSelect: (audit: ComplianceAuditResponse) => void;
}

export function AuditLogsTable({
  audits,
  loading,
  error,
  selectedId,
  onSelect,
}: Props) {
  return (
    <section className="bento-card overflow-hidden">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-white/[0.07] px-4 py-3">
        <div className="flex items-center gap-2">
          <FileSearch className="size-3.5 text-dim" aria-hidden />
          <h2 className="text-[13px] font-medium tracking-display text-white">
            Audit log
          </h2>
        </div>
        <span className="text-[11px] text-faint">
          {loading ? "loading…" : `${audits.length} declarations`}
        </span>
      </header>

      {error ? (
        <ErrorState error={error} />
      ) : loading ? (
        <LoadingRows />
      ) : audits.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="scrollbar-thin overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="border-white/[0.07] hover:bg-transparent">
                <TableHead className={HEAD}>Declaration</TableHead>
                <TableHead className={cn(HEAD, "w-[9rem]")}>Risk</TableHead>
                <TableHead className={cn(HEAD, "w-[13rem]")}>Status</TableHead>
                <TableHead className={cn(HEAD, "hidden lg:table-cell")}>
                  Leading finding
                </TableHead>
                <TableHead className={cn(HEAD, "w-[6.5rem] text-right")}>
                  Cost
                </TableHead>
                <TableHead className={cn(HEAD, "w-[5.5rem] text-right")}>
                  Age
                </TableHead>
                <TableHead className={cn(HEAD, "w-9")} />
              </TableRow>
            </TableHeader>

            <TableBody>
              {audits.map((audit, index) => (
                <AuditRow
                  key={audit.audit_id}
                  audit={audit}
                  index={index}
                  selected={audit.audit_id === selectedId}
                  onSelect={onSelect}
                />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </section>
  );
}

const HEAD =
  "h-9 text-[11px] font-medium uppercase tracking-wider text-faint";

function AuditRow({
  audit,
  index,
  selected,
  onSelect,
}: {
  audit: ComplianceAuditResponse;
  index: number;
  selected: boolean;
  onSelect: (audit: ComplianceAuditResponse) => void;
}) {
  const leading = sortFindings(audit.findings)[0];

  return (
    <motion.tr
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: 0.22,
        // Capped so a long page does not make the last row arrive noticeably
        // after the first. A stagger that runs past ~400ms stops reading as
        // polish and starts reading as lag.
        delay: Math.min(index * 0.025, 0.4),
        ease: "easeOut",
      }}
      onClick={() => onSelect(audit)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect(audit);
        }
      }}
      // Rows are reachable by keyboard, not mouse-only: this table is the
      // primary navigation into the detail panel.
      tabIndex={0}
      role="button"
      aria-label={`Open audit for ${audit.shipment_id}`}
      className={cn(
        "cursor-pointer border-white/[0.05] transition-colors",
        "hover:bg-white/[0.035] focus-visible:bg-white/[0.05] focus-visible:outline-none",
        selected && "bg-white/[0.06]",
      )}
    >
      <TableCell className="py-3">
        <div className="flex min-w-0 flex-col">
          <span className="truncate text-[13px] font-medium text-white">
            {audit.shipment_id}
          </span>
          <span className="truncate text-[11px] text-faint">
            {audit.client_reference ?? audit.case_id}
          </span>
        </div>
      </TableCell>

      <TableCell className="py-3">
        <RiskMeter audit={audit} />
      </TableCell>

      <TableCell className="py-3">
        <RiskBadge audit={audit} />
      </TableCell>

      <TableCell className="hidden py-3 lg:table-cell">
        {leading ? (
          <div className="flex min-w-0 flex-col">
            <span className="truncate text-[12px] text-white/85">
              {humaniseCode(leading.code)}
            </span>
            <span className="truncate text-[11px] text-faint">
              {audit.findings.length} finding
              {audit.findings.length === 1 ? "" : "s"}
            </span>
          </div>
        ) : (
          <span className="text-[12px] text-faint">no findings</span>
        )}
      </TableCell>

      <TableCell className="tnum py-3 text-right text-[12px] text-dim">
        {formatUsd(audit.usage.estimated_cost_usd)}
      </TableCell>

      <TableCell className="tnum py-3 text-right text-[12px] text-faint">
        {formatRelative(audit.created_at)}
      </TableCell>

      <TableCell className="py-3 pr-3 text-right">
        <ChevronRight className="inline size-4 text-faint" aria-hidden />
      </TableCell>
    </motion.tr>
  );
}

/**
 * Effective risk, with the deterministic floor marked on the track.
 *
 * The floor tick is the point of this control. The model can raise the score
 * above the floor but never below it, so showing both makes visible whether a
 * verdict came from the rules or from the model -- and makes a disputed score,
 * where the model went lower and was overridden, legible at a glance.
 */
function RiskMeter({ audit }: { audit: ComplianceAuditResponse }) {
  const risk = audit.effective_risk;
  const floor = audit.risk_floor;
  const tone =
    risk >= 80
      ? "bg-[#ff4d4d]"
      : risk >= 40
        ? "bg-[#f5a524]"
        : "bg-[#3ecf8e]";

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="flex cursor-default items-center gap-2">
          <span className="tnum w-7 shrink-0 text-[13px] font-medium text-white">
            {Math.round(risk)}
          </span>
          <span className="relative h-1.5 w-full max-w-[5rem] overflow-hidden rounded-full bg-white/[0.08]">
            <span
              className={cn("absolute inset-y-0 left-0 rounded-full", tone)}
              style={{ width: `${Math.min(100, Math.max(0, risk))}%` }}
            />
            {floor > 0 ? (
              <span
                className="absolute inset-y-0 w-px bg-white/70"
                style={{ left: `${Math.min(100, floor)}%` }}
                aria-hidden
              />
            ) : null}
          </span>
        </div>
      </TooltipTrigger>
      <TooltipContent side="right" className="max-w-[20rem]">
        <p className="text-[12px] leading-relaxed">
          Effective risk <span className="text-white">{risk}</span>, on a
          deterministic floor of <span className="text-white">{floor}</span>.
          {audit.model_risk !== null ? (
            <> The model scored {audit.model_risk} on its own.</>
          ) : (
            <> The model layer did not run.</>
          )}
        </p>
        {audit.score_disputed ? (
          <p className="mt-1.5 text-[11px] leading-relaxed text-[#f7bc5c]">
            Disputed: the model and the floor differ by 15 points or more. The
            floor stands.
          </p>
        ) : null}
      </TooltipContent>
    </Tooltip>
  );
}

function LoadingRows() {
  return (
    <div className="divide-y divide-white/[0.05]">
      {[0, 1, 2, 3, 4].map((i) => (
        <div key={i} className="flex items-center gap-4 px-4 py-3.5">
          <Skeleton className="h-4 w-44 bg-white/[0.07]" />
          <Skeleton className="ml-auto h-4 w-16 bg-white/[0.07]" />
          <Skeleton className="h-5 w-24 rounded-full bg-white/[0.07]" />
        </div>
      ))}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="grid place-items-center gap-2 px-4 py-16 text-center">
      <Inbox className="size-5 text-faint" aria-hidden />
      <p className="text-[13px] text-dim">No declarations in this window.</p>
    </div>
  );
}

function ErrorState({ error }: { error: unknown }) {
  const unreachable = error instanceof ApiError && error.kind === "unreachable";
  return (
    <div className="grid place-items-center gap-2 px-4 py-16 text-center">
      <AlertCircle className="size-5 text-[#f7bc5c]" aria-hidden />
      {/* Never an empty table on failure. An empty table reads as "nothing was
          flagged", which is the opposite of "the results could not be loaded". */}
      <p className="text-[13px] text-white">
        {unreachable
          ? "The audit API is unreachable."
          : "Could not load audits."}
      </p>
      <p className="max-w-md text-[12px] text-faint">
        {error instanceof Error ? error.message : String(error)}
      </p>
    </div>
  );
}
