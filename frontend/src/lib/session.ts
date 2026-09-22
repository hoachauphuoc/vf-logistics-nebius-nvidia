/**
 * Signed session tokens for the console's login.
 *
 * WHY THIS EXISTS RATHER THAN CLOUD IAP
 *
 * IAP was the first choice and is not available here. IAP needs an OAuth consent
 * screen, and creating one requires the Google Cloud project to belong to an
 * organisation -- `gcloud iap oauth-brands list` on this project answers
 * "Project must belong to an organization". The older brand API that could have
 * worked around it was permanently shut down by Google in March 2026. Enabling
 * `iapEnabled` on the Cloud Run service without a consent screen does not fail
 * loudly; it serves an empty HTTP 502 to every visitor, which is how this was
 * discovered.
 *
 * So the console signs its own sessions. That is a smaller trust base than IAP
 * -- it is our HMAC rather than Google's -- and the tradeoff is accepted
 * deliberately, because the alternative on this project is no login at all.
 *
 * WHAT THIS REPLACES
 *
 * Before this, every visitor to the deployed console was a GOVERNANCE_ADMIN. The
 * proxy attaches VF_API_KEY server-side to every forwarded request, a valid key
 * grants GOVERNANCE_ADMIN upstream, and there was nothing in front of it. Proven
 * against the live service with no credential of any kind:
 *
 *   GET https://vf-console-.../api/proxy/billing/usage  -> 200  (data returned)
 *   GET https://vf-logistics-.../api/v1/billing/usage   -> 403  (backend refuses)
 *
 * The backend authorisation was right; the console defeated it.
 *
 * WEB CRYPTO, NOT NODE CRYPTO
 *
 * Uses the Web Crypto API rather than `node:crypto` because the same verify path
 * runs in middleware, which is Edge runtime, and `node:crypto` is unavailable
 * there. Web Crypto exists in both.
 */

const COOKIE_NAME = "vf_session";

/**
 * Twelve hours: long enough for a working day, short enough that a forgotten
 * session on a shared machine expires by the next one.
 */
const TTL_SECONDS = 12 * 60 * 60;

export { COOKIE_NAME, TTL_SECONDS };

export type Session = {
  /** The operator's email. This is the value the audit trail records. */
  email: string;
  /** Expiry, epoch seconds. */
  exp: number;
};

function b64urlEncode(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function b64urlDecode(text: string): Uint8Array {
  const padded = text.replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(padded + "=".repeat((4 - (padded.length % 4)) % 4));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

/**
 * The HMAC secret.
 *
 * Returns null rather than a default when unset, and every caller treats null as
 * "refuse" rather than "allow". A default secret would be a published secret,
 * and a fallback to "no signing required" would reintroduce exactly the hole
 * this file closes.
 */
function secret(): string | null {
  const value = process.env.VF_SESSION_SECRET;
  return value && value.length >= 32 ? value : null;
}

/**
 * Whether a login is required at all.
 *
 * True in production always. In development it is true only when a secret is
 * configured, so `npm run dev` against a memory-store backend still works with
 * no setup -- the deployed posture is what this protects, and there the secret
 * is mandatory.
 *
 * Deliberately NOT "false when the secret is missing" in production: a missing
 * secret there must take the console offline, not open it. A dead console is a
 * visible failure that gets fixed; an open one is not.
 */
export function loginRequired(): boolean {
  return process.env.NODE_ENV === "production" || secret() !== null;
}

/**
 * Whether anonymous visitors may READ the console without signing in.
 *
 * Writes are never covered by this. It governs GET only, which is the same line
 * the backend already draws: auth.py's `anonymous_role()` docstring describes the
 * intended posture as "reads are public, writes need a key", and calls refusing
 * anonymous reads the stronger setting that is deliberately not the default.
 *
 * WHY IT EXISTS
 *
 * The console's own login wall is absolute -- proxy.ts turns away every request
 * without a session. That is right for a paying customer and wrong for a
 * hackathon judge, who may open the URL once and never sign in. With the wall up
 * and the backend refusing anonymous reads, the deployed service rendered a page
 * that loaded and was empty: `/` answered 200 while every XHR behind it answered
 * 401. A judge reads that as broken, not as protected.
 *
 * DEFAULTS TO FALSE, and the default is the point. A deployment that forgets this
 * variable is locked, not open. Turning it on is a deliberate act with a stated
 * reason, and the reason here is the judging window ending 15 December 2026.
 *
 * ONE CONSEQUENCE, ACCEPTED KNOWINGLY: an anonymous GET still carries VF_API_KEY
 * upstream, so an anonymous reader sees `review/queue` and `billing/usage`, both
 * of which sit above `viewer` on the backend. That is wanted here -- the review
 * queue and the cost figure are the demo -- and it is exactly why this must be
 * off before a paying customer's data is in the store.
 */
export function publicReads(): boolean {
  return (process.env.VF_PUBLIC_READS ?? "").trim().toLowerCase() === "true";
}

async function key(rawSecret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(rawSecret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"],
  );
}

/** Length-independent comparison, so a mismatch does not leak where it differs. */
function sameBytes(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) diff |= a[i] ^ b[i];
  return diff === 0;
}

/**
 * Mint a token for an operator. Returns null when no secret is configured, which
 * callers must surface as a server misconfiguration rather than a failed login.
 */
export async function signSession(email: string): Promise<string | null> {
  const rawSecret = secret();
  if (!rawSecret) return null;

  const payload: Session = {
    email,
    exp: Math.floor(Date.now() / 1000) + TTL_SECONDS,
  };
  const body = b64urlEncode(new TextEncoder().encode(JSON.stringify(payload)));
  const signature = await crypto.subtle.sign(
    "HMAC",
    await key(rawSecret),
    new TextEncoder().encode(body),
  );
  return `${body}.${b64urlEncode(new Uint8Array(signature))}`;
}

/**
 * Verify a token and return its session, or null.
 *
 * Null covers every failure indistinguishably -- absent, malformed, wrong
 * signature, expired, no secret configured. A caller cannot tell a forged token
 * from an expired one, and does not need to.
 */
export async function verifySession(
  token: string | undefined | null,
): Promise<Session | null> {
  const rawSecret = secret();
  if (!rawSecret || !token) return null;

  const dot = token.indexOf(".");
  if (dot <= 0 || dot === token.length - 1) return null;

  const body = token.slice(0, dot);
  const provided = token.slice(dot + 1);

  try {
    const expected = await crypto.subtle.sign(
      "HMAC",
      await key(rawSecret),
      new TextEncoder().encode(body),
    );
    if (!sameBytes(b64urlDecode(provided), new Uint8Array(expected))) return null;

    const session = JSON.parse(
      new TextDecoder().decode(b64urlDecode(body)),
    ) as Session;

    // Checked after the signature, not before: an expiry read from an unverified
    // payload is an attacker-supplied expiry.
    if (typeof session.exp !== "number" || session.exp * 1000 < Date.now()) {
      return null;
    }
    if (typeof session.email !== "string" || !session.email) return null;
    return session;
  } catch {
    return null;
  }
}

/** Cookie attributes. Shared so login and logout cannot drift apart. */
export function cookieOptions(maxAge: number) {
  return {
    httpOnly: true,
    // Off in development so the cookie works over plain http on localhost.
    secure: process.env.NODE_ENV === "production",
    // Lax rather than Strict: it still withholds the cookie from a cross-site
    // POST, which is what protects the proxy's write routes from CSRF, without
    // dropping the session when an operator follows a link in from elsewhere.
    sameSite: "lax" as const,
    path: "/",
    maxAge,
  };
}
