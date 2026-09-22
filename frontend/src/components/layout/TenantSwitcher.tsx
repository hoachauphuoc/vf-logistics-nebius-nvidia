"use client";

import { Building2, Check, ChevronDown, Lock } from "lucide-react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from "@/components/ui/select";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useTenant } from "@/lib/tenant-context";
import type { Tenant } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Organisation selector.
 *
 * In live mode this is a read-only display, and that is not a limitation to
 * work around. The API derives the tenant from the authenticated identity
 * (`_tenant()` in app.py) precisely so that a caller cannot select one; making
 * this control writable would mean adding a tenant parameter to the API, which
 * is the hole tests/test_tenant_isolation.py exists to keep shut. Switching
 * tenant for real means authenticating as someone else.
 */
export function TenantSwitcher({ display }: { display?: Tenant }) {
  const { tenant: selected, tenants, canSwitch, setTenantId } = useTenant();
  const tenant = display ?? selected;

  if (!canSwitch) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <div
            className={cn(
              "flex items-center gap-2.5 rounded-lg border border-white/10",
              "bg-black/30 px-2.5 py-1.5 text-left",
            )}
          >
            <TenantMark name={tenant.name} />
            <div className="min-w-0">
              <div className="truncate text-[13px] font-medium leading-tight text-white">
                {tenant.name}
              </div>
              <div className="truncate text-[11px] leading-tight text-faint">
                {tenant.descriptor}
              </div>
            </div>
            <Lock className="ml-1 size-3 shrink-0 text-faint" aria-hidden />
          </div>
        </TooltipTrigger>
        <TooltipContent side="bottom" className="max-w-[19rem]">
          Tenant is bound to your authenticated identity. The API reads it from
          the verified session, never from the client, so it cannot be changed
          from this console.
        </TooltipContent>
      </Tooltip>
    );
  }

  return (
    <Select value={tenant.id} onValueChange={setTenantId}>
      <SelectTrigger
        aria-label="Select organisation"
        className={cn(
          "h-auto w-[15.5rem] gap-2.5 rounded-lg border-white/10 bg-black/30 px-2.5 py-1.5",
          "transition-colors hover:border-white/20 hover:bg-black/45",
          "focus-visible:ring-2 focus-visible:ring-brand/40",
          "[&>svg:last-child]:hidden",
        )}
      >
        <span className="flex min-w-0 items-center gap-2.5">
          <TenantMark name={tenant.name} />
          <span className="min-w-0 text-left">
            <span className="block truncate text-[13px] font-medium leading-tight text-white">
              {tenant.name}
            </span>
            <span className="block truncate text-[11px] leading-tight text-faint">
              {tenant.descriptor}
            </span>
          </span>
        </span>
        <ChevronDown
          className="ml-auto size-3.5 shrink-0 text-dim opacity-70"
          aria-hidden
        />
      </SelectTrigger>

      <SelectContent
        align="start"
        className="w-[17rem] border-white/10 bg-[#0a0f1f]/95 backdrop-blur-xl"
      >
        <div className="px-2 pb-1.5 pt-1 text-[10px] font-medium uppercase tracking-wider text-faint">
          Organisation
        </div>
        {tenants.map((t) => (
          <SelectItem
            key={t.id}
            value={t.id}
            className="gap-2.5 rounded-md py-1.5 pl-2 pr-2 focus:bg-white/[0.07] [&>span:last-child]:hidden"
          >
            <span className="flex w-full items-center gap-2.5">
              <TenantMark name={t.name} />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-medium leading-tight text-white">
                  {t.name}
                </span>
                <span className="block truncate text-[11px] leading-tight text-faint">
                  {t.descriptor}
                </span>
              </span>
              {t.id === tenant.id ? (
                <Check className="size-3.5 shrink-0 text-brand" aria-hidden />
              ) : null}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** Initials tile, so each tenant is distinguishable before reading the name. */
function TenantMark({ name }: { name: string }) {
  const initials = name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toUpperCase();

  return (
    <span
      aria-hidden
      className={cn(
        "grid size-7 shrink-0 place-items-center rounded-md",
        "border border-white/10 bg-gradient-to-br from-indigo-500/25 to-brand/15",
        "text-[10px] font-semibold tracking-tight text-white/90",
      )}
    >
      {initials || <Building2 className="size-3.5" />}
    </span>
  );
}
