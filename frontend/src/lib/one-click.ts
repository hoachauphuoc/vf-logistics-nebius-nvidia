/**
 * One-click sign-in for hackathon judges.
 *
 * A judge with three minutes should not have to find a password in a private
 * field to try the product, so the console can offer a button that signs them in
 * as a dedicated guest account. That account holds whatever role the backend's
 * own lists give it (ADMIN_EMAILS on Cloud Run); the console asserts nothing
 * about roles.
 *
 * WHAT IT CANNOT DO. The session it mints is marked `amr: "one_click"`, and the
 * routes whose effect outlives the visitor -- clearing the board, revoking the
 * delegation boundary, and editing the prefilter rules -- refuse it in both the
 * BFF and Flask (auth.require_password_session). A judge who wants those signs
 * in with a password.
 *
 * OFF BY DEFAULT, like VF_PUBLIC_READS: a deployment that forgets the variables
 * offers no button. VF_ONE_CLICK_UNTIL turns it off on a date, so the public
 * door closes with the judging window even if nobody remembers to.
 *
 *   VF_ONE_CLICK_JUDGE=true
 *   VF_ONE_CLICK_EMAIL=guest-judge@vf-logistics.demo
 *   VF_ONE_CLICK_UNTIL=2026-12-16          (optional; any Date.parse-able value)
 */

/** Four hours: one judging session, with room to come back after lunch. */
export const ONE_CLICK_TTL_SECONDS = 4 * 60 * 60;

/**
 * The guest account to sign in as, or null when one-click is unavailable.
 *
 * Null for every reason indistinguishably -- switched off, no account named, a
 * malformed account, an unparseable end date, or the end date passed. An end
 * date that cannot be read closes the door rather than leaving it open forever.
 */
export function oneClickJudge(now: Date = new Date()): { email: string } | null {
  if ((process.env.VF_ONE_CLICK_JUDGE ?? "").trim().toLowerCase() !== "true") return null;

  const email = (process.env.VF_ONE_CLICK_EMAIL ?? "").trim().toLowerCase();
  if (!/^[^\s@]+@[^\s@]+$/.test(email)) return null;

  const until = (process.env.VF_ONE_CLICK_UNTIL ?? "").trim();
  if (until) {
    const end = Date.parse(until);
    if (Number.isNaN(end) || now.getTime() >= end) return null;
  }
  return { email };
}
