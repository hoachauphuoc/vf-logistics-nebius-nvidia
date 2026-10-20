import { fireEvent, render, screen } from "@testing-library/react";
import { Tooltip as TooltipPrimitive } from "radix-ui";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { type Identity, TenantChoiceRequired } from "@/lib/identity";
import type { Tenant } from "@/lib/types";

// The hooks are replaced so each test sets exactly the state one branch of the switcher reads.
const mocks = vi.hoisted(() => ({
  setTenantId: vi.fn(),
  chooseTenant: vi.fn(),
  tenant: { id: "", name: "", descriptor: "" } as Tenant,
  tenants: [] as Tenant[],
  canSwitch: false,
  identity: undefined as Identity | undefined,
  pending: null as TenantChoiceRequired | null,
}));

vi.mock("@/lib/tenant-context", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/tenant-context")>()),
  useTenant: () => ({
    tenant: mocks.tenant,
    tenants: mocks.tenants,
    canSwitch: mocks.canSwitch,
    setTenantId: mocks.setTenantId,
  }),
}));
vi.mock("@/lib/identity", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/identity")>()),
  useIdentity: () => ({ data: mocks.identity }),
  useTenantChoice: () => mocks.pending,
}));
vi.mock("@/lib/tenant-choice", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/tenant-choice")>()),
  chooseTenant: mocks.chooseTenant,
}));

import { TenantSwitcher } from "./TenantSwitcher";

beforeAll(() => {
  // Radix Select asks for these; jsdom does not implement them.
  Element.prototype.hasPointerCapture ??= () => false;
  Element.prototype.releasePointerCapture ??= () => {};
  Element.prototype.scrollIntoView ??= () => {};
});

const ACME: Tenant = { id: "acme", name: "Acme Freight", descriptor: "Bound to your session" };

function identityWith(memberships: Record<string, Identity["role"]> | null | undefined): Identity {
  return {
    email: "a@acme.com",
    authenticated_by: "console_session",
    acts_for_a_person: true,
    role: "operator",
    roles: ["operator"],
    grants: ["viewer", "reviewer", "operator"],
    role_source: "VF_TENANT_MEMBERS",
    tenant_id: "acme",
    memberships,
  };
}

function renderSwitcher(display?: Tenant) {
  return render(
    <TooltipPrimitive.Provider>
      <TenantSwitcher display={display} />
    </TooltipPrimitive.Provider>,
  );
}

