"use client";

import Link from "next/link";
import { ArrowLeft, ChevronRight } from "lucide-react";

import { routes } from "@/config/routes";

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

/**
 * The way back home, at the top left of every page but the home, as the
 * sprint's mockups draw it (LEKA-455): no sidebar to find it in. A page that
 * draws its own header puts it above (Agents et bundles, Activité, an
 * element's page).
 */
export function BackHome({ className }: { className?: string }) {
  const t = useDictionary();
  return (
    <Link
      href={routes.overview()}
      data-testid="back-home"
      className={`inline-flex items-center gap-2 rounded-lg bg-shell-canvas px-3 py-1.5 text-sm text-shell-nav transition-colors outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40 ${className ?? "mb-4"}`}
    >
      <ArrowLeft className="rtl:-scale-x-100 size-4" aria-hidden="true" />
      {t.shell.backHome}
    </Link>
  );
}

export function PageHeader({ title, subtitle, breadcrumb, actions }: PageHeaderProps) {
  const t = useDictionary();
  return (
    <div className="mb-6">
      <BackHome />
      {/* Deeper than a page of its own: where it sits, beside the way back. */}
      {breadcrumb && breadcrumb.length > 2 && (
        // Named in the page's language: a screen reader announcing
        // "Breadcrumb navigation" in a French interface was the one English
        // landmark left.
        <nav aria-label={t.shell.breadcrumb} className="mb-2">
          <ol className="flex flex-wrap items-center gap-1 text-xs text-shell-muted">
            {breadcrumb.map((crumb, index) => (
              <li key={`${crumb.label}-${index}`} className="flex items-center gap-1">
                {index > 0 && <ChevronRight className="rtl:-scale-x-100 size-3" aria-hidden="true" />}
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
          {/* As every mockup draws it: a large, bold title, its line under
              it in the accent's muted violet. */}
          <h1 className="text-[1.75rem] leading-tight font-bold tracking-[-0.02em] text-brand-navy md:text-[2.25rem]">
            {title}
          </h1>
          {subtitle && (
            <p className="mt-1 text-[0.9375rem] text-shell-accent-muted md:text-[1.0625rem]">{subtitle}</p>
          )}
        </div>
        {/* On a phone they wrap, never past the screen's edge (2026-10-27). */}
        {actions && <div className="flex max-w-full shrink-0 flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}
