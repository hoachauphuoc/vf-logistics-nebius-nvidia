"use client";

import { AlertTriangle, Ban, Check, ShieldAlert, SkipForward } from "lucide-react";

import { buildChain, type ChainLink, type ChainStatus } from "@/lib/case-chain";
import type { Case } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS_ICON: Record<ChainStatus, typeof Check> = {
  done: Check,
  blocked: ShieldAlert,
  denied: Ban,
  skipped: SkipForward,
  failed: AlertTriangle,
};

const STATUS_TONE: Record<ChainStatus, string> = {
  done: "text-risk-clear",
  blocked: "text-risk-critical",
  denied: "text-risk-critical",
  skipped: "text-dim",
  failed: "text-risk-warn",
};

const STATUS_WORD: Record<ChainStatus, string> = {
  done: "done",
  blocked: "blocked",
  denied: "refused",
  skipped: "skipped",
  failed: "failed",
};

/**
 * The case's end-to-end chain, at the top of the trace. See lib/case-chain.ts.
 *
 * An ordered list rather than a diagram, so a screen reader reads it as the
 * sequence it is, and it wraps on a narrow sheet instead of scrolling sideways.
 */
export function CaseChain({ case: c }: { case: Case }) {
  const links = buildChain(c);
  if (links.length === 0) return null;

  return (
    <section aria-labelledby="case-chain-title">
      <h3
        id="case-chain-title"
        className="text-[11px] font-medium uppercase tracking-wide text-faint"
      >
        End to end
      </h3>
      <p className="mt-1 text-[11.5px] leading-relaxed text-dim">
        Every step this case went through, in order, and what ran it.
      </p>
      <ol className="mt-2 space-y-1">
        {links.map((link, i) => (
          <ChainRow key={link.key} link={link} index={i} last={i === links.length - 1} />
        ))}
      </ol>
    </section>
  );
}

function ChainRow({ link, index, last }: { link: ChainLink; index: number; last: boolean }) {
  const Icon = STATUS_ICON[link.status];
  return (
    <li className="relative flex items-start gap-2.5 pl-0.5">
      {/* The connector, so the list reads as a chain rather than a set. */}
      {!last && (
        <span className="absolute left-[10px] top-5 h-[calc(100%-4px)] w-px bg-white/10" aria-hidden />
      )}
      <span
        className={cn(
          "relative z-10 mt-[1px] grid size-[19px] shrink-0 place-items-center rounded-full border border-white/10 bg-slate-950",
          STATUS_TONE[link.status],
        )}
      >
        <Icon className="size-3" aria-hidden />
      </span>
      <span className="min-w-0 flex-1 pb-1">
        <span className="flex flex-wrap items-baseline gap-x-2">
          <span className="text-[12px] text-white/90">
            <span className="sr-only">Step {index + 1}: </span>
            {link.label}
          </span>
          <span className="font-mono text-[10.5px] text-dim">{link.engine}</span>
          <span className={cn("text-[10.5px]", STATUS_TONE[link.status])}>
            {STATUS_WORD[link.status]}
          </span>
        </span>
        {link.detail && (
          <span className="block text-[11px] leading-relaxed text-dim">{link.detail}</span>
        )}
      </span>
    </li>
  );
}
