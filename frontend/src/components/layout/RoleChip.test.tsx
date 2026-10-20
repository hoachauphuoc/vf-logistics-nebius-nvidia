import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RoleChip } from "./RoleChip";

describe("RoleChip", () => {
  it("labels each known role with its display name", () => {
    const cases: Array<[string, string]> = [
      ["viewer", "Viewer"],
      ["reviewer", "Reviewer"],
      ["operator", "Operator"],
      ["governance_admin", "Governance admin"],
    ];
    for (const [role, label] of cases) {
      const { unmount } = render(<RoleChip role={role} />);
      expect(screen.getByText(label)).toBeInTheDocument();
      unmount();
    }
  });

  it("shows Public when the role is null", () => {
    render(<RoleChip role={null} />);
    expect(screen.getByText("Public")).toBeInTheDocument();
  });

  it("shows Public when the role is an empty string", () => {
    render(<RoleChip role="" />);
    expect(screen.getByText("Public")).toBeInTheDocument();
  });

  it("turns underscores into spaces for a role it does not know", () => {
    render(<RoleChip role="auditor_lead" />);
    expect(screen.getByText("auditor lead")).toBeInTheDocument();
  });

  it("uses the reviewer tone for a reviewer", () => {
    render(<RoleChip role="reviewer" />);
    const chip = screen.getByText("Reviewer");
    expect(chip).toHaveClass("text-risk-clear");
    expect(chip).not.toHaveClass("text-risk-warn");
  });

  it("uses the operator tone for an operator", () => {
    render(<RoleChip role="operator" />);
    expect(screen.getByText("Operator")).toHaveClass("text-risk-warn");
  });

  it("uses the brand tone for a governance admin", () => {
    render(<RoleChip role="governance_admin" />);
    expect(screen.getByText("Governance admin")).toHaveClass("text-brand");
  });

  it("uses the viewer tone for a viewer", () => {
    render(<RoleChip role="viewer" />);
    expect(screen.getByText("Viewer")).toHaveClass("text-white/80");
  });

  it("uses the neutral fallback tone for an unknown role", () => {
    render(<RoleChip role="auditor_lead" />);
    const chip = screen.getByText("auditor lead");
    expect(chip).toHaveClass("text-dim");
    expect(chip).not.toHaveClass("text-brand");
  });

  it("uses the neutral fallback tone when the role is null", () => {
    render(<RoleChip role={null} />);
    expect(screen.getByText("Public")).toHaveClass("text-dim");
  });

  it("keeps the base chip classes on every chip", () => {
    render(<RoleChip role="viewer" />);
    const chip = screen.getByText("Viewer");
    expect(chip.tagName).toBe("SPAN");
    expect(chip).toHaveClass("inline-flex", "whitespace-nowrap", "rounded-md");
  });

  it("adds the caller's className to the chip", () => {
    render(<RoleChip role="viewer" className="custom-chip-class" />);
    expect(screen.getByText("Viewer")).toHaveClass("custom-chip-class");
  });
});
