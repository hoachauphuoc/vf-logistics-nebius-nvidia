"use client";

import { AlertTriangle, RotateCcw } from "lucide-react";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";

/**
 * Route-level error boundary.
 *
 * DID NOT EXIST until now, and its absence is what made every unguarded field read in
 * this console a page-blanking bug rather than a missing dash. React unmounts the whole
 * tree when a render throws and nothing catches it; Next only shows its own overlay in
 * development. In production the user got a white screen with no explanation and no way
 * forward except editing the URL.
 *
 * The concrete instance: `formatUsd` was typed `(value: number)`, a step with no
 * `cost_usd` passed `undefined`, and `undefined.toLocaleString()` threw. That was on
 * /agents -- the screen clip 3 of the demo video is filmed on.
 *
 * The format helpers are all guarded now, so this should be unreachable. It is here
 * because "should be unreachable" is exactly what was believed about the last one.
 */
export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Logged rather than swallowed: a boundary that renders a friendly panel and
    // discards the stack turns a fixable bug into an anecdote.
    console.error("[route-error]", error);
  }, [error]);

  return (
    <div className="bento-card flex flex-col items-center px-6 py-12 text-center">
      <span className="mb-3 grid size-9 place-items-center rounded-xl bg-risk-critical/10 text-risk-critical ring-1 ring-risk-critical/30">
        <AlertTriangle className="size-4" aria-hidden />
      </span>
      <h2 className="text-[14px] font-medium text-white">
        This screen failed to render
      </h2>
      <div className="mt-1.5 max-w-lg text-[12.5px] leading-relaxed text-dim">
        <p>
          The rest of the console is unaffected — the navigation still works and
          other screens will load. Nothing was written and no case was changed by
          this failure.
        </p>
        <p className="mt-2 font-mono text-[11px] text-faint">
          {error.message || "No message on the error object."}
          {error.digest ? ` · digest ${error.digest}` : null}
        </p>
      </div>
      <Button
        variant="outline"
        size="sm"
        className="mt-4"
        onClick={() => reset()}
      >
        <RotateCcw className="size-3.5" aria-hidden />
        Try this screen again
      </Button>
    </div>
  );
}
