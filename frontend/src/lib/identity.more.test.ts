import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Identity } from "./identity";
import {
  holds,
  identityKey,
  isOneClick,
  lockReason,
  passwordLockReason,
  roleLabel,
  TenantChoiceRequired,
  tenantChoiceFromRefusal,
  useIdentity,
  usePolicy,
  useTenantChoice,
} from "./identity";

const mocks = vi.hoisted(() => ({
  fetch: vi.fn(),
}));

vi.mock("@/lib/config", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/config")>();
  return {
    ...mod,
    DEMO_MODE: false,
  };
});

beforeEach(() => {
  vi.stubGlobal("fetch", mocks.fetch);
});

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

function identity(overrides: Partial<Identity>): Identity {
  return {
    email: "user@example.com",
    authenticated_by: "console_session",
    acts_for_a_person: true,
    role: "viewer",
    roles: ["viewer"],
    grants: ["viewer"],
    role_source: "TEST",
    tenant_id: "tenant-1",
    ...overrides,
  };
}

function createWrapper(client: QueryClient) {
  function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client }, children);
  }
  return Wrapper;
}

describe("roleLabel", () => {
  it("handles undefined and missing roles", () => {
    expect(roleLabel(undefined)).toBe("Public");
    expect(roleLabel(null)).toBe("Public");
  });

  it("handles empty string as falsy", () => {
    expect(roleLabel("")).toBe("Public");
  });

  it("transforms unknown role with underscores", () => {
    expect(roleLabel("custom_role_name")).toBe("custom role name");
  });

  it("returns known role labels", () => {
    expect(roleLabel("viewer")).toBe("Viewer");
    expect(roleLabel("reviewer")).toBe("Reviewer");
    expect(roleLabel("operator")).toBe("Operator");
    expect(roleLabel("governance_admin")).toBe("Governance admin");
  });
});

describe("TenantChoiceRequired", () => {
  it("constructs with reason and choices", () => {
    const choice = new TenantChoiceRequired("tenant_choice_required", ["a", "b"]);
    expect(choice.reason).toBe("tenant_choice_required");
    expect(choice.choices).toEqual(["a", "b"]);
    expect(choice.name).toBe("TenantChoiceRequired");
    expect(choice.message).toContain("tenant_choice_required");
  });

  it("constructs for each valid reason type", () => {
    const tcr = new TenantChoiceRequired("tenant_choice_required", ["x"]);
    const nmr = new TenantChoiceRequired("not_member_of_requested", ["y"]);
    const inv = new TenantChoiceRequired("invalid_choice", ["z"]);
    expect(tcr.reason).toBe("tenant_choice_required");
    expect(nmr.reason).toBe("not_member_of_requested");
    expect(inv.reason).toBe("invalid_choice");
  });
});

describe("tenantChoiceFromRefusal", () => {
  it("returns TenantChoiceRequired for valid tenant_choice_required", () => {
    const result = tenantChoiceFromRefusal({
      reason: "tenant_choice_required",
      choices: ["a", "b"],
    });
    expect(result).not.toBeNull();
    expect(result?.reason).toBe("tenant_choice_required");
    expect(result?.choices).toEqual(["a", "b"]);
  });

  it("filters out non-string and empty string choices", () => {
    const result = tenantChoiceFromRefusal({
      reason: "tenant_choice_required",
      choices: ["valid", 123, null, "", "also-valid"],
    });
    expect(result?.choices).toEqual(["valid", "also-valid"]);
  });

  it("returns null when choices array becomes empty after filtering", () => {
    expect(
      tenantChoiceFromRefusal({
        reason: "tenant_choice_required",
        choices: ["", null],
      })
    ).toBeNull();
  });

  it("returns null when reason is invalid type", () => {
    expect(tenantChoiceFromRefusal({ reason: 123, choices: ["a"] })).toBeNull();
    expect(tenantChoiceFromRefusal({ reason: null, choices: ["a"] })).toBeNull();
  });

  it("returns null when reason string is not in allowed list", () => {
    expect(
      tenantChoiceFromRefusal({
        reason: "unknown_reason",
        choices: ["a"],
      })
    ).toBeNull();
  });

  it("returns null when choices is not an array", () => {
    expect(
      tenantChoiceFromRefusal({
        reason: "tenant_choice_required",
        choices: { a: "b" },
      })
    ).toBeNull();
  });

  it("returns null for non-object body", () => {
    expect(tenantChoiceFromRefusal("string")).toBeNull();
    expect(tenantChoiceFromRefusal(123)).toBeNull();
    expect(tenantChoiceFromRefusal([])).toBeNull();
    expect(tenantChoiceFromRefusal(null)).toBeNull();
  });

  it("returns TenantChoiceRequired for each valid reason", () => {
    const tcr = tenantChoiceFromRefusal({
      reason: "tenant_choice_required",
      choices: ["x"],
    });
    const nmr = tenantChoiceFromRefusal({
      reason: "not_member_of_requested",
      choices: ["y"],
    });
    const inv = tenantChoiceFromRefusal({
      reason: "invalid_choice",
      choices: ["z"],
    });
    expect(tcr?.reason).toBe("tenant_choice_required");
    expect(nmr?.reason).toBe("not_member_of_requested");
    expect(inv?.reason).toBe("invalid_choice");
  });
});

