/**
 * Links to a case, in one place so every screen links the same way.
 *
 * `/?case=<id>` opens the case trace over the Pipeline board, and survives a
 * refresh and a copy-paste -- the trace used to live only in component state, so
 * a case could not be shared or returned to. `/review?case=<id>` selects it in
 * the Review Queue.
 */

export function caseHref(caseId: string): string {
  return `/?case=${encodeURIComponent(caseId)}`;
}

export function reviewHref(caseId: string): string {
  return `/review?case=${encodeURIComponent(caseId)}`;
}
