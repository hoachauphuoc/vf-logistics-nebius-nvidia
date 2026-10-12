/**
 * Which of the signed-in person's organisations the console is acting in.
 *
 * Authorization review findings T02/T03: with multi-tenancy on, the API resolves
 * a request's tenant from the person's registered memberships
 * (src/vf_logistics/membership.py). Someone who belongs to more than one picks
 * which, and this is where that pick lives -- a plain cookie the BFF forwards as
 * X-VF-Tenant.
 *
 * It can only SELECT. The API checks the value against the person's own
 * memberships and refuses anything else with the same 403 whether or not the
 * tenant exists, so this cookie is a preference, not a credential: editing it
 * reaches nothing the person could not already reach. That is why it needs no
 * signature and may be readable by the page.
 */

export const TENANT_COOKIE = "vf_tenant";

/** The shape tenant.validate() accepts, so a malformed value is never forwarded. */
const TENANT_ID = /^[a-z0-9][a-z0-9_-]{1,62}$/;

export function isTenantId(value: string): boolean {
  return TENANT_ID.test(value);
}

/** The chosen tenant from a Cookie header, or null when absent or malformed. */
export function tenantChoiceFromCookieHeader(header: string | null | undefined): string | null {
  const part = (header ?? "")
    .split(";")
    .map((p) => p.trim())
    .find((p) => p.startsWith(`${TENANT_COOKIE}=`));
  if (!part) return null;
  let value: string;
  try {
    value = decodeURIComponent(part.slice(TENANT_COOKIE.length + 1)).trim().toLowerCase();
  } catch {
    return null;
  }
  return isTenantId(value) ? value : null;
}

/** Switch organisation: remember the choice and reload so every screen re-reads. */
export function chooseTenant(tenantId: string): void {
  if (typeof document === "undefined" || !isTenantId(tenantId)) return;
  document.cookie = `${TENANT_COOKIE}=${encodeURIComponent(tenantId)}; path=/; samesite=lax; max-age=${60 * 60 * 24 * 30}`;
  window.location.reload();
}

/**
 * Options that expire the choice at once, for the routes that start or end a
 * session: `response.cookies.set(TENANT_COOKIE, "", EXPIRED_TENANT_CHOICE)`.
 *
 * Re-review finding R03: the choice outlived the session, so the next person to
 * sign in on the same browser inherited it -- a tenant they are not in, and a 403
 * on every screen. A choice belongs to one person's session, and goes with it.
 * The path matches chooseTenant's, or the browser would keep a second cookie.
 */
export const EXPIRED_TENANT_CHOICE = { path: "/", maxAge: 0, sameSite: "lax" } as const;