describe("useIdentity", () => {
  it("fetches identity from whoami endpoint", async () => {
    const mockIdentity = identity({ role: "reviewer" });
    mocks.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockIdentity,
    } as never);

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result } = renderHook(() => useIdentity(), {
      wrapper: createWrapper(client),
    });

    await waitFor(() => {
      expect(result.current.data?.role).toBe("reviewer");
    });

    expect(mocks.fetch).toHaveBeenCalledWith(
      "/api/proxy/auth/whoami",
      expect.objectContaining({ headers: { Accept: "application/json" } })
    );
  });

  it("shows error when fetch fails with non-tenant choice error", async () => {
    mocks.fetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({ error: "Server error" }),
    } as never);

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result } = renderHook(() => useIdentity(), {
      wrapper: createWrapper(client),
    });

    await waitFor(() => {
      expect(result.current.error?.message).toContain("HTTP 500");
    });
  });

  it("throws TenantChoiceRequired when 403 has choice info", async () => {
    mocks.fetch.mockResolvedValueOnce({
      ok: false,
      status: 403,
      json: async () => ({
        reason: "tenant_choice_required",
        choices: ["org-a", "org-b"],
      }),
    } as never);

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result } = renderHook(() => useIdentity(), {
      wrapper: createWrapper(client),
    });

    await waitFor(() => {
      expect(result.current.error).toBeInstanceOf(TenantChoiceRequired);
      if (result.current.error instanceof TenantChoiceRequired) {
        expect(result.current.error.reason).toBe("tenant_choice_required");
        expect(result.current.error.choices).toEqual(["org-a", "org-b"]);
      }
    });
  });

  it("throws TenantChoiceRequired when 400 has choice info", async () => {
    mocks.fetch.mockResolvedValueOnce({
      ok: false,
      status: 400,
      json: async () => ({
        reason: "not_member_of_requested",
        choices: ["org-c"],
      }),
    } as never);

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result } = renderHook(() => useIdentity(), {
      wrapper: createWrapper(client),
    });

    await waitFor(() => {
      expect(result.current.error).toBeInstanceOf(TenantChoiceRequired);
    });
  });

  it("respects enabled option", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    renderHook(() => useIdentity({ enabled: false }), {
      wrapper: createWrapper(client),
    });

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(mocks.fetch).not.toHaveBeenCalled();
  });

  it("handles json parse error on 403/400 response", async () => {
    mocks.fetch.mockResolvedValueOnce({
      ok: false,
      status: 403,
      json: async () => {
        throw new Error("invalid json");
      },
    } as never);

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result } = renderHook(() => useIdentity(), {
      wrapper: createWrapper(client),
    });

    await waitFor(() => {
      expect(result.current.error?.message).toContain("HTTP 403");
    });
  });

  it("throws HTTP error when 403/400 body is not a choice refusal", async () => {
    mocks.fetch.mockResolvedValueOnce({
      ok: false,
      status: 403,
      json: async () => ({ error: "Some other error" }),
    } as never);

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result } = renderHook(() => useIdentity(), {
      wrapper: createWrapper(client),
    });

    await waitFor(() => {
      expect(result.current.error?.message).toContain("HTTP 403");
    });
  });

  it("uses AbortSignal timeout", async () => {
    mocks.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => identity({}),
    } as never);

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    renderHook(() => useIdentity(), {
      wrapper: createWrapper(client),
    });

    await waitFor(() => {
      const call = mocks.fetch.mock.calls[0];
      expect(call[1]?.signal).toBeInstanceOf(AbortSignal);
    });
  });
});

