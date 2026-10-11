import * as React from "react"
import { cn } from "cn"

// No headless primitive: a <table> already carries the semantics a screen
// reader needs (rows, columns, headers) as long as the markup uses real
// <th>/<td> rather than styled <div>s — this file's whole job is to keep
// that true while looking like the rest of the design system.

function Table({ className, ...props }: React.ComponentProps<"table">) {
  return (
    // The scroll container, not the table, gets the overflow: a table wider
    // than its column ever grows the PAGE instead of scrolling in place,
    // which is what breaks a screen at 1024px width, not just this one.
    <div data-slot="table-container" className="relative w-full overflow-x-auto">
      <table
        data-slot="table"
        className={cn("w-full caption-bottom text-sm", className)}
        {...props}
      />
    </div>
  )
}

function TableHeader({ className, ...props }: React.ComponentProps<"thead">) {
  return (
    <thead
      data-slot="table-header"
      className={cn("[&_tr]:border-b [&_tr]:border-shell-line", className)}
      {...props}
    />
  )
}

function TableBody({ className, ...props }: React.ComponentProps<"tbody">) {
  return (
    <tbody
      data-slot="table-body"
      className={cn("[&_tr:last-child]:border-0", className)}
      {...props}
    />
  )
}

function TableFooter({ className, ...props }: React.ComponentProps<"tfoot">) {
  return (
    <tfoot
      data-slot="table-footer"
      className={cn(
        "border-t border-shell-line bg-shell-canvas/50 font-medium [&>tr]:last:border-b-0",
        className
      )}
      {...props}
    />
  )
}

function TableRow({ className, ...props }: React.ComponentProps<"tr">) {
  return (
    <tr
      data-slot="table-row"
      className={cn(
        "border-b border-shell-line transition-colors hover:bg-shell-canvas/50 data-[selected=true]:bg-brand-violet-soft",
        className
      )}
      {...props}
    />
  )
}

function TableHead({ className, ...props }: React.ComponentProps<"th">) {
  return (
    <th
      data-slot="table-head"
      // scope="col" is what ties a data cell back to this header for
      // assistive technology; without it the table reads as an unlabelled
      // grid of numbers.
      scope="col"
      className={cn(
        "h-9 px-3 text-start align-middle text-xs font-medium text-shell-muted whitespace-nowrap",
        "[&:has([role=checkbox])]:pe-0 [&>[role=checkbox]]:translate-y-[2px]",
        className
      )}
      {...props}
    />
  )
}

function TableCell({ className, ...props }: React.ComponentProps<"td">) {
  return (
    <td
      data-slot="table-cell"
      className={cn(
        "p-3 align-middle whitespace-nowrap text-shell-nav",
        "[&:has([role=checkbox])]:pe-0 [&>[role=checkbox]]:translate-y-[2px]",
        className
      )}
      {...props}
    />
  )
}

function TableCaption({ className, ...props }: React.ComponentProps<"caption">) {
  return (
    <caption
      data-slot="table-caption"
      className={cn("mt-3 text-sm text-shell-muted", className)}
      {...props}
    />
  )
}

export { Table, TableHeader, TableBody, TableFooter, TableHead, TableRow, TableCell, TableCaption }
