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
