"use client";

import {
  Activity,
  ChevronLeft,
  FileClock,
  Inbox,
  LayoutGrid,
  Radar,
  ScrollText,
  ShieldCheck,
  Terminal,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { HelpDot } from "@/components/help/HelpDot";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useSidebarCollapsed } from "@/lib/sidebar-state";
import { cn } from "@/lib/utils";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** One line, shown collapsed as the tooltip body and expanded as a subtitle. */
  blurb: string;
}

/**
 * The six operational sections, plus Risk Radar.
 *
 * Order follows the old dashboard's sidebar so that muscle memory survives the
 * port, with two deliberate differences:
 *
 * - "Dashboard" is called Pipeline, because that is what it shows. A section
 *   named Dashboard in a console that is entirely a dashboard tells a reader
 *   nothing about which of six screens they are on.
 * - Risk Radar is new rather than ported: it reads the published B2B audit
 *   contract (`/compliance/reports`) rather than the internal case store, so it
 *   is the view an integrator's data actually appears in. It sits second because
 *   it answers "what did we decide" while Pipeline answers "what is happening".
 */
export const NAV_ITEMS: NavItem[] = [
  {
    href: "/",
    label: "Pipeline",
    icon: LayoutGrid,
    blurb: "Live board, by workflow state",
  },
  {
    href: "/radar",
    label: "Risk Radar",
    icon: Radar,
    blurb: "Completed audits, with provenance",
  },
  {
    href: "/review",
    label: "Review Queue",
    icon: Inbox,
    blurb: "Cases waiting on a person",
  },
  {
    href: "/audit",
    label: "Audit Trail",
    icon: ScrollText,
    blurb: "Every action, including refusals",
  },
  {
    href: "/governance",
    label: "Governance",
    icon: ShieldCheck,
    blurb: "Delegated authority and drift",
  },
  {
    href: "/devops",
    label: "DevOps",
    icon: Terminal,
    blurb: "Inject, upload, bulk load",
  },
  {
    href: "/agents",
    label: "Agent Console",
    icon: Activity,
    blurb: "Models, cost and injection probes",
  },
];

export function Sidebar({ reviewCount }: { reviewCount?: number | null }) {
  const [collapsed, setCollapsed] = useSidebarCollapsed();
  const pathname = usePathname();

  return (
    <aside
      className={cn(
        "sticky top-0 z-30 hidden h-svh shrink-0 flex-col border-r border-white/[0.08]",
        "bg-[#050914]/80 backdrop-blur-xl lg:flex",
        collapsed ? "w-[4.25rem]" : "w-[15.5rem]",
        "transition-[width] duration-200 ease-out",
      )}
    >
      <div className="flex h-14 items-center gap-2.5 px-4">
        <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-brand/15 ring-1 ring-brand/30">
          <FileClock className="size-4 text-brand" aria-hidden />
        </span>
        {!collapsed && (
          <span className="min-w-0">
            <span className="block truncate text-[13px] font-semibold tracking-display text-white">
              VF Logistics
            </span>
            <span className="block truncate text-[10.5px] leading-tight text-faint">
              Trade Compliance
            </span>
          </span>
        )}
      </div>

      <nav className="flex-1 space-y-0.5 overflow-y-auto scrollbar-thin px-2 pt-2">
        {NAV_ITEMS.map((item) => (
          // The help dot is a SIBLING of the link, never a child. NavLink renders
          // an <a>, and a <button> inside an anchor is invalid nesting and gives
          // the row two competing click targets.
          //
          // Suppressed while collapsed: there is no room, and the collapsed
          // tooltip already carries the blurb.
          <div key={item.href} className="flex items-center gap-1">
            <div className="min-w-0 flex-1">
              <NavLink
                item={item}
                collapsed={collapsed}
                // Exact match for "/" so every route does not light up the first
                // item; prefix match for the rest so /review/CASE-1 keeps Review
                // Queue selected.
                active={
                  item.href === "/"
                    ? pathname === "/"
                    : pathname.startsWith(item.href)
                }
                badge={item.href === "/review" ? reviewCount : undefined}
              />
            </div>
            {!collapsed && <HelpDot id={`nav:${item.href}`} side="right" />}
          </div>
        ))}
      </nav>

      <div className="border-t border-white/[0.06] p-2">
        <button
          type="button"
          onClick={() => setCollapsed(!collapsed)}
          className={cn(
            "flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-[12px]",
            "text-dim transition-colors hover:bg-white/[0.05] hover:text-white",
          )}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          <ChevronLeft
            className={cn(
              "size-4 shrink-0 transition-transform duration-200",
              collapsed && "rotate-180",
            )}
            aria-hidden
          />
          {!collapsed && <span>Collapse</span>}
        </button>
      </div>
    </aside>
  );
}

function NavLink({
  item,
  active,
  collapsed,
  badge,
}: {
  item: NavItem;
  active: boolean;
  collapsed: boolean;
  badge?: number | null;
}) {
  const Icon = item.icon;

  const body = (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group relative flex items-center gap-2.5 rounded-lg px-2.5 py-2 transition-colors",
        active
          ? "bg-white/[0.07] text-white"
          : "text-dim hover:bg-white/[0.04] hover:text-white/90",
        collapsed && "justify-center px-0",
      )}
    >
      {/* The selected rail. Absolute so it does not shift the label, which
          would make the whole list jitter as the active item changes. */}
      {active && (
        <span
          className="absolute left-0 top-1/2 h-5 w-[2px] -translate-y-1/2 rounded-r bg-brand"
          aria-hidden
        />
      )}
      <Icon className="size-4 shrink-0" aria-hidden />
      {!collapsed && (
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium">
          {item.label}
        </span>
      )}
      {/* Rendered only for a positive count. A badge reading "0" is noise, and
          `badge != null` alone would show it -- the queue being empty is the
          normal state and does not need announcing. */}
      {badge != null && badge > 0 && (
        <span
          className={cn(
            "badge-risk badge-warn px-1.5 py-0 text-[10px] tabular-nums",
            collapsed &&
              "absolute -right-0.5 -top-0.5 min-w-[1.1rem] justify-center px-1",
          )}
        >
          {badge > 99 ? "99+" : badge}
        </span>
      )}
    </Link>
  );

  if (!collapsed) return body;

  return (
    <Tooltip>
      <TooltipTrigger asChild>{body}</TooltipTrigger>
      <TooltipContent side="right" className="max-w-[16rem]">
        <span className="block font-medium text-white">{item.label}</span>
        <span className="block text-[11px] text-dim">{item.blurb}</span>
      </TooltipContent>
    </Tooltip>
  );
}
