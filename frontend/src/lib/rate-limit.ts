/**
 * An in-memory sliding-window rate limiter, shared by the two sign-in routes.
 *
 * Per-instance, not shared across Cloud Run instances -- the same trade-off as
 * the backend's memory:// limiter, so the real ceiling is `limit` times the
 * instance count. Good enough to stop one source hammering a route; not a
 * substitute for a shared store if the console ever scales out for real.
 */

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

/** The caller's address as Cloud Run's front end reports it, or "unknown". */
export function clientIp(request: Request): string {
  return request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || "unknown";
}

/** One counter to consult: `limit` attempts per `windowSeconds` for `key`. */
export type LimitCheck = { key: string; limit: number; windowSeconds: number };

/** How long to wait for the shared counter before falling back to the local one. */
export const SHARED_LIMIT_TIMEOUT_MS = 3_000;

/**
 * Ask Flask's shared counter whether any of `checks` is over its limit.
 *
 * Review finding A04: the per-instance Map above made the configured limit a
 * per-instance limit. Flask keeps one ledger for every console instance (in
 * Firestore on the deployed service), reached over the loopback with the
 * console's own key -- `/internal/login-throttle` is not forwarded to browsers.
 *
 * Returns null when the shared counter cannot answer (unconfigured key, Flask
 * down, a timeout, an unexpected reply). The caller then uses its local limiter,
 * so a slow Flask degrades the limit to per-instance rather than either locking
 * everyone out or letting every attempt through.
 */
export async function sharedLimited(
  checks: LimitCheck[],
  base: string,
  apiKey: string | undefined,
): Promise<boolean | null> {
  if (!apiKey) return null;
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
    if (!response.ok) return null;
    const body = (await response.json()) as { limited?: unknown };
    return typeof body.limited === "boolean" ? body.limited : null;
  } catch {
    return null;
  }
}
