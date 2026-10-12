import { describe, expect, it } from "vitest";

import { type Identity, holds, isOneClick, lockReason, passwordLockReason, roleLabel, TenantChoiceRequired, tenantChoiceFromRefusal } from "./identity";

function identity(overrides: Partial<Identity>): Identity {
  return {
    email: "dev@localhost",
    authenticated_by: "anonymous",
    acts_for_a_person: false,
    role: "viewer",
    roles: ["viewer"],
    grants: ["viewer"],
    role_source: "ANONYMOUS_ROLE",
    tenant_id: "default",
    ...overrides,
  };
}

const reviewer = identity({
  email: "reviewer@vf-logistics.demo",
  authenticated_by: "console_session",
  acts_for_a_person: true,
  role: "reviewer",
  roles: ["viewer", "reviewer"],
  grants: ["viewer", "reviewer"],
  role_source: "REVIEWER_EMAILS",
});

describe("lockReason", () => {
  it("does not lock anything while the identity is unknown", () => {
    // Loading, demo mode, or the API down: the API still has the last word, and
    // locking everything here would flash a locked screen at an admin.
    expect(lockReason(null, "governance_admin")).toBeNull();
    expect(lockReason(undefined, "reviewer")).toBeNull();
  });

  it("asks an anonymous visitor to sign in, even for a viewer write", () => {
    // The BFF refuses every write without a session, so a viewer-level write
    // (governance/simulate) is still locked for an anonymous caller.
    expect(lockReason(identity({}), "viewer")).toMatch(/sign in/i);
    expect(lockReason(identity({}), "operator")).toMatch(/Operator role/);
  });

  it("names the role a signed-in person lacks, and the one they hold", () => {
    expect(lockReason(reviewer, "operator")).toBe(
      "Needs the Operator role. You are signed in as Reviewer.",
    );
  });

  it("unlocks what the role grants", () => {
    expect(lockReason(reviewer, "reviewer")).toBeNull();
    expect(lockReason(reviewer, "viewer")).toBeNull();
  });
});

describe("holds", () => {
  it("reads the expanded grants, not just the top role", () => {
    expect(holds(reviewer, "viewer")).toBe(true);
    expect(holds(reviewer, "operator")).toBe(false);
    expect(holds(null, "viewer")).toBeNull();
  });
});

describe("roleLabel", () => {
  it("labels the known roles and treats no role as public", () => {
    expect(roleLabel("governance_admin")).toBe("Governance admin");
    expect(roleLabel(null)).toBe("Public");
  });
});

describe("tenantChoiceFromRefusal (re-review R03)", () => {
  it("reads the choices and why a choice is needed", () => {
    const choice = tenantChoiceFromRefusal({
      error: "Not a member of this organisation",
      reason: "tenant_choice_required",
      choices: ["acme", "beta-shipping"],
    });
    expect(choice).toBeInstanceOf(TenantChoiceRequired);
    expect(choice?.choices).toEqual(["acme", "beta-shipping"]);
    expect(choice?.reason).toBe("tenant_choice_required");
  });

  it("treats a stale choice as a choice to make again", () => {
    expect(tenantChoiceFromRefusal({ reason: "not_member_of_requested", choices: ["acme"] })?.choices)
      .toEqual(["acme"]);
  });

  it("is null for any other refusal, so a role 403 is not mistaken for one", () => {
    for (const body of [
      null,
      "no",
      { error: "Insufficient permissions" },
      { reason: "no_membership", choices: [] },
      { reason: "tenant_choice_required", choices: [] },
      { reason: "tenant_choice_required", choices: "acme" },
      { reason: "something_else", choices: ["acme"] },
    ]) {
      expect(tenantChoiceFromRefusal(body), JSON.stringify(body)).toBeNull();
    }
  });
});

describe("passwordLockReason", () => {
  const admin = (session_method: Identity["session_method"]) =>
    identity({
      email: "guest-judge@vf-logistics.demo",
      authenticated_by: "console_session",
      acts_for_a_person: true,
      role: "governance_admin",
      grants: ["viewer", "reviewer", "operator", "governance_admin"],
      session_method,
    });

  it("locks a one-click session and says how to unlock it", () => {
    expect(passwordLockReason(admin("one_click"))).toMatch(/one click/i);
    expect(passwordLockReason(admin("one_click"))).toMatch(/password/i);
    expect(isOneClick(admin("one_click"))).toBe(true);
  });

  it("locks a session whose method is unknown, the way the API does", () => {
    expect(passwordLockReason(admin("unknown"))).toMatch(/password/i);
    expect(passwordLockReason(admin(undefined))).toMatch(/password/i);
  });

  it("opens for a password session, and has nothing to say without a session", () => {
    expect(passwordLockReason(admin("password"))).toBeNull();
    expect(passwordLockReason(identity({ authenticated_by: "api_key" }))).toBeNull();
    expect(passwordLockReason(null)).toBeNull();
  });
});
