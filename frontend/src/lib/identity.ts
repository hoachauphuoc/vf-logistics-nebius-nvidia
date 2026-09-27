"use client";

import { useQuery } from "@tanstack/react-query";

import { DEMO_MODE } from "./config";

/**
 * Who the BACKEND believes the caller is, and what it will therefore let them do.
 *
 * Every role-dependent control in the console reads this, so a disabled button is
 * disabled for the reason the API would give. It is information, not a
 * permission: the API enforces every route itself, and a control enabled by
 * mistake here still gets a 403 there.
 *
 * Deliberately not derived on the client from the session. The console knows who
 * signed in; only the API knows which role that person holds, because the role
 * lists live in its environment (auth.py, ROLE_ASSIGNMENT_VARS).
 */

export type Role = "viewer" | "reviewer" | "operator" | "governance_admin";

export const ROLE_LABEL: Record<Role, string> = {
  viewer: "Viewer",
  reviewer: "Reviewer",
  operator: "Operator",
  governance_admin: "Governance admin",
};

/** GET /api/v1/auth/whoami (auth.describe_identity). */
export interface Identity {
  email: string;
  authenticated_by: "console_session" | "api_key" | "iap" | "anonymous";
  acts_for_a_person: boolean;
  role: Role;
  roles: Role[];
  /** Every role this identity satisfies, the hierarchy already expanded. */
  grants: Role[];
  role_source: string;
  tenant_id: string | null;
}

/** GET /api/v1/auth/policy. */
export interface AccessPolicy {
  roles: Role[];
  hierarchy: Record<Role, Role[]>;
  anonymous_role: Role | null;
  api_key_grant: Role;
  role_assignment: Array<{ variable: string; role: Role; accounts: number }>;
  routes: Array<{ path: string; methods: string[]; required_role: Role | "authenticated" | null }>;
}

export function roleLabel(role: string | null | undefined): string {
  if (!role) return "Public";
  return ROLE_LABEL[role as Role] ?? role.replace(/_/g, " ");
}

async function getAuth<T>(path: "whoami" | "policy"): Promise<T> {
  const response = await fetch(`/api/proxy/auth/${path}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal: AbortSignal.timeout(20_000),
  });
  if (!response.ok) throw new Error(`auth/${path}: HTTP ${response.status}`);
  return (await response.json()) as T;
}

export const identityKey = ["auth", "whoami"] as const;

/**
 * The caller's identity, shared by every screen through one query key.
 *
 * `null` data means the answer is not known -- loading, demo mode, or the API
 * unreachable -- and callers must treat that as "unknown", not as "viewer":
 * disabling every control because the identity is still loading would flash a
 * locked screen at an admin on every page load.
 */
export function useIdentity(options: { enabled?: boolean } = {}) {
  return useQuery<Identity | null>({
    queryKey: identityKey,
    queryFn: () => (DEMO_MODE ? Promise.resolve(null) : getAuth<Identity>("whoami")),
    enabled: options.enabled ?? true,
    retry: false,
    staleTime: 30_000,
    // Refetched with the session so a sign-in or an expiry is reflected.
    refetchInterval: 60_000,
  });
}

export function usePolicy() {
  return useQuery<AccessPolicy | null>({
    queryKey: ["auth", "policy"],
    queryFn: () => (DEMO_MODE ? Promise.resolve(null) : getAuth<AccessPolicy>("policy")),
    retry: false,
    staleTime: 5 * 60_000,
  });
}

/**
 * Whether the identity satisfies `role`. Unknown identity answers `null`, which a
 * caller should treat as "do not block" -- the API still has the final word.
 */
export function holds(identity: Identity | null | undefined, role: Role): boolean | null {
  if (!identity) return null;
  return identity.grants.includes(role);
}

/**
 * Why a WRITE control is unavailable to this identity, or null when it is
 * available (or the identity is unknown). Written as the sentence a tooltip shows.
 *
 * Every control gated with this is a write through the console's BFF, and the BFF
 * refuses any write without a session -- so an anonymous visitor is locked out
 * even of a write the API would allow a viewer (governance/simulate).
 */
export function lockReason(identity: Identity | null | undefined, role: Role): string | null {
  if (!identity) return null;
  const needed = roleLabel(role);
  if (identity.authenticated_by === "anonymous") {
    return role === "viewer"
      ? "Sign in to use this."
      : `Sign in with an account that holds the ${needed} role.`;
  }
  if (!identity.grants.includes(role)) {
    return `Needs the ${needed} role. You are signed in as ${roleLabel(identity.role)}.`;
  }
  return null;
}
