import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useParams: () => ({ token: "signed.token" }) }));

import RespondPage from "./page";

/** What the shipper is told after an upload, from the API's answer (evidence.receive_evidence). */
async function uploadAndRead(answer: Record<string, unknown>) {
  globalThis.fetch = vi.fn(async () => Response.json(answer, { status: 201 })) as unknown as typeof fetch;
  const { container } = render(<RespondPage />);
  const input = container.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [new File(["%PDF"], "cert.pdf", { type: "application/pdf" })] } });
  fireEvent.click(screen.getByRole("button", { name: /^Upload/ }));
  return (await screen.findByText(/received/i)).textContent ?? "";
}

describe("the shipper's upload page (Rev2 N04)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("confirms a usable document", async () => {
    expect(await uploadAndRead({ received: true, usable: true, blocked: false, evidence_version: 2 }))
      .toMatch(/Document received \(version 2\)/);
  });

  it("asks for a clearer copy when the document could not be read", async () => {
    const text = await uploadAndRead({ received: true, usable: false, blocked: false, evidence_version: 2 });
    expect(text).toMatch(/could not be read/);
    expect(text).toMatch(/same link/);
    expect(text).not.toMatch(/Document received \(version/);
  });

  it("says a blocked document does not count and the link still works", async () => {
    const text = await uploadAndRead({ received: true, usable: false, blocked: true, evidence_version: 2 });
    expect(text).toMatch(/flagged/);
    expect(text).toMatch(/same link/);
  });
});
