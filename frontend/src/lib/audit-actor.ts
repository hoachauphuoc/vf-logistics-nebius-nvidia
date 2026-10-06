import type { AuditRecord } from "./types";

/**
 * Who acted on an audit row, and how they signed in.
 *
 * The rows were written by different code over time, so the name lives in
 * different places: `actor` at the top level on human decisions and board resets,
 * `detail.author` on pre-filter edits, `detail.published_by` / `revoked_by` on
 * boundary changes, `detail.reviewer` on older decision rows. Read in that order.
 * A row naming nobody is an agent or system action and returns null.
 */
export function auditActor(row: AuditRecord): string | null {
  const detail = (row.detail ?? {}) as Record<string, unknown>;
  for (const value of [
    row.actor,
    detail.reviewer,
    detail.author,
    detail.published_by,
    detail.revoked_by,
  ]) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

/** The sign-in method recorded beside the actor, or null on rows that predate it. */
export function auditActorAuth(row: AuditRecord): string | null {
  const detail = (row.detail ?? {}) as Record<string, unknown>;
  const value = row.actor_auth ?? detail.actor_auth;
  return typeof value === "string" && value ? value : null;
}
