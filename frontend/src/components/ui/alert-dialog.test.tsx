import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogMedia,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "./alert-dialog";

function DeleteDialog({
  onConfirm,
  size,
}: {
  onConfirm?: () => void;
  size?: "default" | "sm";
}) {
  return (
    <AlertDialog>
      <AlertDialogTrigger>Delete file</AlertDialogTrigger>
      <AlertDialogContent size={size}>
        <AlertDialogHeader>
          <AlertDialogMedia>icon</AlertDialogMedia>
          <AlertDialogTitle>Delete this file?</AlertDialogTitle>
          <AlertDialogDescription>This cannot be undone.</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Keep</AlertDialogCancel>
          <AlertDialogAction onClick={onConfirm}>Delete</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function openDeleteDialog(props: { onConfirm?: () => void; size?: "default" | "sm" } = {}) {
  render(<DeleteDialog {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "Delete file" }));
  return screen.getByRole("alertdialog", { name: "Delete this file?" });
}

describe("AlertDialog", () => {
  it("stays closed until the trigger is clicked", () => {
    render(<DeleteDialog />);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Delete file" }));

    expect(screen.getByRole("alertdialog", { name: "Delete this file?" })).toBeInTheDocument();
  });

  it("shows the description inside the open dialog", () => {
    const dialog = openDeleteDialog();
    expect(dialog).toHaveTextContent("This cannot be undone.");
  });

  it("opens immediately when open is true and reports dismissal through onOpenChange", () => {
    const onOpenChange = vi.fn();
    render(
      <AlertDialog open onOpenChange={onOpenChange}>
        <AlertDialogContent>
          <AlertDialogTitle>Controlled</AlertDialogTitle>
          <AlertDialogDescription>Controlled body</AlertDialogDescription>
          <AlertDialogFooter>
            <AlertDialogCancel>Back</AlertDialogCancel>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>,
    );

    expect(screen.getByRole("alertdialog", { name: "Controlled" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Back" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("closes without running the action when Cancel is clicked", async () => {
    const onConfirm = vi.fn();
    openDeleteDialog({ onConfirm });

    fireEvent.click(screen.getByRole("button", { name: "Keep" }));

    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("runs the action handler once and closes when Action is clicked", async () => {
    const onConfirm = vi.fn();
    openDeleteDialog({ onConfirm });

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(onConfirm).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  });

  it("closes when the Escape key is pressed", async () => {
    openDeleteDialog();

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  });

  it("renders the overlay behind an open dialog", () => {
    openDeleteDialog();
    const overlay = document.querySelector('[data-slot="alert-dialog-overlay"]');
    expect(overlay).not.toBeNull();
    expect(overlay).toHaveClass("bg-black/10");
  });

  it("tags the trigger with its data-slot", () => {
    render(<DeleteDialog />);
    expect(screen.getByRole("button", { name: "Delete file" })).toHaveAttribute(
      "data-slot",
      "alert-dialog-trigger",
    );
  });

  it("tags the content with the default size when no size is given", () => {
    const dialog = openDeleteDialog();
    expect(dialog).toHaveAttribute("data-slot", "alert-dialog-content");
    expect(dialog).toHaveAttribute("data-size", "default");
  });

  it("passes the sm size through to the content", () => {
    const dialog = openDeleteDialog({ size: "sm" });
    expect(dialog).toHaveAttribute("data-size", "sm");
  });

  it("merges a custom className into the content", () => {
    render(
      <AlertDialog open>
        <AlertDialogContent className="custom-content">
          <AlertDialogTitle>Styled</AlertDialogTitle>
          <AlertDialogDescription>Styled body</AlertDialogDescription>
        </AlertDialogContent>
      </AlertDialog>,
    );
    expect(screen.getByRole("alertdialog", { name: "Styled" })).toHaveClass("custom-content");
  });

  it("tags the header, title, media and description with their data-slot", () => {
    openDeleteDialog();
    expect(screen.getByText("Delete this file?").closest('[data-slot="alert-dialog-header"]')).not.toBeNull();
    expect(screen.getByText("Delete this file?")).toHaveAttribute("data-slot", "alert-dialog-title");
    expect(screen.getByText("icon")).toHaveAttribute("data-slot", "alert-dialog-media");
    expect(screen.getByText("This cannot be undone.")).toHaveAttribute(
      "data-slot",
      "alert-dialog-description",
    );
  });

  it("merges a custom className into the header and footer", () => {
    render(
      <AlertDialog open>
        <AlertDialogContent>
          <AlertDialogHeader className="header-extra">
            <AlertDialogTitle>Layout</AlertDialogTitle>
          </AlertDialogHeader>
          <AlertDialogFooter className="footer-extra">
            <AlertDialogCancel>Close</AlertDialogCancel>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>,
    );
    expect(screen.getByText("Layout").closest("[data-slot=alert-dialog-header]")).toHaveClass(
      "header-extra",
    );
    expect(screen.getByRole("button", { name: "Close" }).closest("[data-slot=alert-dialog-footer]")).toHaveClass(
      "footer-extra",
    );
  });

  it("gives Cancel the outline variant and Action the default variant", () => {
    openDeleteDialog();
    expect(screen.getByRole("button", { name: "Keep" })).toHaveAttribute("data-variant", "outline");
    expect(screen.getByRole("button", { name: "Delete" })).toHaveAttribute("data-variant", "default");
  });

  it("tags Cancel and Action with their data-slot", () => {
    openDeleteDialog();
    expect(screen.getByRole("button", { name: "Keep" })).toHaveAttribute(
      "data-slot",
      "alert-dialog-cancel",
    );
    expect(screen.getByRole("button", { name: "Delete" })).toHaveAttribute(
      "data-slot",
      "alert-dialog-action",
    );
  });

  it("applies a destructive variant and sm size to Action when given", () => {
    render(
      <AlertDialog open>
        <AlertDialogContent>
          <AlertDialogTitle>Danger</AlertDialogTitle>
          <AlertDialogDescription>Danger body</AlertDialogDescription>
          <AlertDialogAction variant="destructive" size="sm">
            Wipe
          </AlertDialogAction>
        </AlertDialogContent>
      </AlertDialog>,
    );
    const wipe = screen.getByRole("button", { name: "Wipe" });
    expect(wipe).toHaveAttribute("data-variant", "destructive");
    expect(wipe).toHaveAttribute("data-size", "sm");
  });

  it("merges a custom className into Cancel", () => {
    render(
      <AlertDialog open>
        <AlertDialogContent>
          <AlertDialogTitle>Cancel style</AlertDialogTitle>
          <AlertDialogDescription>Cancel style body</AlertDialogDescription>
          <AlertDialogCancel className="cancel-extra">Nope</AlertDialogCancel>
        </AlertDialogContent>
      </AlertDialog>,
    );
    expect(screen.getByRole("button", { name: "Nope" })).toHaveClass("cancel-extra");
  });
});
