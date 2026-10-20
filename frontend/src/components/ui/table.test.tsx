import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "./table";

describe("Table", () => {
  it("renders a real table element inside a horizontally scrollable container", () => {
    const { container } = render(
      <Table>
        <TableBody />
      </Table>
    );

    const wrapper = container.querySelector('[data-slot="table-container"]');
    expect(wrapper).toHaveClass("overflow-x-auto");
    expect(wrapper?.querySelector("table")).toBe(screen.getByRole("table"));
  });

  it("keeps the caller's className next to the default table classes", () => {
    render(
      <Table className="custom-table">
        <TableBody />
      </Table>
    );

    const table = screen.getByRole("table");
    expect(table).toHaveClass("custom-table");
    expect(table).toHaveClass("w-full");
  });

  it("passes extra table attributes through to the table element", () => {
    render(
      <Table aria-label="Shipments">
        <TableBody />
      </Table>
    );

    expect(screen.getByRole("table", { name: "Shipments" })).toBeInTheDocument();
  });

  it("renders header, body and footer sections with their slots", () => {
    const { container } = render(
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Case</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow>
            <TableCell>CASE-1</TableCell>
          </TableRow>
        </TableBody>
        <TableFooter>
          <TableRow>
            <TableCell>Total 1</TableCell>
          </TableRow>
        </TableFooter>
      </Table>
    );

    expect(container.querySelector('thead[data-slot="table-header"]')).toBeInTheDocument();
    expect(container.querySelector('tbody[data-slot="table-body"]')).toBeInTheDocument();
    expect(container.querySelector('tfoot[data-slot="table-footer"]')).toBeInTheDocument();
    expect(screen.getByText("CASE-1")).toBeInTheDocument();
    expect(screen.getByText("Total 1")).toBeInTheDocument();
  });

  it("gives the footer its top border and muted background", () => {
    const { container } = render(
      <Table>
        <TableFooter>
          <TableRow>
            <TableCell>Sum</TableCell>
          </TableRow>
        </TableFooter>
      </Table>
    );

    const footer = container.querySelector('[data-slot="table-footer"]');
    expect(footer).toHaveClass("border-t", "bg-muted/50", "font-medium");
  });

  it("marks header cells as column headers and body cells as cells", () => {
    render(
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Risk</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow>
            <TableCell>High</TableCell>
          </TableRow>
        </TableBody>
      </Table>
    );

    expect(screen.getByRole("columnheader", { name: "Risk" })).toHaveAttribute(
      "data-slot",
      "table-head"
    );
    expect(screen.getByRole("cell", { name: "High" })).toHaveAttribute(
      "data-slot",
      "table-cell"
    );
  });

  it("keeps a row's selected state and custom attributes on the tr element", () => {
    render(
      <Table>
        <TableBody>
          <TableRow data-state="selected" className="custom-row">
            <TableCell>Selected case</TableCell>
          </TableRow>
        </TableBody>
      </Table>
    );

    const row = screen.getByRole("row");
    expect(row).toHaveAttribute("data-state", "selected");
    expect(row).toHaveAttribute("data-slot", "table-row");
    expect(row).toHaveClass("custom-row", "border-b");
  });

  it("lets a cell's className extend the default cell classes", () => {
    render(
      <Table>
        <TableBody>
          <TableRow>
            <TableCell className="custom-cell">Amount</TableCell>
          </TableRow>
        </TableBody>
      </Table>
    );

    const cell = screen.getByRole("cell", { name: "Amount" });
    expect(cell).toHaveClass("custom-cell", "p-2", "align-middle");
  });

  it("lets a head cell's className extend the default head classes", () => {
    render(
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="custom-head">Origin</TableHead>
          </TableRow>
        </TableHeader>
      </Table>
    );

    const head = screen.getByRole("columnheader", { name: "Origin" });
    expect(head).toHaveClass("custom-head", "h-10", "text-left");
  });

  it("renders a caption with its text and muted style", () => {
    render(
      <Table>
        <TableCaption className="custom-caption">Recent shipments</TableCaption>
        <TableBody />
      </Table>
    );

    const caption = screen.getByText("Recent shipments");
    expect(caption.tagName).toBe("CAPTION");
    expect(caption).toHaveAttribute("data-slot", "table-caption");
    expect(caption).toHaveClass("custom-caption", "text-muted-foreground");
  });

  it("renders an empty body without any rows", () => {
    render(
      <Table>
        <TableBody />
      </Table>
    );

    expect(screen.queryByRole("row")).not.toBeInTheDocument();
  });

  it("renders a populated table with one row per record", () => {
    const records = [
      { id: "A-1", status: "Released" },
      { id: "A-2", status: "Held" },
    ];

    render(
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>ID</TableHead>
            <TableHead>Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {records.map((record) => (
            <TableRow key={record.id}>
              <TableCell>{record.id}</TableCell>
              <TableCell>{record.status}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    );

    expect(screen.getAllByRole("row")).toHaveLength(3);
    expect(screen.getByRole("cell", { name: "A-2" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Held" })).toBeInTheDocument();
  });
});
