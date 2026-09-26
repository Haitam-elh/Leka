"use client";

import { ArrowDown, ArrowUp, ArrowUpDown, Inbox } from "lucide-react";
import { useMemo, useState } from "react";

import { cn } from "cn";

import { StatePanel } from "@/components/states/state-panel";
import { PaginationNext, PaginationPrevious } from "@/components/ui/pagination";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";

export interface KnowledgeColumn<T> {
  id: string;
  header: string;
  cell: (row: T) => React.ReactNode;
  /** Makes the column sortable, on this value. */
  sortValue?: (row: T) => string | number | null | undefined;
  align?: "start" | "end";
  className?: string;
}

export interface KnowledgeTableProps<T> {
  columns: readonly KnowledgeColumn<T>[];
  rows: readonly T[];
  rowKey: (row: T) => string;
  /** What the table is. Read first by a screen reader; hidden unless showCaption. */
  caption: string;
  showCaption?: boolean;
  loading?: boolean;
  empty?: { title?: string; description?: string; action?: React.ReactNode };
  onRowClick?: (row: T) => void;
  /** 25 by default. */
  pageSize?: number;
  initialSort?: { id: string; direction: "asc" | "desc" };
  className?: string;
}

type Sort = { id: string; direction: "asc" | "desc" } | null;

function compare(a: string | number | null | undefined, b: string | number | null | undefined) {
  // Missing values last, whichever way the column is sorted.
  if (a === null || a === undefined) return b === null || b === undefined ? 0 : 1;
  if (b === null || b === undefined) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

/**
 * A table of anything, sorted and paged in the browser (LEKA-340).
 *
 * Built on the design system's Table (LEKA-339) — TanStack Table is not a
 * dependency, and client-side sort and paging need none. Meant for up to a
 * couple of hundred rows; past that, page on the server (the API's lists
 * are cursor-paged) and hand this one page at a time. It still copes with
 * 500: only a page is ever rendered.
 */
export function KnowledgeTable<T>({
  columns,
  rows,
  rowKey,
  caption,
  showCaption = false,
  loading = false,
  empty,
  onRowClick,
  pageSize = 25,
  initialSort,
  className,
}: KnowledgeTableProps<T>) {
  const t = useDictionary();
  const [sort, setSort] = useState<Sort>(initialSort ?? null);
  const [page, setPage] = useState(0);

  const sorted = useMemo(() => {
    const column = sort ? columns.find((candidate) => candidate.id === sort.id) : undefined;
    if (!sort || !column?.sortValue) return rows;
    const value = column.sortValue;
    const sign = sort.direction === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const va = value(a);
      const vb = value(b);
      if (va === null || va === undefined || vb === null || vb === undefined)
        return compare(va, vb);
      return sign * compare(va, vb);
    });
  }, [rows, columns, sort]);

  const size = Math.max(1, pageSize);
  const pages = Math.max(1, Math.ceil(sorted.length / size));
  const current = Math.min(page, pages - 1);
  const shown = sorted.slice(current * size, current * size + size);

  function toggle(id: string) {
    setPage(0);
    setSort((previous) =>
      previous?.id === id && previous.direction === "asc"
        ? { id, direction: "desc" }
        : { id, direction: "asc" },
    );
  }

  if (!loading && rows.length === 0) {
    return (
      <StatePanel
        icon={Inbox}
        size="section"
        headingLevel={3}
        title={empty?.title ?? t.knowledge.table.emptyTitle}
        description={empty?.description}
        actions={empty?.action}
        className={className}
      />
    );
  }

  return (
    <div data-slot="knowledge-table" className={cn("flex flex-col gap-3", className)}>
      <Table aria-busy={loading || undefined}>
        <TableCaption className={cn(!showCaption && "sr-only")}>{caption}</TableCaption>
        <TableHeader>
          <TableRow>
            {columns.map((column) => {
              const active = sort?.id === column.id;
              const Icon = !active ? ArrowUpDown : sort.direction === "asc" ? ArrowUp : ArrowDown;
              return (
                <TableHead
                  key={column.id}
                  aria-sort={
                    column.sortValue
                      ? active
                        ? sort.direction === "asc"
                          ? "ascending"
                          : "descending"
                        : "none"
                      : undefined
                  }
                  className={cn(column.align === "end" && "text-right", column.className)}
                >
                  {column.sortValue ? (
                    <button
                      type="button"
                      onClick={() => toggle(column.id)}
                      aria-label={fill(t.knowledge.table.sortBy, { column: column.header })}
                      className={cn(
                        "inline-flex items-center gap-1 rounded outline-none hover:text-shell-nav focus-visible:ring-2 focus-visible:ring-brand-violet/40",
                        active && "text-shell-nav",
                      )}
                    >
                      {column.header}
                      <Icon aria-hidden="true" className="size-3" />
                    </button>
                  ) : (
                    column.header
                  )}
                </TableHead>
              );
            })}
          </TableRow>
        </TableHeader>
        <TableBody>
          {loading
            ? Array.from({ length: 5 }, (_, index) => (
                <TableRow key={index} aria-hidden="true">
                  {columns.map((column) => (
                    <TableCell key={column.id}>
                      <Skeleton className="h-4 w-full max-w-40" />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            : shown.map((row) => (
                <TableRow
                  key={rowKey(row)}
                  tabIndex={onRowClick ? 0 : undefined}
                  data-clickable={onRowClick ? "true" : undefined}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  onKeyDown={
                    onRowClick
                      ? (event) => {
                          if (event.key !== "Enter" && event.key !== " ") return;
                          event.preventDefault();
                          onRowClick(row);
                        }
                      : undefined
                  }
                  className={cn(
                    onRowClick &&
                      "cursor-pointer outline-none focus-visible:bg-brand-violet-soft/60 focus-visible:ring-2 focus-visible:ring-brand-violet/40 focus-visible:ring-inset",
                  )}
                >
                  {columns.map((column) => (
                    <TableCell
                      key={column.id}
                      className={cn(column.align === "end" && "text-right", column.className)}
                    >
                      {column.cell(row)}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
        </TableBody>
      </Table>

      {loading ? (
        <p role="status" className="sr-only">
          {t.knowledge.table.loading}
        </p>
      ) : pages > 1 ? (
        <nav
          aria-label={caption}
          className="flex flex-wrap items-center justify-between gap-2 text-xs text-shell-muted"
        >
          <span>{fill(t.knowledge.table.rows, { count: rows.length })}</span>
          <div className="flex items-center gap-2">
            <PaginationPrevious
              label={t.knowledge.table.previous}
              disabled={current === 0}
              onClick={() => setPage(current - 1)}
            />
            <span aria-live="polite" className="tabular-nums">
              {fill(t.knowledge.table.page, { page: current + 1, pages })}
            </span>
            <PaginationNext
              label={t.knowledge.table.next}
              disabled={current >= pages - 1}
              onClick={() => setPage(current + 1)}
            />
          </div>
        </nav>
      ) : null}
    </div>
  );
}
