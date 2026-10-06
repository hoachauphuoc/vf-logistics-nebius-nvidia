import { describe, expect, it } from "vitest";

import { auditActor, auditActorAuth } from "./audit-actor";
import type { AuditRecord } from "./types";

function row(overrides: Partial<AuditRecord>): AuditRecord {
  return {
    audit_id: "audit-1",
    case_id: "-",
    action: "agent_decision",
    status: "done",
    at: "2026-10-06T00:00:00Z",
    ...overrides,
  };
}

describe("the Who column", () => {
  it("reads the name wherever each kind of row put it", () => {
    expect(auditActor(row({ actor: "judge@vf-logistics.demo" }))).toBe("judge@vf-logistics.demo");
    expect(auditActor(row({ detail: { author: "a@x.example" } }))).toBe("a@x.example");
    expect(auditActor(row({ detail: { published_by: "p@x.example" } }))).toBe("p@x.example");
    expect(auditActor(row({ detail: { revoked_by: "r@x.example" } }))).toBe("r@x.example");
    expect(auditActor(row({ detail: { reviewer: "old@x.example" } }))).toBe("old@x.example");
  });

  it("prefers the top-level actor, and names nobody on an agent row", () => {
    expect(auditActor(row({ actor: "top@x.example", detail: { author: "inner@x.example" } }))).toBe(
      "top@x.example",
    );
    expect(auditActor(row({ detail: { reason: "gate refused" } }))).toBeNull();
    expect(auditActor(row({ actor: "  " }))).toBeNull();
  });

  it("finds the sign-in method at either level", () => {
    expect(auditActorAuth(row({ actor_auth: "one_click" }))).toBe("one_click");
    expect(auditActorAuth(row({ detail: { actor_auth: "password" } }))).toBe("password");
    expect(auditActorAuth(row({}))).toBeNull();
  });
});
