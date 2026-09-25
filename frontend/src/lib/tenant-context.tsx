"use client";

import { useSyncExternalStore } from "react";

import { DEMO_MODE } from "./config";
import { DEFAULT_TENANT_ID, DEMO_TENANTS } from "./demo-data";
import type { Tenant } from "./types";

const STORAGE_KEY = "vf.console.tenant";

/**
 * Tenant selection, held in a small external store rather than component state.
 *
 * The obvious implementation -- useState plus an effect that restores the
 * persisted value on mount -- calls setState from inside an effect, which
 * cascades an extra render on every mount and is what
 * react-hooks/set-state-in-effect exists to catch. useSyncExternalStore is the
 * API for this shape: `getServerSnapshot` renders the default on the server, so
 * the markup matches, and React re-reads from localStorage once hydration is
 * finished.
 */
let cached: string | null = null;
const listeners = new Set<() => void>();

function read(): string {
  if (!DEMO_MODE || typeof window === "undefined") return DEFAULT_TENANT_ID;
  const stored = window.localStorage.getItem(STORAGE_KEY);
  return stored && DEMO_TENANTS.some((t) => t.id === stored)
    ? stored
    : DEFAULT_TENANT_ID;
}

// Cached, because getSnapshot must return an identical value for identical
// state. Reading localStorage on every call would return a fresh string and
// React would treat the store as permanently changing.
function getSnapshot(): string {
  if (cached === null) cached = read();
  return cached;
}

function getServerSnapshot(): string {
  return DEFAULT_TENANT_ID;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function setTenantId(id: string): void {
  if (!DEMO_MODE || id === cached) return;
  cached = id;
  if (typeof window !== "undefined") {
    window.localStorage.setItem(STORAGE_KEY, id);
  }
  for (const listener of listeners) listener();
}

export interface TenantState {
  tenant: Tenant;
  tenants: Tenant[];
  /** False in live mode: the tenant is fixed by the authenticated identity. */
  canSwitch: boolean;
  setTenantId: (id: string) => void;
}

export function useTenant(): TenantState {
  const tenantId = useSyncExternalStore(
    subscribe,
    getSnapshot,
    getServerSnapshot,
  );

  return {
    tenant: DEMO_TENANTS.find((t) => t.id === tenantId) ?? DEMO_TENANTS[0],
    tenants: DEMO_TENANTS,
    canSwitch: DEMO_MODE,
    setTenantId,
  };
}

/**
 * The organisation to display, given what the API says the tenant is.
 *
 * In demo mode that is the selected fixture. In live mode it must NOT be:
 * DEMO_TENANTS[0] is "Apex Logistics", and printing an invented company name
 * above real screening results is the same liability the demo pill exists to
 * avoid, pointed the other way -- a screenshot then attributes a real sanctions
 * hit to a company that has nothing to do with it.
 *
 * `/billing/usage` returns `tenant_id`, derived server-side from the
 * authenticated identity, which makes it the only trustworthy answer available
 * to the client. Until it arrives the label says so rather than guessing.
 *
 * `failed` distinguishes "the read has not come back yet" from "the read came back an
 * error". Without it both were `liveTenantId === undefined`, so a dead billing API left
 * the heading reading "screened for Resolving tenant" permanently -- a loading state that
 * never ends, which is how a failure disguises itself as slowness.
 *
 * The raw id is humanised for display because the backend's default tenant is literally
 * `"default"`, and "Import and export declarations screened for default" reads as an
 * unconfigured install rather than as a single-tenant deployment.
 */
export function displayTenant(
  selected: Tenant,
  liveTenantId: string | null | undefined,
  failed = false,
): Tenant {
  if (DEMO_MODE) return selected;
  if (liveTenantId) {
    return {
      id: liveTenantId,
      name: tenantLabel(liveTenantId),
      descriptor: "Bound to your authenticated session",
    };
  }
  return {
    id: "unknown",
    name: failed ? "Tenant unavailable" : "Resolving tenant",
    descriptor: failed
      ? "The identity read failed; this is not a tenant named 'unknown'"
      : "Reading identity from the audit API",
  };
}

/**
 * A tenant id rendered for a heading.
 *
 * Only `default` is special-cased, and deliberately so: inventing a display name for an
 * arbitrary customer id would put a company name on screen that the API never said, which
 * is the exact failure the comment above is guarding against. Everything else is shown as
 * the id it is.
 */
function tenantLabel(tenantId: string): string {
  if (tenantId === "default") return "this deployment";
  return tenantId;
}
