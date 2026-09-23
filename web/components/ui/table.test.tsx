/**
 * No headless primitive here: the accessibility is the markup itself
 * (<table>, <th scope="col">). This holds that markup in place rather than
 * the styling, which nothing here asserts on.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

function Example() {
  return (
    <Table>
      <TableCaption>Sources connectées</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>Nom</TableHead>
          <TableHead>Statut</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        <TableRow>
          <TableCell>payment-api</TableCell>
          <TableCell>Synchronisé</TableCell>
        </TableRow>
      </TableBody>
    </Table>
  );
}

describe("Table", () => {
  it("renders one table, reachable by role, with its caption as the accessible name", () => {
    render(<Example />);
    expect(screen.getByRole("table", { name: "Sources connectées" })).toBeInTheDocument();
  });

  it("scopes every header to its column, so a screen reader can name a cell by it", () => {
    render(<Example />);
    for (const header of screen.getAllByRole("columnheader")) {
      expect(header).toHaveAttribute("scope", "col");
    }
  });

  it("puts the scrolling on a wrapper, never on the table itself", () => {
    const { container } = render(<Example />);
    const table = screen.getByRole("table");
    const wrapper = table.parentElement;
    expect(wrapper).toHaveAttribute("data-slot", "table-container");
    expect(wrapper).toHaveClass("overflow-x-auto");
    // The table itself must not repeat that class, or a wide row grows both
    // the wrapper's scrollbar and the table's own — two scrollbars for one
    // overflow, which is what this split exists to prevent.
    expect(table).not.toHaveClass("overflow-x-auto");
    expect(container.querySelectorAll('[data-slot="table-container"]')).toHaveLength(1);
  });

  it("keeps each row's cells reachable in reading order", () => {
    render(<Example />);
    const row = screen.getByRole("row", { name: "payment-api Synchronisé" });
    expect(row).toBeInTheDocument();
  });
});
