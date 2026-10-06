// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { isPasswordSession, signSession, tokenFromCookieHeader, verifySession } from "./session";

/**
 * The `amr` claim on the console session: how someone signed in.
 *
 * The one property that matters is that it fails closed. Clearing the board is
 * gated on it, so a token that does not explicitly say "password" -- including one
 * minted before the claim existed -- must never read as a password sign-in.
 */

const SECRET = "test-session-secret-do-not-ship-0123456789abcdef";

function b64url(text: string): string {
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** A correctly signed token with an arbitrary body, the way an older console minted them. */
async function signedBody(body: object): Promise<string> {
  const encoded = b64url(JSON.stringify(body));
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(SECRET),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const mac = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(encoded)));
  return `${encoded}.${b64url(String.fromCharCode(...mac))}`;
}

describe("sign-in method on the session", () => {
  beforeEach(() => vi.stubEnv("VF_SESSION_SECRET", SECRET));
  afterEach(() => vi.unstubAllEnvs());

  it("round-trips both methods", async () => {
    const password = await verifySession(await signSession("a@x.example", "password"));
    const oneClick = await verifySession(await signSession("b@x.example", "one_click"));
    expect(password?.amr).toBe("password");
    expect(oneClick?.amr).toBe("one_click");
    expect(isPasswordSession(password)).toBe(true);
    expect(isPasswordSession(oneClick)).toBe(false);
  });

  it("reads a token without the claim as a session, but never as a password", async () => {
    const legacy = await signedBody({ email: "a@x.example", exp: Math.floor(Date.now() / 1000) + 60 });
    const session = await verifySession(legacy);
    expect(session?.email).toBe("a@x.example");
    expect(session?.amr).toBeUndefined();
    expect(isPasswordSession(session)).toBe(false);
  });

  it("drops a value nobody mints instead of passing it on", async () => {
    const odd = await signedBody({
      email: "a@x.example",
      exp: Math.floor(Date.now() / 1000) + 60,
      amr: "admin",
      role: "governance_admin",
    });
    const session = await verifySession(odd);
    expect(session).toEqual({ email: "a@x.example", exp: expect.any(Number) });
    expect(isPasswordSession(session)).toBe(false);
  });

  it("honours a shorter lifetime for the one-click session", async () => {
    const session = await verifySession(await signSession("g@x.example", "one_click", 60));
    const now = Math.floor(Date.now() / 1000);
    expect(session?.exp).toBeGreaterThan(now);
    expect(session?.exp).toBeLessThanOrEqual(now + 61);
  });

  it("finds the token among other cookies", () => {
    expect(tokenFromCookieHeader("a=1; vf_session=abc.def; b=2")).toBe("abc.def");
    expect(tokenFromCookieHeader("a=1")).toBeNull();
    expect(tokenFromCookieHeader(null)).toBeNull();
  });
});