describe("TenantSwitcher: a read-only organisation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.tenant = ACME;
    mocks.tenants = [ACME];
    mocks.canSwitch = false;
    mocks.identity = identityWith({ acme: "operator" });
    mocks.pending = null;
  });

  it("shows the organisation and its descriptor, with no selector", () => {
    renderSwitcher();
    expect(screen.getByText("Acme Freight")).toBeInTheDocument();
    expect(screen.getByText("Bound to your session")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("derives the initials of the first two words for the mark", () => {
    mocks.tenant = { id: "x", name: "Acme Freight Lines", descriptor: "d" };
    renderSwitcher();
    expect(screen.getByText("AF")).toBeInTheDocument();
    expect(screen.queryByText("AFL")).toBeNull();
  });

  it("shows the display organisation in place of the selected one", () => {
    renderSwitcher({ id: "live", name: "Live Co", descriptor: "From the API" });
    expect(screen.getByText("Live Co")).toBeInTheDocument();
    expect(screen.getByText("From the API")).toBeInTheDocument();
    expect(screen.queryByText("Acme Freight")).toBeNull();
  });

  it("stays read-only while the identity is still loading", () => {
    mocks.identity = undefined;
    renderSwitcher();
    expect(screen.getByText("Acme Freight")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("stays read-only when the person has exactly one membership", () => {
    mocks.identity = identityWith({ acme: "operator" });
    renderSwitcher();
    expect(screen.queryByLabelText("Switch organisation")).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("stays read-only when memberships are not reported", () => {
    mocks.identity = identityWith(null);
    renderSwitcher();
    expect(screen.queryByLabelText("Switch organisation")).toBeNull();
    expect(screen.getByText("Acme Freight")).toBeInTheDocument();
  });
});

describe("TenantSwitcher: the API is waiting for an organisation choice", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.tenant = { id: "", name: "", descriptor: "" };
    mocks.tenants = [];
    mocks.canSwitch = false;
    mocks.identity = undefined;
    mocks.pending = null;
  });

  it("offers the choices and counts them", () => {
    mocks.pending = new TenantChoiceRequired("tenant_choice_required", ["acme", "beta-shipping"]);
    renderSwitcher();
    expect(screen.getByLabelText("Choose organisation")).toBeInTheDocument();
    expect(screen.getByText("Choose an organisation")).toBeInTheDocument();
    expect(screen.getByText("2 available to you")).toBeInTheDocument();
  });

  it("says a previous choice is no longer available when the reason is not a first sign-in", () => {
    mocks.pending = new TenantChoiceRequired("not_member_of_requested", ["acme"]);
    renderSwitcher();
    expect(screen.getByText("Your previous choice is not available")).toBeInTheDocument();
    expect(screen.queryByText(/available to you/)).toBeNull();
  });

  it("passes the picked organisation to chooseTenant", async () => {
    mocks.pending = new TenantChoiceRequired("tenant_choice_required", ["acme", "beta-shipping"]);
    renderSwitcher();
    fireEvent.pointerDown(screen.getByLabelText("Choose organisation"), {
      button: 0,
      ctrlKey: false,
      pointerType: "mouse",
    });
    fireEvent.click(await screen.findByRole("option", { name: /beta-shipping/ }));
    expect(mocks.chooseTenant).toHaveBeenCalledWith("beta-shipping");
  });

  it("ignores a pending choice when the organisations are switchable here", () => {
    mocks.pending = new TenantChoiceRequired("tenant_choice_required", ["acme"]);
    mocks.canSwitch = true;
    mocks.tenant = ACME;
    mocks.tenants = [ACME];
    renderSwitcher();
    expect(screen.getByLabelText("Select organisation")).toBeInTheDocument();
    expect(screen.queryByLabelText("Choose organisation")).toBeNull();
  });
});

describe("TenantSwitcher: one person, several organisations", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.tenant = ACME;
    mocks.tenants = [ACME];
    mocks.canSwitch = false;
    mocks.identity = identityWith({ acme: "operator", "beta-shipping": "viewer" });
    mocks.pending = null;
  });

  it("shows the current organisation, the role here and the number of organisations", () => {
    renderSwitcher();
    expect(screen.getByLabelText("Switch organisation")).toBeInTheDocument();
    expect(screen.getByText("Acme Freight")).toBeInTheDocument();
    expect(screen.getByText("Operator here · 2 organisations")).toBeInTheDocument();
  });

  it("lists each membership with the role held in it", async () => {
    renderSwitcher();
    fireEvent.pointerDown(screen.getByLabelText("Switch organisation"), {
      button: 0,
      ctrlKey: false,
      pointerType: "mouse",
    });
    expect(await screen.findByRole("option", { name: /beta-shipping/ })).toHaveTextContent("Viewer");
    expect(screen.getByRole("option", { name: /acme/ })).toHaveTextContent("Operator");
  });

  it("passes the picked membership to chooseTenant", async () => {
    renderSwitcher();
    fireEvent.pointerDown(screen.getByLabelText("Switch organisation"), {
      button: 0,
      ctrlKey: false,
      pointerType: "mouse",
    });
    fireEvent.click(await screen.findByRole("option", { name: /beta-shipping/ }));
    expect(mocks.chooseTenant).toHaveBeenCalledWith("beta-shipping");
    expect(mocks.setTenantId).not.toHaveBeenCalled();
  });
});

describe("TenantSwitcher: demo organisations that can be switched", () => {
  const ALPHA: Tenant = { id: "a", name: "Alpha Co", descriptor: "Demo A" };
  const BETA: Tenant = { id: "b", name: "Beta Ltd", descriptor: "Demo B" };

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.tenant = ALPHA;
    mocks.tenants = [ALPHA, BETA];
    mocks.canSwitch = true;
    mocks.identity = undefined;
    mocks.pending = null;
  });

  it("shows the selected organisation and its descriptor in a selector", () => {
    renderSwitcher();
    expect(screen.getByLabelText("Select organisation")).toBeInTheDocument();
    expect(screen.getByText("Alpha Co")).toBeInTheDocument();
    expect(screen.getByText("Demo A")).toBeInTheDocument();
  });

  it("lists every organisation when opened", async () => {
    renderSwitcher();
    fireEvent.pointerDown(screen.getByLabelText("Select organisation"), {
      button: 0,
      ctrlKey: false,
      pointerType: "mouse",
    });
    expect(await screen.findByRole("option", { name: /Alpha Co/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Beta Ltd/ })).toBeInTheDocument();
  });

  it("selects the picked organisation through setTenantId", async () => {
    renderSwitcher();
    fireEvent.pointerDown(screen.getByLabelText("Select organisation"), {
      button: 0,
      ctrlKey: false,
      pointerType: "mouse",
    });
    fireEvent.click(await screen.findByRole("option", { name: /Beta Ltd/ }));
    expect(mocks.setTenantId).toHaveBeenCalledWith("b");
    expect(mocks.chooseTenant).not.toHaveBeenCalled();
  });
});
