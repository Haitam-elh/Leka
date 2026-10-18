import * as React from "react"
import { ChevronLeftIcon, ChevronRightIcon, MoreHorizontalIcon } from "lucide-react"
import { cn } from "cn"

import { Button, buttonVariants } from "@/components/ui/button"

// THE API IS CURSOR-BASED, ON PURPOSE — see docs/api.md. A list route
// returns { data, next_cursor } and nothing else: no page number, no total,
// no way to jump to "page 4" or to ask for the page before this one without
// having kept its cursor yourself. That is deliberate — a page number is an
// OFFSET, and a row inserted while someone is reading shifts every offset
// after it, showing one row twice or skipping one.
//
// So this primitive is presentational only, same as Table: it does not know
// what a "page" is here, and a caller wiring it to a cursor-paged list uses
// PaginationPrevious/PaginationNext, disabling whichever side it does not
// have a cursor for, and keeps its own stack of visited cursors if it wants
// Previous to go anywhere. PaginationLink and the numbered items exist for
// the rarer case of a genuinely small, fully-known list — nothing in this
// app is that today.

function Pagination({ className, ...props }: React.ComponentProps<"nav">) {
  return (
    <nav
      aria-label="Pagination"
      data-slot="pagination"
      className={cn("mx-auto flex w-full justify-center", className)}
      {...props}
    />
  )
}

function PaginationContent({ className, ...props }: React.ComponentProps<"ul">) {
  return (
    <ul
      data-slot="pagination-content"
      className={cn("flex flex-row items-center gap-1", className)}
      {...props}
    />
  )
}

function PaginationItem({ ...props }: React.ComponentProps<"li">) {
  return <li data-slot="pagination-item" {...props} />
}

type PaginationLinkProps = {
  isActive?: boolean
} & Pick<React.ComponentProps<typeof Button>, "size"> &
  React.ComponentProps<"a">

function PaginationLink({ className, isActive, size = "icon", ...props }: PaginationLinkProps) {
  return (
    <a
      aria-current={isActive ? "page" : undefined}
      data-slot="pagination-link"
      data-active={isActive}
      className={cn(
        buttonVariants({ variant: isActive ? "outline" : "ghost", size }),
        className
      )}
      {...props}
    />
  )
}

function PaginationPrevious({
  className,
  label,
  ...props
}: React.ComponentProps<typeof Button> & { label: string }) {
  return (
    <Button
      variant="ghost"
      size="default"
      className={cn("gap-1 px-2.5", className)}
      {...props}
    >
      <ChevronLeftIcon className="rtl:-scale-x-100" aria-hidden="true" />
      {label}
    </Button>
  )
}

function PaginationNext({
  className,
  label,
  ...props
}: React.ComponentProps<typeof Button> & { label: string }) {
  return (
    <Button
      variant="ghost"
      size="default"
      className={cn("gap-1 px-2.5", className)}
      {...props}
    >
      {label}
      <ChevronRightIcon className="rtl:-scale-x-100" aria-hidden="true" />
    </Button>
  )
}

function PaginationEllipsis({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      aria-hidden="true"
      data-slot="pagination-ellipsis"
      className={cn("flex size-8 items-center justify-center", className)}
      {...props}
    >
      <MoreHorizontalIcon className="size-4" />
      <span className="sr-only">Plus de pages</span>
    </span>
  )
}

export {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
}
