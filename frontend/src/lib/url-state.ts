"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

/**
 * Report the `?case=` parameter whenever it changes.
 *
 * A component rather than a hook because useSearchParams() must sit inside a
 * <Suspense> boundary or Next refuses to prerender the page; wrapping just this
 * null-rendering listener keeps the rest of the screen server-rendered as before.
 */
export function CaseParamListener({ onChange }: { onChange: (caseId: string | null) => void }) {
  const caseId = useSearchParams().get("case");
  useEffect(() => {
    onChange(caseId);
  }, [caseId, onChange]);
  return null;
}

/**
 * Put the open case in the address bar, or take it out, without a navigation.
 *
 * replaceState rather than pushState: opening and closing a case is not a page
 * the Back button should step through. Next's router observes native
 * replaceState, so useSearchParams above sees the change.
 */
export function writeCaseParam(caseId: string | null): void {
  const url = new URL(window.location.href);
  if (caseId) url.searchParams.set("case", caseId);
  else url.searchParams.delete("case");
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
}

/**
 * True once `active` has stayed true for `ms`. For saying "this is slow, and
 * here is why" instead of leaving a skeleton on screen with no explanation.
 */
export function useLate(active: boolean, ms: number): boolean {
  const [late, setLate] = useState(false);
  useEffect(() => {
    if (!active) return;
    const timer = setTimeout(() => setLate(true), ms);
    return () => {
      clearTimeout(timer);
      setLate(false);
    };
  }, [active, ms]);
  return active && late;
}
