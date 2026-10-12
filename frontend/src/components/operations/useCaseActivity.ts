"use client";

import { useEffect } from "react";

import { reportCaseActivity } from "@/lib/api";
import { createActivityMeter, REPORT_EVERY_MS } from "@/lib/activity";

/** What counts as the person doing something with the page. */
const INPUT_EVENTS = ["pointerdown", "keydown", "scroll", "wheel", "pointermove"] as const;

/**
 * Report the time the signed-in reviewer spends with `caseId` in view.
 *
 * `enabled` is false for anyone the API would refuse (viewers, anonymous, the API
 * key acting for nobody): sending reports that are certain to 403 would fill the
 * console's network log with failures that mean nothing. A report that fails for
 * any other reason is dropped, so handling time under-counts rather than the
 * review being interrupted -- see reportCaseActivity.
 */
export function useCaseActivity(caseId: string | null, enabled: boolean) {
  useEffect(() => {
    if (!caseId || !enabled || typeof document === "undefined") return;

    const meter = createActivityMeter(document.visibilityState === "visible", Date.now());
    const send = () => {
      const ms = meter.drain(Date.now());
      if (ms > 0) reportCaseActivity(caseId, ms).catch(() => undefined);
    };

    // Throttled to once a second: pointermove fires far more often than the meter
    // needs, and touch() only has to know the person is still there.
    let lastTouch = 0;
    const onInput = () => {
      const now = Date.now();
      if (now - lastTouch < 1_000) return;
      lastTouch = now;
      meter.touch(now);
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        meter.touch(Date.now());
      } else {
        meter.hide(Date.now());
        send();
      }
    };

    for (const name of INPUT_EVENTS) window.addEventListener(name, onInput, { passive: true });
    document.addEventListener("visibilitychange", onVisibility);
    const timer = window.setInterval(send, REPORT_EVERY_MS);

    return () => {
      window.clearInterval(timer);
      for (const name of INPUT_EVENTS) window.removeEventListener(name, onInput);
      document.removeEventListener("visibilitychange", onVisibility);
      send();
    };
  }, [caseId, enabled]);
}
