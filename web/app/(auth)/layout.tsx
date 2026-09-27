import { Instrument_Sans } from "next/font/google";

import { SiteHeader } from "@/components/auth/site-header";

// leka-core.com's typeface. Loaded here, for these screens only: the
// application behind the sign-in keeps its own.
const instrumentSans = Instrument_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

/**
 * The layout the screens before signing in share — sign-in, registration,
 * recovery, confirmation.
 *
 * They are reached from leka-core.com's "Se connecter", and look like the
 * site that sent the person there: its header, its tinted page, its card
 * (AuthCard), its fields and its dark button — the site's own values, from
 * public/style.css, as tokens in globals.css (`site-*`). The application
 * shell — sidebar, workspace switcher — is for the signed-in pages, under
 * (app).
 *
 * The fields and buttons are the design system's own, restyled here rather
 * than forked: every screen below gets the site's 46px fields, its violet
 * focus and its dark submit button without a class of its own.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div
      className={[
        instrumentSans.className,
        "flex min-h-screen flex-col bg-site-mist text-site-ink antialiased",
        // The site's fields (.field input): 46px, a firmer border, a violet
        // focus with a pale halo.
        "[&_[data-slot=input]]:h-[46px] [&_[data-slot=input]]:rounded-[6px] [&_[data-slot=input]]:border-site-rule-strong [&_[data-slot=input]]:bg-white [&_[data-slot=input]]:px-[14px] [&_[data-slot=input]]:text-[15px] [&_[data-slot=input]]:shadow-none",
        "[&_[data-slot=input]:focus-visible]:border-site-violet [&_[data-slot=input]:focus-visible]:ring-[3px] [&_[data-slot=input]:focus-visible]:ring-site-violet-wash",
        "[&_[data-slot=select-trigger]]:h-[46px] [&_[data-slot=select-trigger]]:rounded-[6px] [&_[data-slot=select-trigger]]:border-site-rule-strong [&_[data-slot=select-trigger]]:bg-white [&_[data-slot=select-trigger]]:text-[15px]",
        // Its labels (.field label): small, bold, ink.
        "[&_[data-slot=label]]:text-[13px] [&_[data-slot=label]]:font-semibold [&_[data-slot=label]]:tracking-[-0.01em] [&_[data-slot=label]]:text-site-ink",
        // Its buttons (.btn): 46px; the submit is the dark one that turns
        // violet under the pointer (.btn--primary).
        "[&_[data-slot=button]]:h-[46px] [&_[data-slot=button]]:rounded-[6px] [&_[data-slot=button]]:text-[15px] [&_[data-slot=button]]:font-semibold [&_[data-slot=button]]:tracking-[-0.012em]",
        "[&_button[type=submit]]:bg-site-ink [&_button[type=submit]]:text-white [&_button[type=submit]:hover]:bg-site-violet",
      ].join(" ")}
    >
      {/* The shell's pages title themselves from the route registry; these
          have no registry entry, and no title would show the URL instead. */}
      <title>LEKA</title>
      <SiteHeader />
      <main className="flex-1 px-4 py-14 md:py-24">{children}</main>
    </div>
  );
}
