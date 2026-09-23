"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";

import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * Where a page's content goes, and how its top reads.
 *
 * Every screen in the product uses these two, so the width, the paddings and
 * the distance between a title and what follows are decided once. A page
 * that laid out its own would be the first of two, then of five.
 */
export function PageContainer({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto w-full max-w-content px-4 py-6 sm:px-6 lg:px-8">{children}</div>
  );
}

export interface Crumb {
  label: string;
  href?: string;
}

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  breadcrumb?: readonly Crumb[];
  /** Primary actions, right-aligned on one line with the title. */
  actions?: React.ReactNode;
}

export function PageHeader({ title, subtitle, breadcrumb, actions }: PageHeaderProps) {
  const t = useDictionary();
  return (
    <div className="mb-6">
      {breadcrumb && breadcrumb.length > 0 && (
        // Named in the page's language: a screen reader announcing
        // "Breadcrumb navigation" in a French interface was the one English
        // landmark left.
        <nav aria-label={t.shell.breadcrumb} className="mb-2">
          <ol className="flex flex-wrap items-center gap-1 text-xs text-shell-muted">
            {breadcrumb.map((crumb, index) => (
              <li key={`${crumb.label}-${index}`} className="flex items-center gap-1">
                {index > 0 && <ChevronRight className="size-3" aria-hidden="true" />}
                {crumb.href ? (
                  <Link
                    href={crumb.href}
                    className="rounded transition-colors outline-none hover:text-brand-violet focus-visible:ring-3 focus-visible:ring-brand-violet/40"
                  >
                    {crumb.label}
                  </Link>
                ) : (
                  // The page you are on is not a link to itself.
                  <span aria-current="page">{crumb.label}</span>
                )}
              </li>
            ))}
          </ol>
        </nav>
      )}

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight text-brand-navy">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-shell-muted">{subtitle}</p>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}
