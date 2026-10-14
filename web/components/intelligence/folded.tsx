"use client";

import { ChevronDown } from "lucide-react";

import { cn } from "cn";

/**
 * What a page holds for who looks for it, folded under one line that says
 * what it is (2026-10-14, the product call: « les blocs empilés qu'on ne lit
 * pas », « la longue colonne de droite »). The answer and what is delivered
 * are read first; the rest is one click away, never gone.
 */
export function Folded({
  title,
  hint,
  testId,
  className,
  children,
}: {
  title: string;
  /** What is inside, in one line. */
  hint?: string;
  testId?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <details
      className={cn("group rounded-xl border border-shell-line bg-white", className)}
      data-testid={testId}
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 rounded-xl px-5 py-4 outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40 [&::-webkit-details-marker]:hidden">
        <span className="min-w-0">
          <span className="block text-[0.9375rem] font-semibold text-brand-navy">{title}</span>
          {hint ? <span className="block text-[0.8125rem] text-shell-muted">{hint}</span> : null}
        </span>
        <ChevronDown
          className="size-4 shrink-0 text-shell-muted transition-transform group-open:rotate-180"
          aria-hidden="true"
        />
      </summary>
      <div className="space-y-4 border-t border-shell-line p-4">{children}</div>
    </details>
  );
}
