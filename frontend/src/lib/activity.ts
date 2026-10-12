/**
 * Time a reviewer actually had a case in front of them, for the Outcomes screen.
 *
 * Counted only while the page is visible AND the person has done something in the
 * last IDLE_MS. A tab left open over lunch is not handling time, and an Outcomes
 * figure that counted it would overstate the effort a case takes -- which is the
 * one direction this number must never err in, because "it takes this long by
 * hand" is the claim the whole product is measured against.
 *
 * The accounting is a plain object with an injected clock so the tests can drive
 * it without timers; the hook in useCaseActivity wires it to the DOM.
 */

/** Past this long without input, the reviewer is treated as away. */
export const IDLE_MS = 60_000;
/** How often an accumulated span is sent. */
export const REPORT_EVERY_MS = 30_000;
/** The API's cap on one report (app.MAX_ACTIVITY_REPORT_MS). */
export const MAX_REPORT_MS = 120_000;

export interface ActivityMeter {
  /** The page became visible, or the person interacted with it. */
  touch(now: number): void;
  /** The page was hidden. Time up to now counts; nothing after it does. */
  hide(now: number): void;
  /**
   * Take the accumulated time, in whole ms, capped to one report's worth, and
   * reset. Returns 0 when there is nothing worth sending.
   */
  drain(now: number): number;
}

export function createActivityMeter(startVisible: boolean, now: number): ActivityMeter {
  let visible = startVisible;
  // When the person last did something; counting stops IDLE_MS after it.
  let lastInput = now;
  // Up to when time has already been added to `pending`.
  let countedTo = now;
  let pending = 0;

  // Add the active part of [countedTo, upTo]: visible, and before the idle cutoff.
  function accrue(upTo: number) {
    if (visible) {
      const activeUntil = Math.min(upTo, lastInput + IDLE_MS);
      if (activeUntil > countedTo) pending += activeUntil - countedTo;
    }
    countedTo = Math.max(countedTo, upTo);
  }

  return {
    touch(at) {
      accrue(at);
      visible = true;
      lastInput = at;
      countedTo = at;
    },
    hide(at) {
      accrue(at);
      visible = false;
    },
    drain(at) {
      accrue(at);
      const out = Math.min(Math.round(pending), MAX_REPORT_MS);
      pending = 0;
      return out >= 1 ? out : 0;
    },
  };
}
