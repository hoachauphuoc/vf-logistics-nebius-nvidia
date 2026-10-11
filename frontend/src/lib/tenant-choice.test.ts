// @vitest-environment node
import { describe, expect, it } from "vitest";

import { isTenantId, tenantChoiceFromCookieHeader } from "./tenant-choice";

/**
 * The organisation a person in several has chosen (findings T02/T03).
 *
 * Only a well-formed id is ever forwarded. Whether the person is a member of it
 * is the API's decision, not this file's; these tests pin only that nothing
 * malformed rides along to become part of a Firestore query.
 */
describe("tenantChoiceFromCookieHeader", () => {
  it("reads the choice among other cookies", () => {
    expect(tenantChoiceFromCookieHeader("a=1; vf_tenant=acme; vf_session=x.y")).toBe("acme");
    expect(tenantChoiceFromCookieHeader("vf_tenant=beta-shipping")).toBe("beta-shipping");
  });

  it("normalises case the way the API does", () => {
    expect(tenantChoiceFromCookieHeader("vf_tenant=Acme")).toBe("acme");
  });

  it("drops anything the API would refuse to put in a query", () => {
    for (const value of ["../other", "a%2Fb", "x", "", "has%20space", "%E0%A4%A", "-lead"]) {
      expect(tenantChoiceFromCookieHeader(`vf_tenant=${value}`), value).toBeNull();
    }
  });

  it("is null when nothing was chosen", () => {
    expect(tenantChoiceFromCookieHeader("vf_session=x.y")).toBeNull();
    expect(tenantChoiceFromCookieHeader(null)).toBeNull();
  });

  it("agrees with the id shape tenant.validate() accepts", () => {
    expect(isTenantId("acme-freight_2")).toBe(true);
    expect(isTenantId("a".repeat(64))).toBe(false);
  });
});
