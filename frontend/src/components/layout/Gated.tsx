"use client";

import { Lock } from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

/**
 * A control that may be locked for this identity, and says why.
 *
 * `reason` comes from lib/identity.ts `lockReason()`, i.e. from what the API
 * reported about the caller. With no reason the child renders untouched. With a
 * reason, the child is expected to be disabled by its caller (so the click never
 * fires) and is wrapped in a focusable span: a disabled button receives no
 * pointer or focus events, so a tooltip on the button itself would never open.
 *
 * This is presentation. The API enforces the same role on the route, so a
 * control left enabled by mistake still gets a 403 -- this only saves the click.
 */
export function Gated({
  reason,
  children,
}: {
  reason: string | null;
  children: React.ReactElement;
}) {
  if (!reason) return children;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          tabIndex={0}
          aria-label={reason}
          className="inline-flex cursor-not-allowed rounded-md focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand/60"
        >
          {children}
        </span>
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-[18rem] text-[11.5px]">
        <span className="flex items-start gap-1.5">
          <Lock className="mt-[2px] size-3 shrink-0" aria-hidden />
          <span>{reason}</span>
        </span>
      </TooltipContent>
    </Tooltip>
  );
}
