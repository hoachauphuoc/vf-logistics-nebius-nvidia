import { clientIp, type LimitCheck, sharedLimited, slidingWindowLimiter } from "@/lib/rate-limit";

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
 * allowance; per-instance counters are the fallback when Flask cannot answer.
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
 * Whether this sign-in attempt is over either limit. Counts the attempt when it
 * is not. `account` must already be canonical (see canonicalEmail).
 */
export async function isLoginRateLimited(
  account: string,
  request: Request,
  base: string,
  apiKey: string | undefined,
): Promise<boolean> {
  const source = clientIp(request);
  const checks: LimitCheck[] = [
    { key: `acct:${account}`, limit: ACCOUNT_LIMIT, windowSeconds: WINDOW_SECONDS },
    { key: `ip:${source}`, limit: SOURCE_LIMIT, windowSeconds: WINDOW_SECONDS },
  ];
  const shared = await sharedLimited(checks, base, apiKey);
  if (shared !== null) return shared;
  // Both counted rather than short-circuited, so each limit sees every attempt.
  const overAccount = local.account(`acct:${account}`);
  const overSource = local.source(`ip:${source}`);
  return overAccount || overSource;
}
