/**
 * An in-memory sliding-window rate limiter, shared by the two sign-in routes.
 *
 * Per-instance, not shared across Cloud Run instances -- the same trade-off as
 * the backend's memory:// limiter, so the real ceiling is `limit` times the
 * instance count. Good enough to stop one source hammering a route; not a
 * substitute for a shared store if the console ever scales out for real.
 */

import { createHash } from "node:crypto";
import { isIP } from "node:net";

export type Limiter = (key: string) => boolean;

/**
 * Returns a function answering "is this key over the limit?", which also counts
 * the attempt when it is not. `limit` attempts are allowed per `windowMs`.
 */
export function slidingWindowLimiter(windowMs: number, limit: number): Limiter {
  const attempts = new Map<string, number[]>();

  // Periodic cleanup so the map does not grow unbounded on a long-lived instance.
  // unref'd where the runtime supports it, so a test process is not kept alive.
  const timer = setInterval(() => {
    const cutoff = Date.now() - windowMs;
    for (const [key, stamps] of attempts) {
      while (stamps.length > 0 && stamps[0] <= cutoff) stamps.shift();
      if (stamps.length === 0) attempts.delete(key);
    }
  }, windowMs);
  (timer as { unref?: () => void }).unref?.();

  return (key: string) => {
    const now = Date.now();
    let stamps = attempts.get(key);
    if (!stamps) {
      stamps = [];
      attempts.set(key, stamps);
    }
    while (stamps.length > 0 && stamps[0] <= now - windowMs) stamps.shift();
    if (stamps.length >= limit) return true;
    stamps.push(now);
    return false;
  };
}

/** The bucket for a request whose address cannot be established. */
export const UNKNOWN_SOURCE = "unknown";

/** The longest textual IP address (IPv4-mapped IPv6). Anything longer is not one. */
const MAX_IP_LENGTH = 45;

/**
 * The caller's address as Cloud Run's front end reports it, or "unknown".
 *
 * Re-review finding R01: this took the FIRST X-Forwarded-For entry, which is
 * whatever the caller chose to send. Cloud Run's front end APPENDS the address it
 * saw, and Next only fills the header in when it is absent, so the LAST entry is
 * the one nobody but the infrastructure wrote -- the same entry Flask trusts with
 * ProxyFix(x_for=1) (app.py) and that lib/upstream.ts forwards for. With the
 * first entry, a fresh made-up prefix bought a fresh per-source allowance, and a
 * very long one pushed the ledger key past its length limit.
 *
 * The entry must also BE an address: a malformed one is "unknown", so a caller
 * cannot mint buckets by writing junk where an address belongs.
 */
export function clientIp(request: Request): string {
  const header = request.headers.get("x-forwarded-for");
  if (!header) return UNKNOWN_SOURCE;
  const last = header.slice(header.lastIndexOf(",") + 1).trim();
  return last.length <= MAX_IP_LENGTH && isIP(last) !== 0 ? last : UNKNOWN_SOURCE;
}

/**
 * The ledger key for one counted value: `kind:` and the value's SHA-256.
 *
 * Fixed length whatever was typed into the email box, so no input can push the
 * key past the ledger's limit and turn a count into a 400 (finding R01). And the
 * ledger -- Firestore on the deployed service -- never holds a raw address or a
 * raw email.
 */
export function limitKey(kind: "acct" | "ip", value: string): string {
  return `${kind}:${createHash("sha256").update(value, "utf8").digest("hex")}`;
}

/** One counter to consult: `limit` attempts per `windowSeconds` for `key`. */
export type LimitCheck = { key: string; limit: number; windowSeconds: number };

/** How long to wait for the shared counter before giving up on it. */
export const SHARED_LIMIT_TIMEOUT_MS = 3_000;

/**
 * The shared counter's answer, or why there is none.
 *
 * `reason` is for the log line only; the caller acts on `limited` or on there
 * being no answer at all, and treats every kind of "no answer" the same way.
 */
export type SharedAnswer = { limited: boolean } | { limited: null; reason: string };

/**
 * Ask Flask's shared counter whether any of `checks` is over its limit.
 *
 * Review finding A04: the per-instance Map above made the configured limit a
 * per-instance limit. Flask keeps one ledger for every console instance (in
 * Firestore on the deployed service), reached over the loopback with the
 * console's own key -- `/internal/login-throttle` is not forwarded to browsers.
 *
 * Every failure -- no key, Flask down, a timeout, a 4xx, a 5xx, a body without a
 * boolean -- is "no answer". Re-review finding R01: a 400 or a 403 used to fall
 * through to a local counter that had never seen the attempts the ledger had,
 * which handed out a second, fresh allowance. What to do without an answer is
 * the caller's decision (lib/login-limit.ts), and it is not "allow".
 */
export async function sharedLimited(
  checks: LimitCheck[],
  base: string,
  apiKey: string | undefined,
): Promise<SharedAnswer> {
  if (!apiKey) return { limited: null, reason: "no VF_API_KEY" };
  try {
    const response = await fetch(`${base}/internal/login-throttle`, {
      method: "POST",
      headers: { "content-type": "application/json", "X-VF-API-Key": apiKey },
      body: JSON.stringify({
        checks: checks.map((c) => ({ key: c.key, limit: c.limit, window_seconds: c.windowSeconds })),
      }),
      cache: "no-store",
      signal: AbortSignal.timeout(SHARED_LIMIT_TIMEOUT_MS),
    });
    if (!response.ok) return { limited: null, reason: `HTTP ${response.status}` };
    const body = (await response.json()) as { limited?: unknown };
    return typeof body.limited === "boolean"
      ? { limited: body.limited }
      : { limited: null, reason: "reply without a boolean `limited`" };
  } catch (error) {
    return { limited: null, reason: error instanceof Error ? error.name : "error" };
  }
}
