"use client";

import { AlertTriangle, Ban, Circle, ShieldCheck, ShieldAlert } from "lucide-react";

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { severityLabel } from "@/lib/format";
import { RISK_CLASS, derivePresentation, type RiskState } from "@/lib/risk";
import type { ComplianceAuditResponse, Severity } from "@/lib/types";
import { severityState } from "@/lib/risk";
import { cn } from "@/lib/utils";

const ICON: Record<RiskState, typeof Circle> = {
  critical: Ban,
  warn: AlertTriangle,
  clear: ShieldCheck,
  neutral: Circle,
};

/**
 * The status cell.
 *
 * Three states rather than two. `AuditOutcome` has five values and some of them
 * mean "this could not be determined"; rendering those as a green "Clear" would
 * put a passing mark on a shipment nobody screened, which is the one output this
 * product must never produce. `derivePresentation` owns that decision -- see the
 * comment there for the branch where a CLEARED audit still carries an
 * unverified check.
 */
export function RiskBadge({ audit }: { audit: ComplianceAuditResponse }) {
  const presentation = derivePresentation(audit);
  const Icon = ICON[presentation.state];

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(RISK_CLASS[presentation.state], "cursor-default")}
          data-state={presentation.state}
        >
          <Icon className="size-3 shrink-0" aria-hidden />
          {presentation.label}
        </span>
      </TooltipTrigger>
      <TooltipContent side="left" className="max-w-[22rem]">
        <p className="text-[12px] leading-relaxed">{presentation.reason}</p>
        {presentation.unverified.length > 0 ? (
          <p className="mt-1.5 flex items-start gap-1.5 text-[11px] leading-relaxed text-[#f7bc5c]">
            <ShieldAlert className="mt-px size-3 shrink-0" aria-hidden />
            An incomplete check is not a clearance.
          </p>
        ) : null}
      </TooltipContent>
    </Tooltip>
  );
}

/** Severity chip for an individual finding inside the detail panel. */
export function SeverityBadge({ severity }: { severity: Severity }) {
  const state = severityState(severity);
  const Icon = ICON[state];
  return (
    <span className={cn(RISK_CLASS[state], "shrink-0")}>
      <Icon className="size-3 shrink-0" aria-hidden />
      {severityLabel(severity)}
    </span>
  );
}
