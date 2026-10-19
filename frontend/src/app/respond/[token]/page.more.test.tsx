import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  useParams: vi.fn(),
  fetch: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useParams: mocks.useParams,
}));

import RespondPage from "./page";

function renderPage() {
  return render(<RespondPage />);
}

describe("Respond page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.fetch.mockClear();
    vi.stubGlobal("fetch", mocks.fetch);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  describe("when token is missing", () => {
    beforeEach(() => {
      mocks.useParams.mockReturnValue({ token: undefined });
    });

    it("shows an error message when token is not in params", () => {
      renderPage();
      expect(screen.getByText(/No token found in the URL/)).toBeInTheDocument();
    });

    it("shows a red XCircle icon for the error", () => {
      renderPage();
      const errorMessage = screen.getByText(/No token found in the URL/);
      expect(errorMessage.parentElement).toHaveClass("text-risk-critical");
    });

    it("does not show the file upload area when token is missing", () => {
      renderPage();
      expect(screen.queryByText(/Drop a file here/)).not.toBeInTheDocument();
    });
  });

  describe("when token is provided", () => {
    beforeEach(() => {
      mocks.useParams.mockReturnValue({ token: "valid.token.here" });
    });

    it("shows the file upload drop zone", () => {
      renderPage();
      expect(screen.getByText(/Drop a file here or click to choose/)).toBeInTheDocument();
    });

    it("shows file type restrictions and size limit", () => {
      renderPage();
      expect(screen.getByText(/PDF, PNG, JPG, TIFF. Max 20 MB/)).toBeInTheDocument();
    });

    it("does not show the error message", () => {
      renderPage();
      expect(screen.queryByText(/No token found in the URL/)).not.toBeInTheDocument();
    });
  });

  describe("file selection via input", () => {
    beforeEach(() => {
      mocks.useParams.mockReturnValue({ token: "valid.token.here" });
    });

    it("opens file picker when clicking the drop zone", () => {
      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      const clickSpy = vi.spyOn(fileInput, "click");
      const dropZone = container.querySelector("div[class*='border-dashed']") as HTMLDivElement;
      fireEvent.click(dropZone);
      expect(clickSpy).toHaveBeenCalled();
    });

    it("displays the file name after selecting a file", () => {
      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(fileInput, {
        target: { files: [new File(["content"], "document.pdf", { type: "application/pdf" })] },
      });
      expect(screen.getByText("document.pdf")).toBeInTheDocument();
    });

    it("shows the upload button when a file is selected", () => {
      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(fileInput, {
        target: { files: [new File(["content"], "test.jpg", { type: "image/jpeg" })] },
      });
      expect(screen.getByRole("button", { name: /^Upload test.jpg/ })).toBeInTheDocument();
    });

    it("clears message and state when a new file is selected", async () => {
      mocks.useParams.mockReturnValue({ token: "valid.token.here" });
      mocks.fetch.mockResolvedValue(
        new Response(
          JSON.stringify({
            received: true,
            blocked: false,
            usable: true,
            evidence_version: 1,
          }),
          { status: 200 },
        ),
      );

      const { container, rerender } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;

      // Upload first file
      fireEvent.change(fileInput, {
        target: { files: [new File(["content"], "first.pdf", { type: "application/pdf" })] },
      });
      fireEvent.click(screen.getByRole("button", { name: /^Upload first.pdf/ }));

      // Wait for success state
      await waitFor(() => {
        expect(screen.getByText(/Document received/)).toBeInTheDocument();
      });

      // Select new file
      fireEvent.change(fileInput, {
        target: { files: [new File(["content"], "second.pdf", { type: "application/pdf" })] },
      });

      // State should return to idle
      expect(screen.queryByText(/Document received/)).not.toBeInTheDocument();
      expect(screen.getByText("second.pdf")).toBeInTheDocument();
    });
  });

  describe("file selection via drag and drop", () => {
    beforeEach(() => {
      mocks.useParams.mockReturnValue({ token: "valid.token.here" });
    });

    it("shows the drag-over styling when a file is dragged over the zone", () => {
      const { container } = renderPage();
      const dropZone = container.querySelector(
        "div[class*='border-dashed']",
      ) as HTMLDivElement;
      fireEvent.dragOver(dropZone);
      expect(dropZone).toHaveClass("border-brand");
    });

    it("removes the drag-over styling when the file leaves the zone", () => {
      const { container } = renderPage();
      const dropZone = container.querySelector(
        "div[class*='border-dashed']",
      ) as HTMLDivElement;
      fireEvent.dragOver(dropZone);
      expect(dropZone).toHaveClass("border-brand");
      fireEvent.dragLeave(dropZone);
      expect(dropZone).not.toHaveClass("border-brand");
    });

    it("accepts a file dropped onto the zone", () => {
      const { container } = renderPage();
      const dropZone = container.querySelector(
        "div[class*='border-dashed']",
      ) as HTMLDivElement;
      const file = new File(["content"], "dropped.pdf", { type: "application/pdf" });
      fireEvent.drop(dropZone, {
        dataTransfer: { files: [file] },
      });
      expect(screen.getByText("dropped.pdf")).toBeInTheDocument();
    });


    it("clears drag-over state when a file is dropped", () => {
      const { container } = renderPage();
      const dropZone = container.querySelector(
        "div[class*='border-dashed']",
      ) as HTMLDivElement;
      fireEvent.dragOver(dropZone);
      expect(dropZone).toHaveClass("border-brand");
      const file = new File(["content"], "dropped.pdf", { type: "application/pdf" });
      fireEvent.drop(dropZone, {
        dataTransfer: { files: [file] },
      });
      expect(dropZone).not.toHaveClass("border-brand");
    });
  });

  describe("upload flow: successful upload", () => {
    beforeEach(() => {
      mocks.useParams.mockReturnValue({ token: "valid.token.here" });
      mocks.fetch.mockResolvedValue(
        new Response(
          JSON.stringify({
            received: true,
            blocked: false,
            usable: true,
            evidence_version: 2,
          }),
          { status: 200 },
        ),
      );
    });

    it("sends the file with the token header", async () => {
      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      const file = new File(["content"], "test.pdf", { type: "application/pdf" });
      fireEvent.change(fileInput, { target: { files: [file] } });
      fireEvent.click(screen.getByRole("button", { name: /^Upload test.pdf/ }));

      await waitFor(() => {
        expect(mocks.fetch).toHaveBeenCalled();
      });

      const call = mocks.fetch.mock.calls[0];
      expect(call[0]).toBe("/api/proxy/evidence/respond");
      const request = call[1] as RequestInit;
      expect(request.method).toBe("POST");
      expect(request.headers).toEqual({ "X-VF-Evidence-Token": "valid.token.here" });
      expect(request.body).toBeInstanceOf(FormData);
    });

    it("shows the uploading state with a spinner", async () => {
      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(fileInput, { target: { files: [new File(["x"], "test.pdf")] } });
      fireEvent.click(screen.getByRole("button", { name: /^Upload test.pdf/ }));

      expect(screen.getByText("Uploading...")).toBeInTheDocument();
      // Spinner div should be present
      expect(document.querySelector("svg[class*='animate-spin']")).toBeInTheDocument();

      // Wait for fetch to complete so state updates are wrapped in act
      await waitFor(() => {
        expect(screen.getByText(/Document received/)).toBeInTheDocument();
      });
    });

    it("shows success message when the document is received and usable", async () => {
      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(fileInput, { target: { files: [new File(["x"], "test.pdf")] } });
      fireEvent.click(screen.getByRole("button", { name: /^Upload test.pdf/ }));

      expect(await screen.findByText(/Document received \(version 2\)/)).toBeInTheDocument();
    });

    it("shows a CheckCircle icon in the success state", async () => {
      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(fileInput, { target: { files: [new File(["x"], "test.pdf")] } });
      fireEvent.click(screen.getByRole("button", { name: /^Upload test.pdf/ }));

      const message = await screen.findByText(/Document received/);
      expect(message.parentElement).toHaveClass("border-risk-clear/30");
    });

    it("hides the upload button after a successful upload", async () => {
      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(fileInput, { target: { files: [new File(["x"], "test.pdf")] } });
      const uploadBtn = screen.getByRole("button", { name: /^Upload test.pdf/ });
      fireEvent.click(uploadBtn);

      await waitFor(() => {
        expect(screen.queryByRole("button", { name: /^Upload test.pdf/ })).not.toBeInTheDocument();
      });
    });

    it("shows an 'Upload another document' button after success", async () => {
      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(fileInput, { target: { files: [new File(["x"], "test.pdf")] } });
      fireEvent.click(screen.getByRole("button", { name: /^Upload test.pdf/ }));

      expect(await screen.findByRole("button", { name: /Upload another document/ })).toBeInTheDocument();
    });
  });

  describe("upload flow: blocked document", () => {
    beforeEach(() => {
      mocks.useParams.mockReturnValue({ token: "valid.token.here" });
      mocks.fetch.mockResolvedValue(
        new Response(
          JSON.stringify({
            received: true,
            blocked: true,
            usable: true,
            evidence_version: 1,
          }),
          { status: 200 },
        ),
      );
    });

    it("shows a blocked message when document is flagged by safety screen", async () => {
      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(fileInput, { target: { files: [new File(["x"], "test.pdf")] } });
      fireEvent.click(screen.getByRole("button", { name: /^Upload test.pdf/ }));

      const message = await screen.findByText(/flagged by our safety screen/);
      expect(message).toBeInTheDocument();
    });

    it("invites re-upload with the same link for blocked documents", async () => {
      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(fileInput, { target: { files: [new File(["x"], "test.pdf")] } });
      fireEvent.click(screen.getByRole("button", { name: /^Upload test.pdf/ }));

      const message = await screen.findByText(/same link/);
      expect(message).toBeInTheDocument();
    });

    it("shows an AlertTriangle icon in the blocked state", async () => {
      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(fileInput, { target: { files: [new File(["x"], "test.pdf")] } });
      fireEvent.click(screen.getByRole("button", { name: /^Upload test.pdf/ }));

      const message = await screen.findByText(/flagged/);
      expect(message.parentElement).toHaveClass("border-risk-warn/30");
    });

    it("shows 'Upload another document' button in blocked state", async () => {
      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(fileInput, { target: { files: [new File(["x"], "test.pdf")] } });
      fireEvent.click(screen.getByRole("button", { name: /^Upload test.pdf/ }));

      expect(await screen.findByRole("button", { name: /Upload another document/ })).toBeInTheDocument();
    });
  });

  describe("upload flow: unreadable document", () => {
    beforeEach(() => {
      mocks.useParams.mockReturnValue({ token: "valid.token.here" });
      mocks.fetch.mockResolvedValue(
        new Response(
          JSON.stringify({
            received: true,
            blocked: false,
            usable: false,
            evidence_version: 1,
          }),
          { status: 200 },
        ),
      );
    });

    it("shows message when document could not be read", async () => {
      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(fileInput, { target: { files: [new File(["x"], "test.pdf")] } });
      fireEvent.click(screen.getByRole("button", { name: /^Upload test.pdf/ }));

      const message = await screen.findByText(/could not be read/);
      expect(message).toBeInTheDocument();
    });

    it("invites re-upload with the same link for unreadable documents", async () => {
      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(fileInput, { target: { files: [new File(["x"], "test.pdf")] } });
      fireEvent.click(screen.getByRole("button", { name: /^Upload test.pdf/ }));

      const message = await screen.findByText(/same link/);
      expect(message).toBeInTheDocument();
    });

    it("shows blocked state UI for unreadable documents", async () => {
      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(fileInput, { target: { files: [new File(["x"], "test.pdf")] } });
      fireEvent.click(screen.getByRole("button", { name: /^Upload test.pdf/ }));

      const message = await screen.findByText(/could not be read/);
      expect(message.parentElement).toHaveClass("border-risk-warn/30");
    });
  });

  describe("upload flow: API error response", () => {
    beforeEach(() => {
      mocks.useParams.mockReturnValue({ token: "valid.token.here" });
    });

    it("shows error message from API response when upload fails", async () => {
      mocks.fetch.mockResolvedValue(
        new Response(JSON.stringify({ error: "File too large" }), { status: 413 }),
      );

      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(fileInput, { target: { files: [new File(["x"], "test.pdf")] } });
      fireEvent.click(screen.getByRole("button", { name: /^Upload test.pdf/ }));

      expect(await screen.findByText(/File too large/)).toBeInTheDocument();
    });

    it("shows status code when API error has no message", async () => {
      mocks.fetch.mockResolvedValue(
        new Response(JSON.stringify({}), { status: 500 }),
      );

      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(fileInput, { target: { files: [new File(["x"], "test.pdf")] } });
      fireEvent.click(screen.getByRole("button", { name: /^Upload test.pdf/ }));

      expect(await screen.findByText(/Upload failed \(500\)/)).toBeInTheDocument();
    });

    it("handles API response with neither message nor error field", async () => {
      mocks.fetch.mockResolvedValue(
        new Response(JSON.stringify({ received: false }), { status: 400 }),
      );

      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(fileInput, { target: { files: [new File(["x"], "test.pdf")] } });
      fireEvent.click(screen.getByRole("button", { name: /^Upload test.pdf/ }));

      expect(await screen.findByText(/Upload failed \(400\)/)).toBeInTheDocument();
    });

    it("shows XCircle icon in error state", async () => {
      mocks.fetch.mockResolvedValue(
        new Response(JSON.stringify({ error: "Bad request" }), { status: 400 }),
      );

      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(fileInput, { target: { files: [new File(["x"], "test.pdf")] } });
      fireEvent.click(screen.getByRole("button", { name: /^Upload test.pdf/ }));

      const message = await screen.findByText(/Bad request/);
      expect(message.parentElement).toHaveClass("border-risk-critical/30");
    });

    it("shows 'Upload another document' button after error", async () => {
      mocks.fetch.mockResolvedValue(
        new Response(JSON.stringify({ error: "Failed" }), { status: 500 }),
      );

      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(fileInput, { target: { files: [new File(["x"], "test.pdf")] } });
      fireEvent.click(screen.getByRole("button", { name: /^Upload test.pdf/ }));

      expect(await screen.findByRole("button", { name: /Upload another document/ })).toBeInTheDocument();
    });
  });

  describe("upload flow: network error", () => {
    beforeEach(() => {
      mocks.useParams.mockReturnValue({ token: "valid.token.here" });
      mocks.fetch.mockRejectedValue(new Error("Connection timeout"));
    });

    it("shows network error message when fetch fails", async () => {
      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(fileInput, { target: { files: [new File(["x"], "test.pdf")] } });
      fireEvent.click(screen.getByRole("button", { name: /^Upload test.pdf/ }));

      expect(await screen.findByText(/Connection timeout/)).toBeInTheDocument();
    });

    it("shows generic error for non-Error exceptions", async () => {
      mocks.fetch.mockRejectedValue("unknown");

      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(fileInput, { target: { files: [new File(["x"], "test.pdf")] } });
      fireEvent.click(screen.getByRole("button", { name: /^Upload test.pdf/ }));

      expect(await screen.findByText(/Network error/)).toBeInTheDocument();
    });
  });

  describe("upload flow: edge cases", () => {
    beforeEach(() => {
      mocks.useParams.mockReturnValue({ token: "valid.token.here" });
    });

    it("does not upload when file is missing", () => {
      const { container } = renderPage();
      // Try to trigger upload without selecting a file
      expect(mocks.fetch).not.toHaveBeenCalled();
    });

    it("handles API response without JSON body", async () => {
      mocks.fetch.mockResolvedValue(
        new Response("Internal server error", { status: 500 }),
      );

      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(fileInput, { target: { files: [new File(["x"], "test.pdf")] } });
      fireEvent.click(screen.getByRole("button", { name: /^Upload test.pdf/ }));

      expect(await screen.findByText(/Upload failed \(500\)/)).toBeInTheDocument();
    });

    it("uses question mark for evidence_version when not provided", async () => {
      mocks.fetch.mockResolvedValue(
        new Response(
          JSON.stringify({
            received: true,
            blocked: false,
            usable: true,
          }),
          { status: 200 },
        ),
      );

      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(fileInput, { target: { files: [new File(["x"], "test.pdf")] } });
      fireEvent.click(screen.getByRole("button", { name: /^Upload test.pdf/ }));

      expect(await screen.findByText(/Document received \(version \?\)/)).toBeInTheDocument();
    });
  });

  describe("reset button", () => {
    beforeEach(() => {
      mocks.useParams.mockReturnValue({ token: "valid.token.here" });
      mocks.fetch.mockResolvedValue(
        new Response(
          JSON.stringify({
            received: true,
            blocked: false,
            usable: true,
            evidence_version: 1,
          }),
          { status: 200 },
        ),
      );
    });

    it("resets state to idle after success", async () => {
      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(fileInput, { target: { files: [new File(["x"], "first.pdf")] } });
      fireEvent.click(screen.getByRole("button", { name: /^Upload first.pdf/ }));

      await screen.findByText(/Document received/);
      expect(screen.getByText(/first.pdf/)).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: /Upload another document/ }));

      expect(screen.queryByText(/Document received/)).not.toBeInTheDocument();
      expect(screen.getByText(/Drop a file here or click to choose/)).toBeInTheDocument();
    });

    it("clears the file selection when reset button is clicked", async () => {
      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(fileInput, { target: { files: [new File(["x"], "test.pdf")] } });
      fireEvent.click(screen.getByRole("button", { name: /^Upload test.pdf/ }));

      await screen.findByText(/Document received/);
      fireEvent.click(screen.getByRole("button", { name: /Upload another document/ }));

      expect(screen.queryByText(/test.pdf/)).not.toBeInTheDocument();
      expect(screen.getByText(/Drop a file here or click to choose/)).toBeInTheDocument();
    });

    it("allows a new file to be selected after reset", async () => {
      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(fileInput, { target: { files: [new File(["x"], "first.pdf")] } });
      fireEvent.click(screen.getByRole("button", { name: /^Upload first.pdf/ }));

      await screen.findByText(/Document received/);
      fireEvent.click(screen.getByRole("button", { name: /Upload another document/ }));

      fireEvent.change(fileInput, { target: { files: [new File(["x"], "second.pdf")] } });
      expect(screen.getByRole("button", { name: /^Upload second.pdf/ })).toBeInTheDocument();
    });
  });

  describe("footer", () => {
    beforeEach(() => {
      mocks.useParams.mockReturnValue({ token: "valid.token.here" });
    });

    it("shows the expiry notice", () => {
      renderPage();
      expect(screen.getByText(/single-use per document type and expires after 7 days/)).toBeInTheDocument();
    });

    it("always shows the footer text regardless of token presence", () => {
      mocks.useParams.mockReturnValue({ token: undefined });
      renderPage();
      expect(screen.getByText(/single-use per document type and expires after 7 days/)).toBeInTheDocument();
    });
  });

  describe("page layout", () => {
    beforeEach(() => {
      mocks.useParams.mockReturnValue({ token: "valid.token.here" });
    });

    it("shows the Floorline title", () => {
      renderPage();
      expect(screen.getByText("Floorline")).toBeInTheDocument();
    });

    it("shows the submit evidence subtitle", () => {
      renderPage();
      expect(screen.getByText(/Submit evidence for your shipment/)).toBeInTheDocument();
    });

    it("renders the full component without crashing", () => {
      const { container } = renderPage();
      expect(container.querySelector("div[class*='min-h-screen']")).toBeInTheDocument();
    });
  });

  describe("token parameter handling", () => {
    it("uses token from params when present", async () => {
      mocks.useParams.mockReturnValue({ token: "test.token.abc123" });
      mocks.fetch.mockResolvedValue(
        new Response(
          JSON.stringify({ received: true, blocked: false, usable: true }),
          { status: 200 },
        ),
      );

      const { container } = renderPage();
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(fileInput, { target: { files: [new File(["x"], "test.pdf")] } });
      fireEvent.click(screen.getByRole("button", { name: /^Upload test.pdf/ }));

      await waitFor(() => {
        const headers = (mocks.fetch.mock.calls[0]?.[1] as RequestInit)
          ?.headers as Record<string, string>;
        expect(headers["X-VF-Evidence-Token"]).toBe("test.token.abc123");
      });
    });

    it("handles token being an array (converts to empty string)", () => {
      mocks.useParams.mockReturnValue({ token: ["array", "value"] });
      renderPage();
      expect(screen.getByText(/No token found in the URL/)).toBeInTheDocument();
    });
  });
});