describe("useTenantChoice", () => {
  it("returns null when identity loads successfully", async () => {
    mocks.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => identity({}),
    } as never);

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result } = renderHook(
      () => ({ identity: useIdentity(), choice: useTenantChoice() }),
      { wrapper: createWrapper(client) },
    );

    await waitFor(() => {
      expect(result.current.identity.isSuccess).toBe(true);
    });
    expect(result.current.choice).toBeNull();
  });

  it("returns TenantChoiceRequired when identity query has that error", async () => {
    mocks.fetch.mockResolvedValueOnce({
      ok: false,
      status: 403,
      json: async () => ({
        reason: "tenant_choice_required",
        choices: ["org-x", "org-y"],
      }),
    } as never);

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result } = renderHook(() => useTenantChoice(), {
      wrapper: createWrapper(client),
    });

    await waitFor(() => {
      expect(result.current).toBeInstanceOf(TenantChoiceRequired);
      expect((result.current as TenantChoiceRequired).reason).toBe(
        "tenant_choice_required"
      );
    });
  });

  it("returns null when identity query has different error", async () => {
    mocks.fetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({ error: "Server error" }),
    } as never);

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result } = renderHook(
      () => ({ identity: useIdentity(), choice: useTenantChoice() }),
      { wrapper: createWrapper(client) },
    );

    await waitFor(() => {
      expect(result.current.identity.isError).toBe(true);
    });
    expect(result.current.choice).toBeNull();
  });
});

describe("usePolicy", () => {
  it("fetches policy from policy endpoint", async () => {
    const mockPolicy = {
      roles: ["viewer", "reviewer"],
      hierarchy: { viewer: [] } as Record<string, string[]>,
      anonymous_role: "viewer" as const,
      api_key_grant: "viewer" as const,
      role_assignment: [],
      routes: [],
    };
    mocks.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockPolicy,
    } as never);

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result } = renderHook(() => usePolicy(), {
      wrapper: createWrapper(client),
    });

    await waitFor(() => {
      expect(result.current.data).toEqual(mockPolicy);
    });
    expect(mocks.fetch).toHaveBeenCalledWith(
      "/api/proxy/auth/policy",
      expect.any(Object)
    );
  });

  it("handles errors in policy fetch", async () => {
    mocks.fetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({ error: "Server error" }),
    } as never);

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result } = renderHook(() => usePolicy(), {
      wrapper: createWrapper(client),
    });

    await waitFor(() => {
      expect(result.current.error?.message).toContain("HTTP 500");
    });
  });
});

describe("holds", () => {
  it("returns null for null and undefined identity", () => {
    expect(holds(null, "viewer")).toBeNull();
    expect(holds(undefined, "viewer")).toBeNull();
  });

  it("returns false when role not in grants", () => {
    const id = identity({ grants: ["viewer"] });
    expect(holds(id, "reviewer")).toBe(false);
    expect(holds(id, "operator")).toBe(false);
    expect(holds(id, "governance_admin")).toBe(false);
  });

  it("returns true when role is in grants", () => {
    const id = identity({ grants: ["viewer", "reviewer", "operator"] });
    expect(holds(id, "viewer")).toBe(true);
    expect(holds(id, "reviewer")).toBe(true);
    expect(holds(id, "operator")).toBe(true);
  });

  it("checks grants, not roles", () => {
    const id = identity({
      roles: ["viewer", "reviewer"],
      grants: ["viewer"],
    });
    expect(holds(id, "reviewer")).toBe(false);
    expect(holds(id, "viewer")).toBe(true);
  });
});

describe("lockReason", () => {
  it("returns null for null and undefined identity", () => {
    expect(lockReason(null, "viewer")).toBeNull();
    expect(lockReason(undefined, "viewer")).toBeNull();
  });

  it("returns message for anonymous identity lacking role", () => {
    const id = identity({ authenticated_by: "anonymous" });
    const msg = lockReason(id, "reviewer");
    expect(msg).toContain("Sign in");
    expect(msg).toContain("Reviewer");
  });

  it("returns special message for anonymous viewer role", () => {
    const id = identity({ authenticated_by: "anonymous" });
    const msg = lockReason(id, "viewer");
    expect(msg).toContain("Sign in to use this");
  });

  it("returns message when authenticated but lacking role", () => {
    const id = identity({
      authenticated_by: "console_session",
      role: "viewer",
      grants: ["viewer"],
    });
    const msg = lockReason(id, "operator");
    expect(msg).toContain("Needs the Operator role");
    expect(msg).toContain("Viewer");
  });

  it("returns null for api_key authenticated with needed role", () => {
    const id = identity({
      authenticated_by: "api_key",
      grants: ["viewer"],
    });
    expect(lockReason(id, "viewer")).toBeNull();
  });

  it("returns message for api_key authenticated without needed role", () => {
    const id = identity({
      authenticated_by: "api_key",
      grants: ["viewer"],
    });
    const msg = lockReason(id, "governance_admin");
    expect(msg).toContain("Needs the Governance admin role");
  });

  it("returns null for iap authenticated with needed role", () => {
    const id = identity({
      authenticated_by: "iap",
      grants: ["viewer", "reviewer"],
    });
    expect(lockReason(id, "viewer")).toBeNull();
    expect(lockReason(id, "reviewer")).toBeNull();
  });

  it("returns message for iap authenticated without needed role", () => {
    const id = identity({
      authenticated_by: "iap",
      role: "reviewer",
      grants: ["viewer", "reviewer"],
    });
    const msg = lockReason(id, "operator");
    expect(msg).toContain("Needs the Operator role");
  });
});

