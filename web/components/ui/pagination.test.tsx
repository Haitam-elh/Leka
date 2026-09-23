/**
 * The API is cursor-based (docs/api.md): no page number, no total, no way
 * back without having kept the cursor yourself. What must hold regardless
 * of how a caller wires it up: the landmark is announced, Previous/Next
 * are reachable by their name rather than by an icon alone, and a side
 * with nothing behind it is disabled rather than silently doing nothing.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination";

describe("Pagination", () => {
  it("is a named landmark, distinguishable from every other nav on the page", () => {
    render(<Pagination />);
    expect(screen.getByRole("navigation", { name: "Pagination" })).toBeInTheDocument();
  });

  it("Previous and Next are reachable by name, not by their icon alone", () => {
    render(
      <Pagination>
        <PaginationContent>
          <PaginationItem>
            <PaginationPrevious />
          </PaginationItem>
          <PaginationItem>
            <PaginationNext />
          </PaginationItem>
        </PaginationContent>
      </Pagination>
    );

    expect(screen.getByRole("button", { name: "Précédent" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Suivant" })).toBeInTheDocument();
  });

  it("disables the side that has no cursor behind it, and calls back on the side that does", async () => {
    const user = userEvent.setup();
    const onNext = vi.fn();

    render(
      <Pagination>
        <PaginationContent>
          <PaginationItem>
            <PaginationPrevious disabled />
          </PaginationItem>
          <PaginationItem>
            <PaginationNext onClick={onNext} />
          </PaginationItem>
        </PaginationContent>
      </Pagination>
    );

    expect(screen.getByRole("button", { name: "Précédent" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Suivant" }));
    expect(onNext).toHaveBeenCalledOnce();
  });

  it("marks the active page with aria-current, for the rarer fully-known list", () => {
    render(
      <Pagination>
        <PaginationContent>
          <PaginationItem>
            <PaginationLink href="#" isActive>
              1
            </PaginationLink>
          </PaginationItem>
          <PaginationItem>
            <PaginationLink href="#">2</PaginationLink>
          </PaginationItem>
        </PaginationContent>
      </Pagination>
    );

    expect(screen.getByRole("link", { name: "1" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "2" })).not.toHaveAttribute("aria-current");
  });
});
