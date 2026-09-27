"use client";

import { cn } from "cn";

import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * The card every screen before signing in sits in — leka-core.com's
 * (.form-card in public/style.css): white, a hairline, a soft deep shadow,
 * the "Espace client" eyebrow with the logo's chevron, a large title and
 * a line under it, a footer set apart by a rule.
 *
 * The title is the page's <h1>: the header above is the site's, with a
 * logo and no heading, so this is what a screen reader lands on — and what
 * the browser tests find.
 *
 * `wide` for the forms that ask more than an address and a password — the
 * registration's two columns — as the site's own longer forms are.
 */
export function AuthCard({
  title,
  description,
  children,
  footer,
  wide = false,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  wide?: boolean;
}) {
  const t = useDictionary();

  return (
    <section
      className={cn(
        "mx-auto w-full rounded-[20px] border border-site-rule bg-white p-7 shadow-[0_2px_4px_rgba(10,15,43,.04),0_24px_60px_rgba(10,15,43,.10)] sm:p-12",
        wide ? "max-w-[600px]" : "max-w-[420px]",
      )}
    >
      <div className="mb-8">
        <p className="mb-3 inline-flex items-center gap-2.5 text-[13px] font-semibold tracking-[-0.01em] text-site-violet">
          <span
            aria-hidden="true"
            className="h-[10px] w-[13px] flex-none bg-current [clip-path:polygon(50%_0,100%_100%,76%_100%,50%_47%,24%_100%,0_100%)]"
          />
          {t.auth.eyebrow}
        </p>
        <h1 className="text-[26px] leading-[1.15] font-semibold tracking-[-0.03em] text-site-ink sm:text-[30px]">
          {title}
        </h1>
        {description ? (
          <p className="mt-3 text-[15px] leading-normal tracking-[-0.01em] text-site-slate">
            {description}
          </p>
        ) : null}
      </div>
      <div className="space-y-4">{children}</div>
      {footer ? (
        <div className="mt-6 border-t border-site-rule pt-6 text-center text-sm text-site-slate [&_a]:font-semibold [&_a]:text-site-violet [&_a]:no-underline">
          {footer}
        </div>
      ) : null}
    </section>
  );
}
