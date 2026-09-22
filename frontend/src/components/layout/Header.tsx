"use client";

import { ShieldCheck } from "lucide-react";

import { AccountMenu } from "@/components/layout/AccountMenu";
import { HelpModeToggle } from "@/components/layout/HelpModeToggle";
import { TenantSwitcher } from "@/components/layout/TenantSwitcher";
import { Separator } from "@/components/ui/separator";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { DEMO_MODE } from "@/lib/config";
import type { Tenant } from "@/lib/types";

export function Header({ display }: { display?: Tenant }) {
  return (
    <header className="sticky top-0 z-30 border-b border-white/[0.08] bg-slate-950/70 backdrop-blur-xl">
      {/* Full width rather than a centred max-width container: the shell's
          sidebar already sets the content's left edge, and centring inside that
          put the header controls visibly out of line with the page below. */}
      <div className="flex h-14 w-full items-center gap-3 px-4 sm:px-6 lg:px-8">
        {/* Tenant first, top-left: it scopes everything below it, so it reads
            before the product name rather than after. */}
        <TenantSwitcher display={display} />

        <Separator
          orientation="vertical"
          className="mx-1 hidden !h-7 bg-white/10 sm:block"
        />

        <div className="hidden items-center gap-2 sm:flex">
          <ShieldCheck className="size-4 text-brand" aria-hidden />
          <span className="text-[13px] font-medium tracking-display text-white/90">
            Trade Compliance Auditor
          </span>
        </div>

        <div className="ml-auto flex items-center gap-2">
          <HelpModeToggle />
          {DEMO_MODE ? <DemoPill /> : <LivePill />}
          <AccountMenu />
        </div>
      </div>
    </header>
  );
}

/**
 * Says so, plainly, when the numbers are fixtures.
 *
 * A compliance console that cannot be told apart from the real thing is a
 * liability: someone screenshots it, and a synthetic sanctions hit against a
 * named company becomes evidence of something that never happened.
 */
function DemoPill() {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="badge-risk badge-warn cursor-default">
          <span className="size-1.5 rounded-full bg-current" aria-hidden />
          Demo data
        </span>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="max-w-[20rem]">
        Audits below are synthetic fixtures. Finding codes and model ids are the
        real ones, so the shapes match production, but no shipment, company or
        citation here is real.
      </TooltipContent>
    </Tooltip>
  );
}

function LivePill() {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="badge-risk badge-clear cursor-default">
          <span className="size-1.5 rounded-full bg-current" aria-hidden />
          Live
        </span>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="max-w-[20rem]">
        Reading the audit API for the tenant your session is authenticated
        against.
      </TooltipContent>
    </Tooltip>
  );
}