describe("isOneClick", () => {
  it("returns false for undefined and null identity", () => {
    expect(isOneClick(undefined)).toBe(false);
    expect(isOneClick(null)).toBe(false);
  });

  it("returns false for non-console-session auth", () => {
    expect(
      isOneClick(
        identity({
          authenticated_by: "api_key",
          session_method: "one_click",
        })
      )
    ).toBe(false);
    expect(
      isOneClick(identity({ authenticated_by: "iap", session_method: "one_click" }))
    ).toBe(false);
    expect(
      isOneClick(
        identity({
          authenticated_by: "anonymous",
          session_method: "one_click",
        })
      )
    ).toBe(false);
  });

  it("returns false for console_session without one_click method", () => {
    expect(
      isOneClick(
        identity({
          authenticated_by: "console_session",
          session_method: "password",
        })
      )
    ).toBe(false);
    expect(
      isOneClick(
        identity({
          authenticated_by: "console_session",
          session_method: "unknown",
        })
      )
    ).toBe(false);
    expect(
      isOneClick(
        identity({
          authenticated_by: "console_session",
          session_method: undefined,
        })
      )
    ).toBe(false);
    expect(
      isOneClick(
        identity({
          authenticated_by: "console_session",
          session_method: null,
        })
      )
    ).toBe(false);
  });

  it("returns true only for console_session with one_click", () => {
    expect(
      isOneClick(
        identity({
          authenticated_by: "console_session",
          session_method: "one_click",
        })
      )
    ).toBe(true);
  });
});

describe("passwordLockReason", () => {
  it("returns null for undefined and null identity", () => {
    expect(passwordLockReason(undefined)).toBeNull();
    expect(passwordLockReason(null)).toBeNull();
  });

  it("returns null for non-console-session auth", () => {
    expect(
      passwordLockReason(
        identity({ authenticated_by: "api_key", session_method: "password" })
      )
    ).toBeNull();
    expect(
      passwordLockReason(identity({ authenticated_by: "iap" }))
    ).toBeNull();
    expect(
      passwordLockReason(identity({ authenticated_by: "anonymous" }))
    ).toBeNull();
  });

  it("returns null for password session method", () => {
    expect(
      passwordLockReason(
        identity({
          authenticated_by: "console_session",
          session_method: "password",
        })
      )
    ).toBeNull();
  });

  it("mentions one_click specifically", () => {
    const msg = passwordLockReason(
      identity({
        authenticated_by: "console_session",
        session_method: "one_click",
      })
    );
    expect(msg).toContain("one click");
    expect(msg).toContain("password");
  });

  it("gives fallback message for unknown session method", () => {
    const msg = passwordLockReason(
      identity({
        authenticated_by: "console_session",
        session_method: "unknown",
      })
    );
    expect(msg).toContain("password");
    expect(msg).not.toContain("one click");
  });

  it("gives fallback message for undefined session method", () => {
    const msg = passwordLockReason(
      identity({
        authenticated_by: "console_session",
        session_method: undefined,
      })
    );
    expect(msg).toContain("password");
  });

  it("gives fallback message for null session method", () => {
    const msg = passwordLockReason(
      identity({
        authenticated_by: "console_session",
        session_method: null,
      })
    );
    expect(msg).toContain("password");
  });

  it("distinguishes one_click message from fallback", () => {
    const oneClickMsg = passwordLockReason(
      identity({
        authenticated_by: "console_session",
        session_method: "one_click",
      })
    );
    const unknownMsg = passwordLockReason(
      identity({
        authenticated_by: "console_session",
        session_method: "unknown",
      })
    );
    expect(oneClickMsg).not.toBe(unknownMsg);
  });
});

describe("identityKey constant", () => {
  it("is an array with auth and whoami", () => {
    expect(Array.isArray(identityKey)).toBe(true);
    expect(identityKey).toEqual(["auth", "whoami"]);
  });

});
