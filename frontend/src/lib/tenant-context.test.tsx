import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Tenant } from "./types";

const mocks = vi.hoisted(() => ({ demoMode: true }));

// The module reads DEMO_MODE into a constant at import time through the config
// module; a getter lets each test choose demo or live mode before re-importing it.
vi.mock("@/lib/config", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/config")>();
  return {
    ...mod,
    get DEMO_MODE() {
      return mocks.demoMode;
    },
  };
});

type TenantModule = typeof import("./tenant-context");

// tenant-context keeps the selected id in module-level state, so every test gets a
// fresh module instance rather than inheriting the previous test's selection.
async function loadModule(demoMode: boolean): Promise<TenantModule> {
  mocks.demoMode = demoMode;
  vi.resetModules();
  return import("./tenant-context");
}

const STORAGE_KEY = "vf.console.tenant";

const selected: Tenant = {
  id: "apex-logistics",
  name: "Apex Logistics",
  descriptor: "Freight forwarder",
};

beforeEach(() => {
  window.localStorage.clear();
});

describe("useTenant in demo mode", () => {
  it("selects the first demo tenant when nothing is stored", async () => {
    const mod = await loadModule(true);
    const { result } = renderHook(() => mod.useTenant());

    expect(result.current.tenant.id).toBe("apex-logistics");
    expect(result.current.tenant.name).toBe("Apex Logistics");
    expect(result.current.canSwitch).toBe(true);
  });

  it("lists every demo tenant", async () => {
    const mod = await loadModule(true);
    const { result } = renderHook(() => mod.useTenant());

    expect(result.current.tenants.map((t) => t.id)).toEqual([
      "apex-logistics",
      "meridian-freight",
      "kestrel-shipping",
    ]);
  });

  it("restores the tenant stored in localStorage", async () => {
    window.localStorage.setItem(STORAGE_KEY, "kestrel-shipping");
    const mod = await loadModule(true);
    const { result } = renderHook(() => mod.useTenant());

    expect(result.current.tenant.name).toBe("Kestrel Shipping");
  });

  it("ignores a stored id that is not a demo tenant", async () => {
    window.localStorage.setItem(STORAGE_KEY, "not-a-tenant");
    const mod = await loadModule(true);
    const { result } = renderHook(() => mod.useTenant());

    expect(result.current.tenant.id).toBe("apex-logistics");
  });

  it("switches tenant and persists the choice", async () => {
    const mod = await loadModule(true);
    const { result } = renderHook(() => mod.useTenant());

    act(() => {
      result.current.setTenantId("meridian-freight");
    });

    expect(result.current.tenant.name).toBe("Meridian Freight");
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("meridian-freight");
  });

  it("updates every mounted consumer when the tenant changes", async () => {
    const mod = await loadModule(true);
    const { result } = renderHook(() => ({
      first: mod.useTenant(),
      second: mod.useTenant(),
    }));

    act(() => {
      result.current.first.setTenantId("kestrel-shipping");
    });

    expect(result.current.first.tenant.id).toBe("kestrel-shipping");
    expect(result.current.second.tenant.id).toBe("kestrel-shipping");
  });

  it("does not write to localStorage when the same tenant is selected again", async () => {
    const mod = await loadModule(true);
    const { result } = renderHook(() => mod.useTenant());

    act(() => {
      result.current.setTenantId("apex-logistics");
    });

    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("falls back to the first tenant when an unknown id is selected", async () => {
    const mod = await loadModule(true);
    const { result } = renderHook(() => mod.useTenant());

    act(() => {
      result.current.setTenantId("ghost-tenant");
    });

    expect(result.current.tenant.id).toBe("apex-logistics");
  });
});

describe("useTenant in live mode", () => {
  it("fixes the tenant and reports that it cannot be switched", async () => {
    window.localStorage.setItem(STORAGE_KEY, "kestrel-shipping");
    const mod = await loadModule(false);
    const { result } = renderHook(() => mod.useTenant());

    expect(result.current.canSwitch).toBe(false);
    expect(result.current.tenant.id).toBe("apex-logistics");
  });

  it("ignores setTenantId and leaves storage untouched", async () => {
    const mod = await loadModule(false);
    const { result } = renderHook(() => mod.useTenant());

    act(() => {
      result.current.setTenantId("meridian-freight");
    });

    expect(result.current.tenant.id).toBe("apex-logistics");
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });
});

describe("displayTenant in demo mode", () => {
  it("returns the selected tenant unchanged, whatever the live id says", async () => {
    const mod = await loadModule(true);

    expect(mod.displayTenant(selected, "acme-co", true)).toBe(selected);
    expect(mod.displayTenant(selected, undefined)).toBe(selected);
  });
});

describe("displayTenant in live mode", () => {
  it("shows the live tenant id and describes it as the authenticated session", async () => {
    const mod = await loadModule(false);

    expect(mod.displayTenant(selected, "acme-co")).toEqual({
      id: "acme-co",
      name: "acme-co",
      descriptor: "Bound to your authenticated session",
    });
  });

  it("humanises the backend default tenant as this deployment", async () => {
    const mod = await loadModule(false);

    expect(mod.displayTenant(selected, "default").name).toBe("this deployment");
  });

  it("never shows the invented demo name in live mode", async () => {
    const mod = await loadModule(false);

    expect(mod.displayTenant(selected, "acme-co").name).not.toBe(
      "Apex Logistics",
    );
  });

  it("shows a resolving placeholder while the identity read is pending", async () => {
    const mod = await loadModule(false);

    expect(mod.displayTenant(selected, undefined)).toEqual({
      id: "unknown",
      name: "Resolving tenant",
      descriptor: "Reading identity from the audit API",
    });
  });

  it("treats a null live id as still resolving", async () => {
    const mod = await loadModule(false);

    expect(mod.displayTenant(selected, null).name).toBe("Resolving tenant");
  });

  it("treats an empty live id as still resolving", async () => {
    const mod = await loadModule(false);

    expect(mod.displayTenant(selected, "").name).toBe("Resolving tenant");
  });

  it("reports the tenant as unavailable when the identity read failed", async () => {
    const mod = await loadModule(false);

    expect(mod.displayTenant(selected, undefined, true)).toEqual({
      id: "unknown",
      name: "Tenant unavailable",
      descriptor:
        "The identity read failed; this is not a tenant named 'unknown'",
    });
  });

  it("prefers a resolved live id over the failed flag", async () => {
    const mod = await loadModule(false);

    expect(mod.displayTenant(selected, "acme-co", true).name).toBe("acme-co");
  });
});
