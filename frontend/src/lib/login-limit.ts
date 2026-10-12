import { clientIp, type LimitCheck, limitKey, sharedLimited, slidingWindowLimiter } from "@/lib/rate-limit";

/**
 * The sign-in attempt limits (authorization review finding A04).
 *
 * Two independent limits, both checked before PBKDF2 runs. The single
 * "IP|email" key these replaced meant a new address gave the same account a fresh
 * allowance and a new account gave the same address one, so neither the account
 * nor the source was actually bounded. And the key only lower-cased the email
 * while verifyOperator also trimmed it, so " judge@x" and "judge@x" were one
 * account with two allowances -- padding with spaces bought unlimited attempts.
 *
 * - per account: bounds a distributed guess against one account, from anywhere.
 *   Five a minute; a person mistyping a password does not reach it.
 * - per source: bounds one address spraying many accounts, and the CPU that
 *   PBKDF2 costs. Twenty a minute, so one colleague behind an office NAT does
 *   not lock out the rest.
 *
 * Counted on Flask's shared ledger so every Cloud Run instance spends one
 * allowance. When the ledger cannot answer, a deployed console refuses the
 * attempt (re-review finding R01) -- see isLoginRateLimited.
 */
export const ACCOUNT_LIMIT = 5;
export const SOURCE_LIMIT = 20;
export const WINDOW_SECONDS = 60;

/** The one canonical form of a sign-in email: for the limit AND the lookup. */
export function canonicalEmail(raw: string): string {
  return raw.trim().toLowerCase();
}

type LocalLimiters = { account: (key: string) => boolean; source: (key: string) => boolean };

function newLocalLimiters(): LocalLimiters {
  return {
    account: slidingWindowLimiter(WINDOW_SECONDS * 1000, ACCOUNT_LIMIT),
    source: slidingWindowLimiter(WINDOW_SECONDS * 1000, SOURCE_LIMIT),
  };
}

let local = newLocalLimiters();

/** Test seam: forget every locally counted attempt. */
export function resetLocalLoginLimits(): void {
  local = newLocalLimiters();
}

/**
 * The verdict on one sign-in attempt.
 *
 * - "allowed": under both limits; the attempt has been counted.
 * - "limited": over a limit -- 429.
 * - "unavailable": no limit could be established -- 503, and no password check.
 */
export type LoginLimitVerdict = "allowed" | "limited" | "unavailable";

/**
 * Whether per-instance counters may stand in for the shared ledger: only on a
 * development server with no key to reach Flask's ledger with. A deployed
 * console always has the key, and there a missing answer means a fault, not a
 * reason to count somewhere weaker.
 */
function mayCountLocally(apiKey: string | undefined): boolean {
  return !apiKey && process.env.NODE_ENV !== "production";
}

/**
 * The verdict on this sign-in attempt. Counts the attempt when it is allowed.
 * `account` must already be canonical (see canonicalEmail).
 *
 * Re-review finding R01: any failure of the shared ledger used to fall through
 * to local counters that had never seen the attempts the ledger had counted, so
 * an attacker who could make the ledger refuse (an over-long key was enough)
 * got a second allowance -- and a fresh one on every instance. Without the
 * ledger's answer the attempt is now refused outright: Flask runs in the same
 * container, so when it cannot answer the console cannot do anything else
 * either, and refusing a sign-in is the only outcome that keeps the limit.
 */
export async function loginAttemptVerdict(
  account: string,
  request: Request,
  base: string,
  apiKey: string | undefined,
): Promise<LoginLimitVerdict> {
  const source = clientIp(request);
  const accountKey = limitKey("acct", account);
  const sourceKey = limitKey("ip", source);
  const checks: LimitCheck[] = [
    { key: accountKey, limit: ACCOUNT_LIMIT, windowSeconds: WINDOW_SECONDS },
    { key: sourceKey, limit: SOURCE_LIMIT, windowSeconds: WINDOW_SECONDS },
  ];
  const shared = await sharedLimited(checks, base, apiKey);
  if (shared.limited !== null) return shared.limited ? "limited" : "allowed";

  if (!mayCountLocally(apiKey)) {
    // Loud, so a misconfiguration (a wrong key, a ledger refusing every key) is
    // an alert and not a quietly weaker limit.
    console.error(`sign-in refused: the shared attempt counter did not answer (${shared.reason})`);
    return "unavailable";
  }
  // Both counted rather than short-circuited, so each limit sees every attempt.
  const overAccount = local.account(accountKey);
  const overSource = local.source(sourceKey);
  return overAccount || overSource ? "limited" : "allowed";
}
