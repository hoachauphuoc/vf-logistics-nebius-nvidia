import { describe, expect, it } from "vitest";

import { type Identity, holds, lockReason, roleLabel } from "./identity";

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
